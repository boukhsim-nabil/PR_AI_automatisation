from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.authorization import MembershipAuthorization, require_permission
from app.core.config import settings
from app.db.models import (
    AttachmentScanStatus,
    Contact,
    Conversation,
    Membership,
    Message,
    MessageAttachment,
    MessageContentType,
    MessageDirection,
    MessageSenderType,
    MessageStatus,
    User,
)
from app.db.session import get_db
from app.schemas.inbox import (
    MessageApiRead,
    MessageAttachmentSummary,
    MessageDraftPatch,
    MessageDraftRequest,
    MessagePage,
    MessageSenderSummary,
    ReplyMessageSummary,
    SimulatedInboundRequest,
)
from app.services.audit import AuditEvent, AuditService
from app.services.inbox import ConversationReadOnlyError, ConversationService, InboxDomainError
from app.services.inbox_messages import MessageApiService

router = APIRouter(prefix="/inbox", tags=["inbox-messages"])
DatabaseSession = Annotated[Session, Depends(get_db)]
InboxReader = Annotated[
    MembershipAuthorization,
    Depends(require_permission("inbox.read")),
]
InboxReplier = Annotated[
    MembershipAuthorization,
    Depends(require_permission("inbox.reply")),
]
InboxSimulator = Annotated[
    MembershipAuthorization,
    Depends(require_permission("inbox.simulate_inbound")),
]


def _audit(
    request: Request,
    access: MembershipAuthorization,
    *,
    action: str,
    message_id: UUID,
    metadata: dict[str, Any] | None = None,
) -> None:
    AuditService.record(
        request.scope,
        AuditEvent(
            company_id=access.company.id,
            actor_user_id=access.user.id,
            actor_membership_id=access.membership.id,
            action=action,
            result="success",
            resource_type="message",
            resource_id=str(message_id),
            metadata=metadata,
        ),
    )


def _hidden(
    request: Request,
    access: MembershipAuthorization,
    resource_id: UUID,
    *,
    resource_type: str,
) -> None:
    AuditService.record(
        request.scope,
        AuditEvent(
            company_id=access.company.id,
            actor_user_id=access.user.id,
            actor_membership_id=access.membership.id,
            action="security.cross_tenant",
            result="denied",
            resource_type=resource_type,
            resource_id=str(resource_id),
            metadata={"reason": "resource_not_visible"},
        ),
    )


def _conversation_or_404(
    db: Session,
    request: Request,
    access: MembershipAuthorization,
    conversation_id: UUID,
) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.company_id == access.company.id,
        )
    )
    if conversation is None:
        _hidden(request, access, conversation_id, resource_type="conversation")
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _message_or_404(
    db: Session,
    request: Request,
    access: MembershipAuthorization,
    message_id: UUID,
) -> Message:
    message = db.scalar(
        select(Message).where(
            Message.id == message_id,
            Message.company_id == access.company.id,
            Message.discarded_at.is_(None),
        )
    )
    if message is None:
        _hidden(request, access, message_id, resource_type="message")
        raise HTTPException(status_code=404, detail="Message not found")
    return message


def _ensure_author(message: Message, access: MembershipAuthorization) -> None:
    if message.sender_membership_id != access.membership.id:
        raise HTTPException(status_code=403, detail="Only the draft author can change it")


def _raise_domain_error(exc: InboxDomainError) -> None:
    code = 409 if isinstance(exc, ConversationReadOnlyError) else 422
    raise HTTPException(status_code=code, detail=str(exc)) from exc


def _encode_cursor(
    message: Message,
    *,
    conversation_id: UUID,
    content_type: MessageContentType | None,
) -> str:
    raw = json.dumps(
        {
            "conversation_id": str(conversation_id),
            "content_type": content_type.value if content_type else None,
            "created_at": message.created_at.isoformat(),
            "id": str(message.id),
        },
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(
    value: str,
    *,
    conversation_id: UUID,
    content_type: MessageContentType | None,
) -> tuple[datetime, UUID]:
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(value + padding))
        expected_type = content_type.value if content_type else None
        if (
            payload["conversation_id"] != str(conversation_id)
            or payload["content_type"] != expected_type
        ):
            raise ValueError
        created_at = datetime.fromisoformat(payload["created_at"])
        if created_at.tzinfo is None:
            raise ValueError
        return created_at, UUID(payload["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid pagination cursor") from exc


def _serialize_messages(db: Session, messages: list[Message]) -> list[MessageApiRead]:
    if not messages:
        return []
    membership_ids = {item.sender_membership_id for item in messages if item.sender_membership_id}
    contact_ids = {item.sender_contact_id for item in messages if item.sender_contact_id}
    reply_ids = {item.reply_to_message_id for item in messages if item.reply_to_message_id}
    message_ids = {item.id for item in messages}

    members: dict[UUID, tuple[Membership, User]] = {}
    if membership_ids:
        members = {
            membership.id: (membership, user)
            for membership, user in db.execute(
                select(Membership, User)
                .join(User, User.id == Membership.user_id)
                .where(Membership.id.in_(membership_ids))
            ).all()
        }
    contacts = (
        {item.id: item for item in db.scalars(select(Contact).where(Contact.id.in_(contact_ids)))}
        if contact_ids
        else {}
    )
    replies = (
        {item.id: item for item in db.scalars(select(Message).where(Message.id.in_(reply_ids)))}
        if reply_ids
        else {}
    )
    attachment_rows = db.scalars(
        select(MessageAttachment)
        .where(MessageAttachment.message_id.in_(message_ids))
        .order_by(MessageAttachment.created_at.asc())
    ).all()
    attachments: dict[UUID, list[MessageAttachment]] = {}
    for attachment in attachment_rows:
        attachments.setdefault(attachment.message_id, []).append(attachment)

    result = []
    for message in messages:
        member = members.get(message.sender_membership_id) if message.sender_membership_id else None
        contact = contacts.get(message.sender_contact_id) if message.sender_contact_id else None
        display_name = None
        if member:
            display_name = member[1].display_name
        elif contact:
            display_name = " ".join(
                part for part in (contact.first_name, contact.last_name) if part
            )
        elif message.sender_type == MessageSenderType.SYSTEM:
            display_name = "System"
        reply = replies.get(message.reply_to_message_id) if message.reply_to_message_id else None
        result.append(
            MessageApiRead(
                id=message.id,
                conversation_id=message.conversation_id,
                direction=MessageDirection(message.direction),
                sender=MessageSenderSummary(
                    sender_type=MessageSenderType(message.sender_type),
                    membership_id=message.sender_membership_id,
                    contact_id=message.sender_contact_id,
                    display_name=display_name or None,
                    identifier=message.sender_identifier,
                ),
                content_type=MessageContentType(message.content_type),
                is_system_event=message.content_type == MessageContentType.SYSTEM_EVENT,
                subject=message.subject,
                body_text=message.body_text,
                body_html=message.body_html,
                html_requires_sanitization=message.body_html is not None,
                status=MessageStatus(message.status),
                sent_at=message.sent_at,
                received_at=message.received_at,
                created_at=message.created_at,
                updated_at=message.updated_at,
                reply_to_message=(
                    ReplyMessageSummary(
                        id=reply.id,
                        direction=MessageDirection(reply.direction),
                        content_type=MessageContentType(reply.content_type),
                        body_preview=(reply.body_text or reply.subject or "")[:200] or None,
                        created_at=reply.created_at,
                    )
                    if reply
                    else None
                ),
                attachments=[
                    MessageAttachmentSummary(
                        id=attachment.id,
                        filename=attachment.filename,
                        mime_type=attachment.mime_type,
                        size_bytes=attachment.size_bytes,
                        scan_status=AttachmentScanStatus(attachment.scan_status),
                        created_at=attachment.created_at,
                    )
                    for attachment in attachments.get(message.id, [])
                ],
            )
        )
    return result


@router.get("/conversations/{conversation_id}/messages", response_model=MessagePage)
def list_messages(
    conversation_id: UUID,
    request: Request,
    access: InboxReader,
    db: DatabaseSession,
    page_size: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, min_length=1, max_length=1000),
    content_type: MessageContentType | None = None,
) -> MessagePage:
    _conversation_or_404(db, request, access, conversation_id)
    clauses = [
        Message.company_id == access.company.id,
        Message.conversation_id == conversation_id,
        Message.discarded_at.is_(None),
    ]
    if content_type is not None:
        clauses.append(Message.content_type == content_type)
    if cursor:
        created_at, message_id = _decode_cursor(
            cursor,
            conversation_id=conversation_id,
            content_type=content_type,
        )
        clauses.append(
            or_(
                Message.created_at > created_at,
                and_(Message.created_at == created_at, Message.id > message_id),
            )
        )
    rows = list(
        db.scalars(
            select(Message)
            .where(*clauses)
            .order_by(Message.created_at.asc(), Message.id.asc())
            .limit(page_size + 1)
        )
    )
    has_more = len(rows) > page_size
    page_rows = rows[:page_size]
    return MessagePage(
        items=_serialize_messages(db, page_rows),
        next_cursor=(
            _encode_cursor(
                page_rows[-1],
                conversation_id=conversation_id,
                content_type=content_type,
            )
            if has_more and page_rows
            else None
        ),
        has_more=has_more,
        page_size=page_size,
    )


@router.post(
    "/conversations/{conversation_id}/drafts",
    response_model=MessageApiRead,
    status_code=status.HTTP_201_CREATED,
)
def create_draft(
    conversation_id: UUID,
    payload: MessageDraftRequest,
    request: Request,
    access: InboxReplier,
    db: DatabaseSession,
) -> MessageApiRead:
    conversation = _conversation_or_404(db, request, access, conversation_id)
    try:
        message = MessageApiService.create_draft(
            db,
            conversation,
            payload,
            sender_membership_id=access.membership.id,
        )
        db.flush()
    except InboxDomainError as exc:
        _raise_domain_error(exc)
    _audit(request, access, action="inbox.message.draft_created", message_id=message.id)
    return _serialize_messages(db, [message])[0]


@router.patch("/messages/{message_id}/draft", response_model=MessageApiRead)
def update_draft(
    message_id: UUID,
    payload: MessageDraftPatch,
    request: Request,
    access: InboxReplier,
    db: DatabaseSession,
) -> MessageApiRead:
    message = _message_or_404(db, request, access, message_id)
    _ensure_author(message, access)
    conversation = _conversation_or_404(db, request, access, message.conversation_id)
    try:
        ConversationService.ensure_writable(conversation)
        MessageApiService.update_draft(message, payload)
        db.flush()
    except InboxDomainError as exc:
        _raise_domain_error(exc)
    _audit(request, access, action="inbox.message.draft_updated", message_id=message.id)
    return _serialize_messages(db, [message])[0]


@router.delete("/messages/{message_id}/draft", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft(
    message_id: UUID,
    request: Request,
    access: InboxReplier,
    db: DatabaseSession,
) -> Response:
    message = _message_or_404(db, request, access, message_id)
    _ensure_author(message, access)
    conversation = _conversation_or_404(db, request, access, message.conversation_id)
    try:
        ConversationService.ensure_writable(conversation)
        MessageApiService.discard_draft(message)
        db.flush()
    except InboxDomainError as exc:
        _raise_domain_error(exc)
    _audit(request, access, action="inbox.message.draft_discarded", message_id=message.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/messages/{message_id}/queue", response_model=MessageApiRead)
def queue_message(
    message_id: UUID,
    request: Request,
    access: InboxReplier,
    db: DatabaseSession,
) -> MessageApiRead:
    message = _message_or_404(db, request, access, message_id)
    _ensure_author(message, access)
    conversation = _conversation_or_404(db, request, access, message.conversation_id)
    try:
        MessageApiService.queue(conversation, message)
        db.flush()
    except InboxDomainError as exc:
        _raise_domain_error(exc)
    _audit(request, access, action="inbox.message.queued", message_id=message.id)
    return _serialize_messages(db, [message])[0]


@router.post("/messages/{message_id}/send", response_model=MessageApiRead)
def send_message(
    message_id: UUID,
    request: Request,
    access: InboxReplier,
    db: DatabaseSession,
) -> MessageApiRead:
    message = _message_or_404(db, request, access, message_id)
    _ensure_author(message, access)
    conversation = _conversation_or_404(db, request, access, message.conversation_id)
    try:
        MessageApiService.send(db, conversation, message)
        db.flush()
    except InboxDomainError as exc:
        _raise_domain_error(exc)
    _audit(request, access, action="inbox.message.sent", message_id=message.id)
    return _serialize_messages(db, [message])[0]


@router.post(
    "/messages/simulate-inbound",
    response_model=MessageApiRead,
    status_code=status.HTTP_201_CREATED,
)
def simulate_inbound(
    payload: SimulatedInboundRequest,
    response: Response,
    request: Request,
    access: InboxSimulator,
    db: DatabaseSession,
) -> MessageApiRead:
    if settings.environment.strip().lower() not in {"development", "test", "e2e"}:
        raise HTTPException(status_code=404, detail="Not found")
    conversation = _conversation_or_404(db, request, access, payload.conversation_id)
    if payload.external_message_id:
        existing = db.scalar(
            select(Message).where(
                Message.company_id == access.company.id,
                Message.external_message_id == payload.external_message_id,
                Message.discarded_at.is_(None),
            )
        )
        if existing is not None:
            if existing.conversation_id != conversation.id:
                raise HTTPException(status_code=409, detail="External message id conflict")
            response.status_code = status.HTTP_200_OK
            return _serialize_messages(db, [existing])[0]

    sender_contact_id = payload.sender_contact_id or conversation.contact_id
    sender_identifier = payload.sender_identifier
    if sender_contact_id is not None:
        contact = db.scalar(
            select(Contact).where(
                Contact.id == sender_contact_id,
                Contact.company_id == access.company.id,
            )
        )
        if contact is None or (
            conversation.contact_id is not None and contact.id != conversation.contact_id
        ):
            _hidden(request, access, sender_contact_id, resource_type="contact")
            raise HTTPException(status_code=422, detail="Invalid simulated sender")
        sender_identifier = None
    elif not sender_identifier:
        raise HTTPException(status_code=422, detail="A controlled sender identity is required")

    try:
        with db.begin_nested():
            message = MessageApiService.receive(
                db,
                conversation,
                payload,
                sender_contact_id=sender_contact_id,
                sender_identifier=sender_identifier,
            )
            db.flush()
    except InboxDomainError as exc:
        _raise_domain_error(exc)
    except IntegrityError as exc:
        if payload.external_message_id:
            existing = db.scalar(
                select(Message).where(
                    Message.company_id == access.company.id,
                    Message.external_message_id == payload.external_message_id,
                    Message.discarded_at.is_(None),
                )
            )
            if existing is not None and existing.conversation_id == conversation.id:
                response.status_code = status.HTTP_200_OK
                return _serialize_messages(db, [existing])[0]
        raise HTTPException(status_code=409, detail="External message id conflict") from exc
    _audit(
        request,
        access,
        action="inbox.message.received_simulated",
        message_id=message.id,
    )
    return _serialize_messages(db, [message])[0]


@router.get("/messages/{message_id}", response_model=MessageApiRead)
def read_message(
    message_id: UUID,
    request: Request,
    access: InboxReader,
    db: DatabaseSession,
) -> MessageApiRead:
    message = _message_or_404(db, request, access, message_id)
    return _serialize_messages(db, [message])[0]

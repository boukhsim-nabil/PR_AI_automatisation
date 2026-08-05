from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.api.authorization import MembershipAuthorization, require_permission
from app.db.models import (
    Contact,
    Conversation,
    ConversationChannel,
    ConversationParticipant,
    ConversationParticipantType,
    ConversationPriority,
    ConversationStatus,
    ConversationTag,
    ConversationTagLink,
    Lead,
    Membership,
    Message,
    MessageContentType,
    MessageDirection,
    MessageSenderType,
    MessageStatus,
    User,
)
from app.db.session import get_db
from app.schemas.inbox import (
    AssignedMemberSummary,
    ContactSummary,
    ConversationAssign,
    ConversationCreate,
    ConversationDetail,
    ConversationFilters,
    ConversationListItem,
    ConversationPage,
    ConversationPriorityChange,
    ConversationRead,
    ConversationSortField,
    ConversationStatusChange,
    ConversationUpdate,
    LeadSummary,
    MessageSummary,
    ParticipantSummary,
    SortDirection,
    TagRead,
)
from app.services.audit import AuditEvent, AuditService
from app.services.inbox import ConversationReadOnlyError, ConversationService, InboxDomainError
from app.services.inbox_conversations import (
    ConversationManagementService,
    InvalidConversationTransitionError,
)

router = APIRouter(prefix="/inbox/conversations", tags=["inbox-conversations"])
DatabaseSession = Annotated[Session, Depends(get_db)]
InboxReader = Annotated[
    MembershipAuthorization,
    Depends(require_permission("inbox.read")),
]
InboxCreator = Annotated[
    MembershipAuthorization,
    Depends(require_permission("inbox.create")),
]
InboxAssigner = Annotated[
    MembershipAuthorization,
    Depends(require_permission("inbox.assign")),
]
InboxStatusEditor = Annotated[
    MembershipAuthorization,
    Depends(require_permission("inbox.update_status")),
]
InboxPriorityEditor = Annotated[
    MembershipAuthorization,
    Depends(require_permission("inbox.manage_priority")),
]
InboxArchiver = Annotated[
    MembershipAuthorization,
    Depends(require_permission("inbox.archive")),
]
InboxTakeover = Annotated[
    MembershipAuthorization,
    Depends(require_permission("inbox.takeover")),
]


def _audit(
    request: Request,
    access: MembershipAuthorization,
    *,
    action: str,
    conversation_id: UUID,
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
            resource_type="conversation",
            resource_id=str(conversation_id),
            metadata=metadata,
        ),
    )


def _hidden_resource(
    request: Request,
    access: MembershipAuthorization,
    resource_id: UUID,
    *,
    resource_type: str = "conversation",
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
        _hidden_resource(request, access, conversation_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


def _contact_summary(contact: Contact | None) -> ContactSummary | None:
    if contact is None:
        return None
    return ContactSummary(
        id=contact.id,
        first_name=contact.first_name,
        last_name=contact.last_name,
        email=contact.email,
        phone=contact.phone,
        organization_name=contact.organization_name,
    )


def _lead_summary(lead: Lead | None) -> LeadSummary | None:
    if lead is None:
        return None
    return LeadSummary(id=lead.id, title=lead.title, status=lead.status, priority=lead.priority)


def _member_summary(
    membership: Membership | None,
    user: User | None,
) -> AssignedMemberSummary | None:
    if membership is None or user is None:
        return None
    return AssignedMemberSummary(
        membership_id=membership.id,
        display_name=user.display_name,
        email=user.email,
    )


def _list_item(
    conversation: Conversation,
    contact: Contact | None = None,
    lead: Lead | None = None,
    membership: Membership | None = None,
    user: User | None = None,
) -> ConversationListItem:
    return ConversationListItem(
        id=conversation.id,
        contact_id=conversation.contact_id,
        lead_id=conversation.lead_id,
        channel=ConversationChannel(conversation.channel),
        subject=conversation.subject,
        status=ConversationStatus(conversation.status),
        priority=ConversationPriority(conversation.priority),
        assigned_membership_id=conversation.assigned_membership_id,
        human_takeover=conversation.human_takeover,
        unread_count=conversation.unread_count,
        last_message_at=conversation.last_message_at,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        assigned_member=_member_summary(membership, user),
        contact=_contact_summary(contact),
        lead=_lead_summary(lead),
    )


def _read(conversation: Conversation) -> ConversationRead:
    item = _list_item(conversation)
    return ConversationRead(
        **item.model_dump(),
        external_conversation_id=conversation.external_conversation_id,
        ai_enabled=conversation.ai_enabled,
        first_message_at=conversation.first_message_at,
        resolved_at=conversation.resolved_at,
        closed_at=conversation.closed_at,
        archived_at=conversation.archived_at,
    )


def _encode_cursor(
    timestamp: datetime,
    item_id: UUID,
    filters: ConversationFilters,
) -> str:
    raw = json.dumps(
        {
            "timestamp": timestamp.isoformat(),
            "id": str(item_id),
            "sort_by": filters.sort_by.value,
            "sort_direction": filters.sort_direction.value,
        },
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str, filters: ConversationFilters) -> tuple[datetime, UUID]:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
        if (
            payload["sort_by"] != filters.sort_by.value
            or payload["sort_direction"] != filters.sort_direction.value
        ):
            raise ValueError
        timestamp = datetime.fromisoformat(payload["timestamp"])
        if timestamp.tzinfo is None:
            raise ValueError
        return timestamp, UUID(payload["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid pagination cursor") from exc


def _raise_domain_error(exc: InboxDomainError) -> None:
    code = status.HTTP_409_CONFLICT if isinstance(exc, ConversationReadOnlyError) else 422
    raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreate,
    request: Request,
    access: InboxCreator,
    db: DatabaseSession,
) -> ConversationRead:
    contact = None
    if payload.contact_id is not None:
        contact = db.scalar(
            select(Contact).where(
                Contact.id == payload.contact_id,
                Contact.company_id == access.company.id,
            )
        )
        if contact is None:
            _hidden_resource(
                request,
                access,
                payload.contact_id,
                resource_type="contact",
            )
            raise HTTPException(status_code=422, detail="Invalid contact")

    lead = None
    contact_id = payload.contact_id
    if payload.lead_id is not None:
        lead = db.scalar(
            select(Lead).where(
                Lead.id == payload.lead_id,
                Lead.company_id == access.company.id,
            )
        )
        if lead is None:
            _hidden_resource(
                request,
                access,
                payload.lead_id,
                resource_type="lead",
            )
            raise HTTPException(status_code=422, detail="Invalid lead")
        if contact_id is not None and lead.contact_id != contact_id:
            raise HTTPException(status_code=422, detail="Lead and contact are inconsistent")
        contact_id = lead.contact_id

    conversation = Conversation(
        company_id=access.company.id,
        contact_id=contact_id,
        lead_id=payload.lead_id,
        channel=payload.channel,
        subject=payload.subject,
        priority=payload.priority,
        created_by_membership_id=access.membership.id,
    )
    db.add(conversation)
    try:
        ConversationService.assign(db, conversation, payload.assigned_membership_id)
        db.flush()
    except InboxDomainError as exc:
        if payload.assigned_membership_id is not None:
            visible_membership = db.scalar(
                select(Membership.id).where(
                    Membership.id == payload.assigned_membership_id,
                    Membership.company_id == access.company.id,
                )
            )
            if visible_membership is None:
                _hidden_resource(
                    request,
                    access,
                    payload.assigned_membership_id,
                    resource_type="membership",
                )
        _raise_domain_error(exc)
    _audit(
        request,
        access,
        action="inbox.conversation.created",
        conversation_id=conversation.id,
    )
    return _read(conversation)


@router.get("", response_model=ConversationPage)
def list_conversations(
    access: InboxReader,
    db: DatabaseSession,
    filters: Annotated[ConversationFilters, Query()],
) -> ConversationPage:
    clauses = [Conversation.company_id == access.company.id]
    if filters.channel is not None:
        clauses.append(Conversation.channel == filters.channel)
    if filters.status is not None:
        clauses.append(Conversation.status == filters.status)
    if filters.priority is not None:
        clauses.append(Conversation.priority == filters.priority)
    if filters.assigned_membership_id is not None:
        clauses.append(Conversation.assigned_membership_id == filters.assigned_membership_id)
    if filters.contact_id is not None:
        clauses.append(Conversation.contact_id == filters.contact_id)
    if filters.lead_id is not None:
        clauses.append(Conversation.lead_id == filters.lead_id)
    if filters.human_takeover is not None:
        clauses.append(Conversation.human_takeover.is_(filters.human_takeover))
    if filters.unread_only:
        clauses.append(Conversation.unread_count > 0)
    if filters.created_from is not None:
        clauses.append(Conversation.created_at >= filters.created_from)
    if filters.created_to is not None:
        clauses.append(Conversation.created_at <= filters.created_to)
    if filters.search:
        pattern = f"%{filters.search}%"
        clauses.append(
            or_(
                Conversation.subject.ilike(pattern),
                Contact.first_name.ilike(pattern),
                Contact.last_name.ilike(pattern),
                Contact.email.ilike(pattern),
                Contact.phone.ilike(pattern),
                Contact.organization_name.ilike(pattern),
                Lead.title.ilike(pattern),
            )
        )

    sort_column = (
        func.coalesce(Conversation.last_message_at, Conversation.created_at)
        if filters.sort_by is ConversationSortField.LAST_MESSAGE_AT
        else Conversation.created_at
    )
    if filters.cursor:
        cursor_time, cursor_id = _decode_cursor(filters.cursor, filters)
        if filters.sort_direction is SortDirection.ASC:
            clauses.append(
                or_(
                    sort_column > cursor_time,
                    and_(sort_column == cursor_time, Conversation.id > cursor_id),
                )
            )
        else:
            clauses.append(
                or_(
                    sort_column < cursor_time,
                    and_(sort_column == cursor_time, Conversation.id < cursor_id),
                )
            )

    ordering = (
        (sort_column.asc(), Conversation.id.asc())
        if filters.sort_direction is SortDirection.ASC
        else (sort_column.desc(), Conversation.id.desc())
    )
    rows = db.execute(
        select(Conversation, Contact, Lead, Membership, User)
        .outerjoin(
            Contact,
            and_(
                Contact.company_id == Conversation.company_id,
                Contact.id == Conversation.contact_id,
            ),
        )
        .outerjoin(
            Lead,
            and_(Lead.company_id == Conversation.company_id, Lead.id == Conversation.lead_id),
        )
        .outerjoin(
            Membership,
            and_(
                Membership.company_id == Conversation.company_id,
                Membership.id == Conversation.assigned_membership_id,
            ),
        )
        .outerjoin(User, User.id == Membership.user_id)
        .where(*clauses)
        .order_by(*ordering)
        .limit(filters.page_size + 1)
    ).all()
    has_more = len(rows) > filters.page_size
    page_rows = rows[: filters.page_size]
    items = [_list_item(*row) for row in page_rows]
    next_cursor = None
    if has_more and page_rows:
        last_conversation = page_rows[-1][0]
        timestamp = (
            last_conversation.last_message_at or last_conversation.created_at
            if filters.sort_by is ConversationSortField.LAST_MESSAGE_AT
            else last_conversation.created_at
        )
        next_cursor = _encode_cursor(timestamp, last_conversation.id, filters)
    return ConversationPage(
        items=items,
        next_cursor=next_cursor,
        has_more=has_more,
        page_size=filters.page_size,
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
def read_conversation(
    conversation_id: UUID,
    request: Request,
    access: InboxReader,
    db: DatabaseSession,
) -> ConversationDetail:
    row = db.execute(
        select(Conversation, Contact, Lead, Membership, User)
        .outerjoin(
            Contact,
            and_(
                Contact.company_id == Conversation.company_id,
                Contact.id == Conversation.contact_id,
            ),
        )
        .outerjoin(
            Lead,
            and_(Lead.company_id == Conversation.company_id, Lead.id == Conversation.lead_id),
        )
        .outerjoin(
            Membership,
            and_(
                Membership.company_id == Conversation.company_id,
                Membership.id == Conversation.assigned_membership_id,
            ),
        )
        .outerjoin(User, User.id == Membership.user_id)
        .where(
            Conversation.id == conversation_id,
            Conversation.company_id == access.company.id,
        )
    ).one_or_none()
    if row is None:
        _hidden_resource(request, access, conversation_id)
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation, contact, lead, membership, user = row
    participants = db.scalars(
        select(ConversationParticipant)
        .where(
            ConversationParticipant.company_id == access.company.id,
            ConversationParticipant.conversation_id == conversation.id,
        )
        .order_by(ConversationParticipant.created_at.asc())
    ).all()
    tags = db.scalars(
        select(ConversationTag)
        .join(
            ConversationTagLink,
            and_(
                ConversationTagLink.company_id == ConversationTag.company_id,
                ConversationTagLink.tag_id == ConversationTag.id,
            ),
        )
        .where(
            ConversationTagLink.company_id == access.company.id,
            ConversationTagLink.conversation_id == conversation.id,
        )
        .order_by(ConversationTag.normalized_name.asc())
    ).all()
    message_count = (
        db.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.company_id == access.company.id,
                Message.conversation_id == conversation.id,
            )
        )
        or 0
    )
    last_message = db.scalar(
        select(Message)
        .where(
            Message.company_id == access.company.id,
            Message.conversation_id == conversation.id,
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1)
    )
    item = _list_item(conversation, contact, lead, membership, user)
    return ConversationDetail(
        **item.model_dump(),
        external_conversation_id=conversation.external_conversation_id,
        ai_enabled=conversation.ai_enabled,
        first_message_at=conversation.first_message_at,
        resolved_at=conversation.resolved_at,
        closed_at=conversation.closed_at,
        archived_at=conversation.archived_at,
        participants=[
            ParticipantSummary(
                id=participant.id,
                participant_type=ConversationParticipantType(participant.participant_type),
                display_name=participant.display_name,
                email=participant.email,
                phone=participant.phone,
            )
            for participant in participants
        ],
        tags=[TagRead.model_validate(tag) for tag in tags],
        message_count=message_count,
        last_message=(
            MessageSummary(
                id=last_message.id,
                direction=MessageDirection(last_message.direction),
                sender_type=MessageSenderType(last_message.sender_type),
                content_type=MessageContentType(last_message.content_type),
                body_preview=(last_message.body_text or last_message.subject or "")[:200] or None,
                status=MessageStatus(last_message.status),
                created_at=last_message.created_at,
            )
            if last_message is not None
            else None
        ),
        applicable_permissions=sorted(
            permission for permission in access.permissions if permission.startswith("inbox.")
        ),
    )


@router.patch("/{conversation_id}", response_model=ConversationRead)
def update_conversation(
    conversation_id: UUID,
    payload: ConversationUpdate,
    request: Request,
    access: InboxStatusEditor,
    db: DatabaseSession,
) -> ConversationRead:
    conversation = _conversation_or_404(db, request, access, conversation_id)
    try:
        ConversationService.update(conversation, subject=payload.subject)
        db.flush()
    except InboxDomainError as exc:
        _raise_domain_error(exc)
    _audit(
        request,
        access,
        action="inbox.conversation.updated",
        conversation_id=conversation.id,
        metadata={"fields": ["subject"]},
    )
    return _read(conversation)


@router.post("/{conversation_id}/assign", response_model=ConversationRead)
def assign_conversation(
    conversation_id: UUID,
    payload: ConversationAssign,
    request: Request,
    access: InboxAssigner,
    db: DatabaseSession,
) -> ConversationRead:
    conversation = _conversation_or_404(db, request, access, conversation_id)
    previous = conversation.assigned_membership_id
    try:
        ConversationService.assign(db, conversation, payload.assigned_membership_id)
        if previous != conversation.assigned_membership_id:
            ConversationManagementService.add_system_event(
                db,
                conversation,
                subject="Conversation assignment changed",
                body="Conversation assignment updated.",
            )
            db.flush()
    except InboxDomainError as exc:
        if payload.assigned_membership_id is not None:
            visible_membership = db.scalar(
                select(Membership.id).where(
                    Membership.id == payload.assigned_membership_id,
                    Membership.company_id == access.company.id,
                )
            )
            if visible_membership is None:
                _hidden_resource(
                    request,
                    access,
                    payload.assigned_membership_id,
                    resource_type="membership",
                )
        _raise_domain_error(exc)
    if previous != conversation.assigned_membership_id:
        _audit(
            request,
            access,
            action=(
                "inbox.conversation.unassigned"
                if conversation.assigned_membership_id is None
                else "inbox.conversation.assigned"
            ),
            conversation_id=conversation.id,
            metadata={"assigned_membership_id": conversation.assigned_membership_id},
        )
    return _read(conversation)


@router.post("/{conversation_id}/status", response_model=ConversationRead)
def change_conversation_status(
    conversation_id: UUID,
    payload: ConversationStatusChange,
    request: Request,
    access: InboxStatusEditor,
    db: DatabaseSession,
) -> ConversationRead:
    conversation = _conversation_or_404(db, request, access, conversation_id)
    previous = conversation.status
    try:
        changed = ConversationManagementService.change_status(db, conversation, payload.status)
        db.flush()
    except (ConversationReadOnlyError, InvalidConversationTransitionError) as exc:
        _raise_domain_error(exc)
    if changed:
        _audit(
            request,
            access,
            action="inbox.conversation.status_changed",
            conversation_id=conversation.id,
            metadata={"from": previous, "to": payload.status},
        )
    return _read(conversation)


@router.post("/{conversation_id}/priority", response_model=ConversationRead)
def change_conversation_priority(
    conversation_id: UUID,
    payload: ConversationPriorityChange,
    request: Request,
    access: InboxPriorityEditor,
    db: DatabaseSession,
) -> ConversationRead:
    conversation = _conversation_or_404(db, request, access, conversation_id)
    previous = conversation.priority
    try:
        changed = ConversationManagementService.change_priority(db, conversation, payload.priority)
        db.flush()
    except InboxDomainError as exc:
        _raise_domain_error(exc)
    if changed:
        _audit(
            request,
            access,
            action="inbox.conversation.priority_changed",
            conversation_id=conversation.id,
            metadata={"from": previous, "to": payload.priority},
        )
    return _read(conversation)


@router.post("/{conversation_id}/archive", response_model=ConversationRead)
def archive_conversation(
    conversation_id: UUID,
    request: Request,
    access: InboxArchiver,
    db: DatabaseSession,
) -> ConversationRead:
    conversation = _conversation_or_404(db, request, access, conversation_id)
    try:
        changed = ConversationManagementService.archive(db, conversation)
        db.flush()
    except InboxDomainError as exc:
        _raise_domain_error(exc)
    if changed:
        _audit(
            request,
            access,
            action="inbox.conversation.archived",
            conversation_id=conversation.id,
        )
    return _read(conversation)


@router.post("/{conversation_id}/reopen", response_model=ConversationRead)
def reopen_conversation(
    conversation_id: UUID,
    request: Request,
    access: InboxStatusEditor,
    db: DatabaseSession,
) -> ConversationRead:
    conversation = _conversation_or_404(db, request, access, conversation_id)
    try:
        changed = ConversationManagementService.reopen(db, conversation)
        db.flush()
    except InboxDomainError as exc:
        _raise_domain_error(exc)
    if changed:
        _audit(
            request,
            access,
            action="inbox.conversation.reopened",
            conversation_id=conversation.id,
        )
    return _read(conversation)


@router.post("/{conversation_id}/mark-read", response_model=ConversationRead)
def mark_conversation_read(
    conversation_id: UUID,
    request: Request,
    access: InboxReader,
    db: DatabaseSession,
) -> ConversationRead:
    conversation = _conversation_or_404(db, request, access, conversation_id)
    try:
        ConversationService.mark_read(conversation)
        db.flush()
    except InboxDomainError as exc:
        _raise_domain_error(exc)
    return _read(conversation)


@router.post("/{conversation_id}/mark-unread", response_model=ConversationRead)
def mark_conversation_unread(
    conversation_id: UUID,
    request: Request,
    access: InboxReader,
    db: DatabaseSession,
) -> ConversationRead:
    conversation = _conversation_or_404(db, request, access, conversation_id)
    try:
        ConversationManagementService.mark_unread(conversation)
        db.flush()
    except InboxDomainError as exc:
        _raise_domain_error(exc)
    return _read(conversation)


def _set_takeover(
    conversation_id: UUID,
    enabled: bool,
    request: Request,
    access: MembershipAuthorization,
    db: Session,
) -> ConversationRead:
    conversation = _conversation_or_404(db, request, access, conversation_id)
    try:
        changed = ConversationManagementService.set_takeover(db, conversation, enabled)
        db.flush()
    except InboxDomainError as exc:
        _raise_domain_error(exc)
    if changed:
        _audit(
            request,
            access,
            action=("inbox.conversation.takeover" if enabled else "inbox.conversation.released"),
            conversation_id=conversation.id,
        )
    return _read(conversation)


@router.post("/{conversation_id}/takeover", response_model=ConversationRead)
def takeover_conversation(
    conversation_id: UUID,
    request: Request,
    access: InboxTakeover,
    db: DatabaseSession,
) -> ConversationRead:
    return _set_takeover(conversation_id, True, request, access, db)


@router.post("/{conversation_id}/release", response_model=ConversationRead)
def release_conversation(
    conversation_id: UUID,
    request: Request,
    access: InboxTakeover,
    db: DatabaseSession,
) -> ConversationRead:
    return _set_takeover(conversation_id, False, request, access, db)

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.authorization import MembershipAuthorization, require_permission, require_permissions
from app.db.models import (
    Conversation,
    ConversationNote,
    ConversationTag,
    ConversationTagLink,
    Membership,
    User,
)
from app.db.session import get_db
from app.schemas.inbox_collaboration import (
    AssigneeRead,
    ConversationCrmContext,
    ConversationOperationalSummary,
    NoteCreateRequest,
    NoteRead,
    NoteUpdateRequest,
    TagCreateRequest,
    TagRead,
    TagUpdateRequest,
)
from app.services.audit import AuditEvent, AuditService
from app.services.inbox import ConversationReadOnlyError, ConversationService
from app.services.inbox_collaboration import InboxCollaborationService, tag_read

router = APIRouter(prefix="/inbox", tags=["inbox-collaboration"])
DatabaseSession = Annotated[Session, Depends(get_db)]
InboxReader = Annotated[MembershipAuthorization, Depends(require_permission("inbox.read"))]
NoteWriter = Annotated[
    MembershipAuthorization,
    Depends(require_permission("inbox.notes.create")),
]
TagManager = Annotated[
    MembershipAuthorization,
    Depends(require_permission("inbox.tags.manage")),
]
AssigneeReader = Annotated[
    MembershipAuthorization,
    Depends(require_permissions("inbox.assign", "members.read")),
]
CrmContextReader = Annotated[
    MembershipAuthorization,
    Depends(require_permissions("inbox.read", "crm.read")),
]


def _audit(
    request: Request,
    access: MembershipAuthorization,
    *,
    action: str,
    resource_type: str,
    resource_id: UUID,
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
            resource_type=resource_type,
            resource_id=str(resource_id),
            metadata=metadata,
        ),
    )


def _conversation_or_404(
    db: Session, access: MembershipAuthorization, item_id: UUID
) -> Conversation:
    item = db.scalar(
        select(Conversation).where(
            Conversation.id == item_id,
            Conversation.company_id == access.company.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return item


def _note_or_404(db: Session, access: MembershipAuthorization, item_id: UUID) -> ConversationNote:
    item = db.scalar(
        select(ConversationNote).where(
            ConversationNote.id == item_id,
            ConversationNote.company_id == access.company.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return item


def _tag_or_404(db: Session, access: MembershipAuthorization, item_id: UUID) -> ConversationTag:
    item = db.scalar(
        select(ConversationTag).where(
            ConversationTag.id == item_id,
            ConversationTag.company_id == access.company.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    return item


def _note_read(db: Session, note: ConversationNote) -> NoteRead:
    display_name = db.scalar(
        select(User.display_name)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.id == note.author_membership_id)
    )
    return NoteRead(
        id=note.id,
        conversation_id=note.conversation_id,
        author_membership_id=note.author_membership_id,
        author_display_name=display_name,
        body=note.body,
        created_at=note.created_at,
        updated_at=note.updated_at,
        archived_at=note.archived_at,
    )


def _ensure_writable(conversation: Conversation) -> None:
    try:
        ConversationService.ensure_writable(conversation)
    except ConversationReadOnlyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _ensure_note_author(note: ConversationNote, access: MembershipAuthorization) -> None:
    if note.author_membership_id != access.membership.id:
        raise HTTPException(status_code=403, detail="Only the note author can change it")


def _flush_or_conflict(db: Session, detail: str) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail=detail) from exc


@router.get("/conversations/{conversation_id}/notes", response_model=list[NoteRead])
def list_notes(
    conversation_id: UUID,
    access: InboxReader,
    db: DatabaseSession,
) -> list[NoteRead]:
    _conversation_or_404(db, access, conversation_id)
    notes = list(
        db.scalars(
            select(ConversationNote)
            .where(
                ConversationNote.company_id == access.company.id,
                ConversationNote.conversation_id == conversation_id,
            )
            .order_by(ConversationNote.created_at.asc(), ConversationNote.id.asc())
        )
    )
    author_ids = {item.author_membership_id for item in notes}
    names = (
        {
            membership_id: display_name
            for membership_id, display_name in db.execute(
                select(Membership.id, User.display_name)
                .join(User, User.id == Membership.user_id)
                .where(Membership.id.in_(author_ids))
            )
        }
        if author_ids
        else {}
    )
    return [
        NoteRead(
            id=item.id,
            conversation_id=item.conversation_id,
            author_membership_id=item.author_membership_id,
            author_display_name=names.get(item.author_membership_id),
            body=item.body,
            created_at=item.created_at,
            updated_at=item.updated_at,
            archived_at=item.archived_at,
        )
        for item in notes
    ]


@router.post(
    "/conversations/{conversation_id}/notes",
    response_model=NoteRead,
    status_code=status.HTTP_201_CREATED,
)
def create_note(
    conversation_id: UUID,
    payload: NoteCreateRequest,
    request: Request,
    access: NoteWriter,
    db: DatabaseSession,
) -> NoteRead:
    conversation = _conversation_or_404(db, access, conversation_id)
    _ensure_writable(conversation)
    note = ConversationNote(
        company_id=access.company.id,
        conversation_id=conversation.id,
        author_membership_id=access.membership.id,
        body=payload.body,
    )
    db.add(note)
    db.flush()
    _audit(
        request,
        access,
        action="inbox.note.created",
        resource_type="conversation_note",
        resource_id=note.id,
    )
    return _note_read(db, note)


@router.patch("/notes/{note_id}", response_model=NoteRead)
def update_note(
    note_id: UUID,
    payload: NoteUpdateRequest,
    request: Request,
    access: NoteWriter,
    db: DatabaseSession,
) -> NoteRead:
    note = _note_or_404(db, access, note_id)
    _ensure_note_author(note, access)
    if note.archived_at is not None:
        raise HTTPException(status_code=409, detail="Archived note is read-only")
    conversation = _conversation_or_404(db, access, note.conversation_id)
    _ensure_writable(conversation)
    note.body = payload.body
    note.updated_at = datetime.now(UTC)
    db.flush()
    _audit(
        request,
        access,
        action="inbox.note.updated",
        resource_type="conversation_note",
        resource_id=note.id,
    )
    return _note_read(db, note)


@router.post("/notes/{note_id}/archive", response_model=NoteRead)
def archive_note(
    note_id: UUID,
    request: Request,
    access: NoteWriter,
    db: DatabaseSession,
) -> NoteRead:
    note = _note_or_404(db, access, note_id)
    _ensure_note_author(note, access)
    if note.archived_at is None:
        conversation = _conversation_or_404(db, access, note.conversation_id)
        _ensure_writable(conversation)
        note.archived_at = datetime.now(UTC)
        note.updated_at = note.archived_at
        db.flush()
        _audit(
            request,
            access,
            action="inbox.note.archived",
            resource_type="conversation_note",
            resource_id=note.id,
        )
    return _note_read(db, note)


@router.get("/tags", response_model=list[TagRead])
def list_tags(access: InboxReader, db: DatabaseSession) -> list[TagRead]:
    tags = list(
        db.scalars(
            select(ConversationTag)
            .where(ConversationTag.company_id == access.company.id)
            .order_by(ConversationTag.normalized_name.asc())
        )
    )
    return [tag_read(item) for item in tags]


@router.post("/tags", response_model=TagRead, status_code=status.HTTP_201_CREATED)
def create_tag(
    payload: TagCreateRequest,
    request: Request,
    access: TagManager,
    db: DatabaseSession,
) -> TagRead:
    tag = ConversationTag(
        company_id=access.company.id,
        name=payload.name,
        description=payload.description,
    )
    db.add(tag)
    _flush_or_conflict(db, "A tag with this normalized name already exists")
    db.refresh(tag)
    _audit(
        request,
        access,
        action="inbox.tag.created",
        resource_type="conversation_tag",
        resource_id=tag.id,
    )
    return tag_read(tag)


@router.patch("/tags/{tag_id}", response_model=TagRead)
def update_tag(
    tag_id: UUID,
    payload: TagUpdateRequest,
    request: Request,
    access: TagManager,
    db: DatabaseSession,
) -> TagRead:
    tag = _tag_or_404(db, access, tag_id)
    for field in payload.model_fields_set:
        setattr(tag, field, getattr(payload, field))
    _flush_or_conflict(db, "A tag with this normalized name already exists")
    db.refresh(tag)
    _audit(
        request,
        access,
        action="inbox.tag.updated",
        resource_type="conversation_tag",
        resource_id=tag.id,
    )
    return tag_read(tag)


@router.post("/conversations/{conversation_id}/tags/{tag_id}", response_model=TagRead)
def add_tag(
    conversation_id: UUID,
    tag_id: UUID,
    request: Request,
    access: TagManager,
    db: DatabaseSession,
) -> TagRead:
    conversation = _conversation_or_404(db, access, conversation_id)
    _ensure_writable(conversation)
    tag = _tag_or_404(db, access, tag_id)
    existing = db.get(
        ConversationTagLink,
        (access.company.id, conversation.id, tag.id),
    )
    if existing is None:
        db.add(
            ConversationTagLink(
                company_id=access.company.id,
                conversation_id=conversation.id,
                tag_id=tag.id,
                created_by_membership_id=access.membership.id,
            )
        )
        db.flush()
        _audit(
            request,
            access,
            action="inbox.tag.added",
            resource_type="conversation",
            resource_id=conversation.id,
            metadata={"tag_id": str(tag.id)},
        )
    return tag_read(tag)


@router.delete("/conversations/{conversation_id}/tags/{tag_id}", status_code=204)
def remove_tag(
    conversation_id: UUID,
    tag_id: UUID,
    request: Request,
    access: TagManager,
    db: DatabaseSession,
) -> Response:
    conversation = _conversation_or_404(db, access, conversation_id)
    _ensure_writable(conversation)
    _tag_or_404(db, access, tag_id)
    link = db.get(ConversationTagLink, (access.company.id, conversation.id, tag_id))
    if link is not None:
        db.delete(link)
        db.flush()
        _audit(
            request,
            access,
            action="inbox.tag.removed",
            resource_type="conversation",
            resource_id=conversation.id,
            metadata={"tag_id": str(tag_id)},
        )
    return Response(status_code=204)


@router.get("/assignees", response_model=list[AssigneeRead])
def list_assignees(_access: AssigneeReader, db: DatabaseSession) -> list[AssigneeRead]:
    return InboxCollaborationService.list_assignees(db)


@router.get(
    "/conversations/{conversation_id}/crm-context",
    response_model=ConversationCrmContext,
)
def crm_context(
    conversation_id: UUID,
    access: CrmContextReader,
    db: DatabaseSession,
) -> ConversationCrmContext:
    conversation = _conversation_or_404(db, access, conversation_id)
    return InboxCollaborationService.crm_context(db, conversation)


@router.get(
    "/conversations/{conversation_id}/summary",
    response_model=ConversationOperationalSummary,
)
def conversation_summary(
    conversation_id: UUID,
    access: CrmContextReader,
    db: DatabaseSession,
) -> ConversationOperationalSummary:
    conversation = _conversation_or_404(db, access, conversation_id)
    return InboxCollaborationService.summary(db, conversation)

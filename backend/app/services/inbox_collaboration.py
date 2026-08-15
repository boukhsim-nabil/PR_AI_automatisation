from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    Contact,
    Conversation,
    ConversationNote,
    ConversationTag,
    ConversationTagLink,
    CrmActivity,
    CrmTask,
    Lead,
    Membership,
    Message,
    Role,
    User,
)
from app.schemas.inbox_collaboration import (
    AssigneeRead,
    ConversationCrmContext,
    ConversationOperationalSummary,
    CrmActivityContext,
    CrmContactContext,
    CrmLeadContext,
    CrmTaskContext,
    MessageOperationalSummary,
    TagRead,
)

ASSIGNABLE_ROLE_CODES = frozenset({"owner", "admin", "manager", "sales", "support"})
CRM_CONTEXT_LIMIT = 10


def _contact_context(contact: Contact | None) -> CrmContactContext | None:
    if contact is None:
        return None
    display_name = " ".join(part for part in (contact.first_name, contact.last_name) if part)
    return CrmContactContext(
        id=contact.id,
        display_name=display_name,
        email=contact.email,
        phone=contact.phone,
        organization_name=contact.organization_name,
        status=contact.status,
    )


def _lead_context(
    lead: Lead | None,
    assigned_display_name: str | None,
) -> CrmLeadContext | None:
    if lead is None:
        return None
    return CrmLeadContext(
        id=lead.id,
        title=lead.title,
        status=lead.status,
        score=lead.score,
        priority=lead.priority,
        assigned_membership_id=lead.assigned_membership_id,
        assigned_display_name=assigned_display_name,
        next_action=lead.next_action,
        next_action_at=lead.next_action_at,
    )


def _message_summary(message: Message | None) -> MessageOperationalSummary | None:
    if message is None:
        return None
    preview = message.body_text or message.subject
    return MessageOperationalSummary(
        id=message.id,
        direction=message.direction,
        content_type=message.content_type,
        status=message.status,
        body_preview=preview[:200] if preview else None,
        created_at=message.created_at,
    )


def tag_read(tag: ConversationTag) -> TagRead:
    return TagRead(
        id=tag.id,
        name=tag.name,
        normalized_name=tag.normalized_name,
        description=tag.description,
        created_at=tag.created_at,
    )


class InboxCollaborationService:
    @staticmethod
    def list_assignees(db: Session) -> list[AssigneeRead]:
        rows = db.execute(
            select(Membership.id, User.display_name, Membership.status, Role.code)
            .join(User, User.id == Membership.user_id)
            .join(Role, Role.id == Membership.role_id)
            .where(
                Membership.status == "active",
                User.status == "active",
                Role.code.in_(ASSIGNABLE_ROLE_CODES),
            )
            .order_by(User.display_name.asc().nullslast(), Membership.id.asc())
        ).all()
        return [
            AssigneeRead(
                membership_id=row.id,
                display_name=row.display_name,
                role_code=row.code,
                status=row.status,
            )
            for row in rows
        ]

    @staticmethod
    def crm_context(db: Session, conversation: Conversation) -> ConversationCrmContext:
        contact = db.scalar(select(Contact).where(Contact.id == conversation.contact_id))
        lead = db.scalar(select(Lead).where(Lead.id == conversation.lead_id))
        assigned_name = None
        if lead and lead.assigned_membership_id:
            assigned_name = db.scalar(
                select(User.display_name)
                .join(Membership, Membership.user_id == User.id)
                .where(Membership.id == lead.assigned_membership_id)
            )

        resource_filter = []
        if conversation.lead_id:
            resource_filter.append(CrmTask.lead_id == conversation.lead_id)
        if conversation.contact_id:
            resource_filter.append(CrmTask.contact_id == conversation.contact_id)
        tasks = (
            list(
                db.scalars(
                    select(CrmTask)
                    .where(
                        or_(*resource_filter),
                        CrmTask.status.in_(("todo", "in_progress")),
                    )
                    .order_by(CrmTask.due_at.asc().nullslast(), CrmTask.created_at.desc())
                    .limit(CRM_CONTEXT_LIMIT)
                )
            )
            if resource_filter
            else []
        )

        activity_filter = []
        if conversation.lead_id:
            activity_filter.append(CrmActivity.lead_id == conversation.lead_id)
        if conversation.contact_id:
            activity_filter.append(CrmActivity.contact_id == conversation.contact_id)
        activities = (
            list(
                db.scalars(
                    select(CrmActivity)
                    .where(or_(*activity_filter))
                    .order_by(CrmActivity.occurred_at.desc(), CrmActivity.id.desc())
                    .limit(CRM_CONTEXT_LIMIT)
                )
            )
            if activity_filter
            else []
        )
        return ConversationCrmContext(
            contact=_contact_context(contact),
            lead=_lead_context(lead, assigned_name),
            tasks=[
                CrmTaskContext(
                    id=item.id,
                    title=item.title,
                    status=item.status,
                    priority=item.priority,
                    due_at=item.due_at,
                )
                for item in tasks
            ],
            activities=[
                CrmActivityContext(
                    id=item.id,
                    activity_type=item.activity_type,
                    subject=item.subject,
                    occurred_at=item.occurred_at,
                )
                for item in activities
            ],
        )

    @classmethod
    def summary(cls, db: Session, conversation: Conversation) -> ConversationOperationalSummary:
        crm = cls.crm_context(db, conversation)
        message_base = [
            Message.conversation_id == conversation.id,
            Message.discarded_at.is_(None),
        ]
        message_count = (
            db.scalar(select(func.count()).select_from(Message).where(*message_base)) or 0
        )

        def latest(direction: str | None = None) -> Message | None:
            clauses = list(message_base)
            if direction:
                clauses.append(Message.direction == direction)
            return db.scalar(
                select(Message)
                .where(*clauses)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(1)
            )

        note_count = (
            db.scalar(
                select(func.count())
                .select_from(ConversationNote)
                .where(
                    ConversationNote.conversation_id == conversation.id,
                    ConversationNote.archived_at.is_(None),
                )
            )
            or 0
        )
        last_note_at = db.scalar(
            select(
                func.max(func.coalesce(ConversationNote.updated_at, ConversationNote.created_at))
            )
            .select_from(ConversationNote)
            .where(ConversationNote.conversation_id == conversation.id)
        )
        tags = list(
            db.scalars(
                select(ConversationTag)
                .join(
                    ConversationTagLink,
                    ConversationTagLink.tag_id == ConversationTag.id,
                )
                .where(ConversationTagLink.conversation_id == conversation.id)
                .order_by(ConversationTag.normalized_name.asc())
            )
        )
        last_tag_at = db.scalar(
            select(func.max(ConversationTagLink.created_at)).where(
                ConversationTagLink.conversation_id == conversation.id
            )
        )
        now = datetime.now(UTC)
        resource_filter = []
        if conversation.lead_id:
            resource_filter.append(CrmTask.lead_id == conversation.lead_id)
        if conversation.contact_id:
            resource_filter.append(CrmTask.contact_id == conversation.contact_id)
        open_task_count = overdue_task_count = 0
        if resource_filter:
            open_task_count = (
                db.scalar(
                    select(func.count())
                    .select_from(CrmTask)
                    .where(
                        or_(*resource_filter),
                        CrmTask.status.in_(("todo", "in_progress")),
                    )
                )
                or 0
            )
            overdue_task_count = (
                db.scalar(
                    select(func.count())
                    .select_from(CrmTask)
                    .where(
                        or_(*resource_filter),
                        CrmTask.status.in_(("todo", "in_progress")),
                        CrmTask.due_at < now,
                    )
                )
                or 0
            )
        last_task_at = (
            db.scalar(select(func.max(CrmTask.updated_at)).where(or_(*resource_filter)))
            if resource_filter
            else None
        )
        activity_filter = []
        if conversation.lead_id:
            activity_filter.append(CrmActivity.lead_id == conversation.lead_id)
        if conversation.contact_id:
            activity_filter.append(CrmActivity.contact_id == conversation.contact_id)
        last_crm_activity_at = (
            db.scalar(select(func.max(CrmActivity.occurred_at)).where(or_(*activity_filter)))
            if activity_filter
            else None
        )
        assigned_name = None
        if conversation.assigned_membership_id:
            assigned_name = db.scalar(
                select(User.display_name)
                .join(Membership, Membership.user_id == User.id)
                .where(Membership.id == conversation.assigned_membership_id)
            )
        last_message = latest()
        activity_candidates = [conversation.updated_at, conversation.created_at]
        if last_message:
            activity_candidates.append(last_message.created_at)
        activity_candidates.extend(
            value
            for value in (last_note_at, last_tag_at, last_task_at, last_crm_activity_at)
            if value is not None
        )
        return ConversationOperationalSummary(
            conversation_id=conversation.id,
            status=conversation.status,
            priority=conversation.priority,
            assigned_membership_id=conversation.assigned_membership_id,
            assigned_display_name=assigned_name,
            message_count=message_count,
            unread_count=conversation.unread_count,
            last_message=_message_summary(last_message),
            last_inbound_message=_message_summary(latest("inbound")),
            last_outbound_message=_message_summary(latest("outbound")),
            note_count=note_count,
            tags=[tag_read(item) for item in tags],
            contact=crm.contact,
            lead=crm.lead,
            open_task_count=open_task_count,
            overdue_task_count=overdue_task_count,
            human_takeover=conversation.human_takeover,
            last_activity_at=max(activity_candidates),
        )

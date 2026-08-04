from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ConversationChannel(StrEnum):
    INTERNAL = "internal"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    SMS = "sms"
    WEBCHAT = "webchat"
    FORM = "form"
    API = "api"


class ConversationStatus(StrEnum):
    OPEN = "open"
    PENDING = "pending"
    WAITING_CUSTOMER = "waiting_customer"
    WAITING_INTERNAL = "waiting_internal"
    RESOLVED = "resolved"
    CLOSED = "closed"
    ARCHIVED = "archived"


class ConversationPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class MessageDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    INTERNAL = "internal"


class MessageSenderType(StrEnum):
    CONTACT = "contact"
    USER = "user"
    EXTERNAL = "external"
    SYSTEM = "system"
    AI_AGENT = "ai_agent"


class MessageContentType(StrEnum):
    TEXT = "text"
    HTML = "html"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    LOCATION = "location"
    SYSTEM_EVENT = "system_event"


class MessageStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    RECEIVED = "received"


MESSAGE_METADATA_TYPE = JSON().with_variant(JSONB(), "postgresql")


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("company_id", "id"),
        ForeignKeyConstraint(
            ["company_id", "contact_id"],
            ["contacts.company_id", "contacts.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "lead_id"],
            ["leads.company_id", "leads.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "assigned_membership_id"],
            ["memberships.company_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "created_by_membership_id"],
            ["memberships.company_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "channel IN ('internal', 'email', 'whatsapp', 'sms', 'webchat', 'form', 'api')",
            name="channel_allowed",
        ),
        CheckConstraint(
            "status IN ('open', 'pending', 'waiting_customer', 'waiting_internal', "
            "'resolved', 'closed', 'archived')",
            name="status_allowed",
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="priority_allowed",
        ),
        CheckConstraint("unread_count >= 0", name="unread_count_non_negative"),
        Index(
            "uq_conversations_company_channel_external_not_null",
            "company_id",
            "channel",
            "external_conversation_id",
            unique=True,
            postgresql_where=text("external_conversation_id IS NOT NULL"),
        ),
        Index(
            "ix_conversations_company_status_last_message",
            "company_id",
            "status",
            "last_message_at",
        ),
        Index(
            "ix_conversations_company_assigned_status",
            "company_id",
            "assigned_membership_id",
            "status",
        ),
        Index(
            "ix_conversations_company_priority_status",
            "company_id",
            "priority",
            "status",
        ),
    )

    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    lead_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    channel: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ConversationChannel.INTERNAL, server_default="internal"
    )
    external_conversation_id: Mapped[str | None] = mapped_column(String(512))
    subject: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ConversationStatus.OPEN, server_default="open"
    )
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ConversationPriority.NORMAL, server_default="normal"
    )
    assigned_membership_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    created_by_membership_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    human_takeover: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    ai_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    unread_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    first_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("company_id", "id"),
        UniqueConstraint("company_id", "conversation_id", "id"),
        ForeignKeyConstraint(
            ["company_id", "conversation_id"],
            ["conversations.company_id", "conversations.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "sender_membership_id"],
            ["memberships.company_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "sender_contact_id"],
            ["contacts.company_id", "contacts.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "conversation_id", "reply_to_message_id"],
            ["messages.company_id", "messages.conversation_id", "messages.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "direction IN ('inbound', 'outbound', 'internal')",
            name="direction_allowed",
        ),
        CheckConstraint(
            "sender_type IN ('contact', 'user', 'external', 'system', 'ai_agent')",
            name="sender_type_allowed",
        ),
        CheckConstraint(
            "content_type IN ('text', 'html', 'image', 'audio', 'video', 'document', "
            "'location', 'system_event')",
            name="content_type_allowed",
        ),
        CheckConstraint(
            "status IN ('draft', 'queued', 'sent', 'delivered', 'read', 'failed', 'received')",
            name="status_allowed",
        ),
        Index(
            "uq_messages_company_external_not_null",
            "company_id",
            "external_message_id",
            unique=True,
            postgresql_where=text("external_message_id IS NOT NULL"),
        ),
        Index(
            "ix_messages_company_conversation_created",
            "company_id",
            "conversation_id",
            "created_at",
        ),
        Index(
            "ix_messages_company_status_created",
            "company_id",
            "status",
            "created_at",
        ),
    )

    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_type: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_membership_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    sender_contact_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    sender_identifier: Mapped[str | None] = mapped_column(String(320))
    content_type: Mapped[str] = mapped_column(
        String(24), nullable=False, default=MessageContentType.TEXT, server_default="text"
    )
    subject: Mapped[str | None] = mapped_column(String(500))
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(
        Text, comment="Untrusted HTML; sanitize before any rendering or transformation."
    )
    external_message_id: Mapped[str | None] = mapped_column(String(512))
    reply_to_message_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    message_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        MESSAGE_METADATA_TYPE,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

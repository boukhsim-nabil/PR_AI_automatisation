from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class ConversationParticipantType(StrEnum):
    CONTACT = "contact"
    USER = "user"
    EXTERNAL = "external"
    SYSTEM = "system"
    AI_AGENT = "ai_agent"


class AttachmentScanStatus(StrEnum):
    PENDING = "pending"
    CLEAN = "clean"
    INFECTED = "infected"
    REJECTED = "rejected"


class ConversationParticipant(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "conversation_participants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "conversation_id"],
            ["conversations.company_id", "conversations.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "contact_id"],
            ["contacts.company_id", "contacts.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "membership_id"],
            ["memberships.company_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "participant_type IN ('contact', 'user', 'external', 'system', 'ai_agent')",
            name="participant_type_allowed",
        ),
        CheckConstraint(
            "(participant_type = 'contact' AND contact_id IS NOT NULL) OR "
            "(participant_type = 'user' AND membership_id IS NOT NULL) OR "
            "(participant_type = 'external' AND "
            "(external_identifier IS NOT NULL OR email_normalized IS NOT NULL "
            "OR phone_normalized IS NOT NULL)) OR "
            "(participant_type IN ('system', 'ai_agent') AND external_identifier IS NOT NULL)",
            name="usable_identity_required",
        ),
        CheckConstraint(
            "external_identifier IS NULL OR length(trim(external_identifier)) > 0",
            name="external_identifier_non_empty",
        ),
        Index(
            "uq_conversation_participants_contact_not_null",
            "company_id",
            "conversation_id",
            "contact_id",
            unique=True,
            postgresql_where=text("contact_id IS NOT NULL"),
        ),
        Index(
            "uq_conversation_participants_membership_not_null",
            "company_id",
            "conversation_id",
            "membership_id",
            unique=True,
            postgresql_where=text("membership_id IS NOT NULL"),
        ),
        Index(
            "uq_conversation_participants_external_not_null",
            "company_id",
            "conversation_id",
            "participant_type",
            "external_identifier",
            unique=True,
            postgresql_where=text("external_identifier IS NOT NULL"),
        ),
        Index(
            "uq_conversation_participants_email_not_null",
            "company_id",
            "conversation_id",
            "email_normalized",
            unique=True,
            postgresql_where=text("email_normalized IS NOT NULL"),
        ),
        Index(
            "uq_conversation_participants_phone_not_null",
            "company_id",
            "conversation_id",
            "phone_normalized",
            unique=True,
            postgresql_where=text("phone_normalized IS NOT NULL"),
        ),
        Index(
            "ix_conversation_participants_company_conversation",
            "company_id",
            "conversation_id",
        ),
    )

    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    participant_type: Mapped[str] = mapped_column(String(16), nullable=False)
    contact_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    membership_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    external_identifier: Mapped[str | None] = mapped_column(String(512))
    display_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    email_normalized: Mapped[str | None] = mapped_column(
        String(320), Computed("NULLIF(lower(trim(email)), '')", persisted=True)
    )
    phone: Mapped[str | None] = mapped_column(String(40))
    phone_normalized: Mapped[str | None] = mapped_column(
        String(40),
        Computed(
            "NULLIF(replace(replace(replace(replace(replace(replace(replace(trim(phone), "
            "' ', ''), '+', ''), '-', ''), '(', ''), ')', ''), '.', ''), '/', ''), '')",
            persisted=True,
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ConversationNote(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "conversation_notes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "conversation_id"],
            ["conversations.company_id", "conversations.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "author_membership_id"],
            ["memberships.company_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(trim(body)) > 0", name="body_non_empty"),
        Index(
            "ix_conversation_notes_company_conversation_created",
            "company_id",
            "conversation_id",
            "created_at",
        ),
        Index("ix_conversation_notes_company_archived", "company_id", "archived_at"),
    )

    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    author_membership_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationTag(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "conversation_tags"
    __table_args__ = (
        UniqueConstraint("company_id", "id"),
        UniqueConstraint("company_id", "normalized_name"),
        CheckConstraint("length(trim(name)) > 0", name="name_non_empty"),
        Index("ix_conversation_tags_company_name", "company_id", "normalized_name"),
    )

    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    normalized_name: Mapped[str] = mapped_column(
        String(120), Computed("lower(trim(name))", persisted=True), nullable=False
    )
    description: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ConversationTagLink(Base):
    __tablename__ = "conversation_tag_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "conversation_id"],
            ["conversations.company_id", "conversations.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "tag_id"],
            ["conversation_tags.company_id", "conversation_tags.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "created_by_membership_id"],
            ["memberships.company_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        PrimaryKeyConstraint("company_id", "conversation_id", "tag_id"),
        Index("ix_conversation_tag_links_company_tag", "company_id", "tag_id"),
    )

    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    tag_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_by_membership_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MessageAttachment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "message_attachments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "message_id"],
            ["messages.company_id", "messages.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("size_bytes > 0", name="size_bytes_positive"),
        CheckConstraint(
            "scan_status IN ('pending', 'clean', 'infected', 'rejected')",
            name="scan_status_allowed",
        ),
        CheckConstraint("length(trim(filename)) > 0", name="filename_non_empty"),
        CheckConstraint("length(trim(mime_type)) > 0", name="mime_type_non_empty"),
        CheckConstraint(
            "length(trim(storage_key)) > 0 AND storage_key NOT LIKE '%://%'",
            name="storage_key_internal",
        ),
        Index(
            "ix_message_attachments_company_message_created",
            "company_id",
            "message_id",
            "created_at",
        ),
        Index(
            "ix_message_attachments_company_scan_status",
            "company_id",
            "scan_status",
        ),
    )

    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    scan_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AttachmentScanStatus.PENDING, server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

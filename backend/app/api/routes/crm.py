from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import Select, and_, false, func, or_, select
from sqlalchemy.orm import Session

from app.api.authorization import MembershipAuthorization, require_permission
from app.db.models import Contact, CrmActivity, CrmTask, Lead, Membership, User
from app.db.session import get_db
from app.schemas.crm import (
    ActivityCreate,
    ActivityPage,
    ActivityRead,
    ActivityType,
    AssigneeRead,
    ContactCreate,
    ContactFilters,
    ContactListItem,
    ContactPage,
    ContactRead,
    ContactStatus,
    ContactUpdate,
    CrmSummary,
    LeadAssign,
    LeadCreate,
    LeadFilters,
    LeadListItem,
    LeadPage,
    LeadPriority,
    LeadRead,
    LeadSortField,
    LeadSource,
    LeadStatus,
    LeadStatusChange,
    LeadUpdate,
    LeadUrgency,
    SortDirection,
    TaskCreate,
    TaskFilters,
    TaskPage,
    TaskPriority,
    TaskRead,
    TaskStatus,
    TaskUpdate,
)
from app.services.audit import AuditEvent, AuditService
from app.services.crm import (
    add_activity,
    ensure_active_membership,
    ensure_contact_accepts_lead,
    ensure_lead_modifiable,
    flush_or_conflict,
    get_contact,
    get_lead,
    get_task,
    normalize_email,
    normalize_phone,
)

router = APIRouter(prefix="/crm", tags=["crm"])
DatabaseSession = Annotated[Session, Depends(get_db)]
CRMReader = Annotated[MembershipAuthorization, Depends(require_permission("crm.read"))]
CRMCreator = Annotated[MembershipAuthorization, Depends(require_permission("crm.create"))]
CRMEditor = Annotated[MembershipAuthorization, Depends(require_permission("crm.update"))]
CRMArchiver = Annotated[MembershipAuthorization, Depends(require_permission("crm.archive"))]
CRMAssigner = Annotated[MembershipAuthorization, Depends(require_permission("crm.assign"))]
ActivityCreator = Annotated[
    MembershipAuthorization,
    Depends(require_permission("crm.activities.create")),
]
TaskManager = Annotated[
    MembershipAuthorization,
    Depends(require_permission("crm.tasks.manage")),
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


def _contact_list_item(contact: Contact) -> ContactListItem:
    return ContactListItem(
        id=contact.id,
        first_name=contact.first_name,
        last_name=contact.last_name,
        email=contact.email,
        phone=contact.phone,
        job_title=contact.job_title,
        organization_name=contact.organization_name,
        status=ContactStatus(contact.status),
        archived_at=contact.archived_at,
        created_at=contact.created_at,
        updated_at=contact.updated_at,
    )


def _contact_read(contact: Contact) -> ContactRead:
    return ContactRead(
        **_contact_list_item(contact).model_dump(),
        language=contact.language,
        consent_email=contact.consent_email,
        consent_whatsapp=contact.consent_whatsapp,
    )


def _lead_list_item(lead: Lead, contact: Contact) -> LeadListItem:
    return LeadListItem(
        id=lead.id,
        contact_id=contact.id,
        title=lead.title,
        contact_first_name=contact.first_name,
        contact_last_name=contact.last_name,
        contact_email=contact.email,
        organization_name=contact.organization_name,
        score=lead.score,
        priority=LeadPriority(lead.priority),
        status=LeadStatus(lead.status),
        source=LeadSource(lead.source),
        assigned_membership_id=lead.assigned_membership_id,
        next_action=lead.next_action,
        next_action_at=lead.next_action_at,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
    )


def _lead_read(lead: Lead, contact: Contact) -> LeadRead:
    return LeadRead(
        **_lead_list_item(lead, contact).model_dump(),
        contact=_contact_read(contact),
        need_description=lead.need_description,
        estimated_budget=lead.estimated_budget,
        currency=lead.currency,
        urgency=LeadUrgency(lead.urgency),
        lost_reason=lead.lost_reason,
        archived_at=lead.archived_at,
    )


def _task_read(task: CrmTask) -> TaskRead:
    return TaskRead(
        id=task.id,
        lead_id=task.lead_id,
        contact_id=task.contact_id,
        title=task.title,
        description=task.description,
        priority=TaskPriority(task.priority),
        status=TaskStatus(task.status),
        assigned_membership_id=task.assigned_membership_id,
        due_at=task.due_at,
        completed_at=task.completed_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _activity_read(activity: CrmActivity) -> ActivityRead:
    return ActivityRead(
        id=activity.id,
        contact_id=activity.contact_id,
        lead_id=activity.lead_id,
        actor_membership_id=activity.actor_membership_id,
        activity_type=ActivityType(activity.activity_type),
        subject=activity.subject,
        description=activity.description,
        metadata=AuditService.sanitize_metadata(activity.activity_metadata),
        occurred_at=activity.occurred_at,
        created_at=activity.created_at,
    )


def _get_lead_with_contact(db: Session, company_id: UUID, lead_id: UUID) -> tuple[Lead, Contact]:
    row = db.execute(
        select(Lead, Contact)
        .join(Contact, and_(Contact.id == Lead.contact_id, Contact.company_id == Lead.company_id))
        .where(Lead.id == lead_id, Lead.company_id == company_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return row._tuple()


def _validate_task_resources(
    db: Session,
    company_id: UUID,
    lead_id: UUID | None,
    contact_id: UUID | None,
) -> tuple[UUID | None, UUID | None]:
    lead = get_lead(db, company_id, lead_id) if lead_id else None
    contact = get_contact(db, company_id, contact_id) if contact_id else None
    if lead is not None:
        ensure_lead_modifiable(lead)
        if contact is None:
            contact = get_contact(db, company_id, lead.contact_id)
        elif contact.id != lead.contact_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Task contact does not match the selected lead",
            )
    return lead.id if lead else None, contact.id if contact else None


@router.get("/summary", response_model=CrmSummary)
def crm_summary(_access: CRMReader, db: DatabaseSession) -> CrmSummary:
    now = datetime.now(UTC)
    lead_filters = [Lead.archived_at.is_(None)]
    return CrmSummary(
        total_leads=db.scalar(select(func.count()).select_from(Lead).where(*lead_filters)) or 0,
        new_leads=db.scalar(
            select(func.count()).select_from(Lead).where(*lead_filters, Lead.status == "new")
        )
        or 0,
        qualified_leads=db.scalar(
            select(func.count()).select_from(Lead).where(*lead_filters, Lead.status == "qualified")
        )
        or 0,
        won_leads=db.scalar(
            select(func.count()).select_from(Lead).where(*lead_filters, Lead.status == "won")
        )
        or 0,
        overdue_tasks=db.scalar(
            select(func.count())
            .select_from(CrmTask)
            .where(
                CrmTask.due_at < now,
                CrmTask.status.not_in(("completed", "cancelled")),
            )
        )
        or 0,
    )


@router.get("/assignees", response_model=list[AssigneeRead])
def list_assignees(_access: CRMReader, db: DatabaseSession) -> list[AssigneeRead]:
    rows = db.execute(
        select(Membership.id, User.display_name, User.email)
        .join(User, User.id == Membership.user_id)
        .where(Membership.status == "active", User.status == "active")
        .order_by(User.display_name.asc().nullslast(), User.email.asc())
    ).all()
    return [
        AssigneeRead(membership_id=row.id, display_name=row.display_name, email=row.email)
        for row in rows
    ]


@router.post("/contacts", response_model=ContactRead, status_code=status.HTTP_201_CREATED)
def create_contact(
    payload: ContactCreate,
    request: Request,
    access: CRMCreator,
    db: DatabaseSession,
) -> ContactRead:
    values = payload.model_dump()
    values["email"] = str(payload.email) if payload.email else None
    values["email_normalized"] = normalize_email(values["email"])
    values["phone_normalized"] = normalize_phone(payload.phone)
    contact = Contact(
        company_id=access.company.id,
        created_by_membership_id=access.membership.id,
        **values,
    )
    db.add(contact)
    flush_or_conflict(db)
    db.refresh(contact)
    _audit(
        request,
        access,
        action="crm.contact.created",
        resource_type="contact",
        resource_id=contact.id,
    )
    return _contact_read(contact)


@router.get("/contacts", response_model=ContactPage)
def list_contacts(
    _access: CRMReader,
    db: DatabaseSession,
    filters: Annotated[ContactFilters, Query()],
) -> ContactPage:
    clauses = []
    if filters.status:
        clauses.append(Contact.status == filters.status)
    else:
        clauses.append(Contact.archived_at.is_(None))
    if filters.search:
        pattern = f"%{filters.search}%"
        normalized_phone = normalize_phone(filters.search)
        clauses.append(
            or_(
                Contact.first_name.ilike(pattern),
                Contact.last_name.ilike(pattern),
                Contact.email.ilike(pattern),
                Contact.organization_name.ilike(pattern),
                Contact.phone_normalized.ilike(f"%{normalized_phone}%")
                if normalized_phone
                else false(),
            )
        )
    if filters.created_from:
        clauses.append(Contact.created_at >= filters.created_from)
    if filters.created_to:
        clauses.append(Contact.created_at <= filters.created_to)
    sort_column = {
        "created_at": Contact.created_at,
        "updated_at": Contact.updated_at,
        "last_name": Contact.last_name,
    }[filters.sort_by]
    ordering = (
        sort_column.asc() if filters.sort_direction is SortDirection.ASC else sort_column.desc()
    )
    total = db.scalar(select(func.count()).select_from(Contact).where(*clauses)) or 0
    contacts = db.scalars(
        select(Contact)
        .where(*clauses)
        .order_by(ordering, Contact.id.desc())
        .offset((filters.page - 1) * filters.page_size)
        .limit(filters.page_size)
    ).all()
    return ContactPage(
        items=[_contact_list_item(contact) for contact in contacts],
        total=total,
        page=filters.page,
        page_size=filters.page_size,
        pages=math.ceil(total / filters.page_size) if total else 0,
    )


@router.get("/contacts/{contact_id}", response_model=ContactRead)
def read_contact(contact_id: UUID, access: CRMReader, db: DatabaseSession) -> ContactRead:
    return _contact_read(get_contact(db, access.company.id, contact_id))


@router.patch("/contacts/{contact_id}", response_model=ContactRead)
def update_contact(
    contact_id: UUID,
    payload: ContactUpdate,
    request: Request,
    access: CRMEditor,
    db: DatabaseSession,
) -> ContactRead:
    contact = get_contact(db, access.company.id, contact_id)
    if contact.status == "archived":
        raise HTTPException(status_code=409, detail="Archived contact cannot be modified")
    values = payload.model_dump(exclude_unset=True)
    if values.get("status") is ContactStatus.ARCHIVED:
        raise HTTPException(status_code=422, detail="Use the archive endpoint")
    if "last_name" in values and values["last_name"] is None:
        raise HTTPException(status_code=422, detail="last_name cannot be null")
    if "email" in values:
        values["email"] = str(values["email"]) if values["email"] else None
        values["email_normalized"] = normalize_email(values["email"])
    if "phone" in values:
        values["phone_normalized"] = normalize_phone(values["phone"])
    for key, item in values.items():
        setattr(contact, key, item)
    flush_or_conflict(db)
    db.refresh(contact)
    _audit(
        request,
        access,
        action="crm.contact.updated",
        resource_type="contact",
        resource_id=contact.id,
        metadata={"fields": sorted(values)},
    )
    return _contact_read(contact)


@router.post("/contacts/{contact_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
def archive_contact(
    contact_id: UUID,
    request: Request,
    access: CRMArchiver,
    db: DatabaseSession,
) -> Response:
    contact = get_contact(db, access.company.id, contact_id)
    contact.status = "archived"
    contact.archived_at = contact.archived_at or datetime.now(UTC)
    db.flush()
    _audit(
        request,
        access,
        action="crm.contact.archived",
        resource_type="contact",
        resource_id=contact.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/leads", response_model=LeadRead, status_code=status.HTTP_201_CREATED)
def create_lead(
    payload: LeadCreate,
    request: Request,
    access: CRMCreator,
    db: DatabaseSession,
) -> LeadRead:
    contact = get_contact(db, access.company.id, payload.contact_id)
    ensure_contact_accepts_lead(contact)
    lead = Lead(
        company_id=access.company.id,
        created_by_membership_id=access.membership.id,
        **payload.model_dump(),
    )
    db.add(lead)
    db.flush()
    add_activity(
        db,
        company_id=access.company.id,
        contact_id=contact.id,
        lead_id=lead.id,
        actor_membership_id=access.membership.id,
        activity_type="system",
        subject="Prospect créé",
    )
    db.refresh(lead)
    _audit(
        request,
        access,
        action="crm.lead.created",
        resource_type="lead",
        resource_id=lead.id,
    )
    return _lead_read(lead, contact)


@router.get("/leads", response_model=LeadPage)
def list_leads(
    _access: CRMReader,
    db: DatabaseSession,
    filters: Annotated[LeadFilters, Query()],
) -> LeadPage:
    clauses = []
    if filters.status:
        clauses.append(Lead.status == filters.status)
    else:
        clauses.append(Lead.archived_at.is_(None))
    if filters.priority:
        clauses.append(Lead.priority == filters.priority)
    if filters.source:
        clauses.append(Lead.source == filters.source)
    if filters.assigned_membership_id:
        clauses.append(Lead.assigned_membership_id == filters.assigned_membership_id)
    if filters.created_from:
        clauses.append(Lead.created_at >= filters.created_from)
    if filters.created_to:
        clauses.append(Lead.created_at <= filters.created_to)
    if filters.search:
        pattern = f"%{filters.search}%"
        normalized_phone = normalize_phone(filters.search)
        clauses.append(
            or_(
                Lead.title.ilike(pattern),
                Contact.first_name.ilike(pattern),
                Contact.last_name.ilike(pattern),
                Contact.email.ilike(pattern),
                Contact.organization_name.ilike(pattern),
                Contact.phone_normalized.ilike(f"%{normalized_phone}%")
                if normalized_phone
                else false(),
            )
        )
    sort_columns = {
        LeadSortField.CREATED_AT: Lead.created_at,
        LeadSortField.UPDATED_AT: Lead.updated_at,
        LeadSortField.SCORE: Lead.score,
        LeadSortField.NEXT_ACTION_AT: Lead.next_action_at,
    }
    sort_column = sort_columns[filters.sort_by]
    ordering = (
        sort_column.asc() if filters.sort_direction is SortDirection.ASC else sort_column.desc()
    )
    base: Select[tuple[Lead, Contact]] = select(Lead, Contact).join(
        Contact, and_(Contact.id == Lead.contact_id, Contact.company_id == Lead.company_id)
    )
    total = (
        db.scalar(
            select(func.count())
            .select_from(Lead)
            .join(
                Contact, and_(Contact.id == Lead.contact_id, Contact.company_id == Lead.company_id)
            )
            .where(*clauses)
        )
        or 0
    )
    rows = db.execute(
        base.where(*clauses)
        .order_by(ordering.nullslast(), Lead.id.desc())
        .offset((filters.page - 1) * filters.page_size)
        .limit(filters.page_size)
    ).all()
    return LeadPage(
        items=[_lead_list_item(row.Lead, row.Contact) for row in rows],
        total=total,
        page=filters.page,
        page_size=filters.page_size,
        pages=math.ceil(total / filters.page_size) if total else 0,
    )


@router.get("/leads/{lead_id}", response_model=LeadRead)
def read_lead(lead_id: UUID, access: CRMReader, db: DatabaseSession) -> LeadRead:
    lead, contact = _get_lead_with_contact(db, access.company.id, lead_id)
    return _lead_read(lead, contact)


@router.patch("/leads/{lead_id}", response_model=LeadRead)
def update_lead(
    lead_id: UUID,
    payload: LeadUpdate,
    request: Request,
    access: CRMEditor,
    db: DatabaseSession,
) -> LeadRead:
    lead, contact = _get_lead_with_contact(db, access.company.id, lead_id)
    ensure_lead_modifiable(lead)
    values = payload.model_dump(exclude_unset=True)
    for key, item in values.items():
        setattr(lead, key, item)
    db.flush()
    db.refresh(lead)
    _audit(
        request,
        access,
        action="crm.lead.updated",
        resource_type="lead",
        resource_id=lead.id,
        metadata={"fields": sorted(values)},
    )
    return _lead_read(lead, contact)


@router.post("/leads/{lead_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
def archive_lead(
    lead_id: UUID,
    request: Request,
    access: CRMArchiver,
    db: DatabaseSession,
) -> Response:
    lead = get_lead(db, access.company.id, lead_id)
    lead.status = "archived"
    lead.archived_at = lead.archived_at or datetime.now(UTC)
    db.flush()
    add_activity(
        db,
        company_id=lead.company_id,
        contact_id=lead.contact_id,
        lead_id=lead.id,
        actor_membership_id=access.membership.id,
        activity_type="status_change",
        subject="Prospect archivé",
        metadata={"to": "archived"},
    )
    _audit(
        request,
        access,
        action="crm.lead.archived",
        resource_type="lead",
        resource_id=lead.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/leads/{lead_id}/assign", response_model=LeadRead)
def assign_lead(
    lead_id: UUID,
    payload: LeadAssign,
    request: Request,
    access: CRMAssigner,
    db: DatabaseSession,
) -> LeadRead:
    lead, contact = _get_lead_with_contact(db, access.company.id, lead_id)
    ensure_lead_modifiable(lead)
    ensure_active_membership(db, access.company.id, payload.assigned_membership_id)
    previous = lead.assigned_membership_id
    lead.assigned_membership_id = payload.assigned_membership_id
    db.flush()
    add_activity(
        db,
        company_id=lead.company_id,
        contact_id=lead.contact_id,
        lead_id=lead.id,
        actor_membership_id=access.membership.id,
        activity_type="assignment",
        subject="Responsable modifié",
        metadata={"from": previous, "to": payload.assigned_membership_id},
    )
    db.refresh(lead)
    _audit(
        request,
        access,
        action="crm.lead.assigned",
        resource_type="lead",
        resource_id=lead.id,
        metadata={"assigned_membership_id": payload.assigned_membership_id},
    )
    return _lead_read(lead, contact)


@router.post("/leads/{lead_id}/status", response_model=LeadRead)
def change_lead_status(
    lead_id: UUID,
    payload: LeadStatusChange,
    request: Request,
    access: CRMEditor,
    db: DatabaseSession,
) -> LeadRead:
    lead, contact = _get_lead_with_contact(db, access.company.id, lead_id)
    ensure_lead_modifiable(lead)
    if payload.status is LeadStatus.ARCHIVED:
        raise HTTPException(status_code=422, detail="Use the archive endpoint")
    previous = lead.status
    lead.status = payload.status
    lead.lost_reason = payload.lost_reason if payload.status is LeadStatus.LOST else None
    db.flush()
    add_activity(
        db,
        company_id=lead.company_id,
        contact_id=lead.contact_id,
        lead_id=lead.id,
        actor_membership_id=access.membership.id,
        activity_type="status_change",
        subject="Statut modifié",
        metadata={"from": previous, "to": payload.status},
    )
    if payload.status is LeadStatus.WON:
        add_activity(
            db,
            company_id=lead.company_id,
            contact_id=lead.contact_id,
            lead_id=lead.id,
            actor_membership_id=None,
            activity_type="system",
            subject="Opportunité gagnée",
        )
    db.refresh(lead)
    _audit(
        request,
        access,
        action="crm.lead.status_changed",
        resource_type="lead",
        resource_id=lead.id,
        metadata={"from": previous, "to": payload.status},
    )
    return _lead_read(lead, contact)


@router.get("/leads/{lead_id}/activities", response_model=ActivityPage)
def list_lead_activities(
    lead_id: UUID,
    access: CRMReader,
    db: DatabaseSession,
    page: int = Query(default=1, ge=1, le=100_000),
    page_size: int = Query(default=50, ge=1, le=100),
) -> ActivityPage:
    get_lead(db, access.company.id, lead_id)
    clauses = [CrmActivity.lead_id == lead_id]
    total = db.scalar(select(func.count()).select_from(CrmActivity).where(*clauses)) or 0
    activities = db.scalars(
        select(CrmActivity)
        .where(*clauses)
        .order_by(CrmActivity.occurred_at.desc(), CrmActivity.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ActivityPage(
        items=[_activity_read(activity) for activity in activities],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.post(
    "/leads/{lead_id}/activities",
    response_model=ActivityRead,
    status_code=status.HTTP_201_CREATED,
)
def create_lead_activity(
    lead_id: UUID,
    payload: ActivityCreate,
    request: Request,
    access: ActivityCreator,
    db: DatabaseSession,
) -> ActivityRead:
    lead = get_lead(db, access.company.id, lead_id)
    ensure_lead_modifiable(lead)
    activity = add_activity(
        db,
        company_id=lead.company_id,
        contact_id=lead.contact_id,
        lead_id=lead.id,
        actor_membership_id=access.membership.id,
        activity_type=payload.activity_type,
        subject=payload.subject,
        description=payload.description,
        occurred_at=payload.occurred_at,
    )
    _audit(
        request,
        access,
        action="crm.activity.created",
        resource_type="crm_activity",
        resource_id=activity.id,
    )
    return _activity_read(activity)


@router.post("/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate,
    request: Request,
    access: TaskManager,
    db: DatabaseSession,
) -> TaskRead:
    lead_id, contact_id = _validate_task_resources(
        db, access.company.id, payload.lead_id, payload.contact_id
    )
    ensure_active_membership(db, access.company.id, payload.assigned_membership_id)
    values = payload.model_dump(exclude={"lead_id", "contact_id"})
    task = CrmTask(
        company_id=access.company.id,
        lead_id=lead_id,
        contact_id=contact_id,
        created_by_membership_id=access.membership.id,
        **values,
    )
    db.add(task)
    db.flush()
    add_activity(
        db,
        company_id=task.company_id,
        contact_id=task.contact_id,
        lead_id=task.lead_id,
        actor_membership_id=access.membership.id,
        activity_type="task",
        subject="Tâche créée",
        metadata={"task_id": task.id},
    )
    db.refresh(task)
    _audit(
        request,
        access,
        action="crm.task.created",
        resource_type="crm_task",
        resource_id=task.id,
    )
    return _task_read(task)


@router.get("/tasks", response_model=TaskPage)
def list_tasks(
    _access: CRMReader,
    db: DatabaseSession,
    filters: Annotated[TaskFilters, Query()],
) -> TaskPage:
    clauses = []
    for column, item in (
        (CrmTask.lead_id, filters.lead_id),
        (CrmTask.contact_id, filters.contact_id),
        (CrmTask.status, filters.status),
        (CrmTask.priority, filters.priority),
        (CrmTask.assigned_membership_id, filters.assigned_membership_id),
    ):
        if item is not None:
            clauses.append(column == item)
    if filters.due_from:
        clauses.append(CrmTask.due_at >= filters.due_from)
    if filters.due_to:
        clauses.append(CrmTask.due_at <= filters.due_to)
    total = db.scalar(select(func.count()).select_from(CrmTask).where(*clauses)) or 0
    tasks = db.scalars(
        select(CrmTask)
        .where(*clauses)
        .order_by(CrmTask.due_at.asc().nullslast(), CrmTask.created_at.desc())
        .offset((filters.page - 1) * filters.page_size)
        .limit(filters.page_size)
    ).all()
    return TaskPage(
        items=[_task_read(task) for task in tasks],
        total=total,
        page=filters.page,
        page_size=filters.page_size,
        pages=math.ceil(total / filters.page_size) if total else 0,
    )


@router.patch("/tasks/{task_id}", response_model=TaskRead)
def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    request: Request,
    access: TaskManager,
    db: DatabaseSession,
) -> TaskRead:
    task = get_task(db, access.company.id, task_id)
    values = payload.model_dump(exclude_unset=True)
    if "assigned_membership_id" in values:
        ensure_active_membership(db, access.company.id, values["assigned_membership_id"])
    previous_assignee = task.assigned_membership_id
    for key, item in values.items():
        setattr(task, key, item)
    if values.get("status") is TaskStatus.COMPLETED:
        task.completed_at = task.completed_at or datetime.now(UTC)
    elif "status" in values:
        task.completed_at = None
    db.flush()
    if "assigned_membership_id" in values and previous_assignee != task.assigned_membership_id:
        add_activity(
            db,
            company_id=task.company_id,
            contact_id=task.contact_id,
            lead_id=task.lead_id,
            actor_membership_id=access.membership.id,
            activity_type="assignment",
            subject="Responsable de tâche modifié",
            metadata={"task_id": task.id, "to": task.assigned_membership_id},
        )
    db.refresh(task)
    _audit(
        request,
        access,
        action="crm.task.updated",
        resource_type="crm_task",
        resource_id=task.id,
        metadata={"fields": sorted(values)},
    )
    return _task_read(task)


@router.post("/tasks/{task_id}/complete", response_model=TaskRead)
def complete_task(
    task_id: UUID,
    request: Request,
    access: TaskManager,
    db: DatabaseSession,
) -> TaskRead:
    task = get_task(db, access.company.id, task_id)
    task.status = "completed"
    task.completed_at = task.completed_at or datetime.now(UTC)
    db.flush()
    add_activity(
        db,
        company_id=task.company_id,
        contact_id=task.contact_id,
        lead_id=task.lead_id,
        actor_membership_id=access.membership.id,
        activity_type="task",
        subject="Tâche terminée",
        metadata={"task_id": task.id},
    )
    db.refresh(task)
    _audit(
        request,
        access,
        action="crm.task.completed",
        resource_type="crm_task",
        resource_id=task.id,
    )
    return _task_read(task)

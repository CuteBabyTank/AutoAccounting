"""Resolved, reviewable Casper proposals and route-based execution. No model can apply an action."""
import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import Date, DateTime, Uuid, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import bind_session_user
from app.models.accounting import AAAccount, AAAssistantAction, AACompany, AADocument, AAFile, AATask, AAWorkItem
from app.models.user import User
from app.routers.accounting_scope import MANAGER_ROLES, company_or_404, firm_settings, scope_for
from app.schemas.accounting_assistant import ActionOut
from app.schemas.accounting import DocumentPatch
from app.schemas.accounting_work import TaskIn, TaskPatch, WorkItemIn
from app.services import features
from app.services.accounting import audit, deletion
from app.services.accounting.assignment import lock_firm
from app.services.accounting.assistant import action_policy as policy
from app.services.accounting.assistant.tools import Ctx, ToolError, _uuid, resolve_company
from app.services.accounting.search import like_pattern
from app.services.accounting.work import firm_people, person_name

logger = logging.getLogger('assistant')
TASK_EDIT = ('title', 'notes', 'due_date', 'priority', 'status', 'assignee_id')
DOC_EDIT = ('gl_account_code', 'category', 'period_year', 'period_quarter', 'notes')
WORK_FIELDS = ('assignee_id', 'assigned_auto', 'status_override', 'filed_on', 'filed_by')
# The model may say 'todo' for an open task; stored names are the task API's own.
DETAIL_LABELS = {'assignee_id': 'Assigned to', 'due_date': 'Due', 'gl_account_code': 'Account',
                 'period_year': 'Year', 'period_quarter': 'Quarter', 'status_override': 'Status'}
TASK_STATUS_WORDS = {'open': 'To do', 'in_progress': 'In progress', 'done': 'Done'}
FILING_STATUS_WORDS = {'': 'Automatic', 'no_docs': 'No documents yet', 'docs_in': 'Documents in',
                       'needs_review': 'Needs review', 'generated': 'Return generated'}


def _spelled(value) -> str:
    try:
        d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    except ValueError:
        return str(value)
    return f"{d:%B} {d.day}, {d.year}"


TASK_STATES = {'open': 'open', 'todo': 'open', 'in_progress': 'in_progress', 'done': 'done'}
FILING_STATES = {s: s for s in ('', 'no_docs', 'docs_in', 'needs_review', 'generated')}


@dataclass(frozen=True)
class ActionKind:
    model: type
    fields: tuple[str, ...]
    destructive: bool = False


REGISTRY = {
    'create_task': ActionKind(AATask, ('title', 'notes', 'due_date', 'priority', 'company_id',
                                      'document_id', 'assignee_id')),
    'update_task': ActionKind(AATask, TASK_EDIT),
    'delete_task': ActionKind(AATask, (), True),
    'update_document': ActionKind(AADocument, DOC_EDIT),
    'delete_document': ActionKind(AADocument, (), True),
    'assign_filing': ActionKind(AAWorkItem, ('assignee_id', 'status')),
}


async def permission(db: AsyncSession, user: User) -> dict:
    ent = scope_for(user)
    state = await features.firm_effective_for(db, user)
    # The write kill switch applies to tools even for platform admins; the person's own Casper level comes next.
    level = (user.access or {}).get('assistant') if isinstance(user.access, dict) else None
    return policy.write_permission((await firm_settings(db, ent)).assistant_writes, user.role.value,
                                   state['assistant_write'] and state['assistant'], level)


async def require_write(db: AsyncSession, user: User) -> None:
    allowed = await permission(db, user)
    if not allowed['allowed']:
        raise HTTPException(403, allowed['reason'])


async def check_caps(db: AsyncSession, ent: uuid.UUID, uid: uuid.UUID, kind: str, now: datetime) -> None:
    lo, hi = policy.day_bounds(now)
    a = AAAssistantAction
    # applied_at remains set on undone actions: undo doesn't refund the day's cap.
    counts = (await db.execute(select(
        func.count().filter(a.user_id == uid),
        func.count().filter(a.user_id == uid, a.kind.in_(policy.DELETE_KINDS)),
        func.count().filter(a.kind.in_(policy.DELETE_KINDS)),
    ).where(a.enterprise_id == ent, a.applied_at >= lo, a.applied_at < hi))).one()
    problem = policy.cap_problem(kind, *counts)
    if problem:
        raise HTTPException(429, problem)


def snapshot(row) -> dict:
    return audit.snapshot(row, (c.key for c in row.__table__.columns))


def typed_values(model: type, values: dict) -> dict:
    """Decode a full JSON snapshot back into the column's Python types (including same-id restores)."""
    result = dict(values)
    for c in model.__table__.columns:
        value = result.get(c.key)
        if value is None:
            continue
        if isinstance(c.type, Uuid):
            result[c.key] = uuid.UUID(value)
        elif isinstance(c.type, DateTime):
            result[c.key] = datetime.fromisoformat(value)
        elif isinstance(c.type, Date):
            result[c.key] = date.fromisoformat(value)
    return result


async def resolve_person(ctx: Ctx, ref: str | None) -> User | None:
    if ref is None or ref == '':
        return None
    if ref.lower() in {'me', 'myself'}:
        ref = str(ctx.user.id)
    people = await firm_people(ctx.db, ctx.ent)
    exact = [p for p in people if str(p.id) == ref or ref.casefold() == person_name(p).casefold()
             or ref.casefold() == p.email.casefold()]
    matches = exact or [p for p in people if ref.casefold() in person_name(p).casefold()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ToolError('Person not found in this firm')
    raise ToolError('Several people match: ' + ', '.join(person_name(p) for p in matches) + '. Ask which person.')


async def resolve_target(ctx: Ctx, kind: str, ref: str, company: AACompany | None):
    model = REGISTRY[kind].model
    query = select(model).where(model.enterprise_id == ctx.ent)
    if company:
        query = query.where(model.company_id == company.id)
    if model is AADocument:
        query = query.where(model.deleted_at.is_(None))
    if not str(ref).strip():
        raise ToolError('Choose exactly one record')
    if uid := _uuid(ref):
        query = query.where(model.id == uid)
    elif model is AATask:
        query = query.where(model.title.ilike(like_pattern(ref), escape='\\'))
    else:
        query = query.where(model.doc_number.ilike(like_pattern(ref), escape='\\'))
    rows = (await ctx.db.execute(query.limit(6))).scalars().all()
    label = 'Task' if model is AATask else 'Document'
    if not rows:
        raise ToolError(f'{label} not found')
    if len(rows) != 1:
        names = [r.title if model is AATask else audit.document_label(r) for r in rows]
        raise ToolError(f'Several {label.lower()}s match: ' + ', '.join(f'{r.id}: {n}' for r, n in zip(rows, names))
                        + '. Ask which record.')
    return rows[0]


def validate_body(kind: str, changes: dict) -> dict:
    allowed = REGISTRY[kind].fields
    if not isinstance(changes, dict):
        raise ToolError('Changes must be an object for one record')
    unknown = set(changes) - set(allowed)
    if unknown:
        raise ToolError('Unsupported fields: ' + ', '.join(sorted(unknown)))
    body = dict(changes)
    required = {'title', 'notes', 'status', 'priority'} if kind == 'update_task' else {'category', 'notes'}
    if any(k in body and body[k] is None for k in required):
        raise ToolError('These fields cannot be null: ' + ', '.join(sorted(required & set(body))))
    if kind == 'update_task' and isinstance(body.get('title'), str):
        body['title'] = body['title'].strip()
    if kind == 'update_document' and 'gl_account_code' in body:
        if body['gl_account_code'] is None:
            body['gl_account_code'] = ''
        elif isinstance(body['gl_account_code'], str):
            body['gl_account_code'] = body['gl_account_code'].strip()
    if kind == 'update_task' and 'status' in body:
        if body['status'] not in TASK_STATES:
            raise ToolError('Task status must be open, in_progress or done')
        body['status'] = TASK_STATES[body['status']]
    schema = TaskIn if kind == 'create_task' else TaskPatch if kind == 'update_task' else DocumentPatch
    try:
        return schema.model_validate(body).model_dump(mode='json', exclude_unset=kind != 'create_task')
    except ValidationError as exc:
        raise ToolError(str(exc)) from None


async def propose(ctx: Ctx, kind: str, *, company: str | None = None, target: str | None = None,
                  changes: dict | None = None, assignee: str | None = None, year: int | None = None,
                  quarter: int | None = None, form: str | None = None) -> ActionOut:
    if not ctx.write:
        raise ToolError('Write mode is off')
    if kind == 'assign_filing' and isinstance(changes, dict) and str(changes.get('status', '')).lower() == 'filed':
        raise ToolError('A return is never filed by Casper (status never filed); the person marks it filed on the work board')
    policy.check_proposal_limit(ctx.proposals)
    await require_write(ctx.db, ctx.user)
    await lock_firm(ctx.db, ctx.ent)
    now = datetime.now(timezone.utc)
    await check_caps(ctx.db, ctx.ent, ctx.user.id, kind, now)
    if kind not in REGISTRY:
        raise ToolError('That action is not available')
    config = REGISTRY[kind]
    c = await resolve_company(ctx, company) if company or kind == 'assign_filing' else None
    if changes is not None and not isinstance(changes, dict):
        raise ToolError('Changes must be an object for one record')
    body = dict(changes or {})
    if assignee is not None:
        p = await resolve_person(ctx, assignee)
        body['assignee_id'] = str(p.id) if p else None
    elif body.get('assignee_id'):
        p = await resolve_person(ctx, str(body['assignee_id']))
        body['assignee_id'] = str(p.id)
    row = None
    if kind == 'assign_filing':
        form = (form or '').upper().replace(' ', '')
        if form in {'1601C', '0619E', '1601-C', '0619-E'}:
            raise ToolError('Monthly returns need their exact form_key from filings (e.g. 1601C-M1 for the first '
                            "month of the quarter). Call filings for this company and copy that filing's form_key.")
        form = form if form in {'0619E-M1', '0619E-M2', '1601C-M1', '1601C-M2', '1601C-M3'} else form.replace('-', '')
        unknown = set(body) - {'assignee_id', 'status'}
        if unknown or not body:
            raise ToolError('Only filing assignee and status may change')
        if 'status' in body:
            if body['status'] not in FILING_STATES:
                raise ToolError('Filing status must be no_docs, docs_in, needs_review or generated; never filed')
            body['status_override'] = FILING_STATES[body.pop('status')]
        try:
            body = WorkItemIn(company_id=c.id, year=year, quarter=quarter, form=form, **body).model_dump(
                mode='json', exclude_unset=True)
        except ValidationError as exc:
            raise ToolError(str(exc)) from None
        row = await filing_row(ctx.db, ctx.ent, body)
        label = filing_label(form, year, quarter, c.fiscal_year_end_month if c else 12)
    elif kind == 'create_task':
        # Company/document names resolve to one record before they are stored.
        if c:
            body['company_id'] = str(c.id)
        if body.get('company_id'):
            c = await resolve_company(ctx, str(body['company_id']))
        if body.get('document_id'):
            doc = await resolve_target(ctx, 'update_document', str(body['document_id']), c)
            body['document_id'] = str(doc.id)
            c = c or await company_or_404(ctx.db, ctx.ent, doc.company_id)
            body['company_id'] = str(c.id)
        body = validate_body(kind, body)
        from app.routers.accounting_tasks import _check_links
        await _check_links(ctx.db, ctx.ent, TaskIn(**body).model_dump())
        label = body['title']
    else:
        if not target or not str(target).strip():
            raise ToolError('Choose exactly one record')
        row = await resolve_target(ctx, kind, str(target), c)
        c = await company_or_404(ctx.db, ctx.ent, row.company_id) if row.company_id else None
        label = row.title if isinstance(row, AATask) else audit.document_label(row)
        if config.destructive:
            if body:
                raise ToolError('A delete proposal cannot edit fields')
            delete_rights(kind, row, ctx.user)
            if kind == 'delete_document':
                await deletion.protect_document(ctx.db, c, row)
        else:
            if not body:
                raise ToolError('Choose at least one field to change')
            body = validate_body(kind, body)
            if kind == 'update_task' and 'assignee_id' in body:
                from app.routers.accounting_work import assignee_or_400
                await assignee_or_400(ctx.db, ctx.ent, TaskPatch(**body).assignee_id)
            if kind == 'update_document':
                await protect_document_edit(ctx.db, c, row, body)
    if c and c.archived_at is not None:
        raise ToolError('Restore the company on the Companies screen first')
    if kind == 'assign_filing':
        from app.routers.accounting_work import assignee_or_400
        await assignee_or_400(ctx.db, ctx.ent, WorkItemIn(**body).assignee_id)
        await protect_filing(ctx.db, c, body)
    verb = {'create_task': 'Create task', 'update_task': 'Update task', 'delete_task': 'Delete task',
            'update_document': 'Update document', 'delete_document': 'Delete document',
            'assign_filing': 'Update filing'}[kind]
    # The card shows the company under its heading, so it isn't repeated as a row.
    details = [] if kind == 'create_task' else [{'label': 'Record', 'value': label}]
    for key, value in body.items():
        if key in {'company_id', 'year', 'quarter', 'form', 'document_id'}:
            continue
        if kind == 'create_task' and (key == 'title' or value in (None, '')):
            continue  # the title is the card's heading; blanks say nothing
        display = '(none)' if value in (None, '') else str(value)
        if key == 'assignee_id':
            display = person_name(await resolve_person(ctx, str(value))) if value else 'Nobody'
        elif key.endswith('_date') and value:
            display = _spelled(value)
        elif kind in ('create_task', 'update_task') and key == 'status':
            display = TASK_STATUS_WORDS.get(value, value)
        elif kind == 'assign_filing' and key == 'status_override':
            display = FILING_STATUS_WORDS.get(value, value)
        elif key == 'priority' and value:
            display = str(value).capitalize()
        details.append({'label': DETAIL_LABELS.get(key, key.replace('_', ' ').capitalize()), 'value': display})
    args = {'body': body, 'expected': policy.fingerprint(snapshot(row)) if row else None}
    action = AAAssistantAction(id=uuid.uuid4(), enterprise_id=ctx.ent, user_id=ctx.user.id,
        company_id=c.id if c else None, kind=kind, args=args, summary=f'{verb}: {label}', details=details, destructive=config.destructive,
        status='proposed', target_id=row.id if row else None, created_at=now, expires_at=now + policy.PROPOSAL_TTL)
    ctx.db.add(action)
    await ctx.db.commit()
    ctx.proposals += 1
    return await action_out(ctx.db, action, ctx.user)


def delete_rights(kind: str, row, user: User) -> None:
    if kind == 'delete_document' and user.role not in MANAGER_ROLES:
        raise HTTPException(403, 'Only managers and the firm owner can delete documents through Casper')
    if kind == 'delete_task' and row.created_by != user.id and user.role not in MANAGER_ROLES:
        raise HTTPException(403, 'Only whoever created the task, a manager or the firm owner can delete it')


_FORM_NAMES = {'2550Q': '2550-Q', '2551Q': '2551-Q', '1701Q': '1701-Q', '1702Q': '1702-Q', '1601EQ': '1601-EQ',
               '1702RT': '1702-RT', '1701': '1701', '1701A': '1701-A', '1604C': '1604-C alphalist',
               '0619E': '0619-E', '1601C': '1601-C'}
_MONTH_NAMES = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
                'November', 'December')


def filing_label(form: str, year: int, quarter: int, fye_month: int = 12) -> str:
    """'1601C-M1', 2026, 4 → '1601-C for October 2026'; '2550Q', 2026, 3 → '2550-Q for Q3 2026'."""
    base, _, month = form.partition('-M')
    name = _FORM_NAMES.get(base, base)
    if not quarter:
        return f'{name} for {year}'
    if not month:
        return f'{name} for Q{quarter} {year}'
    # Fiscal year `year` ends in fye_month; its quarter q starts 3*(q-1) months after the fiscal year starts.
    start = (fye_month % 12) + 3 * (quarter - 1) + int(month) - 1          # months after January of year-1/year
    cal_year = year - (1 if fye_month != 12 else 0) + start // 12
    return f'{name} for {_MONTH_NAMES[start % 12]} {cal_year}'


async def filing_row(db: AsyncSession, ent: uuid.UUID, body: dict):
    return (await db.execute(select(AAWorkItem).where(AAWorkItem.enterprise_id == ent,
        AAWorkItem.company_id == uuid.UUID(str(body['company_id'])), AAWorkItem.year == body['year'],
        AAWorkItem.quarter == body['quarter'], AAWorkItem.form == body['form']))).scalar_one_or_none()


async def protect_filing(db: AsyncSession, company: AACompany, body: dict) -> None:
    from app.routers.accounting_work import BOARD_FORMS
    from app.routers.accounting_periods import company_facts
    from app.services.accounting.compute.work import obligations
    if body['form'] not in BOARD_FORMS or (body['quarter'] == 0) != (
            body['form'] in {'1702RT', '1701', '1701A', '1604C'}):
        raise HTTPException(400, 'That form is not a filing on the board')
    owed = obligations(company_facts(company), date(body['year'] - 1, 1, 1), date(body['year'] + 2, 12, 31),
                       {(body['year'], body['quarter'])}, {body['year']})
    if not any((o.form, o.year, o.quarter) == (body['form'], body['year'], body['quarter']) for o in owed):
        raise HTTPException(400, 'That filing is not owed for this period')
    await deletion.protect_history(db, company, periods=[(body['year'], body['quarter'])])


async def protect_document_edit(db: AsyncSession, company: AACompany, doc: AADocument, body: dict) -> None:
    periods = [(doc.period_year, doc.period_quarter)] if doc.period_year and doc.period_quarter else []
    if body.get('period_year') and body.get('period_quarter'):
        periods.append((body['period_year'], body['period_quarter']))
    await deletion.protect_history(db, company, [doc.doc_date, doc.paid_on], periods)
    code = (body.get('gl_account_code') or '').strip()
    if code:
        account = (await db.execute(select(AAAccount).where(AAAccount.enterprise_id == company.enterprise_id,
            AAAccount.company_id == company.id, AAAccount.code == code, AAAccount.active.is_(True)))).scalar_one_or_none()
        if account is None:
            raise HTTPException(400, f"Account {code} isn't an active account in the chart")
        if account.locked and code != doc.gl_account_code:
            raise HTTPException(409, f"Account {code} is locked. Use the Documents screen.")


async def action_out(db: AsyncSession, row: AAAssistantAction, user: User, allowed: bool | None = None) -> ActionOut:
    now = datetime.now(timezone.utc)
    company = (await db.execute(select(AACompany).where(AACompany.enterprise_id == row.enterprise_id,
        AACompany.id == row.company_id))).scalar_one_or_none() if row.company_id else None
    person = (await db.execute(select(User).where(User.id == row.user_id,
        (User.id == row.enterprise_id) | (User.enterprise_id == row.enterprise_id)))).scalar_one_or_none()
    allowed = (await permission(db, user))['allowed'] if allowed is None else allowed
    own = row.user_id == user.id
    return ActionOut(id=row.id, kind=row.kind, summary=row.summary, details=row.details,
        destructive=row.destructive, status=row.status, error=row.error,
        company_name=company.registered_name if company else '', created_at=row.created_at,
        expires_at=row.expires_at, applied_at=row.applied_at, undo_until=row.undo_until, undone_at=row.undone_at,
        can_confirm=bool(allowed and own and row.status == 'proposed' and now < row.expires_at),
        can_undo=bool(allowed and (own or user.role in MANAGER_ROLES) and row.status == 'applied'
                      and row.undo_until and now < row.undo_until), user_name=person_name(person) if person else '')


async def get_action(db: AsyncSession, user: User, action_id: uuid.UUID, *, own: bool = False) -> AAAssistantAction:
    ent = scope_for(user)
    # Consistent lock order with all existing mutations. Also serializes the firm's caps.
    await lock_firm(db, ent)
    query = select(AAAssistantAction).where(AAAssistantAction.enterprise_id == ent,
                                         AAAssistantAction.id == action_id).with_for_update()
    if own or user.role not in MANAGER_ROLES:
        query = query.where(AAAssistantAction.user_id == user.id)
    row = (await db.execute(query.execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, 'Proposal not found')
    return row


@asynccontextmanager
async def route_session(db: AsyncSession, user: User):
    """Route commits release savepoints only; the parent retains the action/firm locks and atomic commit."""
    await db.flush()
    async with AsyncSession(bind=await db.connection(), expire_on_commit=False,
                            join_transaction_mode='create_savepoint') as child:
        await bind_session_user(child, str(user.id))
        from app.services.accounting.assistant.scope import firm_reads
        with firm_reads(child, scope_for(user)):
            yield child
            await child.commit()


async def target_row(db: AsyncSession, action: AAAssistantAction):
    model = REGISTRY[action.kind].model
    if action.kind == 'assign_filing':
        return await filing_row(db, action.enterprise_id, action.args['body'])
    if action.target_id is None:
        return None
    return (await db.execute(select(model).where(model.enterprise_id == action.enterprise_id,
        model.id == action.target_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()


async def apply(db: AsyncSession, action: AAAssistantAction, user: User) -> tuple[uuid.UUID, dict]:
    from app.routers import accounting, accounting_tasks, accounting_work
    kind, body = action.kind, action.args['body']
    row = await target_row(db, action)
    if kind != 'create_task':
        if action.args['expected'] is not None:
            if row is None:
                raise HTTPException(409, 'This record has changed since the proposal')
            policy.check_unchanged({'fingerprint': policy.fingerprint(snapshot(row))},
                                   {'fingerprint': action.args['expected']})
        elif row is not None:
            raise HTTPException(409, 'This record has changed since the proposal')
    before = snapshot(row) if row else None
    if kind in policy.DELETE_KINDS:
        delete_rights(kind, row, user)
    company = await company_or_404(db, action.enterprise_id, action.company_id) if action.company_id else None
    if company and company.archived_at is not None:
        raise HTTPException(409, 'Restore the company first')
    target_id = action.target_id
    bank_lines = []
    if kind == 'create_task':
        out = await accounting_tasks.create_task(TaskIn(**body), user=user, db=db)
        target_id = out.id
    elif kind == 'update_task':
        await accounting_tasks.update_task(row.id, TaskPatch(**body), user=user, db=db)
    elif kind == 'delete_task':
        # Persist the complete row in undo_data BEFORE the handler hard-deletes it, in this same
        # savepoint/outer transaction. The final result adds the after snapshot on success.
        action.undo_data = {'before': before, 'after': None}
        await db.execute(update(AAAssistantAction).where(AAAssistantAction.enterprise_id == action.enterprise_id,
            AAAssistantAction.id == action.id).values(undo_data=action.undo_data))
        await accounting_tasks.delete_task(row.id, user=user, db=db)
    elif kind == 'update_document':
        await protect_document_edit(db, company, row, body)
        await accounting.patch_document(row.id, DocumentPatch(**body), user=user, db=db)
    elif kind == 'delete_document':
        bank_lines = await deletion.protect_document(db, company, row)
        await accounting.delete_document(row.id, user=user, db=db)
    elif kind == 'assign_filing':
        await protect_filing(db, company, body)
        await accounting_work.put_work_item(WorkItemIn(**body), user=user, db=db)
        row = await filing_row(db, action.enterprise_id, body)
        target_id = row.id
    await db.flush()
    after_row = (await db.execute(select(REGISTRY[kind].model).where(
        REGISTRY[kind].model.enterprise_id == action.enterprise_id,
        REGISTRY[kind].model.id == target_id).execution_options(populate_existing=True))).scalar_one_or_none() if kind != 'delete_task' else None
    return target_id, {'before': before, 'after': snapshot(after_row) if after_row else None,
                       'bank_line_ids': [str(line.id) for line in bank_lines]}


# The area each action kind changes; a person without that area (Team page access, or maintenance) can't confirm,
# undo or see it, exactly as on the screen it belongs to.
KIND_AREAS = {'create_task': 'work', 'update_task': 'work', 'delete_task': 'work', 'assign_filing': 'work',
              'update_document': 'documents', 'delete_document': 'documents'}


async def require_area(db: AsyncSession, user: User, kind: str) -> None:
    area = KIND_AREAS.get(kind)
    if area and not (await features.effective_for(db, user)).get(area, True):
        raise HTTPException(403, features.no_access_message(area))


async def confirm(db: AsyncSession, user: User, action_id: uuid.UUID) -> ActionOut:
    action = await get_action(db, user, action_id, own=True)
    now = datetime.now(timezone.utc)
    if action.status == 'proposed' and now >= action.expires_at:
        action.status = 'expired'
        await db.commit()
    policy.check_confirm(action.status, action.expires_at, now)
    await require_area(db, user, action.kind)
    await check_caps(db, action.enterprise_id, user.id, action.kind, now)
    try:
        async with db.begin_nested():
            await require_write(db, user)
            async with route_session(db, user) as child:
                with audit.casper_context(person_name(user)):
                    target, undo = await apply(child, action, user)
            action.target_id = target
            action.undo_data = undo
            action.status = 'applied'
            action.applied_at = datetime.now(timezone.utc)
            action.undo_until = action.applied_at + policy.UNDO_TTL
    except Exception as exc:
        logger.info('assistant_action_failed action=%s error=%s', action_id, type(exc).__name__)
        await db.refresh(action)
        action.status = 'failed'
        action.error = str(exc.detail) if isinstance(exc, HTTPException) else 'The change could not be applied'
        await db.commit()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(500, action.error) from exc
    await db.commit()
    return await action_out(db, action, user)


async def cancel(db: AsyncSession, user: User, action_id: uuid.UUID) -> ActionOut:
    action = await get_action(db, user, action_id, own=True)
    now = datetime.now(timezone.utc)
    if action.status == 'proposed' and now >= action.expires_at:
        action.status = 'expired'
        await db.commit()
    policy.check_confirm(action.status, action.expires_at, now)
    action.status = 'cancelled'
    await db.commit()
    return await action_out(db, action, user)


async def restore_document(db: AsyncSession, action: AAAssistantAction, doc: AADocument, user: User) -> None:
    from app.routers.accounting import _bank_after_document_change, relink_receipts
    from app.services.accounting import duplicates
    company = await company_or_404(db, action.enterprise_id, doc.company_id)
    original = (await db.execute(select(AAFile).where(AAFile.id == doc.file_id,
                                                 AAFile.enterprise_id == action.enterprise_id))).scalar_one()
    duplicate = (await db.execute(select(AADocument.id).join(AAFile, AAFile.id == AADocument.file_id).where(
        AADocument.enterprise_id == action.enterprise_id, AAFile.enterprise_id == action.enterprise_id,
        AADocument.company_id == doc.company_id, AADocument.deleted_at.is_(None),
        AAFile.sha256 == original.sha256, AAFile.id != original.id).limit(1))).first()
    if duplicate:
        raise HTTPException(409, 'This file has been re-uploaded and kept as another document')
    # Check retained history before clearing the tombstone. Includes dates, fiscal period and bank dependencies.
    lines = await deletion.protect_document(db, company, doc)
    from app.models.accounting import AABankLine
    previous_lines = list((await db.execute(select(AABankLine).where(
        AABankLine.enterprise_id == action.enterprise_id, AABankLine.company_id == doc.company_id,
        AABankLine.id.in_([uuid.UUID(i) for i in (action.undo_data or {}).get('bank_line_ids', [])])
    ))).scalars())
    lines = list({line.id: line for line in [*lines, *previous_lines]}.values())
    await deletion.protect_bank_links(db, company, lines)
    await deletion.protect_history(db, company, [doc.doc_date, doc.paid_on, *[l.line_date for l in lines]],
        [(doc.period_year, doc.period_quarter)] if doc.period_year and doc.period_quarter else [])
    before = snapshot(doc)
    doc.deleted_at = None
    await db.flush()
    await relink_receipts(db, doc.company_id)
    await _bank_after_document_change(db, doc, company, line_ids={l.id for l in lines})
    await duplicates.refresh_flags(db, doc.company_id)
    audit.record(db, ent=action.enterprise_id, company_id=doc.company_id, user=user, entity='document',
                 entity_id=doc.id, action='restore', label=audit.document_label(doc), before=before, after=snapshot(doc))


async def execute_undo(db: AsyncSession, action: AAAssistantAction, user: User) -> None:
    from app.routers import accounting, accounting_tasks, accounting_work
    kind, data = action.kind, action.undo_data or {}
    row = await target_row(db, action)
    before, after = data.get('before'), data.get('after')
    if kind == 'delete_task':
        if row is not None or not before:
            raise HTTPException(409, 'This task has changed since Casper deleted it')
        values = typed_values(AATask, before)
        await accounting_tasks._check_links(db, action.enterprise_id, values)
        for key in ('created_by', 'completed_by'):
            if values[key] is not None:
                person = (await db.execute(select(User.id).where(User.id == values[key],
                    (User.id == action.enterprise_id) | (User.enterprise_id == action.enterprise_id)))).first()
                if person is None:
                    raise HTTPException(409, 'A person linked to this task has left the firm. Use the Tasks screen.')
        row = AATask(**values)
        db.add(row)
        audit.record(db, ent=action.enterprise_id, company_id=row.company_id, user=user, entity='task',
                     entity_id=row.id, action='restore', label=row.title, before=None, after=before)
        return
    if row is None or not after:
        raise HTTPException(409, 'This record has changed since Casper changed it')
    policy.check_unchanged(snapshot(row), after)
    if kind == 'create_task':
        await accounting_tasks.delete_task(row.id, user=user, db=db)
    elif kind == 'update_task':
        await accounting_tasks.update_task(row.id, TaskPatch(**{k: before[k] for k in TASK_EDIT}), user=user, db=db)
        # Restore completion/automatic-assignment provenance exactly, after running route validation/audit.
        metadata = ('completed_at', 'completed_by', 'assigned_auto')
        old = audit.snapshot(row, metadata)
        restored = typed_values(AATask, before)
        for k in metadata:
            setattr(row, k, restored[k])
        audit.record(db, ent=action.enterprise_id, company_id=row.company_id, user=user, entity='task',
                     entity_id=row.id, action='update', label=row.title, before=old, after=audit.snapshot(row, metadata))
    elif kind == 'update_document':
        company = await company_or_404(db, action.enterprise_id, row.company_id)
        body = {k: before[k] for k in DOC_EDIT}
        await protect_document_edit(db, company, row, body)
        # A previous monthly/automatic period may not be expressible as DocumentPatch's quarter pair.
        # Validate and apply the editable fields through the route, then restore exact period/flag metadata.
        route_body = {k: v for k, v in body.items() if k not in {'period_year', 'period_quarter'}}
        await accounting.patch_document(row.id, DocumentPatch(**route_body), user=user, db=db)
        metadata = ('period_locked', 'period_month', 'period_year', 'period_quarter', 'review_reasons', 'needs_review')
        old = audit.snapshot(row, metadata)
        for k in metadata:
            setattr(row, k, before[k])
        audit.record(db, ent=action.enterprise_id, company_id=row.company_id, user=user, entity='document',
                     entity_id=row.id, action='update', label=audit.document_label(row), before=old,
                     after=audit.snapshot(row, metadata))
    elif kind == 'delete_document':
        delete_rights(kind, row, user)
        await restore_document(db, action, row, user)
    elif kind == 'assign_filing':
        body = action.args['body']
        company = await company_or_404(db, action.enterprise_id, action.company_id)
        await protect_filing(db, company, body)
        previous = before or {'assignee_id': None, 'status_override': '', 'assigned_auto': False}
        await accounting_work.put_work_item(WorkItemIn(**{k: body[k] for k in ('company_id', 'year', 'quarter', 'form')},
            assignee_id=previous['assignee_id'], status_override=previous['status_override']), user=user, db=db)
        old = {'assigned_auto': row.assigned_auto}
        row.assigned_auto = previous['assigned_auto']
        audit.record(db, ent=action.enterprise_id, company_id=row.company_id, user=user, entity='work_item',
                     entity_id=f'{row.year}:{row.quarter}:{row.form}', action='update', label=action.summary,
                     before=old, after={'assigned_auto': row.assigned_auto})


async def undo(db: AsyncSession, user: User, action_id: uuid.UUID) -> ActionOut:
    action = await get_action(db, user, action_id)
    policy.check_undo(action.status, action.undo_until, datetime.now(timezone.utc))
    await require_write(db, user)
    await require_area(db, user, action.kind)
    try:
        async with db.begin_nested():
            async with route_session(db, user) as child:
                with audit.casper_context(person_name(user)):
                    await execute_undo(child, action, user)
            action.status = 'undone'
            action.undone_at = datetime.now(timezone.utc)
            action.undone_by = user.id
    except HTTPException as exc:
        raise HTTPException(409, str(exc.detail)) from None
    await db.commit()
    return await action_out(db, action, user)


async def list_actions(db: AsyncSession, user: User) -> list[ActionOut]:
    ent, now = scope_for(user), datetime.now(timezone.utc)
    a = AAAssistantAction
    # Purge all expired task restore payloads, including rows older than the list's seven-day window.
    await db.execute(update(a).where(a.enterprise_id == ent, a.kind == 'delete_task',
        a.undo_until <= now, a.undo_data.is_not(None)).values(undo_data=None))
    await db.execute(update(a).where(a.enterprise_id == ent, a.status == 'proposed',
                                    a.expires_at <= now).values(status='expired'))
    query = select(a).where(a.enterprise_id == ent, or_(a.created_at >= now - policy.UNDO_TTL,
        a.undo_until > now))
    if user.role not in MANAGER_ROLES:
        query = query.where(a.user_id == user.id)
    rows = (await db.execute(query.order_by(a.created_at.desc()))).scalars().all()
    await db.commit()
    allowed = (await permission(db, user))['allowed']
    areas = await features.effective_for(db, user)
    visible = [r for r in rows if areas.get(KIND_AREAS.get(r.kind, ''), True)]  # nothing from areas they can't use
    return [await action_out(db, row, user, allowed) for row in visible]

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user, require_roles
from app.database import get_db_session
from app.models import User, UserRole
from app.services.clients import get_request_client_id
from app.services.notifications import record_notification

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskRead(BaseModel):
    id: str
    workflow_id: str | None
    client_id: str | None
    department: str
    assigned_to: str | None
    instructions: str
    required_actions: list[str]
    deadline: str | None
    depends_on: list[str]
    status: str
    created_at: str
    updated_at: str


class TaskStatusUpdate(BaseModel):
    status: str


class TaskAssignmentUpdate(BaseModel):
    assigned_to: str | None = None


@router.get("", response_model=list[TaskRead])
async def list_tasks(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    department: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[TaskRead]:
    client_id = await get_request_client_id(session, current_user)
    result = await session.execute(
        text(
            """
            SELECT id::text, workflow_id::text, client_id::text, department,
                   assigned_to::text, instructions, required_actions, deadline::text,
                   depends_on, status::text, created_at::text, updated_at::text
            FROM department_tasks
            WHERE client_id = :client_id
              AND (CAST(:department AS text) IS NULL OR department = CAST(:department AS text))
              AND (CAST(:status AS text) IS NULL OR status::text = CAST(:status AS text))
            ORDER BY created_at DESC
            """
        ),
        {"client_id": client_id, "department": department, "status": status_filter},
    )
    return [_task_from_row(row) for row in result]


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(
    task_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TaskRead:
    client_id = await get_request_client_id(session, current_user)
    row = await _fetch_task(session, task_id, client_id)
    return _task_from_row(row)


@router.patch("/{task_id}/status", response_model=TaskRead)
async def update_task_status(
    task_id: str,
    payload: TaskStatusUpdate,
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.admin, UserRole.executive, UserRole.department_head)),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TaskRead:
    if payload.status not in {"queued", "in_progress", "blocked", "done"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid status")
    client_id = await get_request_client_id(session, current_user)
    result = await session.execute(
        text(
            """
            UPDATE department_tasks
            SET status = :status, updated_at = now()
            WHERE id = :task_id AND client_id = :client_id
            RETURNING id::text, workflow_id::text, client_id::text, department,
                      assigned_to::text, instructions, required_actions, deadline::text,
                      depends_on, status::text, created_at::text, updated_at::text
            """
        ),
        {"task_id": task_id, "client_id": client_id, "status": payload.status},
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    await record_notification(
        session,
        client_id=client_id,
        workflow_id=row.workflow_id,
        task_id=row.id,
        event_type="task.status_updated",
        channel="audit",
        payload={"status": payload.status, "updated_by": str(current_user.id)},
        commit=False,
    )
    await session.commit()
    return _task_from_row(row)


@router.patch("/{task_id}/assignment", response_model=TaskRead)
async def update_task_assignment(
    task_id: str,
    payload: TaskAssignmentUpdate,
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.admin, UserRole.executive, UserRole.department_head)),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TaskRead:
    client_id = await get_request_client_id(session, current_user)
    result = await session.execute(
        text(
            """
            UPDATE department_tasks
            SET assigned_to = :assigned_to, updated_at = now()
            WHERE id = :task_id AND client_id = :client_id
            RETURNING id::text, workflow_id::text, client_id::text, department,
                      assigned_to::text, instructions, required_actions, deadline::text,
                      depends_on, status::text, created_at::text, updated_at::text
            """
        ),
        {"task_id": task_id, "client_id": client_id, "assigned_to": payload.assigned_to},
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    await session.commit()
    return _task_from_row(row)


async def _fetch_task(session: AsyncSession, task_id: str, client_id: str):
    result = await session.execute(
        text(
            """
            SELECT id::text, workflow_id::text, client_id::text, department,
                   assigned_to::text, instructions, required_actions, deadline::text,
                   depends_on, status::text, created_at::text, updated_at::text
            FROM department_tasks
            WHERE id = :task_id AND client_id = :client_id
            """
        ),
        {"task_id": task_id, "client_id": client_id},
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return row


def _task_from_row(row) -> TaskRead:
    data = dict(row._mapping)
    data["required_actions"] = _json_list(data["required_actions"])
    data["depends_on"] = _json_list(data["depends_on"])
    return TaskRead(**data)


def _json_list(value) -> list[str]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    return []

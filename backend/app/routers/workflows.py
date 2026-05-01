import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user, require_roles
from app.database import get_db_session
from app.models import User, UserRole
from app.services.clients import get_request_client_id
from app.workflow.audit import write_audit
from app.workflow.runtime import (
    approve_and_resume,
    reject_and_loop,
    run_until_approval_pause,
    workflow_row_to_dict,
)
from app.workflow.schemas import (
    AuditRead,
    ObjectiveCreate,
    ReviewRequest,
    WorkflowCreated,
    WorkflowRead,
    WorkflowState,
)

router = APIRouter(tags=["workflows"])


@router.post("/objectives", response_model=WorkflowCreated, status_code=status.HTTP_201_CREATED)
async def submit_objective(
    payload: ObjectiveCreate,
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.admin, UserRole.executive, UserRole.department_head)),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WorkflowCreated:
    client_id = await get_request_client_id(session, current_user)
    result = await session.execute(
        text(
            """
            INSERT INTO workflow_states (
                client_id, objective_text, department, initiated_by,
                priority, approval_status, status, state_blob
            )
            VALUES (
                :client_id, :objective_text, :department, :initiated_by,
                :priority, 'pending', 'created', '{}'::jsonb
            )
            RETURNING id
            """
        ),
        {
            "client_id": client_id,
            "objective_text": payload.objective_text,
            "department": payload.department,
            "initiated_by": str(current_user.id),
            "priority": payload.priority,
        },
    )
    workflow_id = str(result.scalar_one())
    state = WorkflowState(
        workflow_id=workflow_id,
        objective_id=workflow_id,
        objective_text=payload.objective_text,
        client_id=client_id,
        department=payload.department,
        initiated_by=str(current_user.id),
        priority=payload.priority,
    )
    await session.execute(
        text(
            """
            UPDATE workflow_states
            SET state_blob = CAST(:state_blob AS jsonb)
            WHERE id = :workflow_id
            """
        ),
        {"workflow_id": workflow_id, "state_blob": json.dumps(state.model_dump(mode="json"))},
    )
    await session.commit()
    await write_audit(
        session,
        workflow_id,
        "human",
        "objective.submitted",
        input_summary=payload.objective_text[:240],
    )
    state = await run_until_approval_pause(session, state)
    return WorkflowCreated(
        workflow_id=workflow_id,
        status="awaiting_approval",
        approval_status=state.approval_status,
    )


@router.get("/workflows", response_model=list[WorkflowRead])
async def list_workflows(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[WorkflowRead]:
    client_id = await get_request_client_id(session, current_user)
    result = await session.execute(
        text(
            """
            SELECT id, client_id, objective_text, department, initiated_by,
                   priority, approval_status, status, reviewer_feedback,
                   state_blob, created_at, updated_at
            FROM workflow_states
            WHERE client_id = :client_id
            ORDER BY created_at DESC
            LIMIT 50
            """
        ),
        {"client_id": client_id},
    )
    return [WorkflowRead(**workflow_row_to_dict(row)) for row in result]


@router.get("/workflows/{workflow_id}", response_model=WorkflowRead)
async def get_workflow(
    workflow_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WorkflowRead:
    client_id = await get_request_client_id(session, current_user)
    row = await _fetch_workflow_row(session, workflow_id, client_id)
    return WorkflowRead(**workflow_row_to_dict(row))


@router.get("/workflows/{workflow_id}/report")
async def get_report(
    workflow_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    client_id = await get_request_client_id(session, current_user)
    row = await _fetch_workflow_row(session, workflow_id, client_id)
    state = row.state_blob
    report = state.get("decision_report")
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Decision report not ready")
    return report


@router.post("/workflows/{workflow_id}/approve", response_model=WorkflowRead)
async def approve_workflow(
    workflow_id: str,
    payload: ReviewRequest,
    _approver: Annotated[User, Depends(require_roles(UserRole.admin, UserRole.executive))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WorkflowRead:
    await approve_and_resume(session, workflow_id, payload.feedback)
    row = await _fetch_workflow_row_without_client(session, workflow_id)
    return WorkflowRead(**workflow_row_to_dict(row))


@router.post("/workflows/{workflow_id}/reject", response_model=WorkflowRead)
async def reject_workflow(
    workflow_id: str,
    payload: ReviewRequest,
    _approver: Annotated[User, Depends(require_roles(UserRole.admin, UserRole.executive))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WorkflowRead:
    await reject_and_loop(session, workflow_id, payload.feedback)
    row = await _fetch_workflow_row_without_client(session, workflow_id)
    return WorkflowRead(**workflow_row_to_dict(row))


@router.get("/audit/{workflow_id}", response_model=list[AuditRead])
async def get_audit_log(
    workflow_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[AuditRead]:
    client_id = await get_request_client_id(session, current_user)
    await _fetch_workflow_row(session, workflow_id, client_id)
    result = await session.execute(
        text(
            """
            SELECT id, workflow_id, actor, action, input_summary,
                   output_summary, duration_ms, created_at
            FROM audit_log
            WHERE workflow_id = :workflow_id
            ORDER BY created_at
            """
        ),
        {"workflow_id": workflow_id},
    )
    return [AuditRead(**dict(row._mapping)) for row in result]


async def _fetch_workflow_row(session: AsyncSession, workflow_id: str, client_id: str):
    result = await session.execute(
        text(
            """
            SELECT id, client_id, objective_text, department, initiated_by,
                   priority, approval_status, status, reviewer_feedback,
                   state_blob, created_at, updated_at
            FROM workflow_states
            WHERE id = :workflow_id AND client_id = :client_id
            """
        ),
        {"workflow_id": workflow_id, "client_id": client_id},
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return row


async def _fetch_workflow_row_without_client(session: AsyncSession, workflow_id: str):
    result = await session.execute(
        text(
            """
            SELECT id, client_id, objective_text, department, initiated_by,
                   priority, approval_status, status, reviewer_feedback,
                   state_blob, created_at, updated_at
            FROM workflow_states
            WHERE id = :workflow_id
            """
        ),
        {"workflow_id": workflow_id},
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return row

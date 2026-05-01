import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.kb.retrieval.query_router import resolve_domains
from app.kb.retrieval.searcher import search_kb
from app.workflow.agents import (
    run_decision_maker,
    run_learner,
    run_orchestrator,
    run_task_generator,
)
from app.workflow.audit import timed_node, write_audit
from app.workflow.schemas import WorkflowState
from app.services.notifications import record_notification
from app.celery_tasks import dispatch_tasks_to_queues


async def load_workflow_state(session: AsyncSession, workflow_id: str) -> WorkflowState:
    result = await session.execute(
        text("SELECT state_blob FROM workflow_states WHERE id = :workflow_id"),
        {"workflow_id": workflow_id},
    )
    state_blob = result.scalar_one()
    return WorkflowState.model_validate(state_blob)


async def save_workflow_state(
    session: AsyncSession,
    state: WorkflowState,
    node_name: str,
    status: str,
) -> None:
    state_blob = state.model_dump(mode="json")
    checkpoint_id = await _next_checkpoint_id(session, state.workflow_id)
    await session.execute(
        text(
            """
            UPDATE workflow_states
            SET state_blob = CAST(:state_blob AS jsonb),
                approval_status = :approval_status,
                reviewer_feedback = :reviewer_feedback,
                status = :status,
                updated_at = now()
            WHERE id = :workflow_id
            """
        ),
        {
            "workflow_id": state.workflow_id,
            "state_blob": json.dumps(state_blob),
            "approval_status": state.approval_status,
            "reviewer_feedback": state.reviewer_feedback,
            "status": status,
        },
    )
    await session.execute(
        text(
            """
            INSERT INTO workflow_checkpoints (
                workflow_id, checkpoint_id, node_name, state_blob
            )
            VALUES (
                :workflow_id, :checkpoint_id, :node_name, CAST(:state_blob AS jsonb)
            )
            """
        ),
        {
            "workflow_id": state.workflow_id,
            "checkpoint_id": checkpoint_id,
            "node_name": node_name,
            "state_blob": json.dumps(state_blob),
        },
    )
    await session.commit()


async def run_until_approval_pause(session: AsyncSession, state: WorkflowState) -> WorkflowState:
    if state.reviewer_feedback:
        state.reviewer_feedback = None

    state = await timed_node(
        session,
        state.workflow_id,
        "orchestrator",
        "orchestrator",
        lambda: run_orchestrator(state),
        input_summary=state.objective_text[:240],
    )
    await save_workflow_state(session, state, "orchestrator", "orchestrated")

    async def learner_step() -> WorkflowState:
        domains = await resolve_domains(session, state.client_id, None)
        kb_results = await search_kb(
            session,
            state.client_id,
            state.objective_text,
            domains,
            limit=8,
            threshold=-1.0,
        )
        return await run_learner(state, kb_results, domains)

    state = await timed_node(
        session,
        state.workflow_id,
        "learner",
        "learner",
        learner_step,
        input_summary=f"{len(state.subtasks)} subtasks",
    )
    await save_workflow_state(session, state, "learner", "learned")

    state = await timed_node(
        session,
        state.workflow_id,
        "decision_maker",
        "decision_maker",
        lambda: run_decision_maker(state),
        input_summary="learner report",
    )
    state.approval_status = "pending"
    await save_workflow_state(session, state, "decision_maker", "awaiting_approval")
    await record_notification(
        session,
        client_id=state.client_id,
        workflow_id=state.workflow_id,
        event_type="approval.requested",
        channel="audit",
        payload={"objective": state.objective_text, "department": state.department},
    )
    await write_audit(
        session,
        state.workflow_id,
        "system",
        "workflow.suspended_for_approval",
        output_summary="Awaiting human approval",
    )
    return state


async def approve_and_resume(session: AsyncSession, workflow_id: str, feedback: str | None) -> WorkflowState:
    state = await load_workflow_state(session, workflow_id)
    state.approval_status = "approved"
    state.reviewer_feedback = feedback
    await write_audit(
        session,
        workflow_id,
        "human",
        "human.approved",
        input_summary=feedback,
    )
    state = await timed_node(
        session,
        workflow_id,
        "task_generator",
        "task_generator",
        lambda: run_task_generator(state),
        input_summary="approved decision report",
    )
    db_task_ids = await _persist_department_tasks(session, state)
    await save_workflow_state(session, state, "task_generator", "tasks_generated")
    await record_notification(
        session,
        client_id=state.client_id,
        workflow_id=workflow_id,
        event_type="tasks.generated",
        channel="audit",
        payload={"task_count": len(state.task_assignments)},
    )
    await write_audit(session, workflow_id, "system", "workflow.resumed", output_summary="Tasks generated")
    # Dispatch to department-specific Celery queues (non-blocking)
    if db_task_ids:
        dispatch_tasks_to_queues(db_task_ids)
    return state


async def reject_and_loop(session: AsyncSession, workflow_id: str, feedback: str | None) -> WorkflowState:
    state = await load_workflow_state(session, workflow_id)
    state.approval_status = "rejected"
    state.reviewer_feedback = feedback
    await write_audit(
        session,
        workflow_id,
        "human",
        "human.rejected",
        input_summary=feedback,
    )
    await save_workflow_state(session, state, "human_review", "rejected")
    state = await run_until_approval_pause(session, state)
    await write_audit(
        session,
        workflow_id,
        "system",
        "workflow.looped_after_rejection",
        output_summary="Returned to approval pause after reviewer feedback",
    )
    return state


async def _next_checkpoint_id(session: AsyncSession, workflow_id: str) -> int:
    result = await session.execute(
        text(
            """
            SELECT COALESCE(MAX(checkpoint_id), 0) + 1
            FROM workflow_checkpoints
            WHERE workflow_id = :workflow_id
            """
        ),
        {"workflow_id": workflow_id},
    )
    return int(result.scalar_one())


async def _persist_department_tasks(
    session: AsyncSession, state: WorkflowState
) -> list[tuple[str, str]]:
    """Persist all tasks and return list of (db_task_id, department) for Celery dispatch."""
    dispatched: list[tuple[str, str]] = []
    for task in state.task_assignments:
        result = await session.execute(
            text(
                """
                INSERT INTO department_tasks (
                    workflow_id, client_id, department, instructions,
                    required_actions, deadline, depends_on, status
                )
                VALUES (
                    :workflow_id, :client_id, :department, :instructions,
                    CAST(:required_actions AS jsonb), :deadline,
                    CAST(:depends_on AS jsonb), :status
                )
                RETURNING id
                """
            ),
            {
                "workflow_id": state.workflow_id,
                "client_id": state.client_id,
                "department": task.department,
                "instructions": task.instructions,
                "required_actions": json.dumps(task.required_actions),
                "deadline": task.deadline,
                "depends_on": json.dumps(task.depends_on),
                "status": task.status,
            },
        )
        db_id = str(result.scalar_one())
        dispatched.append((db_id, task.department))
    return dispatched


def workflow_row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row._mapping)
    data["state"] = data.pop("state_blob")
    return data

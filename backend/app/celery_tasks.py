import asyncio

from sqlalchemy import text

from app.celery_app import celery_app, queue_for_department
from app.database import AsyncSessionLocal


@celery_app.task(name="app.celery_tasks.check_approval_expiry")
def check_approval_expiry() -> dict[str, int]:
    return asyncio.run(_check_approval_expiry())


async def _check_approval_expiry() -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                UPDATE workflow_states
                SET status = 'approval_escalated', updated_at = now()
                WHERE status = 'awaiting_approval'
                  AND approval_status = 'pending'
                  AND CAST(state_blob #>> '{decision_report,expires_at}' AS timestamptz) < now()
                RETURNING id
                """
            )
        )
        rows = result.all()
        await session.commit()
    return {"escalated": len(rows)}


@celery_app.task(
    name="app.celery_tasks.process_department_task",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def process_department_task(self, task_id: str) -> dict[str, str]:
    """Receive a department task from its queue and mark it dispatched."""
    try:
        return asyncio.run(_mark_task_dispatched(task_id))
    except Exception as exc:
        raise self.retry(exc=exc)


async def _mark_task_dispatched(task_id: str) -> dict[str, str]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                UPDATE department_tasks
                SET status = 'in_progress', updated_at = now()
                WHERE id = :task_id AND status = 'queued'
                RETURNING id, department
                """
            ),
            {"task_id": task_id},
        )
        row = result.one_or_none()
        await session.commit()
    if row is None:
        return {"task_id": task_id, "status": "not_found_or_already_started"}
    return {"task_id": task_id, "department": row.department, "status": "dispatched"}


def dispatch_tasks_to_queues(db_task_ids: list[tuple[str, str]]) -> None:
    """
    Enqueue persisted department tasks to their department-specific Celery queues.
    db_task_ids: list of (task_id, department) tuples from the database.
    """
    for task_id, department in db_task_ids:
        queue = queue_for_department(department)
        process_department_task.apply_async(
            args=[task_id],
            queue=queue,
        )

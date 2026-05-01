from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest
from sqlalchemy import text

from app.database import AsyncSessionLocal

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics() -> Response:
    registry = CollectorRegistry()
    workflow_count = Gauge(
        "manage_ai_workflows_total",
        "Workflow count by status",
        ["status", "approval_status"],
        registry=registry,
    )
    task_count = Gauge("manage_ai_tasks_total", "Task count by status", ["status"], registry=registry)
    kb_entries = Gauge("manage_ai_kb_entries_total", "Total KB entries", registry=registry)
    approval_queue = Gauge("manage_ai_approval_queue_depth", "Pending approvals", registry=registry)

    async with AsyncSessionLocal() as session:
        workflows = await session.execute(
            text(
                """
                SELECT status, approval_status::text AS approval_status, count(*) AS count
                FROM workflow_states
                GROUP BY status, approval_status
                """
            )
        )
        for row in workflows:
            workflow_count.labels(row.status, row.approval_status).set(row.count)

        tasks = await session.execute(
            text("SELECT status::text AS status, count(*) AS count FROM department_tasks GROUP BY status")
        )
        for row in tasks:
            task_count.labels(row.status).set(row.count)

        kb_total = await session.execute(text("SELECT count(*) FROM kb_entries"))
        kb_entries.set(kb_total.scalar_one())

        pending = await session.execute(
            text("SELECT count(*) FROM workflow_states WHERE status = 'awaiting_approval'")
        )
        approval_queue.set(pending.scalar_one())

    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

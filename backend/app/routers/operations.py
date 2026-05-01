import json
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user, require_roles
from app.database import get_db_session
from app.models import User, UserRole
from app.services.clients import get_request_client_id
from app.services.notifications import record_notification

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/notifications")
async def list_notifications(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[dict]:
    client_id = await get_request_client_id(session, current_user)
    result = await session.execute(
        text(
            """
            SELECT id::text, workflow_id::text, task_id::text, channel, event_type,
                   recipient, payload, status, error_detail, created_at::text, sent_at::text
            FROM notification_events
            WHERE client_id = :client_id
            ORDER BY created_at DESC
            LIMIT 100
            """
        ),
        {"client_id": client_id},
    )
    return [dict(row._mapping) for row in result]


@router.post("/expiry/run")
async def run_expiry_check(
    _admin: Annotated[User, Depends(require_roles(UserRole.admin, UserRole.executive))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, int]:
    result = await session.execute(
        text(
            """
            SELECT id::text, client_id::text, state_blob
            FROM workflow_states
            WHERE status = 'awaiting_approval'
              AND approval_status = 'pending'
            """
        )
    )
    escalated = 0
    for row in result:
        report = (row.state_blob or {}).get("decision_report") or {}
        expires_at = report.get("expires_at")
        if not expires_at:
            continue
        expired = await session.execute(
            text("SELECT CAST(CAST(:expires_at AS text) AS timestamptz) < now()"),
            {"expires_at": expires_at},
        )
        if not expired.scalar_one():
            continue
        await session.execute(
            text(
                """
                UPDATE workflow_states
                SET status = 'approval_escalated', updated_at = now()
                WHERE id = :workflow_id
                """
            ),
            {"workflow_id": row.id},
        )
        await record_notification(
            session,
            client_id=row.client_id,
            workflow_id=row.id,
            event_type="approval.escalated",
            channel="audit",
            payload={"reason": "approval expired", "expires_at": expires_at},
            status="sent",
            commit=False,
        )
        await session.execute(
            text(
                """
                INSERT INTO audit_log (workflow_id, actor, action, output_summary)
                VALUES (:workflow_id, 'system', 'approval.escalated', :summary)
                """
            ),
            {"workflow_id": row.id, "summary": json.dumps({"expires_at": expires_at})},
        )
        escalated += 1
    await session.commit()
    return {"escalated": escalated}

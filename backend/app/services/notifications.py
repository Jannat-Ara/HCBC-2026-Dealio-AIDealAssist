import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def record_notification(
    session: AsyncSession,
    client_id: str | None,
    event_type: str,
    channel: str,
    payload: dict,
    workflow_id: str | None = None,
    task_id: str | None = None,
    recipient: str | None = None,
    status: str = "sent",
    commit: bool = True,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO notification_events (
                workflow_id, task_id, client_id, channel, event_type,
                recipient, payload, status, sent_at
            )
            VALUES (
                :workflow_id, :task_id, :client_id, :channel, :event_type,
                :recipient, CAST(:payload AS jsonb), :status,
                CASE WHEN :status = 'sent' THEN now() ELSE NULL END
            )
            """
        ),
        {
            "workflow_id": workflow_id,
            "task_id": task_id,
            "client_id": client_id,
            "channel": channel,
            "event_type": event_type,
            "recipient": recipient,
            "payload": json.dumps(payload),
            "status": status,
        },
    )
    if commit:
        await session.commit()

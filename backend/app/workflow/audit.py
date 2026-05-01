import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


async def write_audit(
    session: AsyncSession,
    workflow_id: str,
    actor: str,
    action: str,
    input_summary: str | None = None,
    output_summary: str | None = None,
    duration_ms: int | None = None,
    commit: bool = True,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO audit_log (
                workflow_id, actor, action, input_summary, output_summary, duration_ms
            )
            VALUES (
                :workflow_id, :actor, :action, :input_summary, :output_summary, :duration_ms
            )
            """
        ),
        {
            "workflow_id": workflow_id,
            "actor": actor,
            "action": action,
            "input_summary": input_summary,
            "output_summary": output_summary,
            "duration_ms": duration_ms,
        },
    )
    if commit:
        await session.commit()


async def timed_node(
    session: AsyncSession,
    workflow_id: str,
    actor: str,
    action: str,
    fn: Callable[[], Awaitable[T]],
    input_summary: str | None = None,
) -> T:
    started = time.perf_counter()
    await write_audit(
        session,
        workflow_id,
        actor,
        f"{action}.started",
        input_summary=input_summary,
    )
    try:
        result = await fn()
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        await write_audit(
            session,
            workflow_id,
            actor,
            f"{action}.failed",
            output_summary=str(exc),
            duration_ms=duration_ms,
        )
        raise
    duration_ms = int((time.perf_counter() - started) * 1000)
    await write_audit(
        session,
        workflow_id,
        actor,
        f"{action}.completed",
        output_summary="completed",
        duration_ms=duration_ms,
    )
    return result

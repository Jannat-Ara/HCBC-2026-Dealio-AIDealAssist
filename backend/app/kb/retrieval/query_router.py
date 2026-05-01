from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def resolve_domains(
    session: AsyncSession,
    client_id: str,
    requested_domains: list[str] | None,
) -> list[str]:
    if requested_domains:
        return [domain.strip() for domain in requested_domains if domain.strip()]

    result = await session.execute(
        text(
            """
            SELECT name
            FROM kb_domains
            WHERE client_id = :client_id AND is_active = true
            ORDER BY name
            """
        ),
        {"client_id": client_id},
    )
    return [row.name for row in result]

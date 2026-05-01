from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User

DEFAULT_CLIENT_NAME = "Default Client"


async def get_request_client_id(session: AsyncSession, user: User) -> str:
    if user.client_id:
        return str(user.client_id)

    result = await session.execute(
        text(
            """
            INSERT INTO clients (name)
            VALUES (:name)
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """
        ),
        {"name": DEFAULT_CLIENT_NAME},
    )
    client_id = str(result.scalar_one())
    await session.commit()
    return client_id

from redis.asyncio import Redis

from app.config import get_settings


def get_redis() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


async def check_redis() -> bool:
    client = get_redis()
    try:
        return await client.ping()
    finally:
        await client.aclose()

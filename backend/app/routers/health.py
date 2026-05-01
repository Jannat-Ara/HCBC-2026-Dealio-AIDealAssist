from fastapi import APIRouter

from app.database import check_database
from app.redis_client import check_redis

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/db")
async def health_db() -> dict[str, str]:
    return {"status": "ok" if await check_database() else "error"}


@router.get("/redis")
async def health_redis() -> dict[str, str]:
    return {"status": "ok" if await check_redis() else "error"}

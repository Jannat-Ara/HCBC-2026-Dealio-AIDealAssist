from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.security import require_roles
from app.models import User, UserRole
from app.services.llm import SUPPORTED_AGENTS, get_llm_config, smoke_test_agent

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/config")
async def llm_config(
    _admin: Annotated[User, Depends(require_roles(UserRole.admin))],
) -> list[dict[str, str]]:
    return [get_llm_config(agent).__dict__ for agent in sorted(SUPPORTED_AGENTS)]


@router.post("/smoke-test")
async def smoke_test(
    _admin: Annotated[User, Depends(require_roles(UserRole.admin))],
) -> list[dict[str, str]]:
    return [await smoke_test_agent(agent) for agent in sorted(SUPPORTED_AGENTS)]

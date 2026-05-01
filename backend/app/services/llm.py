from dataclasses import dataclass

import httpx
from groq import AsyncGroq

from app.config import get_settings


SUPPORTED_AGENTS = {"orchestrator", "learner", "decision_maker", "task_generator"}


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    agent_name: str


def get_llm_config(agent_name: str) -> LLMConfig:
    if agent_name not in SUPPORTED_AGENTS:
        raise ValueError(f"Unsupported agent: {agent_name}")

    settings = get_settings()
    provider = settings.llm_provider.lower()

    if provider == "groq":
        models = {
            "orchestrator": settings.groq_model_orchestrator,
            "learner": settings.groq_model_learner,
            "decision_maker": settings.groq_model_decision_maker,
            "task_generator": settings.groq_model_task_generator,
        }
        return LLMConfig(provider=provider, model=models[agent_name], agent_name=agent_name)

    if provider == "claude":
        models = {
            "orchestrator": settings.anthropic_model_orchestrator,
            "decision_maker": settings.anthropic_model_decision_maker,
            "learner": settings.ollama_model_learner,
            "task_generator": settings.ollama_model_task_generator,
        }
        return LLMConfig(provider=provider, model=models[agent_name], agent_name=agent_name)

    if provider == "ollama":
        models = {
            "orchestrator": settings.ollama_model_learner,
            "learner": settings.ollama_model_learner,
            "decision_maker": settings.ollama_model_task_generator,
            "task_generator": settings.ollama_model_task_generator,
        }
        return LLMConfig(provider=provider, model=models[agent_name], agent_name=agent_name)

    raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")


def get_llm(agent_name: str):
    config = get_llm_config(agent_name)
    settings = get_settings()
    if config.provider == "groq":
        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is required when LLM_PROVIDER=groq")
        return AsyncGroq(api_key=settings.groq_api_key)
    if config.provider == "ollama":
        return httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=30)
    raise RuntimeError(
        "Claude client is configured as a production placeholder; add Anthropic SDK in hardening."
    )


async def smoke_test_agent(agent_name: str) -> dict[str, str]:
    config = get_llm_config(agent_name)
    settings = get_settings()

    if config.provider != "groq":
        return {
            "agent": agent_name,
            "provider": config.provider,
            "model": config.model,
            "status": "skipped",
        }

    if not settings.groq_api_key:
        return {
            "agent": agent_name,
            "provider": config.provider,
            "model": config.model,
            "status": "missing_api_key",
        }

    client = AsyncGroq(api_key=settings.groq_api_key)
    response = await client.chat.completions.create(
        model=config.model,
        messages=[
            {"role": "system", "content": "You are a concise smoke test responder."},
            {"role": "user", "content": f"Reply with OK for {agent_name}."},
        ],
        max_tokens=8,
        temperature=0,
    )
    content = response.choices[0].message.content or ""
    return {
        "agent": agent_name,
        "provider": config.provider,
        "model": config.model,
        "status": "ok",
        "response": content.strip(),
    }

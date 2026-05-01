import pytest

from app.services.llm import SUPPORTED_AGENTS, get_llm_config


@pytest.mark.parametrize("agent_name", sorted(SUPPORTED_AGENTS))
def test_get_llm_config_for_supported_agents(agent_name: str) -> None:
    config = get_llm_config(agent_name)
    assert config.agent_name == agent_name
    assert config.provider
    assert config.model


def test_get_llm_config_rejects_unknown_agent() -> None:
    with pytest.raises(ValueError):
        get_llm_config("unknown")

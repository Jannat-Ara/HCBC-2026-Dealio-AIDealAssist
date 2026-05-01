import pytest

from app.workflow.agents import (
    run_decision_maker,
    run_learner,
    run_orchestrator,
    run_task_generator,
)
from app.workflow.schemas import WorkflowState


@pytest.fixture
def state() -> WorkflowState:
    return WorkflowState(
        workflow_id="workflow-1",
        objective_id="workflow-1",
        objective_text="Improve invoice approval process using internal finance policy",
        client_id="client-1",
        department="Finance",
        initiated_by="user-1",
        priority="medium",
    )


@pytest.mark.asyncio
async def test_workflow_agent_sequence_pauses_before_tasks(state: WorkflowState) -> None:
    state = await run_orchestrator(state)
    assert len(state.subtasks) == 3

    state = await run_learner(
        state,
        [{"source_file": "policy.txt", "content": "Invoices above 5000 require approval."}],
        ["Finance"],
    )
    assert state.learner_output is not None
    assert state.learner_output.supporting_evidence

    state = await run_decision_maker(state)
    assert state.decision_report is not None
    assert state.task_assignments == []


@pytest.mark.asyncio
async def test_task_generator_requires_decision_report(state: WorkflowState) -> None:
    with pytest.raises(ValueError):
        await run_task_generator(state)


@pytest.mark.asyncio
async def test_task_generator_creates_tasks_after_decision(state: WorkflowState) -> None:
    state = await run_orchestrator(state)
    state = await run_learner(state, [], [])
    state = await run_decision_maker(state)
    state.approval_status = "approved"
    state = await run_task_generator(state)
    assert len(state.task_assignments) == 1
    assert state.task_assignments[0].department == "Finance"

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta

from app.services.llm import get_llm, get_llm_config
from app.workflow.schemas import (
    DecisionReport,
    DepartmentTask,
    LearnerReport,
    Priority,
    SubTask,
    WorkflowState,
)


async def _call_groq(agent_name: str, system_prompt: str, user_prompt: str, max_retries: int = 3) -> dict:
    """Call Groq and return parsed JSON dict. Retries up to max_retries on bad output."""
    config = get_llm_config(agent_name)
    client = get_llm(agent_name)

    last_error: Exception = ValueError("No attempts made")
    for attempt in range(max_retries):
        try:
            response = await client.chat.completions.create(
                model=config.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=1500,
                temperature=0.3,
            )
            raw = response.choices[0].message.content or ""
            # Strip markdown code fences if present
            raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
            # Extract the first JSON object or array
            match = re.search(r"\{[\s\S]*\}", raw)
            if not match:
                raise ValueError(f"No JSON object found in response: {raw[:200]}")
            return json.loads(match.group())
        except Exception as exc:
            last_error = exc
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
    raise last_error


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


# ── Orchestrator ─────────────────────────────────────────────────────────────

_ORCHESTRATOR_SYSTEM = """You are the Orchestrator agent in an autonomous business workflow system.
Decompose the given business objective into 3-5 concrete, actionable subtasks.

Return ONLY a valid JSON object — no extra text:
{
  "subtasks": [
    {
      "title": "Short task title",
      "description": "Detailed description of what needs to be done",
      "department": "Department responsible",
      "priority": "low|medium|high|critical"
    }
  ]
}"""


async def run_orchestrator(state: WorkflowState) -> WorkflowState:
    user_prompt = (
        f"Objective: {state.objective_text}\n"
        f"Department: {state.department}\n"
        f"Priority: {state.priority}\n\n"
        "Break this into 3-5 specific, actionable subtasks."
    )
    try:
        result = await _call_groq("orchestrator", _ORCHESTRATOR_SYSTEM, user_prompt)
        raw_tasks = result.get("subtasks", [])
        if not raw_tasks:
            raise ValueError("Empty subtasks list from LLM")
        state.subtasks = [
            SubTask(
                title=str(t.get("title", "Untitled")),
                description=str(t.get("description", "")),
                department=str(t.get("department", state.department)),
                priority=_safe_priority(t.get("priority"), state.priority),
            )
            for t in raw_tasks[:5]
        ]
    except Exception:
        state.subtasks = _fallback_subtasks(state)
    return state


def _safe_priority(value: object, default: Priority) -> Priority:
    valid: set[str] = {"low", "medium", "high", "critical"}
    return value if isinstance(value, str) and value in valid else default  # type: ignore[return-value]


def _fallback_subtasks(state: WorkflowState) -> list[SubTask]:
    words = state.objective_text.split()
    concise = " ".join(words[:18])
    return [
        SubTask(
            title="Clarify objective scope",
            description=f"Confirm success criteria, constraints, and required inputs for: {concise}",
            department=state.department,
            priority=state.priority,
        ),
        SubTask(
            title="Research internal knowledge",
            description=f"Search company knowledge for policies, risks, and examples related to: {concise}",
            department=state.department,
            priority=state.priority,
        ),
        SubTask(
            title="Prepare execution recommendation",
            description=f"Summarize feasibility, risks, and next actions for: {concise}",
            department=state.department,
            priority=state.priority,
        ),
    ]


# ── Learner ──────────────────────────────────────────────────────────────────

_LEARNER_SYSTEM = """You are the Learner agent. Assess whether a business objective is feasible
based on internal knowledge base content and identified subtasks.

Return ONLY a valid JSON object — no extra text:
{
  "feasibility_score": 0.0,
  "confidence": 0.0,
  "supporting_evidence": ["quote or reference from KB content"],
  "identified_gaps": ["what knowledge is missing"],
  "recommended_adjustments": ["what changes would improve success odds"]
}

Scores are between 0.0 (impossible/unknown) and 1.0 (fully feasible/certain)."""


async def run_learner(state: WorkflowState, kb_results: list[dict], domains: list[str]) -> WorkflowState:
    if kb_results:
        kb_context = "\n\n".join(
            f"[Source: {r.get('source_file', 'unknown')} | Score: {r.get('similarity_score', 0):.2f}]\n{r.get('content', '')[:600]}"
            for r in kb_results[:5]
        )
    else:
        kb_context = "No relevant documents found in the knowledge base."

    subtasks_text = "\n".join(f"  - {s.title}: {s.description}" for s in state.subtasks)

    user_prompt = (
        f"Objective: {state.objective_text}\n"
        f"Department: {state.department}\n\n"
        f"Subtasks:\n{subtasks_text}\n\n"
        f"Internal Knowledge Base Content:\n{kb_context}\n\n"
        "Assess feasibility based on the available internal knowledge."
    )
    try:
        result = await _call_groq("learner", _LEARNER_SYSTEM, user_prompt)
        state.learner_output = LearnerReport(
            feasibility_score=_clamp(result.get("feasibility_score", 0.5)),
            confidence=_clamp(result.get("confidence", 0.5)),
            supporting_evidence=_str_list(result.get("supporting_evidence", [])),
            identified_gaps=_str_list(result.get("identified_gaps", [])),
            recommended_adjustments=_str_list(result.get("recommended_adjustments", [])),
            domains_searched=domains,
        )
    except Exception:
        # Fallback: derive rough scores from KB result count
        has_evidence = bool(kb_results)
        state.learner_output = LearnerReport(
            feasibility_score=0.72 if has_evidence else 0.38,
            confidence=0.75 if has_evidence else 0.42,
            supporting_evidence=[
                f"{r.get('source_file', 'unknown')}: {r.get('content', '')[:200]}"
                for r in kb_results[:3]
            ],
            identified_gaps=[] if has_evidence else ["No relevant internal KB evidence was found."],
            recommended_adjustments=[
                "Upload relevant internal policy documents before execution.",
                "Proceed with human-reviewed decision report.",
            ],
            domains_searched=domains,
        )
    return state


def _str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


# ── Decision Maker ────────────────────────────────────────────────────────────

_DECISION_MAKER_SYSTEM = """You are the Decision Maker agent. Synthesize a learner feasibility report
and produce a structured decision recommendation for human review.

Return ONLY a valid JSON object — no extra text:
{
  "recommendation": "Clear recommendation sentence",
  "confidence_score": 0.0,
  "risk_level": "low|medium|high|critical",
  "requires_expert_review": false,
  "markdown_summary": "## Decision Report\\n\\n**full markdown text here**"
}

confidence_score is between 0.0 and 1.0.
requires_expert_review should be true when confidence < 0.5 or risk_level is high/critical."""


async def run_decision_maker(state: WorkflowState) -> WorkflowState:
    learner = state.learner_output
    fs = learner.feasibility_score if learner else 0.35
    conf = learner.confidence if learner else 0.35
    evidence_text = "\n".join(learner.supporting_evidence[:3]) if learner and learner.supporting_evidence else "None"
    gaps_text = "\n".join(learner.identified_gaps) if learner and learner.identified_gaps else "None"
    adj_text = "\n".join(learner.recommended_adjustments[:3]) if learner and learner.recommended_adjustments else "None"

    user_prompt = (
        f"Objective: {state.objective_text}\n"
        f"Department: {state.department}\n"
        f"Priority: {state.priority}\n\n"
        f"Learner Assessment:\n"
        f"  Feasibility score: {fs:.2f}\n"
        f"  Confidence: {conf:.2f}\n"
        f"  Supporting evidence:\n{evidence_text}\n"
        f"  Identified gaps:\n{gaps_text}\n"
        f"  Recommended adjustments:\n{adj_text}\n\n"
        "Produce a decision recommendation with risk assessment. "
        "Human approval is required before any tasks are generated."
    )
    now = datetime.now(UTC)
    try:
        result = await _call_groq("decision_maker", _DECISION_MAKER_SYSTEM, user_prompt)
        risk = result.get("risk_level", "medium")
        if risk not in {"low", "medium", "high", "critical"}:
            risk = "medium"
        state.decision_report = DecisionReport(
            recommendation=str(result.get("recommendation", "See markdown summary.")),
            confidence_score=_clamp(result.get("confidence_score", conf)),
            risk_level=risk,  # type: ignore[arg-type]
            supporting_data={
                "learner_feasibility": fs,
                "external_connectors": {
                    "market_data": "not configured",
                    "regulatory": "not configured",
                    "economic": "not configured",
                },
            },
            requires_expert_review=bool(result.get("requires_expert_review", conf < 0.5)),
            markdown_summary=str(result.get("markdown_summary", f"## Decision Report\n\n**Recommendation:** {result.get('recommendation', '')}")),
            generated_at=now,
            expires_at=now + timedelta(hours=48),
        )
    except Exception:
        risk = "low" if conf >= 0.7 and fs >= 0.7 else ("high" if conf < 0.45 else "medium")
        recommendation = (
            "Approve with standard monitoring"
            if risk in {"low", "medium"}
            else "Do not approve until knowledge gaps are resolved"
        )
        state.decision_report = DecisionReport(
            recommendation=recommendation,
            confidence_score=conf,
            risk_level=risk,  # type: ignore[arg-type]
            supporting_data={
                "learner_feasibility": fs,
                "external_connectors": {
                    "market_data": "not configured",
                    "regulatory": "not configured",
                    "economic": "not configured",
                },
            },
            requires_expert_review=risk in {"high", "critical"},
            markdown_summary=(
                f"## Decision Report\n\n"
                f"**Objective:** {state.objective_text}\n\n"
                f"**Recommendation:** {recommendation}\n\n"
                f"**Risk level:** {risk}\n\n"
                f"**Confidence:** {conf:.2f}\n\n"
                "Human approval is required before task generation."
            ),
            generated_at=now,
            expires_at=now + timedelta(hours=48),
        )
    return state


# ── Task Generator ────────────────────────────────────────────────────────────

_TASK_GENERATOR_SYSTEM = """You are the Task Generator agent. Convert an approved decision report
into specific, department-appropriate tasks that need to be executed.

Return ONLY a valid JSON object — no extra text:
{
  "tasks": [
    {
      "department": "Department name",
      "instructions": "Clear instructions for the department team",
      "required_actions": ["Action 1", "Action 2", "Action 3"]
    }
  ]
}

Generate 2-4 tasks. Each task must have concrete, actionable instructions."""


async def run_task_generator(state: WorkflowState) -> WorkflowState:
    if not state.decision_report:
        raise ValueError("Decision report is required before task generation")

    subtasks_text = "\n".join(f"  - {s.title}: {s.description}" for s in state.subtasks)
    learner_adj = (
        "\n".join(state.learner_output.recommended_adjustments[:3])
        if state.learner_output
        else "None"
    )

    user_prompt = (
        f"Objective: {state.objective_text}\n"
        f"Department: {state.department}\n"
        f"Priority: {state.priority}\n\n"
        f"Approved decision:\n{state.decision_report.recommendation}\n\n"
        f"Subtasks identified:\n{subtasks_text}\n\n"
        f"Learner recommended adjustments:\n{learner_adj}\n\n"
        f"Generate 2-4 specific tasks for the {state.department} department to implement this decision."
    )
    try:
        result = await _call_groq("task_generator", _TASK_GENERATOR_SYSTEM, user_prompt)
        raw_tasks = result.get("tasks", [])
        if not raw_tasks:
            raise ValueError("Empty tasks list from LLM")
        state.task_assignments = [
            DepartmentTask(
                task_id=f"{state.workflow_id}-task-{i + 1}",
                department=str(t.get("department", state.department)),
                instructions=str(t.get("instructions", "")),
                required_actions=_str_list(t.get("required_actions", [])),
            )
            for i, t in enumerate(raw_tasks[:5])
        ]
    except Exception:
        state.task_assignments = [_fallback_task(state)]
    return state


def _fallback_task(state: WorkflowState) -> DepartmentTask:
    recommendation = state.decision_report.recommendation if state.decision_report else "See decision report."
    return DepartmentTask(
        task_id=f"{state.workflow_id}-task-1",
        department=state.department,
        instructions=f"Execute approved objective: {state.objective_text}. Follow recommendation: {recommendation}.",
        required_actions=[
            "Review the approved decision report",
            "Assign an owner",
            "Confirm completion criteria",
            "Begin execution and update task status",
        ],
    )

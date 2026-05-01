from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


Priority = Literal["low", "medium", "high", "critical"]
ApprovalStatus = Literal["pending", "approved", "rejected"]
TaskStatus = Literal["queued", "in_progress", "blocked", "done"]
RiskLevel = Literal["low", "medium", "high", "critical"]


class ObjectiveCreate(BaseModel):
    objective_text: str = Field(min_length=10)
    department: str = Field(min_length=1)
    priority: Priority = "medium"


class SubTask(BaseModel):
    title: str
    description: str
    department: str
    priority: Priority = "medium"


class LearnerReport(BaseModel):
    feasibility_score: float
    supporting_evidence: list[str]
    identified_gaps: list[str]
    recommended_adjustments: list[str]
    confidence: float
    domains_searched: list[str]


class DecisionReport(BaseModel):
    recommendation: str
    confidence_score: float
    risk_level: RiskLevel
    supporting_data: dict[str, Any]
    requires_expert_review: bool
    markdown_summary: str
    generated_at: datetime
    expires_at: datetime


class DepartmentTask(BaseModel):
    task_id: str
    department: str
    assigned_to: str | None = None
    instructions: str
    required_actions: list[str]
    deadline: datetime | None = None
    depends_on: list[str] = []
    status: TaskStatus = "queued"


class AuditEntry(BaseModel):
    event_id: str
    workflow_id: str
    actor: str
    action: str
    input_summary: str | None = None
    output_summary: str | None = None
    timestamp: datetime
    duration_ms: int | None = None


class WorkflowState(BaseModel):
    workflow_id: str
    objective_id: str
    objective_text: str
    client_id: str
    department: str
    initiated_by: str
    priority: Priority
    subtasks: list[SubTask] = []
    learner_output: LearnerReport | None = None
    decision_report: DecisionReport | None = None
    approval_status: ApprovalStatus = "pending"
    reviewer_feedback: str | None = None
    task_assignments: list[DepartmentTask] = []
    audit_trail: list[AuditEntry] = []


class WorkflowCreated(BaseModel):
    workflow_id: UUID
    status: str
    approval_status: ApprovalStatus


class WorkflowRead(BaseModel):
    id: UUID
    client_id: UUID | None
    objective_text: str
    department: str
    initiated_by: UUID | None
    priority: Priority
    approval_status: ApprovalStatus
    status: str
    reviewer_feedback: str | None = None
    state: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ReviewRequest(BaseModel):
    feedback: str | None = None


class AuditRead(BaseModel):
    id: UUID
    workflow_id: UUID | None
    actor: str
    action: str
    input_summary: str | None
    output_summary: str | None
    duration_ms: int | None
    created_at: datetime

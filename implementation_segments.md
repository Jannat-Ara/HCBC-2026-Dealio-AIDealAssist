# Detailed Implementation Plan

This plan breaks the autonomous AI agent system into four reviewable implementation segments. Each segment has a clear goal, build order, technical tasks, validation steps, and approval criteria. Do not start the next segment until the current segment is working and reviewed.

---

## Implementation Principles

- Build the system vertically, but review it segment by segment.
- Keep testing mode simple first: Groq API, simple prompts, synthetic data, and local Docker services.
- Keep production concerns visible, but avoid hardening too early.
- Make every major workflow observable through logs, database records, and API responses.
- Enforce the human approval gate in backend workflow logic, not only in the UI.
- Treat the custom knowledge base as a first-class backend service, not a helper script.

---

## Proposed Repository Structure

```text
.
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── auth/
│   │   ├── routers/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── tests/
│   ├── migrations/
│   └── pyproject.toml
├── agent_runtime/
│   ├── graph.py
│   ├── state.py
│   ├── llm.py
│   ├── agents/
│   │   ├── orchestrator.py
│   │   ├── learner.py
│   │   ├── decision_maker.py
│   │   └── task_generator.py
│   ├── connectors/
│   └── tests/
├── kb_service/
│   ├── api.py
│   ├── ingestion/
│   │   ├── chunker.py
│   │   ├── embedder.py
│   │   ├── pipeline.py
│   │   └── parsers/
│   ├── retrieval/
│   │   ├── query_router.py
│   │   ├── reranker.py
│   │   └── searcher.py
│   └── tests/
├── frontend/
├── infrastructure/
│   ├── docker-compose.yml
│   ├── prometheus/
│   └── grafana/
├── docs/
└── scripts/
```

This structure can be adjusted during implementation, but the ownership boundaries should stay clear:

- `backend` owns API, auth, workflow endpoints, task endpoints, audit endpoints.
- `agent_runtime` owns LangGraph state, agents, prompts, and workflow execution.
- `kb_service` owns document ingestion, embeddings, retrieval, and KB APIs.
- `frontend` owns the dashboard.
- `infrastructure` owns Docker Compose, monitoring, and deployment config.

---

## Segment 1: Core Foundation

**Goal:** Establish the backend, database, infrastructure, auth, and LLM configuration needed by every later segment.

### Build Order

1. Create repository folders and baseline app structure.
2. Add environment configuration.
3. Add Docker Compose for PostgreSQL, Redis, backend, and optional admin tools.
4. Configure PostgreSQL with pgvector.
5. Add database schema and migrations.
6. Build FastAPI skeleton.
7. Add JWT auth foundation.
8. Add LLM provider configuration and Groq smoke tests.
9. Add base logging and health checks.

### Technical Tasks

#### 1. Environment Configuration

Create `.env.example` with:

```text
APP_ENV=local
DATABASE_URL=postgresql+asyncpg://app:app@postgres:5432/manage_ai
REDIS_URL=redis://redis:6379/0
JWT_SECRET_KEY=change-me
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
LLM_PROVIDER=groq
GROQ_API_KEY=
ANTHROPIC_API_KEY=
OLLAMA_BASE_URL=http://ollama:11434
```

Implementation notes:

- Do not commit real API keys.
- Load configuration through a typed settings object.
- Fail fast when required settings are missing.

#### 2. Docker Compose Foundation

Add services:

- `postgres`
- `redis`
- `backend`
- optional `pgadmin` or database admin tool

PostgreSQL requirements:

- Enable `pgvector`.
- Persist database data in a named volume.
- Expose port `5432` only for local development.

Redis requirements:

- Persist only if needed for local debugging.
- Expose port `6379` for local development.

#### 3. Database Schema

Create initial tables:

- `users`
- `clients`
- `roles`
- `workflow_states`
- `workflow_checkpoints`
- `audit_log`
- `kb_domains`
- `kb_entries`
- `kb_ingestion_log`
- `department_tasks`

Minimum schema requirements:

- All major records use UUID primary keys.
- All tables include `created_at`.
- Mutable operational tables include `updated_at`.
- `audit_log` should be append-only by application behavior.
- `kb_entries.embedding` uses `vector(768)`.
- Add indexes for client, workflow, domain, status, and created date lookups.

#### 4. FastAPI Skeleton

Create routers:

- `/api/health`
- `/api/auth`
- `/api/users`

Health endpoints:

- `GET /api/health`
- `GET /api/health/db`
- `GET /api/health/redis`

#### 5. Auth Foundation

Implement:

- password hashing
- login endpoint
- JWT access token generation
- current-user dependency
- role field on users
- route protection helper

Roles to support initially:

- `admin`
- `executive`
- `department_head`
- `viewer`

#### 6. LLM Provider Module

Create a provider factory:

```python
def get_llm(agent_name: str):
    ...
```

Testing mode:

- Use Groq for all agents.
- Keep prompts simple.
- Add a smoke test that calls the configured model with a minimal prompt.

Production placeholders:

- Claude for Orchestrator and Decision Maker.
- Ollama for Learner and Task Generator.
- Ollama `nomic-embed-text` for embeddings.

### Testing Plan

Add tests or scripts for:

- backend app starts
- database connection works
- Redis connection works
- migrations apply cleanly
- JWT login works
- protected endpoint rejects unauthenticated requests
- protected endpoint accepts valid token
- Groq connectivity works for all four agent configs

### Segment 1 Deliverables

- Local backend can start.
- PostgreSQL and Redis run through Docker Compose.
- Database schema is created.
- Auth-protected FastAPI endpoint exists.
- LLM provider factory exists.
- Groq smoke test passes.
- Developer setup instructions are documented.

### Segment 1 Review Checklist

Approve this segment only when:

- `docker-compose up` starts the foundation services.
- `GET /api/health` returns success.
- `GET /api/health/db` confirms database access.
- `GET /api/health/redis` confirms Redis access.
- Auth blocks unauthenticated requests.
- A test user can log in and call a protected endpoint.
- Groq calls work for Orchestrator, Learner, Decision Maker, and Task Generator.

---

## Segment 2: Knowledge Base Service

**Goal:** Build the fully owned internal knowledge base system before connecting agent reasoning to it.

### Build Order

1. Add KB service module and API router.
2. Implement domain management.
3. Implement document upload endpoint.
4. Implement parsers for supported file types.
5. Implement chunking.
6. Implement embedding adapter.
7. Store chunks and metadata in PostgreSQL.
8. Implement vector search.
9. Add query routing and optional reranking.
10. Add ingestion status tracking and tests.

### Technical Tasks

#### 1. KB Domain Management

Endpoints:

- `GET /api/kb/domains`
- `POST /api/kb/domains`
- `PATCH /api/kb/domains/{id}`

Domain fields:

- `id`
- `client_id`
- `name`
- `description`
- `is_active`
- `created_at`

Rules:

- Domain names are unique per client.
- Inactive domains should not be searched by default.

#### 2. Document Upload and Ingestion

Endpoint:

- `POST /api/kb/ingest`

Inputs:

- file
- `client_id`
- `domain_id`
- optional metadata JSON

Supported file types:

- `.txt`
- `.pdf`
- `.docx`
- `.csv`

Ingestion pipeline:

```text
upload -> validate -> parse -> normalize text -> chunk -> embed -> store -> log status
```

Failure handling:

- Create ingestion log entry at the start.
- Mark it `processing`.
- Mark it `complete` with `chunks_created` when done.
- Mark it `failed` with `error_detail` when parsing, embedding, or database storage fails.

#### 3. Parsers

Parser modules:

- `txt_parser.py`
- `pdf_parser.py`
- `docx_parser.py`
- `csv_parser.py`

Parser output should be consistent:

```python
class ParsedDocument(BaseModel):
    text: str
    source_file: str
    metadata: dict
```

#### 4. Chunker

Default chunking:

- chunk size: 512 tokens or approximate words
- overlap: 64 tokens or approximate words
- preserve chunk order with `chunk_index`

Rules:

- Skip empty chunks.
- Store original filename.
- Store basic metadata such as file type, uploaded date, and domain.

#### 5. Embedder

Testing mode:

- Use Groq-compatible test embedding fallback if available, or a deterministic local test embedder for development.

Production mode:

- Use Ollama `nomic-embed-text`.
- Vector dimension must match `kb_entries.embedding`.

Important decision:

- If Groq is not suitable for embeddings during testing, use a deterministic fake embedder for tests and mark it clearly as non-production.

#### 6. Retrieval

Endpoint:

- `GET /api/kb/search?q=...&domain=...`

Preferred production query:

```sql
SELECT
    e.id,
    e.content,
    e.source_file,
    e.metadata,
    d.name AS domain,
    1 - (e.embedding <=> :query_embedding) AS similarity_score
FROM kb_entries e
JOIN kb_domains d ON e.domain_id = d.id
WHERE e.client_id = :client_id
  AND d.name = ANY(:domains)
  AND d.is_active = true
  AND 1 - (e.embedding <=> :query_embedding) > :threshold
ORDER BY e.embedding <=> :query_embedding
LIMIT :limit;
```

Default retrieval settings:

- limit: 8
- similarity threshold: 0.65
- domain filter: optional, but recommended

#### 7. Query Router

Implement basic routing first:

- If domain is explicitly provided, use it.
- If no domain is provided, search active domains.
- Later, add LLM-based domain classification.

### Testing Plan

Add tests or scripts for:

- create KB domain
- upload TXT file
- upload PDF file
- upload DOCX file
- upload CSV file
- failed ingestion logs useful error detail
- chunk count is reasonable
- embeddings are stored
- search returns top-K chunks
- search can be filtered by domain

### Segment 2 Deliverables

- KB domain APIs.
- KB ingestion API.
- Parser, chunker, embedder, pipeline, searcher, and query router modules.
- Sample test documents.
- Search endpoint returning content, source, domain, metadata, and score.
- KB ingestion logs.

### Segment 2 Review Checklist

Approve this segment only when:

- A domain can be created.
- A document can be uploaded and parsed.
- Chunks are stored in `kb_entries`.
- Ingestion status is recorded in `kb_ingestion_log`.
- Search returns relevant chunks with similarity scores.
- Search can be restricted to selected domains.
- Failed ingestion produces a readable error.

---

## Segment 3: Agent Workflow and Human Approval Gate

**Goal:** Connect the four-agent LangGraph workflow and enforce the human approval checkpoint.

### Build Order

1. Define shared schemas and workflow state.
2. Build LangGraph graph skeleton.
3. Add checkpoint persistence.
4. Implement Orchestrator node.
5. Implement Learner node.
6. Add external data connector interface.
7. Implement Decision Maker node.
8. Add approval pause and resume logic.
9. Implement approval and rejection APIs.
10. Add audit logging for every transition.
11. Add integration test from objective submission to approval pause.

### Technical Tasks

#### 1. Shared State and Schemas

Define:

- `Objective`
- `SubTask`
- `LearnerReport`
- `DecisionReport`
- `DepartmentTask`
- `AuditEntry`
- `WorkflowState`

Minimum `WorkflowState`:

```python
class WorkflowState(TypedDict):
    workflow_id: str
    objective_id: str
    objective_text: str
    client_id: str
    department: str
    initiated_by: str
    priority: Literal["low", "medium", "high", "critical"]
    subtasks: list[SubTask]
    learner_output: LearnerReport | None
    decision_report: DecisionReport | None
    approval_status: Literal["pending", "approved", "rejected"]
    reviewer_feedback: str | None
    task_assignments: list[DepartmentTask]
    audit_trail: list[AuditEntry]
```

#### 2. Workflow APIs

Endpoints:

- `POST /api/objectives`
- `GET /api/workflows/{id}`
- `GET /api/workflows/{id}/report`
- `POST /api/workflows/{id}/approve`
- `POST /api/workflows/{id}/reject`

Objective submission should:

- validate user permissions
- create objective record
- create initial workflow state
- start LangGraph execution
- return workflow ID

#### 3. Orchestrator Agent

Input:

- objective text
- department
- priority
- client context

Output:

- 3 to 5 structured subtasks

Testing prompt:

```text
You are the Orchestrator agent.
Break this objective into 3-5 concrete subtasks.
Return strict JSON only.
```

Validation:

- Reject malformed JSON.
- Retry up to 3 times.
- Write failure to audit log.

#### 4. Learner Agent

Input:

- objective
- subtasks

Process:

- call KB search
- gather top-K chunks
- run simple RAG prompt
- produce `LearnerReport`

Output must include:

- feasibility score
- supporting evidence
- identified gaps
- recommended adjustments
- confidence
- domains searched

#### 5. Decision Maker Agent

Input:

- `LearnerReport`
- external data connector results

External connector interface:

```python
class ExternalDataConnector(Protocol):
    name: str
    async def fetch(self, objective: Objective) -> dict:
        ...
```

Initial connectors:

- mock market data connector
- mock regulatory connector
- mock economic connector

Decision report output:

- recommendation
- confidence score
- risk level
- supporting data
- requires expert review
- markdown summary
- generated timestamp
- expiry timestamp

#### 6. HITL Gate

Required behavior:

- Workflow must pause after Decision Maker.
- Task Generator must not run while `approval_status=pending`.
- Approval resumes workflow.
- Rejection loops back to Orchestrator with reviewer feedback.

Routing behavior:

```python
def route_after_decision(state: WorkflowState) -> str:
    if state["approval_status"] == "approved":
        return "task_generator"
    if state["approval_status"] == "rejected":
        return "orchestrator"
    return END
```

#### 7. Audit Logging

Log every major event:

- objective submitted
- orchestrator started/completed/failed
- learner KB search started/completed/failed
- decision maker started/completed/failed
- workflow suspended for approval
- human approved
- human rejected
- workflow resumed

Audit fields:

- workflow ID
- actor
- action
- input summary
- output summary
- timestamp
- duration in milliseconds

### Testing Plan

Add tests or scripts for:

- submit objective
- Orchestrator creates valid subtasks
- Learner calls KB and returns report
- Decision Maker creates report
- workflow pauses before Task Generator
- approval resumes workflow
- rejection returns to Orchestrator
- audit records exist for each node
- workflow can resume from checkpoint after simulated failure

### Segment 3 Deliverables

- Working LangGraph graph.
- Workflow state models.
- Workflow APIs.
- Orchestrator, Learner, and Decision Maker agents.
- Approval and rejection backend flow.
- PostgreSQL checkpoint persistence.
- Audit logs for every transition.

### Segment 3 Review Checklist

Approve this segment only when:

- Submitting an objective creates a workflow.
- The workflow reaches Decision Maker.
- A decision report is available through the API.
- The workflow stops before Task Generator.
- Approval resumes the workflow.
- Rejection captures feedback and loops back.
- Audit log shows a complete trace.

---

## Segment 4: Task Dispatch, Dashboard, Observability, and Production Hardening

**Goal:** Finish the operational product and prepare it for real client use.

### Build Order

1. Implement Task Generator.
2. Add Celery worker and Redis-backed queues.
3. Add department task APIs.
4. Build dashboard foundation.
5. Build objective submission UI.
6. Build approval review UI.
7. Build task tracker UI.
8. Build KB admin UI.
9. Build audit trail UI.
10. Add notifications.
11. Add expiry and escalation jobs.
12. Add Prometheus metrics.
13. Add Grafana dashboards.
14. Add production LLM switching.
15. Finalize Docker Compose packaging and deployment docs.

### Technical Tasks

#### 1. Task Generator Agent

Input:

- approved `DecisionReport`
- client department config
- original objective
- learner report

Output:

- `DepartmentTask[]`

Task fields:

- task ID
- department
- assigned user or role
- instructions
- required actions
- deadline
- dependencies
- status

Rules:

- Generate tasks only after approval.
- Every task must map to a valid department.
- Every generated task must be persisted before dispatch.
- Dispatch failure should not lose the task.

#### 2. Celery Queues

Queues:

- `tasks.default`
- `tasks.hr`
- `tasks.finance`
- `tasks.operations`
- `tasks.legal`

Implementation notes:

- Start with generic queues.
- Later allow client-specific department queues.
- Store task status in PostgreSQL.
- Use Redis as broker.

#### 3. Task APIs

Endpoints:

- `GET /api/tasks`
- `GET /api/tasks/{id}`
- `PATCH /api/tasks/{id}/status`
- `PATCH /api/tasks/{id}/assignment`

Filters:

- client
- department
- status
- priority
- assigned user

#### 4. Frontend Dashboard

Pages:

- login
- dashboard overview
- objective submission
- workflow detail
- approval review
- task tracker
- KB domains
- KB upload
- audit trail

Dashboard priorities:

- Approval review must be clear and safe.
- Task tracker must be easy for department heads to scan.
- KB upload must expose ingestion status.
- Audit trail must be readable by admins.

#### 5. Notifications

Channels:

- email
- Slack webhook

Notification events:

- decision report ready for approval
- approval pending near expiry
- approval expired and escalated
- task assigned
- task blocked

#### 6. Expiry and Escalation

Use Celery Beat for scheduled checks.

Rules:

- If approval is pending past `expires_at`, escalate.
- Escalation target comes from client supervisor hierarchy.
- Escalation action is written to audit log.

#### 7. Observability

Prometheus metrics:

- workflow count by status
- agent latency by node
- node failure count
- approval queue depth
- approval age
- KB ingestion success/failure count
- KB search latency
- task queue depth
- LLM provider latency
- LLM error count

Grafana dashboards:

- workflow health
- agent performance
- approval queue
- KB ingestion and retrieval
- task dispatch
- system services

#### 8. Production LLM Switching

Production routing:

- Orchestrator: Claude Sonnet 4.6
- Decision Maker: Claude Sonnet 4.6
- Learner: Ollama Llama 3
- Task Generator: Ollama Llama 3
- Embeddings: Ollama `nomic-embed-text`

Implementation requirements:

- Provider switch through environment variables.
- Per-agent model config.
- Clear fallback behavior.
- Startup validation for required providers.

#### 9. Final Docker Compose Packaging

Final services:

- `backend`
- `kb_service`
- `agent_runtime`
- `frontend`
- `postgres`
- `redis`
- `celery_worker`
- `celery_beat`
- `ollama`
- `prometheus`
- `grafana`

### Testing Plan

Add tests or scripts for:

- approval produces tasks
- tasks persist in database
- Celery dispatch receives tasks
- task status can be updated
- dashboard can submit objective
- dashboard can approve report
- dashboard can display tasks
- notification sends through configured channel
- expired approval escalates
- metrics endpoint exposes expected metrics
- final Docker Compose stack starts

### Segment 4 Deliverables

- Task Generator agent.
- Celery queues.
- Task APIs.
- Next.js dashboard.
- Notification system.
- Expiry and escalation worker.
- Prometheus metrics.
- Grafana dashboards.
- Production LLM config.
- Final deployment docs.

### Segment 4 Review Checklist

Approve this segment only when:

- Approved decisions generate department tasks.
- Tasks are visible in the dashboard.
- Task status can be updated.
- Approval notifications are sent.
- Expired approvals escalate.
- Prometheus exposes useful metrics.
- Grafana dashboards load.
- Production LLM provider switching works.
- The full system starts from Docker Compose.
- A complete objective moves from submission to approved department tasks.

---

## Cross-Segment Dependency Map

| Dependency | Needed By | Segment |
|---|---|---|
| PostgreSQL schema | KB, workflows, audit, tasks | 1 |
| Redis | Celery, async workflow support | 1, 4 |
| Auth | all protected APIs and dashboard | 1 |
| LLM factory | all agents | 1 |
| KB ingestion | Learner RAG | 2, 3 |
| KB search | Learner RAG and dashboard admin search | 2, 3, 4 |
| Workflow checkpoints | HITL pause/resume | 3 |
| Audit log | compliance and dashboard | 1, 3, 4 |
| Approval API | dashboard and Task Generator gate | 3, 4 |
| Department tasks | task dashboard and queues | 4 |

---

## Suggested Milestones

### Milestone A: Local Foundation Demo

Show:

- backend running
- database connected
- auth working
- Groq smoke test passing

Corresponds to Segment 1.

### Milestone B: KB Demo

Show:

- create domain
- upload document
- inspect stored chunks
- search KB and retrieve relevant results

Corresponds to Segment 2.

### Milestone C: Agent Workflow Demo

Show:

- submit objective
- workflow runs through Orchestrator, Learner, Decision Maker
- report is generated
- workflow pauses for human approval

Corresponds to Segment 3.

### Milestone D: Full Product Demo

Show:

- submit objective from dashboard
- approve report from dashboard
- department tasks are generated
- task status changes
- audit trail and metrics are visible

Corresponds to Segment 4.

---

## Implementation Risks and Controls

| Risk | Control |
|---|---|
| LLM output is malformed | Require JSON schema validation and retry logic |
| HITL gate is bypassed | Enforce routing in LangGraph backend, not only frontend |
| KB search quality is poor | Track similarity scores and allow domain filtering |
| Embedding model changes break vector dimensions | Store embedding model metadata and validate dimensions |
| External data connector fails | Use connector timeouts, fallback data, and audit warnings |
| Celery task dispatch fails | Persist tasks before dispatch and retry queue delivery |
| Approval expires unnoticed | Scheduled expiry worker plus notification audit records |
| Prompt injection through KB content | Isolate retrieved context and add prompt rules against instruction following from documents |
| Sensitive data leaks to cloud LLM during testing | Use synthetic data only while `LLM_PROVIDER=groq` |

---

## Definition of Done for the Whole System

The system is complete when:

- A user can log in.
- A user can submit a business objective.
- The Orchestrator breaks it into subtasks.
- The Learner searches the internal KB and creates a feasibility report.
- The Decision Maker creates a decision report.
- The workflow pauses for human approval.
- A human can approve or reject the report.
- Approval triggers task generation.
- Department tasks are queued and visible in the dashboard.
- Audit logs show every action and handoff.
- Metrics show workflow, agent, KB, approval, and task health.
- The full stack can run through Docker Compose.

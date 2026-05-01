# Technical Architecture: Autonomous AI Agent System

**Version:** 1.1
**Audience:** Engineering Team
**Status:** Draft for Review

---

## 1. System Overview

The system is a **multi-agent orchestration platform** built on a directed graph execution model. Four specialized agents communicate through a shared state bus, each scoped to its own context and permissions. A human approval gate is enforced as a hard blocker between the Decision Maker and the Task Generator — no code path bypasses it.

The knowledge base is **fully owned and built in-house** — no third-party KB service. It runs on the same PostgreSQL instance as the rest of the system, with a custom Python service handling all ingestion, embedding, and retrieval.

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT INTERFACE                         │
│              (Web Dashboard / REST API / Slack Bot)             │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Objective Input (JSON)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      API GATEWAY (FastAPI)                      │
│         Auth · Rate Limiting · Request Validation               │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AGENT RUNTIME (LangGraph)                    │
│                                                                 │
│   ┌─────────────┐     ┌──────────┐     ┌──────────────────┐    │
│   │ ORCHESTRATOR│────▶│ LEARNER  │────▶│ DECISION MAKER   │    │
│   │   (Node 1)  │     │ (Node 2) │     │    (Node 3)      │    │
│   └─────────────┘     └──────────┘     └────────┬─────────┘    │
│          ▲                 │                     │              │
│          │                 │ KB Query            │ Report       │
│          │                 ▼                     ▼              │
│          │       ┌──────────────────┐   ┌────────────────┐      │
│          │       │   KB SERVICE     │   │  HUMAN REVIEW  │      │
│          │       │   (Python)       │   │  (HITL Gate)   │      │
│          │       └──────────────────┘   └───────┬────────┘      │
│          │                                      │ Approved       │
│          │                                      ▼               │
│          │                           ┌──────────────────┐       │
│          └───────────────────────────│ TASK GENERATOR   │       │
│                    Feedback Loop     │    (Node 4)      │       │
│                                      └──────────────────┘       │
└─────────────────────────────────────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
   ┌─────────────┐  ┌──────────────┐  ┌──────────────┐
   │ PostgreSQL  │  │    Redis     │  │    Ollama    │
   │ KB + State  │  │  Msg Queue   │  │  LLM + Embed │
   │ + Audit Log │  │              │  │  (local)     │
   └─────────────┘  └──────────────┘  └──────────────┘
```

---

## 2. Technology Stack

| Layer                    | Testing                                                | Production                                           | Rationale                                                                    |
| ------------------------ | ------------------------------------------------------ | ---------------------------------------------------- | ---------------------------------------------------------------------------- |
| Agent Framework          | LangGraph                                              | LangGraph                                            | Directed graph execution, built-in checkpointing, TypedDict state validation |
| LLM — All Agents         | **Groq API** (Llama 3.3 70B / Mixtral 8x7B)           | Claude Sonnet 4.6 (cloud) / Llama 3 via Ollama (local) | Groq: free tier, ~300 tokens/s, no GPU needed for testing                  |
| Embeddings               | Groq API (llama3 for text tasks)                       | Ollama nomic-embed-text (local, on-premise)          | Keep embeddings local in production for data sovereignty                     |
| Agent Prompts            | Simple, single-turn prompts                            | Full structured prompt chains with few-shot examples | Validate agent logic cheaply before investing in prompt engineering          |
| API Layer                | FastAPI                                                | FastAPI                                              | Async, high-performance, native Pydantic validation                          |
| Knowledge Base           | **Custom KB Service (Python) + PostgreSQL + pgvector** | Same — fully owned, no third-party KB service        | Identical schema in both environments; no migration needed at launch         |
| State Store              | PostgreSQL                                             | PostgreSQL                                           | Persistent checkpoints, audit logs                                           |
| Message Bus              | Redis (Pub/Sub)                                        | Redis (Pub/Sub)                                      | Non-blocking inter-agent event passing                                       |
| Task Queue               | Celery + Redis                                         | Celery + Redis                                       | Async task dispatch to department queues                                     |
| Auth                     | JWT + OAuth2                                           | JWT + OAuth2                                         | Human-in-the-loop approval flows; role-based access                          |
| Frontend                 | Next.js                                                | Next.js                                              | Approval dashboard, objective input UI, task tracking                        |
| Containerization         | Docker + Docker Compose                                | Docker + Docker Compose / Kubernetes                 | Single-command SME deployment; K8s for scale-out                             |
| Monitoring               | Prometheus + Grafana                                   | Prometheus + Grafana                                 | Agent performance, latency, approval queue depth                             |

---

## 3. LLM Strategy — Testing vs. Production

### Why Two Tiers

Testing with Claude or Ollama burns tokens fast and requires a GPU for local inference. Groq solves both problems: it provides a **free API tier** with extremely fast inference (no GPU needed on your machine) and simple prompt structures that are easy to debug. Once the agent logic is validated, swapping to the production LLM is a one-line config change.

### Testing Phase — Groq API

**Why Groq:**
- Free tier: 14,400 requests/day, 6,000 tokens/minute on Llama 3.3 70B — sufficient for full pipeline testing
- ~300 tokens/second — near-instant responses, tight feedback loop during development
- No GPU or local hardware required — any dev machine works
- OpenAI-compatible API — same Python SDK interface, easy to swap out later

**Models available on free tier:**

| Model | Tokens/min | Best Used For |
|---|---|---|
| Llama 3.3 70B (Groq) | 6,000 | Orchestrator, Decision Maker logic |
| Llama 3.1 8B (Groq) | 14,400 | Learner, Task Generator |
| Mixtral 8x7B (Groq) | 5,000 | Fallback / secondary reasoning |

**Agent prompts in testing are intentionally simple:**
```python
# Testing — simple, single-turn prompt
prompt = f"""
You are the Orchestrator agent.
Objective: {objective_text}
Break this into 3-5 sub-tasks. Return as JSON list.
"""

# Production — structured chain with role, constraints, few-shot examples
# (added after logic is validated in testing)
```

### Production Phase — LLM Switch

A single environment variable controls which LLM provider each agent uses:

```python
# config.py
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")  # "groq" | "claude" | "ollama"

def get_llm(agent: str) -> BaseChatModel:
    if LLM_PROVIDER == "groq":
        return ChatGroq(model="llama-3.3-70b-versatile", api_key=GROQ_API_KEY)
    elif LLM_PROVIDER == "claude":
        return ChatAnthropic(model="claude-sonnet-4-6", api_key=ANTHROPIC_API_KEY)
    elif LLM_PROVIDER == "ollama":
        return ChatOllama(model="llama3", base_url=OLLAMA_BASE_URL)
```

**Per-agent LLM assignment in production:**

| Agent | Testing (Groq) | Production |
|---|---|---|
| Orchestrator | Llama 3.3 70B (Groq) | Claude Sonnet 4.6 |
| Learner | Llama 3.1 8B (Groq) | Llama 3 13B via Ollama |
| Decision Maker | Llama 3.3 70B (Groq) | Claude Sonnet 4.6 |
| Task Generator | Llama 3.1 8B (Groq) | Llama 3 13B via Ollama |

The Decision Maker and Orchestrator always get the strongest model in production — they handle the highest-stakes reasoning. The Learner and Task Generator run locally via Ollama to keep data on-premise and cut cost.

### What Changes Between Testing and Production

| Concern | Testing | Production |
|---|---|---|
| LLM provider | Groq (free API) | Claude API + Ollama |
| Prompt complexity | Single-turn, minimal | Structured chains, few-shot |
| Embeddings | Text handled by Groq LLM | nomic-embed-text via Ollama |
| Hardware needed | Any dev machine | GPU server for Ollama |
| Data sensitivity | Use synthetic/dummy data only | Real client data |
| Cost | Free | Pay-per-token (Claude) + electricity (Ollama) |

**Nothing else changes.** The LangGraph graph, state schema, KB service, PostgreSQL schema, API contract, and HITL gate are identical in both environments. This is the point — validate the logic cheaply, flip the switch to go live.

---

## 4. Knowledge Base — Fully Custom, Fully Owned

### What It Is

A **custom Python service** that sits between the Learner agent and the PostgreSQL database. No third-party service. No external API. Every line of KB logic is code we write and own.

It has two responsibilities:

1. **Ingestion** — accept raw documents, chunk them, generate embeddings via Ollama, store in PostgreSQL
2. **Retrieval** — accept a query from the Learner, find the most semantically relevant KB entries, return them

### Database Schema (PostgreSQL + pgvector)

pgvector is not a third-party service — it is a PostgreSQL extension (like adding a column type). The database is fully yours.

```sql
-- Enable the extension once on setup
CREATE EXTENSION IF NOT EXISTS vector;

-- Domain routing table — controls which domains the Learner searches
CREATE TABLE kb_domains (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id     uuid NOT NULL,
    name          text NOT NULL,          -- "HR", "Finance", "Operations", "Legal"
    description   text,
    is_active     boolean DEFAULT true,
    created_at    timestamptz DEFAULT now()
);

-- The actual knowledge base — one row per document chunk
CREATE TABLE kb_entries (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id     uuid NOT NULL,
    domain_id     uuid REFERENCES kb_domains(id),
    source_file   text,                   -- original filename
    chunk_index   int,                    -- position within the source file
    content       text NOT NULL,          -- the raw text chunk
    embedding     vector(768),            -- generated by nomic-embed-text via Ollama
    metadata      jsonb,                  -- tags, author, date, version, etc.
    created_at    timestamptz DEFAULT now()
);

-- Index for fast similarity search
CREATE INDEX kb_embedding_idx
    ON kb_entries
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Ingestion job log — track every document upload
CREATE TABLE kb_ingestion_log (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id     uuid NOT NULL,
    domain_id     uuid REFERENCES kb_domains(id),
    filename      text,
    file_type     text,                   -- "pdf", "docx", "csv", "txt"
    chunks_created int,
    status        text,                   -- "processing", "complete", "failed"
    error_detail  text,
    ingested_at   timestamptz DEFAULT now()
);
```

### KB Service — Python Module Structure

```
kb_service/
├── ingestion/
│   ├── chunker.py          # splits documents into overlapping chunks
│   ├── embedder.py         # calls Ollama nomic-embed-text to generate vectors
│   ├── parsers/
│   │   ├── pdf_parser.py   # extracts text from PDFs (PyMuPDF)
│   │   ├── docx_parser.py  # extracts text from Word docs (python-docx)
│   │   └── csv_parser.py   # extracts text from CSVs (pandas)
│   └── pipeline.py         # orchestrates parse → chunk → embed → store
├── retrieval/
│   ├── searcher.py         # runs cosine similarity query against PostgreSQL
│   ├── reranker.py         # optional: re-ranks results by relevance score
│   └── query_router.py     # decides which kb_domains to search for a given query
└── api.py                  # FastAPI router — /kb/ingest, /kb/search, /kb/domains
```

### How Ingestion Works (Step by Step)

```
Admin uploads a file via dashboard
        │
        ▼
POST /api/kb/ingest  →  KB Service receives file + domain label
        │
        ▼
Parser extracts raw text (PDF / DOCX / CSV / TXT)
        │
        ▼
Chunker splits text into overlapping chunks
(chunk size: 512 tokens, overlap: 64 tokens)
        │
        ▼
Embedder sends each chunk to Ollama nomic-embed-text
→ returns a 768-dimension vector per chunk
        │
        ▼
Each chunk + its vector stored as a row in kb_entries
        │
        ▼
Ingestion logged in kb_ingestion_log
```

### How Retrieval Works (Step by Step)

```
Learner agent has an objective to research
        │
        ▼
KB Service query_router reads the objective
→ decides which domains are relevant (e.g., "HR" and "Legal")
        │
        ▼
Embedder generates a vector for the objective text
        │
        ▼
Searcher runs cosine similarity query against kb_entries
WHERE domain_id IN (relevant domains)
ORDER BY embedding <=> objective_vector
LIMIT 8
        │
        ▼
Top-K chunks returned to the Learner with similarity scores
        │
        ▼
Learner runs RAG chain over returned chunks
→ produces LearnerReport
```

### The SQL Query That Powers Retrieval

```sql
SELECT
    e.content,
    e.source_file,
    e.metadata,
    d.name                                  AS domain,
    1 - (e.embedding <=> $1::vector)        AS similarity_score
FROM
    kb_entries e
JOIN
    kb_domains d ON e.domain_id = d.id
WHERE
    e.client_id = $2
    AND d.name = ANY($3)                    -- only search relevant domains
    AND 1 - (e.embedding <=> $1::vector) > 0.65  -- similarity threshold
ORDER BY
    e.embedding <=> $1::vector
LIMIT 8;
```

No external service. No API call. Pure PostgreSQL.

---

## 5. Agent Specifications

### 5.1 The Orchestrator (Node 1)

**Role:** Entry point and coordination hub. Owns the global workflow state.

**Trigger:** HTTP POST from dashboard or API with a structured `Objective` payload.

**State it manages:**

```python
class WorkflowState(TypedDict):
    objective_id: str
    objective_text: str
    department: str
    initiated_by: str
    priority: Literal["low", "medium", "high", "critical"]
    subtasks: list[SubTask]
    learner_output: LearnerReport | None
    decision_report: DecisionReport | None
    approval_status: Literal["pending", "approved", "rejected"]
    task_assignments: list[DepartmentTask]
    audit_trail: list[AuditEntry]
```

**Responsibilities:**

- Validates and parses the incoming objective
- Decomposes it into sub-tasks using a structured prompt chain
- Routes sub-tasks to the Learner
- Waits on approval gate before releasing to Task Generator
- Writes every state transition to the audit trail

**LLM:** Claude Sonnet 4.6 — templated prompt per client's department schema.

**Failure Handling:** Retries failed nodes up to 3 times with exponential backoff, then escalates with a `SYSTEM_ESCALATION` flag.

---

### 5.2 The Learner (Node 2)

**Role:** Queries the internal KB and produces a feasibility assessment.

**Input:** `SubTask[]` from Orchestrator state
**Output:** `LearnerReport`

**How it works:**

1. Sends the objective text to the KB Service `/kb/search` endpoint
2. KB Service returns the top-K relevant chunks from PostgreSQL (fully internal)
3. Learner runs a RAG chain over the returned chunks using Llama 3 via Ollama
4. Produces a structured feasibility report

```python
class LearnerReport(BaseModel):
    feasibility_score: float          # 0.0 – 1.0
    supporting_evidence: list[str]    # cited KB entries (content + source file)
    identified_gaps: list[str]        # what knowledge is missing from the KB
    recommended_adjustments: list[str]
    confidence: float
    domains_searched: list[str]       # which KB domains were queried
```

**LLM:** Llama 3 (13B) via Ollama — all data stays on-premise.

---

### 5.3 The Decision Maker (Node 3)

**Role:** Multi-source synthesis and report generation. Last agent before the human.

**Input:** `LearnerReport` + live external data
**Output:** `DecisionReport` → human approval queue

**External Data Sources (configurable per client):**
| Source Type | Example | Usage |
|---|---|---|
| Market Data | Alpha Vantage, Yahoo Finance | Financial decisions |
| Regulatory | Government open data, EUR-Lex | Compliance checks |
| Economic | World Bank API, FRED | Macro context |
| Custom | Client-configured webhooks | Industry-specific signals |

```python
class DecisionReport(BaseModel):
    recommendation: str
    confidence_score: float
    risk_level: Literal["low", "medium", "high", "critical"]
    supporting_data: dict[str, Any]
    requires_expert_review: bool
    markdown_summary: str
    generated_at: datetime
    expires_at: datetime
```

**HITL Gate:** Graph suspends after this node. Resumes only on `POST /api/workflows/{id}/approve`.

**LLM:** Claude Sonnet 4.6.

---

### 5.4 The Task Generator (Node 4)

**Role:** Converts an approved decision into department-routed tasks.

**Input:** Approved `DecisionReport` + client's department config
**Output:** `DepartmentTask[]` dispatched to Celery queues

```python
class DepartmentTask(BaseModel):
    task_id: str
    department: str
    assigned_to: str | None
    instructions: str
    required_actions: list[str]
    deadline: datetime | None
    depends_on: list[str]
    status: Literal["queued", "in_progress", "blocked", "done"]
```

**LLM:** Llama 3 (13B) via Ollama — local, cheap, appropriate for this lower-risk step.

---

## 6. State Management & Checkpointing

Every node reads from and writes to a single `WorkflowState` object. LangGraph checkpoints this to PostgreSQL after every node.

```
WorkflowState in PostgreSQL
├── thread_id       (workflow run UUID)
├── checkpoint_id   (auto-incremented per node)
├── node_name       (which agent wrote this checkpoint)
├── state_blob      (serialized TypedDict)
└── created_at
```

If any agent crashes, the workflow resumes from the last checkpoint — not from scratch.

---

## 7. Human-in-the-Loop (HITL) Implementation

Enforced at the graph level, not the UI level.

```python
def route_after_decision(state: WorkflowState) -> str:
    if state["approval_status"] == "approved":
        return "task_generator"
    elif state["approval_status"] == "rejected":
        return "orchestrator"       # loops back with reviewer feedback
    else:
        return END                  # graph pauses; waits for webhook
```

**Approval Flow:**

1. Decision Maker writes report → graph suspends
2. Approver notified via email / Slack with a secure one-time link
3. Approver reviews markdown summary in the dashboard
4. Approver clicks Approve or Reject (with optional feedback text)
5. Dashboard calls `POST /api/workflows/{id}/approve` → updates `approval_status`
6. LangGraph resumes from the suspended checkpoint
7. Action written to audit trail with approver ID and timestamp

**Expiry:** No action within `expires_at` window → automatically escalated to the next supervisor in the configured hierarchy.

---

## 8. Security Architecture

### Inter-Agent Trust (Zero-Trust)

- All agent communication goes through shared state — no direct container-to-container calls
- Each agent container has no network access except through the Redis bus
- Each agent reads only the state fields it needs (least-privilege context injection)

### Roles

```
admin           → full system access, configure agents and departments
executive       → submit objectives, approve/reject Decision Reports
department_head → view and update tasks for their department
viewer          → read-only dashboard
```

- JWT tokens, 1-hour expiry; refresh tokens in HttpOnly cookies
- Approval actions require step-up re-authentication
- API keys for external data sources stored in environment variables only

### Audit Log

```python
class AuditEntry(BaseModel):
    event_id: str
    workflow_id: str
    actor: str          # agent name or user ID
    action: str         # e.g., "learner.kb_search", "human.approved"
    input_summary: str
    output_summary: str
    timestamp: datetime
    duration_ms: int
```

Append-only table — no UPDATE/DELETE permissions. Exported nightly for regulated clients.

---

## 9. Deployment Architecture

### Single-Command Deployment

```bash
docker-compose up
```

```
Services:
├── api_gateway        (FastAPI — port 8000)
├── kb_service         (Custom KB Python service — port 8001)
├── agent_runtime      (LangGraph workers)
│   ├── orchestrator
│   ├── learner
│   ├── decision_maker
│   └── task_generator
├── ollama             (Local LLM + embedding server — port 11434)
├── postgres           (KB + State + Audit — port 5432)
├── redis              (Message bus — port 6379)
├── celery_worker      (Async task dispatch)
├── celery_beat        (Scheduled jobs — KB re-indexing, expiry checks)
├── frontend           (Next.js dashboard — port 3000)
├── prometheus         (Metrics — port 9090)
└── grafana            (Dashboards — port 3001)
```

### Environment Tiers

| Tier        | Setup                       | LLM                                          | Use Case                                |
| ----------- | --------------------------- | -------------------------------------------- | --------------------------------------- |
| Local (SME) | Docker Compose on-premise   | Ollama (Llama 3 13B/70B)                     | Full data sovereignty; predictable cost |
| Hybrid      | Docker Compose + cloud LLM  | Ollama local + Claude API for Decision Maker | Balance cost vs. reasoning quality      |
| Cloud       | Kubernetes on AWS/GCP/Azure | Claude API for all agents                    | Scale-out for larger clients            |

### Hardware Minimums (Local Deployment)

| Component | Minimum        | Recommended |
| --------- | -------------- | ----------- |
| RAM       | 16 GB          | 32 GB       |
| VRAM      | 12 GB (NVIDIA) | 24 GB       |
| Storage   | 100 GB SSD     | 500 GB NVMe |
| CPU       | 8 cores        | 16 cores    |

---

## 10. API Contract (Key Endpoints)

```
# Workflow
POST   /api/objectives                  → Submit objective (triggers Orchestrator)
GET    /api/workflows/{id}              → Full workflow state
GET    /api/workflows/{id}/report       → Decision Report (for approval UI)
POST   /api/workflows/{id}/approve      → Human approves
POST   /api/workflows/{id}/reject       → Human rejects with feedback

# Tasks
GET    /api/tasks                       → List tasks (filtered by dept/status)
PATCH  /api/tasks/{id}/status           → Update task status

# Knowledge Base (fully internal)
POST   /api/kb/ingest                   → Upload document to KB
GET    /api/kb/domains                  → List configured KB domains
POST   /api/kb/domains                  → Create a new KB domain
GET    /api/kb/search?q=...&domain=...  → Manual KB search (admin/debug use)
DELETE /api/kb/entries/{id}             → Remove a KB entry

# Audit
GET    /api/audit/{workflow_id}         → Full audit trail for a workflow
```

---

## 11. Data Flow Diagram

```
[Human Submits Objective]
        │
        ▼
[API Gateway] — validates JWT, creates WorkflowState in PostgreSQL
        │
        ▼
[Orchestrator] — decomposes objective → writes SubTask[] to state
        │
        ▼
[Learner] — calls KB Service → KB Service queries PostgreSQL (our own DB)
         → RAG chain over results → writes LearnerReport to state
        │
        ▼
[Decision Maker] — fetches external data (async) → synthesizes → writes DecisionReport
                 → notifies approver
        │
        ▼
[GRAPH SUSPENDED — awaiting human approval]
        │
        ▼  (on POST /approve)
[Task Generator] — generates DepartmentTask[] → pushes to Celery queues
        │
        ▼
[Department Queues] — tasks visible in dashboard per department
```

---

## 12. Monitoring & Observability

| Signal               | Tool                 | What We Track                           |
| -------------------- | -------------------- | --------------------------------------- |
| Agent latency        | Prometheus + Grafana | Time per node, end-to-end duration      |
| Approval queue depth | Grafana              | Reports awaiting human review           |
| LLM confidence       | Custom metrics       | Decision Maker confidence trend         |
| KB retrieval quality | Custom metrics       | Similarity score distribution per query |
| KB ingestion health  | Celery monitoring    | Failed ingestion jobs, chunk counts     |
| Error rates          | Prometheus           | Node failures, retries, escalations     |
| Audit completeness   | PostgreSQL query     | Workflows with missing audit entries    |

Alert thresholds (configurable per client):

- Approval pending > 24 hrs → escalate to next supervisor
- Decision Maker confidence < 50% → flag for expert review
- Agent failure rate > 5% in 1 hr → page on-call
- KB ingestion job failed → notify admin

---

## 13. Build Sequence (Implementation Order)

Steps 1–9 use **Groq API + simple prompts** throughout. Steps 10–15 are production hardening.

**Phase 1 — Testing (Groq API, simple prompts)**

1. **Groq API setup + LLM config module** — `get_llm()` factory wired to `LLM_PROVIDER=groq`; validate all 4 agents can call Groq before writing any agent logic
2. **PostgreSQL schema** — KB tables, state tables, audit table, pgvector extension
3. **FastAPI skeleton + JWT auth** — gates all subsequent work
4. **KB Service — ingestion pipeline** — parser, chunker, embedder, store to PostgreSQL
5. **KB Service — retrieval** — cosine search, query router, reranker
6. **LangGraph graph definition** — nodes, edges, conditional routing, checkpointer
7. **Orchestrator agent (Groq + simple prompt)** — validate objective decomposition end-to-end
8. **Learner agent (Groq + simple prompt)** — validate KB retrieval + RAG chain
9. **External data connectors** — pluggable modules consumed by Decision Maker
10. **Decision Maker agent (Groq + simple prompt)** — validate report generation + HITL suspend
11. **Task Generator agent + Celery queues (Groq + simple prompt)** — validate task dispatch

**Phase 2 — Production Hardening (swap LLM_PROVIDER, upgrade prompts)**

12. **Switch Orchestrator + Decision Maker to Claude Sonnet 4.6** — upgrade to structured prompt chains with few-shot examples
13. **Switch Learner + Task Generator to Ollama** — install Ollama, pull Llama 3 13B, validate on-premise inference
14. **Switch embeddings to Ollama nomic-embed-text** — re-index all KB entries with production embedding model
15. **HITL approval API + email/Slack notifications** — full approval flow with expiry and escalation
16. **Next.js dashboard** — approval UI, task tracker, KB upload, objective submission
17. **Prometheus + Grafana** — wired up once data is flowing
18. **Docker Compose packaging** — wraps all services for SME one-command deployment

---

## 14. Four Review Segments

The detailed checkpoint plan is maintained in `implementation_segments.md`.

Use this four-part structure for execution and client/team review:

| Segment | Focus | Approval Point |
|---|---|---|
| 1 | Core foundation | Backend, database, auth, Docker services, and Groq connectivity are working |
| 2 | Knowledge Base service | Documents can be ingested, embedded, stored, and searched by domain |
| 3 | Agent workflow + HITL gate | Objective flows through Orchestrator, Learner, Decision Maker, and pauses for approval |
| 4 | Task dispatch + dashboard + production hardening | Approved decisions generate department tasks and the full system is deployable |

Each segment should be completed, tested, and reviewed before the next segment begins.

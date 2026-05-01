/* ═══════════════════════════════════════════════════════════
   CONFIG
════════════════════════════════════════════════════════════ */
const API_BASE      = "http://localhost:8010";
const POLL_INTERVAL = 5000;
const AUTO_REFRESH  = 30000;

const DEPARTMENTS = ["finance", "hr", "operations", "legal", "sales"];

/* ═══════════════════════════════════════════════════════════
   STATE
════════════════════════════════════════════════════════════ */
const S = {
  token:              localStorage.getItem("manage_ai_token") || null,
  workflows:          [],
  tasks:              [],
  domains:            [],
  notifications:      [],
  llm:                [],
  selectedWorkflowId: null,
  trackedWorkflowId:  null,
  activeDept:         "finance",
  industry:           null,
  pollTimer:          null,
  refreshTimer:       null,
};

/* ═══════════════════════════════════════════════════════════
   BOOT
════════════════════════════════════════════════════════════ */
document.addEventListener("DOMContentLoaded", () => {
  setupNav();
  setupForms();
  setupDeptTabs();
  pollHealth();
  setInterval(pollHealth, 30000);
  if (S.token) bootApp();
  else showEl("loginOverlay");
});

function bootApp() {
  hideEl("loginOverlay");
  showEl("app");
  loadOverview();
  loadDomains();
  loadLLMConfig();
  detectIndustry();
  startAutoRefresh();
}

/* ═══════════════════════════════════════════════════════════
   AUTH
════════════════════════════════════════════════════════════ */
g("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = v("loginEmail"), pw = v("loginPassword");
  const errEl = g("loginError"), btn = g("loginBtn");
  errEl.classList.add("hidden");
  btn.disabled = true; btn.textContent = "Signing in...";
  try {
    const fd = new FormData();
    fd.append("username", email); fd.append("password", pw);
    const res = await fetch(`${API_BASE}/api/auth/login`, { method: "POST", body: fd });
    if (!res.ok) throw new Error("Invalid email or password");
    const data = await res.json();
    S.token = data.access_token;
    localStorage.setItem("manage_ai_token", S.token);
    g("userEmailDisplay").textContent = email.split("@")[0];
    g("userAvatar").textContent       = email[0].toUpperCase();
    bootApp();
    toast("Signed in", "success");
  } catch (err) {
    errEl.textContent = err.message; errEl.classList.remove("hidden");
  } finally { btn.disabled = false; btn.textContent = "Sign In"; }
});

function logout() {
  S.token = null;
  localStorage.removeItem("manage_ai_token");
  clearTimers(); hideEl("app"); showEl("loginOverlay");
}

/* ═══════════════════════════════════════════════════════════
   API
════════════════════════════════════════════════════════════ */
async function api(path, opts = {}) {
  const headers = {};
  if (S.token) headers["Authorization"] = `Bearer ${S.token}`;
  if (opts.body && !(opts.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    if (typeof opts.body !== "string") opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers: { ...headers, ...(opts.headers||{}) } });
  if (res.status === 401) { logout(); throw new Error("Session expired"); }
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { const j = await res.json(); msg = j.detail || JSON.stringify(j); } catch {}
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

/* ═══════════════════════════════════════════════════════════
   HEALTH
════════════════════════════════════════════════════════════ */
async function pollHealth() {
  try {
    const r = await fetch(`${API_BASE}/api/health`);
    g("healthDot").className  = "health-dot " + (r.ok ? "ok" : "err");
    g("healthText").textContent = r.ok ? "API Online" : "API Error";
  } catch {
    g("healthDot").className  = "health-dot err";
    g("healthText").textContent = "API Offline";
  }
}

/* ═══════════════════════════════════════════════════════════
   INDUSTRY DETECTION
════════════════════════════════════════════════════════════ */
async function detectIndustry() {
  try {
    const data = await api("/api/kb/industry");
    S.industry = data;
    const badge = g("industryBadge");
    if (data.detected && data.industry !== "Unknown") {
      badge.innerHTML = `
        <span class="ib-icon">🏢</span>
        <span>${esc(data.industry)}</span>
        <span class="ib-conf">${Math.round((data.confidence || 0) * 100)}%</span>`;
      badge.classList.remove("hidden");
      badge.title = data.reasoning || "";
    } else {
      badge.classList.add("hidden");
    }
  } catch { /* silent — no KB docs yet */ }
}

/* ═══════════════════════════════════════════════════════════
   NAVIGATION
════════════════════════════════════════════════════════════ */
function setupNav() {
  document.querySelectorAll(".nav-item").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      switchView(btn.dataset.view, btn.dataset.title);
    });
  });
}

function switchView(name, title) {
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active-view"));
  g(`${name}View`)?.classList.add("active-view");
  if (title) g("pageTitle").textContent = title;
  if (name === "departments") loadDeptDashboard(S.activeDept);
  if (name === "workflow")    loadWorkflows();
  if (name === "report")      loadReports();
  if (name === "task")        loadTasks();
  if (name === "ops")         loadNotifications();
}

/* ═══════════════════════════════════════════════════════════
   AUTO-REFRESH
════════════════════════════════════════════════════════════ */
function startAutoRefresh() {
  clearInterval(S.refreshTimer);
  S.refreshTimer = setInterval(() => {
    if (g("overviewView")?.classList.contains("active-view")) loadOverview();
  }, AUTO_REFRESH);
}
function clearTimers() { clearInterval(S.refreshTimer); clearInterval(S.pollTimer); }

/* ═══════════════════════════════════════════════════════════
   OVERVIEW
════════════════════════════════════════════════════════════ */
async function loadOverview() {
  try {
    const [workflows, tasks, domains] = await Promise.all([
      api("/api/workflows"),
      api("/api/tasks"),
      api("/api/kb/domains"),
    ]);
    S.workflows = workflows || [];
    S.tasks     = tasks     || [];
    S.domains   = domains   || [];

    const pending   = S.workflows.filter(w => w.approval_status === "pending");
    const completed = S.workflows.filter(w => w.status === "tasks_generated");
    const inProg    = S.tasks.filter(t => t.status === "in_progress");

    g("metricGrid").innerHTML = `
      <div class="metric-card c-primary">
        <div class="metric-value">${S.workflows.length}</div>
        <div class="metric-label">Total Workflows</div>
        <div class="metric-sub">${completed.length} completed</div>
      </div>
      <div class="metric-card c-warning">
        <div class="metric-value">${pending.length}</div>
        <div class="metric-label">Pending Approvals</div>
        <div class="metric-sub">Awaiting your decision</div>
      </div>
      <div class="metric-card c-success">
        <div class="metric-value">${S.tasks.length}</div>
        <div class="metric-label">Department Tasks</div>
        <div class="metric-sub">${inProg.length} in progress</div>
      </div>
      <div class="metric-card c-info">
        <div class="metric-value">${S.domains.length}</div>
        <div class="metric-label">KB Domains</div>
        <div class="metric-sub">${S.domains.filter(d => d.is_active).length} active</div>
      </div>`;

    g("recentWorkflows").innerHTML = S.workflows.length
      ? S.workflows.slice(0, 6).map(w => `
          <div class="item-row" style="cursor:pointer" onclick="navToWorkflow('${w.id}')">
            <div class="item-title">${esc(truncate(w.objective_text, 65))}</div>
            <div class="item-meta">
              ${statusPill(w.status)} ${approvalPill(w.approval_status)}
              <span class="badge badge-gray">${esc(w.department)}</span>
            </div>
          </div>`).join("")
      : emptyState("No workflows yet", "Submit an objective in the Workflows tab to get started");

    g("pendingBadge").textContent = pending.length;
    g("pendingApprovals").innerHTML = pending.length
      ? pending.map(w => `
          <div class="item-row">
            <div class="item-title">${esc(truncate(w.objective_text, 60))}</div>
            <div class="item-meta"><span class="badge badge-gray">${esc(w.department)}</span></div>
            <div style="display:flex;gap:.375rem;margin-top:.5rem">
              <button class="btn btn-success btn-sm" onclick="openApproveModal('${w.id}')">✓ Approve</button>
              <button class="btn btn-danger btn-sm"  onclick="openRejectModal('${w.id}')">✕ Reject</button>
            </div>
          </div>`).join("")
      : emptyState("No pending approvals", "All workflows are up to date");
  } catch (err) { toast("Failed to load overview: " + err.message, "error"); }
}

function navToWorkflow(id) {
  document.querySelectorAll(".nav-item").forEach(b => b.classList.toggle("active", b.dataset.view === "workflow"));
  switchView("workflow", "Workflows");
  S.selectedWorkflowId = id;
  loadWorkflows().then(() => openWorkflowDetail(id));
}

/* ═══════════════════════════════════════════════════════════
   DEPARTMENT DASHBOARD
════════════════════════════════════════════════════════════ */
function setupDeptTabs() {
  document.querySelectorAll(".dept-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".dept-tab").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      S.activeDept = btn.dataset.dept;
      loadDeptDashboard(S.activeDept);
    });
  });
}

async function reloadDept() { loadDeptDashboard(S.activeDept); }

async function loadDeptDashboard(dept) {
  S.activeDept = dept;
  const label = dept.charAt(0).toUpperCase() + dept.slice(1);
  g("deptWorkflowsTitle").textContent = `${label} Workflows`;
  g("deptTasksTitle").textContent     = `${label} Tasks`;

  try {
    const [allWf, allTasks] = await Promise.all([
      api("/api/workflows"),
      api(`/api/tasks?department=${encodeURIComponent(dept)}`),
    ]);
    S.workflows = allWf || [];
    const deptWf    = S.workflows.filter(w => w.department?.toLowerCase() === dept.toLowerCase());
    const deptTasks = allTasks || [];

    const pending  = deptWf.filter(w => w.approval_status === "pending");
    const queued   = deptTasks.filter(t => t.status === "queued");
    const inProg   = deptTasks.filter(t => t.status === "in_progress");
    const done     = deptTasks.filter(t => t.status === "done");

    g("deptMetrics").innerHTML = `
      <div class="metric-card c-primary">
        <div class="metric-value">${deptWf.length}</div>
        <div class="metric-label">${label} Workflows</div>
        <div class="metric-sub">${deptWf.filter(w=>w.status==="tasks_generated").length} completed</div>
      </div>
      <div class="metric-card c-warning">
        <div class="metric-value">${pending.length}</div>
        <div class="metric-label">Pending Approval</div>
        <div class="metric-sub">Need your decision</div>
      </div>
      <div class="metric-card c-info">
        <div class="metric-value">${queued.length + inProg.length}</div>
        <div class="metric-label">Active Tasks</div>
        <div class="metric-sub">${inProg.length} in progress</div>
      </div>
      <div class="metric-card c-success">
        <div class="metric-value">${done.length}</div>
        <div class="metric-label">Tasks Done</div>
        <div class="metric-sub">of ${deptTasks.length} total</div>
      </div>`;

    // Workflow list for this dept
    g("deptWorkflowList").innerHTML = deptWf.length
      ? deptWf.map(w => `
          <div class="item-row">
            <div class="item-title">${esc(truncate(w.objective_text, 60))}</div>
            <div class="item-meta">${statusPill(w.status)} ${approvalPill(w.approval_status)}</div>
            ${w.approval_status === "pending" ? `
              <div style="display:flex;gap:.375rem;margin-top:.5rem">
                <button class="btn btn-success btn-sm" onclick="openApproveModal('${w.id}')">✓ Approve</button>
                <button class="btn btn-danger btn-sm"  onclick="openRejectModal('${w.id}')">✕ Reject</button>
                <button class="btn btn-outline btn-sm" onclick="navToWorkflow('${w.id}')">View Report</button>
              </div>` : `
              <button class="btn btn-ghost btn-sm" onclick="navToWorkflow('${w.id}')" style="margin-top:.375rem">View Detail</button>`}
          </div>`).join("")
      : emptyState(`No ${label} workflows`, "Submit an objective for this department");

    // Mini task board (2 columns: active + done)
    g("deptTaskBoard").innerHTML = [
      { key: "queued",      label: "Queued",      color: "var(--text-3)"  },
      { key: "in_progress", label: "In Progress", color: "var(--primary)" },
      { key: "blocked",     label: "Blocked",     color: "var(--danger)"  },
      { key: "done",        label: "Done",        color: "var(--success)" },
    ].map(col => {
      const cards = deptTasks.filter(t => t.status === col.key);
      return `
        <div class="task-col">
          <div class="task-col-head">
            <h4 style="color:${col.color}">${col.label}</h4>
            <span class="task-col-count">${cards.length}</span>
          </div>
          <div class="task-cards">
            ${cards.length ? cards.map(taskCard).join("") : `<div class="empty-col">None</div>`}
          </div>
        </div>`;
    }).join("");
  } catch (err) { toast("Failed to load department: " + err.message, "error"); }
}

/* ═══════════════════════════════════════════════════════════
   WORKFLOWS
════════════════════════════════════════════════════════════ */
async function loadWorkflows() {
  try {
    S.workflows = await api("/api/workflows") || [];
    renderWorkflowList();
  } catch (err) { toast("Failed to load workflows: " + err.message, "error"); }
}

function renderWorkflowList() {
  const el = g("workflowList");
  el.innerHTML = S.workflows.length
    ? S.workflows.map(w => `
        <div class="item-row ${w.id === S.selectedWorkflowId ? "selected" : ""}" onclick="selectWorkflow('${w.id}')">
          <div class="item-title">${esc(truncate(w.objective_text, 58))}</div>
          <div class="item-meta">
            ${statusPill(w.status)} ${approvalPill(w.approval_status)}
            <span class="badge badge-gray">${esc(w.department)}</span>
          </div>
        </div>`).join("")
    : emptyState("No workflows yet", "Submit an objective above");
}

async function selectWorkflow(id) {
  S.selectedWorkflowId = id;
  renderWorkflowList();
  openWorkflowDetail(id);
}

async function openWorkflowDetail(id) {
  const detail  = g("workflowDetail");
  const content = g("workflowDetailContent");
  detail.classList.remove("hidden");
  content.innerHTML = `<div class="empty-state"><div class="empty-title">Loading...</div></div>`;
  try {
    const wf    = S.workflows.find(w => w.id === id);
    if (!wf) throw new Error("Workflow not found");
    const state = wf.state || wf.state_blob || {};
    const rpt   = state.decision_report;
    const ip    = wf.approval_status === "pending";
    const hasReport = !!rpt;

    content.innerHTML = `
      <div class="detail-header">
        <div>
          <div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;margin-bottom:.25rem">
            <strong>${esc(wf.department?.toUpperCase())} Workflow</strong>
            ${statusPill(wf.status)} ${approvalPill(wf.approval_status)}
          </div>
          <div style="font-size:.72rem;color:var(--text-3)">ID: ${wf.id}</div>
        </div>
        <div class="detail-actions">
          ${ip ? `
            <button class="btn btn-success btn-sm" onclick="openApproveModal('${wf.id}')">✓ Approve</button>
            <button class="btn btn-danger btn-sm"  onclick="openRejectModal('${wf.id}')">✕ Reject</button>` : ""}
          ${hasReport ? `<button class="btn btn-pdf btn-sm" onclick="exportReportPDF('${wf.id}')">⬇ Export PDF</button>` : ""}
          <button class="btn btn-outline btn-sm" onclick="openAuditModal('${wf.id}')">Audit Trail</button>
        </div>
      </div>

      <div style="padding:.875rem;background:var(--surface-2);border-radius:var(--radius);border-left:3px solid var(--primary);font-size:.875rem;line-height:1.65">
        ${esc(wf.objective_text)}
      </div>

      ${state.subtasks?.length ? `
        <div class="detail-section">
          <div class="detail-section-title">① Orchestrator — Subtask Breakdown</div>
          ${state.subtasks.map(s => `
            <div class="subtask-item">
              <div class="subtask-title">${esc(s.title || s)}</div>
              ${s.description ? `<div class="subtask-desc">${esc(s.description)}</div>` : ""}
            </div>`).join("")}
        </div>` : ""}

      ${state.learner_report ? `
        <div class="detail-section">
          <div class="detail-section-title">② Learner — Knowledge Base Findings</div>
          <div class="kv-grid">
            <div class="kv-card"><div class="kv-key">Feasibility Score</div><div class="kv-val">${state.learner_report.feasibility_score ?? "—"} / 1.0</div></div>
            <div class="kv-card"><div class="kv-key">Confidence</div><div class="kv-val">${state.learner_report.confidence ?? "—"} / 1.0</div></div>
          </div>
          ${state.learner_report.supporting_evidence?.length ? `
            <div style="font-size:.72rem;font-weight:700;text-transform:uppercase;color:var(--success);margin-bottom:.375rem">Supporting Evidence</div>
            ${state.learner_report.supporting_evidence.map(e => `<div class="evidence-item">✓ ${esc(e)}</div>`).join("")}` : ""}
          ${state.learner_report.identified_gaps?.length ? `
            <div style="font-size:.72rem;font-weight:700;text-transform:uppercase;color:var(--warning);margin:.5rem 0 .375rem">Identified Gaps</div>
            ${state.learner_report.identified_gaps.map(g2 => `<div class="gap-item">⚠ ${esc(g2)}</div>`).join("")}` : ""}
        </div>` : ""}

      ${rpt ? `
        <div class="detail-section">
          <div class="detail-section-title">③ Decision Maker — Recommendation</div>
          <div class="kv-grid">
            <div class="kv-card"><div class="kv-key">Recommendation</div><div class="kv-val">${esc(rpt.recommendation || "—")}</div></div>
            <div class="kv-card"><div class="kv-key">Risk Level</div><div class="kv-val">${riskPill(rpt.risk_level)}</div></div>
          </div>
          ${rpt.summary ? `<div class="markdown-body">${renderMd(rpt.summary)}</div>` : ""}
        </div>` : ""}

      ${state.task_assignments?.length ? `
        <div class="detail-section">
          <div class="detail-section-title">④ Task Generator — Department Tasks</div>
          ${state.task_assignments.map(t => `
            <div class="task-gen-card">
              <div class="task-gen-header"><strong>${esc(t.department)}</strong> ${statusPill(t.status)}</div>
              <div class="task-gen-instructions">${esc(t.instructions)}</div>
              ${t.deadline ? `<div class="task-gen-deadline">Deadline: ${t.deadline}</div>` : ""}
            </div>`).join("")}
        </div>` : ""}
    `;
  } catch (err) {
    content.innerHTML = `<div class="empty-state"><div class="empty-title">Error: ${esc(err.message)}</div></div>`;
  }
}

/* ═══════════════════════════════════════════════════════════
   FORMS SETUP
════════════════════════════════════════════════════════════ */
function setupForms() {
  g("objectiveForm").addEventListener("submit", submitObjective);
  g("domainForm").addEventListener("submit", createDomain);
  g("uploadForm").addEventListener("submit", uploadDoc);
  g("searchForm").addEventListener("submit", searchKB);
}

/* ═══════════════════════════════════════════════════════════
   SUBMIT OBJECTIVE
════════════════════════════════════════════════════════════ */
async function submitObjective(e) {
  e.preventDefault();
  const text = v("objText").trim();
  if (!text) { toast("Please enter an objective", "error"); return; }
  const btn = g("submitBtn");
  btn.disabled = true; btn.textContent = "Submitting...";
  try {
    const result = await api("/api/objectives", {
      method: "POST",
      body: { department: v("objDept"), priority: v("objPriority"), objective_text: text },
    });
    S.trackedWorkflowId = result.workflow_id;
    toast("Objective submitted — agents are running", "success");
    g("objText").value = "";
    showPipelineViz();
    setPipelineNode("orchestrator", "active");
    setPipelineMsg("Orchestrator is breaking your objective into subtasks...");
    startPolling(result.workflow_id);
    loadWorkflows();
  } catch (err) { toast("Submit failed: " + err.message, "error"); }
  finally { btn.disabled = false; btn.textContent = "↳ Submit to AI Pipeline"; }
}

/* ═══════════════════════════════════════════════════════════
   PIPELINE
════════════════════════════════════════════════════════════ */
const NODES = ["orchestrator","learner","decision_maker","hitl","task_generator"];

function showPipelineViz() { g("pipelineViz").classList.remove("hidden"); }
function setPipelineNode(n, s) {
  const el = g(`pn-${n}`);
  if (el) el.className = "pipeline-node" + (s ? ` pn-${s}` : "");
}
function setPipelineMsg(msg) { g("pipelineMsg").textContent = msg; }

const STATUS_MAP = {
  orchestrated:      { done:["orchestrator"],                                    active:"learner",        msg:"Learner is researching the Knowledge Base..." },
  learned:           { done:["orchestrator","learner"],                           active:"decision_maker", msg:"Decision Maker is generating recommendation..." },
  awaiting_approval: { done:["orchestrator","learner","decision_maker"],          wait:"hitl",             msg:"⏸ Waiting for your approval — go to Reports tab" },
  rejected:          { done:["orchestrator","learner","decision_maker"],          active:"hitl",           msg:"Workflow rejected — re-running with your feedback..." },
  tasks_generated:   { done:["orchestrator","learner","decision_maker","hitl","task_generator"], msg:"✓ Complete — department tasks created and queued" },
};

function applyPipelineStatus(status) {
  const map = STATUS_MAP[status];
  if (!map) return;
  NODES.forEach(n => {
    if (map.done?.includes(n))    setPipelineNode(n, "done");
    else if (map.wait === n)      setPipelineNode(n, "wait");
    else if (map.active === n)    setPipelineNode(n, "active");
    else                          setPipelineNode(n, "");
  });
  if (map.msg) setPipelineMsg(map.msg);
}

function startPolling(workflowId) {
  clearInterval(S.pollTimer);
  S.pollTimer = setInterval(async () => {
    try {
      S.workflows = await api("/api/workflows") || [];
      renderWorkflowList();
      const wf = S.workflows.find(w => w.id === workflowId);
      if (!wf) return;
      applyPipelineStatus(wf.status);
      if (wf.status === "awaiting_approval") {
        clearInterval(S.pollTimer);
        toast("Decision ready — please approve or reject in Reports", "info");
        loadOverview();
      }
      if (wf.status === "tasks_generated") {
        clearInterval(S.pollTimer);
        toast("Tasks generated and dispatched to department queues!", "success");
        loadOverview(); loadTasks();
      }
    } catch { /* silent */ }
  }, POLL_INTERVAL);
}

/* ═══════════════════════════════════════════════════════════
   APPROVE / REJECT MODALS
════════════════════════════════════════════════════════════ */
function openApproveModal(workflowId) {
  openModal("Approve Decision Report", `
    <p style="font-size:.875rem;color:var(--text-2);margin-bottom:1rem;line-height:1.65">
      Approving will immediately trigger the <strong>Task Generator</strong> to create department
      tasks. You can add optional guidance below.
    </p>
    <div class="field">
      <label>Feedback for Task Generator (optional)</label>
      <textarea id="approveFeedback" rows="3" placeholder="e.g. Focus on HR first, keep budget under £50k..."></textarea>
    </div>`,
    async () => {
      const feedback = v("approveFeedback") || null;
      await api(`/api/workflows/${workflowId}/approve`, { method: "POST", body: { feedback } });
      toast("Approved! Task Generator is running...", "success");
      closeModal();
      if (S.trackedWorkflowId === workflowId) {
        setPipelineNode("hitl","done"); setPipelineNode("task_generator","active");
        setPipelineMsg("Task Generator is creating department tasks...");
      }
      startPolling(workflowId);
      loadWorkflows(); loadOverview();
    },
    { confirmText: "Approve", confirmClass: "btn btn-success" }
  );
}

function openRejectModal(workflowId) {
  openModal("Reject & Request Revision", `
    <p style="font-size:.875rem;color:var(--text-2);margin-bottom:1rem;line-height:1.65">
      Rejecting sends the workflow back to the <strong>Orchestrator</strong> with your feedback.
      All agents will revise their outputs. Feedback is required.
    </p>
    <div class="field">
      <label>Rejection Reason <span class="req">*</span></label>
      <textarea id="rejectFeedback" rows="3" placeholder="Explain what needs to change..."></textarea>
    </div>`,
    async () => {
      const feedback = v("rejectFeedback").trim();
      if (!feedback) { toast("Feedback is required when rejecting", "error"); return; }
      await api(`/api/workflows/${workflowId}/reject`, { method: "POST", body: { feedback } });
      toast("Rejected — workflow re-looping with your feedback", "info");
      closeModal();
      if (S.trackedWorkflowId === workflowId) {
        showPipelineViz(); NODES.forEach(n => setPipelineNode(n,""));
        setPipelineMsg("Workflow re-looping after rejection...");
      }
      startPolling(workflowId); S.trackedWorkflowId = workflowId;
      loadWorkflows(); loadOverview();
    },
    { confirmText: "Reject", confirmClass: "btn btn-danger" }
  );
}

async function openAuditModal(workflowId) {
  try {
    const data = await api(`/api/audit/${workflowId}`);
    openModal("Audit Trail",
      `<pre style="font-size:.75rem;white-space:pre-wrap;max-height:360px;overflow-y:auto">${esc(JSON.stringify(data,null,2))}</pre>`,
      null
    );
  } catch (err) { toast("Audit load failed: " + err.message, "error"); }
}

/* ═══════════════════════════════════════════════════════════
   PDF EXPORT — INDUSTRY-STANDARD DECISION REPORT
════════════════════════════════════════════════════════════ */
async function exportReportPDF(workflowId) {
  const wf = S.workflows.find(w => w.id === workflowId);
  if (!wf) { toast("Workflow not found", "error"); return; }

  const state = wf.state || wf.state_blob || {};
  const rpt   = state.decision_report;

  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ unit: "mm", format: "a4" });

  const W = 210, H = 297, M = 20, CW = W - 2 * M;
  const INDIGO = [99, 102, 241];
  const GREEN  = [16, 185, 129];
  const AMBER  = [245, 158, 11];
  const RED    = [239, 68, 68];
  const DARK   = [17, 24, 39];
  const MUTED  = [107, 114, 128];

  const riskColor = { low: GREEN, medium: AMBER, high: RED, critical: RED };
  const totalPages = 4;

  const footer = (pg) => {
    doc.setFontSize(7.5); doc.setTextColor(...MUTED);
    doc.line(M, H-14, W-M, H-14);
    const company = S.industry?.industry !== "Unknown" ? `${S.industry?.industry} | ` : "";
    doc.text(`${company}Manage AI Decision Report | Confidential`, M, H-9);
    doc.text(`Page ${pg} of ${totalPages}`, W-M, H-9, { align: "right" });
    doc.setTextColor(0);
  };

  const sectionHeader = (title) => {
    doc.setFillColor(...INDIGO);
    doc.rect(0, 0, W, 20, "F");
    doc.setFontSize(10.5); doc.setTextColor(255, 255, 255); doc.setFont("helvetica","bold");
    doc.text(title, M, 13.5);
    doc.setTextColor(0); doc.setFont("helvetica","normal");
    return 32;
  };

  const dateStr = new Date().toLocaleDateString("en-GB", { year:"numeric", month:"long", day:"numeric" });
  const refNo   = `WF-${workflowId.substring(0,8).toUpperCase()}`;

  /* ── PAGE 1: COVER ── */
  doc.setFillColor(...INDIGO);
  doc.rect(0, 0, W, 70, "F");

  // Logo circle
  doc.setFillColor(255,255,255);
  doc.circle(M + 16, 34, 13, "F");
  doc.setFontSize(16); doc.setFont("helvetica","bold"); doc.setTextColor(...INDIGO);
  doc.text("M", M + 11.5, 39.5);

  // Report title
  doc.setTextColor(255,255,255);
  doc.setFontSize(20); doc.setFont("helvetica","bold");
  doc.text("DECISION REPORT", M + 40, 28);
  doc.setFontSize(11); doc.setFont("helvetica","normal");
  doc.text(`${(wf.department || "").toUpperCase()} DEPARTMENT`, M + 40, 38);
  doc.setFontSize(8.5);
  doc.text(`Reference: ${refNo}  ·  ${dateStr}`, M + 40, 50);
  doc.text(`Priority: ${(wf.priority || "medium").toUpperCase()}`, M + 40, 58);

  // Status pill (top right)
  const isApproved = wf.approval_status === "approved";
  doc.setFillColor(...(isApproved ? GREEN : AMBER));
  doc.roundedRect(W - M - 32, 22, 30, 10, 2, 2, "F");
  doc.setFontSize(7.5); doc.setFont("helvetica","bold"); doc.setTextColor(255,255,255);
  doc.text((wf.approval_status||"pending").toUpperCase(), W - M - 17, 28.5, { align:"center" });

  // Industry tag (if detected)
  if (S.industry?.detected && S.industry.industry !== "Unknown") {
    doc.setFillColor(139, 92, 246);
    doc.roundedRect(W - M - 32, 36, 30, 10, 2, 2, "F");
    doc.setFontSize(7); doc.setFont("helvetica","normal");
    doc.text(truncate(S.industry.industry, 18), W - M - 17, 42.5, { align:"center" });
  }

  // Objective box
  doc.setTextColor(0); doc.setFont("helvetica","normal");
  let y = 84;
  doc.setFontSize(7.5); doc.setFont("helvetica","bold"); doc.setTextColor(...INDIGO);
  doc.text("OBJECTIVE", M, y); y += 5;
  doc.setFont("helvetica","normal"); doc.setFontSize(10.5); doc.setTextColor(...DARK);
  const objLines = doc.splitTextToSize(wf.objective_text || "", CW);
  doc.text(objLines.slice(0, 6), M, y); y += objLines.slice(0,6).length * 5.5 + 8;

  // Divider
  doc.setDrawColor(220,220,220); doc.line(M, y, W-M, y); y += 8;

  // Recommendation callout
  if (rpt) {
    doc.setFillColor(236, 253, 245);
    doc.roundedRect(M, y, CW, 28, 2, 2, "F");
    doc.setFontSize(7.5); doc.setFont("helvetica","bold"); doc.setTextColor(...GREEN);
    doc.text("RECOMMENDATION", M + 5, y + 7);
    doc.setFont("helvetica","normal"); doc.setFontSize(10); doc.setTextColor(...DARK);
    const recL = doc.splitTextToSize(rpt.recommendation || "—", CW - 12);
    doc.text(recL.slice(0,2), M + 5, y + 14);
    y += 34;

    // Risk badge
    const rc = riskColor[rpt.risk_level] || MUTED;
    doc.setFillColor(...rc);
    doc.roundedRect(M, y, 42, 18, 2, 2, "F");
    doc.setFontSize(7); doc.setFont("helvetica","bold"); doc.setTextColor(255,255,255);
    doc.text("RISK LEVEL", M + 21, y + 7, { align:"center" });
    doc.setFontSize(12); doc.text((rpt.risk_level||"—").toUpperCase(), M + 21, y + 14.5, { align:"center" });
    y += 26;

    // Feasibility
    if (state.learner_report) {
      const lr = state.learner_report;
      doc.setFillColor(239, 246, 255);
      doc.roundedRect(M + 50, y - 26, 70, 18, 2, 2, "F");
      doc.setFontSize(7); doc.setFont("helvetica","bold"); doc.setTextColor(...INDIGO);
      doc.text("FEASIBILITY", M + 85, y - 20, { align:"center" });
      doc.setFontSize(16); doc.setFont("helvetica","bold");
      doc.text(`${((lr.feasibility_score||0)*10).toFixed(1)}/10`, M + 85, y - 10, { align:"center" });
    }
  }

  // Prepared by
  doc.setFontSize(8); doc.setFont("helvetica","italic"); doc.setTextColor(...MUTED);
  doc.text("Prepared by Manage AI Autonomous Agent System", M, 256);
  doc.text("This report was generated by AI agents and requires human review before implementation.", M, 263);

  footer(1);

  /* ── PAGE 2: KB ANALYSIS + SUBTASKS ── */
  doc.addPage();
  y = sectionHeader("SECTION 1 — KNOWLEDGE BASE ANALYSIS & AGENT FINDINGS");

  if (state.learner_report) {
    const lr = state.learner_report;

    // Score bars
    const drawBar = (label, score, bx, by) => {
      doc.setFontSize(8); doc.setFont("helvetica","bold"); doc.setTextColor(...MUTED);
      doc.text(label.toUpperCase(), bx, by);
      doc.setFillColor(230, 230, 230); doc.rect(bx, by + 2, 65, 4.5, "F");
      doc.setFillColor(...INDIGO); doc.rect(bx, by + 2, 65 * (score || 0), 4.5, "F");
      doc.setFontSize(7.5); doc.setTextColor(...DARK);
      doc.text(`${((score||0)*10).toFixed(1)}/10`, bx + 68, by + 6);
    };
    drawBar("Feasibility Score", lr.feasibility_score, M, y);
    drawBar("Confidence Level",  lr.confidence,         M + 100, y);
    y += 16;

    // Evidence
    if (lr.supporting_evidence?.length) {
      doc.setFontSize(8.5); doc.setFont("helvetica","bold"); doc.setTextColor(...GREEN);
      doc.text("SUPPORTING EVIDENCE FROM KNOWLEDGE BASE", M, y); y += 6;
      lr.supporting_evidence.forEach(ev => {
        doc.setFillColor(236,253,245); doc.roundedRect(M, y, CW, 8, 1, 1, "F");
        doc.setFont("helvetica","normal"); doc.setFontSize(8.5); doc.setTextColor(...DARK);
        const ls = doc.splitTextToSize(`✓  ${ev}`, CW - 8);
        doc.text(ls[0], M + 4, y + 5.5);
        y += 10;
      });
      y += 2;
    }

    // Gaps
    if (lr.identified_gaps?.length) {
      doc.setFontSize(8.5); doc.setFont("helvetica","bold"); doc.setTextColor(...AMBER);
      doc.text("IDENTIFIED KNOWLEDGE GAPS", M, y); y += 6;
      lr.identified_gaps.forEach(gap => {
        doc.setFillColor(255,251,235); doc.roundedRect(M, y, CW, 8, 1, 1, "F");
        doc.setFont("helvetica","normal"); doc.setFontSize(8.5); doc.setTextColor(...DARK);
        const ls = doc.splitTextToSize(`⚠  ${gap}`, CW - 8);
        doc.text(ls[0], M + 4, y + 5.5);
        y += 10;
      });
      y += 4;
    }
  }

  // Subtasks
  if (state.subtasks?.length) {
    doc.setFontSize(8.5); doc.setFont("helvetica","bold"); doc.setTextColor(...INDIGO);
    doc.text("ORCHESTRATOR — OBJECTIVE DECOMPOSITION", M, y); y += 7;
    state.subtasks.forEach((s, i) => {
      const title = s.title || (typeof s === "string" ? s : "");
      doc.setFontSize(8.5); doc.setFont("helvetica","bold"); doc.setTextColor(...DARK);
      const tl = doc.splitTextToSize(`${i+1}.  ${title}`, CW - 5);
      doc.text(tl, M + 3, y); y += tl.length * 5 + 1;
      if (s.description) {
        doc.setFont("helvetica","normal"); doc.setFontSize(8); doc.setTextColor(...MUTED);
        const dl = doc.splitTextToSize(`     ${s.description}`, CW - 10);
        doc.text(dl.slice(0,2), M + 6, y); y += dl.slice(0,2).length * 4.5 + 1;
        doc.setTextColor(...DARK);
      }
    });
  }

  footer(2);

  /* ── PAGE 3: RECOMMENDATION ── */
  doc.addPage();
  y = sectionHeader("SECTION 2 — DECISION MAKER RECOMMENDATION");

  if (rpt?.summary) {
    const plain = rpt.summary
      .replace(/#{1,3}\s*/g, "")
      .replace(/\*\*(.+?)\*\*/g, "$1")
      .replace(/\*(.+?)\*/g, "$1")
      .replace(/^- /gm, "• ");

    const lines = doc.splitTextToSize(plain, CW);
    doc.setFontSize(9); doc.setFont("helvetica","normal"); doc.setTextColor(...DARK);
    lines.forEach(line => {
      if (y > H - 22) { doc.addPage(); y = 25; }
      const isBullet = line.trim().startsWith("•");
      if (isBullet) { doc.setFont("helvetica","normal"); }
      doc.text(line, M, y);
      y += 5.5;
    });
  } else {
    doc.setFontSize(9); doc.setTextColor(...MUTED);
    doc.text("No decision report summary available.", M, y);
  }

  footer(3);

  /* ── PAGE 4: ACTION PLAN ── */
  doc.addPage();
  y = sectionHeader("SECTION 3 — ACTION PLAN & DEPARTMENT TASK ASSIGNMENTS");

  if (state.task_assignments?.length) {
    doc.autoTable({
      startY: y,
      margin: { left: M, right: M },
      head: [["#", "Department", "Instructions", "Deadline", "Status"]],
      body: state.task_assignments.map((t, i) => [
        i + 1,
        t.department,
        truncate(t.instructions || "", 130),
        t.deadline || "—",
        (t.status || "queued").replace(/_/g," "),
      ]),
      styles: { fontSize: 8, cellPadding: 3, lineColor: [220,220,220], lineWidth: 0.3 },
      headStyles: { fillColor: INDIGO, textColor: 255, fontStyle:"bold", fontSize: 8 },
      columnStyles: {
        0: { cellWidth: 8 },
        1: { cellWidth: 26 },
        2: { cellWidth: 98 },
        3: { cellWidth: 28 },
        4: { cellWidth: 20 },
      },
      alternateRowStyles: { fillColor: [248, 249, 255] },
      didDrawPage: () => footer(doc.internal.getCurrentPageInfo().pageNumber),
    });

    // Dependency note if any tasks have dependencies
    const withDeps = state.task_assignments.filter(t => t.depends_on?.length);
    if (withDeps.length) {
      const fy = doc.lastAutoTable.finalY + 8;
      doc.setFontSize(7.5); doc.setFont("helvetica","italic"); doc.setTextColor(...MUTED);
      doc.text("Note: Some tasks have dependencies. Refer to the Manage AI platform for the full dependency graph.", M, fy);
    }
  } else {
    doc.setFontSize(9); doc.setTextColor(...MUTED);
    doc.text("No tasks have been generated yet for this workflow.", M, y);
  }

  footer(4);

  const filename = `report-${refNo}-${dateStr.replace(/ /g,"-")}.pdf`;
  doc.save(filename);
  toast(`PDF exported: ${filename}`, "success");
}

/* ═══════════════════════════════════════════════════════════
   REPORTS
════════════════════════════════════════════════════════════ */
async function loadReports() {
  const el = g("reportList");
  el.innerHTML = `<div class="empty-state"><div class="empty-title">Loading...</div></div>`;
  try {
    S.workflows = await api("/api/workflows") || [];
    const withReports = S.workflows.filter(w => {
      const s = w.state || w.state_blob || {};
      return s.decision_report;
    });
    if (!withReports.length) {
      el.innerHTML = emptyState("No decision reports yet",
        "Reports appear here after the Decision Maker agent completes. Submit an objective in Workflows.");
      return;
    }
    el.innerHTML = withReports.map(w => {
      const state = w.state || w.state_blob || {};
      const rpt   = state.decision_report;
      const ip    = w.approval_status === "pending";
      return `
        <div class="report-card">
          <div class="report-card-header">
            <div>
              <div class="report-card-title">${esc(w.department?.toUpperCase())} Decision Report</div>
              <div class="report-card-obj">${esc(truncate(w.objective_text, 110))}</div>
              <div class="report-card-pills">${statusPill(w.status)} ${approvalPill(w.approval_status)}</div>
            </div>
            <div class="report-card-actions">
              ${ip ? `
                <button class="btn btn-success btn-sm" onclick="openApproveModal('${w.id}')">✓ Approve</button>
                <button class="btn btn-danger btn-sm"  onclick="openRejectModal('${w.id}')">✕ Reject</button>` : ""}
              <button class="btn btn-pdf btn-sm" onclick="exportReportPDF('${w.id}')">⬇ PDF</button>
              <button class="btn btn-outline btn-sm" onclick="navToWorkflow('${w.id}')">Full Detail</button>
            </div>
          </div>
          ${rpt ? `
            <div class="kv-grid" style="margin-bottom:.875rem">
              <div class="kv-card"><div class="kv-key">Recommendation</div><div class="kv-val">${esc(rpt.recommendation||"—")}</div></div>
              <div class="kv-card"><div class="kv-key">Risk Level</div><div class="kv-val">${riskPill(rpt.risk_level)}</div></div>
            </div>
            ${rpt.summary ? `<div class="markdown-body">${renderMd(rpt.summary)}</div>` : ""}
          ` : ""}
        </div>`;
    }).join("");
  } catch (err) {
    el.innerHTML = `<div class="empty-state"><div class="empty-title">Error: ${esc(err.message)}</div></div>`;
  }
}

/* ═══════════════════════════════════════════════════════════
   KNOWLEDGE BASE
════════════════════════════════════════════════════════════ */
async function loadDomains() {
  try {
    S.domains = await api("/api/kb/domains") || [];
    g("domainList").innerHTML = S.domains.length
      ? S.domains.map(d => `
          <div class="domain-item">
            <div>
              <div class="domain-name">${esc(d.name)}</div>
              <div class="domain-desc">${esc(d.description||"No description")}</div>
            </div>
            <span class="badge ${d.is_active?"badge-success":"badge-gray"}">${d.is_active?"Active":"Inactive"}</span>
          </div>`).join("")
      : emptyState("No domains", "Create one above");

    const opts = S.domains.map(d => `<option value="${d.id}">${esc(d.name)}</option>`).join("");
    g("uploadDomain").innerHTML = opts || `<option value="">— Create a domain first —</option>`;
    g("searchDomain").innerHTML = `<option value="">All Domains</option>` +
      S.domains.map(d => `<option value="${d.name}">${esc(d.name)}</option>`).join("");
  } catch (err) { toast("Failed to load domains: " + err.message, "error"); }
}

async function createDomain(e) {
  e.preventDefault();
  const name = v("domainName").trim(), desc = v("domainDesc").trim();
  if (!name) return;
  try {
    await api("/api/kb/domains", { method: "POST", body: { name, description: desc } });
    toast(`Domain "${name}" created`, "success");
    g("domainName").value = ""; g("domainDesc").value = "";
    loadDomains();
  } catch (err) { toast("Failed: " + err.message, "error"); }
}

async function uploadDoc(e) {
  e.preventDefault();
  const domainId = v("uploadDomain"), file = g("uploadFile").files[0];
  let metadata = {};
  try { metadata = JSON.parse(v("uploadMeta")); } catch { toast("Metadata must be valid JSON", "error"); return; }
  if (!domainId) { toast("Select a domain", "error"); return; }
  if (!file)     { toast("Select a file", "error"); return; }
  const btn = g("uploadBtn");
  btn.disabled = true; btn.textContent = "Uploading...";
  const fd = new FormData();
  fd.append("domain_id", domainId); fd.append("file", file); fd.append("metadata", JSON.stringify(metadata));
  try {
    const result = await api("/api/kb/ingest", { method: "POST", body: fd });
    g("uploadResult").classList.remove("hidden");
    g("uploadResult").textContent = JSON.stringify(result, null, 2);
    toast("Document ingested!", "success");
    g("uploadFile").value = "";
    detectIndustry(); // Re-run industry detection after new doc
  } catch (err) {
    g("uploadResult").classList.remove("hidden");
    g("uploadResult").textContent = "Error: " + err.message;
    toast("Upload failed: " + err.message, "error");
  } finally { btn.disabled = false; btn.textContent = "Upload to KB"; }
}

async function searchKB(e) {
  e.preventDefault();
  const q = v("searchQuery").trim(), domain = v("searchDomain");
  const el = g("searchResults");
  if (!q) return;
  el.innerHTML = `<div class="empty-state"><div class="empty-title">Searching...</div></div>`;
  try {
    const params = new URLSearchParams({ q });
    if (domain) params.set("domain", domain);
    const results = await api(`/api/kb/search?${params}`);
    el.innerHTML = results?.length
      ? results.map(r => `
          <div class="search-result">
            <div class="search-result-meta">
              <span class="badge badge-primary">${esc(r.domain || domain || "KB")}</span>
              <span class="badge badge-gray">Score: ${r.similarity_score?.toFixed(3)??"—"}</span>
              ${r.source_file ? `<span style="font-size:.72rem;color:var(--text-3)">${esc(r.source_file)}</span>` : ""}
            </div>
            <div class="search-result-content">${esc(truncate(r.content, 300))}</div>
          </div>`).join("")
      : emptyState("No results", "Try different keywords or upload more documents");
  } catch (err) { el.innerHTML = `<div class="empty-state"><div class="empty-title">Error: ${esc(err.message)}</div></div>`; }
}

/* ═══════════════════════════════════════════════════════════
   TASKS
════════════════════════════════════════════════════════════ */
async function loadTasks() {
  const dept = v("taskDeptFilter"), status = v("taskStatusFilter");
  const params = new URLSearchParams();
  if (dept)   params.set("department", dept);
  if (status) params.set("status", status);
  try {
    S.tasks = await api(`/api/tasks?${params}`) || [];
    renderTaskBoard();
  } catch (err) { toast("Failed to load tasks: " + err.message, "error"); }
}

const COLUMNS = [
  { key:"queued",      label:"Queued",      color:"var(--text-3)"  },
  { key:"in_progress", label:"In Progress", color:"var(--primary)" },
  { key:"blocked",     label:"Blocked",     color:"var(--danger)"  },
  { key:"done",        label:"Done",        color:"var(--success)" },
];

function renderTaskBoard() {
  g("taskBoard").innerHTML = COLUMNS.map(col => {
    const tasks = S.tasks.filter(t => t.status === col.key);
    return `<div class="task-col">
      <div class="task-col-head"><h4 style="color:${col.color}">${col.label}</h4><span class="task-col-count">${tasks.length}</span></div>
      <div class="task-cards">${tasks.length ? tasks.map(taskCard).join("") : `<div class="empty-col">No tasks</div>`}</div>
    </div>`;
  }).join("");
}

function taskCard(t) {
  const actions = {
    queued:      `<button class="btn btn-primary btn-sm" onclick="updateTask('${t.id}','in_progress')">Start</button><button class="btn btn-outline btn-sm" onclick="updateTask('${t.id}','blocked')">Block</button>`,
    in_progress: `<button class="btn btn-success btn-sm" onclick="updateTask('${t.id}','done')">Done</button><button class="btn btn-outline btn-sm" onclick="updateTask('${t.id}','blocked')">Block</button>`,
    blocked:     `<button class="btn btn-primary btn-sm" onclick="updateTask('${t.id}','in_progress')">Resume</button>`,
    done:        `<span style="font-size:.72rem;color:var(--success);font-weight:600">✓ Completed</span>`,
  };
  return `<div class="task-card">
    <div class="task-card-dept">${esc(t.department)}</div>
    <div class="task-card-text">${esc(truncate(t.instructions,120))}</div>
    <div class="task-card-actions">${actions[t.status]||""}</div>
  </div>`;
}

async function updateTask(taskId, newStatus) {
  try {
    await api(`/api/tasks/${taskId}/status`, { method:"PATCH", body:{ status: newStatus } });
    toast(`Task moved to ${newStatus.replace("_"," ")}`, "success");
    loadTasks();
  } catch (err) { toast("Update failed: " + err.message, "error"); }
}

/* ═══════════════════════════════════════════════════════════
   OPERATIONS
════════════════════════════════════════════════════════════ */
async function loadNotifications() {
  const el = g("notifList");
  try {
    S.notifications = await api("/api/operations/notifications") || [];
    el.innerHTML = S.notifications.length
      ? S.notifications.slice(0,25).map(n => `
          <div class="notif-item">
            <div class="notif-type">${esc(n.event_type)}</div>
            <div class="notif-meta">
              <span class="badge badge-gray">${esc(n.channel)}</span>
              <span class="badge ${n.status==="sent"?"badge-success":"badge-gray"}">${esc(n.status)}</span>
              <span style="font-size:.7rem;color:var(--text-3)">${fmtDate(n.created_at)}</span>
            </div>
          </div>`).join("")
      : emptyState("No notifications", "They appear as workflows progress");
  } catch (err) { el.innerHTML = `<div class="empty-state"><div class="empty-title">Error: ${esc(err.message)}</div></div>`; }
}

async function runExpiryCheck() {
  const el = g("maintResult");
  try {
    const r = await api("/api/operations/expiry/run", { method:"POST" });
    el.classList.remove("hidden"); el.textContent = JSON.stringify(r, null, 2);
    toast("Expiry check complete", "success");
  } catch (err) {
    el.classList.remove("hidden"); el.textContent = "Error: " + err.message;
    toast("Failed: " + err.message, "error");
  }
}

/* ═══════════════════════════════════════════════════════════
   SETTINGS — LLM CONFIG
════════════════════════════════════════════════════════════ */
async function loadLLMConfig() {
  try {
    S.llm = await api("/api/llm/config") || [];
    g("llmConfig").innerHTML = S.llm.length
      ? S.llm.map(c => `
          <div class="llm-item">
            <div class="llm-agent-name">${esc(c.agent)}</div>
            <div class="llm-details">
              <span class="badge badge-primary">${esc(c.provider)}</span>
              <span class="llm-model">${esc(c.model)}</span>
            </div>
          </div>`).join("")
      : emptyState("No config", "");
  } catch (err) { toast("Failed to load LLM config: " + err.message, "error"); }
}

/* ═══════════════════════════════════════════════════════════
   MODAL
════════════════════════════════════════════════════════════ */
let _modalCb = null;

function openModal(title, body, callback, opts = {}) {
  g("modalTitle").textContent = title;
  g("modalBody").innerHTML    = body;
  _modalCb = callback;
  const btn = g("modalConfirm");
  if (callback) {
    btn.classList.remove("hidden");
    btn.className   = opts.confirmClass || "btn btn-primary";
    btn.textContent = opts.confirmText  || "Confirm";
    btn.onclick = async () => {
      btn.disabled = true;
      try { await _modalCb(); } catch (err) { toast(err.message, "error"); }
      btn.disabled = false;
    };
  } else { btn.classList.add("hidden"); }
  g("modal").classList.remove("hidden");
}

function closeModal() { g("modal").classList.add("hidden"); }
function handleOverlayClick(e) { if (e.target.id === "modal") closeModal(); }

/* ═══════════════════════════════════════════════════════════
   TOAST
════════════════════════════════════════════════════════════ */
let _tt;
function toast(msg, type="info") {
  const el = g("toast"); clearTimeout(_tt);
  el.textContent = msg; el.className = `toast ${type}`;
  _tt = setTimeout(() => el.classList.add("hidden"), 3800);
}

/* ═══════════════════════════════════════════════════════════
   HELPERS
════════════════════════════════════════════════════════════ */
function g(id)     { return document.getElementById(id); }
function v(id)     { return (g(id)?.value ?? ""); }
function showEl(id){ g(id)?.classList.remove("hidden"); }
function hideEl(id){ g(id)?.classList.add("hidden"); }

function esc(str) {
  return String(str ?? "")
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function truncate(s, n) { const r = s??""; return r.length > n ? r.substring(0,n)+"…" : r; }
function fmtDate(iso)    { try { return new Date(iso).toLocaleString(); } catch { return iso||""; } }

function emptyState(title, sub) {
  return `<div class="empty-state"><div class="empty-icon">○</div><div class="empty-title">${title}</div><div class="empty-sub">${sub}</div></div>`;
}

function statusPill(s) {
  const m = { created:"badge-gray", orchestrated:"badge-info", learned:"badge-info",
    awaiting_approval:"badge-warning", rejected:"badge-danger", tasks_generated:"badge-success",
    approval_escalated:"badge-danger", queued:"badge-gray", in_progress:"badge-primary",
    blocked:"badge-danger", done:"badge-success" };
  return `<span class="badge ${m[s]||"badge-gray"}">${esc((s||"—").replace(/_/g," "))}</span>`;
}
function approvalPill(s) {
  if (!s) return "";
  const m = { pending:"badge-warning", approved:"badge-success", rejected:"badge-danger" };
  return `<span class="badge ${m[s]||"badge-gray"}">${esc(s)}</span>`;
}
function riskPill(l) {
  if (!l) return "—";
  const m = { low:"badge-success", medium:"badge-warning", high:"badge-danger", critical:"badge-danger" };
  return `<span class="badge ${m[l]||"badge-gray"}">${esc(l)}</span>`;
}

function renderMd(text) {
  if (!text) return "";
  return esc(text)
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm,  "<h2>$1</h2>")
    .replace(/^# (.+)$/gm,   "<h1>$1</h1>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g,     "<em>$1</em>")
    .replace(/^- (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>[\s\S]+?<\/li>)/g, "<ul>$1</ul>")
    .replace(/\n\n/g, "<br/><br/>");
}

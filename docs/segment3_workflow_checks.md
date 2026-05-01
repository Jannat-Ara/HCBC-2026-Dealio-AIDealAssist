# Segment 3 Workflow Checks

The backend is exposed locally at:

```text
http://localhost:8010
```

## 1. Login

```powershell
$login = @{ email='admin@example.com'; password='change-this-password' } | ConvertTo-Json
$token = (Invoke-RestMethod -Method Post -Uri http://localhost:8010/api/auth/login -ContentType 'application/json' -Body $login).access_token
$headers = @{ Authorization = "Bearer $token" }
```

## 2. Make Sure the KB Has Evidence

You can reuse Segment 2's KB checks. At minimum, create a domain and upload a finance policy document before submitting the workflow.

## 3. Submit an Objective

```powershell
$objective = @{
  objective_text = "Improve the invoice approval process using internal finance policy and audit evidence."
  department = "Finance"
  priority = "medium"
} | ConvertTo-Json

$workflow = Invoke-RestMethod -Method Post -Uri http://localhost:8010/api/objectives -Headers $headers -ContentType 'application/json' -Body $objective
$workflow
$workflowId = $workflow.workflow_id
```

Expected result:

```text
status: awaiting_approval
approval_status: pending
```

## 4. Inspect Workflow State

```powershell
Invoke-RestMethod -Uri "http://localhost:8010/api/workflows/$workflowId" -Headers $headers | ConvertTo-Json -Depth 10
```

You should see:

- `subtasks`
- `learner_output`
- `decision_report`
- empty `task_assignments`
- `status` set to `awaiting_approval`

## 5. Inspect Decision Report

```powershell
Invoke-RestMethod -Uri "http://localhost:8010/api/workflows/$workflowId/report" -Headers $headers | ConvertTo-Json -Depth 10
```

## 6. Confirm Audit Trail

```powershell
Invoke-RestMethod -Uri "http://localhost:8010/api/audit/$workflowId" -Headers $headers | ConvertTo-Json -Depth 10
```

You should see node events for:

- `objective.submitted`
- `orchestrator.started`
- `orchestrator.completed`
- `learner.started`
- `learner.completed`
- `decision_maker.started`
- `decision_maker.completed`
- `workflow.suspended_for_approval`

## 7. Approve and Resume

```powershell
$approval = @{ feedback = "Approved for Segment 3 verification." } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://localhost:8010/api/workflows/$workflowId/approve" -Headers $headers -ContentType 'application/json' -Body $approval | ConvertTo-Json -Depth 10
```

You should now see:

- `approval_status` set to `approved`
- `status` set to `tasks_generated`
- one or more `task_assignments`

## 8. Database Verification

```powershell
docker compose exec -T postgres psql -U app -d manage_ai -c "SELECT id, status, approval_status FROM workflow_states ORDER BY created_at DESC LIMIT 5;"
docker compose exec -T postgres psql -U app -d manage_ai -c "SELECT workflow_id, checkpoint_id, node_name FROM workflow_checkpoints ORDER BY id DESC LIMIT 10;"
docker compose exec -T postgres psql -U app -d manage_ai -c "SELECT actor, action FROM audit_log ORDER BY created_at DESC LIMIT 20;"
docker compose exec -T postgres psql -U app -d manage_ai -c "SELECT workflow_id, department, status, left(instructions, 100) FROM department_tasks ORDER BY created_at DESC LIMIT 5;"
```

## 9. Rejection Loop Check

Submit another objective, then reject it:

```powershell
$reject = @{ feedback = "Need clearer supporting evidence." } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://localhost:8010/api/workflows/$workflowId/reject" -Headers $headers -ContentType 'application/json' -Body $reject | ConvertTo-Json -Depth 10
```

Expected result:

- rejection is written to audit log
- workflow loops through Orchestrator/Learner/Decision Maker again
- final status returns to `awaiting_approval`

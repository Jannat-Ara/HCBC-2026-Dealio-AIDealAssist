# Segment 4 Product Checks

Local URLs:

```text
Backend:    http://localhost:8010
Frontend:   http://localhost:3010
Prometheus: http://localhost:9090
Grafana:    http://localhost:3001
```

Grafana login:

```text
admin / admin
```

## Login Token for API Checks

```powershell
$login = @{ email='admin@example.com'; password='change-this-password' } | ConvertTo-Json
$token = (Invoke-RestMethod -Method Post -Uri http://localhost:8010/api/auth/login -ContentType 'application/json' -Body $login).access_token
$headers = @{ Authorization = "Bearer $token" }
```

## Submit and Approve Workflow

```powershell
$objective = @{
  objective_text = "Improve invoice approval operations with finance policy and audit evidence."
  department = "Finance"
  priority = "medium"
} | ConvertTo-Json

$workflow = Invoke-RestMethod -Method Post -Uri http://localhost:8010/api/objectives -Headers $headers -ContentType 'application/json' -Body $objective
$workflowId = $workflow.workflow_id

$approval = @{ feedback = "Approved for Segment 4 verification." } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://localhost:8010/api/workflows/$workflowId/approve" -Headers $headers -ContentType 'application/json' -Body $approval
```

## Check Tasks

```powershell
$tasks = Invoke-RestMethod -Uri http://localhost:8010/api/tasks -Headers $headers
$tasks
$taskId = $tasks[0].id
Invoke-RestMethod -Method Patch -Uri "http://localhost:8010/api/tasks/$taskId/status" -Headers $headers -ContentType 'application/json' -Body (@{ status='in_progress' } | ConvertTo-Json)
```

## Check Notifications

```powershell
Invoke-RestMethod -Uri http://localhost:8010/api/operations/notifications -Headers $headers
```

## Run Expiry Check

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8010/api/operations/expiry/run -Headers $headers
```

## Check Metrics

```powershell
Invoke-WebRequest -Uri http://localhost:8010/metrics | Select-Object -ExpandProperty Content
```

Expected metric names include:

- `manage_ai_workflows_total`
- `manage_ai_tasks_total`
- `manage_ai_kb_entries_total`
- `manage_ai_approval_queue_depth`

## Database Checks

```powershell
docker compose exec -T postgres psql -U app -d manage_ai -c "SELECT workflow_id, department, status FROM department_tasks ORDER BY created_at DESC LIMIT 5;"
docker compose exec -T postgres psql -U app -d manage_ai -c "SELECT event_type, channel, status FROM notification_events ORDER BY created_at DESC LIMIT 10;"
```

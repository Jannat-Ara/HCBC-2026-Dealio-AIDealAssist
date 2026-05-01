# Segment 2 KB Checks

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

## 2. Create a Domain

```powershell
$domainBody = @{ name='Finance'; description='Finance policies and approval rules' } | ConvertTo-Json
$domain = Invoke-RestMethod -Method Post -Uri http://localhost:8010/api/kb/domains -Headers $headers -ContentType 'application/json' -Body $domainBody
$domain
```

## 3. Upload a Document

```powershell
Set-Content -Path .\sample_finance_policy.txt -Value "Finance policy requires manager approval for invoices above 5000 dollars. Vendor payments need audit documentation."

curl.exe -X POST "http://localhost:8010/api/kb/ingest" `
  -H "Authorization: Bearer $token" `
  -F "domain_id=$($domain.id)" `
  -F "file=@sample_finance_policy.txt"
```

## 4. Search the KB

```powershell
Invoke-RestMethod -Uri "http://localhost:8010/api/kb/search?q=invoice%20approval&domain=Finance" -Headers $headers
```

## 5. Confirm Failed Ingestion Error

```powershell
Set-Content -Path .\bad_upload.exe -Value "unsupported"

curl.exe -X POST "http://localhost:8010/api/kb/ingest" `
  -H "Authorization: Bearer $token" `
  -F "domain_id=$($domain.id)" `
  -F "file=@bad_upload.exe"
```

## 6. Database Verification

```powershell
docker compose exec -T postgres psql -U app -d manage_ai -c "SELECT name FROM kb_domains;"
docker compose exec -T postgres psql -U app -d manage_ai -c "SELECT source_file, chunk_index, left(content, 80) FROM kb_entries;"
docker compose exec -T postgres psql -U app -d manage_ai -c "SELECT filename, status, chunks_created, error_detail FROM kb_ingestion_log ORDER BY ingested_at DESC;"
```

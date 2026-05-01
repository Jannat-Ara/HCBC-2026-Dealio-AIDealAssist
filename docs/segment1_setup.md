# Segment 1 Setup

## Prerequisites

- Docker Desktop
- A `.env` file copied from `.env.example`
- Optional Groq API key for LLM smoke tests

## Start Foundation Services

```powershell
Copy-Item .env.example .env
docker compose up --build
```

## Bootstrap First Admin

```http
POST http://localhost:8010/api/auth/bootstrap-admin
Content-Type: application/json

{
  "email": "admin@example.com",
  "full_name": "Admin User",
  "password": "change-this-password",
  "role": "admin"
}
```

## Login

```http
POST http://localhost:8010/api/auth/login
Content-Type: application/json

{
  "email": "admin@example.com",
  "password": "change-this-password"
}
```

Use the returned bearer token for protected endpoints.

## Health Checks

```http
GET http://localhost:8010/api/health
GET http://localhost:8010/api/health/db
GET http://localhost:8010/api/health/redis
```

## LLM Checks

```http
GET  http://localhost:8010/api/llm/config
POST http://localhost:8010/api/llm/smoke-test
```

If `GROQ_API_KEY` is blank, the smoke test reports `missing_api_key` instead of failing the backend.

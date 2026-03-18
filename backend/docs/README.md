# Internal Knowledge Base + AI Gateway (MVP)

## 1) Quick start

```bash
cp .env.example .env
docker compose up -d --build
```

Endpoints:
- Gateway: `http://localhost:8080/healthz`
- Identity: `http://localhost:8081/healthz`
- Knowledge: `http://localhost:8082/healthz`
- AI: `http://localhost:8083/healthz`
- Ops: `http://localhost:8084/healthz`

## 2) Architecture

- `gateway-service`: API entry and request tracing.
- `identity-service`: auth callback and `/me`.
- `knowledge-service`: document CRUD and basic retrieval.
- `ai-service`: session + messages + LLM routing.
- `worker-service`: async ingestion queue consumer.
- `ops-service`: audit logs and quota query.

## 3) Seed identities

Default tenant/user inserted by migration:
- tenant: `11111111-1111-1111-1111-111111111111`
- user: `22222222-2222-2222-2222-222222222222`

Pass these headers when calling APIs:
- `X-Tenant-Id`
- `X-User-Id`
- `X-Role`

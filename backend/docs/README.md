# Internal Knowledge Base + AI Gateway (MVP)

## 1) Quick start

```bash
cp .env.example .env
docker-compose up -d --build
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
docker-compose up -d --build
```

Helpful task runners:
- GNU Make: `make up`, `make down`, `make logs`
- just: `just up`, `just down`, `just logs`
- Install dev deps: `just install-dev`
- Install git hooks: `just hooks-install`
- Run full checks: `just check`

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

## 4) CI and API collection

- GitHub Actions workflow: `.github/workflows/ci.yml`
- GitHub release workflow: `.github/workflows/release.yml`
- Postman collection: `backend/docs/postman/internal-kb-ai-gateway.postman_collection.json`

## 5) Learning and iteration docs

- Development playbook: `backend/docs/development-playbook.md`
- Development guide (detailed): `backend/docs/development-guide.md`
- Deployment guide (detailed): `backend/docs/deployment-guide.md`
- Reuse playbook (new machine checklist + pitfalls): `backend/docs/reuse-playbook.md`
- Commit message validator: `backend/scripts/validate_commit_msg.py`
- Pre-commit config: `.pre-commit-config.yaml`

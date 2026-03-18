from fastapi import Depends, FastAPI, Query

from libs.common_auth import Actor, get_actor
from libs.common_db import get_conn
from libs.common_observability import setup_logging

setup_logging("ops-service")

app = FastAPI(title="ops-service", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "ops-service"}


@app.get("/v1/admin/audit/logs")
def get_audit_logs(
    actor: Actor = Depends(get_actor),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    if actor.role != "admin":
        return {"items": []}

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tenant_id, user_id, endpoint, model, status_code, created_at
                FROM request_logs
                WHERE tenant_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (actor.tenant_id, limit),
            )
            rows = cur.fetchall()

    items = [
        {
            "id": str(r[0]),
            "tenant_id": str(r[1]) if r[1] else None,
            "user_id": str(r[2]) if r[2] else None,
            "endpoint": r[3],
            "model": r[4],
            "status_code": r[5],
            "created_at": r[6].isoformat() if r[6] else None,
        }
        for r in rows
    ]
    return {"items": items}


@app.get("/v1/admin/quotas/{tenant_id}")
def get_quota(tenant_id: str, actor: Actor = Depends(get_actor)) -> dict:
    if actor.role != "admin":
        return {"items": []}

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.metric, p.limit_value, p.window, u.used_value, u.window_start
                FROM quota_policies p
                LEFT JOIN quota_usages u
                    ON u.tenant_id = p.tenant_id
                   AND u.metric = p.metric
                WHERE p.tenant_id = %s
                ORDER BY p.metric
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()

    items = [
        {
            "metric": r[0],
            "limit": r[1],
            "window": r[2],
            "used": r[3] if r[3] is not None else 0,
            "window_start": r[4].isoformat() if r[4] else None,
        }
        for r in rows
    ]
    return {"tenant_id": tenant_id, "items": items}

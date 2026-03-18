from datetime import datetime, timezone

from fastapi import Depends, FastAPI
from pydantic import BaseModel

from libs.common_auth import Actor, get_actor
from libs.common_db import get_conn
from libs.common_observability import setup_logging

setup_logging("identity-service")

app = FastAPI(title="identity-service", version="0.1.0")


class SSOCallbackRequest(BaseModel):
    code: str


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "identity-service"}


@app.post("/v1/auth/sso/callback")
def sso_callback(payload: SSOCallbackRequest) -> dict[str, str]:
    # MVP: return static token format for local development.
    return {
        "access_token": f"dev-token-{payload.code}",
        "token_type": "bearer",
    }


@app.get("/v1/me")
def me(actor: Actor = Depends(get_actor)) -> dict[str, str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET last_login_at = %s WHERE id = %s",
                (datetime.now(timezone.utc), actor.user_id),
            )

    return {
        "tenant_id": actor.tenant_id,
        "user_id": actor.user_id,
        "role": actor.role,
    }

from fastapi import FastAPI

from libs.common_observability import setup_logging

setup_logging("gateway-service")

app = FastAPI(title="gateway-service", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "gateway-service"}


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "gateway online",
        "routes": "/healthz",
    }

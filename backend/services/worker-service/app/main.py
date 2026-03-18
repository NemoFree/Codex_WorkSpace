from fastapi import FastAPI

from libs.common_observability import setup_logging

setup_logging('worker-service')

app = FastAPI(title='worker-service', version='0.1.0')


@app.get('/healthz')
def healthz() -> dict[str, str]:
    return {'status': 'ok', 'service': 'worker-service'}

ARG DOCKER_REGISTRY=docker.io
FROM ${DOCKER_REGISTRY}/library/python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY libs /app/libs
COPY services/worker-service /app/service

ENV PYTHONPATH=/app

CMD ["python", "-m", "service.app.worker"]

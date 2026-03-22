import json
import logging
import os
import time
from datetime import datetime, timezone
from uuid import uuid4

from redis import Redis

from libs.common_db import get_conn
from libs.common_embedding import chunk_text, embed_text, to_vector_literal
from libs.common_observability import setup_logging
from libs.common_s3 import get_bytes_from_storage_uri

setup_logging("worker-service")
logger = logging.getLogger("worker-service")

QUEUE_MAIN = "ingest_jobs"  # list: legacy producer pushes JSON, retry flow pushes job_id
QUEUE_RETRY = "ingest_retry"  # zset: job_id -> unix seconds
QUEUE_DLQ = "ingest_dlq"  # list: json payload including last_error + attempt
PAYLOAD_STORE = "ingest_payload"  # hash: job_id -> json payload

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "text-embedding-3-small"
    if os.getenv("LITELLM_URL", "").strip()
    else "deterministic-hash-v1",
)

INGEST_MAX_ATTEMPTS = int(os.getenv("INGEST_MAX_ATTEMPTS", "5"))
INGEST_RETRY_BASE_SECONDS = int(os.getenv("INGEST_RETRY_BASE_SECONDS", "2"))
INGEST_RETRY_MAX_SECONDS = int(os.getenv("INGEST_RETRY_MAX_SECONDS", "60"))
INGEST_RETRY_BATCH = int(os.getenv("INGEST_RETRY_BATCH", "20"))
S3_MAX_BYTES = int(os.getenv("S3_MAX_BYTES", "5000000"))


def _set_document_status(tenant_id: str, document_id: str, status: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE documents
                SET status = %s
                WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL
                """,
                (status, document_id, tenant_id),
            )
            return cur.rowcount > 0


def _build_source_text(
    tenant_id: str, document_id: str, payload_content: str | None
) -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT title, storage_uri
                FROM documents
                WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL
                """,
                (document_id, tenant_id),
            )
            row = cur.fetchone()
    if not row:
        raise ValueError("document not found or deleted")

    parts: list[str] = []
    title, storage_uri = row

    content = (payload_content or "").strip()
    if not content and storage_uri and str(storage_uri).startswith("s3://"):
        # Best-effort: treat object as UTF-8 text for MVP. (PDF/Office parsing comes later.)
        data = get_bytes_from_storage_uri(str(storage_uri), max_bytes=S3_MAX_BYTES)
        content = data.decode("utf-8", errors="replace").lstrip("\ufeff").strip()

    if content:
        parts.append(content)

    if title:
        parts.append(f"title: {title}")
    if storage_uri:
        parts.append(f"storage_uri: {storage_uri}")

    return "\n".join(parts).strip() or f"document {document_id}"


def _compute_retry_delay_seconds(attempt: int) -> int:
    # attempt starts at 1. The 1st retry waits base seconds, then exponential backoff.
    attempt = max(1, int(attempt))
    delay = INGEST_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
    return int(min(INGEST_RETRY_MAX_SECONDS, delay))


def _cleanup_job_state(redis_client: Redis, job_id: str) -> None:
    try:
        redis_client.zrem(QUEUE_RETRY, job_id)
        redis_client.hdel(PAYLOAD_STORE, job_id)
    except Exception:
        logger.exception("cleanup job state failed job_id=%s", job_id)


def _move_due_retries(redis_client: Redis, *, now_ts: int | None = None) -> int:
    now_ts = int(now_ts if now_ts is not None else time.time())
    moved = 0

    try:
        job_ids = redis_client.zrangebyscore(
            QUEUE_RETRY, "-inf", now_ts, start=0, num=INGEST_RETRY_BATCH
        )
    except Exception:
        logger.exception("failed to scan retry schedule")
        return 0

    for job_id in job_ids or []:
        try:
            payload_json = redis_client.hget(PAYLOAD_STORE, job_id)
            redis_client.zrem(QUEUE_RETRY, job_id)
            if not payload_json:
                continue
            redis_client.rpush(QUEUE_MAIN, job_id)
            moved += 1
        except Exception:
            logger.exception("failed to requeue retry job_id=%s", job_id)

    return moved


def _load_payload_from_queue_item(
    redis_client: Redis, raw: str
) -> tuple[str, dict] | None:
    s = (raw or "").strip()
    if not s:
        return None

    # Compatible with the legacy producer which pushes JSON payloads to ingest_jobs.
    if s.startswith("{"):
        try:
            payload = json.loads(s)
        except json.JSONDecodeError:
            return None
        job_id = str(payload.get("job_id") or uuid4())
        attempt = int(payload.get("attempt") or 1)
        payload["job_id"] = job_id
        payload["attempt"] = attempt
        try:
            redis_client.hset(PAYLOAD_STORE, job_id, json.dumps(payload))
        except Exception:
            logger.exception("failed to store payload job_id=%s", job_id)
        return job_id, payload

    # Our retry flow requeues job_id only.
    job_id = s
    try:
        payload_json = redis_client.hget(PAYLOAD_STORE, job_id)
    except Exception:
        logger.exception("failed to load payload for job_id=%s", job_id)
        return None

    if not payload_json:
        return None

    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return None

    payload["job_id"] = job_id
    payload["attempt"] = int(payload.get("attempt") or 1)
    return job_id, payload


def _send_to_dlq(redis_client: Redis, payload: dict, *, last_error: str) -> None:
    item = dict(payload)
    item["last_error"] = last_error
    item["failed_at"] = datetime.now(timezone.utc).isoformat()
    redis_client.rpush(QUEUE_DLQ, json.dumps(item))


def _schedule_retry_or_dlq(
    redis_client: Redis, payload: dict, *, last_error: str, now_ts: int | None = None
) -> str:
    now_ts = int(now_ts if now_ts is not None else time.time())
    job_id = str(payload.get("job_id") or uuid4())
    attempt = int(payload.get("attempt") or 1)

    if attempt >= INGEST_MAX_ATTEMPTS:
        _send_to_dlq(redis_client, payload, last_error=last_error)
        _cleanup_job_state(redis_client, job_id)
        return "dlq"

    next_attempt = attempt + 1
    delay = _compute_retry_delay_seconds(attempt)
    run_at = now_ts + delay

    payload2 = dict(payload)
    payload2["job_id"] = job_id
    payload2["attempt"] = next_attempt
    payload2["last_error"] = last_error
    payload2["retry_at"] = run_at

    redis_client.hset(PAYLOAD_STORE, job_id, json.dumps(payload2))
    redis_client.zadd(QUEUE_RETRY, {job_id: run_at})
    return "retry"


def _ingest_document(
    tenant_id: str, document_id: str, payload_content: str | None
) -> int:
    max_words = int(os.getenv("INGEST_CHUNK_WORDS", "180"))
    overlap_words = int(os.getenv("INGEST_CHUNK_OVERLAP_WORDS", "30"))
    source_text = _build_source_text(tenant_id, document_id, payload_content)
    chunks = (
        chunk_text(source_text, max_words=max_words, overlap_words=overlap_words)
        or [source_text]
    )

    with get_conn() as conn:
        with conn.cursor() as cur:
            for idx, chunk_content in enumerate(chunks):
                now = datetime.now(timezone.utc)
                proposed_chunk_id = str(uuid4())
                cur.execute(
                    """
                    INSERT INTO document_chunks (id, tenant_id, document_id, chunk_no, content, token_count, metadata_jsonb, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (document_id, chunk_no) DO UPDATE SET
                      content = EXCLUDED.content,
                      token_count = EXCLUDED.token_count,
                      metadata_jsonb = EXCLUDED.metadata_jsonb,
                      created_at = EXCLUDED.created_at
                    RETURNING id
                    """,
                    (
                        proposed_chunk_id,
                        tenant_id,
                        document_id,
                        idx,
                        chunk_content,
                        len(chunk_content.split()),
                        json.dumps(
                            {
                                "strategy": "word-window",
                                "chunk_index": idx,
                                "chunk_total": len(chunks),
                            }
                        ),
                        now,
                    ),
                )
                row = cur.fetchone()
                chunk_id = str(row[0]) if row and row[0] else proposed_chunk_id
                cur.execute(
                    """
                    INSERT INTO chunk_vectors (chunk_id, tenant_id, embedding, model, created_at)
                    VALUES (%s, %s, %s::vector, %s, %s)
                    ON CONFLICT (chunk_id) DO UPDATE SET
                      embedding = EXCLUDED.embedding,
                      model = EXCLUDED.model,
                      created_at = EXCLUDED.created_at
                    """,
                    (
                        chunk_id,
                        tenant_id,
                        to_vector_literal(embed_text(chunk_content)),
                        EMBEDDING_MODEL,
                        now,
                    ),
                )

            # Remove stale chunks (and their vectors via cascade) when the new chunk count is smaller.
            cur.execute(
                """
                DELETE FROM document_chunks
                WHERE tenant_id = %s AND document_id = %s AND chunk_no >= %s
                """,
                (tenant_id, document_id, len(chunks)),
            )

    return len(chunks)


def run() -> None:
    redis_client = Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
    )

    while True:
        _move_due_retries(redis_client)

        item = redis_client.blpop([QUEUE_MAIN], timeout=5)
        if not item:
            continue

        _, raw = item
        loaded = _load_payload_from_queue_item(redis_client, raw)
        if not loaded:
            logger.warning("skip invalid ingest payload: %s", raw)
            continue

        job_id, payload = loaded
        tenant_id = payload.get("tenant_id")
        document_id = payload.get("document_id")
        payload_content = payload.get("content")
        if not tenant_id or not document_id:
            logger.warning("skip ingest job with missing identifiers: %s", payload)
            _cleanup_job_state(redis_client, job_id)
            continue

        if not _set_document_status(tenant_id, document_id, "processing"):
            logger.info(
                "skip ingest because document is missing or deleted tenant_id=%s document_id=%s job_id=%s",
                tenant_id,
                document_id,
                job_id,
            )
            _cleanup_job_state(redis_client, job_id)
            continue

        try:
            chunk_count = _ingest_document(tenant_id, document_id, payload_content)
            _set_document_status(tenant_id, document_id, "ready")
            logger.info(
                "ingest completed tenant_id=%s document_id=%s chunks=%s job_id=%s attempt=%s",
                tenant_id,
                document_id,
                chunk_count,
                job_id,
                payload.get("attempt"),
            )
            _cleanup_job_state(redis_client, job_id)
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            try:
                action = _schedule_retry_or_dlq(
                    redis_client,
                    payload,
                    last_error=last_error,
                )
            except Exception:
                action = "dlq"
                logger.exception(
                    "failed to schedule retry, sending to dlq job_id=%s", job_id
                )
                try:
                    _send_to_dlq(redis_client, payload, last_error=last_error)
                except Exception:
                    logger.exception("failed to push dlq job_id=%s", job_id)

            if action == "retry":
                _set_document_status(tenant_id, document_id, "queued")
            else:
                _set_document_status(tenant_id, document_id, "failed")

            logger.exception(
                "ingest failed tenant_id=%s document_id=%s job_id=%s attempt=%s action=%s",
                tenant_id,
                document_id,
                job_id,
                payload.get("attempt"),
                action,
            )
        time.sleep(0.2)


if __name__ == "__main__":
    run()

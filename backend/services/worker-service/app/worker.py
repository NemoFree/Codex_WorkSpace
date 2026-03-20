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

setup_logging("worker-service")
logger = logging.getLogger("worker-service")
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "text-embedding-3-small"
    if os.getenv("LITELLM_URL", "").strip()
    else "deterministic-hash-v1",
)


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
    if payload_content and payload_content.strip():
        parts.append(payload_content.strip())
    if row:
        title, storage_uri = row
        if title:
            parts.append(f"title: {title}")
        if storage_uri:
            parts.append(f"storage_uri: {storage_uri}")

    return "\n".join(parts).strip() or f"document {document_id}"


def _ingest_document(
    tenant_id: str, document_id: str, payload_content: str | None
) -> int:
    max_words = int(os.getenv("INGEST_CHUNK_WORDS", "180"))
    overlap_words = int(os.getenv("INGEST_CHUNK_OVERLAP_WORDS", "30"))
    source_text = _build_source_text(tenant_id, document_id, payload_content)
    chunks = chunk_text(
        source_text, max_words=max_words, overlap_words=overlap_words
    ) or [source_text]

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM document_chunks WHERE tenant_id = %s AND document_id = %s",
                (tenant_id, document_id),
            )
            for idx, chunk_content in enumerate(chunks):
                chunk_id = str(uuid4())
                now = datetime.now(timezone.utc)
                cur.execute(
                    """
                    INSERT INTO document_chunks (id, tenant_id, document_id, chunk_no, content, token_count, metadata_jsonb, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    """,
                    (
                        chunk_id,
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
                cur.execute(
                    """
                    INSERT INTO chunk_vectors (chunk_id, tenant_id, embedding, model, created_at)
                    VALUES (%s, %s, %s::vector, %s, %s)
                    """,
                    (
                        chunk_id,
                        tenant_id,
                        to_vector_literal(embed_text(chunk_content)),
                        EMBEDDING_MODEL,
                        now,
                    ),
                )
    return len(chunks)


def run() -> None:
    redis_client = Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
    )

    while True:
        item = redis_client.blpop(["ingest_jobs"], timeout=5)
        if not item:
            continue

        _, raw = item
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("skip invalid ingest payload: %s", raw)
            continue

        tenant_id = payload.get("tenant_id")
        document_id = payload.get("document_id")
        payload_content = payload.get("content")
        if not tenant_id or not document_id:
            logger.warning("skip ingest job with missing identifiers: %s", payload)
            continue

        if not _set_document_status(tenant_id, document_id, "processing"):
            logger.info(
                "skip ingest because document is missing or deleted tenant_id=%s document_id=%s",
                tenant_id,
                document_id,
            )
            continue
        try:
            chunk_count = _ingest_document(tenant_id, document_id, payload_content)
            _set_document_status(tenant_id, document_id, "ready")
            logger.info(
                "ingest completed tenant_id=%s document_id=%s chunks=%s",
                tenant_id,
                document_id,
                chunk_count,
            )
        except Exception:
            _set_document_status(tenant_id, document_id, "failed")
            logger.exception(
                "ingest failed tenant_id=%s document_id=%s",
                tenant_id,
                document_id,
            )
        time.sleep(0.2)


if __name__ == "__main__":
    run()

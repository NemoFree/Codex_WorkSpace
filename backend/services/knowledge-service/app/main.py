import json
import os
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from redis import Redis

from libs.common_auth import Actor, get_actor
from libs.common_db import get_conn
from libs.common_observability import setup_logging

setup_logging('knowledge-service')

app = FastAPI(title='knowledge-service', version='0.1.0')
redis_client = Redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'), decode_responses=True)


class DocumentCreate(BaseModel):
    title: str
    source_type: str = Field(default='upload')
    storage_uri: str | None = None


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)


@app.get('/healthz')
def healthz() -> dict[str, str]:
    return {'status': 'ok', 'service': 'knowledge-service'}


@app.post('/v1/documents')
def create_document(payload: DocumentCreate, actor: Actor = Depends(get_actor)) -> dict[str, str]:
    doc_id = str(uuid4())

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                INSERT INTO documents (id, tenant_id, title, source_type, storage_uri, status, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ''',
                (
                    doc_id,
                    actor.tenant_id,
                    payload.title,
                    payload.source_type,
                    payload.storage_uri,
                    'queued',
                    actor.user_id,
                    datetime.now(timezone.utc),
                ),
            )

    redis_client.rpush('ingest_jobs', json.dumps({'tenant_id': actor.tenant_id, 'document_id': doc_id}))
    return {'document_id': doc_id, 'status': 'queued'}


@app.get('/v1/documents')
def list_documents(
    actor: Actor = Depends(get_actor),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT id, title, source_type, status, created_at
                FROM documents
                WHERE tenant_id = %s AND deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                ''',
                (actor.tenant_id, limit, offset),
            )
            rows = cur.fetchall()

    items = [
        {
            'id': str(r[0]),
            'title': r[1],
            'source_type': r[2],
            'status': r[3],
            'created_at': r[4].isoformat() if r[4] else None,
        }
        for r in rows
    ]
    return {'items': items}


@app.get('/v1/documents/{document_id}')
def get_document(document_id: str, actor: Actor = Depends(get_actor)) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT id, title, source_type, storage_uri, status, created_at
                FROM documents
                WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL
                ''',
                (document_id, actor.tenant_id),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail='document not found')

    return {
        'id': str(row[0]),
        'title': row[1],
        'source_type': row[2],
        'storage_uri': row[3],
        'status': row[4],
        'created_at': row[5].isoformat() if row[5] else None,
    }


@app.delete('/v1/documents/{document_id}')
def delete_document(document_id: str, actor: Actor = Depends(get_actor)) -> dict[str, bool]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                UPDATE documents
                SET deleted_at = %s, status = 'deleted'
                WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL
                ''',
                (datetime.now(timezone.utc), document_id, actor.tenant_id),
            )
            deleted = cur.rowcount > 0

    if not deleted:
        raise HTTPException(status_code=404, detail='document not found')

    return {'deleted': True}


@app.post('/v1/rag/search')
def rag_search(payload: SearchRequest, actor: Actor = Depends(get_actor)) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT id, content, metadata_jsonb
                FROM document_chunks
                WHERE tenant_id = %s AND content ILIKE %s
                LIMIT %s
                ''',
                (actor.tenant_id, f'%{payload.query}%', payload.top_k),
            )
            rows = cur.fetchall()

    hits = [
        {
            'chunk_id': str(r[0]),
            'content': r[1],
            'metadata': r[2],
        }
        for r in rows
    ]
    return {'query': payload.query, 'hits': hits}

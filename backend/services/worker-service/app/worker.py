import json
import os
import time
from datetime import datetime, timezone
from uuid import uuid4

from redis import Redis

from libs.common_db import get_conn
from libs.common_observability import setup_logging

setup_logging('worker-service')


def run() -> None:
    redis_client = Redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'), decode_responses=True)

    while True:
        item = redis_client.blpop(['ingest_jobs'], timeout=5)
        if not item:
            continue

        _, raw = item
        payload = json.loads(raw)
        tenant_id = payload['tenant_id']
        document_id = payload['document_id']

        # MVP: insert one synthetic chunk and a zero vector placeholder.
        with get_conn() as conn:
            with conn.cursor() as cur:
                chunk_id = str(uuid4())
                cur.execute(
                    '''
                    INSERT INTO document_chunks (id, tenant_id, document_id, chunk_no, content, token_count, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    ''',
                    (
                        chunk_id,
                        tenant_id,
                        document_id,
                        0,
                        f'Indexed content for document {document_id}',
                        16,
                        datetime.now(timezone.utc),
                    ),
                )
                cur.execute(
                    '''
                    INSERT INTO chunk_vectors (chunk_id, tenant_id, embedding, model, created_at)
                    VALUES (%s, %s, %s::vector, %s, %s)
                    ON CONFLICT DO NOTHING
                    ''',
                    (
                        chunk_id,
                        tenant_id,
                        '[' + ','.join(['0'] * 1536) + ']',
                        'text-embedding-3-small',
                        datetime.now(timezone.utc),
                    ),
                )
                cur.execute(
                    'UPDATE documents SET status = %s WHERE id = %s AND tenant_id = %s',
                    ('ready', document_id, tenant_id),
                )
        time.sleep(0.2)


if __name__ == '__main__':
    run()

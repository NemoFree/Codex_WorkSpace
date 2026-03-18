from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from libs.common_auth import Actor, get_actor
from libs.common_db import get_conn
from libs.common_llm import chat_completion
from libs.common_observability import setup_logging

setup_logging('ai-service')

app = FastAPI(title='ai-service', version='0.1.0')


class SessionCreate(BaseModel):
    title: str | None = None


class MessageCreate(BaseModel):
    content: str
    model: str = Field(default='gpt-4o-mini')


@app.get('/healthz')
def healthz() -> dict[str, str]:
    return {'status': 'ok', 'service': 'ai-service'}


@app.post('/v1/chat/sessions')
def create_session(payload: SessionCreate, actor: Actor = Depends(get_actor)) -> dict:
    session_id = str(uuid4())
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                INSERT INTO chat_sessions (id, tenant_id, user_id, title, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ''',
                (session_id, actor.tenant_id, actor.user_id, payload.title, datetime.now(timezone.utc)),
            )
    return {'session_id': session_id, 'title': payload.title}


@app.post('/v1/chat/sessions/{session_id}/messages')
def chat(session_id: str, payload: MessageCreate, actor: Actor = Depends(get_actor)) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT id FROM chat_sessions WHERE id = %s AND tenant_id = %s',
                (session_id, actor.tenant_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail='session not found')

            user_msg_id = str(uuid4())
            cur.execute(
                '''
                INSERT INTO chat_messages (id, session_id, role, content, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ''',
                (user_msg_id, session_id, 'user', payload.content, datetime.now(timezone.utc)),
            )

    completion = chat_completion(payload.model, [{'role': 'user', 'content': payload.content}])
    assistant_content = completion['content']

    with get_conn() as conn:
        with conn.cursor() as cur:
            assistant_msg_id = str(uuid4())
            cur.execute(
                '''
                INSERT INTO chat_messages (id, session_id, role, content, token_in, token_out, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ''',
                (
                    assistant_msg_id,
                    session_id,
                    'assistant',
                    assistant_content,
                    completion.get('usage', {}).get('prompt_tokens', 0),
                    completion.get('usage', {}).get('completion_tokens', 0),
                    datetime.now(timezone.utc),
                ),
            )
            cur.execute(
                '''
                INSERT INTO request_logs (id, tenant_id, user_id, session_id, endpoint, model, status_code, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ''',
                (
                    str(uuid4()),
                    actor.tenant_id,
                    actor.user_id,
                    session_id,
                    '/v1/chat/sessions/{id}/messages',
                    payload.model,
                    200,
                    datetime.now(timezone.utc),
                ),
            )

    return {
        'session_id': session_id,
        'message': {'role': 'assistant', 'content': assistant_content},
        'model': completion['model'],
    }


@app.get('/v1/chat/sessions/{session_id}/messages')
def list_messages(session_id: str, actor: Actor = Depends(get_actor)) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT m.id, m.role, m.content, m.created_at
                FROM chat_messages m
                JOIN chat_sessions s ON s.id = m.session_id
                WHERE m.session_id = %s AND s.tenant_id = %s
                ORDER BY m.created_at ASC
                ''',
                (session_id, actor.tenant_id),
            )
            rows = cur.fetchall()

    items = [
        {
            'id': str(r[0]),
            'role': r[1],
            'content': r[2],
            'created_at': r[3].isoformat() if r[3] else None,
        }
        for r in rows
    ]
    return {'items': items}

import os
from typing import Any

import httpx


LITELLM_URL = os.getenv('LITELLM_URL', '').strip()
LITELLM_API_KEY = os.getenv('LITELLM_API_KEY', '').strip()


def chat_completion(model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    if not LITELLM_URL:
        content = messages[-1]['content'] if messages else ''
        return {
            'model': model,
            'content': f'[mock] {content}',
            'usage': {'prompt_tokens': 0, 'completion_tokens': 0},
        }

    headers = {'Content-Type': 'application/json'}
    if LITELLM_API_KEY:
        headers['Authorization'] = f'Bearer {LITELLM_API_KEY}'

    payload = {
        'model': model,
        'messages': messages,
        'stream': False,
    }

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(f'{LITELLM_URL}/chat/completions', headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    return {
        'model': data.get('model', model),
        'content': data['choices'][0]['message']['content'],
        'usage': data.get('usage', {}),
    }

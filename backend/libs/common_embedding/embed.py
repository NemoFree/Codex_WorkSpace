import math
import os
import re
from hashlib import blake2b
from typing import Iterable

import httpx


DEFAULT_EMBEDDING_DIM = 1536
_TOKEN_RE = re.compile(r"\w+")


def chunk_text(
    text: str, *, max_words: int = 180, overlap_words: int = 30
) -> list[str]:
    cleaned = " ".join(text.split())
    if not cleaned:
        return []

    tokens = cleaned.split(" ")
    if len(tokens) <= max_words:
        return [cleaned]

    if overlap_words >= max_words:
        overlap_words = max_words // 2

    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + max_words, len(tokens))
        chunks.append(" ".join(tokens[start:end]))
        if end >= len(tokens):
            break
        start = end - overlap_words
    return chunks


def _embed_text_deterministic(
    text: str, *, dim: int = DEFAULT_EMBEDDING_DIM
) -> list[float]:
    vector = [0.0] * dim
    tokens = _TOKEN_RE.findall(text.lower())

    if not tokens:
        vector[0] = 1.0
        return vector

    for token in tokens:
        digest = blake2b(token.encode("utf-8"), digest_size=16).digest()
        weight = 1.0 + min(len(token), 16) / 16.0

        idx1 = int.from_bytes(digest[0:4], "big") % dim
        sign1 = 1.0 if (digest[4] & 1) else -1.0
        vector[idx1] += sign1 * weight

        idx2 = int.from_bytes(digest[8:12], "big") % dim
        sign2 = 1.0 if (digest[12] & 1) else -1.0
        vector[idx2] += sign2 * (weight * 0.75)

    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        vector[0] = 1.0
        return vector
    return [v / norm for v in vector]


def _is_enabled(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def embed_text(text: str, *, dim: int = DEFAULT_EMBEDDING_DIM) -> list[float]:
    litellm_url = os.getenv("LITELLM_URL", "").strip()
    if not litellm_url:
        return _embed_text_deterministic(text, dim=dim)

    model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    fallback_on_error = _is_enabled(os.getenv("EMBEDDING_FALLBACK_ON_ERROR"), True)
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("LITELLM_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{litellm_url}/embeddings",
                headers=headers,
                json={"model": model, "input": text},
            )
            resp.raise_for_status()
            data = resp.json()
        embedding = data["data"][0]["embedding"]
        vector = [float(v) for v in embedding]
        if len(vector) != dim:
            raise ValueError(
                f"embedding dimension mismatch: expected {dim}, got {len(vector)}"
            )
        return vector
    except Exception:
        if fallback_on_error:
            return _embed_text_deterministic(text, dim=dim)
        raise


def to_vector_literal(values: Iterable[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"

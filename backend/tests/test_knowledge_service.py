from contextlib import contextmanager
from datetime import datetime, timezone
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))


def _load_module(name: str, relative_path: str):
    module_path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, module_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"failed to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


knowledge = _load_module(
    "knowledge_service_main", "backend/services/knowledge-service/app/main.py"
)


class FakeCursor:
    def __init__(self, *, fetchone_result=None, fetchall_results: list | None = None):
        self.fetchone_result = fetchone_result
        self.fetchall_results = list(fetchall_results or [])
        self.executions: list[tuple[str, object]] = []
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params=None) -> None:
        self.executions.append((sql, params))

    def fetchone(self):
        return self.fetchone_result

    def fetchall(self):
        if self.fetchall_results:
            return self.fetchall_results.pop(0)
        return []


class FakeConn:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def cursor(self) -> FakeCursor:
        return self._cursor


@contextmanager
def fake_get_conn(cursor: FakeCursor):
    yield FakeConn(cursor)


class KnowledgeServiceTests(unittest.TestCase):
    def test_create_document_pushes_content_to_ingest_queue(self) -> None:
        cursor = FakeCursor()
        redis_mock = MagicMock()
        actor = knowledge.Actor(tenant_id="t1", user_id="u1", role="admin")
        payload = knowledge.DocumentCreate(title="Doc A", content="hello world")

        with (
            patch.object(knowledge, "get_conn", lambda: fake_get_conn(cursor)),
            patch.object(knowledge, "redis_client", redis_mock),
        ):
            result = knowledge.create_document(payload, actor)

        self.assertEqual(result["status"], "queued")
        self.assertEqual(redis_mock.rpush.call_count, 1)
        queue_name, raw_payload = redis_mock.rpush.call_args[0]
        self.assertEqual(queue_name, "ingest_jobs")
        data = json.loads(raw_payload)
        self.assertEqual(data["tenant_id"], "t1")
        self.assertEqual(data["content"], "hello world")

    def test_rag_search_falls_back_to_ilike_when_vector_returns_empty(self) -> None:
        cursor = FakeCursor(fetchall_results=[[], [("chunk-1", "hello", {}, None)]])
        actor = knowledge.Actor(tenant_id="t1", user_id="u1", role="admin")
        payload = knowledge.SearchRequest(query="hello", top_k=5)

        with patch.object(knowledge, "get_conn", lambda: fake_get_conn(cursor)):
            result = knowledge.rag_search(payload, actor)

        self.assertEqual(len(result["hits"]), 1)
        self.assertIsNone(result["hits"][0]["score"])
        self.assertEqual(len(cursor.executions), 2)

    def test_rag_search_uses_vector_score_when_available(self) -> None:
        cursor = FakeCursor(fetchall_results=[[("chunk-1", "hello", {}, 0.87)]])
        actor = knowledge.Actor(tenant_id="t1", user_id="u1", role="admin")
        payload = knowledge.SearchRequest(query="hello", top_k=5)

        with patch.object(knowledge, "get_conn", lambda: fake_get_conn(cursor)):
            result = knowledge.rag_search(payload, actor)

        self.assertEqual(len(result["hits"]), 1)
        self.assertAlmostEqual(result["hits"][0]["score"], 0.87, places=6)
        self.assertEqual(len(cursor.executions), 1)

    def test_ingest_summary_forbidden_for_non_admin(self) -> None:
        actor = knowledge.Actor(tenant_id="t1", user_id="u1", role="user")
        with self.assertRaises(knowledge.HTTPException) as ctx:
            knowledge.ingest_summary(actor)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_ingest_summary_admin_returns_queue_and_recent_docs(self) -> None:
        cursor = FakeCursor(
            fetchall_results=[
                [("queued", 2), ("ready", 5)],
                [
                    (
                        "doc-1",
                        "Doc 1",
                        "ready",
                        datetime(2026, 3, 22, 12, 0, 0, tzinfo=timezone.utc),
                        3,
                    )
                ],
            ]
        )
        redis_mock = MagicMock()
        redis_mock.llen.return_value = 7
        actor = knowledge.Actor(tenant_id="t1", user_id="u1", role="admin")

        with (
            patch.object(knowledge, "get_conn", lambda: fake_get_conn(cursor)),
            patch.object(knowledge, "redis_client", redis_mock),
        ):
            result = knowledge.ingest_summary(actor)

        self.assertEqual(result["tenant_id"], "t1")
        self.assertEqual(result["queue_len"], 7)
        self.assertEqual(result["status_counts"]["queued"], 2)
        self.assertEqual(result["status_counts"]["ready"], 5)
        self.assertEqual(len(result["recent_documents"]), 1)
        self.assertEqual(result["recent_documents"][0]["id"], "doc-1")
        self.assertEqual(result["recent_documents"][0]["chunk_count"], 3)


if __name__ == "__main__":
    unittest.main()

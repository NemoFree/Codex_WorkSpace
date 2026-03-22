from contextlib import contextmanager
import importlib.util
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


worker = _load_module(
    "worker_service_worker", "backend/services/worker-service/app/worker.py"
)


class FakeCursor:
    def __init__(
        self,
        *,
        rowcount: int = 1,
        fetchone_result=None,
        fetchall_results: list | None = None,
    ) -> None:
        self.rowcount = rowcount
        self.fetchone_result = fetchone_result
        self.fetchall_results = list(fetchall_results or [])
        self.executions: list[tuple[str, object]] = []
        self._last_sql: str | None = None
        self._last_params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params=None) -> None:
        self.executions.append((sql, params))
        self._last_sql = sql
        self._last_params = params

    def fetchone(self):
        if self.fetchone_result is not None:
            return self.fetchone_result
        # For INSERT ... RETURNING id, return the proposed id for predictable tests.
        if self._last_sql and "RETURNING id" in self._last_sql and self._last_params:
            return (self._last_params[0],)
        return None

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


class WorkerServiceTests(unittest.TestCase):
    def test_set_document_status_returns_true_when_updated(self) -> None:
        cursor = FakeCursor(rowcount=1)
        with patch.object(worker, "get_conn", lambda: fake_get_conn(cursor)):
            ok = worker._set_document_status("t1", "d1", "processing")
        self.assertTrue(ok)

    def test_build_source_text_raises_when_missing_or_deleted(self) -> None:
        cursor = FakeCursor(fetchone_result=None)
        with patch.object(worker, "get_conn", lambda: fake_get_conn(cursor)):
            with self.assertRaises(ValueError):
                worker._build_source_text("t1", "d1", None)

    def test_build_source_text_fetches_s3_when_payload_missing(self) -> None:
        cursor = FakeCursor(fetchone_result=("Title", "s3://kb/t1/x.txt"))
        with (
            patch.object(worker, "get_conn", lambda: fake_get_conn(cursor)),
            patch.object(worker, "get_bytes_from_storage_uri", lambda *_args, **_kw: b"hello s3"),
        ):
            txt = worker._build_source_text("t1", "d1", None)
        self.assertIn("hello s3", txt)
        self.assertIn("storage_uri: s3://kb/t1/x.txt", txt)

    def test_ingest_document_inserts_chunks_and_vectors(self) -> None:
        cursor = FakeCursor()
        long_text = " ".join(f"w{i}" for i in range(420))

        with (
            patch.object(worker, "get_conn", lambda: fake_get_conn(cursor)),
            patch.object(worker, "_build_source_text", lambda *_: long_text),
        ):
            chunk_count = worker._ingest_document("t1", "d1", None)

        self.assertGreater(chunk_count, 1)
        sql_calls = [sql for sql, _ in cursor.executions]
        chunk_upserts = [s for s in sql_calls if "INSERT INTO document_chunks" in s]
        vector_upserts = [s for s in sql_calls if "INSERT INTO chunk_vectors" in s]
        self.assertEqual(len(chunk_upserts), chunk_count)
        self.assertEqual(len(vector_upserts), chunk_count)
        self.assertTrue(any("ON CONFLICT (document_id, chunk_no)" in s for s in chunk_upserts))
        self.assertTrue(any("ON CONFLICT (chunk_id)" in s for s in vector_upserts))
        self.assertEqual(len([s for s in sql_calls if "DELETE FROM document_chunks" in s]), 1)

    def test_compute_retry_delay_seconds_uses_exponential_backoff(self) -> None:
        with (
            patch.object(worker, "INGEST_RETRY_BASE_SECONDS", 2),
            patch.object(worker, "INGEST_RETRY_MAX_SECONDS", 60),
        ):
            self.assertEqual(worker._compute_retry_delay_seconds(1), 2)
            self.assertEqual(worker._compute_retry_delay_seconds(2), 4)
            self.assertEqual(worker._compute_retry_delay_seconds(3), 8)

    def test_schedule_retry_or_dlq_schedules_retry_until_max_attempts(self) -> None:
        redis_mock = MagicMock()
        with (
            patch.object(worker, "INGEST_MAX_ATTEMPTS", 3),
            patch.object(worker, "INGEST_RETRY_BASE_SECONDS", 2),
            patch.object(worker, "INGEST_RETRY_MAX_SECONDS", 60),
        ):
            payload = {"job_id": "job-1", "attempt": 1, "tenant_id": "t1", "document_id": "d1"}
            action = worker._schedule_retry_or_dlq(redis_mock, payload, last_error="boom", now_ts=1000)
            self.assertEqual(action, "retry")
            redis_mock.hset.assert_called()
            redis_mock.zadd.assert_called_with(worker.QUEUE_RETRY, {"job-1": 1002})

            redis_mock.reset_mock()
            payload2 = {"job_id": "job-1", "attempt": 3, "tenant_id": "t1", "document_id": "d1"}
            action2 = worker._schedule_retry_or_dlq(redis_mock, payload2, last_error="boom", now_ts=1000)
            self.assertEqual(action2, "dlq")
            redis_mock.rpush.assert_called()

    def test_move_due_retries_requeues_only_existing_payloads(self) -> None:
        redis_mock = MagicMock()
        redis_mock.zrangebyscore.return_value = ["job-1", "job-2"]
        redis_mock.hget.side_effect = ["{\\\"job_id\\\":\\\"job-1\\\"}", None]

        moved = worker._move_due_retries(redis_mock, now_ts=2000)
        self.assertEqual(moved, 1)
        self.assertEqual(redis_mock.rpush.call_count, 1)
        redis_mock.rpush.assert_called_with(worker.QUEUE_MAIN, "job-1")


if __name__ == "__main__":
    unittest.main()

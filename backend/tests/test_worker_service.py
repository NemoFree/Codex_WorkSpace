from contextlib import contextmanager
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch
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
        self.assertEqual(
            len([s for s in sql_calls if "INSERT INTO document_chunks" in s]),
            chunk_count,
        )
        self.assertEqual(
            len([s for s in sql_calls if "INSERT INTO chunk_vectors" in s]),
            chunk_count,
        )


if __name__ == "__main__":
    unittest.main()

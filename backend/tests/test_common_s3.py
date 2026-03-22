from pathlib import Path
import sys
from datetime import datetime, timezone
from unittest.mock import patch
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from libs.common_s3.s3 import S3Config, get_bytes_from_storage_uri, parse_storage_uri, put_bytes, sigv4_headers


class _FakeResponse:
    def __init__(self, status_code: int, *, headers=None, content: bytes = b"") -> None:
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.content = content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http error {self.status_code}")


class _FakeClient:
    def __init__(self, *args, **kwargs) -> None:
        self.calls = []
        self.objects: dict[str, bytes] = {}

    def request(self, method: str, url: str, headers=None, content=None):
        self.calls.append((method.upper(), url, dict(headers or {}), content))
        if method.upper() == "HEAD":
            return _FakeResponse(404, content=b"")
        if method.upper() == "PUT" and url.endswith("/kb0"):
            return _FakeResponse(200, content=b"")
        if method.upper() == "PUT":
            self.objects[url] = content or b""
            return _FakeResponse(200, headers={"etag": '"abc123"'}, content=b"")
        if method.upper() == "GET":
            return _FakeResponse(200, content=self.objects.get(url, b""))
        return _FakeResponse(200, content=b"")

    def close(self) -> None:
        return None


class CommonS3Tests(unittest.TestCase):
    def test_parse_storage_uri(self) -> None:
        bucket, key = parse_storage_uri("s3://kb0/a/b.txt")
        self.assertEqual(bucket, "kb0")
        self.assertEqual(key, "a/b.txt")

        with self.assertRaises(ValueError):
            parse_storage_uri("http://kb/a")

        with self.assertRaises(ValueError):
            parse_storage_uri("s3://kb")

    def test_sigv4_headers_contains_authorization(self) -> None:
        h = sigv4_headers(
            method="GET",
            url="http://minio:9000/kb0/x.txt",
            access_key="minio",
            secret_key="minio123",
            region="us-east-1",
            service="s3",
            headers={},
            body=b"",
            now=datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc),
        )
        self.assertIn("authorization", h)
        self.assertIn("AWS4-HMAC-SHA256", h["authorization"])
        self.assertIn("Credential=minio/", h["authorization"])
        self.assertIn("x-amz-date", h)
        self.assertIn("x-amz-content-sha256", h)
        self.assertEqual(h["x-amz-date"], "20260322T000000Z")

    def test_put_and_get_bytes_use_httpx_and_signed_headers(self) -> None:
        cfg = S3Config(
            endpoint="http://minio:9000",
            access_key="minio",
            secret_key="minio123",
            bucket="kb",  # will be sanitized to kb0
            region="us-east-1",
        )
        with patch("libs.common_s3.s3.httpx.Client", _FakeClient):
            c = _FakeClient()
            meta = put_bytes(cfg, key="t1/x.txt", data=b"hello", content_type="text/plain", client=c)
            self.assertEqual(meta["bucket"], "kb0")
            self.assertEqual(meta["key"], "t1/x.txt")
            self.assertEqual(meta["size"], 5)
            self.assertTrue(meta["etag"])

            data = get_bytes_from_storage_uri("s3://kb/t1/x.txt", cfg=cfg, client=c)
            self.assertEqual(data, b"hello")


if __name__ == "__main__":
    unittest.main()

from pathlib import Path 
import sys 
from datetime import datetime, timezone 
from unittest.mock import patch, MagicMock 
import unittest 
import io 


ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from libs.common_s3.s3 import (
    S3Config,
    get_bytes_from_storage_uri,
    parse_storage_uri,
    put_bytes,
    sigv4_headers,
)


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self._bucket_exists = False

    def head_bucket(self, *, Bucket: str):
        if not self._bucket_exists:
            from botocore.exceptions import ClientError

            raise ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}},
                "HeadBucket",
            )
        return {}

    def create_bucket(self, *, Bucket: str):
        self._bucket_exists = True
        return {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str):
        self.objects[(Bucket, Key)] = Body
        return {"ETag": '"abc123"'}

    def get_object(self, *, Bucket: str, Key: str):
        data = self.objects.get((Bucket, Key), b"")
        return {"Body": io.BytesIO(data)}


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

    def test_put_and_get_bytes_use_s3_client(self) -> None: 
        cfg = S3Config( 
            endpoint="http://minio:9000", 
            access_key="minio", 
            secret_key="minio123", 
            bucket="kb",  # will be sanitized to kb0 
            region="us-east-1", 
        ) 
        c = _FakeS3Client()
        meta = put_bytes(cfg, key="t1/x.txt", data=b"hello", content_type="text/plain", client=c)
        self.assertEqual(meta["bucket"], "kb0") 
        self.assertEqual(meta["key"], "t1/x.txt") 
        self.assertEqual(meta["size"], 5) 
        self.assertTrue(meta["etag"]) 

        data = get_bytes_from_storage_uri("s3://kb/t1/x.txt", cfg=cfg, client=c) 
        self.assertEqual(data, b"hello") 

    def test_ensure_bucket_exists_raises_on_forbidden(self) -> None:
        cfg = S3Config(
            endpoint="http://minio:9000",
            access_key="bad",
            secret_key="bad",
            bucket="kbdocs",
            region="us-east-1",
        )
        from botocore.exceptions import ClientError

        forbidden = ClientError({"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadBucket")
        s3 = MagicMock()
        s3.head_bucket.side_effect = forbidden
        with self.assertRaises(ClientError):
            from libs.common_s3.s3 import ensure_bucket_exists

            ensure_bucket_exists(cfg, client=s3, bucket="kbdocs")


if __name__ == "__main__":
    unittest.main()

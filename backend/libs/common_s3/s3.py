import hashlib
import hmac
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import httpx


@dataclass(frozen=True)
class S3Config:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    region: str = "us-east-1"
    service: str = "s3"


def _env(name: str, default: str) -> str:
    v = os.getenv(name)
    if v is None:
        return default
    v = v.strip()
    return v if v else default


def _sanitize_bucket_name(bucket: str) -> str:
    # S3 bucket naming: 3-63 chars, lowercase letters/numbers/hyphen/dot.
    b = (bucket or "").strip().lower()
    b = re.sub(r"[^a-z0-9.-]", "-", b)
    b = b.strip(".-")
    if len(b) < 3:
        b = (b + "000")[:3]
    if len(b) > 63:
        b = b[:63]
    if not b:
        b = "kb0"
    return b


def load_s3_config() -> S3Config:
    endpoint = _env("S3_ENDPOINT", "http://minio:9000")
    access_key = os.getenv("S3_ACCESS_KEY", "").strip() or os.getenv(
        "MINIO_ROOT_USER", "minio"
    ).strip()
    secret_key = os.getenv("S3_SECRET_KEY", "").strip() or os.getenv(
        "MINIO_ROOT_PASSWORD", "minio123"
    ).strip()
    # Requirement says default bucket is `kb`; normalize to a legal bucket name for S3 engines.
    bucket = _sanitize_bucket_name(_env("S3_BUCKET", "kb"))
    region = _env("S3_REGION", "us-east-1")
    return S3Config(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        bucket=bucket,
        region=region,
    )


def parse_storage_uri(storage_uri: str) -> tuple[str, str]:
    if not storage_uri or not storage_uri.startswith("s3://"):
        raise ValueError("invalid storage_uri: expected s3://<bucket>/<key>")
    rest = storage_uri[len("s3://") :]
    bucket, _, key = rest.partition("/")
    if not bucket or not key:
        raise ValueError("invalid storage_uri: expected s3://<bucket>/<key>")
    return bucket, key


def storage_uri_for(bucket: str, key: str) -> str:
    if not bucket or not key:
        raise ValueError("bucket and key are required")
    return f"s3://{bucket}/{key}"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, date_yyyymmdd: str, region: str, service: str) -> bytes:
    k_date = _hmac_sha256(("AWS4" + secret_key).encode("utf-8"), date_yyyymmdd)
    k_region = hmac.new(k_date, region.encode("utf-8"), hashlib.sha256).digest()
    k_service = hmac.new(k_region, service.encode("utf-8"), hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()
    return k_signing


def _canonical_uri(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return quote(path, safe="/-_.~")


def _canonical_headers(headers: dict[str, str]) -> tuple[str, str]:
    items = []
    for k, v in headers.items():
        kk = k.strip().lower()
        vv = " ".join((v or "").strip().split())
        items.append((kk, vv))
    items.sort(key=lambda x: x[0])
    canonical = "".join([f"{k}:{v}\n" for k, v in items])
    signed = ";".join([k for k, _ in items])
    return canonical, signed


def sigv4_headers(
    *,
    method: str,
    url: str,
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
    now: datetime | None = None,
) -> dict[str, str]:
    headers = dict(headers or {})
    now = now or datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    parsed = urlparse(url)
    payload_hash = _sha256_hex(body)
    headers["host"] = parsed.netloc
    headers["x-amz-date"] = amz_date
    headers["x-amz-content-sha256"] = payload_hash

    canonical_headers, signed_headers = _canonical_headers(headers)
    canonical_request = (
        f"{method.upper()}\n"
        f"{_canonical_uri(parsed.path or '/')}\n"
        f"{parsed.query or ''}\n"
        f"{canonical_headers}"
        f"{signed_headers}\n"
        f"{payload_hash}"
    )

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            algorithm,
            amz_date,
            credential_scope,
            _sha256_hex(canonical_request.encode("utf-8")),
        ]
    )
    signing_key = _signing_key(secret_key, date_stamp, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    headers["authorization"] = (
        f"{algorithm} Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return headers


def _bucket_url(cfg: S3Config, bucket: str) -> str:
    return f"{cfg.endpoint.rstrip('/')}/{bucket}"


def _object_url(cfg: S3Config, bucket: str, key: str) -> str:
    key = key.lstrip("/")
    return f"{cfg.endpoint.rstrip('/')}/{bucket}/{quote(key, safe='/-_.~')}"


def ensure_bucket_exists(
    cfg: S3Config, *, client: httpx.Client | None = None, bucket: str | None = None
) -> None:
    bucket = _sanitize_bucket_name(bucket or cfg.bucket)
    close_client = False
    if client is None:
        client = httpx.Client(timeout=10.0)
        close_client = True
    try:
        url = _bucket_url(cfg, bucket)
        h = sigv4_headers(
            method="HEAD",
            url=url,
            access_key=cfg.access_key,
            secret_key=cfg.secret_key,
            region=cfg.region,
            service=cfg.service,
            headers={},
            body=b"",
        )
        res = client.request("HEAD", url, headers=h)
        if res.status_code in (200, 204):
            return
        if res.status_code not in (400, 403, 404):
            res.raise_for_status()

        # Attempt bucket creation.
        h2 = sigv4_headers(
            method="PUT",
            url=url,
            access_key=cfg.access_key,
            secret_key=cfg.secret_key,
            region=cfg.region,
            service=cfg.service,
            headers={},
            body=b"",
        )
        res2 = client.request("PUT", url, headers=h2, content=b"")
        if res2.status_code not in (200, 204, 409):
            res2.raise_for_status()
    finally:
        if close_client:
            client.close()


def put_bytes(
    cfg: S3Config,
    *,
    key: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    bucket: str | None = None,
    client: httpx.Client | None = None,
) -> dict[str, str | int]:
    bucket = _sanitize_bucket_name(bucket or cfg.bucket)
    close_client = False
    if client is None:
        client = httpx.Client(timeout=30.0)
        close_client = True
    try:
        ensure_bucket_exists(cfg, client=client, bucket=bucket)
        url = _object_url(cfg, bucket, key)
        signed = sigv4_headers(
            method="PUT",
            url=url,
            access_key=cfg.access_key,
            secret_key=cfg.secret_key,
            region=cfg.region,
            service=cfg.service,
            headers={"content-type": content_type},
            body=data,
        )
        res = client.request("PUT", url, headers=signed, content=data)
        res.raise_for_status()
        etag = str(res.headers.get("etag", "")).strip('"')
        return {"bucket": bucket, "key": key, "etag": etag, "size": len(data)}
    finally:
        if close_client:
            client.close()


def get_bytes_from_storage_uri(
    storage_uri: str,
    *,
    cfg: S3Config | None = None,
    client: httpx.Client | None = None,
    max_bytes: int | None = None,
) -> bytes:
    cfg = cfg or load_s3_config()
    bucket, key = parse_storage_uri(storage_uri)
    bucket = _sanitize_bucket_name(bucket)
    close_client = False
    if client is None:
        client = httpx.Client(timeout=30.0)
        close_client = True
    try:
        url = _object_url(cfg, bucket, key)
        signed = sigv4_headers(
            method="GET",
            url=url,
            access_key=cfg.access_key,
            secret_key=cfg.secret_key,
            region=cfg.region,
            service=cfg.service,
            headers={},
            body=b"",
        )
        res = client.request("GET", url, headers=signed)
        res.raise_for_status()
        data = res.content
        if max_bytes is not None and len(data) > max_bytes:
            return data[:max_bytes]
        return data
    finally:
        if close_client:
            client.close()


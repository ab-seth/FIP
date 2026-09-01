from __future__ import annotations

import hashlib
import hmac
import http.client
import os
import ssl
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit

from fip_api.core.config import Settings

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class ObjectStoreError(RuntimeError):
    pass


class ObjectStoreObjectMissing(ObjectStoreError):
    pass


class S3ObjectStore:
    """Bounded AWS SigV4 client for immutable S3-compatible FIP evidence."""

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        region: str,
        prefix: str,
        timeout_seconds: int = 60,
    ) -> None:
        parsed = urlsplit(endpoint.rstrip("/"))
        if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
            raise ObjectStoreError("The S3-compatible endpoint must be an HTTPS origin.")
        self.hostname = parsed.hostname
        self.port = parsed.port or 443
        self.endpoint_path = parsed.path.rstrip("/")
        self.bucket = _safe_segment(bucket, label="bucket")
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.region = _safe_segment(region, label="region")
        self.prefix = _safe_relative_key(prefix)
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> S3ObjectStore:
        endpoint = settings.object_store_endpoint
        bucket = settings.object_store_bucket
        access_key = settings.object_store_access_key_id
        secret_key = settings.object_store_secret_access_key
        if endpoint is None or bucket is None or access_key is None or secret_key is None:
            raise ObjectStoreError("S3-compatible artifact storage is not fully configured.")
        return cls(
            endpoint=endpoint,
            bucket=bucket,
            access_key_id=access_key.get_secret_value(),
            secret_access_key=secret_key.get_secret_value(),
            region=settings.object_store_region,
            prefix=settings.object_store_prefix,
        )

    def upload_file(
        self,
        relative_key: str,
        source: Path,
        *,
        checksum: str,
        content_type: str = "application/octet-stream",
    ) -> None:
        try:
            size = source.stat().st_size
        except OSError as exc:
            raise ObjectStoreError("The immutable artifact could not be read.") from exc
        if size <= 0:
            raise ObjectStoreError("The immutable artifact is empty.")
        path = self._path(relative_key)
        headers = self._signed_headers(
            method="PUT",
            path=path,
            payload_hash=checksum,
            additional={
                "content-length": str(size),
                "content-type": content_type,
                "x-amz-meta-sha256": checksum,
            },
        )
        connection = self._connection()
        try:
            connection.putrequest("PUT", path, skip_host=True, skip_accept_encoding=True)
            for name, value in headers.items():
                connection.putheader(name, value)
            connection.endheaders()
            with source.open("rb") as artifact:
                while chunk := artifact.read(1024 * 1024):
                    connection.send(chunk)
            response = connection.getresponse()
            response.read()
            if response.status < 200 or response.status >= 300:
                raise ObjectStoreError(
                    f"The immutable artifact upload returned HTTP {response.status}."
                )
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise ObjectStoreError("The immutable artifact could not be uploaded.") from exc
        finally:
            connection.close()

    def download_file(self, relative_key: str, destination: Path, *, max_bytes: int) -> int:
        path = self._path(relative_key)
        headers = self._signed_headers(
            method="GET",
            path=path,
            payload_hash=EMPTY_SHA256,
            additional={},
        )
        connection = self._connection()
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            if response.status == 404:
                response.read()
                raise ObjectStoreObjectMissing("The immutable artifact is not available.")
            if response.status < 200 or response.status >= 300:
                response.read()
                raise ObjectStoreError(
                    f"The immutable artifact download returned HTTP {response.status}."
                )
            declared_header = response.getheader("Content-Length")
            try:
                declared_size = int(declared_header or "")
            except ValueError as exc:
                raise ObjectStoreError("The remote artifact did not declare a valid size.") from exc
            if declared_size <= 0 or declared_size > max_bytes:
                raise ObjectStoreError("The remote artifact has an invalid size.")

            written = 0
            try:
                with destination.open("xb") as output:
                    while chunk := response.read(min(1024 * 1024, max_bytes + 1 - written)):
                        written += len(chunk)
                        if written > max_bytes:
                            raise ObjectStoreError("The remote artifact exceeds its size contract.")
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
            except Exception:
                destination.unlink(missing_ok=True)
                raise
            if written != declared_size:
                destination.unlink(missing_ok=True)
                raise ObjectStoreError("The remote artifact download was incomplete.")
            return written
        except ObjectStoreError:
            raise
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            destination.unlink(missing_ok=True)
            raise ObjectStoreError("The immutable artifact could not be downloaded.") from exc
        finally:
            connection.close()

    def _connection(self) -> http.client.HTTPSConnection:
        return http.client.HTTPSConnection(
            self.hostname,
            port=self.port,
            timeout=self.timeout_seconds,
            context=ssl.create_default_context(),
        )

    def _path(self, relative_key: str) -> str:
        key = f"{self.prefix}/{_safe_relative_key(relative_key)}"
        raw_path = f"{self.endpoint_path}/{self.bucket}/{key}"
        return quote(raw_path, safe="/-_.~")

    def _signed_headers(
        self,
        *,
        method: str,
        path: str,
        payload_hash: str,
        additional: dict[str, str],
    ) -> dict[str, str]:
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        host = self.hostname if self.port == 443 else f"{self.hostname}:{self.port}"
        canonical_headers = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
            **{name.lower(): value.strip() for name, value in additional.items()},
        }
        signed_header_names = sorted(canonical_headers)
        signed_headers = ";".join(signed_header_names)
        header_block = "".join(
            f"{name}:{canonical_headers[name]}\n" for name in signed_header_names
        )
        canonical_request = "\n".join(
            [method, path, "", header_block, signed_headers, payload_hash]
        )
        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )
        signing_key = _signature_key(
            self.secret_access_key,
            date_stamp=date_stamp,
            region=self.region,
        )
        signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
        authorization = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return {
            **canonical_headers,
            "authorization": authorization,
        }


def _signature_key(secret: str, *, date_stamp: str, region: str) -> bytes:
    date_key = hmac.new(f"AWS4{secret}".encode(), date_stamp.encode(), hashlib.sha256).digest()
    region_key = hmac.new(date_key, region.encode(), hashlib.sha256).digest()
    service_key = hmac.new(region_key, b"s3", hashlib.sha256).digest()
    return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()


def _safe_relative_key(value: str) -> str:
    key = PurePosixPath(value.strip("/"))
    if key.is_absolute() or not key.parts or any(part in {"", ".", ".."} for part in key.parts):
        raise ObjectStoreError("The object key is unsafe.")
    return key.as_posix()


def _safe_segment(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not normalized or "/" in normalized or normalized in {".", ".."}:
        raise ObjectStoreError(f"The object-store {label} is invalid.")
    return normalized

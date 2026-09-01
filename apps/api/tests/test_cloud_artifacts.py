from __future__ import annotations

import hashlib
import io
import shutil
from pathlib import Path

from fip_api.core.object_store import S3ObjectStore
from fip_api.model_runtime import S3ModelArtifactStore
from fip_api.training_operations import S3TrainingArtifactStore
from fip_api.training_operations.artifacts import EXPECTED_BUNDLE_FILES


class MemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def upload_file(
        self,
        relative_key: str,
        source: Path,
        *,
        checksum: str,
        content_type: str = "application/octet-stream",
    ) -> None:
        del content_type
        content = source.read_bytes()
        assert hashlib.sha256(content).hexdigest() == checksum
        self.objects[relative_key] = content

    def download_file(self, relative_key: str, destination: Path, *, max_bytes: int) -> int:
        content = self.objects[relative_key]
        assert 0 < len(content) <= max_bytes
        destination.write_bytes(content)
        return len(content)


class MemoryResponse:
    def __init__(self, content: bytes, *, status: int = 200) -> None:
        self.status = status
        self.content = io.BytesIO(content)
        self.headers = {"Content-Length": str(len(content))}

    def read(self, amount: int | None = None) -> bytes:
        return self.content.read() if amount is None else self.content.read(amount)

    def getheader(self, name: str) -> str | None:
        return self.headers.get(name)


class MemoryConnection:
    def __init__(self, response: MemoryResponse) -> None:
        self.response = response
        self.method: str | None = None
        self.path: str | None = None
        self.headers: dict[str, str] = {}
        self.sent = bytearray()
        self.closed = False

    def putrequest(self, method: str, path: str, **kwargs: object) -> None:
        del kwargs
        self.method = method
        self.path = path

    def putheader(self, name: str, value: str) -> None:
        self.headers[name] = value

    def endheaders(self) -> None:
        return None

    def send(self, content: bytes) -> None:
        self.sent.extend(content)

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
    ) -> None:
        self.method = method
        self.path = path
        self.headers = headers

    def getresponse(self) -> MemoryResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


def test_model_artifact_rehydrates_from_remote_verified_cache(tmp_path: Path) -> None:
    remote = MemoryObjectStore()
    root = tmp_path / "models"
    store = S3ModelArtifactStore(  # type: ignore[arg-type]
        root,
        max_bytes=1024,
        object_store=remote,
    )
    content = b"checksum-bound-model-artifact"
    checksum = hashlib.sha256(content).hexdigest()

    installation = store.install(checksum, content)
    shutil.rmtree(root)
    with store.open_verified(checksum) as artifact:
        restored = artifact.read()

    assert installation.installed is True
    assert restored == content
    assert store.status(checksum).integrity_verified is True
    assert remote.objects[f"model-artifacts/{checksum[:2]}/{checksum}.joblib"] == content


def test_training_bundle_rehydrates_only_the_fixed_file_contract(tmp_path: Path) -> None:
    remote = MemoryObjectStore()
    root = tmp_path / "training"
    store = S3TrainingArtifactStore(  # type: ignore[arg-type]
        root,
        max_artifact_bytes=1024,
        object_store=remote,
    )
    bundle_key = "10000000-0000-0000-0000-000000000001"
    directory = store.output_directory(bundle_key)
    for relative_path in EXPECTED_BUNDLE_FILES | {"run-manifest.json"}:
        path = directory / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"{}" if relative_path.endswith(".json") else b"artifact")

    store.make_immutable(bundle_key)
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir():
            path.chmod(0o750)
    shutil.rmtree(root)
    restored = store.evidence_path(bundle_key, evidence_name="training-evidence")

    assert restored.read_bytes() == b"{}"
    assert len(remote.objects) == len(EXPECTED_BUNDLE_FILES) + 1
    assert set(remote.objects) == {
        f"training-artifacts/{bundle_key}/{relative_path}"
        for relative_path in EXPECTED_BUNDLE_FILES | {"run-manifest.json"}
    }


def test_s3_signing_uses_encoded_path_and_never_exposes_secret() -> None:
    store = S3ObjectStore(
        endpoint="https://example.r2.cloudflarestorage.com",
        bucket="fip-artifacts",
        access_key_id="access-key",
        secret_access_key="private-secret",
        region="auto",
        prefix="fip-staging",
    )
    path = store._path("training-artifacts/run id/model.joblib")
    headers = store._signed_headers(
        method="GET",
        path=path,
        payload_hash=hashlib.sha256(b"").hexdigest(),
        additional={},
    )

    assert path == "/fip-artifacts/fip-staging/training-artifacts/run%20id/model.joblib"
    assert headers["host"] == "example.r2.cloudflarestorage.com"
    assert headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=access-key/")
    assert "private-secret" not in headers["authorization"]


def test_s3_client_streams_signed_upload_and_bounded_download(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = S3ObjectStore(
        endpoint="https://example.r2.cloudflarestorage.com",
        bucket="fip-artifacts",
        access_key_id="access-key",
        secret_access_key="private-secret",
        region="auto",
        prefix="fip-staging",
    )
    content = b"bounded immutable object"
    checksum = hashlib.sha256(content).hexdigest()
    source = tmp_path / "source.bin"
    source.write_bytes(content)
    upload_connection = MemoryConnection(MemoryResponse(b""))
    monkeypatch.setattr(store, "_connection", lambda: upload_connection)

    store.upload_file("models/artifact.bin", source, checksum=checksum)

    assert upload_connection.method == "PUT"
    assert bytes(upload_connection.sent) == content
    assert upload_connection.headers["x-amz-content-sha256"] == checksum
    assert upload_connection.closed is True

    download_connection = MemoryConnection(MemoryResponse(content))
    monkeypatch.setattr(store, "_connection", lambda: download_connection)
    destination = tmp_path / "destination.bin"

    written = store.download_file("models/artifact.bin", destination, max_bytes=1024)

    assert written == len(content)
    assert destination.read_bytes() == content
    assert download_connection.method == "GET"
    assert download_connection.closed is True

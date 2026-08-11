from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from fip_api.core.config import get_settings


class ArtifactStoreError(ValueError):
    pass


class ArtifactNotInstalled(ArtifactStoreError):
    pass


class ArtifactIntegrityError(ArtifactStoreError):
    pass


@dataclass(frozen=True)
class ArtifactInstallation:
    checksum: str
    size_bytes: int
    installed: bool


@dataclass(frozen=True)
class ArtifactStatus:
    checksum: str
    installed: bool
    integrity_verified: bool
    size_bytes: int | None


class ModelArtifactStore:
    """Content-addressed storage for administrator-approved model artifacts."""

    def __init__(self, root: Path, *, max_bytes: int) -> None:
        self.root = root
        self.max_bytes = max_bytes

    def install(self, expected_checksum: str, content: bytes) -> ArtifactInstallation:
        checksum = _validated_checksum(expected_checksum)
        if not content:
            raise ArtifactIntegrityError("The model artifact is empty.")
        if len(content) > self.max_bytes:
            raise ArtifactIntegrityError(
                f"The model artifact cannot exceed {self.max_bytes} bytes."
            )
        actual_checksum = hashlib.sha256(content).hexdigest()
        if actual_checksum != checksum:
            raise ArtifactIntegrityError(
                "The uploaded artifact checksum does not match the registered model."
            )

        destination = self._path(checksum)
        destination.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            with self.open_verified(checksum) as existing:
                existing.seek(0, os.SEEK_END)
                size_bytes = existing.tell()
            return ArtifactInstallation(
                checksum=checksum,
                size_bytes=size_bytes,
                installed=False,
            )

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{checksum}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            temporary.chmod(0o440)
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return ArtifactInstallation(
            checksum=checksum,
            size_bytes=len(content),
            installed=True,
        )

    def status(self, expected_checksum: str) -> ArtifactStatus:
        checksum = _validated_checksum(expected_checksum)
        try:
            with self.open_verified(checksum) as artifact:
                artifact.seek(0, os.SEEK_END)
                size_bytes = artifact.tell()
        except ArtifactNotInstalled:
            return ArtifactStatus(
                checksum=checksum,
                installed=False,
                integrity_verified=False,
                size_bytes=None,
            )
        except ArtifactIntegrityError:
            return ArtifactStatus(
                checksum=checksum,
                installed=True,
                integrity_verified=False,
                size_bytes=None,
            )
        return ArtifactStatus(
            checksum=checksum,
            installed=True,
            integrity_verified=True,
            size_bytes=size_bytes,
        )

    @contextmanager
    def open_verified(self, expected_checksum: str) -> Generator[BinaryIO]:
        checksum = _validated_checksum(expected_checksum)
        path = self._path(checksum)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError as exc:
            raise ArtifactNotInstalled(
                "The registered model artifact is not installed in the trusted store."
            ) from exc
        except OSError as exc:
            raise ArtifactIntegrityError(
                "The registered model artifact cannot be opened safely."
            ) from exc

        with os.fdopen(descriptor, "rb") as artifact:
            metadata = os.fstat(artifact.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise ArtifactIntegrityError("The model artifact must be a regular file.")
            if metadata.st_size <= 0 or metadata.st_size > self.max_bytes:
                raise ArtifactIntegrityError("The installed model artifact has an invalid size.")
            actual_checksum = _checksum_stream(artifact)
            if actual_checksum != checksum:
                raise ArtifactIntegrityError(
                    "The installed model artifact no longer matches its registered checksum."
                )
            artifact.seek(0)
            yield artifact

    def _path(self, checksum: str) -> Path:
        return self.root / checksum[:2] / f"{checksum}.joblib"


def get_model_artifact_store() -> ModelArtifactStore:
    settings = get_settings()
    return ModelArtifactStore(
        settings.model_artifact_root,
        max_bytes=settings.model_artifact_max_bytes,
    )


def _validated_checksum(value: str) -> str:
    normalized = value.lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ArtifactIntegrityError("A valid SHA-256 artifact checksum is required.")
    return normalized


def _checksum_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import urllib.request
from pathlib import Path

from fip_api.research_ml.pipeline import ULB_DOWNLOAD_URL, ULB_SOURCE_PAGE

ULB_OPENML_MD5 = "178bcf9bb1f31a3dfe12d0e577884add"


def fetch_ulb(output_path: Path) -> dict[str, str | int]:
    """Download the pinned public OpenML file and verify provider metadata."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise FileExistsError(output_path)

    md5_digest = hashlib.md5(usedforsecurity=False)
    sha256_digest = hashlib.sha256()
    request = urllib.request.Request(
        ULB_DOWNLOAD_URL,
        headers={"User-Agent": "FIP research dataset fetcher/1.0"},
    )
    temporary_path: Path | None = None
    try:
        with (
            urllib.request.urlopen(request, timeout=60) as response,
            tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{output_path.name}-",
                dir=output_path.parent,
                delete=False,
            ) as temporary_file,
        ):
            temporary_path = Path(temporary_file.name)
            while chunk := response.read(1024 * 1024):
                temporary_file.write(chunk)
                md5_digest.update(chunk)
                sha256_digest.update(chunk)

        actual_md5 = md5_digest.hexdigest()
        if actual_md5 != ULB_OPENML_MD5:
            raise ValueError(
                f"OpenML file checksum mismatch: expected {ULB_OPENML_MD5}, received {actual_md5}"
            )
        os.replace(temporary_path, output_path)
        temporary_path = None
        return {
            "source_page": ULB_SOURCE_PAGE,
            "download_url": ULB_DOWNLOAD_URL,
            "output": str(output_path),
            "bytes": output_path.stat().st_size,
            "provider_md5": actual_md5,
            "sha256": sha256_digest.hexdigest(),
        }
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch the pinned ULB/OpenML research dataset.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/creditcard.arff"),
    )
    arguments = parser.parse_args()
    print(json.dumps(fetch_ulb(arguments.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

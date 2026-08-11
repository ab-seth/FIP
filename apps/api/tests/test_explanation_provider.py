from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from fip_api.explainability import (
    CaseBriefProviderFailure,
    CaseBriefProviderUnavailable,
    JsonHttpCaseBriefProvider,
    UnavailableCaseBriefProvider,
)


class FakeHttpResponse:
    def __init__(self, body: bytes, *, content_length: str | None = None) -> None:
        self.body = body
        self.headers = {"Content-Length": content_length} if content_length is not None else {}

    def __enter__(self) -> FakeHttpResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


def test_json_http_provider_accepts_wrapped_structured_output() -> None:
    output = {"summary": "Structured provider output"}
    raw = json.dumps({"output": output}).encode()
    provider = _provider()
    with patch(
        "fip_api.explainability.provider.urlopen",
        return_value=FakeHttpResponse(raw, content_length=str(len(raw))),
    ) as mocked_urlopen:
        result = provider.generate({"response_format": "json"})

    assert result.output == output
    assert result.raw_output == raw.decode()
    assert result.generation_milliseconds >= 0
    request = mocked_urlopen.call_args.args[0]
    assert request.full_url == "https://llm-gateway.example.test/case-brief"
    assert request.get_header("Authorization") == "Bearer test-secret"
    assert mocked_urlopen.call_args.kwargs["timeout"] == 4


def test_json_http_provider_rejects_invalid_or_oversized_output() -> None:
    provider = _provider(max_response_bytes=1024)
    with (
        patch(
            "fip_api.explainability.provider.urlopen",
            return_value=FakeHttpResponse(b"not-json"),
        ),
        pytest.raises(CaseBriefProviderFailure, match="not valid JSON") as invalid,
    ):
        provider.generate({"response_format": "json"})
    assert invalid.value.raw_output == "not-json"

    with (
        patch(
            "fip_api.explainability.provider.urlopen",
            return_value=FakeHttpResponse(b"{}", content_length="1025"),
        ),
        pytest.raises(CaseBriefProviderFailure, match="exceeded"),
    ):
        provider.generate({"response_format": "json"})


def test_unavailable_provider_fails_without_using_evidence() -> None:
    provider = UnavailableCaseBriefProvider()
    with pytest.raises(CaseBriefProviderUnavailable, match="No LLM endpoint"):
        provider.generate({"evidence": {"sensitive": "not sent"}})


def _provider(*, max_response_bytes: int = 2048) -> JsonHttpCaseBriefProvider:
    return JsonHttpCaseBriefProvider(
        endpoint="https://llm-gateway.example.test/case-brief",
        api_key="test-secret",
        model_name="provider-model-v1",
        provider_name="test-gateway",
        timeout_seconds=4,
        max_response_bytes=max_response_bytes,
    )

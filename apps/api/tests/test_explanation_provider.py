from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from fip_api.core.config import Settings
from fip_api.explainability import (
    CaseBriefProviderFailure,
    CaseBriefProviderUnavailable,
    JsonHttpCaseBriefProvider,
    OpenAICompatibleCaseBriefProvider,
    UnavailableCaseBriefProvider,
    build_case_brief_provider_status,
    get_case_brief_provider,
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


def test_local_provider_configuration_normalizes_empty_secret_and_allows_cold_start_timeout() -> (
    None
):
    settings = Settings(_env_file=None, llm_api_key="", llm_timeout_seconds=120)

    assert settings.llm_api_key is None
    assert settings.llm_timeout_seconds == 120


def test_openai_compatible_provider_sends_schema_and_parses_message_content() -> None:
    output = {"summary": "Grounded structured output"}
    raw = json.dumps(
        {
            "id": "chatcmpl-test",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(output)},
                }
            ],
        }
    ).encode()
    provider = _openai_provider(endpoint="http://localhost:1234/v1")
    payload = {
        "prompt_version": "grounded-case-brief-v1.0.0",
        "output_schema_version": "grounded-case-brief-output-v1.0.0",
        "response_format": "json",
        "system_instruction": "Return only grounded JSON.",
        "evidence": {"evidence_catalog": {"rule.score": 75}},
        "response_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
    }
    with patch(
        "fip_api.explainability.provider.urlopen",
        return_value=FakeHttpResponse(raw, content_length=str(len(raw))),
    ) as mocked_urlopen:
        result = provider.generate(payload)

    assert result.output == output
    assert result.raw_output == raw.decode()
    request = mocked_urlopen.call_args.args[0]
    assert request.full_url == "http://localhost:1234/v1/chat/completions"
    assert request.get_header("Authorization") is None
    request_body = json.loads(request.data)
    assert request_body["model"] == "qwen-test"
    assert request_body["temperature"] == 0
    assert request_body["stream"] is False
    assert request_body["max_tokens"] == 1200
    assert request_body["messages"][0] == {
        "role": "system",
        "content": "Return only grounded JSON.",
    }
    user_message = json.loads(request_body["messages"][1]["content"])
    assert user_message["evidence"]["evidence_catalog"]["rule.score"] == 75
    assert "system_instruction" not in user_message
    assert request_body["response_format"]["json_schema"]["strict"] is True
    assert request_body["response_format"]["json_schema"]["schema"] == payload["response_schema"]


@pytest.mark.parametrize(
    ("response", "expected_error"),
    [
        ({"choices": []}, "exactly one completion choice"),
        (
            {"choices": [{"finish_reason": "length", "message": {"content": '{"summary":"cut"}'}}]},
            "token limit",
        ),
        (
            {"choices": [{"finish_reason": "stop", "message": {"content": "not-json"}}]},
            "message content was not valid JSON",
        ),
    ],
)
def test_openai_compatible_provider_rejects_invalid_completion_envelopes(
    response: dict[str, object],
    expected_error: str,
) -> None:
    raw = json.dumps(response).encode()
    with (
        patch(
            "fip_api.explainability.provider.urlopen",
            return_value=FakeHttpResponse(raw, content_length=str(len(raw))),
        ),
        pytest.raises(CaseBriefProviderFailure, match=expected_error) as failure,
    ):
        _openai_provider().generate(
            {
                "system_instruction": "Return JSON.",
                "response_schema": {"type": "object"},
                "evidence": {},
            }
        )
    assert failure.value.raw_output == raw.decode()


def test_provider_factory_and_status_select_local_openai_adapter_without_exposing_endpoint() -> (
    None
):
    settings = SimpleNamespace(
        llm_adapter="openai-compatible",
        llm_endpoint="http://host.docker.internal:1234/v1/chat/completions",
        llm_api_key=None,
        llm_model="qwen-local",
        llm_provider_name="lm-studio",
        llm_timeout_seconds=60,
        llm_max_response_bytes=262_144,
        llm_max_completion_tokens=1800,
    )
    with patch("fip_api.explainability.provider.get_settings", return_value=settings):
        provider = get_case_brief_provider()
        status = build_case_brief_provider_status()

    assert isinstance(provider, OpenAICompatibleCaseBriefProvider)
    assert status.configured is True
    assert status.adapter == "openai-compatible"
    assert status.provider_name == "lm-studio"
    assert status.model_name == "qwen-local"
    assert status.endpoint_scope == "local"
    assert status.api_key_configured is False
    assert status.connectivity_checked is False
    assert "endpoint" not in status.model_dump()


def _provider(*, max_response_bytes: int = 2048) -> JsonHttpCaseBriefProvider:
    return JsonHttpCaseBriefProvider(
        endpoint="https://llm-gateway.example.test/case-brief",
        api_key="test-secret",
        model_name="provider-model-v1",
        provider_name="test-gateway",
        timeout_seconds=4,
        max_response_bytes=max_response_bytes,
    )


def _openai_provider(
    *, endpoint: str = "http://localhost:1234/v1/chat/completions"
) -> OpenAICompatibleCaseBriefProvider:
    return OpenAICompatibleCaseBriefProvider(
        endpoint=endpoint,
        api_key=None,
        model_name="qwen-test",
        provider_name="lm-studio",
        timeout_seconds=60,
        max_response_bytes=4096,
        max_completion_tokens=1200,
    )

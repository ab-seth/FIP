from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter_ns
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from fip_api.core.config import get_settings
from fip_api.schemas.explanation import CaseBriefProviderStatusResponse


class CaseBriefProviderFailure(RuntimeError):
    def __init__(self, message: str, *, raw_output: str | None = None) -> None:
        super().__init__(message)
        self.raw_output = raw_output


class CaseBriefProviderUnavailable(CaseBriefProviderFailure):
    pass


@dataclass(frozen=True)
class CaseBriefProviderResult:
    output: object
    raw_output: str
    generation_milliseconds: int


@dataclass(frozen=True)
class _HttpJsonResult:
    output: object
    raw_output: str
    generation_milliseconds: int


class CaseBriefProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def generate(self, request_payload: dict[str, object]) -> CaseBriefProviderResult: ...


class UnavailableCaseBriefProvider:
    provider_name = "deterministic-fallback"
    model_name = "deterministic-case-brief-v1"

    def generate(self, request_payload: dict[str, object]) -> CaseBriefProviderResult:
        del request_payload
        raise CaseBriefProviderUnavailable("No LLM endpoint is configured.")


class JsonHttpCaseBriefProvider:
    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str | None,
        model_name: str,
        provider_name: str,
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.model_name = model_name
        self.provider_name = provider_name
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes

    def generate(self, request_payload: dict[str, object]) -> CaseBriefProviderResult:
        body = json.dumps(
            {"model": self.model_name, **request_payload},
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        response = _post_json(
            endpoint=self.endpoint,
            api_key=self.api_key,
            body=body,
            timeout_seconds=self.timeout_seconds,
            max_response_bytes=self.max_response_bytes,
        )
        decoded = response.output
        if isinstance(decoded, dict) and "output" in decoded:
            decoded = decoded["output"]
        return CaseBriefProviderResult(
            output=decoded,
            raw_output=response.raw_output,
            generation_milliseconds=response.generation_milliseconds,
        )


class OpenAICompatibleCaseBriefProvider:
    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str | None,
        model_name: str,
        provider_name: str,
        timeout_seconds: int,
        max_response_bytes: int,
        max_completion_tokens: int,
    ) -> None:
        self.endpoint = _normalize_chat_completions_endpoint(endpoint)
        self.api_key = api_key
        self.model_name = model_name
        self.provider_name = provider_name
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.max_completion_tokens = max_completion_tokens

    def generate(self, request_payload: dict[str, object]) -> CaseBriefProviderResult:
        system_instruction = request_payload.get("system_instruction")
        response_schema = request_payload.get("response_schema")
        if not isinstance(system_instruction, str) or not system_instruction.strip():
            raise CaseBriefProviderFailure("The case-brief system instruction is invalid.")
        if not isinstance(response_schema, dict):
            raise CaseBriefProviderFailure("The case-brief response schema is invalid.")

        evidence_request = {
            key: value
            for key, value in request_payload.items()
            if key not in {"response_format", "response_schema", "system_instruction"}
        }
        body = json.dumps(
            {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {
                        "role": "user",
                        "content": json.dumps(
                            evidence_request,
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    },
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "fip_grounded_case_brief",
                        "strict": True,
                        "schema": response_schema,
                    },
                },
                "temperature": 0,
                "max_tokens": self.max_completion_tokens,
                "stream": False,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        response = _post_json(
            endpoint=self.endpoint,
            api_key=self.api_key,
            body=body,
            timeout_seconds=self.timeout_seconds,
            max_response_bytes=self.max_response_bytes,
        )
        content = _openai_message_content(response.output, response.raw_output)
        try:
            output = json.loads(content)
        except json.JSONDecodeError as exc:
            raise CaseBriefProviderFailure(
                "LLM message content was not valid JSON.", raw_output=response.raw_output
            ) from exc
        return CaseBriefProviderResult(
            output=output,
            raw_output=response.raw_output,
            generation_milliseconds=response.generation_milliseconds,
        )


def get_case_brief_provider() -> CaseBriefProvider:
    settings = get_settings()
    if settings.llm_endpoint is None or settings.llm_model is None:
        return UnavailableCaseBriefProvider()
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key is not None else None
    if settings.llm_adapter == "openai-compatible":
        return OpenAICompatibleCaseBriefProvider(
            endpoint=settings.llm_endpoint,
            api_key=api_key,
            model_name=settings.llm_model,
            provider_name=settings.llm_provider_name,
            timeout_seconds=settings.llm_timeout_seconds,
            max_response_bytes=settings.llm_max_response_bytes,
            max_completion_tokens=settings.llm_max_completion_tokens,
        )
    return JsonHttpCaseBriefProvider(
        endpoint=settings.llm_endpoint,
        api_key=api_key,
        model_name=settings.llm_model,
        provider_name=settings.llm_provider_name,
        timeout_seconds=settings.llm_timeout_seconds,
        max_response_bytes=settings.llm_max_response_bytes,
    )


def build_case_brief_provider_status() -> CaseBriefProviderStatusResponse:
    settings = get_settings()
    configured = settings.llm_endpoint is not None and settings.llm_model is not None
    adapter = settings.llm_adapter if configured else "disabled"
    return CaseBriefProviderStatusResponse(
        configured=configured,
        adapter=adapter,
        provider_name=settings.llm_provider_name if configured else "deterministic-fallback",
        model_name=settings.llm_model if configured else None,
        endpoint_scope=_endpoint_scope(settings.llm_endpoint if configured else None),
        api_key_configured=settings.llm_api_key is not None,
        timeout_seconds=settings.llm_timeout_seconds,
        max_response_bytes=settings.llm_max_response_bytes,
        max_completion_tokens=settings.llm_max_completion_tokens,
    )


def _post_json(
    *,
    endpoint: str,
    api_key: str | None,
    body: bytes,
    timeout_seconds: int,
    max_response_bytes: int,
) -> _HttpJsonResult:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "fip-grounded-case-brief/1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(endpoint, data=body, headers=headers, method="POST")
    started_at = perf_counter_ns()
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            content_length = response.headers.get("Content-Length")
            if (
                content_length is not None
                and content_length.isdigit()
                and int(content_length) > max_response_bytes
            ):
                raise CaseBriefProviderFailure("LLM response exceeded the configured limit.")
            raw_bytes = response.read(max_response_bytes + 1)
    except HTTPError as exc:
        raise CaseBriefProviderFailure(f"LLM endpoint returned HTTP {exc.code}.") from exc
    except (TimeoutError, URLError, OSError) as exc:
        raise CaseBriefProviderFailure("LLM endpoint could not be reached.") from exc
    generation_milliseconds = max(0, (perf_counter_ns() - started_at) // 1_000_000)
    if len(raw_bytes) > max_response_bytes:
        raise CaseBriefProviderFailure("LLM response exceeded the configured limit.")
    try:
        raw_output = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CaseBriefProviderFailure("LLM response was not valid UTF-8.") from exc
    try:
        decoded = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise CaseBriefProviderFailure(
            "LLM response was not valid JSON.", raw_output=raw_output
        ) from exc
    return _HttpJsonResult(
        output=decoded,
        raw_output=raw_output,
        generation_milliseconds=generation_milliseconds,
    )


def _openai_message_content(output: object, raw_output: str) -> str:
    if not isinstance(output, dict):
        raise CaseBriefProviderFailure(
            "LLM response did not contain a chat-completion object.", raw_output=raw_output
        )
    choices = output.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise CaseBriefProviderFailure(
            "LLM response did not contain exactly one completion choice.", raw_output=raw_output
        )
    choice = choices[0]
    if choice.get("finish_reason") == "length":
        raise CaseBriefProviderFailure(
            "LLM response stopped at the configured token limit.", raw_output=raw_output
        )
    message = choice.get("message")
    if not isinstance(message, dict):
        raise CaseBriefProviderFailure(
            "LLM response did not contain an assistant message.", raw_output=raw_output
        )
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise CaseBriefProviderFailure(
            "LLM response did not contain structured message content.", raw_output=raw_output
        )
    return content


def _normalize_chat_completions_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    path = parsed.path.rstrip("/")
    if path in {"", "/v1"}:
        path = f"{path or '/v1'}/chat/completions"
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def _endpoint_scope(endpoint: str | None) -> Literal["disabled", "local", "remote"]:
    if endpoint is None:
        return "disabled"
    hostname = (urlsplit(endpoint).hostname or "").lower()
    if hostname in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}:
        return "local"
    return "remote"

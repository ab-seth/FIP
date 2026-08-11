from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter_ns
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fip_api.core.config import get_settings


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
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "fip-grounded-case-brief/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.endpoint, data=body, headers=headers, method="POST")
        started_at = perf_counter_ns()
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                content_length = response.headers.get("Content-Length")
                if (
                    content_length is not None
                    and content_length.isdigit()
                    and int(content_length) > self.max_response_bytes
                ):
                    raise CaseBriefProviderFailure("LLM response exceeded the configured limit.")
                raw_bytes = response.read(self.max_response_bytes + 1)
        except HTTPError as exc:
            raise CaseBriefProviderFailure(f"LLM endpoint returned HTTP {exc.code}.") from exc
        except (TimeoutError, URLError, OSError) as exc:
            raise CaseBriefProviderFailure("LLM endpoint could not be reached.") from exc
        generation_milliseconds = max(0, (perf_counter_ns() - started_at) // 1_000_000)
        if len(raw_bytes) > self.max_response_bytes:
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
        if isinstance(decoded, dict) and "output" in decoded:
            decoded = decoded["output"]
        return CaseBriefProviderResult(
            output=decoded,
            raw_output=raw_output,
            generation_milliseconds=generation_milliseconds,
        )


def get_case_brief_provider() -> CaseBriefProvider:
    settings = get_settings()
    if settings.llm_endpoint is None or settings.llm_model is None:
        return UnavailableCaseBriefProvider()
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key is not None else None
    return JsonHttpCaseBriefProvider(
        endpoint=settings.llm_endpoint,
        api_key=api_key,
        model_name=settings.llm_model,
        provider_name=settings.llm_provider_name,
        timeout_seconds=settings.llm_timeout_seconds,
        max_response_bytes=settings.llm_max_response_bytes,
    )

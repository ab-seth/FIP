from __future__ import annotations

from fip_api.schemas.explanation import CaseBriefOutput

PROMPT_VERSION = "grounded-case-brief-v1.0.0"
OUTPUT_SCHEMA_VERSION = "grounded-case-brief-output-v1.0.0"
EVIDENCE_SCHEMA_VERSION = "grounded-case-brief-evidence-v1.0.0"

SYSTEM_INSTRUCTION = """You generate a concise fraud-review case brief from supplied evidence.
Use only facts in evidence_catalog. Every sentence or list item must cite one or more exact catalog
keys in its evidence_refs. Do not calculate or modify a risk score. Do not declare fraud proven,
classify the case, or recommend blocking, freezing, declining, reversing, or closing a transaction,
payment, or account. Do not introduce unsupported amounts, dates, counts, percentages, thresholds,
or other numerical claims. Return only one JSON object matching response_schema."""


def build_provider_request(evidence: dict[str, object]) -> dict[str, object]:
    return {
        "prompt_version": PROMPT_VERSION,
        "output_schema_version": OUTPUT_SCHEMA_VERSION,
        "response_format": "json",
        "system_instruction": SYSTEM_INSTRUCTION,
        "evidence": evidence,
        "response_schema": CaseBriefOutput.model_json_schema(),
    }

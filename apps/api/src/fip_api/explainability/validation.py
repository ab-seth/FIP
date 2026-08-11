from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from fip_api.schemas.explanation import (
    CaseBriefOutput,
    GroundingFailureResponse,
    GroundingValidationResponse,
)

NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?")
PROHIBITED_PATTERNS = (
    re.compile(r"\b(?:is|was|constitutes?|proves?)\s+(?:definitely\s+)?fraud\b", re.I),
    re.compile(r"\bfraud\s+(?:is\s+)?(?:proven|confirmed)\b", re.I),
    re.compile(
        r"\b(?:block|freeze|decline|reverse|cancel|close|seize)\b.{0,40}"
        r"\b(?:transaction|payment|account|funds?)\b",
        re.I,
    ),
    re.compile(r"\bautomatically\s+(?:classify|approve|reject|report|escalate)\b", re.I),
)


def validate_case_brief_output(
    candidate: object,
    evidence_catalog: dict[str, object],
) -> tuple[CaseBriefOutput | None, GroundingValidationResponse]:
    try:
        output = CaseBriefOutput.model_validate(candidate)
    except ValidationError as exc:
        schema_failures = [
            GroundingFailureResponse(
                code="schema_invalid",
                location=".".join(str(part) for part in error["loc"]),
                detail=str(error["msg"]),
            )
            for error in exc.errors(include_url=False)[:20]
        ]
        return None, GroundingValidationResponse(
            schema_valid=False,
            citations_valid=False,
            numerical_claims_valid=False,
            prohibited_actions_absent=False,
            grounding_passed=False,
            failures=schema_failures,
        )

    failures: list[GroundingFailureResponse] = []
    narrative = [
        ("summary", output.summary, output.summary_evidence_refs),
        *(
            (f"primary_risk_factors.{index}", claim.text, claim.evidence_refs)
            for index, claim in enumerate(output.primary_risk_factors)
        ),
        *(
            (f"supporting_evidence.{index}", claim.text, claim.evidence_refs)
            for index, claim in enumerate(output.supporting_evidence)
        ),
        *(
            (f"uncertainties.{index}", claim.text, claim.evidence_refs)
            for index, claim in enumerate(output.uncertainties)
        ),
        *(
            (f"recommended_review_steps.{index}", claim.text, claim.evidence_refs)
            for index, claim in enumerate(output.recommended_review_steps)
        ),
    ]
    citations_valid = True
    numerical_claims_valid = True
    prohibited_actions_absent = True
    for location, text, evidence_refs in narrative:
        unknown_refs = sorted(set(evidence_refs).difference(evidence_catalog))
        duplicate_refs = len(evidence_refs) != len(set(evidence_refs))
        if unknown_refs:
            citations_valid = False
            failures.append(
                GroundingFailureResponse(
                    code="unsupported_evidence_reference",
                    location=location,
                    detail=f"Unknown evidence references: {', '.join(unknown_refs)}.",
                )
            )
        if duplicate_refs:
            citations_valid = False
            failures.append(
                GroundingFailureResponse(
                    code="duplicate_evidence_reference",
                    location=location,
                    detail="Evidence references must be unique within a claim.",
                )
            )
        if not unknown_refs:
            allowed_numbers = _numbers_from_values(
                [evidence_catalog[reference] for reference in evidence_refs]
            )
            unsupported_numbers = sorted(
                number for number in _numbers_from_text(text) if number not in allowed_numbers
            )
            if unsupported_numbers:
                numerical_claims_valid = False
                failures.append(
                    GroundingFailureResponse(
                        code="unsupported_numerical_claim",
                        location=location,
                        detail="Unsupported numerical values: "
                        + ", ".join(_decimal_text(value) for value in unsupported_numbers)
                        + ".",
                    )
                )
        if any(pattern.search(text) for pattern in PROHIBITED_PATTERNS):
            prohibited_actions_absent = False
            failures.append(
                GroundingFailureResponse(
                    code="prohibited_claim_or_action",
                    location=location,
                    detail=(
                        "The narrative contains a prohibited conclusion or consequential action."
                    ),
                )
            )

    grounding_passed = citations_valid and numerical_claims_valid and prohibited_actions_absent
    return output, GroundingValidationResponse(
        schema_valid=True,
        citations_valid=citations_valid,
        numerical_claims_valid=numerical_claims_valid,
        prohibited_actions_absent=prohibited_actions_absent,
        grounding_passed=grounding_passed,
        failures=failures,
    )


def provider_failure_report(
    *,
    code: str,
    detail: str,
) -> GroundingValidationResponse:
    return GroundingValidationResponse(
        schema_valid=False,
        citations_valid=False,
        numerical_claims_valid=False,
        prohibited_actions_absent=False,
        grounding_passed=False,
        failures=[
            GroundingFailureResponse(
                code=code,
                location="provider",
                detail=detail,
            )
        ],
    )


def _numbers_from_values(values: list[object]) -> set[Decimal]:
    return _numbers_from_text(
        json.dumps(values, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    )


def _numbers_from_text(text: str) -> set[Decimal]:
    numbers: set[Decimal] = set()
    for raw_number in NUMBER_PATTERN.findall(text):
        try:
            number = Decimal(raw_number)
        except InvalidOperation:
            continue
        if number.is_finite():
            numbers.add(number.normalize())
    return numbers


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")

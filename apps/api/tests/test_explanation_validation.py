from __future__ import annotations

from copy import deepcopy

from fip_api.explainability.validation import validate_case_brief_output


def test_grounding_validator_rejects_unknown_and_duplicate_citations() -> None:
    evidence = {"source.fact": {"value": 42, "status": "review"}}
    candidate = _candidate()
    output, valid = validate_case_brief_output(candidate, evidence)
    assert output is not None
    assert valid.grounding_passed is True

    unknown = deepcopy(candidate)
    unknown["summary_evidence_refs"] = ["source.missing"]
    _, unknown_report = validate_case_brief_output(unknown, evidence)
    assert unknown_report.citations_valid is False
    assert unknown_report.failures[0].code == "unsupported_evidence_reference"

    duplicate = deepcopy(candidate)
    duplicate["summary_evidence_refs"] = ["source.fact", "source.fact"]
    _, duplicate_report = validate_case_brief_output(duplicate, evidence)
    assert duplicate_report.citations_valid is False
    assert duplicate_report.failures[0].code == "duplicate_evidence_reference"


def test_grounding_validator_rejects_schema_failures() -> None:
    output, report = validate_case_brief_output(
        {"summary": "This intentionally omits required structured fields."},
        {"source.fact": {"value": 42}},
    )

    assert output is None
    assert report.schema_valid is False
    assert report.grounding_passed is False
    assert all(failure.code == "schema_invalid" for failure in report.failures)


def _candidate() -> dict[str, object]:
    return {
        "summary": "The supplied evidence contains value 42 and remains under review.",
        "summary_evidence_refs": ["source.fact"],
        "primary_risk_factors": [
            {
                "text": "The supplied fact is marked for review.",
                "evidence_refs": ["source.fact"],
            }
        ],
        "supporting_evidence": [],
        "uncertainties": [],
        "recommended_review_steps": [
            {
                "text": "Review the supplied fact before a human decision.",
                "evidence_refs": ["source.fact"],
            }
        ],
    }

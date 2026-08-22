from __future__ import annotations

from fip_api.core.checksums import canonical_json_checksum
from fip_api.schemas.research_evidence import ResearchEvidenceResponse

RESEARCH_EVIDENCE_SCHEMA_VERSION = "research-model-evidence-v1.0.0"
RESEARCH_EVIDENCE_RUN_ID = "ULB-OPENML-1597-SEED-42"
RECORDED_EVIDENCE_CHECKSUM = "56b73daef711b61a9227a7fa541707d4f85230621bc88ebc0c6143c22a93febe"


def research_evidence_facts() -> dict[str, object]:
    return {
        "schema_version": RESEARCH_EVIDENCE_SCHEMA_VERSION,
        "run_id": RESEARCH_EVIDENCE_RUN_ID,
        "created_at": "2026-08-10T04:17:53.948099Z",
        "dataset": {
            "dataset_id": "openml-1597-v1",
            "display_name": "ULB Credit Card Fraud Detection",
            "source_page": "https://www.openml.org/d/1597",
            "provenance": (
                "Real European card transactions from a Worldline and ULB research collaboration."
            ),
            "observation_period": "Two days of European card transactions from 2013",
            "provider_license": "Public (OpenML dataset metadata)",
            "provider_md5": "178bcf9bb1f31a3dfe12d0e577884add",
            "source_file_sha256": (
                "fdaf12730dc1fc426f318b71349f24f5c5fd00aa1152940be7e7509ae3d89d2a"
            ),
            "row_count": 284_807,
            "positive_count": 492,
            "negative_count": 284_315,
            "prevalence": "0.001727",
            "feature_count": 30,
            "operational_feature_compatible": False,
            "operational_block_reason": (
                "V1 through V28 are undisclosed PCA features that cannot be recreated from the "
                "FIP canonical transaction contract."
            ),
        },
        "partitions": [
            {
                "name": "train",
                "purpose": "Fit candidate estimators without access to later observations.",
                "row_count": 170_888,
                "positive_count": 360,
                "minimum_event_time": 0,
                "maximum_event_time": 120_396,
            },
            {
                "name": "calibration",
                "purpose": "Calibrate candidate probabilities on a later, isolated window.",
                "row_count": 42_717,
                "positive_count": 38,
                "minimum_event_time": 120_397,
                "maximum_event_time": 139_320,
            },
            {
                "name": "validation",
                "purpose": (
                    "Select the candidate and threshold under the false-positive constraint."
                ),
                "row_count": 28_481,
                "positive_count": 42,
                "minimum_event_time": 139_321,
                "maximum_event_time": 151_328,
            },
            {
                "name": "test",
                "purpose": "Measure the selected configuration once on untouched future rows.",
                "row_count": 42_721,
                "positive_count": 52,
                "minimum_event_time": 151_329,
                "maximum_event_time": 172_792,
            },
        ],
        "candidates": [
            {
                "model_key": "logistic-regression",
                "display_name": "Logistic regression",
                "selected": False,
                "validation": {
                    "average_precision": "0.846857",
                    "roc_auc": "0.982447",
                    "brier_score": "0.000431",
                    "expected_calibration_error": "0.000239",
                    "precision": "0.148289",
                    "recall": "0.928571",
                    "f1": "0.255738",
                    "false_positive_rate": "0.007877",
                    "alert_rate": "0.009234",
                    "threshold": "0.0022108461264643037",
                },
            },
            {
                "model_key": "hist-gradient-boosting",
                "display_name": "Histogram gradient boosting",
                "selected": True,
                "validation": {
                    "average_precision": "0.870925",
                    "roc_auc": "0.979986",
                    "brier_score": "0.000408",
                    "expected_calibration_error": "0.000242",
                    "precision": "0.209677",
                    "recall": "0.928571",
                    "f1": "0.342105",
                    "false_positive_rate": "0.005169",
                    "alert_rate": "0.006531",
                    "threshold": "0.00277101602326677",
                },
            },
        ],
        "selected_model": "hist-gradient-boosting",
        "held_out_test": {
            "average_precision": "0.737251",
            "roc_auc": "0.954710",
            "brier_score": "0.000425",
            "expected_calibration_error": "0.000222",
            "precision": "0.188341",
            "recall": "0.807692",
            "f1": "0.305455",
            "false_positive_rate": "0.004242",
            "alert_rate": "0.005220",
            "threshold": "0.00277101602326677",
            "row_count": 42_721,
            "positive_count": 52,
            "true_positives": 42,
            "false_positives": 181,
            "true_negatives": 42_488,
            "false_negatives": 10,
        },
        "explainability": {
            "method": "Validation permutation importance by average-precision decrease",
            "repeats": 3,
            "validation_sample_fraction": "1.0",
            "semantic_limit": (
                "The PCA component names are suitable for research diagnostics, not "
                "human-readable operational reasons."
            ),
            "features": [
                {
                    "feature": "V14",
                    "mean_pr_auc_decrease": "0.189797",
                    "standard_deviation": "0.004590",
                },
                {
                    "feature": "V4",
                    "mean_pr_auc_decrease": "0.079417",
                    "standard_deviation": "0.003184",
                },
                {
                    "feature": "V12",
                    "mean_pr_auc_decrease": "0.026034",
                    "standard_deviation": "0.004172",
                },
                {
                    "feature": "V17",
                    "mean_pr_auc_decrease": "0.015554",
                    "standard_deviation": "0.004017",
                },
                {
                    "feature": "V7",
                    "mean_pr_auc_decrease": "0.012573",
                    "standard_deviation": "0.005266",
                },
                {
                    "feature": "V18",
                    "mean_pr_auc_decrease": "0.006808",
                    "standard_deviation": "0.002631",
                },
                {
                    "feature": "V3",
                    "mean_pr_auc_decrease": "0.005494",
                    "standard_deviation": "0.000157",
                },
                {
                    "feature": "V10",
                    "mean_pr_auc_decrease": "0.004459",
                    "standard_deviation": "0.002865",
                },
                {
                    "feature": "V15",
                    "mean_pr_auc_decrease": "0.003010",
                    "standard_deviation": "0.002350",
                },
                {
                    "feature": "V21",
                    "mean_pr_auc_decrease": "0.002904",
                    "standard_deviation": "0.000584",
                },
            ],
        },
        "reproducibility": {
            "pipeline_version": "fip-research-ml-v1.0.0",
            "random_seed": 42,
            "maximum_validation_false_positive_rate": "0.01",
            "split_contract": "temporal-60-15-10-15-equal-timestamps-v1.0.0",
            "runtime": {
                "python": "3.13.12",
                "numpy": "2.5.2",
                "scikit_learn": "1.9.0",
            },
            "artifacts": {
                "metrics_sha256": (
                    "c5cddde7fcbb74d6078fe6371a12d219787072dde3e7b0cc5275252b9887986d"
                ),
                "model_card_sha256": (
                    "bd18acdfd1df06a59af6fc02e56b7c36a3ba3b8841c569437e54261428ad9393"
                ),
                "model_artifact_sha256": (
                    "75e07dea9004b5fce60ff6531c470bc4e81a09f2672ac7ffac63728a0ed4bf0e"
                ),
                "run_manifest_sha256": (
                    "b948ea97a56afea15f40094d3c6c04e785928c13f552d2eedab5878cc095e061"
                ),
            },
        },
        "claims": {
            "evidence_scope": "research_methodology",
            "research_only": True,
            "real_public_transactions": True,
            "eligible_for_operational_promotion": False,
            "demonstrates_institution_specific_efficacy": False,
            "affects_operational_score": False,
            "triggers_automatic_action": False,
            "statement": (
                "This run demonstrates reproducible model-development methodology on real public "
                "transactions. It does not demonstrate institution-specific operational efficacy."
            ),
        },
        "read_only": True,
        "changes_operational_state": False,
    }


def build_research_evidence_response() -> ResearchEvidenceResponse:
    facts = research_evidence_facts()
    observed_checksum = canonical_json_checksum(facts)
    return ResearchEvidenceResponse.model_validate(
        {
            **facts,
            "evidence_checksum": RECORDED_EVIDENCE_CHECKSUM,
            "integrity_verified": observed_checksum == RECORDED_EVIDENCE_CHECKSUM,
        }
    )

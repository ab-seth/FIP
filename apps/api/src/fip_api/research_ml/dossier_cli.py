from __future__ import annotations

import argparse
import json
from pathlib import Path

from fip_api.research_ml.dossier import CandidateDossierConfig, build_candidate_dossier


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Independently replay a FIP research run and export a governed candidate dossier."
        ),
    )
    parser.add_argument("--input", type=Path, required=True, help="Pinned raw CSV or ARFF path.")
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        required=True,
        help="Reviewed machine-readable provenance and provider-checksum manifest.",
    )
    parser.add_argument(
        "--run",
        type=Path,
        required=True,
        help="Completed research run directory to verify.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New output directory for the checksummed candidate bundle.",
    )
    parser.add_argument("--model-key", required=True, help="Governed registry model key.")
    parser.add_argument("--version", required=True, help="Immutable candidate version.")
    parser.add_argument(
        "--model-card-reference",
        required=True,
        help="Stable repository or evidence-store reference for the verified model card.",
    )
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    dossier = build_candidate_dossier(
        CandidateDossierConfig(
            input_path=arguments.input,
            dataset_manifest_path=arguments.dataset_manifest,
            run_directory=arguments.run,
            output_directory=arguments.output,
            model_key=arguments.model_key,
            version=arguments.version,
            model_card_reference=arguments.model_card_reference,
        )
    )
    registration = dossier["candidate_registration"]
    print(
        json.dumps(
            {
                "output": str(arguments.output),
                "dossier_checksum": dossier["dossier_checksum"],
                "model_key": registration["model_key"],
                "version": registration["version"],
                "purpose": registration["purpose"],
                "operational_feature_compatible": registration["operational_feature_compatible"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

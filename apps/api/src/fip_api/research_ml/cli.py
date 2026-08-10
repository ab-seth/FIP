from __future__ import annotations

import argparse
import json
from pathlib import Path

from fip_api.research_ml.pipeline import ExperimentConfig, run_experiment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train and evaluate FIP research-only fraud models.",
    )
    parser.add_argument(
        "--dataset",
        choices=("ulb-credit-card",),
        default="ulb-credit-card",
        help="Approved research dataset adapter.",
    )
    parser.add_argument("--input", type=Path, required=True, help="Local CSV or ARFF dataset path.")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New output directory for model, metrics, manifest, and model card.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--maximum-fpr", type=float, default=0.01)
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    result = run_experiment(
        ExperimentConfig(
            input_path=arguments.input,
            output_directory=arguments.output,
            seed=arguments.seed,
            maximum_false_positive_rate=arguments.maximum_fpr,
        )
    )
    print(
        json.dumps(
            {
                "output": str(arguments.output),
                "selected_model": result["selected_model"],
                "test": result["test"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

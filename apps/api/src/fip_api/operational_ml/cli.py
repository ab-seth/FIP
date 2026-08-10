from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from fip_api.db.session import SessionLocal
from fip_api.operational_ml.pipeline import (
    OperationalTrainingConfig,
    run_operational_training,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train governed offline FIP operational model candidates.",
    )
    parser.add_argument(
        "--dataset-id",
        required=True,
        help="Operational dataset UUID or display ID",
    )
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--version", required=True, help="Candidate model version")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--maximum-false-positive-rate", type=float, default=0.05)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = OperationalTrainingConfig(
        output_directory=args.output_directory,
        version=args.version,
        seed=args.seed,
        maximum_false_positive_rate=args.maximum_false_positive_rate,
    )
    with SessionLocal() as db:
        evidence = run_operational_training(db, args.dataset_id, config)
    print(
        json.dumps(
            {
                "output_directory": str(config.output_directory),
                "dataset": evidence["dataset"]["id"],
                "supervised_candidate": evidence["supervised"]["selected_model"],
                "anomaly_candidate": evidence["anomaly"]["model"],
                "candidate_only": True,
                "automatic_registration": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

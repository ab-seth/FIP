from __future__ import annotations

from fip_api.db.session import SessionLocal
from fip_api.scoring import backfill_rule_assessments


def main() -> None:
    with SessionLocal() as db:
        created = backfill_rule_assessments(db)
    print(f"Rule assessments created: {created}")


if __name__ == "__main__":
    main()

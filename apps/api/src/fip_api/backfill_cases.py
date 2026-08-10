from sqlalchemy import select

from fip_api.cases import open_case_for_assessment
from fip_api.db.session import SessionLocal
from fip_api.models import AnalystCase, Transaction
from fip_api.scoring import find_current_rule_assessment


def backfill_cases() -> int:
    created = 0
    with SessionLocal() as db:
        transaction_ids_with_cases = set(db.scalars(select(AnalystCase.transaction_id)).all())
        transactions = db.scalars(
            select(Transaction).order_by(
                Transaction.occurred_at,
                Transaction.external_transaction_id,
            )
        ).all()
        for transaction in transactions:
            if transaction.id in transaction_ids_with_cases:
                continue
            result = find_current_rule_assessment(db, transaction.id)
            if result is None:
                continue
            snapshot, assessment = result
            case = open_case_for_assessment(db, transaction, snapshot, assessment)
            if case is not None:
                created += 1
        db.commit()
    return created


def main() -> None:
    created = backfill_cases()
    print(f"Investigation cases created: {created}")


if __name__ == "__main__":
    main()

# Semantic features and deterministic rules

FIP assesses every newly ingested canonical transaction with a rules-only baseline. The assessment
uses operational fields and prior canonical transactions; no public-dataset-specific or synthetic
feature is accepted by the live path.

This output is an investigative signal. It is not a fraud probability, an automated financial
decision, or a substitute for human review.

## Atomic assessment behavior

REST and CSV ingestion create the transaction, immutable feature snapshot, and immutable rule
assessment in one database transaction. A failure in feature extraction or rule evaluation rolls the
entire intake operation back. Replaying an existing intake does not create another snapshot or
assessment.

Transactions stored before this migration can be assessed after `alembic upgrade head` with:

```bash
uv run fip-api-backfill-rule-assessments
```

The backfill is idempotent and evaluates transactions in occurrence-time order.

## Feature contract

Feature set `semantic-transaction-v1.0.0` uses a 30-day account history window. Only transactions
with the same `account_reference` and an `occurred_at` value before the assessed transaction are
eligible. Same-time and future events are excluded.

| Feature | Definition |
| --- | --- |
| `amount`, `currency` | Canonical transaction amount and currency |
| `occurred_hour_utc` | UTC hour, `0` through `23` |
| `occurred_day_of_week_utc` | UTC weekday, Monday `0` through Sunday `6` |
| `is_weekend_utc` | Saturday or Sunday in UTC |
| `is_off_hours_utc` | UTC hour from `00:00` through `04:59` |
| `is_cross_border` | Source and destination are both present and differ; otherwise `null` if either is absent |
| `channel` | Canonical transaction channel |
| `merchant_reference` | Canonical merchant reference |
| `merchant_category_code` | Canonical merchant category code |
| `source_country`, `destination_country` | Canonical transaction countries |
| `prior_transaction_count_1h` | Earlier account transactions in the preceding hour |
| `prior_transaction_count_24h` | Earlier account transactions in the preceding 24 hours |
| `prior_transaction_count_30d` | Earlier account transactions in the 30-day window |
| `prior_same_currency_count_30d` | Earlier account transactions in the same currency |
| `prior_same_currency_median_amount_30d` | Median amount from same-currency history |
| `amount_to_median_ratio_30d` | Current amount divided by that median |
| `merchant_seen_before_30d` | Whether the merchant exists in eligible account history; `null` without a merchant |

The same-currency condition prevents invalid amount comparisons across currencies. FIP does not use
a global value threshold or perform an implicit currency conversion.

## Ruleset

Ruleset `semantic-rules-v1.0.0` contains six transparent signals:

| Rule | Trigger | Points |
| --- | --- | ---: |
| `R001_RAPID_ACCOUNT_ACTIVITY` | At least three earlier account transactions in one hour | 25 |
| `R002_AMOUNT_SPIKE` | At least five same-currency history rows and amount at least five times the median | 25 |
| `R003_NEW_MERCHANT` | At least five history rows and the merchant has not appeared | 15 |
| `R004_CROSS_BORDER_CARD_NOT_PRESENT` | Cross-border and card-not-present | 15 |
| `R005_ELEVATED_REVIEW_MCC` | MCC is `4829`, `6010`, `6011`, `6051`, `6211`, `6540`, or `7995` | 10 |
| `R006_OFF_HOURS_CARD_NOT_PRESENT` | Card-not-present during UTC hours `00:00`–`04:59` | 10 |

An MCC or cross-border transaction is not evidence of fraud by itself. These points only determine
review priority. Every triggered rule returns its exact contribution and supporting feature values.

Risk-band policy `rule-risk-bands-v1.0.0` maps a rules-only score to:

- `low`: 0–39
- `medium`: 40–69
- `high`: 70–100

## Reproducibility records

Each feature snapshot stores its feature-set version, history window, feature values, a checksum of
the exact history facts, and a snapshot checksum. Each assessment stores its ruleset and risk-band
versions, triggered rules, contribution points, rules-only score, level, and assessment checksum.
Checksums use stable external transaction identifiers rather than deployment-specific database UUIDs.

`GET /api/v1/transactions/{transaction_id}/rule-assessment` returns the current assessment and its
feature snapshot to any authenticated FIP role.

## Current limits

- Rules are initial review heuristics and require institutional policy validation before production.
- UTC off-hours are deliberately deterministic but are not a substitute for account-local time.
- The 30-day history is limited to transactions already present when the immutable snapshot is made.
- No supervised model, anomaly detector, public dataset, exchange-rate feed, or automatic case action
  participates in this score. Separately stored shadow-model outputs never modify it.

# Transaction intake

Transaction intake is the canonical boundary between source-specific data and FIP. Institution feeds and public-dataset adapters must map into this contract; downstream scoring modules do not read source-specific columns.

## CSV contract

Files must be UTF-8 CSV documents no larger than 10 MB or 10,000 non-blank transaction rows. The first row must contain unique column names. Unknown columns are rejected so schema drift cannot pass silently.

Required columns:

| Column | Contract |
| --- | --- |
| `external_transaction_id` | Unique source identifier, 1–120 characters |
| `occurred_at` | ISO 8601 date-time with an explicit timezone |
| `amount` | Positive decimal with at most 2 decimal places |
| `currency` | Three-letter currency code |
| `account_reference` | Source account reference, 1–120 characters |

Optional columns:

| Column | Contract |
| --- | --- |
| `merchant_reference` | Merchant reference, at most 120 characters |
| `merchant_category_code` | Merchant category code, at most 12 characters |
| `channel` | `card_present`, `card_not_present`, `atm`, `transfer`, or `other` |
| `source_country` | Two-letter country code |
| `destination_country` | Two-letter country code |

Example:

```csv
external_transaction_id,occurred_at,amount,currency,account_reference,merchant_reference,merchant_category_code,channel,source_country,destination_country
TX-804120,2026-08-03T09:42:00Z,1284.00,USD,ACC-014,MER-091,5734,card_not_present,RW,KE
```

## Import behavior

`POST /api/v1/transactions/upload/validate` validates raw CSV bytes and returns row-specific errors and a three-row preview. It never writes an ingestion batch or transaction.

`POST /api/v1/transactions/upload` repeats validation and commits a valid file in one database transaction. A file with any error stores no rows. The raw file bytes are identified by a SHA-256 checksum; replaying the exact file returns the existing immutable receipt and does not duplicate transactions.

Both endpoints accept the source name through `X-FIP-Filename` and require an analyst or administrator bearer token. The web application proxies these calls so the browser never reads the bearer token.

## REST contract

`POST /api/v1/transactions` ingests one canonical JSON transaction. Replaying the same normalized payload returns the original transaction and receipt. Reusing an external transaction identifier with different data returns `409 Conflict`.

`GET /api/v1/transactions/{transaction_id}` returns a stored canonical transaction to any authenticated FIP role. Intake records have no update or delete endpoints.

An example direct API request:

```bash
curl -X POST http://localhost:8000/api/v1/transactions \
  -H "Authorization: Bearer $FIP_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "external_transaction_id": "TX-804120",
    "occurred_at": "2026-08-03T09:42:00Z",
    "amount": "1284.00",
    "currency": "USD",
    "account_reference": "ACC-014",
    "channel": "card_not_present",
    "source_country": "RW",
    "destination_country": "KE"
  }'
```

The upload limits are configured with `FIP_TRANSACTION_UPLOAD_MAX_BYTES` and `FIP_TRANSACTION_UPLOAD_MAX_ROWS`.

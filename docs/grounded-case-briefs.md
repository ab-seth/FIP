# Grounded case briefs

## Purpose

FIP can turn a case's already verified evidence into a concise, cited review brief. The feature is
decision support only: it does not calculate or change any risk score, set case priority, classify a
case, trigger a transaction action, or create an ML label.

The preferred path calls an explicitly configured JSON-gateway or OpenAI-compatible endpoint. Every
candidate response is validated against a strict schema and deterministic grounding rules before an
analyst can see it. If the provider is absent, unavailable, malformed, or ungrounded, FIP displays a
server-generated deterministic fallback instead. Scoring and the investigation workflow remain
available throughout.

## Evidence contract

The server constructs `grounded-case-brief-evidence-v1.0.0` from the case's pinned transaction,
semantic feature snapshot, and rules assessment. A caller may explicitly add one hybrid assessment
ID. FIP accepts that hybrid evidence only when its rules, feature, transaction, prediction, lifecycle,
artifact, and checksum lineage still verifies.

The provider receives a catalog of individually addressable facts such as:

- `transaction.amount`
- `transaction.occurred_at`
- `rule_assessment.score`
- `rules.<rule_id>`
- `features.<semantic_feature>`
- `hybrid.score` and verified component/factor entries, when explicitly supplied
- limitations establishing human authority and the ban on financial action

Account references and user credentials are not included. The exact sorted evidence catalog and
lineage are SHA-256 checksummed before generation.

## Provider contracts

FIP supports two explicit transport adapters. `json-http` preserves the provider-neutral gateway
contract below. `openai-compatible` translates the same versioned evidence into a non-streaming
chat-completions request with the output schema supplied as `response_format.json_schema`. The
assistant message content is parsed as JSON and then passes through the same deterministic schema,
citation, numerical-claim, and prohibited-action checks as gateway output.

In `json-http` mode, FIP sends an HTTP `POST` request with JSON containing:

```json
{
  "model": "configured-model-name",
  "prompt_version": "grounded-case-brief-v1.0.0",
  "output_schema_version": "grounded-case-brief-output-v1.0.0",
  "response_format": "json",
  "system_instruction": "server-owned safety and grounding instruction",
  "evidence": { "schema_version": "...", "evidence_catalog": {} },
  "response_schema": {}
}
```

The endpoint may return the output object directly or wrap it as `{ "output": { ... } }`. If an API
key is configured, FIP sends it as a bearer token. The provider must return these structured fields:

- `summary` and `summary_evidence_refs`
- `primary_risk_factors`
- `supporting_evidence`
- `uncertainties`
- `recommended_review_steps`

Every list entry has `text` and one or more exact `evidence_refs`.

Configuration:

| Variable | Purpose | Default/control |
| --- | --- | --- |
| `FIP_LLM_ADAPTER` | Transport contract | `json-http`; also supports `openai-compatible`. |
| `FIP_LLM_ENDPOINT` | Provider or internal gateway URL | Empty disables provider calls. |
| `FIP_LLM_API_KEY` | Optional bearer credential | Never returned by the API. |
| `FIP_LLM_MODEL` | Provider model identifier | Required when an endpoint is set. |
| `FIP_LLM_PROVIDER_NAME` | Auditable provider label | `json-http` |
| `FIP_LLM_TIMEOUT_SECONDS` | Hard provider timeout | `8`; maximum `120` |
| `FIP_LLM_MAX_RESPONSE_BYTES` | Maximum response body | `262144`; maximum 1 MiB |
| `FIP_LLM_MAX_COMPLETION_TOKENS` | OpenAI-compatible output ceiling | `1800`; maximum `8192` |

Production configuration requires HTTPS.

`GET /api/v1/explanations/provider-status` exposes authenticated, non-secret configuration facts
for the case dossier. It never returns the endpoint or API key and deliberately does not perform a
network call. Availability is established only when a user requests a brief; a connection or model
failure follows the existing deterministic-fallback path.

## Grounding and failure behavior

FIP rejects a provider candidate when any of these controls fail:

1. The JSON does not match the strict output schema or contains extra fields.
2. A citation is missing, duplicated within a claim, or absent from the supplied catalog.
3. A narrative contains a numerical value that is not present in its cited evidence entries.
4. A narrative declares fraud proven or recommends a prohibited consequential action such as
   freezing an account or declining a transaction.

Only a fully validated candidate receives generation mode `llm`. Otherwise the visible result is a
freshly validated `deterministic_fallback` built from the same evidence. The validation report keeps
the candidate failure reason for audit, while rejected provider output is not exposed by the API.

The deterministic fallback is not represented as AI output. A fallback produced during a transient
provider failure is replay-stable for the same evidence, prompt, provider, and model; changing one of
those versioned inputs creates a new immutable brief.

## Immutability and audit

Each brief stores the prompt and schema versions, exact input evidence, upstream evidence checksums,
provider and model labels, accepted or fallback output, validation report, latency, requester, and
creation time. An explanation checksum covers all of those facts. Reads reconstruct the evidence,
re-run grounding validation, verify upstream evidence, and expose `integrity_verified`.

A newly created brief also appends `brief_generated` to the case's hash-chained decision ledger.
Replaying the same request returns the existing brief and does not append a second event.

## API and roles

| Method | Endpoint | Roles | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/cases/{case_id}/briefs` | Any authenticated role | Read immutable brief versions and integrity state. |
| `POST` | `/api/v1/cases/{case_id}/briefs` | Administrator, analyst | Generate or replay a brief for rules-only evidence or one explicit hybrid assessment. |

POST body:

```json
{ "hybrid_assessment_id": null }
```

Use an actual assessment ID to ground the brief in verified hybrid evidence. FIP intentionally does
not select a hidden "latest" hybrid record inside the API.

## Current limitations

- The built-in adapters cover the generic JSON gateway and OpenAI-compatible chat completions.
  Other authentication schemes and provider-specific protocols require separately tested adapters.
- Citation validation proves that statements reference supplied evidence and that numerical claims
  occur in those entries. It is not a general natural-language entailment proof.
- Case briefs do not retrieve external documents, customer profiles, sanctions data, or web content.
- Provider output may contain sensitive transaction context; operators must select an approved
  deployment and data-processing boundary before enabling an endpoint.

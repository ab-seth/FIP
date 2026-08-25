# Local Qwen with LM Studio

FIP can generate grounded case briefs with a Qwen model served locally by LM Studio. This connection
uses LM Studio's OpenAI-compatible `POST /v1/chat/completions` endpoint and JSON-schema structured
output. The model remains an explanation provider only: its result cannot change a risk score,
classify a case, register a model, or trigger a financial action.

## 1. Start and inspect LM Studio

Load the intended Qwen instruct model in LM Studio and start the local server from the Developer
tab. LM Studio normally listens on port `1234`. Confirm the exact model identifier:

```bash
curl http://localhost:1234/v1/models
```

Use the returned model `id` exactly as `FIP_LLM_MODEL`. Structured output works best with an instruct
model of at least 7B parameters; the deployed model still has to follow FIP's strict brief schema and
grounding rules.

## 2. Configure FIP

When the API runs in Docker on the same machine as LM Studio, add these values to `.env`:

```dotenv
FIP_LLM_ADAPTER=openai-compatible
FIP_LLM_ENDPOINT=http://host.docker.internal:1234/v1/chat/completions
FIP_LLM_MODEL=<exact-model-id-from-lm-studio>
FIP_LLM_PROVIDER_NAME=lm-studio
FIP_LLM_TIMEOUT_SECONDS=60
FIP_LLM_MAX_COMPLETION_TOKENS=1800
```

For an API process running directly on the host, use
`http://localhost:1234/v1/chat/completions` instead. The adapter also accepts a base ending in `/v1`
and appends `/chat/completions`.

LM Studio must accept the API container's connection. On macOS or Windows this generally means
enabling **Serve on Local Network** in LM Studio; the Compose service resolves
`host.docker.internal` to the host. Do not enable browser CORS for this server-to-server connection.
Keep the service restricted to the local machine/network. If LM Studio authentication is enabled,
export it as `LM_API_TOKEN` before starting Compose; Compose maps that value into the API container
without writing the token to `.env`. `FIP_LLM_API_KEY` remains the direct configuration alternative.

```bash
export LM_API_TOKEN="<local-token>"
docker compose up --build
```

Do not add the token to a tracked file or paste it into logs.

Restart the API after changing configuration. If the token is already exported, this is sufficient:

```bash
docker compose up --build
```

## 3. Verify in FIP

An authenticated case dossier now shows one of three states above the brief:

- **Local AI configured**: local OpenAI-compatible configuration is present;
- **AI provider configured**: a non-local endpoint is configured; or
- **Deterministic explanation mode**: no model endpoint is configured.

This indicator reports configuration, not a background connection probe. Open a case and select
**Generate cited AI brief** to exercise the real provider. FIP then:

1. builds and checksums the verified case evidence;
2. sends the server-owned instruction, evidence document, and strict JSON schema;
3. rejects malformed, truncated, uncited, numerically unsupported, or action-taking output;
4. displays a validated AI brief only when every control passes; and
5. otherwise stores the failure evidence and displays a grounded deterministic fallback.

The immutable brief records `lm-studio`, the exact Qwen model identifier, generation latency,
validation result, evidence checksum, and explanation checksum. The provider-status API never
returns the configured endpoint or credential.

## Source compatibility

The implementation follows LM Studio's documented OpenAI-compatible chat-completions and structured
output contracts:

- <https://lmstudio.ai/docs/developer/openai-compat>
- <https://lmstudio.ai/docs/developer/openai-compat/structured-output>

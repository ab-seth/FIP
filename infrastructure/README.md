# Infrastructure

The MVP uses Docker-compatible service images and PostgreSQL. `compose.yaml` is the authoritative local environment. Cloud-specific deployment manifests will be added only after the managed hosting provider is selected.

No Kubernetes, Kafka, or vector database is required for the MVP.

## Authentication boundary

The browser posts credentials only to the Next.js server. That server calls the FastAPI authentication endpoint and stores the returned token in an `HttpOnly`, `SameSite=Lax` session cookie. `FIP_API_URL` is therefore server-only and should point to the internal API address in deployed environments. Local HTTP sets `FIP_COOKIE_SECURE=false`; any externally reachable environment must use TLS and set it to `true`.

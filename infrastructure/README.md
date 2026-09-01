# Infrastructure

The MVP uses Docker-compatible service images and PostgreSQL. `compose.yaml` is the authoritative local environment. The selected demonstration topology uses Vercel for the web application, a Render Blueprint for the API, Neon PostgreSQL, Cloudflare R2 for immutable artifacts and encrypted backups, and GitHub Actions for controlled automation.

No Kubernetes, Kafka, or vector database is required for the MVP.

The complete environment separation, secret inventory, first-deploy sequence, worker procedure,
backup controls, monitoring alerts and production-promotion gates are defined in
[`../docs/secure-cloud-deployment.md`](../docs/secure-cloud-deployment.md). The root `render.yaml`
creates staging only; it must not be used to claim an always-on production service.

## Authentication boundary

The browser posts credentials only to the Next.js server. That server calls the FastAPI authentication endpoint and stores the returned token in an `HttpOnly`, `SameSite=Lax` session cookie. `FIP_API_URL` is therefore server-only and should point to the internal API address in deployed environments. Local HTTP sets `FIP_COOKIE_SECURE=false`; any externally reachable environment must use TLS and set it to `true`.

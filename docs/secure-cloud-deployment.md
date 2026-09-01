# Secure cloud deployment

This runbook deploys a public **demonstration/staging** environment without changing FIP's human
decision boundary. It is not authorization to process cardholder data, personal financial data, or
live financial decisions. The free services described here have no production service-level
commitment; production promotion requires the controls in [Production promotion](#production-promotion).

## Deployed topology

| Boundary | Staging service | Responsibility |
| --- | --- | --- |
| Browser application | Vercel | Next.js server, `HttpOnly` session cookie, managed HTTPS |
| Transaction and evidence API | Render | FastAPI container, authentication, scoring, evidence and health endpoints |
| Relational evidence | Neon | TLS-protected PostgreSQL |
| Immutable binary evidence | Cloudflare R2 | Model artifacts, candidate bundles and encrypted database backups |
| Automation | GitHub Actions | CI, security checks, migrations, deploy hooks, one-shot workers and backups |
| Observability | Render log stream plus Grafana Cloud | Structured request events, availability, latency and error monitoring |

The API's local artifact directories are caches only when `FIP_ARTIFACT_STORE=s3`. Every executable
model is rechecked against its registered SHA-256 digest after retrieval. Candidate bundles are
downloaded as a fixed file set and pass the existing manifest, evidence and checksum verification
before use.

## 1. Create isolated staging resources

Create resources with names that cannot be mistaken for production:

1. A Neon project or branch named `fip-staging`.
2. An R2 Standard bucket named `fip-staging-artifacts`.
3. An R2 API token limited to object read/write for that bucket only.
4. A Render Blueprint connected to this repository's root `render.yaml`.
5. A Vercel project connected to `apps/web` in this monorepo.
6. A GitHub Environment named `staging`.

Copy the Neon pooled connection string and retain its TLS parameters. FIP's SQLAlchemy setting uses
the `postgresql+psycopg://` scheme. The backup-only connection uses the standard `postgresql://`
scheme because it is consumed directly by `pg_dump`.

Configure an R2 lifecycle rule after backup retention is agreed. A practical demonstration policy is
seven daily backups and four weekly retained copies. Lifecycle configuration belongs to the bucket,
not the application repository.

## 2. Configure the Render API

Create the Blueprint from `render.yaml`. Render prompts for every `sync: false` value:

| Variable | Value |
| --- | --- |
| `FIP_DATABASE_URL` | Neon TLS URL with the SQLAlchemy `postgresql+psycopg://` scheme |
| `FIP_CORS_ORIGINS` | JSON array containing only the final Vercel URL, for example `["https://fip-demo.vercel.app"]` |
| `FIP_OBJECT_STORE_ENDPOINT` | R2 S3 endpoint, `https://<account-id>.r2.cloudflarestorage.com` |
| `FIP_OBJECT_STORE_BUCKET` | `fip-staging-artifacts` |
| `FIP_OBJECT_STORE_ACCESS_KEY_ID` | Bucket-scoped R2 access key ID |
| `FIP_OBJECT_STORE_SECRET_ACCESS_KEY` | Bucket-scoped R2 secret access key |

Render generates the staging JWT signing secret. The Blueprint deliberately disables automatic
deploys; GitHub triggers a deploy only after the Security workflow succeeds on `main`.

After Render assigns the API hostname, update `FIP_TRUSTED_HOSTS` if the hostname differs from
`fip-api-staging.onrender.com`. Add custom API domains to this list before sending traffic to them.

## 3. Configure the Vercel web application

Import the repository, set the project Root Directory to `apps/web`, and enable inclusion of source
files outside the Root Directory because the web application consumes `packages/contracts`.
`apps/web/vercel.json` supplies the monorepo install/build commands and a bounded server-function
duration for Render cold starts.

Set these Vercel Production and Preview variables:

| Variable | Value |
| --- | --- |
| `FIP_API_URL` | The HTTPS Render API origin, with no trailing slash |
| `FIP_COOKIE_SECURE` | `true` |

The browser continues to call same-origin Next.js routes. The Next.js server calls the Render API,
and the bearer token remains inside an `HttpOnly`, `SameSite=Lax`, secure cookie.

## 4. Configure the GitHub staging environment

Add these environment secrets under **Settings → Environments → staging**:

| Secret | Consumer |
| --- | --- |
| `FIP_DATABASE_URL` | migrations and one-shot workers; SQLAlchemy scheme |
| `FIP_BACKUP_DATABASE_URL` | `pg_dump`; standard PostgreSQL scheme and least-privilege backup role |
| `FIP_JWT_SECRET` | validates staging configuration in automation; 32+ random characters |
| `FIP_BOOTSTRAP_ADMIN_USERNAME` | first administrator creation |
| `FIP_BOOTSTRAP_ADMIN_PASSWORD` | first administrator creation; replace after first sign-in |
| `FIP_OBJECT_STORE_ENDPOINT` | worker and backup R2 endpoint |
| `FIP_OBJECT_STORE_BUCKET` | worker and backup R2 bucket |
| `FIP_OBJECT_STORE_ACCESS_KEY_ID` | bucket-scoped R2 access key |
| `FIP_OBJECT_STORE_SECRET_ACCESS_KEY` | bucket-scoped R2 secret key |
| `FIP_BACKUP_ENCRYPTION_KEY` | random high-entropy key stored separately from backup objects |
| `RENDER_DEPLOY_HOOK_URL` | Render API deploy hook |
| `VERCEL_DEPLOY_HOOK_URL` | optional Vercel deploy hook; omit when Git integration deploys `main` |
| `FIP_LOAD_USERNAME` | dedicated read-only load-test account |
| `FIP_LOAD_PASSWORD` | dedicated read-only load-test password |

Generate random material locally without printing it into a shared terminal transcript:

```bash
openssl rand -base64 48
```

Treat any credential pasted into chat, committed, or included in shell history as disclosed and
rotate it before deployment.

## 5. First deployment

The first Render Blueprint sync can start the API before the schema has been initialized. After all
GitHub staging secrets and deploy hooks exist, run **Deploy staging** manually once. The workflow:

1. installs the locked API dependencies;
2. applies every Alembic migration to Neon;
3. creates the first administrator idempotently;
4. calls the Render deploy hook; and
5. optionally calls the Vercel deploy hook.

Verify both health contracts:

```bash
curl --fail https://<api-host>/health
curl --fail https://<api-host>/api/v1/health/ready
```

Then sign in through the Vercel URL and immediately change the bootstrap password through the
approved account-management process. Remove `FIP_BOOTSTRAP_ADMIN_USERNAME` and
`FIP_BOOTSTRAP_ADMIN_PASSWORD` from the GitHub environment after successful provisioning.

## 6. Workers, backups and verification

- Queue candidate training in the FIP UI, then dispatch **Governed worker → training**. It processes
  at most one queued run, uploads the verified bundle to R2 and exits.
- Queue a benchmark, then dispatch **Governed worker → benchmark**. It processes at most one run and
  exits.
- **Encrypted database backup** runs nightly and can also be dispatched manually. It creates a
  PostgreSQL custom-format dump, encrypts it before upload, records a SHA-256 checksum, and removes
  the plaintext dump from the runner.
- **Authorized load test** is manual and bounded. Use only an owned endpoint whose hosting terms
  permit load testing. Never target Vercel Hobby.
- **Authorized dynamic security test** runs an OWASP ZAP baseline only after ownership is confirmed.
- **Security** audits Python and JavaScript dependencies and scans the repository and both container
  images for high/critical vulnerabilities, configuration errors and disclosed secrets.

Perform a restore drill into a disposable Neon branch, never into staging or production. Download
one encrypted dump, verify its companion checksum, decrypt it locally and restore with PostgreSQL 17
`pg_restore`. Record the backup object key, restoration result and checksum in the operational
evidence record. Delete the disposable branch after verification.

## 7. Monitoring

Send Render request logs to the selected Grafana Cloud stack. FIP emits one structured `fip.http`
event per request with request ID, method, path, response status and server duration. Do not export
authorization headers, cookies, database URLs or request bodies.

Create alerts for:

- readiness failures for two consecutive checks;
- five-minute 5xx rate above 2%;
- p95 API latency above two seconds outside a documented cold start;
- backup workflow failure or no successful backup within 26 hours;
- failed worker execution; and
- failed Security workflow on `main`.

## Production promotion

Do not relabel the free staging topology as production. Production requires all of the following:

1. Separate Vercel/Render services, Neon project, R2 bucket or prefix, credentials and GitHub
   Environment. Staging credentials must have no production access.
2. Always-on paid API compute and paid background workers, or an approved managed job runner.
3. A paid PostgreSQL recovery window plus independently encrypted backups and a successful restore
   drill.
4. A Render pre-deploy migration command or equivalent release job, rather than migrations in an
   application replica.
5. Central alerts, an incident owner, rollback procedure, key-rotation procedure and defined
   recovery objectives.
6. Domain-specific privacy, retention and regulatory review before any real financial data enters
   the system.
7. A manually approved, immutable release reference. Production deploys must use a reviewed tag or
   image digest, not an unreviewed branch head.

FIP remains decision support. Deployment does not authorize the system, an LLM, or an ML model to
decline transactions, freeze accounts, file reports, or make final fraud classifications.

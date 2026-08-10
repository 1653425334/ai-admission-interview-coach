# AI Admission Interview Coach — Milestone 1

Milestone 1 provides the foundation for an admission-interview coach: Supabase email/password sign-in, owned application targets, and secure CV/personal-statement uploads.

It deliberately **only validates and stores text-based PDFs**. It does **not** parse or analyze the documents, call an LLM, create public URLs, or expose uploaded text. A successful document stays in the `UPLOADED` state.

## Prerequisites (Windows, no Docker)

- Windows PowerShell 7 or Windows PowerShell.
- [PostgreSQL 17](https://www.postgresql.org/download/windows/) including `psql`; add its `bin` directory to `PATH` if the installer did not do so.
- Python 3.12 and [uv](https://docs.astral.sh/uv/).
- Node.js 22 LTS or newer with Corepack enabled (`corepack enable`), then pnpm 11 (`corepack prepare pnpm@11.9.0 --activate`).
- A Supabase project for browser authentication and private object storage.

From the repository root, install the project dependencies:

```powershell
uv sync --project apps/api --all-groups
pnpm install
```

### PostgreSQL 17

The default Windows service installed by PostgreSQL 17 is commonly named `postgresql-x64-17`. Confirm the exact name on this machine, then start or stop it from an elevated PowerShell:

```powershell
Get-Service *postgres*
Start-Service postgresql-x64-17
Stop-Service postgresql-x64-17
```

Create an application role with no server-administration privileges and two dedicated databases. Replace only the angle-bracket placeholders; do not put an actual password in source control. Run the following in `psql` as the local PostgreSQL administrator:

```powershell
psql -U postgres -d postgres
```

```sql
CREATE ROLE admission_coach_app LOGIN PASSWORD '<choose-a-local-password>'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

CREATE DATABASE admission_coach OWNER postgres;
CREATE DATABASE admission_coach_test OWNER postgres;

\connect admission_coach
REVOKE ALL ON DATABASE admission_coach FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE admission_coach TO admission_coach_app;
GRANT USAGE, CREATE ON SCHEMA public TO admission_coach_app;

\connect admission_coach_test
REVOKE ALL ON DATABASE admission_coach_test FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE admission_coach_test TO admission_coach_app;
GRANT USAGE, CREATE ON SCHEMA public TO admission_coach_app;
```

The role can connect and create the tables/indexes it owns in these two databases, but cannot create roles or databases and is not a superuser. The test database is intentionally separate because migration/integration tests upgrade and downgrade its schema.

## Environment configuration

Create the root API environment file and fill in the placeholders locally:

```powershell
Copy-Item .env.example .env
```

`DATABASE_URL` points at `admission_coach`; `TEST_DATABASE_URL` must point at the isolated `admission_coach_test` database. `WEB_ORIGIN` is the single browser origin allowed by the API. The `SUPABASE_*` values are server-only FastAPI configuration, while the `NEXT_PUBLIC_*` values are browser-safe configuration.

The following values are required. `.env.example` contains only placeholders and must remain secret-free.

| Variable | Used by | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | API/Alembic | Development PostgreSQL URL |
| `TEST_DATABASE_URL` | API integration tests | Dedicated `admission_coach_test` URL |
| `WEB_ORIGIN` | API | Allowed web origin |
| `SUPABASE_URL` | API | Supabase project URL for JWT validation/storage |
| `SUPABASE_JWT_AUDIENCE` | API | Usually `authenticated` |
| `SUPABASE_STORAGE_BUCKET` | API | Private bucket name, e.g. `application-documents` |
| `SUPABASE_SERVICE_ROLE_KEY` | API only | Prefer the current `sb_secret_...` server key; the legacy `service_role` JWT also works. Never expose either value or prefix it `NEXT_PUBLIC_` |
| `NEXT_PUBLIC_SUPABASE_URL` | Web | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Web | Browser publishable/anon key, never the service-role key |
| `NEXT_PUBLIC_API_BASE_URL` | Web | FastAPI base URL, normally `http://localhost:8000` |

Next.js reads its local environment file from its application directory. Create `apps/web/.env.local` with only the three `NEXT_PUBLIC_*` entries above (the same public values from root `.env`); do not copy the server secret into that file.

## Supabase setup

1. In **Authentication → Providers**, enable Email and configure email/password sign-in for the local project. Create two test users (A and B), completing email confirmation if the project requires it.
2. In **Storage**, create the bucket named by `SUPABASE_STORAGE_BUCKET` and keep it **private**. Do not make the bucket public.
3. Copy the project URL to both Supabase URL variables. Put the publishable key only in `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`. Put a current `sb_secret_...` key only in the root API `.env` as `SUPABASE_SERVICE_ROLE_KEY`; a legacy `service_role` JWT remains supported during migration.

The server secret bypasses Storage access controls and is used only by FastAPI after it has verified the caller's JWT and ownership. It must never be committed, sent to the browser, logged, or used as a publishable key.

## Migrate and run

Apply the schema to the development database:

```powershell
Push-Location apps/api
uv run alembic upgrade head
Pop-Location
```

Run FastAPI in one terminal:

```powershell
Push-Location apps/api
uv run uvicorn app.main:app --reload
Pop-Location
```

`http://localhost:8000/api/v1/health` should return `{"status":"ok"}`.

Run the durable material-analysis worker in a second API terminal:

```powershell
Push-Location apps/api
uv run python -m app.workers.run_analysis_worker
Pop-Location
```

The worker uses the same root `.env` as FastAPI, so it requires a migrated
`DATABASE_URL` and valid private Supabase Storage settings. It intentionally
uses the offline Fake LLM in M2, so this local workflow does not make a model
or network call beyond reading the already-private uploaded PDFs from Storage.
Keep this process running while testing the analysis UI. For a one-job smoke
test, use `uv run python -m app.workers.run_analysis_worker --once`.

Run the web app in another terminal:

```powershell
pnpm --filter web dev
```

Open `http://localhost:3000`, sign in, and create an application before uploading a CV or PS. Each upload must be a text-based PDF, no larger than 10 MB and no more than 30 pages. Scanned, encrypted, malformed, oversized, and over-length PDFs are rejected. The API also applies a 10 MB plus 64 KiB ingress cap to the whole multipart request before it is spooled; this transport cap permits multipart boundaries and form headers, while the route remains the exact 10 MB file-size authority.

## Verification

Run API tests and coverage (this uses the dedicated test database and returns it to the base migration):

```powershell
uv run --project apps/api pytest apps/api/tests -v --cov=app --cov-report=term-missing
```

Run the focused PostgreSQL acceptance journey separately if needed:

```powershell
uv run --project apps/api pytest apps/api/tests/api/test_milestone_one_journey.py -v
```

Run web checks:

```powershell
pnpm --filter web test -- --run
pnpm --filter web lint
pnpm --filter web exec tsc --noEmit
$env:NEXT_PUBLIC_SUPABASE_URL = "https://example.supabase.co"
$env:NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY = "test-publishable-key"
$env:NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000"
pnpm --filter web build
```

If a `pnpm` shim cannot resolve correctly from a Chinese/non-ASCII repository path, invoke the checked-in workspace binaries directly instead:

```powershell
node .\apps\web\node_modules\vitest\vitest.mjs --run --config .\apps\web\vitest.config.ts
node .\apps\web\node_modules\eslint\bin\eslint.js .\apps\web
node .\apps\web\node_modules\typescript\bin\tsc --noEmit -p .\apps\web\tsconfig.json
node .\apps\web\node_modules\next\dist\bin\next build .\apps\web
```

To exercise the migration round-trip manually, run `upgrade`, `downgrade`, then `upgrade` for development. Finish with development at `head`; finish the test database at `base`.

```powershell
Push-Location apps/api
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
Pop-Location
```

Finally check whitespace and the worktree:

```powershell
git diff --check
git status --short
```

## Manual cloud/browser acceptance checklist

Run this only after supplying a real Supabase project URL and keys. It is intentionally not performed against placeholder or dummy credentials.

- [ ] Sign in as user A with email/password, create an application, upload one CV and one PS, then refresh; both metadata entries remain visible.
- [ ] Confirm the API response and page never reveal a storage key, public URL, or extracted text.
- [ ] In the Supabase dashboard, confirm the bucket remains private and contains the two original objects only.
- [ ] Sign in as user B and open user A's application URL; it must show a not-found result and B must not be able to delete either document.
- [ ] Sign back in as A, delete the CV, refresh, and confirm its upload slot is available and the private storage object is gone.

No live Supabase/browser A/B claim should be made until this checklist is completed with valid cloud credentials. The local acceptance test covers the corresponding ownership, persistence, metadata-redaction, and deletion behavior using real PostgreSQL plus a fake storage boundary.

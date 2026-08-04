# Milestone 1 Foundation and Secure Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a locally runnable Next.js/FastAPI foundation in which an authenticated user can create an application and securely upload or delete owned CV/PS text PDFs.

**Architecture:** The Next.js App Router frontend uses Supabase only for authentication and calls FastAPI for all domain operations. FastAPI validates Supabase JWTs, persists applications and document metadata in PostgreSQL, and stores original PDFs behind an `ObjectStorage` interface whose production implementation uses a private Supabase Storage bucket. This milestone stops after secure upload; parsing and LLM calls begin in Milestone 2.

**Tech Stack:** Next.js App Router, TypeScript, Tailwind CSS, pnpm, Vitest, FastAPI, Python 3.12, uv, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL, PyJWT, pypdf, pytest, HTTPX, Supabase Auth and Storage.

## Global Constraints

- Accept only `CV` and `PS` document types.
- Accept only text-based PDF files; each file is limited to 10 MB and 30 pages.
- Store original files in a private bucket and persist storage keys, never public URLs.
- Route every domain operation through FastAPI; the web app may use Supabase directly only for authentication.
- Verify resource ownership on every application and document operation.
- Exclude full CV/PS text and full prompts from routine logs and error trackers.
- Use UUID primary keys and UTC `timestamptz` timestamps.
- Do not add parsing, LLM calls, interview behavior, reports, OCR, RAG, Redis, Celery, or LangChain in this milestone.

---

## File Map

### Repository and local infrastructure

- `.gitignore` — ignores dependency, build, cache, environment, and coverage artifacts.
- `.env.example` — documents required public and server-only environment variables without secrets.
- `package.json` — root pnpm scripts for the web app.
- `pnpm-workspace.yaml` — declares the web workspace.
- `infra/docker-compose.yml` — provides only local PostgreSQL for development and integration tests.
- `README.md` — contains exact local setup, migration, test, and run commands.

### Web application

- `apps/web/src/app/layout.tsx` — root layout.
- `apps/web/src/app/page.tsx` — redirects authenticated users to applications and others to sign-in.
- `apps/web/src/app/(auth)/sign-in/page.tsx` — email/password sign-in form.
- `apps/web/src/app/(dashboard)/applications/page.tsx` — application list and creation form.
- `apps/web/src/app/(dashboard)/applications/[id]/page.tsx` — application detail and document upload UI.
- `apps/web/src/components/document-upload-form.tsx` — CV/PS upload form and client-side file checks.
- `apps/web/src/lib/api/client.ts` — authenticated FastAPI client and typed error handling.
- `apps/web/src/lib/supabase/client.ts` — browser Supabase client.
- `apps/web/src/lib/supabase/server.ts` — server Supabase client.
- `apps/web/src/types/api.ts` — Milestone 1 API response types.
- `apps/web/src/**/*.test.tsx` — focused UI tests.

### API application

- `apps/api/app/main.py` — FastAPI factory, middleware, and router registration.
- `apps/api/app/core/config.py` — validated environment settings.
- `apps/api/app/core/errors.py` — stable API error envelope and exception handlers.
- `apps/api/app/core/security.py` — JWT validation and `AuthPrincipal` dependency.
- `apps/api/app/db/base.py` — SQLAlchemy declarative base.
- `apps/api/app/db/session.py` — engine and request-scoped session dependency.
- `apps/api/app/db/models/profile.py` — authenticated user profile row.
- `apps/api/app/db/models/application.py` — owned application target.
- `apps/api/app/db/models/document.py` — stored file metadata and parse status.
- `apps/api/app/schemas/application.py` — application request/response models.
- `apps/api/app/schemas/document.py` — document response models and enums.
- `apps/api/app/services/applications.py` — application ownership and CRUD operations.
- `apps/api/app/services/pdf_validation.py` — signature, size, page-count, and text-layer checks.
- `apps/api/app/storage/base.py` — storage protocol and stored-object result.
- `apps/api/app/storage/supabase.py` — private Supabase bucket adapter.
- `apps/api/app/api/routes/health.py` — health endpoint.
- `apps/api/app/api/routes/applications.py` — application endpoints.
- `apps/api/app/api/routes/documents.py` — upload and delete endpoints.
- `apps/api/alembic/` — migration environment and revisions.
- `apps/api/tests/` — unit and PostgreSQL-backed integration tests.

---

### Task 1: Bootstrap the repository and health checks

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `package.json`
- Create: `pnpm-workspace.yaml`
- Create: `apps/web/package.json`
- Create: `apps/web/src/app/layout.tsx`
- Create: `apps/web/src/app/page.tsx`
- Create: `apps/web/vitest.config.ts`
- Create: `apps/web/src/test/setup.ts`
- Create: `apps/web/src/app/page.test.tsx`
- Create: `apps/api/pyproject.toml`
- Create: `apps/api/app/__init__.py`
- Create: `apps/api/app/main.py`
- Create: `apps/api/app/api/routes/health.py`
- Create: `apps/api/tests/test_health.py`

**Interfaces:**
- Produces: `create_app() -> FastAPI` in `app.main`.
- Produces: `GET /api/v1/health -> {"status": "ok"}`.
- Produces: root web page with product name and no domain functionality.

- [ ] **Step 1: Create the Python project and failing health test**

Run:

```bash
uv init --app apps/api
uv add --project apps/api fastapi "uvicorn[standard]" pydantic-settings sqlalchemy alembic "psycopg[binary]" "pyjwt[crypto]" httpx python-multipart pypdf
uv add --project apps/api --dev pytest pytest-asyncio pytest-cov
```

```python
# apps/api/tests/test_health.py
from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_ok() -> None:
    response = TestClient(create_app()).get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the API test and verify it fails**

Run: `uv run --project apps/api pytest apps/api/tests/test_health.py -v`  
Expected: FAIL because `app.main.create_app` does not exist.

- [ ] **Step 3: Implement the minimal FastAPI factory and route**

```python
# apps/api/app/api/routes/health.py
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

```python
# apps/api/app/main.py
from fastapi import FastAPI

from app.api.routes.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="AI Admission Interview Coach API")
    app.include_router(health_router, prefix="/api/v1")
    return app


app = create_app()
```

- [ ] **Step 4: Run the API test and verify it passes**

Run: `uv run --project apps/api pytest apps/api/tests/test_health.py -v`  
Expected: PASS.

- [ ] **Step 5: Scaffold the web app and add a smoke test**

Generate the app and install the required capability dependencies:

```bash
pnpm create next-app@latest apps/web --ts --tailwind --eslint --app --src-dir --use-pnpm --import-alias "@/*"
pnpm --dir apps/web add @supabase/ssr @supabase/supabase-js
pnpm --dir apps/web add -D vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event
```

Configure Vitest with jsdom and Testing Library. The initial page must render `AI Admission Interview Coach`.

```tsx
// apps/web/src/app/page.test.tsx
import { render, screen } from "@testing-library/react";
import Home from "./page";

it("renders the product name", () => {
  render(<Home />);
  expect(screen.getByRole("heading", { name: "AI Admission Interview Coach" })).toBeInTheDocument();
});
```

Run: `pnpm --filter web test -- --run`  
Expected: PASS after the minimal page and test configuration exist.

- [ ] **Step 6: Add root configuration and commit**

`.env.example` must list `DATABASE_URL`, `WEB_ORIGIN`, `SUPABASE_URL`, `SUPABASE_JWT_AUDIENCE`, `SUPABASE_STORAGE_BUCKET`, `SUPABASE_SERVICE_ROLE_KEY`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, and `NEXT_PUBLIC_API_BASE_URL` with empty values.

Run: `git status --short` and verify that no `.env`, `.venv`, `node_modules`, or build output is tracked.

```bash
git add .gitignore .env.example package.json pnpm-workspace.yaml pnpm-lock.yaml apps/web apps/api
git commit -m "chore: bootstrap web and API applications"
```

### Task 2: Add validated configuration and the PostgreSQL schema

**Files:**
- Create: `infra/docker-compose.yml`
- Create: `apps/api/app/core/config.py`
- Create: `apps/api/app/db/base.py`
- Create: `apps/api/app/db/session.py`
- Create: `apps/api/app/db/models/profile.py`
- Create: `apps/api/app/db/models/application.py`
- Create: `apps/api/app/db/models/document.py`
- Create: `apps/api/app/db/models/__init__.py`
- Create: `apps/api/alembic.ini`
- Create: `apps/api/alembic/env.py`
- Create: `apps/api/alembic/versions/0001_profiles_applications_documents.py`
- Create: `apps/api/tests/test_migrations.py`

**Interfaces:**
- Produces: `Settings` and cached `get_settings() -> Settings`.
- Produces: `get_db() -> Iterator[Session]`.
- Produces: SQLAlchemy models `Profile`, `Application`, and `Document` matching the approved schema subset.

- [ ] **Step 1: Write the migration smoke test**

```python
# apps/api/tests/test_migrations.py
from sqlalchemy import create_engine, inspect


def test_head_migration_creates_milestone_one_tables(migrated_database_url: str) -> None:
    tables = set(inspect(create_engine(migrated_database_url)).get_table_names())
    assert {"profiles", "applications", "documents"} <= tables
```

The `migrated_database_url` fixture must run `alembic upgrade head` against the dedicated test database configured by `TEST_DATABASE_URL`.

- [ ] **Step 2: Start PostgreSQL and verify the test fails**

Run: `docker compose -f infra/docker-compose.yml up -d db`  
Run: `uv run --project apps/api pytest apps/api/tests/test_migrations.py -v`  
Expected: FAIL because the migration environment and tables do not exist.

- [ ] **Step 3: Implement settings, engine, models, and migration**

Use native PostgreSQL UUID and JSON-compatible types. `Document.document_type` has a check constraint limiting values to `CV` and `PS`; `parse_status` is limited to `UPLOADED`, `PARSING`, `PARSED`, and `FAILED`. Foreign keys use `ON DELETE CASCADE`.

```python
# apps/api/app/core/config.py
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    web_origin: str = "http://localhost:3000"
    supabase_url: str
    supabase_jwt_audience: str = "authenticated"
    supabase_storage_bucket: str = "application-documents"
    supabase_service_role_key: str
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

The initial migration must create the index `ix_applications_user_created` on `(user_id, created_at DESC)` and a unique constraint on `(application_id, document_type)` so an application has at most one active CV and one active PS in Milestone 1.

- [ ] **Step 4: Run the migration test**

Run: `uv run --project apps/api pytest apps/api/tests/test_migrations.py -v`  
Expected: PASS.

- [ ] **Step 5: Verify migration rollback and reapply**

Run from `apps/api`: `uv run alembic downgrade base`  
Expected: tables are removed without an error.  
Run: `uv run alembic upgrade head`  
Expected: migration reaches `0001`.

- [ ] **Step 6: Commit**

```bash
git add infra apps/api/app/core apps/api/app/db apps/api/alembic.ini apps/api/alembic apps/api/tests
git commit -m "feat: add milestone one database schema"
```

### Task 3: Add authentication, error envelopes, and ownership primitives

**Files:**
- Create: `apps/api/app/core/errors.py`
- Create: `apps/api/app/core/security.py`
- Modify: `apps/api/app/main.py`
- Create: `apps/api/tests/test_security.py`
- Create: `apps/api/tests/test_errors.py`

**Interfaces:**
- Produces: `AuthPrincipal(user_id: UUID, email: str | None)`.
- Produces: `get_current_principal(credentials, settings) -> AuthPrincipal`.
- Produces: `ApiError(status_code: int, code: str, message: str)` and envelope `{"error": {"code", "message", "request_id"}}`.
- Produces: CORS policy allowing only `WEB_ORIGIN`, with `Authorization`, `Content-Type`, `Idempotency-Key`, and `X-Request-ID` request headers.

- [ ] **Step 1: Write failing authentication and error tests**

```python
def test_missing_bearer_token_is_401(client):
    response = client.get("/api/v1/test-auth")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert response.json()["error"]["request_id"]


def test_valid_token_returns_principal(authenticated_client, user_id):
    response = authenticated_client.get("/api/v1/test-auth")
    assert response.status_code == 200
    assert response.json()["user_id"] == str(user_id)


def test_cors_allows_only_configured_web_origin(client):
    response = client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
```

Tests must sign local RS256 JWT fixtures and override the JWKS loader; they must not call Supabase over the network.

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run --project apps/api pytest apps/api/tests/test_security.py apps/api/tests/test_errors.py -v`  
Expected: FAIL because security and error modules do not exist.

- [ ] **Step 3: Implement JWT validation and stable errors**

Validate signature, expiration, issuer equal to `${SUPABASE_URL}/auth/v1`, audience equal to `SUPABASE_JWT_AUDIENCE`, and UUID format of `sub`. Cache the provider JWKS response. Never accept unsigned tokens or decode with signature verification disabled.

```python
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AuthPrincipal:
    user_id: UUID
    email: str | None
```

Add request-ID middleware that accepts a valid incoming `X-Request-ID` or creates a UUID, returns it in the response header, and includes it in every handled API error.
Configure FastAPI `CORSMiddleware` from `Settings.web_origin`; never use wildcard origins together with credentialed requests.

- [ ] **Step 4: Run tests and verify pass**

Run: `uv run --project apps/api pytest apps/api/tests/test_security.py apps/api/tests/test_errors.py -v`  
Expected: PASS for missing, expired, wrong-audience, invalid-subject, and valid tokens.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/core apps/api/app/main.py apps/api/tests
git commit -m "feat: validate Supabase authentication"
```

### Task 4: Implement owned application APIs

**Files:**
- Create: `apps/api/app/schemas/application.py`
- Create: `apps/api/app/schemas/document.py`
- Create: `apps/api/app/services/applications.py`
- Create: `apps/api/app/api/routes/applications.py`
- Modify: `apps/api/app/main.py`
- Create: `apps/api/tests/api/test_applications.py`

**Interfaces:**
- Consumes: `AuthPrincipal`, `get_db`, and `Application`.
- Produces: `get_owned_application(db: Session, application_id: UUID, user_id: UUID) -> Application`.
- Produces: `POST /api/v1/applications`, `GET /api/v1/applications`, and `GET /api/v1/applications/{id}`.
- Produces: `ApplicationDetailResponse` containing application fields plus `documents: list[DocumentResponse]`, ordered by document type. The list endpoint returns summary objects without documents.

- [ ] **Step 1: Write failing API tests**

```python
def test_user_can_create_and_list_application(authenticated_client):
    created = authenticated_client.post(
        "/api/v1/applications",
        json={"target_school": "CUHK-Shenzhen", "target_program": "MSc AI"},
    )
    assert created.status_code == 201
    listed = authenticated_client.get("/api/v1/applications")
    assert [item["id"] for item in listed.json()["items"]] == [created.json()["id"]]


def test_user_cannot_read_another_users_application(client_for_user, application_factory):
    owned_by_a = application_factory(user="a")
    response = client_for_user("b").get(f"/api/v1/applications/{owned_by_a.id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "APPLICATION_NOT_FOUND"


def test_application_detail_includes_owned_documents(authenticated_client, application, document_factory):
    document_factory(application=application, document_type="CV")
    response = authenticated_client.get(f"/api/v1/applications/{application.id}")
    assert response.status_code == 200
    assert [item["document_type"] for item in response.json()["documents"]] == ["CV"]
```

Return 404, not 403, for another user's resource to avoid leaking its existence.

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run --project apps/api pytest apps/api/tests/api/test_applications.py -v`  
Expected: FAIL with route not found.

- [ ] **Step 3: Implement schemas, service, and routes**

`ApplicationCreate` requires trimmed, non-empty `target_school` and `target_program`, each at most 200 characters. Creation inserts the current user's `Profile` row if it does not exist. List order is `created_at DESC`.

```python
class ApplicationCreate(BaseModel):
    target_school: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    target_program: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    degree_type: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=100)] = None
```

Define `DocumentResponse` at this point because application details embed it. It exposes exactly `id`, `application_id`, `document_type`, `original_filename`, `mime_type`, `size_bytes`, `parse_status`, and `created_at`. It does not expose `storage_key`, `sha256`, `extracted_text`, or `parse_error`.

- [ ] **Step 4: Run API tests**

Run: `uv run --project apps/api pytest apps/api/tests/api/test_applications.py -v`  
Expected: PASS, including validation, empty list, ordering, ownership, and missing-resource cases.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/schemas apps/api/app/services apps/api/app/api/routes apps/api/app/main.py apps/api/tests
git commit -m "feat: add owned application APIs"
```

### Task 5: Implement PDF validation and the storage boundary

**Files:**
- Create: `apps/api/app/services/pdf_validation.py`
- Create: `apps/api/app/storage/base.py`
- Create: `apps/api/app/storage/supabase.py`
- Create: `apps/api/tests/unit/test_pdf_validation.py`
- Create: `apps/api/tests/unit/test_supabase_storage.py`
- Create: `apps/api/tests/fixtures/text.pdf`
- Create: `apps/api/tests/fixtures/scanned.pdf`

**Interfaces:**
- Produces: `ValidatedPdf(content: bytes, sha256: str, page_count: int)`.
- Produces: `validate_pdf(content: bytes, content_type: str | None) -> ValidatedPdf`.
- Produces: `ObjectStorage.put(key: str, content: bytes, content_type: str) -> None` and `ObjectStorage.delete(key: str) -> None`.
- Produces: cached dependency `get_object_storage() -> ObjectStorage`, which tests override with an in-memory fake.

- [ ] **Step 1: Write failing PDF validation tests**

```python
def test_accepts_small_text_pdf(text_pdf_bytes):
    result = validate_pdf(text_pdf_bytes, "application/pdf")
    assert result.page_count == 1
    assert len(result.sha256) == 64


@pytest.mark.parametrize(
    ("content", "content_type", "code"),
    [
        (b"not pdf", "application/pdf", "INVALID_PDF_SIGNATURE"),
        (b"%PDF-fake", "text/plain", "INVALID_CONTENT_TYPE"),
    ],
)
def test_rejects_invalid_pdf(content, content_type, code):
    with pytest.raises(ApiError) as error:
        validate_pdf(content, content_type)
    assert error.value.code == code
```

Add separate tests for content over 10 MB, more than 30 pages, encrypted PDFs, parser failures, and a PDF whose pages contain no extractable non-whitespace text. Expected codes are `FILE_TOO_LARGE`, `PDF_TOO_LONG`, `ENCRYPTED_PDF_UNSUPPORTED`, `INVALID_PDF`, and `SCANNED_PDF_UNSUPPORTED`.

- [ ] **Step 2: Run validation tests and verify failure**

Run: `uv run --project apps/api pytest apps/api/tests/unit/test_pdf_validation.py -v`  
Expected: FAIL because `validate_pdf` does not exist.

- [ ] **Step 3: Implement validation in a fixed order**

Check content type, byte length, `%PDF-` signature, parser readability/encryption, page count, and finally presence of extractable text. Compute SHA-256 only after basic size/signature validation. Do not log file contents.

- [ ] **Step 4: Run PDF validation tests**

Run: `uv run --project apps/api pytest apps/api/tests/unit/test_pdf_validation.py -v`  
Expected: PASS for all accepted and rejected fixtures.

- [ ] **Step 5: Write and run the failing storage-adapter test**

Mock HTTPX and assert that `put` sends bytes only to `/storage/v1/object/{bucket}/{key}` with the service-role bearer token and `x-upsert: false`, while `delete` calls the storage deletion endpoint. Assert that a provider error becomes `ApiError(code="STORAGE_UNAVAILABLE")` without including response bodies or service keys.

Run: `uv run --project apps/api pytest apps/api/tests/unit/test_supabase_storage.py -v`  
Expected: FAIL before implementation, then PASS after the adapter is implemented.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/services/pdf_validation.py apps/api/app/storage apps/api/tests/unit apps/api/tests/fixtures
git commit -m "feat: validate PDFs and add private storage adapter"
```

### Task 6: Implement secure document upload and deletion APIs

**Files:**
- Modify: `apps/api/app/schemas/document.py`
- Create: `apps/api/app/services/documents.py`
- Create: `apps/api/app/api/routes/documents.py`
- Modify: `apps/api/app/main.py`
- Create: `apps/api/tests/api/test_documents.py`

**Interfaces:**
- Consumes: `get_owned_application`, `validate_pdf`, `ObjectStorage`, `Document`, and `AuthPrincipal`.
- Produces: `POST /api/v1/applications/{application_id}/documents` and `DELETE /api/v1/documents/{document_id}`.
- Produces: `DocumentResponse` with metadata only; it never includes file bytes, extracted text, service credentials, or a public URL.

- [ ] **Step 1: Write failing upload and isolation tests**

```python
def test_owner_can_upload_cv(authenticated_client, application, text_pdf_path, fake_storage):
    with text_pdf_path.open("rb") as pdf:
        response = authenticated_client.post(
            f"/api/v1/applications/{application.id}/documents",
            data={"document_type": "CV"},
            files={"file": ("cv.pdf", pdf, "application/pdf")},
        )
    assert response.status_code == 201
    assert response.json()["document_type"] == "CV"
    assert response.json()["parse_status"] == "UPLOADED"
    assert "storage_key" not in response.json()
    assert len(fake_storage.put_calls) == 1


def test_other_user_cannot_upload_to_application(client_for_user, application_factory, text_pdf_path):
    application = application_factory(user="a")
    response = client_for_user("b").post(
        f"/api/v1/applications/{application.id}/documents",
        data={"document_type": "CV"},
        files={"file": ("cv.pdf", text_pdf_path.read_bytes(), "application/pdf")},
    )
    assert response.status_code == 404
```

Add tests for invalid document type, duplicate CV, validation failure without storage writes, storage failure without database rows, deletion by owner, deletion by another user, and storage deletion failure preserving the database row.

- [ ] **Step 2: Run API tests and verify failure**

Run: `uv run --project apps/api pytest apps/api/tests/api/test_documents.py -v`  
Expected: FAIL with route not found.

- [ ] **Step 3: Implement storage keys and upload transaction**

Storage keys have the exact shape `{user_id}/{application_id}/{document_id}/{sanitized_filename}`. Generate the document UUID before storage. Validate first, upload second, insert metadata third. If the database insert fails after upload, attempt storage deletion and record only the request ID and storage key in server logs.

The endpoint accepts one `UploadFile` plus form field `document_type`. It reads at most `10 MB + 1 byte`; if the extra byte exists, return `FILE_TOO_LARGE` without reading the remainder.

- [ ] **Step 4: Implement deletion semantics**

Verify ownership through `Document -> Application.user_id`, delete the private storage object, and delete the metadata row only after storage reports success. A missing storage object is treated as already deleted. Any other storage failure returns `STORAGE_DELETE_FAILED` and keeps the row.

- [ ] **Step 5: Run document API tests**

Run: `uv run --project apps/api pytest apps/api/tests/api/test_documents.py -v`  
Expected: PASS for upload, validation, duplicate, isolation, cleanup, and delete cases.

- [ ] **Step 6: Run all API tests and commit**

Run: `uv run --project apps/api pytest apps/api/tests -v --cov=app --cov-report=term-missing`  
Expected: all tests PASS; no uncovered ownership branch in application or document routes.

```bash
git add apps/api/app apps/api/tests
git commit -m "feat: add secure document upload APIs"
```

### Task 7: Add web authentication and the typed API client

**Files:**
- Create: `apps/web/src/lib/supabase/client.ts`
- Create: `apps/web/src/lib/supabase/server.ts`
- Create: `apps/web/src/lib/api/client.ts`
- Create: `apps/web/src/types/api.ts`
- Create: `apps/web/src/app/(auth)/sign-in/page.tsx`
- Create: `apps/web/src/app/(auth)/sign-in/actions.ts`
- Modify: `apps/web/src/app/page.tsx`
- Create: `apps/web/src/lib/api/client.test.ts`
- Create: `apps/web/src/app/(auth)/sign-in/page.test.tsx`

**Interfaces:**
- Produces: `apiFetch<T>(path: string, init?: RequestInit) -> Promise<T>`.
- Produces: `ApiClientError(code: string, message: string, requestId: string | null, status: number)`.
- Produces: sign-in UI using Supabase email/password authentication.

- [ ] **Step 1: Write failing API-client tests**

```ts
it("adds the Supabase access token", async () => {
  mockSession("token-123");
  mockFetchJson(200, { items: [] });
  await apiFetch<ApplicationList>("/api/v1/applications");
  expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining("/api/v1/applications"),
    expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer token-123" }) }),
  );
});

it("maps the API error envelope", async () => {
  mockFetchJson(404, { error: { code: "APPLICATION_NOT_FOUND", message: "Application not found", request_id: "req-1" } });
  await expect(apiFetch("/api/v1/applications/missing")).rejects.toMatchObject({
    code: "APPLICATION_NOT_FOUND",
    requestId: "req-1",
    status: 404,
  });
});
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pnpm --filter web test -- --run src/lib/api/client.test.ts`  
Expected: FAIL because `apiFetch` does not exist.

- [ ] **Step 3: Implement Supabase clients and `apiFetch`**

Use `NEXT_PUBLIC_API_BASE_URL`; obtain the current session through the browser Supabase client; reject missing sessions with `ApiClientError(code="AUTH_REQUIRED")`; set `Authorization` without overriding caller-provided headers; parse the approved error envelope.

```ts
export type DocumentType = "CV" | "PS";
export type ParseStatus = "UPLOADED" | "PARSING" | "PARSED" | "FAILED";

export interface DocumentResponse {
  id: string;
  application_id: string;
  document_type: DocumentType;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  parse_status: ParseStatus;
  created_at: string;
}

export interface ApplicationSummary {
  id: string;
  target_school: string;
  target_program: string;
  degree_type: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ApplicationDetail extends ApplicationSummary {
  documents: DocumentResponse[];
}

export interface ApplicationList {
  items: ApplicationSummary[];
}
```

- [ ] **Step 4: Implement and test sign-in**

The form contains labeled email and password inputs, disables submit while pending, maps invalid credentials to a generic user-safe message, and redirects successful sign-in to `/applications`. It never logs passwords or authentication responses.

Run: `pnpm --filter web test -- --run src/lib/api/client.test.ts 'src/app/(auth)/sign-in/page.test.tsx'`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src
git commit -m "feat: add web authentication and API client"
```

### Task 8: Add application and document upload screens

**Files:**
- Create: `apps/web/src/app/(dashboard)/applications/page.tsx`
- Create: `apps/web/src/app/(dashboard)/applications/application-form.tsx`
- Create: `apps/web/src/app/(dashboard)/applications/[id]/page.tsx`
- Create: `apps/web/src/components/document-upload-form.tsx`
- Create: `apps/web/src/app/(dashboard)/applications/application-form.test.tsx`
- Create: `apps/web/src/components/document-upload-form.test.tsx`

**Interfaces:**
- Consumes: `apiFetch`, `ApplicationResponse`, and `DocumentResponse`.
- Produces: application list/create UI and application detail page with separate CV and PS upload controls.

- [ ] **Step 1: Write failing form tests**

```tsx
it("creates an application and navigates to its detail page", async () => {
  mockApiCreateApplication({ id: "app-1", target_school: "CUHK-Shenzhen", target_program: "MSc AI" });
  render(<ApplicationForm />);
  await userEvent.type(screen.getByLabelText("Target school"), "CUHK-Shenzhen");
  await userEvent.type(screen.getByLabelText("Target program"), "MSc AI");
  await userEvent.click(screen.getByRole("button", { name: "Create application" }));
  expect(mockPush).toHaveBeenCalledWith("/applications/app-1");
});

it("rejects a non-PDF before calling the API", async () => {
  render(<DocumentUploadForm applicationId="app-1" documentType="CV" />);
  await userEvent.upload(screen.getByLabelText("CV PDF"), new File(["x"], "cv.txt", { type: "text/plain" }));
  expect(screen.getByText("Choose a PDF file." )).toBeInTheDocument();
  expect(mockApiFetch).not.toHaveBeenCalled();
});
```

Add tests for files over 10 MB, successful upload, server validation errors, disabled duplicate-type upload, and delete confirmation.

- [ ] **Step 2: Run tests and verify failure**

Run: `pnpm --filter web test -- --run 'src/app/(dashboard)/applications/application-form.test.tsx' src/components/document-upload-form.test.tsx`  
Expected: FAIL because the components do not exist.

- [ ] **Step 3: Implement application list and creation**

The page displays empty, loading, error, and populated states. Creation requires target school and program. After creation, navigate to `/applications/{id}`. Do not add editing, search, sorting controls, or school suggestions.

- [ ] **Step 4: Implement upload and delete UI**

Render separate slots for CV and PS. Each accepts `.pdf`, enforces the 10 MB browser-side limit, sends `multipart/form-data` without manually setting the content-type boundary, shows the server's safe error message and request ID, and refreshes application data after success. Do not preview or parse PDF content in this milestone.

- [ ] **Step 5: Run all web tests and build**

Run: `pnpm --filter web test -- --run`  
Expected: all tests PASS.  
Run: `pnpm --filter web build`  
Expected: production build succeeds without TypeScript or ESLint errors.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src
git commit -m "feat: add application document upload UI"
```

### Task 9: Verify the Milestone 1 acceptance criteria and document operation

**Files:**
- Create: `apps/api/tests/api/test_milestone_one_journey.py`
- Modify: `README.md`
- Modify: `.env.example` only if an environment variable used by the implementation is missing.

**Interfaces:**
- Consumes: all Milestone 1 interfaces.
- Produces: a reproducible setup and verification procedure; no new product behavior.

- [ ] **Step 1: Write the end-to-end API acceptance test**

```python
def test_milestone_one_journey(client_for_user, text_pdf_path, fake_storage):
    user_a = client_for_user("a")
    user_b = client_for_user("b")
    application = user_a.post(
        "/api/v1/applications",
        json={"target_school": "CUHK-Shenzhen", "target_program": "MSc AI"},
    ).json()
    with text_pdf_path.open("rb") as pdf:
        upload = user_a.post(
            f"/api/v1/applications/{application['id']}/documents",
            data={"document_type": "CV"},
            files={"file": ("cv.pdf", pdf, "application/pdf")},
        )
    assert upload.status_code == 201
    assert user_b.get(f"/api/v1/applications/{application['id']}").status_code == 404
    assert user_b.delete(f"/api/v1/documents/{upload.json()['id']}").status_code == 404
    assert user_a.delete(f"/api/v1/documents/{upload.json()['id']}").status_code == 204
    assert fake_storage.objects == {}
```

- [ ] **Step 2: Run the acceptance test**

Run: `uv run --project apps/api pytest apps/api/tests/api/test_milestone_one_journey.py -v`  
Expected: PASS.

- [ ] **Step 3: Document exact local commands**

`README.md` must document prerequisites, environment-file creation, PostgreSQL startup, `alembic upgrade head`, Supabase private bucket creation, web/API startup, test commands, build command, and how to stop local PostgreSQL. It must explicitly state that Milestone 1 stores but does not parse or analyze PDFs.

- [ ] **Step 4: Run the complete verification suite**

Run: `uv run --project apps/api pytest apps/api/tests -v --cov=app --cov-report=term-missing`  
Expected: all API tests PASS.  
Run: `pnpm --filter web test -- --run`  
Expected: all web tests PASS.  
Run: `pnpm --filter web build`  
Expected: production build succeeds.  
Run: `git diff --check`  
Expected: no whitespace errors.

- [ ] **Step 5: Perform the manual browser check**

Start FastAPI and Next.js using the README commands. Sign in as user A, create an application, upload one CV and one PS, refresh the page, and verify both remain visible. Sign in as user B and verify user A's application URL displays a not-found state. Delete user A's CV and verify the slot becomes available again.

- [ ] **Step 6: Commit**

```bash
git add README.md .env.example apps/api/tests/api/test_milestone_one_journey.py
git commit -m "test: verify milestone one user journey"
```

## Milestone 1 Completion Gate

Do not begin Milestone 2 until all of the following are true:

- API tests and coverage command pass.
- Web tests and production build pass.
- Database migration upgrades, downgrades, and reapplies cleanly.
- Authenticated user A can create an application and upload one CV and one PS.
- User B receives not-found responses for user A's application and documents.
- Files are stored in a private bucket and API responses expose no storage key or public URL.
- Invalid, oversized, encrypted, over-30-page, and scanned PDFs are rejected with stable error codes.
- Refreshing the browser preserves uploaded-document state.
- README setup and test commands work from a fresh checkout.
- The milestone changes and test results are summarized to the user before any Milestone 2 planning or implementation.

# AI Admission Interview Coach — MVP Design

**Status:** Approved architecture baseline  
**Date:** 2026-08-05  
**Product scope:** AI/CS graduate admission interview preparation

## 1. Objective

Build a focused interview-training product that turns a candidate's CV and personal statement into an evidence-grounded candidate profile, identifies interview risks, conducts an adaptive text-based stress interview, and produces a traceable coaching report.

The MVP optimizes for a complete and reliable user journey rather than broad feature coverage.

## 2. MVP Scope

### Included

- User authentication.
- One or more application targets per user.
- Upload of a CV and personal statement as text-based PDF files.
- Document parsing and user-visible extraction status.
- Structured candidate profile with source evidence.
- Structured interview risk report with source evidence.
- Interview plan based on material risks.
- An 8–12 turn adaptive, text-based mock interview.
- Hidden per-answer evaluation using a versioned rubric.
- A final report with scores, strengths, weaknesses, and preparation advice.
- Persistent application, interview, and report history.

### Explicitly excluded

- Real-time voice, video, avatars, facial or emotion analysis.
- Scanned-PDF OCR in the first release.
- Admission probability prediction.
- Automatic personal-statement rewriting.
- University or program database.
- Job interview mode.
- RAG, embeddings, or a vector database.
- Autonomous multi-agent services or microservices.
- LangChain or another agent orchestration framework.

## 3. Architecture Decision

Use a modular monolith with a separately deployable web process, API process, and worker process from two application codebases in one repository.

### Components

- **Next.js web application:** App Router, TypeScript, Tailwind CSS; owns pages, authentication UI, upload UI, interview interaction, and report presentation.
- **FastAPI application:** owns authorization, business APIs, file validation, parsing, AI workflows, interview state, scoring, and report generation.
- **Worker process:** runs from the FastAPI codebase and claims durable jobs from PostgreSQL.
- **PostgreSQL:** source of truth for business entities, workflow status, AI output versions, and interview history.
- **Private object storage:** stores original CV and personal-statement files; production uses Supabase Storage.
- **Supabase Auth:** authenticates users and issues JWTs; FastAPI validates JWTs and enforces resource ownership.
- **LLM provider:** accessed through a narrow provider interface; the MVP implements one provider only.

The frontend does not directly read or write domain tables. All domain operations go through FastAPI. Direct frontend use of Supabase is limited to authentication.

## 4. AI Workflow Design

The five conceptual agents are code modules and structured LLM calls, not independently deployed agents.

### Analysis state machine

1. `PARSE_DOCUMENTS`
2. `EXTRACT_PROFILE`
3. `DETECT_RISKS`
4. `BUILD_INTERVIEW_PLAN`
5. `COMPLETED` or `FAILED`

### Interview state machine

1. Select the next uncovered interview objective.
2. Generate one question tied to that objective or risk.
3. Accept and persist the candidate's answer.
4. Evaluate the answer with the current rubric version.
5. Decide deterministically whether to follow up, move to the next objective, or finish.
6. Generate a final report after the terminal state.

### Interview guardrails

- Default interview length is 10 turns; configured range is 8–12 turns.
- A single risk may receive at most two follow-up questions.
- Covered objectives are tracked and cannot be selected again unless a permitted follow-up remains.
- Every question must reference a risk ID or explicit interview objective.
- Per-turn evaluations are stored but hidden until the interview ends.
- The backend, not the model, enforces stopping rules.
- Structured-output validation failure receives one repair retry. A second failure records a stable error and stops the affected operation.

### Evidence contract

Every material claim and risk must include:

- source document ID;
- a short verbatim source excerpt;
- the relevant extracted claim;
- the model's interpretation or risk rationale.

Document content is treated as untrusted data. Instructions found inside an uploaded document are never executed or treated as system instructions.

## 5. Evaluation Design

The MVP rubric is `admission-v1`. Scores use a 1–5 scale; dimensions that do not apply to a question are `null` and excluded from aggregation.

Dimensions:

- relevance;
- specificity and evidence;
- project ownership;
- logical structure;
- technical understanding;
- critical thinking and reflection;
- communication clarity.

The LLM returns scores, reasons, strengths, weaknesses, and whether a follow-up is warranted. The backend calculates aggregate scores using fixed rules. The report presents scores as coaching signals, not objective admission predictions.

## 6. Data Model

All identifiers are UUIDs. All timestamps are UTC `timestamptz` values.

### `profiles`

- `id` UUID primary key and foreign key to the authentication user.
- `display_name` text, nullable.
- `created_at` timestamp.

### `applications`

- `id` UUID primary key.
- `user_id` UUID foreign key.
- `target_school` text.
- `target_program` text.
- `degree_type` text, nullable.
- `status` text.
- `created_at`, `updated_at` timestamps.
- Index on `(user_id, created_at desc)`.

### `documents`

- `id` UUID primary key.
- `application_id` UUID foreign key.
- `document_type` enum-like text: `CV` or `PS`.
- `original_filename`, `storage_key`, `mime_type` text.
- `size_bytes` bigint and `sha256` text.
- `parse_status` enum-like text: `UPLOADED`, `PARSING`, `PARSED`, or `FAILED`.
- `extracted_text` and `parse_error` text, nullable.
- `created_at` timestamp.

### `analysis_runs`

- `id` UUID primary key.
- `application_id` UUID foreign key.
- `status` enum-like text: `PENDING`, `RUNNING`, `COMPLETED`, or `FAILED`.
- `profile_json` and `risk_json` JSONB, nullable.
- `model` and `prompt_version` text.
- `error_code`, `error_message` text, nullable.
- `started_at`, `completed_at` timestamps, nullable.
- `created_at` timestamp.

Each reanalysis creates a new row. Existing results are never silently overwritten.

### `jobs`

- `id` UUID primary key.
- `job_type` text and `entity_id` UUID.
- `status` enum-like text: `PENDING`, `RUNNING`, `COMPLETED`, or `FAILED`.
- `attempts` integer.
- `available_at`, `created_at` timestamps.
- `locked_at`, `completed_at` timestamps, nullable.
- `error_message` text, nullable.

The worker claims rows with `SELECT ... FOR UPDATE SKIP LOCKED`. Jobs are idempotent by entity and operation type. A job may run at most three times, using exponential backoff between attempts; the third failure is permanent until the user explicitly starts a new analysis run.

### `interview_sessions`

- `id` UUID primary key.
- `application_id` and `analysis_run_id` UUID foreign keys.
- `mode` text: `FULL_INTERVIEW` or `PROJECT_STRESS_TEST`.
- `status` text: `CREATED`, `IN_PROGRESS`, `COMPLETED`, or `ABANDONED`.
- `plan_json` and `current_state_json` JSONB.
- `max_turns` integer and `overall_score` numeric, nullable.
- `started_at`, `created_at` timestamps.
- `completed_at` timestamp, nullable.

An interview is permanently tied to the analysis version used to create it.

### `interview_turns`

- `id` UUID primary key.
- `session_id` UUID foreign key.
- `turn_index` integer.
- `risk_id` text, nullable.
- `question_type` and `question` text.
- `answer` text, nullable.
- `evaluation_json` JSONB, nullable.
- `asked_at` timestamp and `answered_at` timestamp, nullable.
- Unique constraint on `(session_id, turn_index)`.

### `interview_reports`

- `id` UUID primary key.
- `session_id` UUID foreign key with a unique constraint.
- `rubric_version` text.
- `report_json` JSONB.
- `generated_at` timestamp.

### `llm_runs`

- `id` UUID primary key.
- `operation`, `entity_type`, `provider`, `model`, `prompt_version`, `status` text.
- `entity_id` UUID.
- `input_tokens`, `output_tokens`, `latency_ms` integer, nullable.
- `error_code` text, nullable.
- `created_at` timestamp.

Full CV/PS text and full prompts are not written to ordinary application logs.

## 7. API Contract

All domain routes use the `/api/v1` prefix and require authentication.

- `POST /applications` creates an application target.
- `GET /applications` lists the current user's applications.
- `GET /applications/{id}` returns an owned application.
- `POST /applications/{id}/documents` uploads one typed PDF using multipart form data.
- `DELETE /documents/{id}` deletes an owned document and its storage object.
- `POST /applications/{id}/analyses` creates an analysis job and returns HTTP 202 with an analysis-run ID.
- `GET /analysis-runs/{id}` returns analysis status and completed output.
- `GET /applications/{id}/latest-analysis` returns the latest completed analysis.
- `POST /applications/{id}/interviews` creates an interview from a completed analysis.
- `GET /interviews/{id}` returns session state and visible turns.
- `POST /interviews/{id}/turns` submits the answer to the current unanswered turn and returns the next question or completion status.
- `GET /interviews/{id}/report` returns the report only after completion.

Write endpoints accept an `Idempotency-Key` header where duplicate submission would create duplicate state.

## 8. File and Security Rules

- The MVP accepts text-based PDF files only.
- The server validates MIME type and PDF file signature. Each file is limited to 10 MB and 30 pages.
- Object-storage buckets are private; the database stores storage keys, not public URLs.
- Download access uses short-lived signed URLs after ownership verification.
- Every database query for user-owned resources includes an ownership check.
- Scanned or unparseable PDFs return an actionable unsupported-file response.
- Application deletion first marks the application `DELETING`, then deletes its storage objects, then deletes dependent database rows through foreign-key cascades. A failed storage deletion leaves the application in `DELETE_FAILED` for retry and does not report success to the user.
- Raw personal materials are excluded from routine logs and error trackers.

## 9. Error Handling and Recovery

- API errors use a stable error code plus a user-safe message and request ID.
- File parsing, LLM validation, provider timeout, provider rate limit, and authorization failures have distinct error codes.
- Analysis status is durable and can be polled after page refresh.
- Worker jobs record attempts and errors. Transient failures receive at most three total attempts; permanent failures require a user-initiated reanalysis.
- Answer submission is idempotent and cannot create two turns for the same turn index.
- An interrupted interview resumes from its most recent persisted state.

## 10. Testing Strategy

### Unit tests

- PDF validation and parsing behavior.
- Pydantic schemas for profile, risks, plans, evaluations, and reports.
- Interview transition and stopping rules.
- Score aggregation with nullable dimensions.
- Ownership and authorization helpers.

### Integration tests

- Authentication plus resource ownership.
- File upload through storage and database metadata.
- Analysis job creation, claiming, completion, and failure.
- Complete interview flow with a mocked LLM provider.
- Duplicate answer and idempotency handling.

### AI regression fixtures

Maintain a small anonymized fixture set representing:

- a clear project with measurable evidence;
- an overclaimed project;
- unclear personal contribution;
- contradictory CV and personal-statement claims;
- a technically weak but honest candidate profile.

Assertions focus on schema validity, evidence traceability, required risk coverage, non-repetition, and stopping behavior rather than exact prose.

## 11. Repository Layout

```text
ai-admission-interview-coach/
├─ apps/
│  ├─ web/
│  │  ├─ src/app/
│  │  ├─ src/components/
│  │  ├─ src/features/
│  │  ├─ src/lib/api/
│  │  ├─ src/lib/auth/
│  │  └─ tests/
│  └─ api/
│     ├─ app/api/routes/
│     ├─ app/core/
│     ├─ app/db/models/
│     ├─ app/schemas/
│     ├─ app/services/
│     ├─ app/ai/prompts/
│     ├─ app/parsers/
│     ├─ app/workers/
│     ├─ alembic/
│     └─ tests/
├─ docs/
├─ infra/
├─ .env.example
└─ README.md
```

## 12. Milestones and Acceptance Criteria

### Milestone 0 — Contracts and fixtures

Finalize Pydantic schemas, API contract, migration design, anonymized fixtures, output examples, and prompt versioning. Acceptance requires unambiguous contracts for every persisted AI output.

### Milestone 1 — Foundation and secure upload

Initialize the repository, web and API applications, authentication, PostgreSQL migrations, private storage, application creation, text-PDF upload, authorization, and baseline tests. Acceptance requires one user to upload CV/PS documents while another user cannot access them.

### Milestone 2 — Material analysis and risk diagnosis

Implement parsing, extraction preview, durable analysis jobs, candidate profiles, evidence-grounded claims, risk diagnosis, schema validation, and failure UI. Acceptance requires fixture documents to produce valid, traceable analysis output.

### Milestone 3 — Adaptive interview engine

Implement interview plans, state transitions, question generation, answer submission, hidden evaluation, bounded follow-ups, termination, and session restoration. Acceptance requires a complete 8–12 turn interview without repeated objectives or infinite follow-ups.

### Milestone 4 — Reports and history

Implement deterministic score aggregation, narrative coaching summaries, answer-level evidence, final reports, and history pages. Acceptance requires each major report conclusion to trace to a risk, question, answer, or evaluation.

### Milestone 5 — MVP hardening

Add input limits, privacy checks, timeouts, rate-limit handling, cost telemetry, prompt regression tests, deletion behavior, deployment documentation, and minimal monitoring. Acceptance requires the core journey to survive expected provider and worker failures without unauthorized data access.

## 13. Key Decisions Summary

- Use Next.js + FastAPI, not a Next.js-only backend.
- Use a modular monolith, not five Agent services.
- Use a durable PostgreSQL worker queue, not in-process background work for the deployed MVP.
- Use Supabase for managed Auth, PostgreSQL, and private Storage while keeping domain access behind FastAPI.
- Use structured, versioned JSON outputs validated by Pydantic.
- Bind claims and risks to source evidence.
- Bind each interview to an immutable analysis version.
- Hide per-turn feedback until the interview ends.
- Use deterministic orchestration and scoring around semantic LLM judgments.
- Support text-based PDFs only in the first release.

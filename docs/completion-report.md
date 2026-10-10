> This report describes the initial engineering upgrade. See [the subsequent correctness and visual redesign report](redesign-report.md) for current checks, evaluation results and screenshots.

# Implementation and verification report — October 10, 2026

## Implemented

All seven phases have local implementations. Existing uncommitted changes were
preserved and no live database was migrated, cloud resource provisioned, application
published or outreach sent.

1. Inspected FastAPI/Pydantic, React/TypeScript/Vite, SQLite, Ollama, Serper and Tsenta
   MCP paths. No applicable AGENTS.md existed. Recorded the initial test failures
   separately. Added a small role-only baseline evaluation adapter.
2. Added application-specific manual job descriptions/source URLs, provenance,
   timestamps/versions, validated structured requirement extraction and exact excerpt
   checks. Requirement review shows selected approved facts, IDs, sources, overlap
   reasons and missing collection evidence. Missing descriptions use an explicitly
   labeled role fallback. This matching is conservative lexical/cosine selection,
   not a semantic proof of qualification or seniority.
3. Added stable, versioned experience with project/employer, technologies, source,
   approval/retirement and update time. Legacy approved facts retain their exact text
   and IDs. SQLAlchemy repository supports SQLite and PostgreSQL, with Alembic frozen
   deployment schema and pgvector cosine retrieval. Embeddings are cached by factual
   content and model/version/dimension; approval changes do not re-embed unchanged
   text. Retrieval filters approval before scoring and rechecks status/version after
   asynchronous work. Failure exposes a lexical fallback warning. Experience UI
   supports create/edit/approve/retire.
4. Added 40 fictional cases, explicit synthetic labels, machine-readable benchmark
   outputs and optional real-model/embedding commands. Captures fact precision/recall,
   contact NDCG, recognized unsupported claims, failures, latency, model calls and
   available token counts. Added optional redacted Langfuse and immutable suggestions
   with accept/edit/reject feedback; rates are null until observations exist.
5. Added persistent LangGraph nodes for requirements, retrieval, contact research,
   evidence, drafting, validation, review and persistence. Explicit fallback/no-contact
   branches and interrupts for insufficient experience, invalid output and provider
   failures. Stable versioned run IDs, durable resume requests, restart scheduling
   recovery, cached research and idempotent persistence preserve edits/history.
   Engine remains the scheduler; graph checkpoints own stage progress. External
   reads may repeat across a crash between response and checkpoint/cache storage.
6. Added a multi-stage Dockerfile, localhost Compose demo and optional pgvector
   profile, pinned Python/npm dependencies, one-command fictional demo, health and
   readiness checks, configurable Ollama URL, credential-store protocol, native
   Keychain, deployment injection and optional existing AWS Secrets Manager provider.
   Private mode requires password authentication, signed Secure/HttpOnly sessions,
   per-session CSRF, roles, HTTPS configuration and explicit hosts/origins.
7. Added CI for backend/frontend/typecheck/build/Playwright and an ephemeral pgvector
   integration test. Browser tests use temporary fictional HTTP and HTTPS servers;
   production has no test-control routes. Generated notes use whole approved facts
   and finite framing variants to reach exactly 200 Unicode code points by default.
   Impossible generation preserves saved drafts. Manual notes remain editable.

## Tested locally

- Baseline: **70 backend passed, 9 failed**; **23 frontend passed**; production build
  passed before changes.
- Final backend: **93 passed, 1 skipped**. Skip is live PostgreSQL/pgvector integration
  because neither Docker nor PostgreSQL is installed. One dependency deprecation
  warning remains in Starlette’s test portal alias.
- Frontend: **23 passed**; TypeScript check and production build passed.
- Playwright: **3 passed**: approval/description/matches/draft edits/activity undo;
  provider failure and paused review resume; actual HTTPS login/session/CSRF/logout.
- PostgreSQL schema DDL compiled locally; all-table import and pgvector runtime tests
  are configured for CI but were not executed against a live PostgreSQL server here.
- Python compilation, pip dependency consistency and git diff whitespace checks pass.
  npm reported zero advisories after a compatible source-map-js patch.

The initial note tests expected a free-form model request absent from the inspected
implementation; they now verify deterministic framing, exact length and rejection
of unapproved IDs/unrequested text. Graph-stage/configuration tests were updated for
the new authority and experience repository. A fictional provider’s hardcoded employer
caused the initial manual-research failure; it now uses the requested fictional company.
Browser verification exposed and fixed asynchronous description-load overwrites and
HTTPS form-origin behavior. Early browser failures also included test-server routing,
locator ambiguity, label mismatch and selecting the wrong identical-title application.
These were corrected; none remains a failing check in the final local suite.

## Measured

`evaluation/results.mock.json` contains the actual mock-harness run over 40 cases.
Synthetic labels were generated from controlled technology terms and recruiter titles;
they are not independent human judgments. Rounded mean values:

| Metric | Role-only baseline | Upgraded selection |
|---|---:|---:|
| Relevant-fact precision | 0.50 | 1.00 |
| Relevant-fact recall | 1.00 | 1.00 |
| Contact NDCG | 1.00 | 1.00 |
| Recognized unsupported-claim rate | 0.00 | 0.00 |
| Failure rate | 0.00 | 0.00 |
| Actual model calls | 0 | 0 |

These are mocked behavior measurements, **not actual model performance**. The corpus
is small/repetitive and favors lexical matching. Generation concatenates exact facts;
contact ranking uses a mock title heuristic. The claim checker only recognizes a
limited set of first-person factual spans. Zero unsupported spans does not prove
factuality. Mean mock benchmark-pipeline latency was 0.031 ms for baseline and 0.304 ms for upgraded selection. These timings use pre-supplied contact evidence, not live research. Exact per-stage timings are in the JSON; they describe local mock execution and do not establish a speedup. No token counts were available
because no real model calls ran. No embedding quality improvement has been measured.
See [evaluation protocol](evaluation.md) before interpreting real-model runs.

## Migration and rollback

Use [operations](operations.md). Stop the worker, back up the ledger and checkpoint
file, and retain the automatically created 0600 `*-before-engineering-v1.sqlite`
backup. SQLite migrations are additive/repeatable. The PostgreSQL importer also makes
`*-before-postgres.sqlite`, verifies full table contents/counts and baseline invariants,
preserves IDs/relationships/history, refuses divergent targets and never switches
configuration automatically. Run with an injected DATABASE_URL:

```
.venv/bin/python -m scripts.migrate_database .local/outreach.sqlite
```

Only switch DATABASE_URL after the live PostgreSQL integration test and restore
rehearsal. Rollback means stopping the app, retaining current data/checkpoints,
restoring the pre-upgrade SQLite snapshot and previous application version. Reconcile
any edits/events newer than the snapshot. Destructive Alembic downgrade is disabled.

## Run commands

```
./scripts/demo.sh
# Or, with Docker installed:
docker compose up --build
# Mock harness only:
.venv/bin/python -m evaluation.run
# Optional actual Ollama evaluation:
.venv/bin/python -m evaluation.run --real-model --output .local/results.real.json
# Optional embedding comparison:
RETRIEVAL_EMBEDDING_THRESHOLD=1 .venv/bin/python -m evaluation.run --real-model --embeddings --output .local/results.embeddings.json
```

## External verification still required

- Docker image/Compose smoke test and live PostgreSQL import/vector/ledger CI test.
- Actual Ollama model/digest, embeddings and quality evaluation; real Serper/Tsenta
  availability/recovery with operator-owned credentials.
- Tsenta provider verification of the chosen remote redirect URI, registration and
  refresh contract before TSENTA_CALLBACK_VERIFIED=true.
- Langfuse server/export validation if enabled; raw tracing remains off by default.
- Existing AWS environment/IAM/secrets, TLS/networking, persistent checkpoint storage,
  RDS backup/restore and organizational auth/SSO review. Optional AWS provider has
  mocked interface tests, not live IAM validation. Nothing was deployed.

## Technologies genuinely demonstrated

Locally exercised: FastAPI, Pydantic validation, React/TypeScript/Vite, SQLite,
SQLAlchemy, LangGraph durable checkpoints/interrupts, deterministic grounding and
retrieval, evaluation harness, pytest, Playwright, signed sessions/CSRF and credential
provider interfaces. Existing Ollama/Serper/Tsenta integrations remain and are mocked
in CI. Implemented but not live-verified here: Alembic/PostgreSQL/pgvector runtime,
Docker/Compose, optional Langfuse exports and AWS Secrets Manager. AWS deployment is
a documented guide, not an operated infrastructure capability. Passing tests alone
does not make this project production-ready.

# Implementation checklist

Current working tree is authoritative; existing uncommitted changes are preserved.
No applicable AGENTS.md was found in the repository or ancestor directories.

- [x] Inspect architecture, schema, credentials and review flow.
- [x] Baseline checks: backend 70 passed / 9 failed; frontend 23 passed; build passed.
- [x] Baseline evaluation adapter and fictional labels.
- [x] Job description provenance, extraction, matching and review.
- [x] Versioned approved experience, retrieval, PostgreSQL and migrations.
- [x] Evaluation, redacted observability and feedback.
- [x] Persistent LangGraph preparation and resume.
- [x] Reproducible demo, containers, credentials and private deployment guide.
- [x] CI, migration/isolation and browser tests.
- [x] Exact generated notes, verification and completion report.

Pre-existing failures: test_contact_evidence (5 note model/fallback tests),
test_improvements (3 note variants), test_manual_research (missing details retry).
These results preceded any edits made for this request.

Architecture: FastAPI/Pydantic API, React/TypeScript/Vite review UI, SQLite Store,
single Engine scheduler, Ollama structured ranking and fact selection, Serper search,
Tsenta read-only MCP over HTTP, native macOS Keychain credentials. Engine caches
search and preserves drafts with INSERT OR IGNORE. SQLite triggers freeze baseline
updates/deletes; baseline membership determines historical eligibility.

All phases have local implementations. Verification boundaries:
- SQLite/API/authentication/graph/retrieval tests, frontend tests/build and fictional
  browser scenarios run locally; final counts are in completion-report.md.
- PostgreSQL/pgvector runtime test is configured in CI, skipped locally without a
  database. Frozen Alembic DDL compiles for PostgreSQL; real import remains a gate.
- Docker build/Compose, AWS/IAM, live OAuth callback, model and Langfuse export need
  their external environments. No infrastructure was created or application published.
- Synthetic mock benchmarks verify the harness; no actual LLM quality/latency or
  embedding improvement is asserted.

Test changes: old tests expected an unused free-form ConnectionNote request and
fallback flags although the inspected implementation already used deterministic
whole-fact rendering. Assertions now test deterministic output, exact length,
approved evidence and unchanged saved drafts. Engine-stage and configuration tests
now target graph checkpoints and experience approval state. The pre-existing missing
company/role fixture used a hardcoded different employer; the fictional provider now
uses the requested company so evidence remains internally consistent.

# Correctness and workspace redesign

Implemented locally, preserving the existing FastAPI/Pydantic, React/TypeScript/CSS, SQLite/PostgreSQL and manual-outreach architecture. No external messages, account connections, cloud resources or deployments were created. Existing uncommitted work was preserved. No applicable AGENTS.md was found in the repository or ancestor directories.

## Checklist

- [x] Inspect current implementation and run baseline checks.
- [x] Conservative named technology/alias evidence and responsibility assessments.
- [x] Versioned suggestion acceptance and independent message feedback.
- [x] PostgreSQL cache backfill and pre-import embedding integration regression.
- [x] Complete serialized drafting input budgeting and compact requirements.
- [x] Description loading, failure/retry and application switching guards.
- [x] Compact Applications, Queue, Tracker, Experience, Settings and Draft Review.
- [x] Fictional browser regressions and desktop/mobile visual inspection.
- [x] Expand reproducible synthetic benchmark and distinguish embedding fallback.
- [ ] Run live PostgreSQL integration locally: no Docker, psql or TEST_DATABASE_URL is available.
- [ ] Measure real Ollama generation/embedding quality: optional external provider gate.

## Functional changes

Named skill evidence must occur explicitly in approved factual text, using a maintained alias catalog. Technology tags and embedding similarity help discovery but cannot prove qualifications. Mixed named-skill requirements require all named skills. Partial responsibility evidence and unsubstantiated durations are uncertain, and uncertain facts are not passed as supporting evidence. IDs, source references and exact original excerpts remain in the review panel. The catalog is intentionally conservative: unfamiliar skills can be unsupported even when a human could establish support. General term coverage is an evidence aid, not semantic entailment or a substitute for review.

Suggestions carry selected experience versions and description version/hash. Acceptance checks current approval, versions and description before any draft update. Stale or legacy unversioned suggestions require regeneration; manual draft saves remain available. Unsaved applied-suggestion metadata survives dialog close/reopen in session storage. Note, DM and both can be applied explicitly. Acceptance/edit observations are per message, with untouched messages retaining their evidence. Legacy combined feedback is preserved and reported separately rather than attributed to a message without evidence.

Editing approved experience resets it to draft in the backend. A second explicit approval of the persisted revision is required. New facts can be explicitly approved at creation. Retired/draft records remain excluded from retrieval.

Valid imported JSON embedding caches are backfilled into PostgreSQL vectors; cache reuse repairs vectors without re-embedding unchanged content. Model identity and dimensions are checked before reuse; malformed/stale/provider failures yield an explicit lexical fallback. The PostgreSQL test now embeds SQLite facts before importing, then asserts PostgreSQL retrieval reuses the cache. It has not been executed locally without a test service.

Drafting receives compact requirement text/category/priority, not long excerpts. Whole facts are removed to fit; factual text is never chopped. The budget includes serialized model, instructions, schema and user input, with a separate 6,500-character user-data bound. MODEL_INPUT_CHAR_BUDGET defaults to 14,000 serialized characters. This is a conservative character budget, not an exact tokenizer estimate. Minimum useful input that cannot fit fails before the call and retains prior drafts. Complete provenance remains stored.

## Visual changes

The light theme, purple accent and outreach. branding remain. Applications has a compact title/sync header, slim idle preparation summary, one filter toolbar and immediately visible records. Sync applications remains functional. Application detail is a focused view with description and matching inside it.

Queue groups show the application role once, prominent professional titles, separate relevance/evidence labels, adjacent View drafts/LinkedIn actions and expandable evidence. Summary counts are filter controls. Tracker has four compact metrics, concise activity rows and a timeline/update drawer. Unavailable rates say Not enough data; singular people counts are corrected.

Experience is a sidebar destination with search, technology chips, sources, approval/retirement actions and an accessible Add/Edit dialog. Settings has Sources, Model & Retrieval, Draft Preferences and Maintenance, with advanced details collapsed. Draft Review places suggestions alongside the editor on desktop and below on mobile, with separate apply controls. Exactly 200-character generated notes and unrestricted manual-note editing/copying are preserved.

Mobile navigation exposes every destination without clipped labels. Application tables become compact cards with visible actions. Native dialogs provide focus containment/restoration and Escape handling; focus styles, text labels, reduced-motion rules and responsive overflow checks are included. This is browser verification, not a full assistive-technology audit.

## Validation

Baseline before edits: backend 93 passed / 1 PostgreSQL skip; frontend 23 passed; TypeScript and production build passed. No baseline test failures. Browser baseline was not rerun before the first edits; existing browser tests were retained and updated for new controls.

Final local checks: backend 107 passed / 1 PostgreSQL skip, frontend 23 passed, TypeScript and production build passed, 9 Playwright tests passed. Python compile checks and pip dependency checks passed. Starlette emits an existing anyio deprecation warning; Playwright emits a harmless NO_COLOR/FORCE_COLOR warning. Initial implementation test failures and visual overflow findings were corrected before completion.

The fictional browser suite covers description matches, experience approval, draft edits, record/undo, provider recovery, persistent paused review, HTTPS authentication/CSRF, delayed and failed description loading, stale acceptance (including close/reopen), per-message feedback, and all redesigned views at 1280×900 and 390×844. Screenshots are explicitly fictional. Desktop and mobile captures were inspected for clipping, alignment, whitespace and action access; the mobile application overflow and oversized tracker actions found during review were fixed.

## Benchmark

50 reproducibly generated, synthetic author-labeled cases now include longer descriptions, aliases, multiple requirements, unsupported skills, irrelevant shared-word facts, unapproved/retired facts, long titles, engineering leadership and former-employment contact distractors. Labels express explicit technology evidence and contact role/company association; they are not independent human judgments. The label/description audit caught inherited labels that no longer matched rewritten descriptions; these were reconciled before the final run. Alias tests also caught React.js incorrectly implying a separate JavaScript qualification and the ordinary verb go implying Golang; both are fixed.

Checked-in evaluation/results.mock.json is a mock harness run, not model performance. Fact precision: baseline 0.60 / upgraded 1.00; recall: both 1.00; contact NDCG: both approximately 0.9754. Recognized unsupported first-person claim rate and harness failures were zero for both. Generation is exact fact concatenation and ranking is a title heuristic; zero recognized unsupported claims does not prove factuality. Model calls and available token counts were zero. No embedding quality result or speedup is claimed. The narrow, intentionally explicit technology labels favor the implemented matching rules.

Both methods have the same final six-fact/2,800-character evidence limit and, in optional real-model runs, the same generation interface, exact-200 constraint and DM limit. The historical baseline candidate selection remains role-only/first-12 by design. --embeddings now forces embedding requests independent of collection size. Results separately count provider calls, retrieval methods and lexical fallbacks. Deterministic tests verify both successful embedding-path exercise and failure reporting; those tests are not an embedding quality benchmark.

## Migration and rollback

SQLite adds only message_feedback; legacy feedback and all application/contact/draft/baseline/event records remain intact. Before initialization, the app creates a private `*-before-correctness-v2.sqlite` backup once. Migrations are repeatable. PostgreSQL deployments run `alembic upgrade head` (new 002_feedback migration) and the validated import command when switching databases. Imported valid embedding JSON is preserved and vector values are derived from it.

To roll back: stop the app, retain a fresh backup of current data, restore the pre-correctness SQLite snapshot with the preceding application version, and restore the matching checkpoint sidecar if reverting workflow progress. For PostgreSQL, restore a pre-upgrade snapshot with the preceding version; destructive Alembic downgrades remain disabled. Do not restore an old snapshot without retaining subsequent manual edits/events. See operations.md for backup/restore commands.

Run checks from the repository root:

```sh
.venv/bin/python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
# Stop any server on 8765/8766 first:
cd frontend && npm run test:e2e
```

Optional evaluation:

```sh
.venv/bin/python -m evaluation.run --output .local/results.mock.json
.venv/bin/python -m evaluation.run --real-model --embeddings --output .local/results.real.json
```

For PostgreSQL tests use an isolated fictional TEST_DATABASE_URL with pgvector installed. CI already supplies an ephemeral pgvector service. No live PostgreSQL migration, model quality assessment, or cloud deployment is implied by the local passing checks.

See [screenshot gallery](screenshots/README.md) for all redesigned views.

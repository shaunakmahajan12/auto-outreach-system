# Setup and verification — October 13, 2026

Update: a temporary private AWS EC2 deployment subsequently passed verification;
see [AWS deployment verification](aws-deployment-verification.md) for deployment
evidence and cleanup status. The remaining text records the earlier local checks.

The local implementation and previously pending runtime checks are now verified.
These checks used isolated test databases and did not send outreach. Subsequent
AWS deployment and cleanup are documented separately above.

## Extraction fix

The model returns zero-based source indexes instead of copying excerpts. The server
splits the original description into bounded exact spans, validates each selected
index and supplies the excerpt itself. Named technologies in requirement text must
occur in the selected passage (recognized aliases are allowed). Invalid output gets
at most one corrective retry, then fails closed.

For combined responsibilities explicitly saying “using Postgres”, a separate narrow
Postgres skill is exposed while the complete responsibility remains uncertain unless
approved evidence substantiates its scope. Negated or alternative usages are excluded
from this deterministic decomposition. Original requirements are retained; no broad
responsibility is relabeled as proven merely by technology overlap.

The three-case actual `qwen3:4b` + `nomic-embed-text` evaluation now passes 3/3 upgraded
cases, with 15 embedding calls and zero lexical fallbacks. Baseline also passes 3/3.
The strict command exits zero. Current results, model digests and exact requirements
are in ignored `.local/results.real-smoke.json`. This is a small synthetic smoke test,
not an independently labeled general quality benchmark. Earlier failed runs motivated
the protocol change; historical reports describe the prior behavior.

## Verified

- Backend after repository cleanup: 130 passed, one PostgreSQL skip in the ordinary
  suite. Five duplicate legacy parameter cases were consolidated; active fact
  grounding and draft-preservation assertions remain. PostgreSQL was previously
  exercised separately against a real disposable PostgreSQL 16 + pgvector container:
  its integration test passes, including full import, repeat import, immutable
  baseline protection, graph draft persistence, event deduplication and cached vectors.
- PostgreSQL backup/restore: actual `pg_dump`/`pg_restore` into a separate database;
  counts and full row-content fingerprints match across all 23 tables. Restored
  baseline protection remains active.
- Frontend: 23 tests, TypeScript and production build passed. Browser: 11 tests passed,
  including setup, provider failure/recovery, paused graph resume, draft feedback,
  stale evidence, desktop/mobile views and HTTPS sessions/CSRF.
- Production Docker image builds and passes startup, readiness, immutable baseline,
  fictional submission transitions and draft preparation with private temporary storage.
- Docker Compose builds and runs the fictional app using a separate verification
  project/volume; readiness, baseline and preparation through the HTTP API pass.
- Live Tsenta complete read-only history, one Serper test query and local Ollama
  availability pass using existing configured credentials. Provider reports expose
  only status/counts; private application contents and credentials are not printed.
- Real Ollama fictional ranking/drafting check passes. Nothing is sent to LinkedIn.

Docker CLI, Compose and Colima were installed for these checks. Verification uses a
separate `outreach` Colima VM and disposable PostgreSQL containers. No live database
is mounted in the verification containers. CI retains PostgreSQL tests and the
isolated production-image smoke job; local passes do not imply a published CI run.
Existing dependency/reflection deprecation warnings remain non-fatal.
Verification containers/fictional volumes were removed and the VM stopped afterward.
Restart it with `colima start --profile outreach` before rerunning Docker checks.

## Repeatable checks

```
.venv/bin/python -m pytest -q
.venv/bin/python scripts/container_smoke.py
.venv/bin/python scripts/postgres_smoke.py
.venv/bin/python scripts/verify_live.py --provider tsenta --provider serper --provider ollama
.venv/bin/python -m evaluation.run --real-model --embeddings --limit 3 --require-success --output .local/results.real-smoke.json
```

Provider checks use existing credentials and do not import/sync the ledger. Normal
OAuth refresh may update the credential store. The Serper check consumes one request.
A full corpus run and independent human labels remain necessary before broader model
quality claims. Optional Langfuse is not enabled or verified without a configured server.

## Deployment status

The temporary private AWS deployment passed verification and was removed to
conserve Free Plan credits. See [AWS deployment verification](aws-deployment-verification.md).
Public HTTPS and remote OAuth reconnect remain outside that verified scope.

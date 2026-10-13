# Local setup and operations

One-command fictional demo, Python 3.11 and Node 22 installed:

```
./scripts/demo.sh
```

Open http://127.0.0.1:8765. This creates only `.local/demo.sqlite`, uses fictional
providers, and needs no Serper, Tsenta or Ollama credentials. Demo credentials and
external profile opening are disabled. To start containers instead, install Docker
and run `docker compose up --build`; only localhost port 8765 is published. No cloud
resource or paid service is created. The production image and Compose workflow have been verified locally. Run `python3 scripts/container_smoke.py` before deployment. This builds
the image and checks readiness, immutable-history availability, fictional submission
transitions and draft preparation in a temporary container with an empty private
tmpfs. It publishes a random localhost port, mounts no workspace data and stops the
container on completion. The same check now runs in a separate CI job; a configured
job is not evidence that it has passed.

Local live mode retains `.local/outreach.sqlite`, native macOS Keychain and localhost.
Never point demo mode at that file. Ollama defaults to http://127.0.0.1:11434; set
OLLAMA_URL for a container (`http://host.docker.internal:11434`) or protected endpoint.
No alternate proprietary API protocol is implied. Use an Ollama-compatible endpoint
or implement/test another provider through the structured model interface.

Fresh live workspaces open Settings automatically. The setup checklist shows source
connection, initial import, search configuration, model readiness and approved
experience. Use Refresh setup status after external sign-in/model changes. Initial
import reads complete history and preserves it as historical, without queuing outreach.
An existing baseline cannot be replaced through onboarding. Provider failures leave
the workspace uninitialized so import can be retried. An existing `.initializing`
file is retained for review instead of being overwritten.

Experience is versioned independently of legacy Settings facts. Existing approved
text and IDs are imported unchanged; an existing record is never rewritten by the
legacy import. Retired records stay retired. New/edited records can be draft,
approved or retired. The UI resets edited content to draft until explicitly approved.
Legacy settings remain as a compatibility import, not the retrieval source of truth.
Use the experience UI to edit or retire migrated facts.

Job descriptions are explicitly pasted for the selected application. Store text,
source URL, manual provenance, timestamp and content version. Tsenta’s posting tool
mapping remains unverified; no other posting is substituted. Extraction requires
exact source excerpts and fails closed. Small collections use lexical retrieval;
RETRIEVAL_EMBEDDING_THRESHOLD (default 50) enables Ollama embeddings above the threshold.
EMBEDDING_MODEL (default nomic-embed-text) and EMBEDDING_VERSION identify cached vectors.
Increment version when model weights change. Stale/edited content is re-embedded;
unchanged embeddings are reused. PostgreSQL stores native pgvector values and uses
cosine distance. SQLite uses JSON vectors and Python cosine for local tests/demo.
Selection remains bounded to six whole records and 2,800 factual-text characters.
No ANN index or retrieval performance improvement is claimed for small collections.

Generated connection notes default to exactly 200 Unicode code points, matching
frontend Array.from and Python len. Whole facts and finite framing variants are used;
no whitespace padding, fact truncation or invented metrics. Impossible combinations
produce an actionable failure and preserve saved text. Disable the setting for
maximum-length rendering. Manual notes remain editable, saveable and copyable.

## Backup and rollback

Stop the single worker before migration/import/restore. No real data migration was
performed during development; tests use temporary fictional databases. Initialization
makes a 0600 `*-before-engineering-v1.sqlite` backup before engineering migrations.
Existing v1/v2/v3 migration backups remain. Migrations are additive/repeatable; baseline
and baseline_members updates/deletes are protected by database triggers.

For a consistent SQLite backup, use Python’s online backup API, not a live file copy:

```
.venv/bin/python -c "import sqlite3; s=sqlite3.connect('.local/outreach.sqlite'); t=sqlite3.connect('.local/outreach.backup.sqlite'); s.backup(t); t.close(); s.close()"
```

Back up `outreach.sqlite.checkpoints.sqlite` too while stopped. Keep backups private
and encrypted; the launcher sets umask 077. Restore a backup to a separate path first,
run integrity checks (`PRAGMA integrity_check` and `foreign_key_check`), and inspect
baseline/application/contact/draft/event counts before changing OUTREACH_DB.
Rollback: stop app, preserve the current database/checkpoints, restore the pre-upgrade
SQLite backup, use the previous application version, then start locally. Do not apply
an automatic destructive Alembic downgrade. A pre-upgrade snapshot omits all later
edits/events; export and reconcile them before rollback. Delete neither history nor
baseline membership to repair a failed import.

## PostgreSQL migration

Optional local service: create `.local/postgres-password` (0600) with a unique local
password, then `docker compose --profile retrieval up -d postgres`. Supply DATABASE_URL
through a secret/environment injector, never a command containing production passwords.
Use a SQLAlchemy URL such as `postgresql+psycopg://…/outreach`; include sslmode=require
for RDS. `DATABASE_URL` controls the full ledger; EXPERIENCE_DATABASE_URL optionally
separates the experience repository. Prefer the same database for atomic operations.

```
.venv/bin/python -m scripts.migrate_database .local/outreach.sqlite
```

The command backs up the SQLite source first, applies Alembic, imports every table
with IDs/relationships/event history, checks full row content and counts, verifies
foreign keys and immutable baseline invariants, and repairs PostgreSQL sequences.
Re-running an identical import is safe; a divergent target is refused. Configuration
is never switched automatically. Inspect counts, take `pg_dump` plus checkpoint
backups, then set DATABASE_URL and CREDENTIAL_STORE=deployment and restart. The
PostgreSQL startup marker and LangGraph SQLite checkpoints need a persistent private
`.local` volume. Use one app worker/instance. The graph is the stage-progress authority;
jobs are scheduling and status projections. No competing graph scheduler runs.

PostgreSQL runtime tests use TEST_DATABASE_URL and an ephemeral pgvector CI service.
Run `.venv/bin/python scripts/postgres_smoke.py` to create a disposable PostgreSQL/pgvector
container, execute real import/vector/ledger tests and rehearse pg_dump/pg_restore with
all-table content comparisons. This has passed locally. Target-environment tests and
backups are still required before switching a real database; an unrun CI job is not a pass.

Graph run IDs derive from application ID + description/version + role/company +
experience revision + explicit no-contact retry epoch. Changed inputs produce a new
run. Search cache is reused; completed drafts use INSERT OR IGNORE. Provider/validation
failures and insufficient evidence interrupt with actionable reasons. The application
panel shows the stable run ID and offers resume. Resume requests persist in the ledger.
Optional pause_before_persistence=true in stored settings enables explicit review
pause. Rejected/closed or unconfirmed applications cannot resume. Old checkpoints are
private history and are not resumed against changed inputs. External reads are
at-least-once if the process dies between a response and its cache/checkpoint write;
there is no outbound sending. Database writes are idempotent across that window.

## Checks

```
.venv/bin/python -m pytest -q
(cd frontend && npm ci && npm test && npm run typecheck && npm run build)
(cd frontend && npx playwright install chromium && npm run test:e2e)
.venv/bin/python -m evaluation.run
```

Playwright starts a temporary fictional server with test-only provider/tick controls.
Those routes are absent from the production factory. Traces/screenshots/video are
turned off. `/health` reports process availability; `/ready` checks ledger/baseline
integrity, not provider account access. Provider availability is shown in Settings.

Live provider checks: `.venv/bin/python scripts/verify_live.py --provider tsenta --provider serper --provider ollama`. This reads complete Tsenta history without importing it, makes one public Serper test query, and checks Ollama availability. Reports contain counts/status only. Existing credentials are required; normal token refresh may update the credential store. No OAuth reconnect or remote callback registration is attempted.

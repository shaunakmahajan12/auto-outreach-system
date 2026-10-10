# Outreach — Application Outreach Assistant

A local dashboard that reads Tsenta submissions, researches potential professional contacts through Serper, and prepares LinkedIn outreach using local Ollama and user-approved experience. Messages are sent manually.

Read the [detailed architecture and repository guide](docs/architecture.md) for the implementation, database, workflows, security boundaries, tests, and deployment limitations.

## Stack

- React 19, TypeScript, Vite 6, CSS, Tailwind Vite integration, Lucide icons.
- Python FastAPI, Uvicorn, Pydantic, HTTPX, SQLite or SQLAlchemy/PostgreSQL/pgvector; Alembic and LangGraph.
- Tsenta MCP over OAuth/PKCE, Serper search, Ollama `qwen3:4b`.
- macOS Keychain or deployment secrets; optional Langfuse; pytest, Node tests and Playwright.

## Run a fictional demo

Use Python 3.11 and Node.js 22. Live credential storage requires macOS; the fictional demo uses in-memory credentials. The launcher uses Unix file locking.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
OUTREACH_DEMO=true OUTREACH_DB=.local/demo.sqlite TSENTA_POLL_ENABLED=false .venv/bin/python scripts/run.py
```

Open http://127.0.0.1:8765. Use the fictional transition button twice to move a demo application from running to submitted, then inspect its contacts and drafts. Demo mode does not call live search, Tsenta, or Ollama.

## Existing live installation

Live startup requires an existing validated Tsenta baseline database; that private database is intentionally not distributed with the code. A fresh clone should start with the demo above. A new live workspace can connect Tsenta and import its complete initial history in Settings. Never replace an existing immutable baseline.

```sh
OUTREACH_DEMO=false OUTREACH_DB=.local/outreach.sqlite TSENTA_POLL_ENABLED=false .venv/bin/python scripts/run.py
```

Configure Tsenta, the Serper key, and approved facts in Settings. Install/run Ollama separately with the configured model. The live app requests one sync on startup, reusing any pending sync. Recurring Tsenta polling defaults to off; a supported interval and reference are required before enabling it.

For frontend development, run `npm run dev` in `frontend/` alongside the backend. Vite proxies `/api` to port 8765.

## Checks

```sh
.venv/bin/python -m pytest -q
cd frontend
npm test
npm run build
```

## Scope and privacy

Localhost is the default. Private remote mode requires real authentication, session-bound CSRF, role checks and explicit HTTPS/host/origin configuration; see the deployment guide. This remains a single-workspace service. It has no LinkedIn sending API or inbox synchronization. Search snippets are evidence to review, not proof of employment or hiring responsibility.

Private databases, response captures, credentials, environment files, dependencies, build output, and account-specific development notes are excluded from Git. `.env.example` contains configuration examples, not credentials. Do not add live data to fixtures or commits.

## Fill a missing role from its posting

Missing roles are checked automatically in the background, one posting at a time. A single title from `JobPosting` structured data is saved automatically; heading-only candidates show **Review extracted role**. Each posting URL is attempted once per application, including failures, so restarts do not repeatedly fetch unavailable pages. Set `OUTREACH_AUTO_ROLE_EXTRACTION=false` to disable this independently of contact research.

Applications with a missing role and a saved Tsenta posting link also offer **Extract role from posting** in the list and application details. The reader checks `JobPosting` structured data, then a single page heading. Review the candidate and source link, then choose **Save role**. The source URL and extraction time are retained; existing roles are not overwritten and no outreach research is queued. Login-only, blocked, oversized, ambiguous, or JavaScript-only pages may require manual entry through **Prepare outreach**.

## Measurable personalization upgrade

The current implementation includes job-description provenance and requirement
review, versioned approved experience, SQLAlchemy/PostgreSQL/pgvector support,
persistent LangGraph preparation, separate draft suggestions and feedback, optional
redacted Langfuse instrumentation, signed-session private mode, fictional benchmarks
and CI/browser tests. Sending remains manual.

Start a separate fictional workspace with `./scripts/demo.sh`, or
`docker compose up --build` when Docker is installed. Neither requires live provider
credentials. Keep the live `.local/outreach.sqlite` database private and separate.

- [Setup, backups, migration and rollback](docs/operations.md)
- [Benchmark protocol and limitations](docs/evaluation.md)
- [Private AWS deployment guide](docs/private-aws.md)
- [Implementation checklist and baseline](docs/implementation-checklist.md)
- [Completion and verification report](docs/completion-report.md)

Run `.venv/bin/python -m evaluation.run` for mock harness verification; use
`--real-model --output .local/results.real.json` only when Ollama is available.
Checked-in synthetic/mock results are not evidence of actual LLM quality or speed.
Docker, real PostgreSQL and provider integration must be verified in your deployment
environment before a database switch or remote rollout.

Current correctness and visual redesign: [implementation and validation report](docs/redesign-report.md), [fictional screenshot gallery](docs/screenshots/README.md).

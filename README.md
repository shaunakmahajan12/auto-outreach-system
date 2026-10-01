# Outreach — Application Outreach Assistant

A local dashboard that reads Tsenta submissions, researches potential professional contacts through Serper, and prepares LinkedIn outreach using local Ollama and user-approved experience. Messages are sent manually.

Read the [detailed architecture and repository guide](docs/architecture.md) for the implementation, database, workflows, security boundaries, tests, and deployment limitations.

## Stack

- React 19, TypeScript, Vite 6, CSS, Tailwind Vite integration, Lucide icons.
- Python FastAPI, Uvicorn, Pydantic, HTTPX, SQLite.
- Tsenta MCP over OAuth/PKCE, Serper search, Ollama `qwen3:4b`.
- macOS Keychain for live credentials; pytest and Node's built-in test runner.

## Run a fictional demo

Use Python 3.10+ and a Node.js version compatible with Vite 6. Live credential storage requires macOS; the fictional demo uses in-memory credentials. The launcher uses Unix file locking.

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

Live startup requires an existing validated Tsenta baseline database; that private database is intentionally not distributed with the code. A fresh clone should start with the demo above. Initial live baseline creation currently uses the diagnostic and baseline Python utilities rather than a complete onboarding wizard.

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

This is a single-user localhost application, not a publicly deployable multi-user service. It has no LinkedIn sending API or inbox synchronization. Search snippets are evidence to review, not proof of employment or hiring responsibility.

Private databases, response captures, credentials, environment files, dependencies, build output, and account-specific development notes are excluded from Git. `.env.example` contains configuration examples, not credentials. Do not add live data to fixtures or commits.

## Fill a missing role from its posting

Missing roles are checked automatically in the background, one posting at a time. A single title from `JobPosting` structured data is saved automatically; heading-only candidates show **Review extracted role**. Each posting URL is attempted once per application, including failures, so restarts do not repeatedly fetch unavailable pages. Set `OUTREACH_AUTO_ROLE_EXTRACTION=false` to disable this independently of contact research.

Applications with a missing role and a saved Tsenta posting link also offer **Extract role from posting** in the list and application details. The reader checks `JobPosting` structured data, then a single page heading. Review the candidate and source link, then choose **Save role**. The source URL and extraction time are retained; existing roles are not overwritten and no outreach research is queued. Login-only, blocked, oversized, ambiguous, or JavaScript-only pages may require manual entry through **Prepare outreach**.

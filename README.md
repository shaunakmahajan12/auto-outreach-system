# Outreach — Application Outreach Assistant

A local dashboard that reads Tsenta submissions, researches potential professional contacts through Serper, and prepares outreach using local Ollama and user-approved experience. Invitations and messages are sent manually by the user.

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

Configure Tsenta, the Serper key, and approved facts in Settings. Install/run Ollama separately with the configured model. Recurring Tsenta polling defaults to off; a supported interval and reference are required before enabling it.

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

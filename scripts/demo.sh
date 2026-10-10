#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock.txt
(cd frontend && npm ci && npm run build)
OUTREACH_DEMO=true OUTREACH_REMOTE=false OUTREACH_DB=.local/demo.sqlite OUTREACH_AUTO_ROLE_EXTRACTION=false TSENTA_POLL_ENABLED=false .venv/bin/python scripts/run.py

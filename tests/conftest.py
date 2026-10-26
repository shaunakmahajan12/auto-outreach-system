"""Tests never inherit live database or telemetry configuration."""

import pytest


@pytest.fixture(autouse=True)
def isolate_live_configuration(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('EXPERIENCE_DATABASE_URL', raising=False)
    monkeypatch.delenv('AWS_CREDENTIAL_SECRET_ID', raising=False)
    monkeypatch.setenv('OUTREACH_REMOTE', 'false')
    monkeypatch.setenv('LANGFUSE_ENABLED', 'false')
    monkeypatch.setenv('TRACE_RAW_CONTENT', 'false')
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')

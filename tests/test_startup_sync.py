"""Startup queues one live sync without duplicating pending work."""

import pytest
from fastapi.testclient import TestClient
from backend.demo import seed, MemorySecrets, FixtureTsenta, FixtureSearch, FixtureOllama
from backend.engine import Engine
from backend.main import create_app
from backend.store import Store


@pytest.mark.parametrize('pending', [None, 'queued', 'retry', 'running'])
def test_live_startup_requests_one_sync(tmp_path, monkeypatch, pending):
    monkeypatch.setenv('OUTREACH_DEMO', 'false')
    monkeypatch.setenv('TSENTA_POLL_ENABLED', 'false')
    path = tmp_path / 'startup.sqlite'
    seed(path)
    store = Store(path)
    store.initialize()
    if pending:
        original_id = store.enqueue_sync()
        with store.db() as db:
            db.execute('UPDATE sync_runs SET state=?', (pending,))

    async def idle(self):
        await self.stop.wait()

    monkeypatch.setattr(Engine, 'run', idle)
    app = create_app(
        store=store,
        tsenta=FixtureTsenta(store),
        search=FixtureSearch(),
        ollama=FixtureOllama(),
        vault=MemorySecrets(),
    )
    with TestClient(app):
        runs = store.rows('SELECT * FROM sync_runs')
        assert len(runs) == 1
        assert runs[0]['state'] in ('queued', 'retry')
        if pending:
            assert runs[0]['id'] == original_id
        assert app.state.engine.poll_active is False


@pytest.mark.parametrize(
    'demo,worker,valid', [(True, True, True), (False, False, True), (False, True, False)]
)
def test_startup_skips_demo_disabled_worker_or_invalid_baseline(
    tmp_path, monkeypatch, demo, worker, valid
):
    monkeypatch.setenv('OUTREACH_DEMO', str(demo).lower())
    path = tmp_path / 'startup.sqlite'
    seed(path)
    store = Store(path)
    store.initialize()
    if not valid:
        with store.db() as db:
            db.execute('UPDATE applications SET historical=0')

    async def idle(self):
        await self.stop.wait()

    monkeypatch.setattr(Engine, 'run', idle)
    app = create_app(
        store=store,
        tsenta=FixtureTsenta(store),
        search=FixtureSearch(),
        ollama=FixtureOllama(),
        vault=MemorySecrets(),
        start_worker=worker,
    )
    with TestClient(app):
        assert store.rows('SELECT * FROM sync_runs') == []

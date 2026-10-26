"""Fresh live-workspace onboarding with fictional providers and isolated storage."""

import pytest
from fastapi.testclient import TestClient

from backend.demo import MemorySecrets, FixtureOllama, FixtureSearch, row
from backend.main import create_app
from backend.security import Unavailable


class InitialHistory:
    fail = False

    async def snapshot(self):
        if self.fail:
            raise Unavailable('Fictional provider temporarily unavailable')
        return [row('FICTIONAL-INITIAL', 'COMPLETED')]


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    path = tmp_path / 'fresh.sqlite'
    monkeypatch.setenv('OUTREACH_DEMO', 'false')
    monkeypatch.setenv('OUTREACH_DB', str(path))
    provider = InitialHistory()
    app = create_app(
        vault=MemorySecrets(),
        tsenta=provider,
        search=FixtureSearch(),
        ollama=FixtureOllama(),
        start_worker=False,
    )
    with TestClient(app) as client:
        client.headers['x-outreach-token'] = client.get('/api/bootstrap').json()['token']
        yield client, path, provider


def test_initial_import_is_review_only_and_cannot_replace_baseline(fresh):
    client, path, _ = fresh
    assert not path.exists()
    settings = client.get('/api/settings').json()
    assert settings['onboarding_required'] and settings['approved_experience_count'] == 0
    assert not path.exists()  # Reading setup must not create a half-initialized ledger.
    assert client.post('/api/onboarding/initialize').json() == {'imported': 1}
    state = client.get('/api/state').json()
    assert state['baseline_valid'] and not state['onboarding_required']
    assert state['contacts'] == []
    assert state['applications'][0]['research_state'] == 'historical_no_outreach'
    store = client.app.state.store
    assert store.rows('SELECT * FROM jobs') == []
    original = store.rows('SELECT * FROM baseline_members')
    assert client.post('/api/onboarding/initialize').status_code == 400
    assert store.rows('SELECT * FROM baseline_members') == original


def test_failed_provider_import_can_be_retried(fresh):
    client, path, provider = fresh
    provider.fail = True
    assert client.post('/api/onboarding/initialize').status_code == 409
    assert not path.exists()
    assert client.get('/api/bootstrap').json()['onboarding_required']
    provider.fail = False
    assert client.post('/api/onboarding/initialize').json() == {'imported': 1}


def test_interrupted_import_preserved_for_operator_review(fresh):
    client, path, _ = fresh
    staged = path.with_name(path.name + '.initializing')
    staged.write_bytes(b'fictional interrupted import')
    assert client.post('/api/onboarding/initialize').status_code == 409
    assert staged.read_bytes() == b'fictional interrupted import'
    assert not path.exists()

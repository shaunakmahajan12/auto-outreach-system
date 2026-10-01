"""End-to-end API checks using fictional data and a temporary database only."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('OUTREACH_DEMO', 'true')
    monkeypatch.setenv('OUTREACH_AUTO_RESEARCH', 'true')
    monkeypatch.setenv('OUTREACH_DB', str(tmp_path / 'fictional.sqlite'))
    app = create_app(start_worker=False)
    with TestClient(app) as client:
        client.headers['x-outreach-token'] = client.get('/api/bootstrap').json()['token']
        yield client


def advance(client):
    asyncio.run(client.app.state.engine.tick())


def test_submission_research_and_conversation(client):
    assert client.get('/').status_code == 200
    initial = client.get('/api/state').json()
    assert initial['scheduler']['enabled'] is False
    assert initial['applications'][0]['research_state'] == 'historical_no_outreach'
    assert client.post('/api/demo/transition').json()['eligible'] == 0
    assert client.post('/api/demo/transition').json()['eligible'] == 1
    advance(client)
    state = client.get('/api/state').json()
    assert len(state['contacts']) == 1
    contact = state['contacts'][0]
    assert contact['events'] == []
    assert 'FICTIONAL DEMO' in contact['note']
    cid = contact['id']
    assert client.get(f'/api/contacts/{cid}/prepare').status_code == 400
    assert client.put(f'/api/contacts/{cid}/drafts', json={'note': 'Hi Avery, I applied for Engineer at Cedar. I built a Python data pipeline that cut reporting time by 40% and added production monitoring. I’d value the chance to connect and learn more about the team.', 'dm': 'Edited fictional DM'}).status_code == 200
    event = {'kind': 'dm_sent', 'request_id': 'fictional-request-001'}
    assert client.post(f'/api/contacts/{cid}/events', json=event).status_code == 200
    assert client.post(f'/api/contacts/{cid}/events', json=event).status_code == 200
    contact = client.get('/api/state').json()['contacts'][0]
    assert len(contact['events']) == 1
    assert contact['conversation']['followup_due_at']
    assert client.post(f'/api/contacts/{cid}/events', json={'kind': 'reply', 'request_id': 'fictional-request-002'}).status_code == 200
    contact = client.get('/api/state').json()['contacts'][0]
    assert contact['conversation']['followup_due_at'] is None
    assert client.post(f'/api/contacts/{cid}/events', json={'kind': 'followup_sent', 'request_id': 'fictional-request-003'}).status_code == 400
    store = client.app.state.store
    store.initialize()
    assert store.rows('SELECT note FROM drafts')[0]['note'] == 'Hi Avery, I applied for Engineer at Cedar. I built a Python data pipeline that cut reporting time by 40% and added production monitoring. I’d value the chance to connect and learn more about the team.'
    assert store.rows('SELECT COUNT(*) AS n FROM baseline_members')[0]['n'] == 1


def test_history_requires_selection_and_sync_deduplicates(client):
    first = client.post('/api/sync').json()['run_id']
    assert client.post('/api/sync').json()['run_id'] == first
    advance(client)
    state = client.get('/api/state').json()
    assert state['sync']['state'] == 'done'
    assert state['contacts'] == []
    assert client.app.state.store.rows('SELECT * FROM jobs') == []
    assert client.post('/api/applications/FICTIONAL-HISTORY/research').status_code == 200
    advance(client)
    assert len(client.get('/api/state').json()['contacts']) == 1


def test_request_protection_and_demo_isolation(client):
    assert client.get('/api/state', headers={'x-outreach-token': ''}).status_code == 403
    assert client.post('/api/sync', headers={'origin': 'https://example.com'}).status_code == 403
    assert client.get('/api/bootstrap', headers={'host': 'example.com'}).status_code == 403
    assert client.post('/api/tsenta/connect').status_code == 400
    assert client.post('/api/settings', json={'facts_text': 'Unapproved claim', 'facts_approved': False, 'note_limit': 200, 'dm_limit': 1200}).status_code == 400


def test_live_database_rejected_in_demo(monkeypatch):
    monkeypatch.setenv('OUTREACH_DEMO', 'true')
    monkeypatch.setenv('OUTREACH_DB', '.local/outreach.sqlite')
    with pytest.raises(RuntimeError, match='Demo mode cannot use the live database'):
        create_app(start_worker=False)

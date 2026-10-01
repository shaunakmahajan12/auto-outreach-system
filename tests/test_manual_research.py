from backend.demo import row
from tests.test_workflow import client, advance


def test_disabled_automation_keeps_sync_and_manual_research(client, monkeypatch):
    monkeypatch.setenv('OUTREACH_AUTO_RESEARCH', 'false')
    store = client.app.state.store
    result = store.apply_snapshot([row('MANUAL-ONLY', 'COMPLETED')])
    assert result['added'] == 1
    assert result['eligible'] == 0
    assert store.rows('SELECT * FROM jobs') == []
    assert client.post('/api/applications/MANUAL-ONLY/research').status_code == 200
    advance(client)
    assert store.rows('SELECT * FROM contacts')


def test_dismiss_queue_persists_and_manual_prepare_restores(client):
    aid='FICTIONAL-HISTORY'
    base=f'/api/applications/{aid}/research'
    assert client.post(base).status_code==200
    assert client.post(base+'/dismiss').status_code==200
    store=client.app.state.store
    store.initialize()
    store.apply_snapshot([row(aid,'COMPLETED')])
    advance(client)
    assert store.rows('SELECT state FROM jobs')[0]['state']=='dismissed'
    assert store.rows('SELECT * FROM contacts')==[]
    assert client.post(base).status_code==200
    advance(client)
    assert store.rows('SELECT state FROM jobs')[0]['state']=='done'
    assert client.post(base+'/dismiss').status_code==400


def test_prepare_missing_details_and_retry_no_candidates(client):
    aid='FICTIONAL-HISTORY'
    store=client.app.state.store
    with store.db() as db:
        db.execute('UPDATE applications SET company=NULL,role=NULL')
    base=f'/api/applications/{aid}/research'
    assert client.post(base,json={'company':'Cedar Labs','role':'Engineer'}).status_code==200
    store.apply_snapshot([{**row(aid,'COMPLETED'),'companyName':None,'jobTitle':None}])
    assert store.rows('SELECT company,role FROM applications')[0]=={'company':'Cedar Labs','role':'Engineer'}
    with store.db() as db:
        db.execute("UPDATE jobs SET state='done'")
        db.execute("UPDATE applications SET research_state='no_contacts'")
        db.execute('INSERT INTO research_cache VALUES(?,?)',(aid,'[]'))
    assert client.post(base).status_code==200
    assert store.rows('SELECT state FROM jobs')[0]['state']=='queued'
    assert store.rows('SELECT * FROM research_cache')==[]
    advance(client)
    assert store.rows('SELECT * FROM contacts')


def test_dismiss_does_not_claim_to_cancel_running_work(client):
    client.post('/api/applications/FICTIONAL-HISTORY/research')
    with client.app.state.store.db() as db:
        db.execute("UPDATE jobs SET state='running'")
    assert client.post('/api/applications/FICTIONAL-HISTORY/research/dismiss').status_code==400
    assert client.app.state.store.rows('SELECT state FROM jobs')[0]['state']=='running'

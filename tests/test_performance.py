"""Regression checks for repeated dashboard reads and research retries."""
from test_workflow import client, advance
from backend.outreach import record_event


def test_email_routes_are_removed(client):
    paths={route.path for route in client.app.routes}
    assert not any('/email' in path or '/gmail' in path or '/mail/' in path for path in paths)


def test_retry_reuses_edited_draft_without_model_call(client):
    client.post('/api/applications/FICTIONAL-HISTORY/research')
    advance(client)
    contact=client.get('/api/state').json()['contacts'][0]
    client.put(f'/api/contacts/{contact["id"]}/drafts',json={'note':'My edited note','dm':'My edited DM'})

    async def unexpected(*args):
        raise AssertionError('Saved drafts must not trigger model generation')

    client.app.state.engine.ollama.draft=unexpected
    with client.app.state.store.db() as db:
        db.execute("UPDATE jobs SET state='interrupted'")
    client.post('/api/applications/FICTIONAL-HISTORY/research')
    advance(client)
    state=client.get('/api/state').json()
    assert state['applications'][0]['research_state']=='ready'
    assert state['contacts'][0]['note']=='My edited note'
    assert state['contacts'][0]['dm']=='My edited DM'


def test_dashboard_preserves_outreach_counts(client,monkeypatch):
    client.post('/api/applications/FICTIONAL-HISTORY/research')
    advance(client)
    client.post('/api/demo/transition');client.post('/api/demo/transition')
    advance(client)
    store=client.app.state.store
    contacts=client.get('/api/state').json()['contacts']
    assert len(contacts)==2
    for i,contact in enumerate(contacts):
        record_event(store,contact['id'],'invitation_sent','',f'performance-event-{i}')
    queries=[]
    original=store.rows

    def rows(sql,*args):
        queries.append(sql)
        return original(sql,*args)

    monkeypatch.setattr(store,'rows',rows)
    result=client.get('/api/state').json()['contacts']
    assert not any('FROM email_outreach' in sql for sql in queries)
    for contact in result:
        related={c['id'] for c in contacts if c['linkedin_url']==contact['linkedin_url'] or
                 (c['application_company'] or '').strip().casefold()==(contact['application_company'] or '').strip().casefold()}
        assert contact['prior_outreach_count']==len(related)
        assert len(contact['events'])==1
        assert 'email_outreach' not in contact

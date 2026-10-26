"""Fictional migration, mapping, workflow and drafting checks (no live services)."""
import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from backend.demo import row, seed
from backend.details import baseline_valid, backfill_captures
from backend.outreach import record_event, state_for
from backend.research import DraftPlan, Ollama, Pick
from backend.store import Store
from backend.security import Unavailable
from test_workflow import client, advance


def prepared(client):
    client.post('/api/applications/FICTIONAL-HISTORY/research')
    advance(client)
    return client.get('/api/state').json()['contacts'][0]


def test_baseline_pending_transition_and_outcomes_survive_sync(client):
    store=client.app.state.store
    cutoff=store.rows('SELECT * FROM baseline')[0]
    with store.db() as db:
        db.execute("UPDATE applications SET confirmed_at_baseline=0,source_status='RUNNING' WHERE source_application_id='FICTIONAL-HISTORY'")
    result=store.apply_snapshot([row('FICTIONAL-HISTORY','COMPLETED')])
    assert result['eligible']==1
    assert store.rows('SELECT * FROM baseline')[0]==cutoff
    client.put('/api/applications/FICTIONAL-HISTORY/outcome',json={'outcome':'rejected','note':'Fictional rejection email'})
    store.apply_snapshot([row('FICTIONAL-HISTORY','COMPLETED')])
    app=client.get('/api/state').json()['applications'][0]
    assert app['hiring_outcome']=='rejected'
    assert app['source_status']=='COMPLETED'


def test_inconsistent_baseline_fails_closed(client):
    store=client.app.state.store
    with store.db() as db:db.execute("UPDATE applications SET historical=0")
    assert not baseline_valid(store)
    assert client.post('/api/applications/FICTIONAL-HISTORY/research').status_code==400
    with pytest.raises(ValueError,match='inconsistent'):store.apply_snapshot([row('NEW','COMPLETED')])
    assert client.get('/api/state').json()['baseline_valid'] is False


def test_metadata_backfill_never_changes_dates_or_status(client,tmp_path):
    store=client.app.state.store
    original=store.rows('SELECT * FROM applications')[0]
    capture={'tool':'list-applications','response':{'result':{'structuredContent':{'result':{'applications':[
        {**row('FICTIONAL-HISTORY','FAILED'),'jobId':'fictional-job','jobStatus':'COMPLETED','createdAt':'2020-01-01','updatedAt':'2021-01-01'}]}}}}}
    (tmp_path/'tsenta-read-003.json').write_text(json.dumps(capture))
    backfill_captures(store,tmp_path)
    app=store.rows('SELECT * FROM applications')[0]
    assert app['job_id']=='fictional-job' and app['source_job_status']=='COMPLETED'
    assert app['submitted_at'] is None
    assert app['source_status']==original['source_status']
    assert app['source_created_at']==original['source_created_at']
    store.apply_snapshot([{**row('FICTIONAL-HISTORY','COMPLETED'),'jobStatus':'FAILED'}])
    app=store.rows('SELECT * FROM applications')[0]
    assert app['source_job_status']=='FAILED' and app['hiring_outcome']=='unknown'


def test_migration_backup_and_rerun_preserve_data(tmp_path):
    path=tmp_path/'fixture.sqlite';seed(path);store=Store(path);store.initialize()
    assert path.with_name('fixture-before-v2.sqlite').exists()
    store.settings_save({'facts':[{'id':'one','text':'Fictional approved fact'}],'note_limit':200,'dm_limit':1200})
    original=store.rows('SELECT * FROM baseline')
    store.initialize()
    assert store.settings()['facts'][0]['id']=='one'
    assert store.rows('SELECT * FROM baseline')==original
    assert baseline_valid(store)


def test_contact_labels_corrections_dismissal(client):
    c=prepared(client)
    assert c['support']['label']=='Evidence not verified'
    assert c['dismissed'] is False
    assert 'not independently' in c['support']['employment']
    payload={'name':'Corrected Name','title':'','company':'','linkedin_url':c['linkedin_url'],'review_status':'supported'}
    assert client.put(f'/api/contacts/{c["id"]}',json=payload).status_code==400
    payload.update(review_source='https://example.com/team',review_note='Team page explicitly names this person; employment recency uncertain.')
    assert client.put(f'/api/contacts/{c["id"]}',json=payload).status_code==200
    updated=client.get('/api/state').json()['contacts'][0]
    assert updated['support']['label']=='Supported by source'
    assert updated['note']==c['note']
    assert updated['original_fields']
    payload.update(review_status='conflicting',review_note='Team page names a different company.',dismissed=True)
    client.put(f'/api/contacts/{c["id"]}',json=payload)
    updated=client.get('/api/state').json()['contacts'][0]
    assert updated['support']['label']=='Conflicting information' and updated['dismissed']


def test_outreach_acceptance_undo_and_closed_outcomes(client):
    c=prepared(client);cid=c['id'];store=client.app.state.store
    record_event(store,cid,'invitation_sent','','request-00001')
    record_event(store,cid,'connection_accepted','','request-00002')
    state=client.get('/api/state').json()['contacts'][0]
    assert state['conversation']['connection_status']=='connected'
    assert not state['conversation']['invitation_pending']
    event=state['events'][-1]
    client.post(f'/api/contacts/{cid}/events/{event["id"]}/undo')
    assert client.get('/api/state').json()['contacts'][0]['conversation']['invitation_pending']
    assert not client.get('/api/state').json()['contacts'][0]['conversation']['followup_due_at']
    record_event(store,cid,'dm_sent','','request-00003')
    assert client.get('/api/state').json()['contacts'][0]['conversation']['followup_due_at']
    client.put('/api/applications/FICTIONAL-HISTORY/outcome',json={'outcome':'job_closed'})
    assert client.get('/api/state').json()['contacts'][0]['conversation']['followup_due_at'] is None


def test_explicit_dates_and_future_rejection(client):
    c=prepared(client);store=client.app.state.store
    stamp=(datetime.now(timezone.utc)-timedelta(days=8)).isoformat()
    record_event(store,c['id'],'dm_sent','','dated-event-001',stamp)
    assert client.get('/api/state').json()['contacts'][0]['conversation']['followup_due']
    with pytest.raises(ValueError,match='future'):
        record_event(store,c['id'],'reply','','dated-event-002',(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())


def test_stages_retry_idempotence_and_restart(client):
    store=client.app.state.store;engine=client.app.state.engine
    client.post('/api/applications/FICTIONAL-HISTORY/research')
    client.post('/api/applications/FICTIONAL-HISTORY/research')
    assert len(store.rows('SELECT * FROM jobs'))==1
    observed=[];original=engine.stage
    def stage(aid,value):observed.append(value);original(aid,value)
    engine.stage=stage
    advance(client)
    assert observed==['missing_description','experience_retrieval','contact_research','evidence_assessment','drafting','validation','review','persistence']
    assert client.get('/api/state').json()['applications'][0]['job']['stage']=='done'
    with store.db() as db:db.execute("UPDATE jobs SET state='running'")
    store.initialize()
    app=client.get('/api/state').json()['applications'][0]
    assert app['job']['state']=='interrupted' and app['research_state']=='interrupted'
    client.post('/api/applications/FICTIONAL-HISTORY/research');advance(client)
    assert len(store.rows('SELECT * FROM contacts'))==1
    assert len(store.rows('SELECT * FROM drafts'))==1


def test_failed_job_exposes_error_and_retry(client):
    store=client.app.state.store
    from backend.experience import ExperienceInput
    repo=client.app.state.engine.experience
    for fact in repo.list():repo.save(ExperienceInput(text=fact['text'],status='retired'),fact['id'])
    client.post('/api/applications/FICTIONAL-HISTORY/research');advance(client)
    app=client.get('/api/state').json()['applications'][0]
    assert app['job']['state']=='blocked'
    assert client.get('/api/applications/FICTIONAL-HISTORY/preparation').json()['interrupts'][0]['reason']=='insufficient_evidence'
    assert client.post('/api/applications/FICTIONAL-HISTORY/research').status_code==200
    assert store.rows('SELECT * FROM jobs')[0]['state']=='queued'


def test_note_includes_whole_approved_fact_without_exact_length():
    model=Ollama()
    calls=[]
    async def structured(schema,*args):
        calls.append(schema)
        return DraftPlan(fact_ids=['fact'],connection_style='connect',dm_style='team')
    model.structured=structured
    pick=Pick(source_id='fixture',name='Avery Example',title='Founder',company='Cedar',evidence_quote='Avery Example',relevance='Fictional relevance',uncertainty='Fictional')
    facts=[{'id':'fact','text':'I built a Python data pipeline that cut reporting time by 40% and added production monitoring.'}]
    draft=asyncio.run(model.draft({'role':'Engineer','company':'Cedar'},pick,facts,{'note_limit':200,'dm_limit':1200}))
    assert facts[0]['text'] in draft['note'] and len(draft['note'])==200
    assert calls==[DraftPlan]
    short=asyncio.run(model.draft({'role':'Engineer','company':'Cedar'},pick,facts,{'note_limit':80,'dm_limit':1200,'exact_note_200':False}))
    assert len(short['note'])<=80 and facts[0]['text'] in short['dm']
    fallback=asyncio.run(model.draft({'role':'Engineer','company':'Cedar'},pick,[{'id':'fact','text':'I use Python.'}],{'note_limit':200,'dm_limit':1200,'exact_note_200':False}))
    assert fallback['grounding']['fallback_used'] is False
    assert 'I use Python.' in fallback['note']
    assert '40%' not in fallback['note']
    with pytest.raises(Unavailable):asyncio.run(model.draft({'role':'Engineer','company':None},pick,facts,{'note_limit':200,'dm_limit':1200}))


def test_note_save_validation_preserves_legacy_and_copies_identical_text(client):
    from backend.outreach import prepare
    c=prepared(client);cid=c['id'];store=client.app.state.store
    with store.db() as db:db.execute('UPDATE drafts SET note=? WHERE contact_id=?',('Legacy edited note',cid))
    assert client.put(f'/api/contacts/{cid}/drafts',json={'note':'Legacy edited note','dm':'Updated DM'}).status_code==200
    for note in ('Short edit','x'*106,'x'*199,' '+'x'*199):
        assert client.put(f'/api/contacts/{cid}/drafts',json={'note':note,'dm':'Updated DM'}).status_code==200
        assert store.rows('SELECT note FROM drafts')[0]['note']==note
        assert prepare(store,cid,'note')['text']==note
    # The note limit is hard: an over-limit edit is rejected and the saved note is kept.
    assert client.put(f'/api/contacts/{cid}/drafts',json={'note':'x'*201,'dm':'Updated DM'}).status_code==400
    assert store.rows('SELECT note FROM drafts')[0]['note']==' '+'x'*199
    assert not store.rows('SELECT * FROM outreach_events')

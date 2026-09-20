"""Preservation and source-field checks; all writes use fictional databases."""
import asyncio
import json
import sqlite3
from backend.details import backfill_captures, baseline_valid, company_metadata
from backend.research import Ollama, Pick, DraftPlan, ConnectionNote
from backend.outreach import prepare, state_for
from test_workflow import client, advance


def test_company_backfill_preserves_imported_application_and_user_data(client,tmp_path):
    store=client.app.state.store
    before=store.rows('SELECT * FROM applications')[0]
    baseline=store.rows('SELECT * FROM baseline')
    members=store.rows('SELECT * FROM baseline_members')
    capture={'tool':'list-applications','response':{'result':{'structuredContent':{'result':{'applications':[{'applicationId':before['source_application_id'],'companyWebsite':'cedar.example.com','locations':['New York, NY'],'status':'FAILED','companyName':'Stale name'}]}}}}}
    (tmp_path/'tsenta-read-003.json').write_text(json.dumps(capture))
    backfill_captures(store,tmp_path)
    after=store.rows('SELECT * FROM applications')[0]
    assert after['company_website']=='https://cedar.example.com'
    assert json.loads(after['locations'])==['New York, NY']
    for key,value in before.items():
        if key not in ('company_website','locations'):assert after[key]==value
    backfill_captures(store,tmp_path)
    assert store.rows('SELECT * FROM applications')[0]==after
    assert store.rows('SELECT * FROM baseline')==baseline
    assert store.rows('SELECT * FROM baseline_members')==members
    assert baseline_valid(store)
    payload=client.get('/api/state').json()['applications'][0]
    assert payload['company']==before['company']
    assert payload['company_website']==after['company_website']
    assert payload['locations']==['New York, NY']


def test_company_metadata_rejects_unsafe_urls_and_unverified_shapes(client):
    s=client.app.state.store
    with s.db() as db:company_metadata(db,'FICTIONAL-HISTORY',{'companyWebsite':'javascript:alert(1)','locations':[{'invented':'data'}]})
    a=s.rows('SELECT * FROM applications')[0]
    assert a['company_website'] is None and a['locations'] is None


def test_copy_prepare_never_records_activity_and_edits_survive_retry(client):
    client.post('/api/applications/FICTIONAL-HISTORY/research');advance(client)
    s=client.app.state.store;c=client.get('/api/state').json()['contacts'][0];cid=c['id']
    client.put(f'/api/contacts/{cid}/drafts',json={'note':'Hi Avery, I applied for Engineer at Cedar. I built a Python data pipeline that cut reporting time by 40% and added production monitoring. I’d value the chance to connect and learn more about the team.','dm':'My edited DM'})
    before=s.rows('SELECT * FROM outreach_events')
    result=prepare(s,cid,'note')
    assert result['text']=='Hi Avery, I applied for Engineer at Cedar. I built a Python data pipeline that cut reporting time by 40% and added production monitoring. I’d value the chance to connect and learn more about the team.'
    assert s.rows('SELECT * FROM outreach_events')==before
    client.post('/api/applications/FICTIONAL-HISTORY/research');advance(client)
    assert s.rows('SELECT note FROM drafts')[0]['note']=='Hi Avery, I applied for Engineer at Cedar. I built a Python data pipeline that cut reporting time by 40% and added production monitoring. I’d value the chance to connect and learn more about the team.'
    assert s.rows('SELECT count(*) n FROM baseline_members')[0]['n']==1


def test_reply_and_closed_application_suppress_followups():
    events=[{'id':1,'kind':'dm_sent','created_at':'2020-01-01T00:00:00+00:00'}]
    for outcome in ('rejected','job_closed'):
        assert not state_for(events,outcome=outcome)['followup_due']
    events.append({'id':2,'kind':'reply','created_at':'2020-01-02T00:00:00+00:00'})
    assert state_for(events)['followup_due_at'] is None


def test_note_budget_and_verified_context():
    model=Ollama();captured={}
    async def structured(schema,instruction,data):
        captured.update(data)
        if schema is ConnectionNote:return ConnectionNote(note='Hi Avery, I applied for Engineer at Cedar. I built a Python data pipeline that cut reporting time by 40% and added production monitoring. I’d value the chance to connect and learn more about the team.',fact_ids=['fact'])
        return DraftPlan(fact_ids=['fact'],note_fact_ids=['fact'],connection_style='connect',dm_style='team')
    model.structured=structured
    facts=[{'id':'fact','text':'I built a Python data pipeline that cut reporting time by 40% and added production monitoring.'}]
    p=Pick(source_id='s',name='Avery Example',title='Recruiter',company='Cedar',evidence_quote='Avery',relevance='Fixture',uncertainty='Fixture')
    result=asyncio.run(model.draft({'role':'Engineer','company':'Cedar'},p,facts,{'note_limit':200,'dm_limit':1200}))
    assert len(result['note'])==200
    assert facts[0]['text'] in result['note']
    assert result['note']==result['note'].strip() and '  ' not in result['note']
    assert captured['contact_title'] is None
    assert 'Recruiter' not in result['note']
    assert result['grounding']['note_fact_ids']==['fact']

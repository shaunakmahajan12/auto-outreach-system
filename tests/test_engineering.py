"""Fictional-data safety, retrieval isolation, migration, auth and checkpoint tests."""
import asyncio
import json
import os
import re
import sqlite3
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.experience import ExperienceInput, retrieve
from backend.matching import extract, Requirements
from backend.note_renderer import render_note
from backend.security import Retryable, Unavailable
from backend.auth import hash_password
from test_workflow import client, advance

AID='FICTIONAL-HISTORY'

def test_description_provenance_same_role_different_selection(client):
    for tech in ('Python','React'):
        response=client.post('/api/experience',json={'text':f'I built a fictional {tech} service.','technologies':[tech],'source_reference':'fictional portfolio','status':'approved'})
        assert response.status_code==200
    ids=[]
    for tech in ('Python','React'):
        response=client.put(f'/api/applications/{AID}/description',json={'text':f'Required: {tech}\nPreferred: Kubernetes','source_url':'https://example.com/fictional-posting'})
        assert response.status_code==200
        description=client.get(f'/api/applications/{AID}/description').json()
        assert description['provenance']=='manual paste' and description['updated_at']
        result=client.post(f'/api/applications/{AID}/matches').json()
        ids.append({f['id'] for f in result['selected_facts']})
        assert result['matches'][1]['unsupported'] is True
        assert 'does not establish' in result['unsupported_meaning']
    assert ids[0]!=ids[1]
    assert client.put(f'/api/applications/{AID}/description',json={'text':'bad','source_url':'http://localhost/private'}).status_code==400

def test_excerpts_must_be_exact():
    class Bad:
        async def structured(self,*args):return Requirements(requirements=[{'text':'Python','excerpt':'invented excerpt','category':'skill','priority':'required'}])
    with pytest.raises(Retryable,match='excerpts'):asyncio.run(extract(Bad(),'Required: Python'))

def test_retired_unapproved_never_retrieved_and_versions(client,monkeypatch):
    repo=client.app.state.engine.experience
    for status in ('draft','retired','approved'):
        repo.save(ExperienceInput(text='I built a fictional React service.',technologies=['React'],status=status),status)
    result=asyncio.run(retrieve(repo,'React'))
    assert 'approved' in {f['id'] for f in result['facts']}
    assert not {'draft','retired'}&{f['id'] for f in result['facts']}
    fact=next(f for f in repo.list() if f['id']=='approved')
    value=ExperienceInput(text=fact['text'],technologies=fact['technologies'],status='approved')
    repo.save(value,'approved');assert next(f for f in repo.list() if f['id']=='approved')['version']==1
    repo.save(ExperienceInput(text='I built a fictional Python service.',status='draft'),'approved')
    assert 'approved' not in {f['id'] for f in asyncio.run(retrieve(repo,'React'))['facts']}

def test_embeddings_reuse_invalidation_fallback_and_retirement_race(client,monkeypatch):
    monkeypatch.setenv('RETRIEVAL_EMBEDDING_THRESHOLD','1')
    repo=client.app.state.engine.experience
    class Provider:
        identity='fictional:1'
        calls=[]
        async def embed(self,text):self.calls.append(text);return [1.,0.,0.]
    provider=Provider()
    asyncio.run(retrieve(repo,'Python',provider=provider));initial=len(provider.calls)
    asyncio.run(retrieve(repo,'Python',provider=provider));assert len(provider.calls)==initial+1
    f=repo.list()[0]
    repo.save(ExperienceInput(text=f['text'],source_reference=f['source_reference'],status='retired'),f['id'])
    repo.save(ExperienceInput(text=f['text'],source_reference=f['source_reference'],status='approved'),f['id'])
    asyncio.run(retrieve(repo,'Python',provider=provider));assert len(provider.calls)==initial+2
    repo.save(ExperienceInput(text=f['text']+' Fictional example.',status='approved'),f['id'])
    updated=next(r for r in repo.list() if r['id']==f['id']);assert updated['status']=='draft'
    repo.save(ExperienceInput(text=updated['text'],status='approved'),f['id'])
    asyncio.run(retrieve(repo,'Python',provider=provider));assert len(provider.calls)==initial+4
    class Failure(Provider):
        async def embed(self,text):raise ValueError('failed')
    assert 'lexical'==asyncio.run(retrieve(repo,'Python',provider=Failure()))['method']
    assert asyncio.run(retrieve(repo,'Python',provider=Failure()))['warning']
    class Race(Provider):
        async def embed(self,text):
            repo.save(ExperienceInput(text=f['text'],status='retired'),f['id']);return [1.,0.,0.]
    assert not asyncio.run(retrieve(repo,'Python',provider=Race()))['facts']

def test_additive_migration_backup_and_legacy_identity(client):
    store=client.app.state.store
    before={t:store.rows('SELECT * FROM '+t) for t in ('baseline','baseline_members','applications','drafts','outreach_events')}
    store.initialize();store.initialize()
    for table,rows in before.items():assert store.rows('SELECT * FROM '+table)==rows
    backup=store.path.with_name(store.path.stem+'-before-engineering-v1.sqlite')
    assert backup.exists() and (backup.stat().st_mode&0o777)==0o600
    fact=client.app.state.engine.experience.list()[0]
    assert fact['id']=='fictional-fact' and fact['text']=='I built a fictional Python project.'
    with store.db() as db:
        with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE baseline SET record_count=0')

def test_exact_note_and_impossible_and_unicode():
    facts=[{'id':'fictional','text':'I built a fictional Python project.'}]
    note,ids,_=render_note('Avery','Software Engineer (fictional)','Fictional Cedar Labs',facts,200,exact=True)
    assert len(note)==200 and facts[0]['text'] in note and ids==['fictional']
    with pytest.raises(Unavailable,match='exactly 200'):render_note('Avery','Engineer','Cedar',[{'id':'x','text':'I built '+('fictional '*100)+'.'}],200,exact=True)
    assert len('😀e\u0301')==3

def test_suggestions_feedback_and_edited_draft_preserved(client):
    client.post(f'/api/applications/{AID}/research');advance(client)
    c=client.get('/api/state').json()['contacts'][0];cid=c['id']
    client.put(f'/api/contacts/{cid}/drafts',json={'note':'Manual fictional edit 😀','dm':'Manual fictional message'})
    result=client.post(f'/api/contacts/{cid}/draft-suggestion');assert result.status_code==200
    s=result.json();assert client.get('/api/state').json()['contacts'][0]['note']=='Manual fictional edit 😀'
    assert client.get('/api/metrics/feedback').json()['status']=='insufficient data'
    assert client.put(f'/api/contacts/{cid}/drafts',json={'note':s['note'],'dm':s['dm'],'suggestion_id':s['suggestion_id']}).status_code==200
    feedback=client.get('/api/metrics/feedback').json();assert feedback['acceptance_rate']==1 and feedback['edit_rate']==0
    client.put(f'/api/contacts/{cid}/drafts',json={'note':'x','dm':'y','suggestion_id':s['suggestion_id']})
    assert client.get('/api/metrics/feedback').json()['observations']==2
    client.put(f'/api/contacts/{cid}/drafts',json={'note':'Later manual fictional edit','dm':s['dm']})
    assert client.get('/api/metrics/feedback').json()['edit_rate']==1

def test_paused_restart_resumes_without_duplicate_effects(client):
    store=client.app.state.store;config=store.settings();config['pause_before_persistence']=True;store.settings_save(config)
    client.post(f'/api/applications/{AID}/research');advance(client)
    status=client.get(f'/api/applications/{AID}/preparation').json()
    assert status['interrupts'][0]['reason']=='review'
    assert not store.rows('SELECT * FROM contacts')
    # Construct a new application/engine over the existing database and checkpoint file.
    new=create_app(store=store,start_worker=False)
    with TestClient(new) as other:
        other.headers['x-outreach-token']=other.get('/api/bootstrap').json()['token']
        assert other.get(f'/api/applications/{AID}/preparation').json()['run_id']==status['run_id']
        assert other.post(f'/api/applications/{AID}/preparation/resume').status_code==200
        advance(other)
        assert other.get(f'/api/applications/{AID}/preparation').json()['complete']
        assert len(store.rows('SELECT * FROM contacts'))==1
        other.post(f'/api/applications/{AID}/preparation/resume');advance(other)
        assert len(store.rows('SELECT * FROM drafts'))==1
        other.put(f'/api/applications/{AID}/outcome',json={'outcome':'rejected'})
        assert other.post(f'/api/applications/{AID}/preparation/resume').status_code==409

def test_provider_failure_resume_and_new_description_run(client):
    engine=client.app.state.engine;original=engine.search.search;calls=[]
    async def broken(*args):calls.append(1);raise Retryable('Fictional provider unavailable')
    engine.search.search=broken
    client.post(f'/api/applications/{AID}/research');advance(client)
    first=client.get(f'/api/applications/{AID}/preparation').json()
    assert first['interrupts'][0]['reason']=='provider_failure'
    engine.search.search=original
    client.post(f'/api/applications/{AID}/preparation/resume');advance(client)
    assert client.get(f'/api/applications/{AID}/preparation').json()['complete']
    client.put(f'/api/applications/{AID}/description',json={'text':'Python'})
    assert client.get(f'/api/applications/{AID}/preparation').json()['run_id']!=first['run_id']

def test_remote_mode_auth_roles_csrf_and_cookie(tmp_path,monkeypatch):
    monkeypatch.setenv('OUTREACH_DEMO','true');monkeypatch.setenv('OUTREACH_DB',str(tmp_path/'remote.sqlite'))
    monkeypatch.setenv('OUTREACH_REMOTE','true');monkeypatch.setenv('EXTERNAL_BASE_URL','https://outreach.example.com')
    monkeypatch.setenv('ALLOWED_HOSTS','outreach.example.com');monkeypatch.setenv('ALLOWED_ORIGINS','https://outreach.example.com')
    monkeypatch.setenv('SESSION_SECRET','fictional-test-session-key-32-characters')
    monkeypatch.setenv('OUTREACH_USERS',json.dumps({'reader':{'role':'reader','password_hash':hash_password('fictional-password')},'operator':{'role':'operator','password_hash':hash_password('fictional-password')}}))
    with TestClient(create_app(start_worker=False),base_url='https://outreach.example.com') as c:
        assert c.get('/api/bootstrap').status_code==401
        page=c.get('/login');assert 'secure' in page.headers['set-cookie'].lower() and 'httponly' in page.headers['set-cookie'].lower() and 'samesite=lax' in page.headers['set-cookie'].lower()
        nonce=re.search('name="csrf" value="([^"]+)"',page.text)[1]
        assert c.post('/login',content=f'csrf={nonce}&username=reader&password=fictional-password',follow_redirects=False).status_code==303
        token=c.get('/api/bootstrap').json()['token'];c.headers['x-outreach-token']=token
        assert c.get('/api/state').status_code==200
        assert c.post('/api/sync').status_code==403
        page=c.get('/login');nonce=re.search('name="csrf" value="([^"]+)"',page.text)[1]
        c.post('/login',content=f'csrf={nonce}&username=operator&password=fictional-password')
        assert c.post('/api/sync').status_code==403
        c.headers['x-outreach-token']=c.get('/api/bootstrap').json()['token']
        assert c.post('/api/sync').status_code==200
        assert c.post('/api/sync',headers={'Origin':'https://evil.example.com'}).status_code==403

def test_remote_mode_refuses_bootstrap_token_as_authentication(tmp_path,monkeypatch):
    monkeypatch.setenv('OUTREACH_REMOTE','true');monkeypatch.delenv('OUTREACH_USERS',raising=False)
    with pytest.raises(RuntimeError,match='requires OUTREACH_USERS'):create_app(start_worker=False)

def test_deployment_credential_interface_without_live_aws(monkeypatch):
    from backend.security import AwsSecrets,DeploymentSecrets
    class Client:
        secret='{}'
        def get_secret_value(self,**kwargs):return {'SecretString':self.secret}
        def put_secret_value(self,**kwargs):self.secret=kwargs['SecretString']
    provider=AwsSecrets('fictional-existing-secret',Client())
    provider.put('serper','fictional-key');provider.put('tsenta',{'access_token':'fictional-token'})
    assert provider.get('serper')=='fictional-key'
    provider.delete('serper');assert provider.get('serper') is None
    assert provider.get('tsenta')=={'access_token':'fictional-token'}
    monkeypatch.setenv('OUTREACH_SECRET_SERPER','fictional-injected-key')
    assert DeploymentSecrets().get('serper')=='fictional-injected-key'
    with pytest.raises(Unavailable,match='deployment secret store'):DeploymentSecrets().put('serper','fictional')

def test_restart_scheduling_projection_uses_checkpoints_and_preserves_terminal(client):
    store=client.app.state.store;engine=client.app.state.engine
    client.post(f'/api/applications/{AID}/research');advance(client)
    with store.db() as db:db.execute("UPDATE jobs SET state='running'")
    store.initialize();engine.recover_pending()
    assert store.rows('SELECT state FROM jobs')[0]['state']=='queued'
    advance(client);assert len(store.rows('SELECT * FROM drafts'))==1
    with store.db() as db:
        db.execute("UPDATE jobs SET state='interrupted'")
        db.execute("UPDATE applications SET hiring_outcome='job_closed'")
    engine.recover_pending();assert store.rows('SELECT state FROM jobs')[0]['state']=='interrupted'

def test_optional_observability_redacts_default_payload(monkeypatch):
    import sys
    from types import SimpleNamespace
    from backend.observability import observe
    captured=[]
    class Span:
        def update(self,**kwargs):captured.append(kwargs)
    class Manager:
        def __enter__(self):return Span()
        def __exit__(self,*args):pass
    class Client:
        def start_as_current_observation(self,**kwargs):captured.append(kwargs);return Manager()
    monkeypatch.setitem(sys.modules,'langfuse',SimpleNamespace(get_client=lambda:Client()))
    monkeypatch.setenv('LANGFUSE_ENABLED','true');monkeypatch.setenv('TRACE_RAW_CONTENT','false')
    with observe('fictional-stage','fictional-model',raw={'facts':'fictional private fact'}) as info:info['tokens']={'input':2,'output':3}
    assert 'fictional private fact' not in json.dumps(captured)
    assert any(c.get('usage_details')=={'input':2,'output':3} for c in captured)
    monkeypatch.setenv('TRACE_RAW_CONTENT','true')
    with observe('fictional-stage',raw={'facts':'fictional opted-in content'}):pass
    assert 'fictional opted-in content' in json.dumps(captured)

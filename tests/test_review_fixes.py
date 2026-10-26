"""Regressions from the repository review, using fictional records only."""
import asyncio
import pytest
from backend.demo import row
from backend.experience import ExperienceInput
from backend.maintenance import repair_notes
from backend.outreach import state_for
from backend.quality import summary
from backend.store import Store
from test_workflow import client, advance
AID='FICTIONAL-HISTORY'


def roleless(aid,status='COMPLETED'):
    return {**row(aid,status),'jobTitle':None}


def test_missing_role_is_not_auto_queued_or_researched(client):
    store=client.app.state.store
    store.apply_snapshot([row(AID,'COMPLETED'),roleless('FICTIONAL-ROLELESS')])
    assert store.rows("SELECT * FROM jobs WHERE application_id='FICTIONAL-ROLELESS'")==[]
    response=client.post('/api/applications/FICTIONAL-ROLELESS/research')
    assert response.status_code==400 and 'role' in response.json()['detail']
    assert client.post('/api/applications/FICTIONAL-ROLELESS/research',json={'role':'Fictional Engineer'}).status_code==200


def test_queued_job_without_role_blocks_with_clear_message(client):
    store=client.app.state.store
    client.post(f'/api/applications/{AID}/research')
    with store.db() as db:db.execute("UPDATE applications SET role='Unknown role' WHERE source_application_id=?",(AID,))
    advance(client)
    job=store.rows('SELECT state,error FROM jobs WHERE application_id=?',(AID,))[0]
    assert job['state']=='blocked' and 'company and role' in job['error']


def test_sync_keeps_saved_posting_link_when_source_omits_it(client):
    store=client.app.state.store
    store.apply_snapshot([{**row(AID,'COMPLETED'),'url':''}])
    assert store.rows('SELECT job_url FROM applications WHERE source_application_id=?',(AID,))[0]['job_url']=='https://example.com/fictional-job'


def test_events_order_by_instant_and_store_utc(client):
    events=[{'id':1,'kind':'dm_sent','created_at':'2026-10-20T10:00:00+00:00'},
            {'id':2,'kind':'followup_sent','created_at':'2026-10-20T08:00:00-05:00'}]
    assert state_for(events)['followup_due_at']=='2026-10-27T13:00:00+00:00'
    client.post(f'/api/applications/{AID}/research');advance(client)
    cid=client.get('/api/state').json()['contacts'][0]['id']
    assert client.post(f'/api/contacts/{cid}/events',json={'kind':'dm_sent','request_id':'fictional-offset-1','created_at':'2026-01-02T08:00:00-05:00'}).status_code==200
    assert client.app.state.store.rows('SELECT created_at FROM outreach_events')[0]['created_at']=='2026-01-02T13:00:00+00:00'


def test_invitation_undo_requires_acceptance_undo_first(client):
    client.post(f'/api/applications/{AID}/research');advance(client)
    cid=client.get('/api/state').json()['contacts'][0]['id']
    for i,kind in enumerate(('invitation_sent','connection_accepted')):
        assert client.post(f'/api/contacts/{cid}/events',json={'kind':kind,'request_id':f'fictional-undo-{i}'}).status_code==200
    events={e['kind']:e['id'] for e in client.get('/api/state').json()['contacts'][0]['events']}
    assert client.post(f"/api/contacts/{cid}/events/{events['invitation_sent']}/undo").status_code==400
    assert client.post(f"/api/contacts/{cid}/events/{events['connection_accepted']}/undo").status_code==200
    assert client.post(f"/api/contacts/{cid}/events/{events['invitation_sent']}/undo").status_code==200


def test_chunked_body_without_length_is_rejected(client):
    response=client.post('/api/sync',content=iter([b'{}']),headers={'content-type':'application/json'})
    assert response.status_code==411


def test_note_repair_uses_versioned_experience(client):
    store=client.app.state.store;repo=client.app.state.engine.experience
    client.post(f'/api/applications/{AID}/research');advance(client)
    fid=repo.save(ExperienceInput(text='I built a fictional queue.',status='approved'))
    long_note='x'*260
    with store.db() as db:
        db.execute('UPDATE drafts SET note=?,grounding=?',(long_note,'{"generated_note":"'+long_note+'","note_fact_ids":["'+fid+'"]}'))
    assert repair_notes(store)['repaired']==0
    assert repair_notes(store,repo)['repaired']==1


def test_quality_counts_placeholder_roles():
    apps=[{'source_status':'COMPLETED','role':'Unknown role'},{'source_status':'COMPLETED','role':'Engineer'}]
    assert summary(apps,[],200)['missing_roles']==1


def test_staged_import_creates_no_backups(tmp_path):
    source=Store(tmp_path/'seed.sqlite')
    from backend.demo import seed
    seed(source.path)
    staged=tmp_path/'outreach.sqlite.initializing'
    staged.write_bytes(source.path.read_bytes())
    Store(staged,backups=False).initialize()
    assert sorted(p.name for p in tmp_path.iterdir() if 'before' in p.name)==[]


def test_company_placeholder_is_missing(client):
    store=client.app.state.store
    store.apply_snapshot([row(AID,'COMPLETED'),{**row('FICTIONAL-NOCOMPANY','COMPLETED'),'companyName':'Unknown company'}])
    assert store.rows("SELECT * FROM jobs WHERE application_id='FICTIONAL-NOCOMPANY'")==[]
    assert client.post('/api/applications/FICTIONAL-NOCOMPANY/research').status_code==400


def test_dismissal_is_not_a_correction_or_review(client):
    client.post(f'/api/applications/{AID}/research');advance(client)
    c=client.get('/api/state').json()['contacts'][0]
    body={'name':c['name'],'title':c['title'] or '','company':c['company'] or '','linkedin_url':c['linkedin_url'],
          'review_status':c['review_status'],'review_note':c['review_note'],'review_source':c['review_source'] or ''}
    for dismissed in (True,False):
        assert client.put(f"/api/contacts/{c['id']}",json={**body,'dismissed':dismissed}).status_code==200
    saved=client.app.state.store.rows('SELECT original_fields,reviewed_at,dismissed FROM contacts')[0]
    assert saved=={'original_fields':None,'reviewed_at':None,'dismissed':0}
    assert client.put(f"/api/contacts/{c['id']}",json={**body,'title':'Corrected fictional title','dismissed':False}).status_code==200
    assert client.app.state.store.rows('SELECT original_fields FROM contacts')[0]['original_fields']


def test_short_aliases_ignore_ordinary_phrases():
    from backend.skill_evidence import skills
    assert skills('Take the helm of the roadmap')==set() and skills('Deploy Helm charts')=={'helm'}
    assert skills('Active TS/SCI clearance')==set() and skills('TS services')=={'typescript'}
    assert skills('Add 5 ml of solution')==set() and skills('Applied ML')=={'machine learning'}


def test_bootstrap_reports_local_mode(client):
    assert client.get('/api/bootstrap').json()['remote'] is False


def remote_client(tmp_path,monkeypatch):
    import json
    from fastapi.testclient import TestClient
    from backend.auth import hash_password
    from backend.main import create_app
    monkeypatch.setenv('OUTREACH_DEMO','true');monkeypatch.setenv('OUTREACH_DB',str(tmp_path/'fictional.sqlite'))
    monkeypatch.setenv('OUTREACH_REMOTE','true');monkeypatch.setenv('EXTERNAL_BASE_URL','https://outreach.example.com')
    monkeypatch.setenv('ALLOWED_HOSTS','outreach.example.com');monkeypatch.setenv('ALLOWED_ORIGINS','https://outreach.example.com')
    monkeypatch.setenv('SESSION_SECRET','fictional-test-session-key-32-characters')
    monkeypatch.setenv('OUTREACH_USERS',json.dumps({'operator':{'role':'operator','password_hash':hash_password('fictional-password')}}))
    return TestClient(create_app(start_worker=False),base_url='https://outreach.example.com')


def login(c,username,password):
    import re
    nonce=re.search('name="csrf" value="([^"]+)"',c.get('/login').text)[1]
    return c.post('/login',content=f'csrf={nonce}&username={username}&password={password}',follow_redirects=False)


def test_login_page_does_not_sign_out_active_session(tmp_path,monkeypatch):
    with remote_client(tmp_path,monkeypatch) as c:
        assert login(c,'operator','fictional-password').status_code==303
        assert c.get('/login').status_code==200
        assert c.get('/api/bootstrap').status_code==200


def test_rotating_usernames_hits_address_limit(tmp_path,monkeypatch):
    with remote_client(tmp_path,monkeypatch) as c:
        codes=[login(c,f'fictional-user-{i}','wrong').status_code for i in range(21)]
        assert codes[:20]==[401]*20 and codes[20]==429
        assert login(c,'operator','fictional-password').status_code==429


def test_search_query_strips_quotes(monkeypatch):
    from backend.research import Serper
    seen={}
    async def results(self,query):seen['q']=query;return []
    monkeypatch.setattr(Serper,'results',results)
    asyncio.run(Serper(None).search('Cedar "Labs"','Engineer'))
    assert seen['q'].startswith('"Cedar Labs" (')


def test_note_limit_is_hard_for_changed_notes(client):
    client.post(f'/api/applications/{AID}/research');advance(client)
    c=client.get('/api/state').json()['contacts'][0];cid=c['id']
    response=client.put(f'/api/contacts/{cid}/drafts',json={'note':'x'*201,'dm':c['dm']})
    assert response.status_code==400 and '200-character limit' in response.json()['detail']
    assert client.put(f'/api/contacts/{cid}/drafts',json={'note':'😀'*200,'dm':c['dm']}).status_code==200


def test_legacy_long_note_does_not_block_dm_but_blocks_copy(client):
    from backend.outreach import prepare
    client.post(f'/api/applications/{AID}/research');advance(client)
    store=client.app.state.store
    cid=client.get('/api/state').json()['contacts'][0]['id']
    with store.db() as db:db.execute('UPDATE drafts SET note=? WHERE contact_id=?',('y'*250,cid))
    assert client.put(f'/api/contacts/{cid}/drafts',json={'note':'y'*250,'dm':'Edited fictional DM'}).status_code==200
    with pytest.raises(ValueError,match='character limit'):prepare(store,cid,'note')

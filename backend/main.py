import asyncio
import hashlib
import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from backend.store import Store, now
from backend.security import Keychain, Unavailable, Retryable, public_url
from backend.contact_evidence import backfill_titles, assess_relevance
from backend.details import baseline_valid, protection, contact_support, sync_metadata
from backend.tsenta import Tsenta
from backend.research import Serper, Ollama
from backend.engine import Engine
from backend.outreach import state_for, record_event, prepare

ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
os.umask(0o077)


class SettingsInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    facts_text: str=Field(max_length=12000)
    facts_approved: bool
    note_limit: int=Field(ge=80,le=200)
    dm_limit: int=Field(ge=300,le=5000)

class KeyInput(BaseModel):
    key: str=Field(min_length=10,max_length=500)

class DraftInput(BaseModel):
    note: str=Field(max_length=5000)
    dm: str=Field(max_length=5000)

class EventInput(BaseModel):
    kind: str
    note: str=Field(default='',max_length=3000)
    request_id: str=Field(min_length=12,max_length=100)
    created_at: str | None=None

class OutcomeInput(BaseModel):
    outcome: Literal['unknown','rejected','job_closed','interviewing','offer']
    note: str=Field(default='',max_length=1000)

class ContactInput(BaseModel):
    name: str=Field(min_length=1,max_length=120)
    title: str=Field(default='',max_length=160)
    company: str=Field(default='',max_length=160)
    linkedin_url: str
    review_status: Literal['needs_review','supported','conflicting']='needs_review'
    review_note: str=Field(default='',max_length=1500)
    review_source: str=Field(default='',max_length=2048)
    dismissed: bool=False

class ConnectionInput(BaseModel):
    status: Literal['unknown','not_connected','connected']


def create_app(store=None,tsenta=None,search=None,ollama=None,vault=None,start_worker=True):
    demo=os.getenv('OUTREACH_DEMO','false').lower()=='true'
    if store is None:
        default='.local/demo.sqlite' if demo else '.local/outreach.sqlite'
        path=(ROOT/os.getenv('OUTREACH_DB',default)).resolve()
        if demo and path==(ROOT/'.local/outreach.sqlite').resolve():
            raise RuntimeError('Demo mode cannot use the live database.')
        if demo:
            from backend.demo import seed
            seed(path)
        store=Store(path)
    store.initialize()
    backfill_titles(store)
    if store.path==(ROOT/'.local/outreach.sqlite').resolve():
        from backend.details import backfill_captures
        backfill_captures(store,ROOT/'.local')
    if demo:
        from backend.demo import MemorySecrets,FixtureTsenta,FixtureSearch,FixtureOllama
        vault=vault or MemorySecrets(); tsenta=tsenta or FixtureTsenta(store)
        search=search or FixtureSearch();ollama=ollama or FixtureOllama()
        if not store.settings()['facts']:
            store.settings_save({'facts':[{'id':'fictional-fact','text':'I built a fictional Python project.'}],'note_limit':200,'dm_limit':1200})
    else:
        vault=vault or Keychain();tsenta=tsenta or Tsenta(vault);search=search or Serper(vault);ollama=ollama or Ollama()
    engine=Engine(store,tsenta,search,ollama)
    if demo:engine.poll_active=False
    csrf=secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        task=asyncio.create_task(engine.run()) if start_worker else None
        yield
        engine.stop.set()
        if task:
            task.cancel()
            try:await task
            except asyncio.CancelledError:pass

    app=FastAPI(title='Application Outreach Assistant',lifespan=lifespan,docs_url=None,redoc_url=None)
    app.state.store=store;app.state.engine=engine;app.state.csrf=csrf

    @app.middleware('http')
    async def local_only(request,call_next):
        if request.headers.get('host') not in ('127.0.0.1:8765','localhost:8765','127.0.0.1:5173','testserver'):
            return JSONResponse({'detail':'Local host required'},status_code=403)
        origin=request.headers.get('origin')
        if origin and origin not in ('http://127.0.0.1:8765','http://localhost:8765','http://127.0.0.1:5173'):
            return JSONResponse({'detail':'Cross-origin access denied'},status_code=403)
        path=request.url.path
        public=path in ('/api/bootstrap','/api/tsenta/callback')
        if path.startswith('/api/') and not public:
            if not secrets.compare_digest(request.headers.get('x-outreach-token',''),csrf):
                return JSONResponse({'detail':'Reload the local dashboard to establish a session'},status_code=403)
        if request.method in ('POST','PUT','PATCH'):
            try:size=int(request.headers.get('content-length','0'))
            except ValueError:return JSONResponse({'detail':'Invalid content length'},status_code=400)
            if size>100000:return JSONResponse({'detail':'Request is too large'},status_code=413)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request,error):return JSONResponse({'detail':'Invalid or oversized input. Check the form fields.'},status_code=422)
    @app.exception_handler(ValueError)
    async def value_error(request,error):return JSONResponse({'detail':str(error)},status_code=400)
    @app.exception_handler(Unavailable)
    async def unavailable(request,error):return JSONResponse({'detail':str(error)},status_code=409)
    @app.exception_handler(Retryable)
    async def temporary(request,error):return JSONResponse({'detail':str(error)},status_code=503)

    @app.get('/api/bootstrap')
    def bootstrap():return {'token':csrf,'demo':demo}

    @app.get('/api/state')
    def state():
        applications=store.rows('''SELECT source_application_id,company,role,job_url,job_description,submitted_at,
            source_status,normalized_status,source_created_at,source_updated_at,historical,selected,first_seen,first_confirmed,
            company_website,locations,research_state,last_error,missing_fields,confirmed_at_baseline,source_job_status,hiring_outcome,outcome_note,
            outcome_updated_at,details_checked_at,details_error,job_id FROM applications ORDER BY historical,first_seen DESC,source_created_at DESC''')
        valid=baseline_valid(store)
        jobs={j['application_id']:j for j in store.rows('SELECT * FROM jobs')}
        for row in applications:
            row['historical']=bool(row['historical'])
            row['selected']=bool(row['selected'])
            row['selected_for_research']=row['selected']
            row['missing_fields']=json.loads(row['missing_fields'])
            row['locations']=json.loads(row['locations'] or '[]')
            row['protection']=protection(row,valid)
            row['job']=jobs.get(row['source_application_id'])
            row['submission_explanation']='Tsenta’s verified application responses provide createdAt and updatedAt, but no submission timestamp. Neither is used as a submission date.'
            row['description_explanation']=row['details_error'] or ('Tsenta application reads omit the description. Check posting details to try its separate read-only job tool.' if row['job_id'] else 'No job ID was supplied by Tsenta, so its separate posting-details tool cannot be queried.')
        contacts=store.rows('''SELECT c.*,d.note,d.dm,d.grounding,a.company AS application_company,a.role,
            a.submitted_at AS application_submitted_at,a.source_status,a.historical,a.hiring_outcome FROM contacts c JOIN applications a ON a.source_application_id=c.application_id
            LEFT JOIN drafts d ON d.contact_id=c.id ORDER BY c.application_id,c.rank''')
        events=store.rows('SELECT * FROM outreach_events ORDER BY id')
        for contact in contacts:
            contact['dismissed']=bool(contact['dismissed'])
            contact['historical']=bool(contact['historical'])
            contact['evidence']=json.loads(contact['evidence'])
            contact['grounding']=json.loads(contact['grounding'] or '{}')
            contact['events']=[event for event in events if event['contact_id']==contact['id']]
            contact['conversation']=state_for(contact['events'],contact['connection_status'],outcome=contact['hiring_outcome'])
            contact['support']=contact_support(contact)
            contact['relevance_assessment']=assess_relevance(contact)
            same_company=[c['id'] for c in contacts if (c['application_company'] or '').strip().casefold()==(contact['application_company'] or '').strip().casefold()]
            same_profile=[c['id'] for c in contacts if c['linkedin_url']==contact['linkedin_url']]
            contact['prior_outreach_count']=sum(e['kind'] in ('invitation_sent','dm_sent','followup_sent') and not e['undone_at'] for e in events if e['contact_id'] in set(same_company+same_profile))
        baseline=store.rows('SELECT imported_at,record_count FROM baseline')[0]
        last=store.rows('SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1')
        success=store.rows("SELECT finished_at FROM sync_runs WHERE state='done' ORDER BY id DESC LIMIT 1")
        return {'applications':applications,'contacts':contacts,'baseline':baseline,'baseline_valid':valid,'sync':last[0] if last else None,
            'last_successful_sync':success[0]['finished_at'] if success else None,'scheduler':engine.scheduler_info(),'demo':demo}

    @app.get('/api/settings')
    async def settings():
        value=store.settings()
        try:
            connected=bool(await asyncio.to_thread(vault.get,'tsenta'))
            search_ready=bool(await asyncio.to_thread(vault.get,'serper'))
            keychain_error=None
        except Unavailable as error:connected=search_ready=False;keychain_error=str(error)
        return {**value,'tsenta_connected':connected,'search_configured':search_ready,'keychain_error':keychain_error,
                'ollama':await ollama.health(),'scheduler':engine.scheduler_info(),'demo':demo}

    @app.post('/api/settings')
    def save_settings(value:SettingsInput):
        lines=[line.strip() for line in value.facts_text.splitlines() if line.strip()]
        if lines and not value.facts_approved:raise ValueError('Approve these facts before they can be used in outreach.')
        if len(lines)>12 or any(len(line)>300 for line in lines):raise ValueError('Use at most 12 facts, each at most 300 characters, to fit the local model context.')
        facts=[{'id':hashlib.sha256(line.encode()).hexdigest()[:16],'text':line} for line in lines]
        store.settings_save({'facts':facts,'note_limit':value.note_limit,'dm_limit':value.dm_limit})
        return {'saved':True}

    @app.post('/api/settings/search-key')
    async def search_key(value:KeyInput):
        if demo:raise ValueError('Credentials are disabled in fictional demo mode')
        if any(c.isspace() for c in value.key):raise ValueError('Enter a Serper key from your own free-tier account.')
        await asyncio.to_thread(vault.put,'serper',value.key)
        return {'saved':True}

    @app.delete('/api/settings/search-key')
    async def delete_key():
        await asyncio.to_thread(vault.delete,'serper')
        return {'removed':True}

    @app.post('/api/tsenta/connect')
    async def connect():
        if demo:raise ValueError('Live account connections are disabled in fictional demo mode')
        return {'url':await tsenta.connect()}

    @app.get('/api/tsenta/callback',response_class=HTMLResponse)
    async def callback(state:str='',code:str='',error:str=''):
        if demo:return HTMLResponse('Live sign-in disabled in demo.',status_code=400)
        try:
            await tsenta.callback(state,code if not error else '')
            store.enqueue_sync()
            text='Tsenta connected securely. A one-time sync is queued; recurring polling remains separately controlled.'
        except (Unavailable,Retryable):text='Connection did not complete. Return to Settings and try again.'
        return HTMLResponse('<!doctype html><title>Tsenta connection</title><p>'+text+'</p><a href="/">Return to dashboard</a>')

    @app.delete('/api/tsenta/connection')
    async def disconnect():
        await asyncio.to_thread(vault.delete,'tsenta')
        if hasattr(tsenta,'session_headers'):tsenta.session_headers=None
        return {'removed':True}

    @app.post('/api/sync')
    def sync():return {'run_id':store.enqueue_sync()}

    @app.post('/api/applications/{aid}/research')
    def research(aid:str):
        store.select_application(aid)
        return {'queued':True}

    @app.put('/api/applications/{aid}/outcome')
    def outcome(aid:str,value:OutcomeInput):
        with store.db() as db:
            if not db.execute('SELECT 1 FROM applications WHERE source_application_id=?',(aid,)).fetchone():raise ValueError('Application not found')
            db.execute('UPDATE applications SET hiring_outcome=?,outcome_note=?,outcome_updated_at=? WHERE source_application_id=?',(value.outcome,value.note,now(),aid))
        return {'saved':True}

    @app.post('/api/applications/{aid}/details')
    async def details(aid:str):
        rows=store.rows('SELECT * FROM applications WHERE source_application_id=?',(aid,))
        if not rows:raise ValueError('Application not found')
        row=rows[0]
        error='Tsenta did not expose a supported job description for this application.'
        try:
            detail=await tsenta.read('get-application-status',{'applicationId':aid})
            if detail.get('applicationId')!=aid:raise Unavailable('Tsenta returned a different application; no fields saved.')
            with store.db() as db:sync_metadata(db,aid,detail)
            job_id=detail.get('jobId') or row['job_id']
            if job_id:
                # The live tool rejected historical application IDs during verification.
                # Do not guess a result mapping or substitute another posting.
                await tsenta.read('get-job-details',{'jobId':job_id})
                error='Posting tool responded, but its description mapping has not been verified. No text was substituted.'
            else:error='Tsenta returned no job ID for retrieving the full posting.'
        except (Unavailable,Retryable):
            error='Tsenta could not return posting details for this application. Its job tool may not support this historical posting; try again later or view the original posting.'
        with store.db() as db:db.execute('UPDATE applications SET details_checked_at=?,details_error=? WHERE source_application_id=?',(now(),error,aid))
        return {'checked':True,'explanation':error}

    @app.put('/api/contacts/{cid}')
    def correct_contact(cid:int,value:ContactInput):
        url=public_url(value.linkedin_url,True)
        source=public_url(value.review_source) if value.review_source else None
        if value.review_status!='needs_review' and (not source or not value.review_note.strip()):raise ValueError('Add a source URL and explain the support or conflict before setting this label.')
        with store.db() as db:
            original=db.execute('SELECT * FROM contacts WHERE id=?',(cid,)).fetchone()
            if not original:raise ValueError('Contact not found')
            saved=json.dumps({k:original[k] for k in ('name','title','company','linkedin_url')})
            db.execute('UPDATE contacts SET name=?,title=?,company=?,linkedin_url=?,review_status=?,review_note=?,review_source=?,reviewed_at=?,dismissed=?,original_fields=COALESCE(original_fields,?) WHERE id=?',
                (value.name,value.title or None,value.company or None,url,value.review_status,value.review_note,source,now(),int(value.dismissed),saved,cid))
        return {'saved':True}

    @app.put('/api/contacts/{cid}/drafts')
    def drafts(cid:int,value:DraftInput):
        limits=store.settings()
        if len(value.dm)>limits['dm_limit']:raise ValueError('Draft exceeds configured limit')
        with store.db() as db:
            existing=db.execute('SELECT note FROM drafts WHERE contact_id=?',(cid,)).fetchone()
            if not existing:raise ValueError('Draft not found')
            db.execute('UPDATE drafts SET note=?,dm=?,updated_at=? WHERE contact_id=?',(value.note,value.dm,now(),cid))
        return {'saved':True}

    @app.post('/api/contacts/{cid}/draft-suggestion')
    async def draft_suggestion(cid:int):
        from backend.research import Pick
        rows=store.rows('SELECT c.*,a.role,a.job_description,a.company AS application_company FROM contacts c JOIN applications a ON a.source_application_id=c.application_id WHERE c.id=?',(cid,))
        if not rows:raise ValueError('Contact not found')
        c=rows[0]
        pick=Pick(source_id=c['source_key'],name=c['name'],title=c['title'],company=c['company'],evidence_quote=json.loads(c['evidence'])['excerpt'][:350],relevance=c['relevance'][:240],uncertainty=c['uncertainty'][:240])
        config=store.settings()
        return await ollama.draft({'role':c['role'],'company':c['application_company'],'job_description':c['job_description'],'verified_contact_context': c['title'] if c['review_status']=='supported' and c['review_source'] else None},pick,config['facts'],config)

    @app.get('/api/contacts/{cid}/prepare')
    def prepare_action(cid:int,kind:Literal['note','dm']='note'):
        if demo:raise ValueError('External profile opening is disabled for fictional contacts.')
        return prepare(store,cid,kind)

    @app.post('/api/contacts/{cid}/events')
    def event(cid:int,value:EventInput):
        record_event(store,cid,value.kind,value.note,value.request_id,value.created_at)
        return {'recorded':True}

    @app.post('/api/contacts/{cid}/events/{eid}/undo')
    def undo(cid:int,eid:int):
        with store.db() as db:
            event=db.execute('SELECT * FROM outreach_events WHERE id=? AND contact_id=?',(eid,cid)).fetchone()
            if not event:raise ValueError('Activity not found')
            if event['kind']=='dm_sent' and db.execute("SELECT 1 FROM outreach_events WHERE contact_id=? AND kind='followup_sent' AND undone_at IS NULL",(cid,)).fetchone():raise ValueError('Undo dependent follow-up entries before undoing the original message.')
            db.execute('UPDATE outreach_events SET undone_at=COALESCE(undone_at,?) WHERE id=?',(now(),eid))
        return {'undone':True}

    @app.put('/api/contacts/{cid}/connection')
    def connection(cid:int,value:ConnectionInput):
        with store.db() as db:
            if not db.execute('SELECT 1 FROM contacts WHERE id=?',(cid,)).fetchone():raise ValueError('Contact not found')
            db.execute('UPDATE contacts SET connection_status=? WHERE id=?',(value.status,cid))
        return {'saved':True}

    @app.post('/api/demo/transition')
    def simulate():
        if not demo:raise ValueError('Fictional transitions are only available in a separate demo database')
        from backend.demo import row
        current=store.rows("SELECT source_status FROM applications WHERE source_application_id='FICTIONAL-NEW'")
        status='RUNNING' if not current else 'COMPLETED'
        rows=[row(r['source_application_id'],r['source_status']) for r in store.rows('SELECT source_application_id,source_status FROM applications') if r['source_application_id']!='FICTIONAL-NEW']
        rows.append(row('FICTIONAL-NEW',status))
        return {'source_status':status,**store.apply_snapshot(rows)}

    dist=ROOT/'frontend/dist'
    if dist.exists():app.mount('/',StaticFiles(directory=dist,html=True),name='dashboard')
    else:
        @app.get('/')
        def not_built():return HTMLResponse('Build the frontend: cd frontend &amp;&amp; npm install &amp;&amp; npm run build')
    return app

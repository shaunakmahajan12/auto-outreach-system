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
    exact_note_200: bool=True

class KeyInput(BaseModel):
    key: str=Field(min_length=10,max_length=500)

class ResearchInput(BaseModel):
    company: str | None=Field(default=None,min_length=1,max_length=300)
    role: str | None=Field(default=None,min_length=1,max_length=300)

class DraftInput(BaseModel):
    note: str=Field(max_length=5000)
    dm: str=Field(max_length=5000)
    suggestion_id: str | None=None
    suggestion_parts: list[Literal["note","dm"]] | None=None

class SuggestionFeedbackInput(BaseModel):
    parts: list[Literal['note','dm']]=Field(default_factory=lambda:['note','dm'])

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
    from backend.auth import configuration
    remote=configuration()
    demo=os.getenv('OUTREACH_DEMO','false').lower()=='true'
    if store is None:
        default='.local/demo.sqlite' if demo else '.local/outreach.sqlite'
        path=(ROOT/os.getenv('OUTREACH_DB',default)).resolve()
        if demo and path==(ROOT/'.local/outreach.sqlite').resolve():
            raise RuntimeError('Demo mode cannot use the live database.')
        if demo:
            from backend.demo import seed
            seed(path)
        if os.getenv("DATABASE_URL") and not demo:
            from backend.postgres_store import PostgresStore
            store=PostgresStore(os.environ["DATABASE_URL"],ROOT/".local/postgres.marker")
            store.initialize()
        else:store=Store(path)
    if store.path.exists():
        store.initialize()
        backfill_titles(store)
    if not hasattr(store,'engine') and store.path.exists() and store.path==(ROOT/'.local/outreach.sqlite').resolve():
        from backend.details import backfill_captures
        backfill_captures(store,ROOT/'.local')
    if demo:
        from backend.demo import MemorySecrets,FixtureTsenta,FixtureSearch,FixtureOllama
        vault=vault or MemorySecrets(); tsenta=tsenta or FixtureTsenta(store)
        search=search or FixtureSearch();ollama=ollama or FixtureOllama()
        if not store.settings()['facts']:
            store.settings_save({'facts':[{'id':'fictional-fact','text':'I built a fictional Python project.'}],'note_limit':200,'dm_limit':1200})
    else:
        from backend.security import DeploymentSecrets, AwsSecrets
        vault=vault or (AwsSecrets(os.environ["AWS_CREDENTIAL_SECRET_ID"]) if os.getenv("AWS_CREDENTIAL_SECRET_ID") else DeploymentSecrets() if os.getenv("CREDENTIAL_STORE")=="deployment" else Keychain());tsenta=tsenta or Tsenta(vault);search=search or Serper(vault);ollama=ollama or Ollama()
    from backend.experience import ExperienceRepository
    experience=ExperienceRepository(store)
    if store.path.exists():experience.initialize()
    engine=Engine(store,tsenta,search,ollama)
    engine.experience=experience
    if demo:engine.poll_active=False
    csrf=secrets.token_urlsafe(32)
    onboarding_lock=asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        if start_worker and not demo and store.path.exists() and baseline_valid(store):
            store.enqueue_sync()
        if start_worker and store.path.exists():engine.recover_pending()
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
        health_probe=request.url.path in ('/health','/ready')
        if not health_probe and request.headers.get('host') not in (remote['hosts'] if remote else ('127.0.0.1:8765','localhost:8765','127.0.0.1:5173','testserver')):
            return JSONResponse({'detail':'Local host required'},status_code=403)
        origin=request.headers.get('origin')
        if origin and origin not in (remote['origins'] if remote else ('http://127.0.0.1:8765','http://localhost:8765','http://127.0.0.1:5173')):
            return JSONResponse({'detail':'Cross-origin access denied'},status_code=403)
        path=request.url.path
        public=path in ('/api/bootstrap','/api/tsenta/callback')
        token=csrf
        if remote and path not in ('/login','/health','/ready'):
            import time
            user=remote['users'].get(request.session.get('user',''))
            if not user or request.session.get('expires',0)<time.time():
                if not path.startswith('/api/'):return __import__('fastapi').responses.RedirectResponse('/login')
                return JSONResponse({'detail':'Authentication required'},status_code=401)
            if (request.method not in ('GET','HEAD') or path=='/api/tsenta/callback') and user['role']!='operator':return JSONResponse({'detail':'Operator role required'},status_code=403)
            token=request.session.get('csrf','')
            public=path=='/api/bootstrap' or (path=='/api/tsenta/callback' and request.method=='GET')
        if path.startswith('/api/') and not public:
            if not secrets.compare_digest(request.headers.get('x-outreach-token',''),token):
                return JSONResponse({'detail':'Reload the local dashboard to establish a session'},status_code=403)
        if not store.path.exists() and path.startswith('/api/') and path not in (
            '/api/bootstrap','/api/state','/api/settings','/api/settings/search-key',
            '/api/tsenta/connect','/api/tsenta/callback','/api/tsenta/connection','/api/onboarding/initialize'):
            return JSONResponse({'detail':'Connect Tsenta and import your initial history in Settings first.'},status_code=409)
        if not store.path.exists() and path=='/api/settings' and request.method!='GET':
            return JSONResponse({'detail':'Import your initial history before saving approved facts.'},status_code=409)
        if request.method in ('POST','PUT','PATCH'):
            try:size=int(request.headers.get('content-length','0'))
            except ValueError:return JSONResponse({'detail':'Invalid content length'},status_code=400)
            if size>100000:return JSONResponse({'detail':'Request is too large'},status_code=413)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['Referrer-Policy']='same-origin' if remote else 'no-referrer'
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
    def bootstrap(request:Request):return {'token':request.session.get('csrf') if remote else csrf,'demo':demo,'onboarding_required':not store.path.exists()}

    @app.get('/api/state')
    def state(request:Request):
        if not store.path.exists():
            return {'applications':[],'contacts':[],'baseline':None,'baseline_valid':False,
                'onboarding_required':True,'sync':None,'last_successful_sync':None,
                'scheduler':engine.scheduler_info(),'demo':demo,'quality':{}}
        applications=store.rows('''SELECT source_application_id,company,role,job_url,job_description,submitted_at,
            source_status,normalized_status,source_created_at,source_updated_at,historical,selected,first_seen,first_confirmed,
            company_website,locations,research_state,last_error,missing_fields,confirmed_at_baseline,source_job_status,hiring_outcome,outcome_note,
            outcome_updated_at,details_checked_at,details_error,job_id FROM applications ORDER BY historical,first_seen DESC,source_created_at DESC''')
        valid=baseline_valid(store)
        jobs={j['application_id']:j for j in store.rows('SELECT * FROM jobs')}
        role_candidates={r['application_id']:r for r in store.rows('SELECT * FROM posting_roles WHERE saved_at IS NULL')}
        for row in applications:
            candidate=role_candidates.get(row['source_application_id'])
            row['role_candidate']=candidate if candidate and candidate['posting_url']==row['job_url'] else None
            row['historical']=bool(row['historical'])
            row['selected']=bool(row['selected'])
            row['selected_for_research']=row['selected']
            row['missing_fields']=json.loads(row['missing_fields'])
            row['locations']=json.loads(row['locations'] or '[]')
            row['protection']=protection(row,valid)
            row['job']=jobs.get(row['source_application_id'])
            row['submission_explanation']='Tsenta’s verified application responses provide createdAt and updatedAt, but no submission timestamp. Neither is used as a submission date.'
            row['description_explanation']=row['details_error'] or ('Tsenta application reads omit the description. Check posting details to try its separate read-only job tool.' if row['job_id'] else 'No job ID was supplied by Tsenta, so its separate posting-details tool cannot be queried.')
        contacts=store.rows('''SELECT c.*,d.note,d.dm,d.grounding,a.company AS application_company,a.company_website,a.role,
            a.submitted_at AS application_submitted_at,a.source_status,a.historical,a.hiring_outcome FROM contacts c JOIN applications a ON a.source_application_id=c.application_id
            LEFT JOIN drafts d ON d.contact_id=c.id ORDER BY c.application_id,c.rank''')
        events=store.rows('SELECT * FROM outreach_events ORDER BY id')
        events_by_contact={}
        sent_by_contact={}
        company_contacts={}
        profile_contacts={}
        for event in events:
            events_by_contact.setdefault(event['contact_id'],[]).append(event)
            if event['kind'] in ('invitation_sent','dm_sent','followup_sent') and not event['undone_at']:
                sent_by_contact[event['contact_id']]=sent_by_contact.get(event['contact_id'],0)+1
        for contact in contacts:
            company=(contact['application_company'] or '').strip().casefold()
            company_contacts.setdefault(company,set()).add(contact['id'])
            profile_contacts.setdefault(contact['linkedin_url'],set()).add(contact['id'])
        for contact in contacts:
            contact['dismissed']=bool(contact['dismissed'])
            contact['historical']=bool(contact['historical'])
            contact['evidence']=json.loads(contact['evidence'])
            contact['grounding']=json.loads(contact['grounding'] or '{}')
            contact['events']=events_by_contact.get(contact['id'],[])
            contact['conversation']=state_for(contact['events'],contact['connection_status'],outcome=contact['hiring_outcome'])
            contact['support']=contact_support(contact)
            contact['relevance_assessment']=assess_relevance(contact)
            same_company=company_contacts[(contact['application_company'] or '').strip().casefold()]
            same_profile=profile_contacts[contact['linkedin_url']]
            contact['prior_outreach_count']=sum(sent_by_contact.get(cid,0) for cid in same_company | same_profile)
        baseline=store.rows('SELECT imported_at,record_count FROM baseline')[0]
        last=store.rows('SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1')
        success=store.rows("SELECT finished_at FROM sync_runs WHERE state='done' ORDER BY id DESC LIMIT 1")
        from backend.quality import summary
        payload={'applications':applications,'contacts':contacts,'baseline':baseline,'baseline_valid':valid,'sync':last[0] if last else None,
            'last_successful_sync':success[0]['finished_at'] if success else None,'scheduler':engine.scheduler_info(),'demo':demo,
            'onboarding_required':False,'quality':summary(applications,contacts,store.settings()['note_limit'])}
        encoded=json.dumps(payload,separators=(',',':'),ensure_ascii=False).encode()
        etag='"'+hashlib.sha256(encoded).hexdigest()+'"'
        from fastapi.responses import Response
        if request.headers.get('if-none-match')==etag:
            return Response(status_code=304,headers={'ETag':etag})
        return Response(content=encoded,media_type='application/json',headers={'ETag':etag})


    @app.get('/health')
    def health():return {'status':'ok'}

    @app.get('/ready')
    def ready():
        try:available=store.path.exists() and baseline_valid(store)
        except Exception:available=False
        return JSONResponse({'ready':available},status_code=200 if available else 503)

    from backend.experience import ExperienceInput
    from backend.matching import prepare_match
    class DescriptionInput(BaseModel):
        model_config=ConfigDict(extra='forbid')
        text: str=Field(max_length=5000)
        source_url: str=Field(default='',max_length=2048)
    @app.put('/api/applications/{aid}/description')
    def description(aid:str,value:DescriptionInput):
        if value.source_url:public_url(value.source_url)
        with store.db() as db:
            if not db.execute('SELECT 1 FROM applications WHERE source_application_id=?',(aid,)).fetchone():raise ValueError('Application not found')
            existing=db.execute('SELECT version FROM descriptions WHERE application_id=?',(aid,)).fetchone()
            version=existing['version']+1 if existing else 1
            db.execute('INSERT OR REPLACE INTO descriptions VALUES(?,?,?,?,?,?)',(aid,value.text,value.source_url,'manual paste',now(),version))
            db.execute('UPDATE applications SET job_description=? WHERE source_application_id=?',(value.text or None,aid))
            db.execute('DELETE FROM match_reviews WHERE application_id=?',(aid,))
        return {'saved':True,'version':version}

    @app.get('/api/applications/{aid}/description')
    def get_description(aid:str):
        rows=store.rows('SELECT * FROM descriptions WHERE application_id=?',(aid,))
        apps=store.rows('SELECT job_description FROM applications WHERE source_application_id=?',(aid,))
        if not apps:raise ValueError('Application not found')
        return rows[0] if rows else {'text':apps[0]['job_description'] or '', 'source_url':'','provenance':'existing source' if apps[0]['job_description'] else 'not supplied','updated_at':None}

    @app.post('/api/applications/{aid}/matches')
    async def review_matches(aid:str):
        rows=store.rows('SELECT * FROM applications WHERE source_application_id=?',(aid,))
        if not rows:raise ValueError('Application not found')
        cached=store.rows('SELECT data FROM match_reviews WHERE application_id=?',(aid,))
        if cached:
            saved=json.loads(cached[0]['data'])
            if saved.get('description_hash')==hashlib.sha256((rows[0]['job_description'] or '').encode()).hexdigest() and saved.get('experience_revision')==experience.revision() and saved.get('role')==rows[0]['role']:
                return saved
        result=await prepare_match(experience,ollama,rows[0])
        result['role']=rows[0]['role']
        current=store.rows('SELECT job_description FROM applications WHERE source_application_id=?',(aid,))[0]
        if (current['job_description'] or '')!=(rows[0]['job_description'] or ''):raise Retryable('Description changed during extraction. Review matches again.')
        with store.db() as db:db.execute('INSERT OR REPLACE INTO match_reviews VALUES(?,?,?)',(aid,json.dumps(result),now()))
        return result

    @app.get('/api/experience')
    def experience_list():return {'experience':[{k:v for k,v in f.items() if k!='embedding'} for f in experience.list()]}

    @app.post('/api/experience')
    def experience_create(value:ExperienceInput):return {'id':experience.save(value)}

    @app.put('/api/experience/{fid}')
    def experience_edit(fid:str,value:ExperienceInput):
        if fid not in {f['id'] for f in experience.list()}:raise ValueError('Experience not found')
        return {'id':experience.save(value,fid)}

    @app.get('/api/metrics/feedback')
    def feedback_metrics():
        rows=store.rows('SELECT accepted,edited FROM message_feedback')
        legacy=store.rows('SELECT accepted,edited FROM draft_feedback WHERE suggestion_id NOT IN (SELECT suggestion_id FROM message_feedback)')
        # Legacy combined observations remain stored but cannot be attributed per message.
        count=len(rows)
        return {'observations':count,'acceptance_rate':sum(r['accepted'] for r in rows)/count if count else None,
            'edit_rate':sum(r['edited'] for r in rows if r['accepted'])/sum(r['accepted'] for r in rows) if any(r['accepted'] for r in rows) else None,
            'status':'observed' if count else 'insufficient data',
            'legacy_observations':len(legacy),
            'messages':{kind:store.rows('SELECT accepted,edited FROM message_feedback WHERE kind=?',(kind,)) for kind in ('note','dm')}}

    @app.post('/api/draft-suggestions/{sid}/reject')
    def reject_suggestion(sid:str,value:SuggestionFeedbackInput=SuggestionFeedbackInput()):
        with store.db() as db:
            if not db.execute('SELECT 1 FROM draft_suggestions WHERE id=?',(sid,)).fetchone():raise ValueError('Suggestion not found')
            for kind in set(value.parts):
                db.execute('INSERT OR IGNORE INTO message_feedback(suggestion_id,kind,accepted,edited,created_at) VALUES(?,?,0,0,?)',(sid,kind,now()))
        return {'saved':True}

    @app.get('/api/settings')
    async def settings():
        value=store.settings()
        try:
            connected=bool(await asyncio.to_thread(vault.get,'tsenta'))
            search_ready=bool(await asyncio.to_thread(vault.get,'serper'))
            keychain_error=None
        except Unavailable as error:connected=search_ready=False;keychain_error=str(error)
        return {**value,'approved_experience_count':len(experience.list(approved=True)) if store.path.exists() else 0,
                'tsenta_connected':connected,'search_configured':search_ready,'keychain_error':keychain_error,
                'ollama':await ollama.health(),'scheduler':engine.scheduler_info(),'demo':demo,'onboarding_required':not store.path.exists()}

    @app.post('/api/settings')
    def save_settings(value:SettingsInput):
        lines=[line.strip() for line in value.facts_text.splitlines() if line.strip()]
        if lines and not value.facts_approved:raise ValueError('Approve these facts before they can be used in outreach.')
        if len(lines)>12 or any(len(line)>300 for line in lines):raise ValueError('Use at most 12 facts, each at most 300 characters, to fit the local model context.')
        facts=[{'id':hashlib.sha256(line.encode()).hexdigest()[:16],'text':line} for line in lines]
        store.settings_save({'facts':facts,'note_limit':200 if value.exact_note_200 else value.note_limit,'dm_limit':value.dm_limit,'exact_note_200':value.exact_note_200})
        experience.initialize()
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
            if store.path.exists():store.enqueue_sync()
            text='Tsenta connected securely. Return to Settings to import your initial history.' if not store.path.exists() else 'Tsenta connected securely. A one-time sync is queued; recurring polling remains separately controlled.'
        except (Unavailable,Retryable):text='Connection did not complete. Return to Settings and try again.'
        return HTMLResponse('<!doctype html><title>Tsenta connection</title><p>'+text+'</p><a href="/">Return to dashboard</a>')

    @app.delete('/api/tsenta/connection')
    async def disconnect():
        await asyncio.to_thread(vault.delete,'tsenta')
        if hasattr(tsenta,'session_headers'):tsenta.session_headers=None
        return {'removed':True}

    @app.post('/api/onboarding/initialize')
    async def initialize_history():
        if demo:raise ValueError('The fictional workspace is already initialized.')
        async with onboarding_lock:
            if store.path.exists():raise ValueError('A database already exists. Your original baseline cannot be replaced.')
            rows=await tsenta.snapshot()
            # snapshot() has already validated the complete, unfiltered source history.
            from scripts.tsenta_baseline import save_baseline
            limit=100;total=len(rows);pages=max(1,(total+limit-1)//limit)
            captures=[{'tool':'list-applications','arguments':{'filter':'all','page':i+1,'limit':limit},
                'response':{'result':{'structuredContent':{'tool':'list-applications','result':{
                    'applications':rows[i*limit:(i+1)*limit],
                    'pagination':{'page':i+1,'limit':limit,'total':total,'totalPages':pages}}}}}}
                for i in range(pages)]
            # Build and migrate privately before publishing the initialized database.
            temporary=store.path.with_name(store.path.name+'.initializing')
            if temporary.exists():raise Unavailable('An interrupted initial import needs attention. Remove only the .initializing file after reviewing it, then retry.')
            from backend.store import Store
            try:
                save_baseline(captures,temporary)
                staged=Store(temporary);staged.initialize()
                if not baseline_valid(staged):raise Unavailable('Initial history validation failed.')
                # Hard link publishes atomically and refuses to overwrite an existing file.
                os.link(temporary,store.path)
            finally:
                temporary.unlink(missing_ok=True)
            experience.initialize()
            return {'imported':total}

    @app.post('/api/maintenance/repair-notes')
    async def repair_generated_notes():
        from backend.maintenance import repair_notes
        return await asyncio.to_thread(repair_notes,store)

    @app.post('/api/sync')
    def sync():return {'run_id':store.enqueue_sync()}

    def queue_changed_version(aid):
        from backend.preparation import eligible,input_version
        app_row=eligible(store,aid)
        version=input_version(app_row,experience)
        if not store.rows('SELECT id FROM preparation_runs WHERE application_id=? AND input_version=?',(aid,version)):
            with store.db() as db:
                db.execute("UPDATE jobs SET state='queued',stage='queued',attempts=0,error=NULL WHERE application_id=? AND state='done'",(aid,))
                db.execute("UPDATE applications SET research_state=(SELECT state FROM jobs WHERE application_id=?) WHERE source_application_id=?",(aid,aid))

    @app.post('/api/applications/{aid}/research')
    def research(aid:str,value:ResearchInput | None=None):
        store.select_application(aid,company=value.company if value else None,role=value.role if value else None)
        queue_changed_version(aid)
        return {'queued':True}

    @app.get('/api/applications/{aid}/preparation')
    async def preparation_status(aid:str):
        from backend.preparation import status
        return await status(engine,aid)

    @app.post('/api/applications/{aid}/preparation/resume')
    async def preparation_resume(aid:str):
        from backend.preparation import eligible
        eligible(store,aid)
        with store.db() as db:db.execute('INSERT OR IGNORE INTO preparation_resume_requests VALUES(?)',(aid,))
        store.select_application(aid)
        queue_changed_version(aid)
        return {'queued':True}

    @app.post('/api/applications/{aid}/research/dismiss')
    def dismiss_research(aid:str):
        store.dismiss_preparation(aid)
        return {'dismissed':True}

    @app.post('/api/applications/{aid}/extract-role')
    async def extract_role(aid:str):
        from backend.posting_role import missing_role, inspect_posting
        rows=store.rows('SELECT role,job_url FROM applications WHERE source_application_id=?',(aid,))
        if not rows:raise ValueError('Application not found')
        row=rows[0]
        if not missing_role(row['role']):raise ValueError('This application already has a role. Nothing was changed.')
        if not row['job_url']:raise ValueError('No posting link was supplied for this application.')
        result=await inspect_posting(row['job_url'])
        with store.db() as db:
            db.execute('INSERT OR REPLACE INTO posting_roles VALUES(?,?,?,?,?,?,NULL)',
                (aid,result['role'],result['source_url'],row['job_url'],result['method'],now()))
        return result

    @app.post('/api/applications/{aid}/extracted-role/save')
    def save_extracted_role(aid:str):
        from backend.posting_role import missing_role
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT role,job_url,missing_fields FROM applications WHERE source_application_id=?',(aid,)).fetchone()
            candidate=db.execute('SELECT * FROM posting_roles WHERE application_id=?',(aid,)).fetchone()
            if not row or not candidate:raise ValueError('Extract a role from this posting first.')
            if not missing_role(row['role']):raise ValueError('This application already has a role. Nothing was changed.')
            if row['job_url']!=candidate['posting_url']:raise ValueError('The posting link changed. Extract the role again.')
            missing=[field for field in json.loads(row['missing_fields']) if field!='role']
            db.execute('UPDATE applications SET role=?,missing_fields=? WHERE source_application_id=?',(candidate['role'],json.dumps(missing),aid))
            db.execute('UPDATE posting_roles SET saved_at=? WHERE application_id=?',(now(),aid))
        return {'saved':True,'role':candidate['role'],'source_url':candidate['source_url']}

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
            grounding=json.loads(db.execute('SELECT grounding FROM drafts WHERE contact_id=?',(cid,)).fetchone()[0])
            accepted=grounding.get('accepted_suggestions',{})
            if value.suggestion_id:
                suggestion=db.execute('SELECT * FROM draft_suggestions WHERE id=? AND contact_id=?',(value.suggestion_id,cid)).fetchone()
                if not suggestion:raise ValueError('Suggestion does not belong to this contact')
                from backend.personalization import validate_acceptance
                evidence=json.loads(suggestion['grounding'])
                aid=db.execute('SELECT application_id FROM contacts WHERE id=?',(cid,)).fetchone()[0]
                validate_acceptance(store,experience,aid,evidence)
                parts=value.suggestion_parts if value.suggestion_parts is not None else ['note','dm']
                if not parts:raise ValueError('Choose which suggested message to accept')
                for kind in set(parts):
                    edited=getattr(value,kind)!=suggestion[kind]
                    db.execute('INSERT INTO message_feedback(suggestion_id,kind,accepted,edited,created_at) VALUES(?,?,1,?,?) ON CONFLICT(suggestion_id,kind) DO UPDATE SET accepted=1,edited=CASE WHEN message_feedback.edited=1 OR excluded.edited=1 THEN 1 ELSE 0 END',(value.suggestion_id,kind,int(edited),now()))
                    accepted[kind]=value.suggestion_id
                # Keep evidence scoped to the applied message; untouched message retains its provenance.
                grounding.setdefault('message_grounding',{}).update({kind:evidence for kind in parts})
            for kind,sid in accepted.items():
                original=db.execute('SELECT note,dm FROM draft_suggestions WHERE id=? AND contact_id=?',(sid,cid)).fetchone()
                if original:
                    db.execute('UPDATE message_feedback SET edited=CASE WHEN edited=1 OR ?=1 THEN 1 ELSE 0 END WHERE suggestion_id=? AND kind=?',(int(getattr(value,kind)!=original[kind]),sid,kind))
            grounding['accepted_suggestions']=accepted
            grounding['dm_edited']=grounding.get('dm_edited',False) or value.dm!=db.execute('SELECT dm FROM drafts WHERE contact_id=?',(cid,)).fetchone()[0]
            if value.note!=existing['note']:grounding['note_edited']=True
            db.execute('UPDATE drafts SET note=?,dm=?,grounding=?,updated_at=? WHERE contact_id=?',(value.note,value.dm,json.dumps(grounding),now(),cid))
        return {'saved':True}

    @app.post('/api/contacts/{cid}/draft-suggestion')
    async def draft_suggestion(cid:int):
        from backend.research import Pick
        rows=store.rows('SELECT c.*,a.role,a.job_description,a.company AS application_company FROM contacts c JOIN applications a ON a.source_application_id=c.application_id WHERE c.id=?',(cid,))
        if not rows:raise ValueError('Contact not found')
        c=rows[0]
        pick=Pick(source_id=c['source_key'],name=c['name'],title=c['title'],company=c['company'],evidence_quote=json.loads(c['evidence'])['excerpt'][:350],relevance=c['relevance'][:240],uncertainty=c['uncertainty'][:240])
        config=store.settings()
        eligibility=store.rows('SELECT source_status,hiring_outcome FROM applications WHERE source_application_id=?',(c['application_id'],))[0]
        if eligibility['source_status']!='COMPLETED' or eligibility['hiring_outcome'] in ('rejected','job_closed'):raise ValueError('Application is not eligible for preparation')
        from backend.personalization import personalize,save_suggestion
        result=await personalize(store,experience,ollama,{'source_application_id':c['application_id'],'role':c['role'],'company':c['application_company'],'job_description':c['job_description'],'verified_contact_context': c['title'] if c['review_status']=='supported' and c['review_source'] else None},pick,config)
        return save_suggestion(store,cid,result)

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

    if remote:
        from backend.auth import routes
        routes(app,remote)

    dist=ROOT/'frontend/dist'
    if dist.exists():app.mount('/',StaticFiles(directory=dist,html=True),name='dashboard')
    else:
        @app.get('/')
        def not_built():return HTMLResponse('Build the frontend: cd frontend &amp;&amp; npm install &amp;&amp; npm run build')
    return app

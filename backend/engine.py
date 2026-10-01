import asyncio
import json
import os
import time
from backend.security import Unavailable, Retryable, public_url
from backend.store import now
from backend.research import Source


class Engine:
    def __init__(self,store,tsenta,search,ollama):
        self.store=store; self.tsenta=tsenta; self.search=search; self.ollama=ollama
        self.poll_enabled=os.getenv('TSENTA_POLL_ENABLED','false').lower()=='true'
        self.poll_reference=os.getenv('TSENTA_POLL_SUPPORT_REFERENCE','').strip()
        try:self.poll_seconds=float(os.getenv('TSENTA_POLL_SECONDS','') or 0)
        except ValueError:self.poll_seconds=0
        self.poll_active=self.poll_enabled and bool(self.poll_reference) and self.poll_seconds>0
        self.stop=asyncio.Event()

    def scheduler_info(self):
        return {'enabled':self.poll_active,'interval_seconds':self.poll_seconds if self.poll_active else None,
            'support_reference':self.poll_reference,
            'message':'Automatic checking enabled with the operator-provided interval.' if self.poll_active else
            'Automatic checking is disabled. Use Sync now. A supported interval and reference are required before enabling recurring polling.'}

    def failure(self,table,key,identifier,error,attempt):
        blocked=isinstance(error,Unavailable)
        state='blocked' if blocked else ('failed' if attempt>=3 else 'retry')
        delay=max(30*(2**(attempt-1)),getattr(error,'retry_after',0))
        message=str(error) if isinstance(error,(Unavailable,Retryable)) else 'Unexpected response or processing error. Data retained; inspect configuration and retry.'
        with self.store.db() as db:
            db.execute(f'UPDATE {table} SET state=?,error=?,next_attempt=? WHERE {key}=?',(state,message,time.time()+delay,identifier))
            if table=='jobs':
                db.execute('UPDATE jobs SET stage=?,updated_at=? WHERE application_id=?',(state,now(),identifier))
                db.execute('UPDATE applications SET research_state=?,last_error=? WHERE source_application_id=?',(state,message,identifier))
            elif state in ('blocked','failed'):
                db.execute('UPDATE sync_runs SET finished_at=? WHERE id=?',(now(),identifier))

    async def tick(self):
        from backend.details import baseline_valid
        if not baseline_valid(self.store):return
        if self.poll_active:
            last=self.store.rows('SELECT started_at FROM sync_runs ORDER BY id DESC LIMIT 1')
            from datetime import datetime
            last_time=datetime.fromisoformat(last[0]['started_at']).timestamp() if last else 0
            if time.time()-last_time>=self.poll_seconds:self.store.enqueue_sync()
        runs=self.store.rows("SELECT * FROM sync_runs WHERE state IN ('queued','retry') AND next_attempt<=? ORDER BY id LIMIT 1",(time.time(),))
        if runs:
            run=runs[0]; attempt=run['attempts']+1
            if attempt>3:
                self.failure('sync_runs','id',run['id'],Retryable('Sync retry limit reached. Use Sync now to try again.'),attempt)
                return
            with self.store.db() as db:db.execute("UPDATE sync_runs SET state='running',attempts=?,error=NULL WHERE id=?",(attempt,run['id']))
            try:
                rows=await self.tsenta.snapshot()
                result=self.store.apply_snapshot(rows)
                with self.store.db() as db:
                    db.execute("UPDATE sync_runs SET state='done',finished_at=?,observed=?,added=?,eligible=?,error=NULL WHERE id=?",(now(),result['observed'],result['added'],result['eligible'],run['id']))
            except Exception as error:
                self.failure('sync_runs','id',run['id'],error,attempt)
            return
        jobs=self.store.rows("SELECT * FROM jobs WHERE state IN ('queued','retry') AND next_attempt<=? ORDER BY rowid LIMIT 1",(time.time(),))
        if not jobs:
            if os.getenv('OUTREACH_AUTO_ROLE_EXTRACTION','true').lower()=='true' and os.getenv('OUTREACH_DEMO','false').lower()!='true':
                from backend.posting_role import fill_next_missing_role
                if await fill_next_missing_role(self.store):return
            return
        job=jobs[0]; aid=job['application_id']; attempt=job['attempts']+1
        if attempt>3:
            self.failure('jobs','application_id',aid,Retryable('Research retry limit reached. Retry from Applications.'),attempt)
            return
        with self.store.db() as db:
            claimed=db.execute("UPDATE jobs SET state='running',attempts=?,error=NULL WHERE application_id=? AND state IN ('queued','retry')",(attempt,aid))
            if not claimed.rowcount:return
            db.execute("UPDATE applications SET research_state='running',last_error=NULL WHERE source_application_id=?",(aid,))
        try:
            await asyncio.wait_for(self.research(aid),timeout=600)
        except asyncio.TimeoutError:
            self.failure('jobs','application_id',aid,Unavailable('Preparation exceeded ten minutes. Retry to resume from saved sources.'),attempt)
        except Exception as error:
            self.failure('jobs','application_id',aid,error,attempt)

    async def research(self,aid):
        app=self.store.rows('SELECT * FROM applications WHERE source_application_id=?',(aid,))[0]
        if app['hiring_outcome'] in ('rejected','job_closed'):raise Unavailable('Application is marked rejected or closed; new outreach preparation stopped.')
        if app['source_status']!='COMPLETED' or (app['historical'] and app['confirmed_at_baseline'] and not app['selected']):
            raise Unavailable('Application is not eligible for research.')
        # Check configuration before spending a search credit or enriching details.
        settings=self.store.settings()
        self.stage(aid,'checking_configuration')
        if not settings['facts']:raise Unavailable('Research unavailable: approve resume/project facts in Settings, then retry.')
        health=await self.ollama.health()
        if not health['available']:raise Unavailable('Drafting unavailable: '+health['message'])
        cache=self.store.rows('SELECT sources FROM research_cache WHERE application_id=?',(aid,))
        self.stage(aid,'researching_contacts')
        if cache:sources=[Source.model_validate(s) for s in json.loads(cache[0]['sources'])]
        else:
            if not app['company'] or not app['role']:raise Unavailable('Research unavailable: source company or role is missing.')
            sources=await self.search.search(app['company'],app['role'])
            with self.store.db() as db:
                db.execute('INSERT OR REPLACE INTO research_cache VALUES(?,?)',(aid,json.dumps([s.model_dump() for s in sources])))
        # Same verified detail tool; unknown source status never gets promoted to success.
        self.stage(aid,'checking_sources')
        if not app['detail_checked']:
            detail=await self.tsenta.read('get-application-status',{'applicationId':aid,'include':['resumePdfUrl']})
            if detail.get('applicationId')!=aid or detail.get('status')!='COMPLETED' or detail.get('isTerminal') is not True:
                raise Unavailable('Tsenta detail no longer confirms this submission. Run Sync now before retrying.')
            reference=detail.get('resumePdfUrl')
            if reference:
                try:reference=public_url(reference)
                except ValueError:reference=None
            missing=json.loads(app['missing_fields'])
            if reference and 'submitted_resume_reference' in missing:missing.remove('submitted_resume_reference')
            with self.store.db() as db:
                db.execute('UPDATE applications SET submitted_resume_reference=?,detail_checked=?,missing_fields=? WHERE source_application_id=?',
                    (reference,now(),json.dumps(missing),aid))
        self.stage(aid,'ranking_candidates')
        ranked=await self.ollama.rank(app['company'],app['role'],sources) if sources else []
        output=[]
        saved_drafts={row['source_key']:row for row in self.store.rows(
            'SELECT c.source_key,d.note,d.dm,d.grounding FROM contacts c JOIN drafts d ON d.contact_id=c.id WHERE c.application_id=?',(aid,))}
        self.stage(aid,'drafting_messages')
        for pick,source in ranked:
            saved=saved_drafts.get(source.id)
            drafts=({'note':saved['note'],'dm':saved['dm'],'grounding':json.loads(saved['grounding'])}
                    if saved else await self.ollama.draft(app,pick,settings['facts'],settings))
            output.append((pick,source,drafts))
        with self.store.db() as db:
            current=db.execute('SELECT source_status,historical,selected,confirmed_at_baseline FROM applications WHERE source_application_id=?',(aid,)).fetchone()
            if current['source_status']!='COMPLETED' or (current['historical'] and current['confirmed_at_baseline'] and not current['selected']):
                raise Unavailable('Application eligibility changed. Results were not published.')
            for rank,(pick,source,draft) in enumerate(output,1):
                db.execute('''INSERT OR IGNORE INTO contacts(application_id,source_key,name,title,company,linkedin_url,rank,evidence,relevance,uncertainty)
                    VALUES(?,?,?,?,?,?,?,?,?,?)''',(aid,source.id,pick.name,pick.title,pick.company,public_url(source.url,True),rank,
                    json.dumps({'url':source.url,'excerpt':pick.evidence_quote,'checked_at':source.checked_at,'source_title':source.title}),
                    pick.relevance,pick.uncertainty+' Public-search snippet only; current employment and ownership of this opening are not independently confirmed.'))
                cid=db.execute('SELECT id FROM contacts WHERE application_id=? AND source_key=?',(aid,source.id)).fetchone()[0]
                # Never overwrite user edits on restarts/retries.
                db.execute('INSERT OR IGNORE INTO drafts VALUES(?,?,?,?,?)',(cid,draft['note'],draft['dm'],json.dumps(draft['grounding']),now()))
            state='ready' if output else 'no_contacts'
            db.execute("UPDATE jobs SET state='done',stage='done',updated_at=?,error=NULL WHERE application_id=?",(now(),aid))
            db.execute('UPDATE applications SET research_state=?,last_error=NULL WHERE source_application_id=?',(state,aid))

    async def run(self):
        while not self.stop.is_set():
            try:await self.tick()
            except Exception:
                # Keep a failed worker iteration from becoming an endless UI spinner.
                with self.store.db() as db:
                    db.execute("UPDATE jobs SET state='interrupted',stage='interrupted',updated_at=?,error='Worker interrupted. Retry preparation.' WHERE state='running'",(now(),))
                    db.execute("UPDATE applications SET research_state='interrupted',last_error='Worker interrupted. Retry preparation.' WHERE source_application_id IN (SELECT application_id FROM jobs WHERE state='interrupted')")
            try:await asyncio.wait_for(self.stop.wait(),timeout=1)
            except asyncio.TimeoutError:pass

    def stage(self,aid,stage):
        with self.store.db() as db:
            db.execute('UPDATE jobs SET stage=?,updated_at=? WHERE application_id=?',(stage,now(),aid))

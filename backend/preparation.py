"""Persistent preparation graph. Engine schedules; graph checkpoints own stage progress.

Only checkpoint identifiers/status are exposed. Full state is private local data.
"""
import hashlib
import json
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from backend.matching import extract, match
from backend.experience import retrieve
from backend.personalization import personalize
from backend.research import Source, Pick
from backend.security import Unavailable, Retryable, InvalidOutput, public_url
from backend.store import now
from backend.observability import observe

class State(TypedDict,total=False):
    app: dict
    requirements: list
    matching: dict
    sources: list
    ranked: list
    output: list
    fallback: bool
    persistence_complete: bool


def eligible(store,aid):
    rows=store.rows('SELECT * FROM applications WHERE source_application_id=?',(aid,))
    if not rows:raise Unavailable('Application not found')
    a=rows[0]
    if a['source_status']!='COMPLETED' or a['hiring_outcome'] in ('rejected','job_closed') or (a['historical'] and a['confirmed_at_baseline'] and not a['selected']):
        raise Unavailable('Application no longer eligible. Preparation stopped.')
    epoch=store.rows("SELECT epoch FROM preparation_epochs WHERE application_id=?",(aid,))
    a["_epoch"]=epoch[0]["epoch"] if epoch else 0
    description=store.rows("SELECT source_url,provenance,updated_at,version FROM descriptions WHERE application_id=?",(aid,))
    a["_description_version"]=description[0]["version"] if description else 0
    a["_description_provenance"]=description[0] if description else {"source_url":"","provenance":"existing source" if a.get("job_description") else "not supplied","version":0}
    return a

def input_version(app,repo):
    return hashlib.sha256(json.dumps([app.get('job_description'),app.get('role'),app.get('company'),app.get('_epoch',0),app.get('_description_version',0),repo.revision()],sort_keys=True).encode()).hexdigest()[:24]


def run_id(store,app,repo,create=True):
    version=input_version(app,repo)
    rid=hashlib.sha256((app['source_application_id']+version).encode()).hexdigest()[:32]
    if create:
        with store.db() as db:db.execute('INSERT OR IGNORE INTO preparation_runs VALUES(?,?,?,?)',(rid,app['source_application_id'],version,now()))
    return rid


def build(engine,saver):
    repo=engine.experience;store=engine.store
    def guard(state):
        current=eligible(store,state['app']['source_application_id'])
        if input_version(current,repo)!=state['app'].get('_input_version'):
            raise Unavailable('Description or approved experience changed. Start a new preparation version.')
    async def requirements(state):
        description=state['app'].get('job_description') or ''
        return {'requirements':(await extract(engine.ollama,description)).model_dump()['requirements'] if description else [],'fallback':not bool(description)}
    async def missing_description(state):
        return {'requirements':[],'fallback':True}
    async def no_contacts(state):
        return {'output':[]}
    async def retrieval(state):
        query=' '.join(r['text'] for r in state['requirements']) or state['app']['role']
        result=await retrieve(repo,query)
        matches=match(state['requirements'],result['facts'])
        ids={f['fact_id'] for r in matches for f in r['supporting_facts']}
        selected=[f for f in result['facts'] if f['id'] in ids] if state['requirements'] else result['facts']
        matching={'requirements':state['requirements'],'matches':matches,'selected_facts':selected,
            'method':'Role-based fallback (no job description)' if state['fallback'] else result['method'],
            'warning':result['warning'],'experience_revision':repo.revision(),'description_provenance':state['app']['_description_provenance'],
            'unsupported_meaning':'Missing evidence in the collection, not proof you lack a skill.'}
        with store.db() as db:db.execute('INSERT OR REPLACE INTO match_reviews VALUES(?,?,?)',(state['app']['source_application_id'],json.dumps(matching),now()))
        return {'matching':matching}
    async def missing_evidence(state):
        interrupt({'reason':'insufficient_evidence','action':'Approve relevant experience and start a new version, or cancel preparation.'})
        # Inputs must change rather than authorizing unsupported generation.
        raise Unavailable('No approved supporting evidence. Add evidence before preparing again.')
    async def research(state):
        aid=state['app']['source_application_id'];app=state['app']
        cache=store.rows('SELECT sources FROM research_cache WHERE application_id=?',(aid,))
        if cache:sources=json.loads(cache[0]['sources'])
        else:
            sources=[s.model_dump() for s in await engine.search.search(app['company'],app['role'])]
            with store.db() as db:db.execute('INSERT OR REPLACE INTO research_cache VALUES(?,?)',(aid,json.dumps(sources)))
        if not app['detail_checked']:
            detail=await engine.tsenta.read('get-application-status',{'applicationId':aid,'include':['resumePdfUrl']})
            if detail.get('applicationId')!=aid or detail.get('status')!='COMPLETED' or detail.get('isTerminal') is not True:
                raise Unavailable('Source no longer confirms this submission. Sync before retrying.')
            reference=detail.get('resumePdfUrl')
            if reference:
                try:reference=public_url(reference)
                except ValueError:reference=None
            with store.db() as db:db.execute('UPDATE applications SET submitted_resume_reference=COALESCE(?,submitted_resume_reference),detail_checked=? WHERE source_application_id=?',(reference,now(),aid))
        return {'sources':sources}
    async def assess(state):
        from backend.contact_evidence import assess_relevance
        sources=[Source.model_validate(s) for s in state['sources']]
        ranked=await engine.ollama.rank(state['app']['company'],state['app']['role'],sources) if sources else []
        accepted=[]
        for pick,source in ranked:
            assessment=assess_relevance({'name':pick.name,'title':pick.title,'application_company':state['app']['company'],'role':state['app']['role'],
                'evidence':{'source_title':source.title,'excerpt':source.excerpt}})
            if assessment['level'] in ('high','medium'):accepted.append({'pick':pick.model_dump(),'source':source.model_dump()})
        return {'ranked':accepted}
    async def drafting(state):
        output=[];aid=state['app']['source_application_id']
        saved={r['source_key']:r for r in store.rows('SELECT c.source_key,d.note,d.dm,d.grounding FROM contacts c JOIN drafts d ON d.contact_id=c.id WHERE c.application_id=?',(aid,))}
        for row in state['ranked']:
            old=saved.get(row['source']['id'])
            draft={'note':old['note'],'dm':old['dm'],'grounding':json.loads(old['grounding'])} if old else await personalize(
                store,repo,engine.ollama,state['app'],Pick.model_validate(row['pick']),store.settings(),state['matching'])
            output.append({**row,'draft':draft,'existing':bool(old)})
        return {'output':output}
    async def validation(state):
        approved={f['id']:f for f in repo.list(approved=True)}
        selected={f['id'] for f in state['matching']['selected_facts']}
        for row in state['output']:
            if row['existing']:continue  # Never reinterpret or replace previously reviewed edits.
            draft=row['draft'];grounding=draft['grounding']
            selected={f['id'] for f in grounding.get('matching',state['matching'])['selected_facts']}
            if any(fid not in approved or fid not in selected for fid in grounding.get('fact_ids',[])+grounding.get('note_fact_ids',[])):
                raise InvalidOutput('Draft references unapproved experience; output rejected.')
            if not draft['note'].strip() or not draft['dm'].strip():raise InvalidOutput('Empty draft rejected.')
        return {}
    async def review(state):
        # Human draft review happens in the UI before any manual outreach.
        # Optional explicit preparation review is checkpointed, never a send approval.
        if store.settings().get('pause_before_persistence',False):
            approved=interrupt({'reason':'review','action':'Review requirement matches, then resume to save suggestions. No messages will be sent.'})
            if approved is not True:raise Unavailable('Preparation review was not approved.')
        return {}
    async def persist(state):
        aid=state['app']['source_application_id']
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT source_status,hiring_outcome FROM applications WHERE source_application_id=?',(aid,)).fetchone()
            if current['source_status']!='COMPLETED' or current['hiring_outcome'] in ('rejected','job_closed'):raise Unavailable('Eligibility changed; results not saved.')
            for rank,row in enumerate(state['output'],1):
                p=row['pick'];s=row['source'];d=row['draft']
                db.execute('''INSERT OR IGNORE INTO contacts(application_id,source_key,name,title,company,linkedin_url,rank,evidence,relevance,uncertainty)
                    VALUES(?,?,?,?,?,?,?,?,?,?)''',(aid,s['id'],p['name'],p['title'],p['company'],public_url(s['url'],True),rank,
                    json.dumps({'url':s['url'],'excerpt':p['evidence_quote'],'checked_at':s['checked_at'],'source_title':s['title']}),p['relevance'],p['uncertainty']))
                cid=db.execute('SELECT id FROM contacts WHERE application_id=? AND source_key=?',(aid,s['id'])).fetchone()[0]
                db.execute('INSERT OR IGNORE INTO drafts VALUES(?,?,?,?,?)',(cid,d['note'],d['dm'],json.dumps(d['grounding']),now()))
        return {'persistence_complete':True}
    graph=StateGraph(State)
    for name,fn in [('requirements_extraction',requirements),('missing_description',missing_description),('no_contacts_review',no_contacts),('experience_retrieval',retrieval),('insufficient_evidence',missing_evidence),('contact_research',research),
                    ('evidence_assessment',assess),('drafting',drafting),('validation',validation),('review',review),('persistence',persist)]:
        def wrap(fn,name):
            async def node(state):
                guard(state);engine.stage(state['app']['source_application_id'],name)
                with observe(name) as observation:
                    # Interrupt is outside try's catch types; only sanitized errors reach UI.
                    while True:
                        try:return await fn(state)
                        except (Unavailable,Retryable) as error:
                            observation['retries']+=1
                            observation['validation_failed']=isinstance(error,InvalidOutput)
                            answer=interrupt({'reason':'invalid_output' if isinstance(error,InvalidOutput) else 'provider_failure','stage':name,'action':str(error)})
                            if answer is not True:raise Unavailable('Preparation paused. Retry when ready.')
                            guard(state)
            return node
        graph.add_node(name,wrap(fn,name))
    graph.add_conditional_edges(START,lambda s:'requirements_extraction' if s['app'].get('job_description') else 'missing_description')
    graph.add_edge('requirements_extraction','experience_retrieval');graph.add_edge('missing_description','experience_retrieval')
    graph.add_conditional_edges('experience_retrieval',lambda s:'contact_research' if s['matching']['selected_facts'] else 'insufficient_evidence')
    graph.add_edge('insufficient_evidence',END)
    graph.add_conditional_edges('evidence_assessment',lambda s:'drafting' if s['ranked'] else 'no_contacts_review')
    graph.add_edge('no_contacts_review','review')
    for a,b in zip(['contact_research','drafting','validation','review','persistence'],['evidence_assessment','validation','review','persistence',END]):graph.add_edge(a,b)
    return graph.compile(checkpointer=saver)

async def execute(engine,aid,resume=False):
    app=eligible(engine.store,aid);rid=run_id(engine.store,app,engine.experience)
    app['_input_version']=input_version(app,engine.experience)
    path=str(engine.store.path)+'.checkpoints.sqlite'
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        graph=build(engine,saver);config={'configurable':{'thread_id':rid}}
        snapshot=await graph.aget_state(config)
        if snapshot.values and snapshot.values.get('persistence_complete'):
            return rid,True,bool(snapshot.values.get('output'))
        value=Command(resume=True) if resume and snapshot.next else (None if snapshot.values else {'app':app})
        result=await graph.ainvoke(value,config)
        complete=bool(result.get('persistence_complete'))
        return rid,complete,bool(result.get('output'))

async def status(engine,aid):
    app=eligible(engine.store,aid);rid=run_id(engine.store,app,engine.experience,create=False)
    async with AsyncSqliteSaver.from_conn_string(str(engine.store.path)+'.checkpoints.sqlite') as saver:
        snapshot=await build(engine,saver).aget_state({'configurable':{'thread_id':rid}})
        return {'run_id':rid,'next':list(snapshot.next),'complete':bool(snapshot.values.get('persistence_complete')),
            'interrupts':[i.value for t in snapshot.tasks for i in t.interrupts]}

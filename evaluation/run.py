"""Reproducible benchmark. Mock mode measures harness behavior, never model quality."""
import argparse
import asyncio
import json
import math
import re
import statistics
import tempfile
import time
import os
import platform
from datetime import datetime, timezone
import httpx
from pathlib import Path
from backend.demo import seed, FixtureOllama
from backend.store import Store
from backend.experience import ExperienceRepository, ExperienceInput, retrieve, Embeddings
from backend.matching import extract, match
from backend.research import Ollama, DraftPlan, Source
from backend.observability import metrics
from evaluation.baseline import select as baseline_select

class MockModel(FixtureOllama):
    async def structured(self,schema,instruction,data):
        if schema is DraftPlan:
            ids=[f['id'] for f in data['facts']][:2]
            return DraftPlan(fact_ids=ids,note_fact_ids=ids[:1],connection_style='connect',dm_style='team')
        return await super().structured(schema,instruction,data)

def factual_spans(text):
    # Controlled benchmark statements only. This intentionally does not cover every possible claim.
    return re.findall(r'I (?:built|led|maintained|implemented|developed|have experience)[^.?!]*[.?!]',text)

def unsupported_claims(text,approved):
    spans=factual_spans(text)
    allowed={f['text'] for f in approved if f['status']=='approved'}
    return sum(s not in allowed for s in spans),len(spans)

def ndcg(ranked,expected):
    gain=sum((1 if fid in expected else 0)/math.log2(i+2) for i,fid in enumerate(ranked))
    ideal=sum(1/math.log2(i+2) for i in range(len(expected)))
    return gain/ideal if ideal else 1

async def runtime_metadata(model, embeddings):
    names={'generation':model.model}
    if embeddings:names['embedding']=os.getenv('EMBEDDING_MODEL','nomic-embed-text')
    result={'recorded_at':datetime.now(timezone.utc).isoformat(),
            'system':platform.system(),'architecture':platform.machine(),
            'python':platform.python_version(),'embedding_version':os.getenv('EMBEDDING_VERSION','1') if embeddings else None,
            'models':{key:{'name':name,'digest':None} for key,name in names.items()}}
    try:
        async with httpx.AsyncClient(timeout=5,trust_env=False) as client:
            response=await client.get(os.getenv('OLLAMA_URL','http://127.0.0.1:11434').rstrip('/')+'/api/tags')
            response.raise_for_status()
            tags=response.json()['models']
            for key,name in names.items():
                canonical=name if ':' in name else name+':latest'
                result['models'][key]['digest']=next((tag.get('digest') for tag in tags if tag.get('name') in (name,canonical)),None)
    except (httpx.HTTPError,ValueError,KeyError,TypeError):
        result['metadata_warning']='Model digests unavailable; do not assume identical model weights across runs.'
    return result

async def benchmark(real=False,embeddings=False,limit=None):
    cases=json.loads(Path(__file__).with_name('cases.json').read_text())
    corpus_count=len(cases)
    if limit is not None:
        if limit<1:raise ValueError('Case limit must be positive')
        cases=cases[:limit]
    model=Ollama() if real else MockModel();results=[]
    runtime=await runtime_metadata(model,embeddings) if real else None
    for case in cases:
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'benchmark.sqlite';seed(path);store=Store(path);store.initialize()
            repo=ExperienceRepository(store,url=f'sqlite:///{path}');repo.initialize()
            for f in case['facts']:repo.save(ExperienceInput(**{k:f[k] for k in ('text','project','technologies','source_reference','status')}),f['id'])
            for method in ('baseline','upgraded'):
                stages={};calls=[];marker=metrics.set(calls);start=time.perf_counter();error=None;selected=[];ranked=[];text='';bad=0;total_claims=0;retrieval_method='role_only' if method=='baseline' else 'lexical';retrieval_warning=None;embedding_calls=0;extracted_requirements=[]
                async def timed(name,fn):
                    before=time.perf_counter()
                    try:return await fn()
                    finally:stages[name]=(time.perf_counter()-before)*1000
                try:
                    if method=='baseline':selected=await timed('fact_selection',lambda:baseline_select(model,case))
                    else:
                        req=await timed('extraction',lambda:extract(model,case['description']))
                        extracted_requirements=req.model_dump()['requirements']
                        query=' '.join(r.text for r in req.requirements)
                        if not embeddings:
                            # Explicit lexical comparison, independent of ambient threshold.
                            from backend.experience import tokens
                            before=time.perf_counter()
                            facts=sorted(repo.list(approved=True),key=lambda f:(-len(tokens(query)&tokens(f['text']+' '+' '.join(f['technologies']))),f['id']))[:6]
                            stages['retrieval']=(time.perf_counter()-before)*1000
                        else:
                            class CountedEmbeddings(Embeddings):
                                async def embed(self,value):
                                    nonlocal embedding_calls
                                    embedding_calls+=1
                                    return await super().embed(value)
                            retrieved=await timed('retrieval',lambda:retrieve(repo,query,provider=CountedEmbeddings(),force_embeddings=True));facts=retrieved['facts'];retrieval_method=retrieved['method'];retrieval_warning=retrieved['warning']
                        matches=match(req.model_dump()['requirements'],facts)
                        selected=list(dict.fromkeys(f['fact_id'] for r in matches for f in r['supporting_facts']))[:6]
                    # Identical final evidence bounds for both selection methods.
                    bounded=[];budget=0
                    for fid in selected:
                        f=next((f for f in case['facts'] if f['id']==fid and f['status']=='approved'),None)
                        if f and len(bounded)<6 and budget+len(f['text'])<=2800:
                            bounded.append(fid);budget+=len(f['text'])
                    selected=bounded
                    sources=[Source(id=c['id'],url=f'https://www.linkedin.com/in/fictional-{c["id"]}',title={'recruiter':'Avery Example','unrelated':'Robin Example','manager':'Taylor Fictional','former':'Casey Fictional'}[c['id']]+' — '+c['title'],excerpt=c['evidence'],checked_at='2026-01-01T00:00:00+00:00') for c in case['contacts']]
                    if real:ranked=[s.id for _,s in await timed('contact_ranking',lambda:model.rank(case['company'],case['role'],sources))]
                    else:
                        before=time.perf_counter();ranked=[c['id'] for c in sorted(case['contacts'],key=lambda c:'recruit' not in c['title'].lower())];stages['contact_ranking']=(time.perf_counter()-before)*1000
                    selected_facts=[f for f in case['facts'] if f['id'] in selected and f['status']=='approved']
                    if real:
                        from backend.research import Pick
                        pick=Pick(source_id='recruiter',name='Avery Example',title='Technical Recruiter',company=case['company'],evidence_quote=case['contacts'][0]['evidence'],relevance='Synthetic expected recruiter',uncertainty='Fictional evaluation evidence')
                        app={'role':case['role'],'company':case['company']}
                        if method=='upgraded':app['requirements']=req.model_dump()['requirements']
                        draft=await timed('generation',lambda:model.draft(app,pick,selected_facts,{'note_limit':200,'dm_limit':1200,'exact_note_200':True}))
                        selected=list(dict.fromkeys(draft['grounding']['fact_ids']+draft['grounding']['note_fact_ids']))
                        text=draft['note']+' '+draft['dm']
                    else:
                        before=time.perf_counter();text=' '.join(f['text'] for f in selected_facts);stages['generation']=(time.perf_counter()-before)*1000
                    before=time.perf_counter();bad,total_claims=unsupported_claims(text,case['facts']);stages['validation']=(time.perf_counter()-before)*1000
                except Exception as exc:error=type(exc).__name__  # Never raw provider response/content.
                finally:metrics.reset(marker)
                expected=set(case['expected_fact_ids']);picked=set(selected)
                results.append({'case_id':case['id'],'method':method,'selected_fact_ids':selected,
                    'precision':len(expected&picked)/len(picked) if picked else 0,'recall':len(expected&picked)/len(expected),
                    'contact_ndcg':ndcg(ranked,set(case['expected_contact_ids'])),'unsupported_claims':bad,'checked_claims':total_claims,
                    'failure':error,'latency_ms':(time.perf_counter()-start)*1000,'stages_ms':stages,
                    'model_calls':len(calls) if real else 0,'token_counts':[c.get('tokens') for c in calls if c.get('tokens')],
                    'embedding_requested':embeddings,'embedding_calls':embedding_calls,'retrieval_method':retrieval_method,'retrieval_warning':retrieval_warning,
                    'extracted_requirements':extracted_requirements})
            repo.engine.dispose()
    summary={}
    for method in ('baseline','upgraded'):
        rows=[r for r in results if r['method']==method];claims=sum(r['checked_claims'] for r in rows)
        summary[method]={key:statistics.mean(r[key] for r in rows) for key in ('precision','recall','contact_ndcg','latency_ms','model_calls')}
        summary[method].update(failure_rate=sum(r['failure'] is not None for r in rows)/len(rows),
            unsupported_claim_rate=sum(r['unsupported_claims'] for r in rows)/claims if claims else None,
            per_stage_mean_ms={stage:statistics.mean(r['stages_ms'][stage] for r in rows if stage in r['stages_ms']) for stage in {s for r in rows for s in r['stages_ms']}},
            retrieval_methods={name:sum(r['retrieval_method']==name for r in rows) for name in sorted({r['retrieval_method'] for r in rows})},
            embedding_calls=sum(r['embedding_calls'] for r in rows),lexical_fallback_cases=sum(bool(r['retrieval_warning']) for r in rows),
            available_token_counts=sum(bool(r['token_counts']) for r in rows))
    return {'mode':'real_model' if real else 'mock_harness_only','runtime':runtime,'case_count':len(cases),'corpus_count':corpus_count,'partial_run':len(cases)<corpus_count,'label_origin':'synthetic, not independently validated',
        'limitations':['Synthetic authored labels include aliases, multi-requirement and unsupported cases; they are not independent human judgments.',
        'Unsupported claims validator only checks recognized first-person experience spans; not a proof of factuality.',
        'Mock generation is exact fact concatenation, not LLM drafting. Contact ranking mock is a title heuristic.',
        'Latencies include local Python and temporary database overhead; no speedup claim.'], 'constraints':{'max_selected_facts':6,'fact_text_characters':2800,'generated_note_characters':200,'dm_limit':1200,'real_generation':'same renderer and model interface for both methods','embedding_mode':'forced when requested; fallback counted separately'}, 'summary':summary,'cases':results}
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--real-model',action='store_true')
    p.add_argument('--embeddings',action='store_true')
    p.add_argument('--limit',type=int,help='Run the first N cases; output explicitly marks partial runs.')
    p.add_argument('--require-success',action='store_true',help='Exit unsuccessfully for any case failure or requested embedding fallback.')
    p.add_argument('--output',help='Result path; defaults to an ignored local file for mock and real-model runs.')
    a=p.parse_args()
    if a.limit is not None and a.limit<1:p.error('--limit must be positive')
    if a.embeddings and not a.real_model:p.error('--embeddings requires --real-model')
    output=Path(a.output or ('.local/results.real.json' if a.real_model else '.local/results.mock.json'))
    result=asyncio.run(benchmark(a.real_model,a.embeddings,a.limit))
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='cases'},indent=2))
    if a.require_success and any(r['failure'] or (r['method']=='upgraded' and a.embeddings and
            (r['retrieval_warning'] or r['retrieval_method'] not in ('embedding cosine','pgvector cosine'))) for r in result['cases']):
        raise SystemExit(1)


if __name__=='__main__':main()

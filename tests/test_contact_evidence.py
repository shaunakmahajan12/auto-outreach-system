import asyncio
import json
import pytest
from backend.contact_evidence import extract_title,backfill_titles,assess_relevance
from backend.research import Ollama,Pick,DraftPlan,ConnectionNote,Ranking,Source,generated_note_issues
from backend.security import Unavailable, Retryable
from test_workflow import client,advance

FACT='I built a Python data pipeline that cut reporting time by 40% and added production monitoring.'
NOTE='Hi Avery, I applied for Engineer at Cedar. '+FACT+' I’d value the chance to connect and learn more about the team.'
PICK=Pick(source_id='s',name='Avery Example',evidence_quote='Avery Example',relevance='fixture',uncertainty='fixture')

def test_title_uses_original_headline_not_generated_reasoning():
    evidence={'source_title':'Avery Example - Senior Recruiter, Talent Acquisition @ Cedar - LinkedIn','excerpt':'With over 6 years at Cedar, currently serving as a Recruiter, expertise spans talent acquisition.'}
    assert extract_title('Avery Example',evidence)=='Senior Recruiter, Talent Acquisition'
    assert extract_title('Avery Example',{'source_title':'Avery Example - Cedar - LinkedIn','excerpt':'Avery Example works at Cedar.'}) is None
    assert extract_title('Avery Example',{'source_title':'Avery Example - Senior Recruit... - LinkedIn'}) is None
    assert extract_title('Avery Example',{'excerpt':'Avery Example is a Technical Recruiter at Cedar.'})=='Technical Recruiter'


def test_rank_fills_missing_title_from_source():
    model=Ollama()
    async def structured(*args):return Ranking(candidates=[PICK])
    model.structured=structured
    source=Source(id='s',title='Avery Example - Senior Recruiter @ Cedar - LinkedIn',excerpt='Avery Example works at Cedar.',url='https://linkedin.com/in/avery-example',checked_at='2026-01-01')
    result=asyncio.run(model.rank('Cedar','Engineer',[source]))
    assert result[0][0].title=='Senior Recruiter'


def test_backfill_is_idempotent_and_preserves_manual_changes_and_history(client):
    client.post('/api/applications/FICTIONAL-HISTORY/research');advance(client)
    store=client.app.state.store
    with store.db() as db:db.execute("UPDATE contacts SET name='Avery Example',title=NULL,evidence=?",(json.dumps({'source_title':'Avery Example - Senior Recruiter at Cedar - LinkedIn','excerpt':'Source'}),))
    before={t:store.rows('SELECT * FROM '+t) for t in ('applications','drafts','outreach_events','baseline','baseline_members')}
    assert backfill_titles(store)==1
    assert backfill_titles(store)==0
    assert store.rows('SELECT title FROM contacts')[0]['title']=='Senior Recruiter'
    for t,rows in before.items():assert store.rows('SELECT * FROM '+t)==rows
    with store.db() as db:db.execute("UPDATE contacts SET title=NULL,original_fields='{}'")
    assert backfill_titles(store)==0


def test_relevance_criteria_do_not_use_rank_or_generated_notes():
    c={'name':'Avery','title':'Technical Recruiter','application_company':'Cedar','role':'Software Engineer','evidence':{'source_title':'Avery - Technical Recruiter at Cedar','excerpt':''}}
    assert assess_relevance(c)['level']=='high'
    assert assess_relevance({**c,'rank':500,'relevance':'Not relevant'})==assess_relevance(c)
    assert assess_relevance({**c,'title':'Recruiter','evidence':{'source_title':'Avery - Recruiter at Cedar','excerpt':''}})['level']=='medium'
    assert assess_relevance({**c,'evidence':{'source_title':'Avery - Technical Recruiter at Elm','excerpt':''}})['level']=='low'
    assert assess_relevance({**c,'title':None,'evidence':{},'relevance':'Avery is a recruiter at Cedar'})['level']=='unassessed'


def test_deterministic_note_never_requests_unconstrained_model_text():
    model=Ollama();attempts=[]
    async def structured(schema,instruction,data):
        if schema is DraftPlan:return DraftPlan(fact_ids=['f'],connection_style='connect',dm_style='team')
        attempts.append(data)
        return ConnectionNote(note=NOTE[:-1] if len(attempts)==1 else NOTE,fact_ids=['f'])
    model.structured=structured
    result=asyncio.run(model.draft({'company':'Cedar','role':'Engineer'},PICK,[{'id':'f','text':FACT}],{'note_limit':200,'dm_limit':1200}))
    assert len(result['note'])==200 and result['note']==NOTE
    assert result['grounding']['validation_issues']==[]
    assert result['grounding']['fallback_used'] is False
    assert len(attempts)==0
    assert generated_note_issues(NOTE.replace('40%','90%'),['f'],{'f':FACT},'Avery','Engineer','Cedar')
    assert len('😀')==1 # same code-point counting as Array.from in the frontend


def test_fallback_suggestion_preserves_saved_draft(client):
    client.post('/api/applications/FICTIONAL-HISTORY/research');advance(client)
    store=client.app.state.store;before=store.rows('SELECT * FROM drafts');cid=before[0]['contact_id']
    model=Ollama();attempts=[]
    async def structured(schema,instruction,data):
        if schema is DraftPlan:return DraftPlan(fact_ids=['fictional-fact'],connection_style='connect',dm_style='team')
        attempts.append(data)
        return ConnectionNote(note='Too short.',fact_ids=['fictional-fact'])
    model.structured=structured
    client.app.state.engine.ollama.draft=model.draft
    response=client.post(f'/api/contacts/{cid}/draft-suggestion')
    assert response.status_code==200
    assert response.json()['grounding']['fallback_used'] is False
    assert 'I built a fictional Python project.' in response.json()['note']
    assert 'Too short.' not in response.json()['note']
    assert len(attempts)==0
    assert store.rows('SELECT * FROM drafts')==before


@pytest.mark.parametrize('text',[
    NOTE.replace('40%','90%'),
    NOTE+' I have led a team of 100 engineers.',
    NOTE.replace('I’d value the chance to connect and learn more about the team.','Would you be willing to connect?'),
])
def test_renderer_ignores_unrequested_wording_and_preserves_approved_fact(text):
    model=Ollama()
    async def structured(schema,*args):
        if schema is DraftPlan:return DraftPlan(fact_ids=['f'],connection_style='connect',dm_style='team')
        return ConnectionNote(note=text,fact_ids=['f'])
    model.structured=structured
    result=asyncio.run(model.draft({'company':'Cedar','role':'Engineer'},PICK,[{'id':'f','text':FACT}],{'note_limit':200,'dm_limit':1200}))
    assert result['note']==NOTE
    assert result['grounding']['fallback_used'] is False
    assert result['grounding']['note_fact_ids']==['f']


def test_fallback_never_accepts_unapproved_plan_fact():
    model=Ollama()
    async def structured(*args):
        return DraftPlan(fact_ids=['invented'],connection_style='connect',dm_style='team')
    model.structured=structured
    with pytest.raises(Retryable,match='unapproved fact'):
        asyncio.run(model.draft({'company':'Cedar','role':'Engineer'},PICK,[{'id':'f','text':FACT}],{'note_limit':200,'dm_limit':1200}))

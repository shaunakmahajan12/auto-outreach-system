"""Focused regressions with fictional records only."""
import asyncio
import pytest
from backend.matching import match
from backend.experience import ExperienceInput
from backend.research import Ollama,Pick,DraftPlan
from backend.security import Unavailable
from test_workflow import client,advance
AID='FICTIONAL-HISTORY'

def requirement(text,category='skill'):
    return {'text':text,'category':category,'priority':'required','excerpt':text}

def test_explicit_technologies_not_shared_generic_words():
    fact={'id':'fictional','text':'I develop services using Python.','technologies':['Kubernetes'],'status':'approved'}
    result=match([requirement('Develop services using Kubernetes.')],[fact])[0]
    assert result['assessment']=='unsupported' and not result['supporting_facts']
    fact['text']='I deployed fictional services with k8s.'
    assert match([requirement('Develop services using Kubernetes.')],[fact])[0]['assessment']=='supported'
    assert match([requirement('Python and Kubernetes')],[fact])[0]['assessment']=='unsupported'

def test_responsibility_partial_evidence_is_uncertain():
    r=match([requirement('Lead incident response across multiple teams','responsibility')],[{'id':'x','text':'I maintained an incident response guide.','status':'approved'}])[0]
    assert r['assessment']=='uncertain' and not r['supporting_facts'] and r['possible_evidence']

@pytest.mark.parametrize('change',['edit','retire','unapprove','description'])
def test_stale_suggestion_does_not_change_saved_draft(client,change):
    client.post(f'/api/applications/{AID}/research');advance(client)
    c=client.get('/api/state').json()['contacts'][0];cid=c['id']
    suggestion=client.post(f'/api/contacts/{cid}/draft-suggestion').json()
    if change=='description':
        client.put(f'/api/applications/{AID}/description',json={'text':'Required: Python','source_url':''})
    else:
        repo=client.app.state.engine.experience;f=repo.list(approved=True)[0]
        repo.save(ExperienceInput(text=f['text']+(' Fictional edit.' if change=='edit' else ''),status='retired' if change=='retire' else 'draft' if change=='unapprove' else 'approved'),f['id'])
    response=client.put(f'/api/contacts/{cid}/drafts',json={'note':suggestion['note'],'dm':c['dm'],'suggestion_id':suggestion['suggestion_id'],'suggestion_parts':['note']})
    assert response.status_code==400 and 'Regenerate' in response.json()['detail']
    assert client.get('/api/state').json()['contacts'][0]['note']==c['note']
    assert client.put(f'/api/contacts/{cid}/drafts',json={'note':'Manual fictional edit','dm':c['dm']}).status_code==200

def test_note_acceptance_does_not_count_untouched_dm(client):
    client.post(f'/api/applications/{AID}/research');advance(client)
    c=client.get('/api/state').json()['contacts'][0];cid=c['id']
    client.put(f'/api/contacts/{cid}/drafts',json={'note':c['note'],'dm':'Existing manual fictional DM'})
    s=client.post(f'/api/contacts/{cid}/draft-suggestion').json()
    assert client.put(f'/api/contacts/{cid}/drafts',json={'note':s['note'],'dm':'Existing manual fictional DM','suggestion_id':s['suggestion_id'],'suggestion_parts':['note']}).status_code==200
    metrics=client.get('/api/metrics/feedback').json()
    assert metrics['edit_rate']==0 and metrics['messages']['dm']==[] and metrics['messages']['note'][0]['edited']==0
    client.put(f'/api/contacts/{cid}/drafts',json={'note':s['note'],'dm':'Later manual DM'})
    assert client.get('/api/metrics/feedback').json()['edit_rate']==0


def test_compact_requirements_and_complete_budget(monkeypatch):
    class Capture(Ollama):
        captured=None
        async def structured(self,schema,instruction,data):
            self.captured=data
            return DraftPlan(fact_ids=['x'],note_fact_ids=['x'],connection_style='connect',dm_style='team')
    model=Capture();app={'role':'Software Engineer (fictional)','company':'Fictional Cedar Labs','requirements':[{**requirement('Python'),'excerpt':'Python '+('long evidence '*1500)}]}
    pick=Pick(source_id='x',name='Avery',title='Engineer',company=app['company'],evidence_quote='Engineer',relevance='fictional',uncertainty='fictional')
    facts=[{'id':'x','text':'I built a fictional Python project.'}]
    asyncio.run(model.draft(app,pick,facts,{'dm_limit':1200,'exact_note_200':True}))
    assert 'excerpt' not in model.captured['requirements'][0]
    monkeypatch.setenv('MODEL_INPUT_CHAR_BUDGET','100')
    model.captured=None
    with pytest.raises(Unavailable,match='Minimum useful'):asyncio.run(model.draft(app,pick,facts,{'dm_limit':1200}))
    assert model.captured is None

def test_approved_content_changes_require_renewed_approval(client):
    repo=client.app.state.engine.experience;f=repo.list(approved=True)[0]
    value=ExperienceInput(text=f['text']+' Fictional revised scope.',status='approved')
    repo.save(value,f['id']);assert next(r for r in repo.list() if r['id']==f['id'])['status']=='draft'
    repo.save(value,f['id']);assert next(r for r in repo.list() if r['id']==f['id'])['status']=='approved'

def test_technology_does_not_establish_duration():
    r=match([requirement('5 years of Python experience','experience')],[{'id':'x','text':'I built a fictional Python project.','status':'approved'}])[0]
    assert r['assessment']=='uncertain' and not r['supporting_facts']

def test_aliases_do_not_create_additional_qualifications():
    from backend.skill_evidence import skills
    assert skills('React.js')=={'react'}
    assert skills('Node.js')=={'node.js'}
    assert 'golang' not in skills('I go to weekly meetings.')
    assert 'golang' in skills('I built a Go service.')

@pytest.mark.parametrize('failure',[False,True])
def test_embedding_benchmark_forces_provider_and_reports_fallback(monkeypatch,failure):
    from backend.experience import Embeddings
    from evaluation.run import benchmark
    monkeypatch.setenv('RETRIEVAL_EMBEDDING_THRESHOLD','99999')
    async def fake_embed(self,text):
        if failure:raise ValueError('Fictional provider unavailable')
        return [1.,0.,0.]
    monkeypatch.setattr(Embeddings,'embed',fake_embed)
    result=asyncio.run(benchmark(embeddings=True))
    summary=result['summary']['upgraded']
    assert summary['embedding_calls']>=50
    assert summary['lexical_fallback_cases']==(50 if failure else 0)
    assert summary['retrieval_methods']==({'lexical':50} if failure else {'embedding cosine':50})

def test_accepting_after_dismissing_updates_only_accepted_message(client):
    client.post(f'/api/applications/{AID}/research');advance(client)
    c=client.get('/api/state').json()['contacts'][0];s=client.post(f"/api/contacts/{c['id']}/draft-suggestion").json()
    client.post(f"/api/draft-suggestions/{s['suggestion_id']}/reject")
    assert client.put(f"/api/contacts/{c['id']}/drafts",json={'note':s['note'],'dm':c['dm'],'suggestion_id':s['suggestion_id'],'suggestion_parts':['note']}).status_code==200
    feedback=client.get('/api/metrics/feedback').json()['messages']
    assert feedback['note'][0]['accepted']==1 and feedback['dm'][0]['accepted']==0

"""Explicitly fictional development fixtures. Never imported into the live database."""
from pathlib import Path
from scripts.tsenta_baseline import save_baseline
from backend.research import Source, Pick
from backend.store import now


class MemorySecrets:
    def __init__(self):self.data={}
    def get(self,name):return self.data.get(name)
    def put(self,name,value):self.data[name]=value
    def delete(self,name):self.data.pop(name,None)


def row(aid,status):
    return {'applicationId':aid,'status':status,'companyName':'Fictional Cedar Labs','jobTitle':'Software Engineer (fictional)',
            'url':'https://example.com/fictional-job','createdAt':'2026-09-18T05:00:00+00:00','updatedAt':now()}


def seed(path):
    if Path(path).exists():return
    result={'applications':[row('FICTIONAL-HISTORY','COMPLETED')],
            'pagination':{'page':1,'limit':100,'total':1,'totalPages':1}}
    save_baseline([{'tool':'list-applications','arguments':{'filter':'all','page':1,'limit':100},
        'response':{'result':{'structuredContent':{'tool':'list-applications','result':result}}}}],path)


class FixtureTsenta:
    def __init__(self,store):self.store=store
    async def snapshot(self):
        current=self.store.rows("SELECT source_application_id,source_status FROM applications WHERE source_application_id LIKE 'FICTIONAL-%'")
        return [row(r['source_application_id'],r['source_status']) for r in current]
    async def read(self,name,args):
        return {'applicationId':args['applicationId'],'status':'COMPLETED','isTerminal':True,'found':True}


class FixtureSearch:
    async def search(self,company,role):
        return [Source(id='fictional-source',url='https://www.linkedin.com/in/fictional-cedar-example',
            title=f'Avery Example — Fictional technical founder at {company}',excerpt=f'Avery Example is the fictional technical founder at {company}. Development fixture, not a real contact.',checked_at=now())]


class FixtureOllama:
    async def structured(self,schema,instruction,data):
        from backend.matching import RequirementReferences
        if schema is RequirementReferences:
            return RequirementReferences(requirements=[{'text':line,'source_index':i,'category':'skill','priority':'preferred' if 'preferred' in line.lower() else 'required'} for i,line in enumerate(data['source_spans'][:24])])
        raise ValueError('Fictional fixture supports requirements only')
    async def health(self):return {'available':True,'model':'FICTIONAL fixture (no model request)','message':'Fictional demo'}
    async def rank(self,company,role,sources):
        return [(Pick(source_id=sources[0].id,name='Avery Example',title='technical founder',company=company,
            evidence_quote=sources[0].excerpt[:350],
            relevance='Fictional small-company founder candidate for workflow testing.',uncertainty='Fictional fixture. Do not contact.'),sources[0])]
    async def draft(self,app,pick,facts,limits):
        from backend.note_renderer import render_note
        note,ids,explanation=render_note(pick.name,app['role'],app['company'],facts,limits.get('note_limit',200),exact=limits.get('exact_note_200',True),prefix='FICTIONAL DEMO: ')
        return {'note':note,'dm':'FICTIONAL DEMO: '+' '.join(f['text'] for f in facts[:2]),
            'grounding':{'fact_ids':[f['id'] for f in facts[:2]],'note_fact_ids':ids,'facts':[f['text'] for f in facts[:2]],
                'note_explanation':explanation,'method':'Fictional fixture, not model output'}}

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
            title='Avery Example — Fictional technical founder',excerpt='Avery Example is the fictional technical founder at Fictional Cedar Labs. Development fixture, not a real contact.',checked_at=now())]


class FixtureOllama:
    async def health(self):return {'available':True,'model':'FICTIONAL fixture (no model request)','message':'Fictional demo'}
    async def rank(self,company,role,sources):
        return [(Pick(source_id=sources[0].id,name='Avery Example',title='technical founder',company='Fictional Cedar Labs',
            evidence_quote='Avery Example is the fictional technical founder at Fictional Cedar Labs.',
            relevance='Fictional small-company founder candidate for workflow testing.',uncertainty='Fictional fixture. Do not contact.'),sources[0])]
    async def draft(self,app,pick,facts,limits):
        return {'note':'FICTIONAL DEMO: Hello Avery, I applied for Software Engineer (fictional) at Fictional Cedar Labs. I built a fictional Python project. I would value the chance to connect and learn more about the team.',
            'dm':'FICTIONAL DEMO: Hi Avery, I applied for the engineering role at Fictional Cedar Labs. I built a fictional Python project. Could you share more about the team?',
            'grounding':{'fact_ids':['fictional-fact'],'facts':['I built a fictional Python project.'],'method':'Fictional fixture, not model output'}}

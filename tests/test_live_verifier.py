import asyncio
import json
from scripts import verify_live
from backend.demo import MemorySecrets


def test_provider_report_contains_only_status_and_counts(monkeypatch):
    class Tsenta:
        def __init__(self,vault):pass
        async def snapshot(self):return [{'company':'PRIVATE COMPANY','applicationId':'PRIVATE ID'}]
    class Serper:
        def __init__(self,vault):pass
        async def results(self,query):
            assert query=='site:example.com "Example Domain"'
            return [{'snippet':'PRIVATE RESPONSE'}]
    class Ollama:
        async def health(self):return {'available':True,'model':'fictional'}
    monkeypatch.setattr(verify_live,'Tsenta',Tsenta)
    monkeypatch.setattr(verify_live,'Serper',Serper)
    monkeypatch.setattr(verify_live,'Ollama',Ollama)
    result=asyncio.run(verify_live.verify(['tsenta','serper','ollama'],MemorySecrets()))
    assert all(p['passed'] for p in result['providers'].values())
    assert 'PRIVATE' not in json.dumps(result)


def test_unexpected_errors_are_redacted(monkeypatch):
    class Tsenta:
        def __init__(self,vault):pass
        async def snapshot(self):raise ValueError('PRIVATE TOKEN AND RESPONSE')
    monkeypatch.setattr(verify_live,'Tsenta',Tsenta)
    result=asyncio.run(verify_live.verify(['tsenta'],MemorySecrets()))
    assert result['providers']['tsenta']=={'passed':False,'error_type':'ValueError'}
    assert 'PRIVATE' not in json.dumps(result)

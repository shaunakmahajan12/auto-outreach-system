import asyncio
import json
import pytest
from backend import posting_role
from backend.security import Unavailable
from tests.test_workflow import client


def test_structured_graph_preferred_over_heading():
    html='<h1>Cedar careers</h1><script type="application/ld+json">'+json.dumps({'@graph':[{'@type':'JobPosting','title':'Software Engineer'}]})+'</script>'
    assert posting_role.extract_title(html)==('Software Engineer','JobPosting structured data')
    assert posting_role.extract_title('<h1>Senior <span>Data Engineer</span></h1>')[0]=='Senior Data Engineer'


@pytest.mark.parametrize('html', ['<h1>Access denied</h1>','<h1>Careers</h1>','<div>Loading…</div>','<h1>Job not found</h1>','<h1>Engineer</h1><h1>Designer</h1>','<script type="application/ld+json">[{"@type":"JobPosting","title":"Engineer"},{"@type":"JobPosting","title":"Designer"}]</script>'])
def test_ambiguous_or_unusable_page_fails(html):
    with pytest.raises(Unavailable):posting_role.extract_title(html)


def test_private_dns_is_blocked(monkeypatch):
    monkeypatch.setattr(posting_role.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(Unavailable,match='public internet'):
        posting_role.PublicConnection('posting.example.com').connect()


def test_redirect_revalidated_and_response_bounded(monkeypatch):
    class Response:
        status=302
        def getheader(self,name,default=None):return 'https://localhost/private' if name=='Location' else default
    class Socket:
        def settimeout(self,value):assert 0<value<=8
    class Connection:
        def __init__(self,*a,**k):self.sock=Socket()
        def request(self,*a,**k):pass
        def getresponse(self):return Response()
        def close(self):pass
    monkeypatch.setattr(posting_role,'PublicConnection',Connection)
    with pytest.raises(ValueError):posting_role.fetch_posting('https://posting.example.com/job')
    Response.status=200
    Response.getheader=lambda self,*a:'text/html'
    Response.read1=lambda self,n:b'x'*n
    with pytest.raises(Unavailable,match='too large'):posting_role.fetch_posting('https://posting.example.com/job')


def test_review_and_save_only_missing_role_without_queuing(client,monkeypatch):
    store=client.app.state.store
    aid='FICTIONAL-HISTORY'
    with store.db() as db:db.execute('UPDATE applications SET role=NULL')
    calls=[]
    async def inspect(url):
        calls.append(url)
        return {'role':'Data Engineer','source_url':url,'method':'JobPosting structured data'}
    monkeypatch.setattr(posting_role,'inspect_posting',inspect)
    base=f'/api/applications/{aid}'
    result=client.post(base+'/extract-role')
    assert result.status_code==200 and result.json()['role']=='Data Engineer'
    assert calls==[store.rows('SELECT job_url FROM applications')[0]['job_url']]
    assert store.rows('SELECT role FROM applications')[0]['role'] is None
    assert client.post(base+'/extracted-role/save').status_code==200
    assert store.rows('SELECT role FROM applications')[0]['role']=='Data Engineer'
    assert store.rows('SELECT * FROM jobs')==[]
    assert store.rows('SELECT saved_at,source_url FROM posting_roles')[0]['saved_at']
    assert client.post(base+'/extract-role').status_code==400
    assert client.post(base+'/extracted-role/save').status_code==400


def test_failed_extraction_leaves_role_and_queue_untouched(client,monkeypatch):
    with client.app.state.store.db() as db:db.execute('UPDATE applications SET role=NULL')
    async def inspect(url):raise Unavailable('Posting unavailable')
    monkeypatch.setattr(posting_role,'inspect_posting',inspect)
    assert client.post('/api/applications/FICTIONAL-HISTORY/extract-role').status_code==409
    assert client.app.state.store.rows('SELECT role FROM applications')[0]['role'] is None
    assert client.app.state.store.rows('SELECT * FROM jobs')==[]


@pytest.mark.parametrize('method,expected',[('JobPosting structured data','Data Engineer'),('Posting heading',None)])
def test_background_extraction_saves_only_structured_titles(client,monkeypatch,method,expected):
    store=client.app.state.store
    with store.db() as db:db.execute('UPDATE applications SET role=NULL')
    calls=[]
    async def inspect(url):
        calls.append(url)
        return {'role':'Data Engineer','source_url':url,'method':method}
    monkeypatch.setattr(posting_role,'inspect_posting',inspect)
    assert asyncio.run(posting_role.fill_next_missing_role(store))
    assert store.rows('SELECT role FROM applications')[0]['role']==expected
    assert store.rows('SELECT * FROM jobs')==[]
    store.initialize()
    assert not asyncio.run(posting_role.fill_next_missing_role(store))
    assert len(calls)==1
    if expected is None:
        candidate=client.get('/api/state').json()['applications'][0]['role_candidate']
        assert candidate['role']=='Data Engineer'
        assert client.post('/api/applications/FICTIONAL-HISTORY/extracted-role/save').status_code==200


def test_background_failure_is_not_repeated_and_changed_link_retries(client,monkeypatch):
    store=client.app.state.store
    with store.db() as db:db.execute('UPDATE applications SET role=NULL')
    calls=[]
    async def inspect(url):
        calls.append(url)
        raise Unavailable('Posting unavailable')
    monkeypatch.setattr(posting_role,'inspect_posting',inspect)
    asyncio.run(posting_role.fill_next_missing_role(store))
    store.initialize()
    assert not asyncio.run(posting_role.fill_next_missing_role(store))
    assert len(calls)==1
    with store.db() as db:db.execute("UPDATE applications SET job_url='https://example.com/new-posting'")
    assert asyncio.run(posting_role.fill_next_missing_role(store))
    assert len(calls)==2


def test_background_preserves_role_entered_during_request(client,monkeypatch):
    store=client.app.state.store
    with store.db() as db:db.execute('UPDATE applications SET role=NULL')
    async def inspect(url):
        with store.db() as db:db.execute("UPDATE applications SET role='Manual role'")
        return {'role':'Data Engineer','source_url':url,'method':'JobPosting structured data'}
    monkeypatch.setattr(posting_role,'inspect_posting',inspect)
    asyncio.run(posting_role.fill_next_missing_role(store))
    assert store.rows('SELECT role FROM applications')[0]['role']=='Manual role'


def test_posting_read_stops_at_overall_deadline(monkeypatch):
    class Response:
        status=200
        def getheader(self,name,default=None):return 'text/html'
        def read1(self,n):return b'<'
    class Connection:
        def __init__(self,*a,**k):self.sock=type('Socket',(),{'settimeout':lambda self,v:None})()
        def request(self,*a,**k):pass
        def getresponse(self):return Response()
        def close(self):pass
    clock=iter(range(0,10000,5))
    monkeypatch.setattr(posting_role,'PublicConnection',Connection)
    monkeypatch.setattr(posting_role.time,'monotonic',lambda:next(clock))
    with pytest.raises(Unavailable,match='too long'):posting_role.fetch_posting('https://posting.example.com/job')

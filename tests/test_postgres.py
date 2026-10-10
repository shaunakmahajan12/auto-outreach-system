"""Live PostgreSQL integration, enabled by CI's ephemeral pgvector service."""
import asyncio
import os
import pytest
from backend.demo import seed,FixtureOllama,FixtureSearch,FixtureTsenta,MemorySecrets
from backend.store import Store
from backend.experience import ExperienceRepository,ExperienceInput,retrieve
from backend.postgres_store import PostgresStore
from scripts.migrate_database import migrate

@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'),reason='No ephemeral PostgreSQL service configured')
def test_full_import_repeatability_ledger_and_pgvector(tmp_path,monkeypatch):
    url=os.environ['TEST_DATABASE_URL'];source=tmp_path/'fictional.sqlite';seed(source)
    local=Store(source);local.initialize();repo=ExperienceRepository(local);repo.initialize()
    repo.save(ExperienceInput(text='I built a fictional Python service.',technologies=['Python'],status='approved'),'fictional-python')
    monkeypatch.setenv('RETRIEVAL_EMBEDDING_THRESHOLD','1')
    class CachedProvider:
        identity='fictional:1'
        async def embed(self,text):return [1.,0.,0.]
    asyncio.run(retrieve(repo,'Python',provider=CachedProvider()))
    before={t:local.rows('SELECT * FROM '+t) for t in ('applications','baseline','baseline_members','outreach_events')}
    counts=migrate(source,url);assert counts['applications']==1
    assert migrate(source,url)==counts
    pg=PostgresStore(url,tmp_path/'postgres.marker');pg.initialize()
    for table,rows in before.items():assert pg.rows('SELECT * FROM '+table)==rows
    pg.select_application('FICTIONAL-HISTORY');assert pg.rows('SELECT * FROM jobs')[0]['state']=='queued'
    from backend.engine import Engine
    engine=Engine(pg,FixtureTsenta(pg),FixtureSearch(),FixtureOllama());engine.experience=ExperienceRepository(pg,url)
    asyncio.run(engine.tick());assert len(pg.rows('SELECT * FROM drafts'))==1
    from backend.outreach import record_event
    cid=pg.rows('SELECT id FROM contacts')[0]['id']
    record_event(pg,cid,'dm_sent','fictional','fictional-pg-request')
    record_event(pg,cid,'dm_sent','fictional','fictional-pg-request')
    assert len(pg.rows('SELECT * FROM outreach_events'))==1
    with pytest.raises(Exception):
        with pg.db() as db:db.execute('DELETE FROM baseline')
    monkeypatch.setenv('RETRIEVAL_EMBEDDING_THRESHOLD','1')
    class Provider:
        identity='fictional:1'
        async def embed(self,text):
            assert text=='Python', 'Imported facts should reuse their cached embedding'
            return [1.,0.,0.]
    result=asyncio.run(retrieve(engine.experience,'Python',provider=Provider()))
    assert result['method']=='pgvector cosine'
    assert pg.rows('SELECT embedding_dimension FROM experience WHERE id=?',('fictional-python',))[0]['embedding_dimension']==3


"""Versioned experience repository. SQLAlchemy isolates SQLite/PostgreSQL differences."""
import hashlib
import json
import math
import os
import re
import uuid
from pathlib import Path
import httpx
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from sqlalchemy import create_engine, MetaData, Table, Column, String, Integer, Text, select, update, text
from backend.store import now

metadata = MetaData()
experience = Table('experience', metadata,
    Column('id', String(64), primary_key=True), Column('text', Text, nullable=False),
    Column('project', Text, nullable=False), Column('technologies', Text, nullable=False),
    Column('source_reference', Text, nullable=False), Column('status', String(16), nullable=False),
    Column('version', Integer, nullable=False), Column('updated_at', String(40), nullable=False),
    Column('content_hash', String(64), nullable=False), Column('embedding', Text),
    Column('embedding_model', Text), Column('embedding_dimension', Integer))

class ExperienceInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=2000)
    project: str = Field(default='', max_length=200)
    technologies: list[str] = Field(default_factory=list, max_length=30)
    source_reference: str = Field(default='', max_length=500)
    status: Literal['draft','approved','retired'] = 'draft'


def tokens(text):
    return set(re.findall(r'[a-z0-9+#]+', text.casefold())) - {'the','and','for','with','a','an','i','in','to','of','is','at','required','preferred'}

class ExperienceRepository:
    def __init__(self, store, url=None):
        self.store = store
        self.engine = create_engine(url or os.getenv('EXPERIENCE_DATABASE_URL') or (os.getenv('DATABASE_URL') if hasattr(store,'engine') else None) or f'sqlite:///{store.path}', echo=False)
    def initialize(self):
        metadata.create_all(self.engine)
        # Only import once. Do not resurrect retired or edited records from legacy settings.
        with self.engine.begin() as db:
            for fact in self.store.settings().get('facts', []):
                if db.execute(select(experience.c.id).where(experience.c.id == fact['id'])).first(): continue
                db.execute(experience.insert().values(**self.values(ExperienceInput(text=fact['text'], status='approved', source_reference='legacy approved settings'), fact['id'], 1)))
    @staticmethod
    def values(value, fid, version):
        content = value.model_dump()
        digest = hashlib.sha256(value.text.encode()).hexdigest()
        return dict(id=fid, **{**content, 'technologies':json.dumps(value.technologies)}, version=version,
                    updated_at=now(), content_hash=digest, embedding=None, embedding_model=None, embedding_dimension=None)
    def list(self, approved=False):
        query = select(experience)
        if approved: query = query.where(experience.c.status == 'approved')
        with self.engine.connect() as db:
            rows = [dict(r) for r in db.execute(query.order_by(experience.c.id)).mappings()]
        for row in rows: row['technologies'] = json.loads(row['technologies'])
        return rows
    def save(self, value, fid=None):
        fid = fid or str(uuid.uuid4())
        with self.engine.begin() as db:
            old = db.execute(select(experience).where(experience.c.id == fid)).mappings().first()
            if old:
                new = self.values(value, fid, old['version'] + 1)
                if all(new[k]==old[k] for k in ('text','project','technologies','source_reference','status')): return fid
                if old['status']=='approved' and any(new[k]!=old[k] for k in ('text','project','technologies','source_reference')):
                    new['status']='draft'  # Approve the persisted revision in a separate explicit action.
                if new['content_hash']==old['content_hash']:
                    for key in ('embedding','embedding_model','embedding_dimension'):new[key]=old[key]
                db.execute(update(experience).where(experience.c.id == fid).values(**new))
            else: db.execute(experience.insert().values(**self.values(value, fid, 1)))
        return fid
    def revision(self):
        return hashlib.sha256(json.dumps([(r['id'], r['version'], r['status'], r['content_hash']) for r in self.list()], sort_keys=True).encode()).hexdigest()[:20]

class Embeddings:
    def __init__(self):
        self.model = os.getenv('EMBEDDING_MODEL', 'nomic-embed-text')
        self.version = os.getenv('EMBEDDING_VERSION', '1')
        self.identity = self.model + ':' + self.version
    async def embed(self, text):
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            r = await client.post(os.getenv('OLLAMA_URL','http://127.0.0.1:11434').rstrip('/')+'/api/embed', json={'model':self.model,'input':text})
            r.raise_for_status()
            vector = r.json()['embeddings'][0]
        if not vector or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in vector): raise ValueError('Invalid embedding')
        return vector

async def retrieve(repo, query, limit=6, provider=None, force_embeddings=False):
    rows = repo.list(approved=True)  # Approval filter precedes either scoring path.
    terms = tokens(query)
    score = lambda r: len(terms & tokens(r['text']+' '+' '.join(r['technologies'])))
    ranked = sorted(rows, key=lambda r:(-score(r),r['id']))
    method, warning = 'lexical', None
    if force_embeddings or len(rows) >= int(os.getenv('RETRIEVAL_EMBEDDING_THRESHOLD','50')):
        provider = provider or Embeddings()
        try:
            q = await provider.embed(query)
            validate_vector(q)
            vectors = []
            for row in rows:
                if row['embedding'] and row['embedding_model'] == provider.identity and row['embedding_dimension']==len(q):
                    vector = json.loads(row['embedding'])
                else:
                    vector = await provider.embed(row['text'])
                    # Optimistic guard: content may change during external call.
                    with repo.engine.begin() as db:
                        db.execute(update(experience).where(experience.c.id==row['id'], experience.c.content_hash==row['content_hash'], experience.c.status=='approved').values(
                            embedding=json.dumps(vector),embedding_model=provider.identity,embedding_dimension=len(vector)))
                        if repo.engine.dialect.name == 'postgresql':
                            db.execute(text('UPDATE experience SET embedding_vector=CAST(:v AS vector) WHERE id=:id AND content_hash=:hash AND status=\'approved\''),{'v':json.dumps(vector),'id':row['id'],'hash':row['content_hash']})
                validate_vector(vector,len(q))
                # Imported JSON caches also need a pgvector value; do not re-embed valid content.
                if repo.engine.dialect.name=='postgresql':
                    with repo.engine.begin() as db:
                        db.execute(text("UPDATE experience SET embedding_vector=CAST(:v AS vector) WHERE id=:id AND content_hash=:hash AND embedding_model=:model AND embedding_dimension=:dimension AND status='approved'"),
                            {'v':json.dumps(vector),'id':row['id'],'hash':row['content_hash'],'model':provider.identity,'dimension':len(q)})
                norm=math.sqrt(sum(x*x for x in q)*sum(x*x for x in vector))
                vectors.append((sum(a*b for a,b in zip(q,vector))/norm if norm else 0,row))
            ranked=[r for _,r in sorted(vectors,key=lambda p:(-p[0],p[1]['id']))]
            if repo.engine.dialect.name=='postgresql':
                with repo.engine.connect() as db:
                    ids=list(db.execute(text("SELECT id FROM experience WHERE status='approved' AND embedding_model=:model AND embedding_dimension=:dimension AND embedding_vector IS NOT NULL ORDER BY embedding_vector <=> CAST(:query AS vector), id LIMIT :limit"),
                        {'model':provider.identity,'dimension':len(q),'query':json.dumps(q),'limit':limit}).scalars())
                by_id={r['id']:r for r in ranked};ranked=[by_id[fid] for fid in ids if fid in by_id]
            method='pgvector cosine' if repo.engine.dialect.name=='postgresql' else 'embedding cosine'
        except (httpx.HTTPError,ValueError,TypeError,KeyError,IndexError):
            ranked=sorted(rows,key=lambda r:(-score(r),r['id']))
            warning='Embeddings unavailable or stale; using approved lexical retrieval.'
    # Re-read approval/version after provider work to avoid a concurrent retirement leaking.
    current={r['id']:r for r in repo.list(approved=True)}
    ranked=[r for r in ranked if r['id'] in current and current[r['id']]['content_hash']==r['content_hash'] and current[r['id']]['version']==r['version']]
    selected=[]
    budget=0
    for fact in ranked:
        if len(selected)>=limit:break
        if budget+len(fact['text'])>2800:continue
        selected.append(fact);budget+=len(fact['text'])
    public=[{k:f[k] for k in ('id','text','project','technologies','source_reference','status','version','updated_at','content_hash')} for f in selected]
    return {'facts':public,'method':method,'warning':warning}


def validate_vector(vector,dimension=None):
    if not isinstance(vector,list) or not vector or not all(type(v) in (int,float) and math.isfinite(v) for v in vector) or (dimension is not None and len(vector)!=dimension):
        raise ValueError('Invalid embedding model dimensions; update the embedding version and retry')

def backfill_vectors(connection):
    """Populate imported valid caches. Retrieval additionally checks configured identity/dimension."""
    rows=connection.execute(text('SELECT id,embedding,embedding_model,embedding_dimension FROM experience WHERE embedding IS NOT NULL')).mappings()
    for row in rows:
        try:
            vector=json.loads(row['embedding']);validate_vector(vector,row['embedding_dimension'])
            if not row['embedding_model'] or not row['embedding_dimension']:continue
        except (ValueError,TypeError):continue
        connection.execute(text('UPDATE experience SET embedding_vector=CAST(:v AS vector) WHERE id=:id'),{'v':json.dumps(vector),'id':row['id']})

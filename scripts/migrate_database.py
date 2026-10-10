"""Validated all-table SQLite -> PostgreSQL import. Target must be empty.

Never changes source or switches configuration. Prints counts only, never data/URLs.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
from sqlalchemy import create_engine, MetaData, select, text
from alembic.config import Config
from alembic import command
from backend.store import Store
os.umask(0o077)
from backend.details import baseline_valid

def migrate(source_path,url):
    source_path=Path(source_path).resolve();backup=source_path.with_name(source_path.stem+'-before-postgres.sqlite')
    if not source_path.exists():raise ValueError('Source does not exist')
    if not backup.exists():
        with sqlite3.connect(source_path) as source,sqlite3.connect(backup) as target:source.backup(target)
        backup.chmod(0o600)
    store=Store(source_path);store.initialize()
    from backend.experience import ExperienceRepository
    ExperienceRepository(store,url=f'sqlite:///{source_path}').initialize()
    if not baseline_valid(store):raise ValueError('Source baseline invariant failed')
    with store.db() as db:
        if db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Source foreign keys invalid')
    os.environ['DATABASE_URL']=url
    command.upgrade(Config('alembic.ini'),'head')
    source=create_engine(f'sqlite:///{source_path}');target=create_engine(url,hide_parameters=True)
    metadata=MetaData();metadata.reflect(source)
    counts={}
    with source.connect() as read,target.begin() as write:
        # Freeze triggers protect updates/deletes, imports only insert into empty tables.
        for table in metadata.sorted_tables:
            rows=[dict(r) for r in read.execute(select(table)).mappings()]
            count=write.execute(text(f'SELECT count(*) FROM "{table.name}"')).scalar_one()
            existing=[dict(r) for r in write.execute(text(f'SELECT * FROM "{table.name}"')).mappings()]
            # Repeatable: skip identical imports; never merge divergent ledgers.
            compare=lambda values: sorted(json.dumps(r,sort_keys=True,default=str) for r in values)
            if count and compare([{k:r[k] for k in table.c.keys()} for r in existing])!=compare(rows):
                raise ValueError('Target differs; use an empty target or restore the matching snapshot')
            if rows and not count:write.execute(table.insert(),rows)
            after=[{k:r[k] for k in table.c.keys()} for r in write.execute(text(f'SELECT * FROM "{table.name}"')).mappings()]
            if compare(after)!=compare(rows):raise ValueError('Import content/count validation failed')
            counts[table.name]=len(after)
            if table.name in ('sync_runs','contacts','outreach_events','draft_feedback'):
                write.execute(text(f"SELECT setval(pg_get_serial_sequence('{table.name}','id'), COALESCE((SELECT MAX(id) FROM {table.name}),0)+1,false)"))
    from backend.experience import backfill_vectors
    with target.begin() as write:backfill_vectors(write)
    from backend.postgres_store import PostgresStore
    anchor=source_path.with_name('postgres-validation.marker')
    imported=PostgresStore(url,anchor)
    if not baseline_valid(imported):raise ValueError('Target baseline invariant failed')
    source.dispose();target.dispose()
    return counts
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source');args=parser.parse_args()
    try:print(json.dumps({'validated_row_counts':migrate(args.source,os.environ['DATABASE_URL'])},sort_keys=True))
    except Exception:raise SystemExit('Migration failed; transaction rolled back where possible. Source and backup retained. Check schema, connectivity and target emptiness; credentials omitted.')

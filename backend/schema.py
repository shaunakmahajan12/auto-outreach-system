"""Canonical full ledger schema derived from the local migrations using fictional data."""
import tempfile
from pathlib import Path
from sqlalchemy import MetaData, create_engine
from backend.demo import seed
from backend.store import Store
from backend.experience import ExperienceRepository

def ledger_metadata():
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'schema.sqlite'
        seed(path);store=Store(path);store.initialize();ExperienceRepository(store).initialize()
        source=create_engine(f'sqlite:///{path}')
        metadata=MetaData();metadata.reflect(source)
        source.dispose()
        # SQLite reflection may not preserve its expression index; install explicitly on PG.
        return metadata

def freeze_baseline(connection):
    connection.exec_driver_sql('''CREATE OR REPLACE FUNCTION protect_baseline() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Original baseline is immutable'; END $$''')
    for table in ('baseline','baseline_members'):
        connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS freeze_baseline ON {table}')
        connection.exec_driver_sql(f'CREATE TRIGGER freeze_baseline BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION protect_baseline()')
    connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS one_active_sync ON sync_runs((1)) WHERE state IN ('queued','running','retry')")

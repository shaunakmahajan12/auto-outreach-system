"""PostgreSQL ledger adapter. Legacy parameter/upsert syntax is isolated here.

Tables are managed by Alembic; first startup requires a validated import.
"""

import re
from contextlib import contextmanager
from sqlalchemy import create_engine, inspect, text
from backend.store import Store, now


class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Result:
    def __init__(self, result, lastrowid=None):
        self.result = result
        self.rowcount = result.rowcount
        self.lastrowid = lastrowid

    def fetchone(self):
        row = self.result.mappings().first()
        return Row(row) if row is not None else None

    def __iter__(self):
        return (Row(r) for r in self.result.mappings())

    def fetchall(self):
        return list(self)


class Connection:
    def __init__(self, connection, tables):
        self.connection = connection
        self.tables = tables

    def execute(self, sql, args=()):
        if sql == 'BEGIN IMMEDIATE':
            return Result(self.connection.execute(text('SELECT 1')))
        sql = sql.replace('ORDER BY rowid', 'ORDER BY application_id')
        # EXISTS returns bool in PostgreSQL; SQLite's baseline invariant compares 0/1.
        sql = sql.replace('historical != EXISTS(', 'historical != CAST(EXISTS(')
        if 'historical != CAST(EXISTS(' in sql:
            sql = sql.replace(
                'b.application_id=a.source_application_id)',
                'b.application_id=a.source_application_id) AS INTEGER)',
            )
        ignore = bool(re.match(r'\s*INSERT OR IGNORE', sql, re.I))
        replace = bool(re.match(r'\s*INSERT OR REPLACE', sql, re.I))
        sql = re.sub(r'INSERT OR (IGNORE|REPLACE)', 'INSERT', sql, flags=re.I)
        match = re.match(r'\s*INSERT INTO (\w+)', sql, re.I)
        table = match.group(1) if match else None
        if ignore:
            sql += ' ON CONFLICT DO NOTHING'
        if replace:
            columns, primary = self.tables[table]
            assignments = ','.join(f'{c}=EXCLUDED.{c}' for c in columns if c not in primary)
            sql += f' ON CONFLICT ({",".join(primary)}) DO UPDATE SET {assignments}'
        params = {f'p{i}': v for i, v in enumerate(args)}
        i = iter(range(len(args)))
        sql = re.sub(r'\?', lambda _: f':p{next(i)}', sql)
        returns = (
            table in ('sync_runs', 'contacts', 'outreach_events', 'draft_feedback')
            and not ignore
            and not replace
        )
        if returns:
            sql += ' RETURNING id'
        result = self.connection.execute(text(sql), params)
        if returns:
            value = result.scalar_one()
            return Result(result, value)
        return Result(result)


class PostgresStore(Store):
    def __init__(self, url, checkpoint_anchor):
        super().__init__(checkpoint_anchor)
        self.engine = create_engine(url, echo=False, pool_pre_ping=True, hide_parameters=True)
        inspector = inspect(self.engine)
        self.tables = {
            name: (
                [c['name'] for c in inspector.get_columns(name)],
                inspector.get_pk_constraint(name)['constrained_columns'],
            )
            for name in inspector.get_table_names()
        }

    @contextmanager
    def db(self):
        with self.engine.begin() as connection:
            yield Connection(connection, self.tables)

    def initialize(self):
        from backend.details import baseline_valid

        if not baseline_valid(self):
            raise RuntimeError(
                'PostgreSQL baseline missing or inconsistent. Run the validated import first.'
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)  # local marker/checkpoint anchor; no ledger data
        with self.db() as db:
            db.execute("UPDATE sync_runs SET state='retry' WHERE state='running'")
            db.execute(
                "UPDATE jobs SET state='interrupted',stage='interrupted',updated_at=? WHERE state='running'",
                (now(),),
            )
        self.reconcile_preparation_states()

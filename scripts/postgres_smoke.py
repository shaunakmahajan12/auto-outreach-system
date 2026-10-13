"""Run import/ledger/pgvector integration against a disposable PostgreSQL container."""
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time


def docker(*args,**kwargs):
    return subprocess.check_output(['docker',*args],text=True,**kwargs).strip()


def main():
    root=Path(__file__).resolve().parents[1]
    password=secrets.token_hex(24)
    environment={**os.environ,'POSTGRES_PASSWORD':password}
    container=docker('run','--detach','--rm','--publish','127.0.0.1::5432',
                     '--env','POSTGRES_PASSWORD','--env','POSTGRES_USER=outreach_test',
                     '--env','POSTGRES_DB=outreach_test','pgvector/pgvector:pg16',env=environment)
    try:
        deadline=time.monotonic()+90
        while subprocess.run(['docker','exec',container,'pg_isready','-U','outreach_test','-d','outreach_test'],
                             stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
            if time.monotonic()>=deadline:raise RuntimeError('Disposable PostgreSQL did not become ready.')
            time.sleep(1)
        port=docker('port',container,'5432/tcp').rsplit(':',1)[1]
        environment={**os.environ,'TEST_DATABASE_URL':f'postgresql+psycopg://outreach_test:{password}@127.0.0.1:{port}/outreach_test'}
        result=subprocess.run([sys.executable,'-m','pytest','-q','tests/test_postgres.py'],cwd=root,env=environment)
        if result.returncode:raise SystemExit(result.returncode)
        dump=subprocess.check_output(['docker','exec',container,'pg_dump','-U','outreach_test','-d','outreach_test','--format=custom'])
        docker('exec',container,'createdb','-U','outreach_test','outreach_restore')
        subprocess.run(['docker','exec','-i',container,'pg_restore','-U','outreach_test','-d','outreach_restore',
                        '--no-owner','--exit-on-error'],input=dump,check=True)
        def query(database,sql):
            return docker('exec',container,'psql','-U','outreach_test','-d',database,'-At','-v','ON_ERROR_STOP=1','-c',sql)
        tables=query('outreach_test',"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
        for table in tables:
            # Table names come from our migration schema, never user input.
            identifier='"'+table.replace('"','""')+'"'
            sql=f"SELECT count(*),md5(COALESCE(string_agg(row_to_json(t)::text,E'\\n' ORDER BY row_to_json(t)::text),'')) FROM {identifier} t"
            assert query('outreach_test',sql)==query('outreach_restore',sql),f'Restored content differs: {table}'
        protected=subprocess.run(['docker','exec',container,'psql','-U','outreach_test','-d','outreach_restore',
                                  '-v','ON_ERROR_STOP=1','-c','DELETE FROM baseline'],capture_output=True)
        assert protected.returncode!=0,'Restored immutable baseline trigger is missing'
        print('PASS: actual PostgreSQL import, repeat import, ledger, immutable baseline and cached pgvector retrieval.')
        print(f'PASS: pg_dump/pg_restore rehearsal; full contents of {len(tables)} tables match and baseline protection remains active.')
    finally:
        docker('stop',container)


if __name__=='__main__':main()

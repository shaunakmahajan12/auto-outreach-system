import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        if not self.path.exists():
            raise RuntimeError('Original Tsenta baseline missing. Restore .local/outreach.sqlite; never create a replacement baseline.')
        os.chmod(self.path, 0o600)
        with self.db() as db:
            baseline = db.execute('SELECT * FROM baseline WHERE singleton=1').fetchone()
            if not baseline:
                raise RuntimeError('Original baseline is required.')
            version = db.execute('PRAGMA user_version').fetchone()[0]
        if version < 1:
            backup = self.path.with_name(self.path.stem + '-before-v1.sqlite')
            if not backup.exists():
                with sqlite3.connect(self.path) as source, sqlite3.connect(backup) as target:
                    source.backup(target)
                os.chmod(backup, 0o600)
            with self.db() as db:
                db.execute('ALTER TABLE applications RENAME TO applications_original')
                db.execute('''CREATE TABLE applications (
                    source_application_id TEXT PRIMARY KEY, company TEXT, role TEXT, job_url TEXT,
                    job_description TEXT, submitted_at TEXT, submitted_resume_reference TEXT,
                    source_resume_profile_id TEXT, source_status TEXT NOT NULL, normalized_status TEXT NOT NULL,
                    source_created_at TEXT, source_updated_at TEXT, historical INTEGER NOT NULL CHECK(historical IN (0,1)),
                    confirmed_at_baseline INTEGER NOT NULL, missing_fields TEXT NOT NULL, research_state TEXT NOT NULL,
                    selected INTEGER NOT NULL DEFAULT 0, first_seen TEXT, first_confirmed TEXT, job_id TEXT,
                    detail_checked TEXT, last_error TEXT)''')
                columns = [r[1] for r in db.execute('PRAGMA table_info(applications_original)')]
                names = ','.join(columns)
                db.execute(f'INSERT INTO applications ({names}) SELECT {names} FROM applications_original')
                db.execute('UPDATE applications SET first_seen=?', (baseline['imported_at'],))
                db.execute('CREATE TABLE baseline_members (application_id TEXT PRIMARY KEY)')
                db.execute('INSERT INTO baseline_members SELECT source_application_id FROM applications_original')
                db.execute('DROP TABLE applications_original')
                db.execute('PRAGMA user_version=1')
        with self.db() as db:
            # SQL-level protection prevents a restart or later sync from moving the cutoff or baseline membership.
            for table in ('baseline', 'baseline_members'):
                for operation in ('UPDATE', 'DELETE'):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS freeze_{table}_{operation} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'Original baseline is immutable'); END")
            db.executescript('''
                CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sync_runs (id INTEGER PRIMARY KEY, state TEXT NOT NULL, started_at TEXT,
                    finished_at TEXT, attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL DEFAULT 0, error TEXT,
                    observed INTEGER DEFAULT 0, added INTEGER DEFAULT 0, eligible INTEGER DEFAULT 0);
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_sync ON sync_runs((1)) WHERE state IN ('queued','running','retry');
                CREATE TABLE IF NOT EXISTS jobs (application_id TEXT PRIMARY KEY REFERENCES applications(source_application_id),
                    state TEXT NOT NULL, attempts INTEGER DEFAULT 0, next_attempt REAL DEFAULT 0, error TEXT);
                CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(source_application_id),
                    source_key TEXT NOT NULL, name TEXT, title TEXT, company TEXT, linkedin_url TEXT, rank INTEGER,
                    evidence TEXT NOT NULL, relevance TEXT NOT NULL, uncertainty TEXT NOT NULL,
                    connection_status TEXT NOT NULL DEFAULT 'unknown', UNIQUE(application_id,source_key));
                CREATE TABLE IF NOT EXISTS drafts (contact_id INTEGER PRIMARY KEY REFERENCES contacts(id), note TEXT NOT NULL,
                    dm TEXT NOT NULL, grounding TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS outreach_events (id INTEGER PRIMARY KEY, contact_id INTEGER NOT NULL REFERENCES contacts(id),
                    kind TEXT NOT NULL, created_at TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', request_id TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS research_cache (application_id TEXT PRIMARY KEY, sources TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS posting_roles (application_id TEXT PRIMARY KEY REFERENCES applications(source_application_id),
                    role TEXT NOT NULL, source_url TEXT NOT NULL, posting_url TEXT NOT NULL, method TEXT NOT NULL, checked_at TEXT NOT NULL, saved_at TEXT);
                CREATE TABLE IF NOT EXISTS posting_role_checks (application_id TEXT PRIMARY KEY REFERENCES applications(source_application_id),
                    posting_url TEXT NOT NULL,status TEXT NOT NULL,error TEXT,checked_at TEXT NOT NULL);
            ''')
            db.execute('INSERT OR IGNORE INTO settings VALUES(1,?)', (json.dumps({'facts': [], 'note_limit': 200, 'dm_limit': 1200}),))
            db.execute("UPDATE sync_runs SET state='retry', error='Interrupted; will resume' WHERE state='running'")
        from backend.details import migrate
        migrate(self)
        from backend.details import migrate_company_metadata
        migrate_company_metadata(self)
        with self.db() as db:
            db.execute("UPDATE jobs SET stage=state WHERE state!='running' AND stage='queued' AND state!='queued'")
            db.execute("UPDATE jobs SET state='interrupted',stage='interrupted',error='Preparation was interrupted. Retry to resume using saved results.',updated_at=? WHERE state='running'",(now(),))
            db.execute("UPDATE applications SET research_state='interrupted',last_error='Preparation was interrupted. Retry to resume.' WHERE source_application_id IN (SELECT application_id FROM jobs WHERE state='interrupted')")

    def settings(self):
        with self.db() as db:
            return json.loads(db.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])

    def settings_save(self, value):
        with self.db() as db:
            db.execute('UPDATE settings SET data=? WHERE id=1', (json.dumps(value),))

    def enqueue_sync(self):
        with self.db() as db:
            active = db.execute("SELECT id FROM sync_runs WHERE state IN ('queued','running','retry')").fetchone()
            if active:
                return active['id']
            return db.execute("INSERT INTO sync_runs(state,started_at) VALUES('queued',?)", (now(),)).lastrowid

    def select_application(self, app_id, company=None, role=None):
        from backend.details import baseline_valid
        if not baseline_valid(self):raise ValueError('Original baseline is missing or inconsistent. Restore it before preparing outreach.')
        with self.db() as db:
            app = db.execute('SELECT * FROM applications WHERE source_application_id=?', (app_id,)).fetchone()
            if not app:
                raise ValueError('Application not found')
            if app['source_status'] != 'COMPLETED':
                raise ValueError('Only a confirmed COMPLETED submission can be researched')
            if app['hiring_outcome'] in ('rejected','job_closed'):raise ValueError('This application is marked rejected or closed. Correct its hiring outcome before preparing new outreach.')
            for field,value in (('company',company),('role',role)):
                if value is not None:
                    if not value.strip():raise ValueError('Company and role cannot be blank')
                    db.execute(f'UPDATE applications SET {field}=? WHERE source_application_id=?',(value.strip(),app_id))
            if app['research_state']=='no_contacts':
                db.execute('DELETE FROM research_cache WHERE application_id=?',(app_id,))
                db.execute("UPDATE jobs SET state='interrupted' WHERE application_id=? AND state='done'",(app_id,))
            db.execute('UPDATE applications SET selected=1 WHERE source_application_id=?', (app_id,))
            db.execute("INSERT OR IGNORE INTO jobs(application_id,state) VALUES(?,'queued')", (app_id,))
            db.execute("UPDATE jobs SET state='queued',stage='queued',updated_at=?, attempts=0,next_attempt=0,error=NULL WHERE application_id=? AND state IN ('blocked','failed','interrupted','dismissed')", (now(),app_id))
            db.execute("UPDATE applications SET research_state=COALESCE((SELECT state FROM jobs WHERE application_id=?),'queued'),last_error=NULL WHERE source_application_id=?", (app_id,app_id))

    def dismiss_preparation(self, app_id):
        with self.db() as db:
            job=db.execute('SELECT state FROM jobs WHERE application_id=?',(app_id,)).fetchone()
            if not job:raise ValueError('No preparation to dismiss')
            if job['state'] not in ('queued','retry','blocked','failed','interrupted','dismissed'):
                raise ValueError('Preparation has already started or finished. Refresh to see its status.')
            db.execute("UPDATE jobs SET state='dismissed',stage='dismissed',error=NULL,updated_at=? WHERE application_id=?",(now(),app_id))
            db.execute("UPDATE applications SET research_state='dismissed',selected=0,last_error=NULL WHERE source_application_id=?",(app_id,))

    def apply_snapshot(self, rows):
        from scripts.tsenta_baseline import normalize_status
        from backend.details import baseline_valid, sync_metadata
        if not baseline_valid(self):raise ValueError('Original baseline is missing or inconsistent; synchronization stopped safely.')
        added = eligible = 0
        with self.db() as db:
            if not db.execute('SELECT 1 FROM baseline WHERE singleton=1').fetchone():
                raise ValueError('Cannot sync without the original baseline')
            for row in rows:
                aid = row['applicationId']
                status = row['status']
                old = db.execute('SELECT * FROM applications WHERE source_application_id=?', (aid,)).fetchone()
                historical = bool(db.execute('SELECT 1 FROM baseline_members WHERE application_id=?', (aid,)).fetchone())
                missing = [k for k,v in {'company':row.get('companyName'),'role':row.get('jobTitle'),'job_url':row.get('url'),
                                       'job_description':None,'submitted_at':None,'submitted_resume_reference':None}.items() if not v]
                if not old:
                    added += 1
                    db.execute('''INSERT INTO applications(source_application_id,company,role,job_url,source_resume_profile_id,
                        source_status,normalized_status,source_created_at,source_updated_at,historical,confirmed_at_baseline,
                        missing_fields,research_state,first_seen,job_id) VALUES(?,?,?,?,?,?,?,?,?,?,0,?,?,?,?)''',
                        (aid,row.get('companyName'),row.get('jobTitle'),row.get('url'),row.get('resumeProfileId'),status,
                         normalize_status(status),row.get('createdAt'),row.get('updatedAt'),int(historical),json.dumps(missing),
                         'historical_no_outreach' if historical else 'awaiting_submission',now(),row.get('jobId')))
                else:
                    db.execute('''UPDATE applications SET company=COALESCE(NULLIF(?,''),company),role=COALESCE(NULLIF(?,''),role),job_url=?,source_status=?,normalized_status=?,
                        source_updated_at=?,job_id=COALESCE(?,job_id),source_resume_profile_id=COALESCE(?,source_resume_profile_id)
                        WHERE source_application_id=?''',(row.get('companyName'),row.get('jobTitle'),row.get('url'),status,
                        normalize_status(status),row.get('updatedAt'),row.get('jobId'),row.get('resumeProfileId'),aid))
                # Membership, not a movable timestamp/high-water mark, excludes the original 281.
                # Newly observed COMPLETED IDs qualify even after offline/development gaps.
                sync_metadata(db,aid,row)
                if status == 'COMPLETED' and (not old or old['hiring_outcome'] not in ('rejected','job_closed')) and (not historical or (old and (old['selected'] or not old['confirmed_at_baseline']))):
                    db.execute('UPDATE applications SET first_confirmed=COALESCE(first_confirmed,?) WHERE source_application_id=?',(now(),aid))
                    if os.getenv('OUTREACH_AUTO_RESEARCH','true').lower() != 'true':
                        continue
                    cur = db.execute("INSERT OR IGNORE INTO jobs(application_id,state) VALUES(?,'queued')", (aid,))
                    if cur.rowcount:
                        eligible += 1
                        db.execute("UPDATE applications SET research_state='queued' WHERE source_application_id=?",(aid,))
                elif status != 'COMPLETED':
                    # Keep blocked work recoverable if Tsenta later confirms completion again.
                    db.execute("UPDATE jobs SET state='blocked',error='Submission is no longer confirmed' WHERE application_id=? AND state!='done'",(aid,))
            return {'observed':len(rows),'added':added,'eligible':eligible}

    def rows(self, sql, args=()):
        with self.db() as db:
            return [dict(r) for r in db.execute(sql,args)]

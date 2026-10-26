"""Additive, repeatable local migration. Never rewrites drafts or baseline rows."""

from backend.store import backup, now


def migrate(store):
    backup(store, '-before-engineering-v1.sqlite')
    backup(store, '-before-correctness-v2.sqlite')
    with store.db() as db:
        db.execute(
            'CREATE TABLE IF NOT EXISTS message_feedback(suggestion_id TEXT NOT NULL REFERENCES draft_suggestions(id), kind TEXT NOT NULL, accepted INTEGER NOT NULL, edited INTEGER NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(suggestion_id,kind))'
        )
        db.execute(
            'CREATE TABLE IF NOT EXISTS preparation_epochs(application_id TEXT PRIMARY KEY, epoch INTEGER NOT NULL DEFAULT 0)'
        )
        db.execute(
            'CREATE TABLE IF NOT EXISTS preparation_resume_requests(application_id TEXT PRIMARY KEY)'
        )
        applied = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='engineering_migrations'"
        ).fetchone()
        if (
            applied
            and db.execute("SELECT 1 FROM engineering_migrations WHERE version=1").fetchone()
        ):
            return
    with store.db() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS engineering_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS descriptions(application_id TEXT PRIMARY KEY REFERENCES applications(source_application_id),
          text TEXT NOT NULL, source_url TEXT NOT NULL, provenance TEXT NOT NULL, updated_at TEXT NOT NULL, version INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS match_reviews(application_id TEXT PRIMARY KEY REFERENCES applications(source_application_id),
          data TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS draft_suggestions(id TEXT PRIMARY KEY, contact_id INTEGER NOT NULL REFERENCES contacts(id),
          note TEXT NOT NULL, dm TEXT NOT NULL, grounding TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS draft_feedback(id INTEGER PRIMARY KEY, suggestion_id TEXT NOT NULL UNIQUE REFERENCES draft_suggestions(id),
          accepted INTEGER NOT NULL, edited INTEGER NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS preparation_runs(id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(source_application_id),
          input_version TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(application_id,input_version));
        ''')
        db.execute('INSERT OR IGNORE INTO engineering_migrations VALUES(1,?)', (now(),))

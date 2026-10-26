"""Source provenance, conservative mappings, and additive v2 migration."""

import json
from datetime import datetime
from pathlib import Path
from backend.store import backup, now


def migrate(store):
    with store.db() as db:
        version = db.execute('PRAGMA user_version').fetchone()[0]
    if version >= 2:
        return
    backup(store, '-before-v2.sqlite')
    with store.db() as db:
        # Explicit transaction: ALTER TABLE and version stamp must commit together.
        db.execute('BEGIN IMMEDIATE')
        for table, columns in {
            'applications': [
                ('source_job_status', 'TEXT'),
                ('hiring_outcome', "TEXT NOT NULL DEFAULT 'unknown'"),
                ('outcome_note', "TEXT NOT NULL DEFAULT ''"),
                ('outcome_updated_at', 'TEXT'),
                ('details_checked_at', 'TEXT'),
                ('details_error', 'TEXT'),
            ],
            'contacts': [
                ('review_status', "TEXT NOT NULL DEFAULT 'needs_review'"),
                ('review_note', "TEXT NOT NULL DEFAULT ''"),
                ('review_source', 'TEXT'),
                ('reviewed_at', 'TEXT'),
                ('dismissed', 'INTEGER NOT NULL DEFAULT 0'),
                ('original_fields', 'TEXT'),
            ],
            'jobs': [('stage', "TEXT NOT NULL DEFAULT 'queued'"), ('updated_at', 'TEXT')],
            'outreach_events': [('undone_at', 'TEXT')],
        }.items():
            existing = {r[1] for r in db.execute(f'PRAGMA table_info({table})')}
            for name, kind in columns:
                if name not in existing:
                    db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {kind}')
        db.execute('PRAGMA user_version=2')


def baseline_valid(store):
    with store.db() as db:
        base = db.execute('SELECT * FROM baseline WHERE singleton=1').fetchone()
        if not base:
            return False
        try:
            stamp = datetime.fromisoformat(base['imported_at'])
            if stamp.tzinfo is None:
                return False
        except (ValueError, TypeError):
            return False
        members = db.execute('SELECT count(*) FROM baseline_members').fetchone()[0]
        missing = db.execute(
            'SELECT count(*) FROM baseline_members b LEFT JOIN applications a ON a.source_application_id=b.application_id WHERE a.source_application_id IS NULL'
        ).fetchone()[0]
        inconsistent = db.execute(
            'SELECT count(*) FROM applications a WHERE historical != EXISTS(SELECT 1 FROM baseline_members b WHERE b.application_id=a.source_application_id)'
        ).fetchone()[0]
        return members == base['record_count'] and not missing and not inconsistent


def protection(app, valid=True):
    if not valid:
        return 'Baseline needs review — automatic outreach disabled'
    if app['historical'] and app['confirmed_at_baseline']:
        return 'Historical application — automatic outreach disabled' + (
            '; explicitly selected by you' if app['selected'] else ''
        )
    if app['historical']:
        return 'Not submitted at original baseline — eligible once submission is confirmed after the cutoff'
    return 'After original baseline — eligible when submission is confirmed'


def sync_metadata(db, aid, row):
    company_metadata(db, aid, row)
    # These exact fields were observed in authenticated list/detail responses.
    db.execute(
        'UPDATE applications SET job_id=COALESCE(?,job_id),source_job_status=COALESCE(?,source_job_status) WHERE source_application_id=?',
        (row.get('jobId'), row.get('jobStatus'), aid),
    )
    app = db.execute('SELECT * FROM applications WHERE source_application_id=?', (aid,)).fetchone()
    if app:
        missing = [
            k
            for k in (
                'company',
                'role',
                'job_url',
                'job_description',
                'submitted_at',
                'submitted_resume_reference',
            )
            if not app[k]
        ]
        db.execute(
            'UPDATE applications SET missing_fields=? WHERE source_application_id=?',
            (json.dumps(missing), aid),
        )


def backfill_captures(store, directory):
    """Local verified captures only; never replay old status or move the baseline."""
    count = 0
    with store.db() as db:
        for name in ('tsenta-read-003.json', 'tsenta-read-004.json', 'tsenta-read-005.json'):
            path = Path(directory) / name
            if not path.exists():
                continue
            capture = json.loads(path.read_text())
            if capture.get('tool') != 'list-applications':
                continue
            rows = capture['response']['result']['structuredContent']['result']['applications']
            for row in rows:
                company_metadata(db, row['applicationId'], row, fill_only=True)
                count += db.execute(
                    'UPDATE applications SET job_id=COALESCE(job_id,?),source_job_status=COALESCE(source_job_status,?) WHERE source_application_id=?',
                    (row.get('jobId'), row.get('jobStatus'), row['applicationId']),
                ).rowcount
    return count


def contact_support(contact):
    evidence = contact['evidence']
    text = (evidence.get('source_title', '') + ' ' + evidence.get('excerpt', '')).casefold()
    fields = {
        k: (
            'Appears in search evidence; not independently verified'
            if contact.get(k) and contact[k].casefold() in text
            else 'Not established by the saved source'
        )
        for k in ('name', 'title', 'company')
    }
    fields['linkedin_url'] = (
        'URL returned by public search; profile identity not independently checked'
    )
    labels = {
        'needs_review': 'Evidence not verified',
        'supported': 'Supported by source',
        'conflicting': 'Conflicting information',
    }
    status = contact['review_status']
    reason = (
        contact['review_note']
        if status != 'needs_review'
        else 'Search snippets and model extraction only. Current employment and relevance to this opening have not been established.'
    )
    return {
        'label': labels[status],
        'reason': reason,
        'fields': fields,
        'scope': 'Supported by source reflects your recorded source review, not an independent employment verification.',
        'employment': 'Current employment not independently established.',
        'opening': 'Ownership of or involvement in this opening is not established.',
    }


def migrate_company_metadata(store):
    with store.db() as db:
        if db.execute('PRAGMA user_version').fetchone()[0] >= 3:
            return
    backup(store, '-before-v3.sqlite')
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        columns = {r[1] for r in db.execute('PRAGMA table_info(applications)')}
        for name in ('company_website', 'locations'):
            if name not in columns:
                db.execute(f'ALTER TABLE applications ADD COLUMN {name} TEXT')
        db.execute('PRAGMA user_version=3')


def company_metadata(db, aid, row, fill_only=False):
    from backend.security import public_url

    website = row.get('companyWebsite')
    if isinstance(website, str) and website and '://' not in website:
        website = 'https://' + website
    try:
        website = public_url(website) if website else None
    except ValueError:
        website = None
    locations = row.get('locations')
    # Preserve only documented string/list shapes; never stringify arbitrary objects.
    if isinstance(locations, str):
        locations = [locations]
    if not isinstance(locations, list) or not all(isinstance(v, str) for v in locations):
        locations = None
    locations = json.dumps([v.strip() for v in locations if v.strip()]) if locations else None
    if fill_only:
        db.execute(
            'UPDATE applications SET company_website=COALESCE(company_website,?),locations=COALESCE(locations,?) WHERE source_application_id=?',
            (website, locations, aid),
        )
    else:
        db.execute(
            'UPDATE applications SET company_website=COALESCE(?,company_website),locations=COALESCE(?,locations) WHERE source_application_id=?',
            (website, locations, aid),
        )

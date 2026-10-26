"""Ephemeral fictional browser-test server. No test routes exist in the real app."""

import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from backend.security import Retryable

with tempfile.TemporaryDirectory(prefix='outreach-fictional-e2e-') as directory:
    os.environ.update(
        OUTREACH_DEMO='true',
        OUTREACH_REMOTE='false',
        OUTREACH_DB=str(Path(directory) / 'fictional.sqlite'),
        OUTREACH_AUTO_ROLE_EXTRACTION='false',
        OUTREACH_AUTO_RESEARCH='true',
        TSENTA_POLL_ENABLED='false',
    )
    from backend.main import create_app

    app = create_app(start_worker=False)
    from starlette.routing import Mount

    mounts = [r for r in app.router.routes if isinstance(r, Mount)]
    app.router.routes = [r for r in app.router.routes if not isinstance(r, Mount)]

    @app.post('/api/test/tick')
    async def tick():
        await app.state.engine.tick()
        return {'advanced': True}

    original = app.state.engine.search.search

    @app.post('/api/test/provider/{state}')
    async def provider(state: str):
        async def failed(*args):
            raise Retryable('Fictional provider failure. Restore provider and resume.')

        app.state.engine.search.search = failed if state == 'fail' else original
        return {'configured': True}

    @app.post('/api/test/pause')
    def pause():
        store = app.state.store
        config = store.settings()
        config['pause_before_persistence'] = True
        store.settings_save(config)
        return {'configured': True}

    @app.post('/api/test/showcase')
    async def showcase():
        import json

        store = app.state.store
        store.select_application('FICTIONAL-HISTORY')
        await app.state.engine.tick()
        with store.db() as db:
            source = dict(db.execute('SELECT * FROM contacts ORDER BY id LIMIT 1').fetchone())
            draft = dict(
                db.execute('SELECT * FROM drafts WHERE contact_id=?', (source['id'],)).fetchone()
            )
            for index, title in enumerate(
                (
                    'Senior Engineering Manager, Platform & Developer Experience',
                    'Technical Recruiter — Infrastructure and Cloud Services',
                )
            ):
                if db.execute(
                    'SELECT 1 FROM contacts WHERE source_key=?', ('showcase-' + str(index),)
                ).fetchone():
                    continue
                contact = {
                    **source,
                    'source_key': 'showcase-' + str(index),
                    'name': ('Jordan Fictional', 'Morgan Example')[index],
                    'title': title,
                    'linkedin_url': 'https://www.linkedin.com/in/fictional-showcase-' + str(index),
                }
                contact['evidence'] = json.dumps(
                    {
                        'source_title': contact['name']
                        + ' — '
                        + title
                        + ' at '
                        + source['company'],
                        'excerpt': contact['name']
                        + ' is '
                        + title
                        + ' at '
                        + source['company']
                        + '. Fictional evidence only.',
                        'url': contact['linkedin_url'],
                        'checked_at': '2026-10-10T12:00:00Z',
                    }
                )
                contact.pop('id')
                keys = list(contact)
                cid = db.execute(
                    'INSERT INTO contacts ('
                    + ','.join(keys)
                    + ') VALUES ('
                    + ','.join('?' for _ in keys)
                    + ')',
                    tuple(contact.values()),
                ).lastrowid
                from backend.note_renderer import render_note

                fact = next(
                    f
                    for f in app.state.engine.experience.list(approved=True)
                    if f['id'] == 'fictional-fact'
                )
                application = store.rows(
                    'SELECT role,company FROM applications WHERE source_application_id=?',
                    (source['application_id'],),
                )[0]
                note, _, explanation = render_note(
                    contact['name'],
                    application['role'],
                    application['company'],
                    [fact],
                    200,
                    exact=True,
                    prefix='FICTIONAL DEMO: ',
                )
                grounding = json.loads(draft['grounding'])
                grounding['note_explanation'] = explanation
                copy = {
                    **draft,
                    'contact_id': cid,
                    'note': note,
                    'dm': 'FICTIONAL DEMO: ' + fact['text'],
                    'grounding': json.dumps(grounding),
                }
                keys = list(copy)
                db.execute(
                    'INSERT INTO drafts ('
                    + ','.join(keys)
                    + ') VALUES ('
                    + ','.join('?' for _ in keys)
                    + ')',
                    tuple(copy.values()),
                )
        from backend.outreach import record_event

        record_event(
            store,
            source['id'],
            'dm_sent',
            'Fictional visual verification only',
            'showcase-fictional-event',
        )
        return {'ready': True}

    app.router.routes.extend(mounts)
    uvicorn.run(app, host='127.0.0.1', port=8765, access_log=False, log_level='warning')

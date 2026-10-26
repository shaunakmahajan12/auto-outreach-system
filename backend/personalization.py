"""Shared preparation entry point; suggestions are immutable until explicitly accepted."""

import json
import uuid
from backend.matching import prepare_match
from backend.security import Unavailable
from backend.store import now


async def personalize(store, repo, model, app, pick, limits, matching=None):
    matching = matching or await prepare_match(repo, model, app, pick.title or '')
    # Contact context can alter bounded retrieval without re-extracting requirements.
    if pick.title and matching['requirements']:
        from backend.experience import retrieve
        from backend.matching import match

        result = await retrieve(
            repo, ' '.join(r['text'] for r in matching['requirements']) + ' ' + pick.title
        )
        matches = match(matching['requirements'], result['facts'])
        ids = {f['fact_id'] for r in matches for f in r['supporting_facts']}
        matching = {
            **matching,
            'matches': matches,
            'selected_facts': [f for f in result['facts'] if f['id'] in ids],
            'contact_context': pick.title,
            'method': result['method'],
            'warning': result['warning'],
        }
    selected = matching['selected_facts']
    if not selected:
        raise Unavailable(
            'No supporting approved evidence selected. Review requirements and approve a relevant fact before drafting.'
        )
    enriched = {**app, 'requirements': matching['requirements'], 'matching': matching}
    result = await model.draft(enriched, pick, selected, limits)
    from backend.security import Retryable

    current = {f['id']: f for f in repo.list(approved=True)}
    if any(
        f['id'] not in current
        or current[f['id']]['content_hash'] != f['content_hash']
        or current[f['id']]['version'] != f['version']
        for f in selected
    ):
        raise Retryable(
            'Approved experience changed during generation. Retry with the current collection; previous draft retained.'
        )
    result['grounding']['matching'] = matching
    result['grounding']['experience_versions'] = {f['id']: f['version'] for f in selected}
    result['grounding']['description_version'] = matching['description_provenance']['version']
    result['grounding']['description_hash'] = (
        matching.get('description_hash')
        or __import__('hashlib').sha256((app.get('job_description') or '').encode()).hexdigest()
    )
    result['grounding']['source_references'] = {f['id']: f['source_reference'] for f in selected}
    return result


def save_suggestion(store, cid, result):
    sid = str(uuid.uuid4())
    with store.db() as db:
        db.execute(
            'INSERT INTO draft_suggestions VALUES(?,?,?,?,?,?)',
            (sid, cid, result['note'], result['dm'], json.dumps(result['grounding']), now()),
        )
    return {**result, 'suggestion_id': sid}


def validate_acceptance(store, repo, application_id, grounding):
    """Reject stale generated evidence; manual draft updates do not call this guard."""
    import hashlib

    versions = grounding.get('experience_versions')
    if not versions:
        raise ValueError(
            'Suggestion has no versioned evidence. Regenerate it; your existing draft is unchanged.'
        )
    current = {f['id']: f for f in repo.list(approved=True)}
    if any(
        fid not in current or current[fid]['version'] != version
        for fid, version in versions.items()
    ):
        raise ValueError(
            'Supporting experience changed or is no longer approved. Regenerate the suggestion; your existing draft is unchanged.'
        )
    rows = store.rows('SELECT version FROM descriptions WHERE application_id=?', (application_id,))
    version = rows[0]['version'] if rows else 0
    app = store.rows(
        'SELECT job_description FROM applications WHERE source_application_id=?', (application_id,)
    )[0]
    digest = hashlib.sha256((app['job_description'] or '').encode()).hexdigest()
    if version != grounding.get('description_version') or digest != grounding.get(
        'description_hash'
    ):
        raise ValueError(
            'Job description changed. Regenerate the suggestion; your existing draft is unchanged.'
        )

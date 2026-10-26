"""Conservative source-only title extraction and explainable application relevance."""

import json
import re

ROLE = re.compile(
    r'\b(recruiter|recruiting|talent acquisition|engineer|architect|analyst|scientist|manager|director|founder|president|head|lead|leader|partner|consultant|associate|VP|CTO|CEO|MD)\b',
    re.I,
)


def extract_title(name, evidence):
    headline = evidence.get('source_title') or evidence.get('title') or ''
    match = re.match(
        r'^' + re.escape(name) + r'(?:,\s*(?:M\.S\.|Ph\.D\.))?\s*[-–—|]\s*(.+)', headline, re.I
    )
    if match:
        title = re.split(
            r'\s+(?:@|at)\s+|\s*[|·]\s*|\s+-\s+(?:LinkedIn|We\b)|\s*\(',
            match[1],
            maxsplit=1,
            flags=re.I,
        )[0].strip(' ,')
        # Do not publish a clipped headline or turn a list of interests into a job title.
        if (
            2 < len(title) <= 160
            and not re.search(r'\.\.\.|…|\bex-|\b(?:certified|enthusiast|years)\b', title, re.I)
            and ROLE.search(title)
        ):
            return title
    excerpt = evidence.get('excerpt') or ''
    # Only explicit attribution, never generated relevance/review notes.
    patterns = [
        re.escape(name) + r'\s+(?:is|works as)\s+(?:an?\s+|the\s+)?(.+?)\s+at\s+',
        r'currently serving as (?:an?\s+)?([^,.;]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, excerpt, re.I)
        if match:
            title = match[1].strip()
            if 2 < len(title) <= 100 and ROLE.search(title) and not re.search(r'\.\.\.|…', title):
                return title
    return None


def backfill_titles(store):
    """Fill missing unedited fields only; sources and user corrections remain untouched."""
    changed = 0
    with store.db() as db:
        for row in db.execute(
            "SELECT id,name,evidence FROM contacts WHERE (title IS NULL OR trim(title)='') AND original_fields IS NULL"
        ).fetchall():
            title = extract_title(row['name'], json.loads(row['evidence']))
            if title:
                changed += db.execute(
                    'UPDATE contacts SET title=? WHERE id=? AND (title IS NULL OR trim(title)=\'\')',
                    (title, row['id']),
                ).rowcount
    return changed


DOMAINS = {
    'engineering': r'\b(?:software|engineering|engineer|developer|technical|platform)\b',
    'data': r'\b(?:data|analytics|analyst|scientist|science|quantitative|machine learning|AI|ML)\b',
    'early career': r'\b(?:university|campus|graduate|new grad|early career|intern|emerging talent)\b',
}


def assess_relevance(contact):
    evidence = contact.get('evidence') or {}
    headline = evidence.get('source_title', '')
    excerpt = evidence.get('excerpt', '')
    title = contact.get('title') or extract_title(contact.get('name', ''), evidence)
    company = (contact.get('application_company') or '').strip()

    def result(level, explanation):
        return {'level': level, 'explanation': explanation, 'method': 'source-rules-v2'}

    if (
        not title
        or not company
        or not contact.get('role')
        or contact.get('review_status') == 'conflicting'
    ):
        return result(
            'unassessed',
            'A supported title, application role, and company association are needed; conflicting evidence requires review.',
        )
    text = headline + ' ' + excerpt
    if title.casefold() not in text.casefold():
        return result(
            'unassessed',
            'The saved source does not support the displayed title. Review a current source before preparing outreach.',
        )
    # An explicit at/@ association is stronger than mere company mention or model inference.
    association = re.compile(r'(?:\bat\s+|@\s*)' + re.escape(company) + r'(?!\w)', re.I)
    name = (contact.get('name') or '').strip()
    associated = bool(name) and any(
        re.search(re.escape(name) + r'.{0,180}' + association.pattern, sentence, re.I)
        and not re.search(r'\b(?:former|previously|past|ex-)\b', sentence, re.I)
        for sentence in (headline, *re.split(r'[.!?]\s+', excerpt))
    )
    if not associated:
        return result(
            'low',
            'The saved source does not explicitly associate this person’s professional context with the application company.',
        )
    domains = [
        name
        for name, pattern in DOMAINS.items()
        if re.search(pattern, contact['role'], re.I)
        and re.search(pattern, title + ' ' + excerpt, re.I)
    ]
    recruiting = bool(re.search(r'recruit|talent acquisition', title, re.I))
    leadership = bool(
        re.search(r'\b(?:manager|director|head|founder|CTO|lead|leader)\b', title, re.I)
    )
    if domains and (recruiting or leadership):
        return result(
            'high',
            'Source names the application company and a recruiting/leadership title aligned with '
            + ', '.join(domains)
            + '. This does not establish ownership of this opening.',
        )
    if recruiting or domains:
        return result(
            'medium',
            'Source names the application company and '
            + (
                'a recruiting title, but no clear role-domain match.'
                if recruiting
                else 'related '
                + ', '.join(domains)
                + ' experience, but no recruiting/leadership connection.'
            ),
        )
    return result(
        'low',
        'Source names the company, but the supported position has no clear recruiting or role-domain alignment.',
    )

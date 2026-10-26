"""Bounded connection notes made only from application context and approved facts."""

from backend.security import Unavailable


def render_note(name, role, company, facts, limit, exact=False, prefix=""):
    first = name.split()[0] if name.strip() else ''
    if not first or not role or not company:
        raise Unavailable(
            'A recipient name, application role, and company are required before drafting.'
        )
    opening = f'Hi {first}, I applied for {role} at {company}.'
    closings = [
        'I’d value the chance to connect and learn more about the team.',
        'I’d be glad to connect.',
        'May we connect?',
    ]
    if exact:
        # Finite approved framing variants, Unicode code points on both client/server.
        greetings = [f'Hi {first},', f'Hello {first},', f'Dear {first},']
        applications = [
            f'I applied for {role} at {company}.',
            f'I have applied for {role} at {company}.',
            f'I recently applied for {role} at {company}.',
            f'My application is for {role} at {company}.',
        ]
        endings = closings + [
            'I would welcome the opportunity to connect and learn more about your team.',
            'I would appreciate the chance to connect.',
            'I would be glad to connect.',
            'I’d appreciate connecting.',
            'Would you be open to connecting?',
            'Thank you. May we connect?',
            'I hope we can connect.',
            'I would value the opportunity to connect.',
            'Thanks for considering a connection.',
        ]
        endings += [
            ending + thanks
            for ending in list(endings)
            for thanks in [
                ' Thank you!',
                ' Thank you for your time.',
                ' I would appreciate your perspective.',
                ' Thank you for considering my request.',
            ]
        ]
        from itertools import combinations

        for count in range(1, min(3, len(facts)) + 1):
            for group in combinations(facts, count):
                body = ' '.join(f['text'] for f in group)
                for greeting in greetings:
                    for application in applications:
                        for ending in endings:
                            candidate = f'{prefix}{greeting} {application} {body} {ending}'
                            if (
                                len(candidate) == 200
                                and candidate == candidate.strip()
                                and '  ' not in candidate
                            ):
                                return (
                                    candidate,
                                    [f['id'] for f in group],
                                    'Exactly 200 Unicode code points; whole approved facts and approved framing.',
                                )
        raise Unavailable(
            'Cannot form exactly 200 characters from these whole approved facts. Approve a concise relevant fact or disable exact-length generation in Settings. Previous draft retained.'
        )
    # Prefer the model-selected accomplishment; never shorten or paraphrase a fact.
    for fact in facts:
        for closing in closings:
            note = f"{opening} {fact['text']} {closing}"
            if len(note) <= limit:
                return (
                    note,
                    [fact['id']],
                    'Includes one whole approved fact selected for relevance.',
                )
    for closing in closings:
        note = f'{opening} {closing}'
        if len(note) <= limit:
            return (
                note,
                [],
                'Approved experience does not fit in full; it is retained in the direct message.',
            )
    # Long job titles stay complete in the DM, rather than being clipped in the note.
    for closing in closings:
        note = f'Hi {first}, I applied to {company}. {closing}'
        if len(note) <= limit:
            return (
                note,
                [],
                'The full role and approved experience are retained in the direct message.',
            )
    raise Unavailable(
        'The recipient name and company cannot fit your note limit. Increase the limit or review the application company name.'
    )

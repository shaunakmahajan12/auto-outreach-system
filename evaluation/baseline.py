"""Frozen pre-upgrade adapter: role + first 12 facts, no job description.

Whole-fact rendering preserves the inspected implementation, without duplicating
application storage, providers, scheduling or UI. No exact-length requirement.
"""

from backend.research import DraftPlan
from backend.note_renderer import render_note

INSTRUCTION = (
    'Select up to three relevant approved fact IDs, strongest concrete accomplishment first, and a connection/DM framing. '
    'Facts not in the provided list are prohibited. Prefer facts relevant to the role. '
    'Choose note_fact_ids as up to three relevant approved facts whose full text together fits note_fact_budget characters; '
    'put a concrete achievement first and add a supporting detail when it fits. Select the most relevant fact for the DM even when no whole fact fits the note budget. '
    'note_fact_id is a backwards-compatible single choice and may be null. '
    'Do not assume the recipient recruits or owns the opening.'
)


async def select(model, case):
    facts = [f for f in case['facts'] if f['status'] == 'approved'][:12]
    opening = f"Hi Avery, I applied for {case['role']} at {case['company']}."
    from backend.observability import prompt_version_context

    version_token = prompt_version_context.set('role-baseline-v0')
    try:
        plan = await model.structured(
            DraftPlan,
            INSTRUCTION,
            {
                'role': case['role'][:200],
                'company': case['company'][:120],
                'contact_title': None,
                'facts': [{k: f[k] for k in ('id', 'text')} for f in facts],
                'note_fact_budget': max(
                    0, 200 - len(opening) - len(' I’d be glad to connect.') - 1
                ),
            },
        )
    finally:
        prompt_version_context.reset(version_token)
    allowed = {f['id'] for f in facts}
    if any(
        fid not in allowed
        for fid in plan.fact_ids
        + plan.note_fact_ids
        + ([plan.note_fact_id] if plan.note_fact_id else [])
    ):
        raise ValueError('Invalid baseline fact ID')
    return plan.fact_ids


def render(case, selected):
    facts = [f for f in case['facts'] if f['id'] in selected and f['status'] == 'approved']
    note, _, _ = render_note('Avery', case['role'], case['company'], facts, 200, exact=False)
    dm = (
        f"Hi Avery, I applied for {case['role']} at {case['company']}.\n\n"
        + ' '.join(f['text'] for f in facts)
        + '\n\nWould you be open to sharing a little about the team? Thank you!'
    )
    return {'note': note, 'dm': dm}

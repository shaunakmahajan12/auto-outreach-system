from datetime import datetime, timedelta, timezone
from backend.store import now
from backend.security import public_url

SENT={'invitation_sent','dm_sent','followup_sent'}
TERMINAL={'reply','rejection','closed'}
ALLOWED=SENT|TERMINAL|{'connection_accepted'}


def instant(value):
    # Order by actual time; stored strings may carry different UTC offsets.
    parsed=datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def state_for(events,connection_status='unknown',at=None,outcome='unknown'):
    events=sorted([e for e in events if not e.get('undone_at')],key=lambda e:(instant(e['created_at']),e.get('id',0)))
    kinds=[e['kind'] for e in events]
    if 'connection_accepted' in kinds:connection_status='connected'
    terminal=next((e['kind'] for e in reversed(events) if e['kind'] in TERMINAL),None)
    if outcome in ('rejected','job_closed'):terminal=outcome
    last=next((e for e in reversed(events) if e['kind'] in {'dm_sent','followup_sent'}),None)
    due=None
    if last and not terminal:
        due=(instant(last['created_at']).astimezone(timezone.utc)+timedelta(days=7)).isoformat()
    return {'connection_status':connection_status,'next_action':('No follow-up suggested' if terminal else 'Follow up on your message' if due and datetime.fromisoformat(due)<=(at or datetime.now(timezone.utc)) else 'Wait for a reply' if last else 'Write a message' if connection_status=='connected' else 'Wait for acceptance' if 'invitation_sent' in kinds else 'Review the draft and send a connection request'),
            'closed_reason':terminal,'invitation_pending':'invitation_sent' in kinds and connection_status!='connected' and not terminal,
            'dm_sent':any(k in ('dm_sent','followup_sent') for k in kinds),'followup_due_at':due,
            'followup_due':bool(due and datetime.fromisoformat(due)<=(at or datetime.now(timezone.utc)))}


def record_event(store,cid,kind,note,request_id,created_at=None):
    if kind not in ALLOWED:raise ValueError('Unknown outreach event. Copy/open is not sending.')
    with store.db() as db:
        if db.execute('SELECT 1 FROM outreach_events WHERE request_id=?',(request_id,)).fetchone():return
        contact=db.execute('SELECT * FROM contacts WHERE id=?',(cid,)).fetchone()
        if not contact:raise ValueError('Contact not found')
        events=[dict(r) for r in db.execute('SELECT * FROM outreach_events WHERE contact_id=? ORDER BY id',(cid,))]
        app=db.execute('SELECT source_status,hiring_outcome FROM applications WHERE source_application_id=?',(contact['application_id'],)).fetchone()
        state=state_for(events,contact['connection_status'],outcome=app['hiring_outcome'])
        if kind in SENT:
            if app['source_status']!='COMPLETED':raise ValueError('Submission is no longer confirmed')
            if state['closed_reason']:raise ValueError('This conversation is closed or has a reply; no automated follow-up state may resume.')
            if kind=='invitation_sent' and (state['invitation_pending'] or state['connection_status']=='connected'):
                raise ValueError('Invitation already pending or connection already accepted')
            if kind=='dm_sent' and state['dm_sent']:raise ValueError('A DM is already recorded; use Mark follow-up sent for a later message.')
            if kind=='followup_sent' and not state['dm_sent']:raise ValueError('Record an actual sent DM before a follow-up')
        stamp=created_at or now()
        parsed=datetime.fromisoformat(stamp)
        if parsed.tzinfo is None or parsed>datetime.now(timezone.utc):raise ValueError('Use a timestamp with a timezone that is not in the future.')
        stamp=parsed.astimezone(timezone.utc).isoformat()
        if kind=='connection_accepted' and state['connection_status']=='connected':raise ValueError('Connection is already accepted')
        db.execute('INSERT INTO outreach_events(contact_id,kind,created_at,note,request_id) VALUES(?,?,?,?,?)',(cid,kind,stamp,note,request_id))


def prepare(store,cid,kind):
    rows=store.rows('''SELECT c.linkedin_url,a.source_status,d.note,d.dm FROM contacts c JOIN applications a
        ON a.source_application_id=c.application_id JOIN drafts d ON d.contact_id=c.id WHERE c.id=?''',(cid,))
    if not rows:raise ValueError('Draft not found')
    row=rows[0]
    contact=store.rows('SELECT c.dismissed,a.hiring_outcome FROM contacts c JOIN applications a ON a.source_application_id=c.application_id WHERE c.id=?',(cid,))[0]
    if contact['dismissed'] or contact['hiring_outcome'] in ('rejected','job_closed'):raise ValueError('Contact dismissed or application closed; review before outreach.')
    if row['source_status']!='COMPLETED':raise ValueError('Submission is not currently confirmed')
    if kind not in ('note','dm'):raise ValueError('Unknown draft kind')
    value=row[kind]
    limit=store.settings()['note_limit' if kind=='note' else 'dm_limit']
    if len(value)>limit:raise ValueError('Draft exceeds your configured character limit; edit and save first')
    # Pure read: copying/opening must never create an outreach event.
    return {'url':public_url(row['linkedin_url'],True),'text':value}

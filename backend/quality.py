"""Readiness and manually observed outcomes; never infer a send or review."""
def summary(applications, contacts, note_limit):
    active=[c for c in contacts if not c['dismissed']]
    sent={c['id'] for c in contacts if any(e['kind'] in ('invitation_sent','dm_sent','followup_sent') and not e['undone_at'] for e in c['events'])}
    replied={c['id'] for c in contacts if any(e['kind']=='reply' and not e['undone_at'] for e in c['events'])}
    accepted={c['id'] for c in contacts if any(e['kind']=='connection_accepted' and not e['undone_at'] for e in c['events'])}
    invitations={c['id'] for c in contacts if any(e['kind']=='invitation_sent' and not e['undone_at'] for e in c['events'])}
    return {'recommended_contacts':sum(c['relevance_assessment']['level'] in ('high','medium') for c in active),
        'needs_evidence':sum(c['review_status']!='supported' for c in active),
        'needs_review':sum(c['review_status']!='supported' for c in active),
        'notes_over_limit':sum(len(c['note'] or '')>note_limit for c in active),
        'missing_roles':sum(a['source_status']=='COMPLETED' and not a['role'] for a in applications),
        'followups_due':sum(bool(c['conversation'].get('followup_due')) for c in active),
        'contacted':len(sent),'replied':len(sent & replied),'accepted':len(invitations & accepted),
        'reply_rate':round(100*len(sent & replied)/len(sent),1) if sent else None,
        'acceptance_rate':round(100*len(invitations & accepted)/len(invitations),1) if invitations else None}

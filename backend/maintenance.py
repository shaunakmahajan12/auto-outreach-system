"""Conservative repair of recognizable generated notes, with a recoverable backup."""
import json
import os
import sqlite3
from backend.note_renderer import render_note
from backend.security import Unavailable
from backend.store import now


def repair_notes(store):
    settings=store.settings()
    facts={f['id']:f for f in settings['facts']}
    planned=[]
    with store.db() as db:
        rows=db.execute('''SELECT d.*,c.name,c.original_fields,c.dismissed,a.role,a.company
            FROM drafts d JOIN contacts c ON c.id=d.contact_id
            JOIN applications a ON a.source_application_id=c.application_id
            WHERE NOT EXISTS(SELECT 1 FROM outreach_events e WHERE e.contact_id=c.id)''').fetchall()
    for row in rows:
        if row['original_fields'] or row['dismissed'] or len(row['note'])<=settings['note_limit']:
            continue
        grounding=json.loads(row['grounding'])
        if grounding.get('note_edited'):continue
        ids=grounding.get('note_fact_ids',[])
        selected=[facts[fid] for fid in ids if fid in facts]
        if not selected:continue
        seed=f"Hi {row['name'].split()[0]}, I applied for {row['role']} at {row['company']}. {selected[0]['text']} I’d value the chance to connect and learn more about the team."
        original=grounding.get('generated_note')
        recognizable=(original==row['note']) or (grounding.get('fallback_used') is True and seed==row['note'])
        if not recognizable:continue
        try:note,chosen,explanation=render_note(row['name'],row['role'],row['company'],selected,settings['note_limit'])
        except Unavailable:continue
        grounding.update(generated_note=note,note_fact_ids=chosen,note_explanation=explanation,
            method='Standard framing with whole model-selected approved facts',fallback_used=False,
            validation_issues=[],previous_generated_note=row['note'])
        planned.append((note,json.dumps(grounding),row['contact_id'],row['note'],row['grounding']))
    if planned:
        backup=store.path.with_name(store.path.stem+'-before-note-repair-'+now().replace(':','-')+'.sqlite')
        with sqlite3.connect(store.path) as source,sqlite3.connect(backup) as target:source.backup(target)
        os.chmod(backup,0o600)
        with store.db() as db:
            changed=0
            for note,grounding,cid,old,old_grounding in planned:
                changed+=db.execute('''UPDATE drafts SET note=?,grounding=?,updated_at=?
                    WHERE contact_id=? AND note=? AND grounding=?
                    AND NOT EXISTS(SELECT 1 FROM outreach_events WHERE contact_id=?)''',
                    (note,grounding,now(),cid,old,old_grounding,cid)).rowcount
        return {'repaired':changed,'backup_created':True}
    return {'repaired':0,'backup_created':False}

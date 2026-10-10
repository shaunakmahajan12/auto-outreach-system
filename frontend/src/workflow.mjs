export const eventLabels = {invitation_sent:'Connection request sent',connection_accepted:'Connection accepted',dm_sent:'Message sent',followup_sent:'Follow-up message sent',reply:'Reply received',rejection:'Rejection received',closed:'Conversation closed'};
export const stages = {queued:'Waiting to start',checking_configuration:'Checking your tools',researching_contacts:'Researching contacts',checking_sources:'Checking source records',ranking_candidates:'Ranking candidates',drafting_messages:'Drafting messages',retry:'Waiting to retry',interrupted:'Preparation interrupted',blocked:'Preparation needs attention',failed:'Preparation failed',done:'Preparation complete'};
export function submissionGroup(a) {
  if(a.source_status==='COMPLETED')return 'completed';
  if(a.source_status==='SKIPPED')return 'skipped';
  if(a.source_status==='FAILED')return 'failed';
  if(['processing','needs_action'].includes(a.normalized_status))return 'pending';
  return 'unknown';
}
export function compareApplications(a,b,sort='submitted-desc') {
 const key=sort.startsWith('source')?'source_created_at':sort.startsWith('submitted')?'submitted_at':'first_seen';
 const ad=queueDate(a[key]),bd=queueDate(b[key]);
 if(ad===null&&bd===null)return `${a.company||''}\u0000${a.role||''}\u0000${a.source_application_id}`.localeCompare(`${b.company||''}\u0000${b.role||''}\u0000${b.source_application_id}`);
 if(ad===null&&bd!==null)return 1;
 if(ad!==null&&bd===null)return -1;
 const difference=ad!==null&&bd!==null?(ad-bd)*(sort.endsWith('asc')?1:-1):0;
 return difference||String(a.source_application_id).localeCompare(String(b.source_application_id));
}
export function filterApplications(rows,f) {
 return rows.filter(a=>(!f.query||`${a.company||''} ${a.role||''}`.toLowerCase().includes(f.query.toLowerCase()))
   &&(f.submission==='all'||submissionGroup(a)===f.submission)).sort((a,b)=>compareApplications(a,b,f.sort));
}
export function relevanceLabel(contact) {
 return {high:'High relevance',medium:'Medium relevance',low:'Low relevance'}[contact.relevance_assessment?.level]||'Not assessed';
}
export function compareContactRelevance(a,b) {
 const levels={high:0,medium:1,low:2};
 const level=(levels[a.relevance_assessment?.level]??3)-(levels[b.relevance_assessment?.level]??3);
 if(level)return level;
 const score=c=>Number.isFinite(c.relevance_assessment?.score)?c.relevance_assessment.score:Number.isFinite(c.relevance_score)?c.relevance_score:null;
 const as=score(a),bs=score(b);
 if(as!==null&&bs===null)return -1;
 if(as===null&&bs!==null)return 1;
 if(as!==null&&bs!==null&&as!==bs)return bs-as;
 return String(a.name||'').localeCompare(String(b.name||''),'en',{sensitivity:'base'})||String(a.id).localeCompare(String(b.id),'en',{numeric:true});
}
export const activeJob = a => ['queued','running','retry'].includes(a?.job?.state);
export function completedWhileViewing(previous, next, viewedId) {
  return next.filter(a=>previous[a.source_application_id] && ['queued','running','retry'].includes(previous[a.source_application_id]) && a.job?.state==='done')
    .map(a=>({id:a.source_application_id,open:a.source_application_id===viewedId,ready:a.research_state==='ready'}));
}

// Source placeholders are absence of data, never display values.
export function displayValue(value) {
  if(value == null)return '';
  const text=String(value).trim();
  return /^(unknown(?: company| role| title)?|unavailable|n\/a|not (?:provided|supplied|recorded|established)|(?:company|role|title) not (?:provided|supplied|established))$/i.test(text)?'':text;
}

export const initialFilters={query:'',submission:'completed',sort:'source-desc'};
export const statusLabels={dismissed:'Dismissed',all:'All',completed:'Submitted',skipped:'Skipped',failed:'Failed',pending:'In progress',unknown:'Not recorded',rejected:'Rejected',job_closed:'Job closed',interviewing:'Interviewing',offer:'Offer',ready:'Drafts ready',historical_no_outreach:'Not started',not_started:'Not started',awaiting_submission:'Awaiting submission',no_contacts:'No candidates',queued:'Queued',running:'Preparing',retry:'Retry scheduled',blocked:'Needs attention',interrupted:'Interrupted',history:'Imported history',new:'New or selected', 'observed-desc':'Recently added','observed-asc':'Oldest added','submitted-desc':'Recently submitted','submitted-asc':'Oldest submitted'};
export const statusLabel=v=>({'source-desc':'Tsenta order (newest first)','source-asc':'Tsenta order (oldest first)'})[v]||statusLabels[v]||displayValue(v).replaceAll('_',' ');
export const findApplication=(rows,id)=>rows.find(a=>a.source_application_id===id);
export const activeEvents=c=>(c.events||[]).filter(e=>!e.undone_at).sort((a,b)=>Date.parse(a.created_at)-Date.parse(b.created_at)||a.id-b.id);
export const inTracker=c=>activeEvents(c).some(e=>['invitation_sent','connection_accepted','dm_sent','followup_sent','reply'].includes(e.kind));
export function trackerStatus(c){
 const events=activeEvents(c), kinds=events.map(e=>e.kind), closed=['rejected','job_closed'].includes(c.hiring_outcome)||kinds.some(k=>['rejection','closed'].includes(k));
 const replied=kinds.includes('reply');
 return {invitation:c.conversation.connection_status==='connected'?'Connected':c.conversation.invitation_pending?'Invitation pending':'',message:closed?'Closed':replied?'Replied':c.conversation.dm_sent?'Awaiting reply':'',group:closed?'closed':replied?'replied':c.conversation.followup_due?'followup':c.conversation.dm_sent?'awaiting':c.conversation.invitation_pending?'pending':'connected',last:events.at(-1)};
}
export function filterTracker(contacts,filter,query='') {return contacts.filter(inTracker).filter(c=>(filter==='all'||trackerStatus(c).group===filter)&&`${c.name} ${c.application_company} ${c.role}`.toLowerCase().includes(query.toLowerCase())).sort((a,b)=>Date.parse(trackerStatus(b).last.created_at)-Date.parse(trackerStatus(a).last.created_at));}
export function allowedEvents(c){
 const s=c.conversation, closed=!!s.closed_reason||['rejected','job_closed'].includes(c.hiring_outcome), sent=!closed&&!c.dismissed&&c.source_status==='COMPLETED';
 return ['invitation_sent','connection_accepted','dm_sent','reply','followup_sent','rejection','closed'].filter(k=>{
  if(k==='invitation_sent')return sent&&!s.invitation_pending&&s.connection_status!=='connected';
  if(k==='connection_accepted')return s.connection_status!=='connected'&&!closed;
  if(k==='dm_sent')return sent&&!s.dm_sent;
  if(k==='followup_sent')return sent&&s.dm_sent;
  return !closed&&inTracker(c);
 });
}
export const safeLink=value=>{try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password?u.href:null}catch{return null}};

export function groupQueueContacts(contacts) {
  const groups=new Map();
  for(const contact of contacts) {
    const id=contact.application_id;
    if(!groups.has(id))groups.set(id,{application_id:id,company:contact.application_company,role:contact.role,submitted_at:contact.application_submitted_at,contacts:[]});
    groups.get(id).contacts.push(contact);
  }
  return [...groups.values()].sort((a,b)=>{
    if(a.submitted_at&&!b.submitted_at)return -1;
    if(!a.submitted_at&&b.submitted_at)return 1;
    if(a.submitted_at&&b.submitted_at){const difference=Date.parse(b.submitted_at)-Date.parse(a.submitted_at);if(difference)return difference;}
    return `${a.company||''}\u0000${a.role||''}\u0000${a.application_id}`.localeCompare(`${b.company||''}\u0000${b.role||''}\u0000${b.application_id}`);
  });
}

function queueDate(value) {
  if(!value)return null;
  const parsed=Date.parse(value);
  return Number.isNaN(parsed)?null:parsed;
}

export function groupQueueCompanies(contacts,applications=[],sort='submitted-desc') {
 const records=new Map(applications.map(a=>[a.source_application_id,a]));
 const groups=new Map();
 for(const contact of contacts){
  const id=contact.application_id;
  if(!groups.has(id)){
   const app=records.get(id)||{source_application_id:id,company:contact.application_company,role:contact.role,submitted_at:contact.application_submitted_at};
   groups.set(id,{...app,application_id:id,contacts:[]});
  }
  groups.get(id).contacts.push(contact);
 }
 const companies=new Map();
 for(const app of [...groups.values()].sort((a,b)=>compareApplications(a,b,sort))){
  app.contacts.sort(compareContactRelevance);
  const company=String(app.company||'').trim(),key=company?`company:${company.toLocaleLowerCase()}`:'company:not-supplied';
  if(!companies.has(key))companies.set(key,{key,company,applications:[],contact_count:0});
  const group=companies.get(key);group.applications.push(app);group.contact_count+=app.contacts.length;
 }
 return [...companies.values()];
}

export function preparationGroups(applications) {
  const byState=state=>applications.filter(a=>a.job?.state===state);
  return {
    queued:byState('queued'),
    running:applications.filter(a=>['running','retry'].includes(a.job?.state)),
    failed:applications.filter(a=>['failed','blocked','interrupted'].includes(a.job?.state)),
    completed:byState('done').sort((a,b)=>Date.parse(b.job?.updated_at||0)-Date.parse(a.job?.updated_at||0)||String(a.source_application_id).localeCompare(String(b.source_application_id)))
  };
}

export function filterQueue(contacts, {query='',showDismissed=false,relevance='recommended'}={}) {
 return contacts.filter(c=>!inTracker(c)&&(showDismissed||!c.dismissed)
   && (relevance==='all'||(relevance==='recommended'?['high','medium'].includes(c.relevance_assessment?.level):c.review_status!=='supported'))
   && `${c.name||''} ${c.application_company||''} ${c.role||''}`.toLowerCase().includes(query.toLowerCase()));
}

Object.assign(stages,{missing_description:'Using role-based fallback',no_contacts_review:'No supported contacts found',requirements_extraction:'Reading job requirements',experience_retrieval:'Finding approved experience',contact_research:'Researching contacts',evidence_assessment:'Reviewing contact evidence',drafting:'Preparing drafts',validation:'Checking evidence',review:'Waiting for your review',persistence:'Saving suggestions',awaiting_review:'Needs your input',insufficient_evidence:'Needs approved evidence'});

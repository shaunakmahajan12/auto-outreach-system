import {MatchPanel,type Matching} from './Personalization';
import React,{useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {api} from './api';
import {copyMessage,openProfile} from './actions.mjs';
import {displayValue} from './workflow.mjs';

export function Dialog({title,children,onClose,wide=false,drawer=false}:{title:string;children:React.ReactNode;onClose:()=>void;wide?:boolean;drawer?:boolean}){
 const ref=useRef<HTMLDialogElement>(null),close=useRef(onClose);close.current=onClose;
 const titleId=React.useId();
 useEffect(()=>{const el=ref.current!,previous=document.activeElement as HTMLElement;el.showModal();return()=>{el.close();if(previous?.isConnected)previous.focus()};},[]);
 return createPortal(<dialog ref={ref} className={'dialog '+(wide?'wide':'')+(drawer?' drawer':'')} aria-labelledby={titleId} onCancel={e=>{e.preventDefault();close.current()}}><div className="dialog-head"><h2 id={titleId}>{title}</h2><button className="icon-button" aria-label="Close dialog" onClick={onClose}>✕</button></div>{children}</dialog>,document.body);
}
interface Draft {note:string;dm:string}
interface Suggestion extends Draft {suggestion_id:string;grounding:{note_explanation?:string;omitted_explanation?:string|null;matching?:Matching}}
interface DraftContact {id:number;application_id:string;name:string;note:string;dm:string;dismissed:boolean;hiring_outcome:string;source_status:string;conversation:{closed_reason:string|null};application_company:string;role:string;linkedin_url:string;grounding?:{facts?:string[];note_explanation?:string;message_grounding?:Partial<Record<'note'|'dm',{facts?:string[];note_explanation?:string}>>}}
interface CopyResult {copied?:boolean;opened?:boolean;copyError?:string;openError?:string}
export function DraftDialog({c,config,demo,onClose,onSaved}:{c:DraftContact;config:{note_limit:number;dm_limit:number}|null;demo:boolean;onClose:()=>void;onSaved:()=>Promise<void>}){
 const storageKey=`outreach-working-${demo?'demo':'live'}-${c.application_id}-${c.id}`;
 // Working edits remember the saved draft they started from; a newer saved draft wins over them.
 const [stored]=useState<(Draft&{base?:Draft})|null>(()=>{try{return JSON.parse(sessionStorage.getItem(storageKey)||'null')}catch{return null}});
 const staleEdits=!!stored?.base&&(stored.base.note!==(c.note||'')||stored.base.dm!==(c.dm||''));
 const initial=()=>stored&&!staleEdits?{note:stored.note,dm:stored.dm}:{note:c.note||'',dm:c.dm||''};
 const [draft,setDraft]=useState<Draft>(initial),[tab,setTab]=useState<'note'|'dm'>('note'),[busy,setBusy]=useState(''),[message,setMessage]=useState(staleEdits?'The saved draft changed after your unsaved edits in this tab, so the saved version is shown.':''),[error,setError]=useState(''),[suggestion,setSuggestion]=useState<Suggestion|null>(null),[fallback,setFallback]=useState<CopyResult|null>(null),[generationFailed,setGenerationFailed]=useState(false);
 const [acceptedSuggestion,setAcceptedSuggestion]=useState<{id:string;parts:('note'|'dm')[]}|null>(()=>{try{return staleEdits?null:JSON.parse(sessionStorage.getItem(storageKey+'-acceptance')||'null')}catch{return null}});
 useEffect(()=>{if(staleEdits)try{sessionStorage.removeItem(storageKey)}catch{}},[]);
 const [baseline,setBaseline]=useState({note:c.note||'',dm:c.dm||''});
 useEffect(()=>{try{if(acceptedSuggestion)sessionStorage.setItem(storageKey+'-acceptance',JSON.stringify(acceptedSuggestion));else sessionStorage.removeItem(storageKey+'-acceptance')}catch{setError('Save before closing; browser storage is unavailable.')}},[acceptedSuggestion,storageKey]);
 const dirty=draft.note!==baseline.note||draft.dm!==baseline.dm;
 const noteLimit=config?.note_limit||200,limit=tab==='note'?noteLimit:(config?.dm_limit||1200);
 const dmOver=Array.from(draft.dm).length>(config?.dm_limit||1200);
 const noteOver=Array.from(draft.note).length>noteLimit;
 // Both limits are hard. An unchanged legacy note over the limit does not block saving the DM.
 const noteBlocked=noteOver&&draft.note!==baseline.note;
 const over=dmOver||noteBlocked;
 const copyInvalid=tab==='note'?noteOver:dmOver;
 const blocked=demo||c.dismissed||['rejected','job_closed'].includes(c.hiring_outcome)||c.source_status!=='COMPLETED'||!!c.conversation.closed_reason;
 function keep(next:Draft){sessionStorage.setItem(storageKey,JSON.stringify({...next,base:baseline}))}
 function update(next:Draft){setDraft(next);try{keep(next)}catch{setError('This browser cannot retain working edits. Save before closing.')}}
 async function persist(){if(over)throw new Error(noteBlocked?`Shorten the connection note to ${noteLimit} characters before saving.`:'Message exceeds the character limit.');await api(`/contacts/${c.id}/drafts`,'PUT',{...draft,suggestion_id:acceptedSuggestion?.id,suggestion_parts:acceptedSuggestion?.parts});setBaseline({...draft});setAcceptedSuggestion(null);sessionStorage.removeItem(storageKey);}
 async function save(){setBusy('save');setError('');try{await persist();setMessage('Drafts saved.');await onSaved()}catch(e){setError((e as Error).message);if((e as {status?:number}).status===400)setAcceptedSuggestion(null)}finally{setBusy('')}}
 async function suggest(){setBusy('suggest');setError('');setGenerationFailed(false);try{setSuggestion(await api(`/contacts/${c.id}/draft-suggestion`,'POST'));setMessage('Suggestion ready. Your current drafts are unchanged.')}catch(e){setGenerationFailed(true);setError((e as Error).message)}finally{setBusy('')}}
 function useSuggestion(parts:('note'|'dm')[]){if(!suggestion)return;if(parts.some(k=>draft[k]!==baseline[k])&&!window.confirm('Replace the working message with this suggestion? Saved drafts stay unchanged until you save.'))return;setAcceptedSuggestion(previous=>({id:suggestion.suggestion_id,parts:[...new Set([...(previous?.id===suggestion.suggestion_id?previous.parts:[]),...parts])]}));update({...draft,...Object.fromEntries(parts.map(k=>[k,suggestion[k]]))});setTab(parts[0]);setMessage('Suggestion applied. Save to keep it.');}
 function close(){if(busy==='save')return;if(dirty){try{keep(draft)}catch{setError('Save your edits before closing; browser storage is unavailable.');return;}}onClose();}
 function feedback(result:CopyResult){
  const parts=[result.copied?'Message copied.':result.copyError||'Message was not copied.',result.opened?'Profile opened in a new tab.':result.openError||'Profile was not opened.'];
  setMessage(parts.join(' '));setFallback(result);
 }
 async function copy(){
  if(blocked||copyInvalid||over)return;
  // Open synchronously under the user's gesture; persist the exact displayed text before copying.
  const opened=openProfile(c.linkedin_url,window);setBusy('copy');setError('');
  try{if(dirty)await persist();feedback({...opened,...await copyMessage(draft[tab],navigator.clipboard)});await onSaved()}
  catch(e){feedback({...opened,copied:false,copyError:'Draft was not copied because saving failed.'});setError((e as Error).message)}finally{setBusy('')}
 }
 async function copyOnly(){
  if(blocked||copyInvalid||over)return;
  setBusy('copy-only');setError('');try{if(dirty)await persist();feedback({...fallback,...await copyMessage(draft[tab],navigator.clipboard)});await onSaved()}catch(e){setError((e as Error).message)}finally{setBusy('')}
 }
 function openOnly(){const result=openProfile(c.linkedin_url,window);feedback({...fallback,...result,copied:fallback?.copied||false})}
 function tabKey(e:React.KeyboardEvent){if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const tabs=['note','dm'] as const;const next=e.key==='Home'?'note':e.key==='End'?'dm':tabs[(tabs.indexOf(tab)+1)%2];setTab(next);document.getElementById('draft-tab-'+next)?.focus();}}
 return <Dialog title={`Drafts for ${c.name}`} onClose={close} wide><div className="dialog-body"><p className="context-line"><strong>{displayValue(c.application_company)}</strong>{displayValue(c.role)&&<> · {c.role}</>}</p><p className="muted">Review your message, then send it yourself on LinkedIn.</p>
 {error&&<div className="notice error" role="alert">{error}{generationFailed&&<button className="text-button" disabled={!!busy} onClick={suggest}>Retry generation</button>}</div>}{message&&<div className="notice success" role="status">{message}</div>}
 <div className="draft-layout"><section className="draft-main"><div className="draft-tabs" role="tablist" aria-label="Message type" onKeyDown={tabKey}>{[['note','Connection note'],['dm','Direct message']].map(([value,label])=><button id={'draft-tab-'+value} key={value} role="tab" aria-selected={tab===value} aria-controls="draft-panel" tabIndex={tab===value?0:-1} onClick={()=>setTab(value as 'note'|'dm')}>{label}</button>)}</div>
 <div id="draft-panel" role="tabpanel" aria-labelledby={'draft-tab-'+tab}><label className="sr-only" htmlFor="draft-text">{tab==='note'?'Connection note':'Direct message'}</label><textarea id="draft-text" className="draft-editor" disabled={!!busy} value={draft[tab]} onChange={e=>update({...draft,[tab]:e.target.value})} rows={9}/><div className="editor-meta"><span>{dirty?'Working edits retained in this browser tab':'Saved draft'}</span><span className={(tab==='note'?noteOver:copyInvalid)?'danger':''} aria-live="polite">{Array.from(draft[tab]).length} / {limit} characters</span></div></div>
 {tab==='note'&&noteOver&&<p className="hint danger" role="status">Over your {noteLimit}-character limit. Shorten this note to save or copy it.</p>}
 {dirty&&<p className="hint">Closing this dialog keeps your working edits. The copy action uses the text currently displayed.</p>}
 <div className="button-row"><button className="button primary" disabled={(!dirty&&!acceptedSuggestion)||over||!!busy} onClick={save}>{busy==='save'?'Saving…':'Save changes'}</button><button className="button" disabled={over||copyInvalid||!!busy||blocked||!draft[tab].trim()} onClick={copy}>{busy==='copy'?'Working…':'Open LinkedIn & copy message'}</button></div>
 {demo&&<p className="hint">Fictional workspace: external profiles are disabled.</p>}{blocked&&!demo&&<p className="hint">Copy/open is unavailable for a dismissed contact, a closed conversation, or an unconfirmed submission.</p>}
 {fallback&&(!fallback.opened||!fallback.copied)&&<div className="notice warning" role="status"><div><strong>One or more actions need attention.</strong>{fallback.copyError&&<p>{fallback.copyError}</p>}{fallback.openError&&<p>{fallback.openError}</p>}<div className="button-row">{!fallback.copied&&<button className="button small" disabled={!!busy||blocked||copyInvalid||over} onClick={copyOnly}>Copy message</button>}{!fallback.opened&&<button className="button small" onClick={openOnly}>Open profile</button>}</div></div></div>}
 </section><aside className="draft-suggestions"><h3>Suggested messages</h3><p className="hint">Review approved experience before applying a suggestion.</p><button className="button" disabled={!!busy} onClick={suggest}>{busy==='suggest'?'Preparing locally…':'Generate suggestion'}</button>{suggestion&&<div className="suggestion"><h4>Connection note</h4><p className="suggested-text">{suggestion.note}</p><h4>Direct message</h4><p className="suggested-text">{suggestion.dm}</p><small>{suggestion.grounding?.note_explanation}</small>{suggestion.grounding?.omitted_explanation&&<p className="hint" role="status">{suggestion.grounding.omitted_explanation}</p>}{suggestion.grounding?.matching&&<details><summary>Selected experience & evidence</summary><MatchPanel matching={suggestion.grounding.matching}/></details>}<div className="button-row"><button className="button small" onClick={()=>useSuggestion(['note'])}>Apply note</button><button className="button small" onClick={()=>useSuggestion(['dm'])}>Apply DM</button><button className="button small" onClick={()=>useSuggestion(['note','dm'])}>Apply both</button><button className="text-button" onClick={()=>{api(`/draft-suggestions/${suggestion.suggestion_id}/reject`,'POST',{parts:acceptedSuggestion?.id===suggestion.suggestion_id?(['note','dm'] as const).filter(k=>!acceptedSuggestion.parts.includes(k)):['note','dm']}).catch((e:Error)=>setError(e.message));setSuggestion(null)}}>Dismiss</button></div></div>}</aside></div>
 <details><summary>Approved experience used</summary>{(c.grounding?.message_grounding?.[tab]?.facts||c.grounding?.facts||[]).map((f:string,i:number)=><p key={i}>{f}</p>)}{c.grounding?.note_explanation&&<p className="hint">{c.grounding.note_explanation}</p>}</details>
 </div></Dialog>;
}

import React,{useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {api} from './main';
import {copyMessage,openProfile} from './actions.mjs';
import {displayValue} from './workflow.mjs';

export function Dialog({title,children,onClose,wide=false}:{title:string;children:React.ReactNode;onClose:()=>void;wide?:boolean}){
 const ref=useRef<HTMLDialogElement>(null),close=useRef(onClose);close.current=onClose;
 const titleId=React.useId();
 useEffect(()=>{const el=ref.current!,previous=document.activeElement as HTMLElement;el.showModal();return()=>{el.close();if(previous?.isConnected)previous.focus()};},[]);
 return createPortal(<dialog ref={ref} className={'dialog '+(wide?'wide':'')} aria-labelledby={titleId} onCancel={e=>{e.preventDefault();close.current()}}><div className="dialog-head"><h2 id={titleId}>{title}</h2><button className="icon-button" aria-label="Close dialog" onClick={onClose}>✕</button></div>{children}</dialog>,document.body);
}
export function DraftDialog({c,config,demo,onClose,onSaved}:any){
 const storageKey=`outreach-working-${demo?'demo':'live'}-${c.application_id}-${c.id}`;
 const initial=()=>{try{return JSON.parse(sessionStorage.getItem(storageKey)||'null')||{note:c.note||'',dm:c.dm||''}}catch{return {note:c.note||'',dm:c.dm||''}}};
 const [draft,setDraft]=useState(initial),[tab,setTab]=useState<'note'|'dm'>('note'),[busy,setBusy]=useState(''),[message,setMessage]=useState(''),[error,setError]=useState(''),[suggestion,setSuggestion]=useState<any>(null),[fallback,setFallback]=useState<any>(null),[generationFailed,setGenerationFailed]=useState(false);
 const [baseline,setBaseline]=useState({note:c.note||'',dm:c.dm||''});
 const dirty=draft.note!==baseline.note||draft.dm!==baseline.dm;
 const noteLimit=config?.note_limit||200,limit=tab==='note'?noteLimit:(config?.dm_limit||1200);
 const over=Array.from(draft.dm).length>(config?.dm_limit||1200);
 const copyInvalid=tab==='dm'&&over;
 const noteOver=Array.from(draft.note).length>noteLimit;
 const blocked=demo||c.dismissed||['rejected','job_closed'].includes(c.hiring_outcome)||c.source_status!=='COMPLETED'||!!c.conversation.closed_reason;
 function update(next:any){setDraft(next);try{sessionStorage.setItem(storageKey,JSON.stringify(next))}catch{setError('This browser cannot retain working edits. Save before closing.')}}
 async function persist(){if(over)throw new Error('Message exceeds the character limit.');await api(`/contacts/${c.id}/drafts`,'PUT',draft);setBaseline({...draft});sessionStorage.removeItem(storageKey);}
 async function save(){setBusy('save');setError('');try{await persist();setMessage('Drafts saved.');await onSaved()}catch(e){setError((e as Error).message)}finally{setBusy('')}}
 async function suggest(){setBusy('suggest');setError('');setGenerationFailed(false);setSuggestion(null);try{setSuggestion(await api(`/contacts/${c.id}/draft-suggestion`,'POST'));setMessage('Suggestion ready. Your current drafts are unchanged.')}catch(e){setGenerationFailed(true);setError((e as Error).message)}finally{setBusy('')}}
 function useSuggestion(){if(dirty&&!window.confirm('Replace your working connection note with this suggestion? Your saved draft will remain unchanged until you save.'))return;update({...draft,note:suggestion.note});setSuggestion(null);setTab('note');setMessage('Suggestion added to the editor. Save to keep it.');}
 function close(){if(busy==='save')return;if(dirty){try{sessionStorage.setItem(storageKey,JSON.stringify(draft))}catch{setError('Save your edits before closing; browser storage is unavailable.');return;}}onClose();}
 function feedback(result:any){
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
 <div className="draft-tabs" role="tablist" aria-label="Message type" onKeyDown={tabKey}>{[['note','Connection note'],['dm','Direct message']].map(([value,label])=><button id={'draft-tab-'+value} key={value} role="tab" aria-selected={tab===value} aria-controls="draft-panel" tabIndex={tab===value?0:-1} onClick={()=>setTab(value as 'note'|'dm')}>{label}</button>)}</div>
 <div id="draft-panel" role="tabpanel" aria-labelledby={'draft-tab-'+tab}><label className="sr-only" htmlFor="draft-text">{tab==='note'?'Connection note':'Direct message'}</label><textarea id="draft-text" className="draft-editor" disabled={!!busy} value={draft[tab]} onChange={e=>update({...draft,[tab]:e.target.value})} rows={9}/><div className="editor-meta"><span>{dirty?'Working edits retained in this browser tab':'Saved draft'}</span><span className={(tab==='note'?noteOver:copyInvalid)?'danger':''} aria-live="polite">{Array.from(draft[tab]).length} / {limit} characters</span></div></div>
 {tab==='note'&&noteOver&&<p className="hint" role="status">Above your configured LinkedIn limit. You can still save or copy this note; LinkedIn may require shortening it.</p>}
 {dirty&&<p className="hint">Closing this dialog keeps your working edits. The copy action uses the text currently displayed.</p>}
 <div className="button-row"><button className="button primary" disabled={!dirty||over||!!busy} onClick={save}>{busy==='save'?'Saving…':'Save changes'}</button><button className="button" disabled={over||copyInvalid||!!busy||blocked||!draft[tab].trim()} onClick={copy}>{busy==='copy'?'Working…':'Open LinkedIn & copy message'}</button></div>
 {demo&&<p className="hint">Fictional workspace: external profiles are disabled.</p>}{blocked&&!demo&&<p className="hint">Copy/open is unavailable for a dismissed contact, a closed conversation, or an unconfirmed submission.</p>}
 {fallback&&(!fallback.opened||!fallback.copied)&&<div className="notice warning" role="status"><div><strong>One or more actions need attention.</strong>{fallback.copyError&&<p>{fallback.copyError}</p>}{fallback.openError&&<p>{fallback.openError}</p>}<div className="button-row">{!fallback.copied&&<button className="button small" disabled={!!busy||blocked||copyInvalid||over} onClick={copyOnly}>Copy message</button>}{!fallback.opened&&<button className="button small" onClick={openOnly}>Open profile</button>}</div></div></div>}
 <details className="secondary-details"><summary>Improve this note</summary><p>Generate a suggestion from approved experience. Review it before replacing your working note.</p><button className="button" disabled={!!busy} onClick={suggest}>{busy==='suggest'?'Preparing locally…':'Generate suggestion'}</button>{suggestion&&<div className="suggestion"><p>{suggestion.note}</p><small>{suggestion.grounding?.note_explanation}</small><div className="button-row"><button className="button" onClick={useSuggestion}>Use suggestion</button><button className="text-button" onClick={()=>setSuggestion(null)}>Dismiss</button></div></div>}</details>
 <details><summary>Approved experience used</summary>{(c.grounding?.facts||[]).map((f:string,i:number)=><p key={i}>{f}</p>)}{c.grounding?.note_explanation&&<p className="hint">{c.grounding.note_explanation}</p>}</details>
 </div></Dialog>;
}

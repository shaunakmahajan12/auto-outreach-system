import {test,expect} from '@playwright/test';
let token='';
async function api(page:any,path:string,body?:any,method='POST'){
 const response=await page.request.fetch('/api'+path,{method,headers:{'X-Outreach-Token':token},data:body});
 expect(response.ok()).toBeTruthy();return response.json();
}
test.beforeEach(async({page})=>{token=(await (await page.request.get('/api/bootstrap')).json()).token;await page.goto('/');});
test('description, approved evidence, draft edit, and outreach undo',async({page})=>{
 await page.getByRole('button',{name:'Experience',exact:true}).click();
 await page.getByRole('button',{name:'Add experience',exact:true}).first().click();
 await page.getByLabel('Factual text').fill('I built a fictional React project.');
 await page.getByLabel('Technologies (comma separated)').fill('React');
 await page.getByLabel('Source reference',{exact:true}).fill('fictional portfolio');
 await page.getByLabel('Approval status').selectOption('approved');
 await page.getByRole('button',{name:'Save experience',exact:true}).click();
 await expect(page.getByText('I built a fictional React project.',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Applications',exact:true}).click();
 await page.getByRole('button',{name:'Software Engineer (fictional)',exact:true}).first().click();
 await page.getByLabel('Job description',{exact:true}).fill('Required: React\nPreferred: accessibility audits');
 await page.getByLabel('Description source URL').fill('https://example.com/fictional-job');
 await page.getByRole('button',{name:'Save description',exact:true}).click();
 await page.getByRole('button',{name:'Review requirement matches',exact:true}).click();
 await page.getByText('Evidence & excerpt',{exact:true}).first().click();
 await expect(page.getByText('Explicit skill evidence: react',{exact:false})).toBeVisible();
 await expect(page.getByText('Unsupported by approved evidence',{exact:false})).toBeVisible();
 await page.getByRole('button',{name:'Prepare outreach',exact:true}).click();
 await api(page,'/test/tick');await page.reload();await page.getByRole('button',{name:'Software Engineer (fictional)',exact:true}).first().click();
 await page.getByRole('button',{name:'View drafts',exact:false}).first().click();
 await page.getByRole('button',{name:'Generate suggestion',exact:true}).click();
 await page.getByRole('button',{name:'Apply note',exact:true}).click();
 await page.getByRole('textbox',{name:'Connection note',exact:true}).fill('My manually edited fictional note 😀');
 await page.getByRole('button',{name:'Save changes',exact:true}).click();
 await expect(page.getByText('Drafts saved.',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Close dialog',exact:true}).click();
 await page.getByRole('button',{name:'Outreach queue',exact:true}).click();
 await page.getByLabel('More actions for Avery Example').click();
 await page.getByRole('button',{name:'Record activity',exact:true}).click();
 await page.getByRole('button',{name:'Record activity',exact:true}).last().click();
 await expect(page.getByRole('button',{name:'Undo / correct',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Undo / correct',exact:true}).click();
 await expect(page.getByText('Connection request sent · undone',{exact:true})).toBeVisible();
});
test('provider failure and persistent review resume',async({page})=>{
 await api(page,'/demo/transition');await api(page,'/demo/transition');
 await api(page,'/test/pause');await api(page,'/test/provider/fail');await api(page,'/test/tick');
 const aid='FICTIONAL-NEW';
 let run=await api(page,`/applications/${aid}/preparation`,undefined,'GET');
 expect(run.interrupts[0].reason).toBe('provider_failure');
 await api(page,'/test/provider/ready');await api(page,`/applications/${aid}/preparation/resume`);await api(page,'/test/tick');
 run=await api(page,`/applications/${aid}/preparation`,undefined,'GET');expect(run.interrupts[0].reason).toBe('review');
 await page.reload();await page.locator('tr[data-application-id="FICTIONAL-NEW"]').getByRole('button',{name:'Software Engineer (fictional)',exact:true}).click();
 await page.getByRole('button',{name:'Check preparation run',exact:true}).click();
 await expect(page.getByRole('button',{name:'Resume preparation',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Resume preparation',exact:true}).click();await api(page,'/test/tick');
 run=await api(page,`/applications/${aid}/preparation`,undefined,'GET');expect(run.complete).toBeTruthy();
});

test('description loading blocks saving and ignores a previous application response',async({page})=>{
 await api(page,'/demo/transition');await api(page,'/demo/transition');
 let release!:()=>void;const delayed=new Promise<void>(resolve=>release=resolve);
 await page.route('**/api/applications/FICTIONAL-HISTORY/description',async route=>{if(route.request().method()==='GET'){await delayed;await route.fulfill({json:{text:'Previous fictional description',source_url:'',version:1,provenance:'manual paste',updated_at:'2026-01-01'}})}else await route.continue()});
 await page.locator('tr[data-application-id="FICTIONAL-HISTORY"]').getByRole('button',{name:'Software Engineer (fictional)',exact:true}).click();
 await expect(page.getByRole('button',{name:'Save description',exact:true})).toBeDisabled();
 await expect(page.getByLabel('Job description',{exact:true})).toBeDisabled();
 await page.getByRole('button',{name:/Back to results/}).click();
 await page.locator('tr[data-application-id="FICTIONAL-NEW"]').getByRole('button',{name:'Software Engineer (fictional)',exact:true}).click();
 await expect(page.getByRole('button',{name:'Save description',exact:true})).toBeEnabled();
 release();await expect(page.getByLabel('Job description',{exact:true})).not.toHaveValue('Previous fictional description');
});

test('stale acceptance retains saved drafts and manual saving remains available',async({page})=>{
 const state=await api(page,'/state',undefined,'GET');const c=state.contacts[0];
 await page.getByRole('button',{name:'Outreach queue',exact:true}).click();await page.getByRole('button',{name:'View drafts',exact:false}).first().click();
 await page.getByRole('button',{name:'Generate suggestion',exact:true}).click();
 await expect(page.getByRole('button',{name:'Apply note',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Apply note',exact:true}).click();
 await page.getByRole('button',{name:'Close dialog',exact:true}).click();
 await page.getByRole('button',{name:'View drafts',exact:false}).first().click();
 await api(page,`/applications/${c.application_id}/description`,{text:'Required: Python\nPreferred: Kubernetes',source_url:''},'PUT');await page.getByRole('button',{name:'Save changes',exact:true}).click();
 await expect(page.getByRole('alert')).toContainText('Regenerate');
 const after=await api(page,'/state',undefined,'GET');expect(after.contacts.find((r:any)=>r.id===c.id).note).toBe(c.note);
 await page.getByRole('textbox',{name:'Connection note',exact:true}).fill('Manual fictional note after stale suggestion');await page.getByRole('button',{name:'Save changes',exact:true}).click();await expect(page.getByText('Drafts saved.',{exact:true})).toBeVisible();
});

test('applying only a note does not count the existing DM as edited feedback',async({page})=>{
 const state=await api(page,'/state',undefined,'GET');const c=state.contacts[0];
 await api(page,`/contacts/${c.id}/drafts`,{note:c.note,dm:'Untouched existing fictional DM'},'PUT');await page.reload();
 await page.getByRole('button',{name:'Outreach queue',exact:true}).click();await page.getByRole('button',{name:'View drafts',exact:false}).first().click();
 await page.getByRole('button',{name:'Generate suggestion',exact:true}).click();await page.getByRole('button',{name:'Apply note',exact:true}).click();await page.getByRole('button',{name:'Save changes',exact:true}).click();await expect(page.getByText('Drafts saved.',{exact:true})).toBeVisible();
 const feedback=await api(page,'/metrics/feedback',undefined,'GET');expect(feedback.messages.note.at(-1).edited).toBe(0);
 expect(feedback.messages.dm).toHaveLength(0);
 await page.getByRole('tab',{name:'Direct message',exact:true}).click();await expect(page.getByRole('textbox',{name:'Direct message',exact:true})).toHaveValue('Untouched existing fictional DM');
});


test('DM and both-message applications produce separate observations',async({page})=>{
 const state=await api(page,'/state',undefined,'GET');const c=state.contacts[0];
 await page.getByRole('button',{name:'Outreach queue',exact:true}).click();await page.getByRole('button',{name:'View drafts',exact:false}).first().click();
 await page.getByRole('button',{name:'Generate suggestion',exact:true}).click();await page.getByRole('button',{name:'Apply DM',exact:true}).click();
 await expect(page.getByRole('tab',{name:'Direct message',exact:true})).toHaveAttribute('aria-selected','true');
 await page.getByRole('button',{name:'Save changes',exact:true}).click();await expect(page.getByText('Drafts saved.',{exact:true})).toBeVisible();
 let feedback=await api(page,'/metrics/feedback',undefined,'GET');expect(feedback.messages.dm.at(-1).edited).toBe(0);
 await page.getByRole('button',{name:'Generate suggestion',exact:true}).click();await page.getByRole('button',{name:'Apply both',exact:true}).click();await page.getByRole('button',{name:'Save changes',exact:true}).click();await expect(page.getByText('Drafts saved.',{exact:true})).toBeVisible();
 feedback=await api(page,'/metrics/feedback',undefined,'GET');expect(feedback.messages.dm.at(-1).edited).toBe(0);expect(feedback.messages.note.at(-1).edited).toBe(0);
 await page.keyboard.press('Escape');await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('failed description load keeps Save disabled until successful retry',async({page})=>{
 let failed=true;
 await page.route('**/api/applications/FICTIONAL-HISTORY/description',async route=>{if(failed){await route.fulfill({status:503,json:{detail:'Fictional load failure'}})}else await route.continue()});
 await page.locator('tr[data-application-id="FICTIONAL-HISTORY"]').getByRole('button',{name:'Software Engineer (fictional)',exact:true}).click();
 await expect(page.getByRole('alert')).toContainText('Fictional load failure');await expect(page.getByRole('button',{name:'Save description',exact:true})).toBeDisabled();
 failed=false;await page.getByRole('button',{name:'Retry loading',exact:true}).click();await expect(page.getByRole('button',{name:'Save description',exact:true})).toBeEnabled();
});
test('typed comma-separated technologies are kept as separate entries',async({page})=>{
 await page.getByRole('button',{name:'Experience',exact:true}).click();
 await page.getByRole('button',{name:'Add experience',exact:true}).first().click();
 await page.getByLabel('Factual text').fill('I built a fictional typed technologies record.');
 // Type key by key: a filled value would hide commas being dropped while typing.
 await page.getByLabel('Technologies (comma separated)').pressSequentially('React, TypeScript');
 await expect(page.getByLabel('Technologies (comma separated)')).toHaveValue('React, TypeScript');
 await page.getByRole('button',{name:'Save experience',exact:true}).click();
 const record=page.locator('.experience-record',{hasText:'I built a fictional typed technologies record.'});
 await expect(record.locator('.technology-chip')).toHaveText(['React','TypeScript']);
});
test('hiring outcome can be recorded from application details',async({page})=>{
 await page.locator('tr[data-application-id="FICTIONAL-HISTORY"]').getByRole('button',{name:'Software Engineer (fictional)',exact:true}).click();
 await page.getByText('Record hiring outcome',{exact:true}).click();
 await page.getByLabel('Hiring outcome').selectOption('interviewing');
 await page.getByRole('button',{name:'Save outcome',exact:true}).click();
 await expect(page.getByText('Hiring outcome saved.',{exact:false})).toBeVisible();
 await expect(page.locator('.application-detail .status-badge',{hasText:'Interviewing'})).toBeVisible();
 await api(page,'/applications/FICTIONAL-HISTORY/outcome',{outcome:'unknown',note:''},'PUT');
});
test('unsaved edits yield to a newer saved draft',async({page})=>{
 const state=await api(page,'/state',undefined,'GET');
 const contact=state.contacts.find((c:any)=>c.application_id==='FICTIONAL-HISTORY');
 await page.locator('tr[data-application-id="FICTIONAL-HISTORY"]').getByRole('button',{name:'Software Engineer (fictional)',exact:true}).click();
 await page.getByRole('button',{name:'View drafts',exact:false}).first().click();
 await page.getByRole('textbox',{name:'Connection note',exact:true}).fill('Unsaved fictional working edit');
 await page.getByRole('button',{name:'Close dialog',exact:true}).click();
 await api(page,`/contacts/${contact.id}/drafts`,{note:'Newer saved fictional note',dm:contact.dm},'PUT');
 await page.reload();
 await page.locator('tr[data-application-id="FICTIONAL-HISTORY"]').getByRole('button',{name:'Software Engineer (fictional)',exact:true}).click();
 await page.getByRole('button',{name:'View drafts',exact:false}).first().click();
 await expect(page.getByRole('textbox',{name:'Connection note',exact:true})).toHaveValue('Newer saved fictional note');
 await expect(page.getByText('The saved draft changed after your unsaved edits',{exact:false})).toBeVisible();
});

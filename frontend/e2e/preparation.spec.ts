import {test,expect} from '@playwright/test';
import path from 'node:path';
test('completed preparation rows, actual count and keyboard navigation at desktop and mobile',async({page})=>{
 const token=(await (await page.request.get('/api/bootstrap')).json()).token;
 const snapshot=await (await page.request.get('/api/state',{headers:{'X-Outreach-Token':token}})).json();
 const original=snapshot.applications[0];
 const apps=Array.from({length:63},(_,i)=>({...original,source_application_id:i===0?original.source_application_id:`fictional-completed-${i}`,company:i<2?'Fictional Cedar Labs':`Fictional Company ${i}`,role:i===0?'Platform Engineer':i===1?'Senior Software Engineer, Developer Experience':'Software Engineer',research_state:'ready',job:{state:'done',stage:'done',updated_at:new Date(Date.UTC(2026,9,10,12,0)-i*60000).toISOString()}}));
 await page.route('**/api/state',route=>route.fulfill({json:{...snapshot,applications:apps,contacts:[],sync:null}}));
 for(const [size,width,height] of [['desktop',1280,900],['mobile',390,844]] as const){
  await page.setViewportSize({width,height});await page.goto('/');
  await expect(page.getByRole('button',{name:'Sync applications',exact:true})).toBeVisible();
  const summary=page.locator('summary').filter({hasText:'Preparation idle · 63 completed'});
  await expect(summary).toBeVisible();await summary.focus();await page.keyboard.press('Enter');
  const list=page.getByRole('list',{name:'Completed applications'});
  await expect(list.getByRole('listitem')).toHaveCount(3);
  await expect(list.getByText('Platform Engineer',{exact:true})).toBeVisible();
  await expect(list.getByText('Senior Software Engineer, Developer Experience',{exact:true})).toBeVisible();
  await expect(list.getByText('Software Engineer',{exact:true})).toHaveCount(0);
  const rects=await list.getByRole('listitem').evaluateAll(rows=>rows.map(row=>{const r=row.getBoundingClientRect();const action=row.querySelector('button')!.getBoundingClientRect();return {top:r.top,bottom:r.bottom,right:r.right,actionRight:action.right}}));
  expect(rects[1].top).toBeGreaterThanOrEqual(rects[0].bottom);
  for(const row of rects)expect(Math.abs(row.right-row.actionRight)).toBeLessThan(2);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await summary.locator('..').screenshot({path:path.resolve('../docs/screenshots',`${size}-preparation-completed.png`)});
  await page.getByRole('button',{name:'View all 63 completed',exact:true}).click();await expect(list.getByRole('listitem')).toHaveCount(63);
  await page.getByRole('button',{name:'Show latest three',exact:true}).click();await expect(list.getByRole('listitem')).toHaveCount(3);
  const action=list.getByRole('button',{name:'View outreach for Fictional Cedar Labs · Platform Engineer',exact:true});
  await action.focus();await page.keyboard.press('Enter');await expect(page.getByRole('button',{name:/Back to results/})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Fictional Cedar Labs',exact:false})).toBeVisible();
  await expect(page.getByRole('button',{name:'Sync applications',exact:true})).toBeVisible();
 }
});

import {test,expect} from '@playwright/test';
import path from 'node:path';
test('fictional desktop and mobile visual inspection captures',async({page})=>{
 const screenshotDir=process.env.UPDATE_SCREENSHOTS==='true'?path.resolve('../docs/screenshots'):test.info().outputPath('screenshots');
 const token=(await (await page.request.get('/api/bootstrap')).json()).token;
 await page.request.post('/api/test/showcase',{headers:{'X-Outreach-Token':token}});
 for(const [size,width,height] of [['desktop',1280,900],['mobile',390,844]] as const){
  await page.setViewportSize({width,height});await page.goto('/');
  for(const [view,name] of [['Applications','applications'],['Outreach queue','queue'],['Outreach tracker','tracker'],['Experience','experience'],['Settings','settings']] as const){
   await page.getByRole('button',{name:view,exact:true}).click();
   await expect(page.getByRole('heading',{level:1})).toBeVisible();
   if(view==='Applications')await expect(page.getByRole('button',{name:'Sync applications',exact:true})).toBeVisible();
   if(view==='Experience')await expect(page.getByRole('button',{name:'Add experience',exact:true}).first()).toBeVisible();
   const overflow=await page.evaluate(()=>({width:window.innerWidth,scroll:document.documentElement.scrollWidth,elements:[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>window.innerWidth+1).slice(0,12).map(e=>({tag:e.tagName,class:e.className,right:e.getBoundingClientRect().right,text:e.textContent?.slice(0,35)}))}));
   expect(overflow.scroll,JSON.stringify({size,view,...overflow})).toBeLessThanOrEqual(width);
   await page.screenshot({path:path.join(screenshotDir,`${size}-${name}.png`),fullPage:true});
  }
  await page.getByRole('button',{name:'Outreach queue',exact:true}).click();await page.getByRole('button',{name:'View drafts',exact:false}).first().click();
  await page.getByRole('button',{name:'Generate suggestion',exact:true}).click();await expect(page.getByRole('button',{name:'Apply both',exact:true})).toBeVisible();
  await page.screenshot({path:path.join(screenshotDir,`${size}-draft.png`),fullPage:false});if(size==='mobile'){await page.getByRole('button',{name:'Apply both',exact:true}).scrollIntoViewIfNeeded();await page.screenshot({path:path.join(screenshotDir,'mobile-draft-suggestions.png')});}await page.getByRole('button',{name:'Close dialog',exact:true}).click();
 }
});

import {test,expect} from '@playwright/test';
test.use({baseURL:'https://127.0.0.1:8766',ignoreHTTPSErrors:true});
test('real remote authentication, secure session and unauthorized access',async({page})=>{
 const before=await page.request.get('/api/bootstrap');expect(before.status()).toBe(401);
 await page.goto('/');await expect(page.getByRole('heading',{name:'Sign in',exact:true})).toBeVisible();
 await expect(page.getByText('Fictional Cedar Labs',{exact:true})).toHaveCount(0);
 await page.getByLabel('Username').fill('fictional');await page.getByLabel('Password').fill('fictional-test-password');
 await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Your applications',exact:true})).toBeVisible();
 const cookies=await page.context().cookies();const session=cookies.find(c=>c.name==='__Host-outreach');
 expect(session?.secure).toBeTruthy();expect(session?.httpOnly).toBeTruthy();
 const noCsrf=await page.request.post('/api/sync');expect(noCsrf.status()).toBe(403);
 const token=(await (await page.request.get('/api/bootstrap')).json()).token;
 const authenticated=await page.request.get('/api/state',{headers:{'X-Outreach-Token':token}});expect(authenticated.status()).toBe(200);
 const logout=await page.request.post('/api/logout',{headers:{'X-Outreach-Token':token}});expect(logout.ok()).toBeTruthy();
 expect((await page.request.get('/api/bootstrap')).status()).toBe(401);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { linkedinUrl, copyAndOpen, copyMessage, openProfile } from '../src/actions.mjs';

test('only HTTPS LinkedIn profile links are accepted', () => {
  assert.equal(linkedinUrl('https://linkedin.com/in/fictional-person/'), 'https://www.linkedin.com/in/fictional-person');
  for (const url of ['javascript:alert(1)', 'https://linkedin.com.evil.test/in/name', 'https://www.linkedin.com/jobs/123', 'https://user@linkedin.com/in/name']) {
    assert.throws(() => linkedinUrl(url));
  }
});

const prepared = {url: 'https://www.linkedin.com/in/fictional-person', text: 'Fictional draft'};

test('copy and open uses displayed text and reports each outcome', async () => {
  let copied, opened;
  const popup = {opener: {}};
  const result = await copyAndOpen(prepared, {open: url => {opened=url;return popup}}, {writeText: async text => { copied = text; }});
  assert.equal(popup.opener, null);
  assert.equal(copied, 'Fictional draft');
  assert.equal(opened, 'https://www.linkedin.com/in/fictional-person');
  assert.equal(result.copied, true);
  assert.equal(result.opened, true);
});

test('blocked popup preserves copied text and offers a profile link', async () => {
  const result = await copyAndOpen(prepared, {open: () => null}, {writeText: async () => {}});
  assert.equal(result.copied, true);
  assert.equal(result.opened, false);
  assert.match(result.openError, /blocked/);
  assert.ok(result.prepared.url);
});

test('clipboard failure does not misreport profile opening', async () => {
  const result = await copyAndOpen(prepared, {open: () => ({opener: {}})}, {writeText: async () => { throw new Error('Denied'); }});
  assert.equal(result.copied, false);
  assert.equal(result.opened, true);
  assert.equal(result.prepared.text, 'Fictional draft');
});

test('invalid profile still copies the exact current edit', async () => {
  let copied;
  const result=await copyAndOpen({url:'invalid',text:'Unsaved visible edit'},{open(){throw new Error('not called')}},{writeText:async text=>{copied=text}});
  assert.equal(copied,'Unsaved visible edit');
  assert.equal(result.copied,true);
  assert.equal(result.opened,false);
  assert.match(result.openError,/profile URL/i);
});

test('fallback copy and open actions are independent', async () => {
  let copied;
  assert.equal((await copyMessage('Current text',{writeText:async text=>{copied=text}})).copied,true);
  assert.equal(copied,'Current text');
  assert.equal(openProfile('',{open(){}}).opened,false);
});

test('manual notes of different lengths copy unchanged',async()=>{
 for(const length of [106,199,200,201]){
  const note='a'.repeat(length);let clipboardText;
  const result=await copyMessage(note,{writeText:async text=>{clipboardText=text}});
  assert.equal(result.copied,true);assert.equal(clipboardText,note);
 }
});

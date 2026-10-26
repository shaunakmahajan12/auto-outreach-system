import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  filterApplications,
  submissionGroup,
  completedWhileViewing,
  activeJob,
} from '../src/workflow.mjs';
const rows = [
  {
    source_application_id: 'one',
    company: 'Cedar',
    role: 'Engineer',
    source_status: 'COMPLETED',
    hiring_outcome: 'rejected',
    research_state: 'ready',
    first_seen: '2026-09-18',
    submitted_at: null,
  },
  {
    source_application_id: 'two',
    company: 'Elm',
    role: 'Scientist',
    source_status: 'RUNNING',
    normalized_status: 'processing',
    hiring_outcome: 'unknown',
    research_state: 'awaiting_submission',
    first_seen: '2026-09-17',
    submitted_at: '2026-09-16',
  },
];
const all = {
  scope: 'all',
  submission: 'all',
  outcome: 'all',
  outreach: 'all',
  query: '',
  sort: 'observed-desc',
};
test('submission filter is independent and removed legacy filters are ignored', () => {
  assert.equal(
    filterApplications(rows, { ...all, submission: 'completed', outcome: 'rejected' }).length,
    1,
  );
  assert.equal(submissionGroup(rows[1]), 'pending');
  assert.equal(filterApplications(rows, { ...all, query: 'cedar', outcome: 'unknown' }).length, 1);
  assert.equal(filterApplications(rows, all).length, 2);
});
test('missing submitted dates sort last without using import dates', () => {
  assert.equal(
    filterApplications(rows, { ...all, sort: 'submitted-desc' })[0].source_application_id,
    'two',
  );
  assert.equal(
    filterApplications(rows, { ...all, sort: 'submitted-asc' })[0].source_application_id,
    'two',
  );
});
test('Tsenta order uses source creation dates despite missing submission dates and different import order', () => {
  const applications = [
    {
      ...rows[0],
      source_application_id: 'older',
      company: 'Aardvark',
      source_created_at: '2026-09-17T12:00:00Z',
      first_seen: '2026-09-19',
    },
    {
      ...rows[0],
      source_application_id: 'newer',
      company: 'Zebra',
      source_created_at: '2026-09-18T12:00:00Z',
      first_seen: '2026-09-18',
    },
    { ...rows[1], source_application_id: 'pending', source_created_at: '2026-09-19T12:00:00Z' },
  ];
  const filters = { query: '', submission: 'completed', sort: 'source-desc' };
  assert.deepEqual(
    filterApplications(applications, filters).map(a => a.source_application_id),
    ['newer', 'older'],
  );
  assert.deepEqual(
    filterApplications(applications, { ...filters, sort: 'source-asc' }).map(
      a => a.source_application_id,
    ),
    ['older', 'newer'],
  );
  assert.deepEqual(
    filterApplications(applications, { ...filters, query: 'zebra' }).map(
      a => a.source_application_id,
    ),
    ['newer'],
  );
});
test('completion notification only opens results for the viewed application', () => {
  const next = [{ ...rows[0], job: { state: 'done' } }];
  assert.deepEqual(completedWhileViewing({ one: 'running' }, next, 'two'), [
    { id: 'one', open: false, ready: true },
  ]);
  assert.equal(completedWhileViewing({ one: 'running' }, next, 'one')[0].open, true);
  assert.deepEqual(completedWhileViewing({}, next, 'one'), []);
  assert.equal(activeJob({ job: { state: 'retry' } }), true);
  assert.equal(activeJob({ job: { state: 'interrupted' } }), false);
});

test('workspace omits the missing submission date badge', () => {
  const source = readFileSync(new URL('../src/Workspace.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /Submission date unavailable/);
});

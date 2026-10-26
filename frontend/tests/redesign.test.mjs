import test from 'node:test';
import assert from 'node:assert/strict';
import {
  initialFilters,
  filterApplications,
  findApplication,
  inTracker,
  trackerStatus,
  filterTracker,
  allowedEvents,
  displayValue,
  groupQueueContacts,
  groupQueueCompanies,
  preparationGroups,
} from '../src/workflow.mjs';
const base = {
  source_status: 'COMPLETED',
  hiring_outcome: 'unknown',
  events: [],
  conversation: {
    connection_status: 'unknown',
    invitation_pending: false,
    dm_sent: false,
    followup_due: false,
  },
};
const event = (kind, id = 1, undone_at = null) => ({
  kind,
  id,
  undone_at,
  created_at: '2026-09-01T10:00:00Z',
});
test('simple filters preserve record identity when list excludes selection', () => {
  const a = {
    source_application_id: 'imported-1',
    company: 'Cedar',
    role: 'Engineer',
    historical: 1,
    confirmed_at_baseline: 1,
    source_status: 'COMPLETED',
    research_state: 'ready',
    hiring_outcome: 'interviewing',
    first_seen: '2026-09-01',
  };
  const b = { ...a, source_application_id: 'new-2', historical: 0, company: 'Elm' };
  const f = { ...initialFilters, query: 'cedar', submission: 'completed' };
  assert.deepEqual(filterApplications([a, b], f), [a]);
  assert.equal(findApplication([a, b], 'imported-1').company, 'Cedar');
  assert.equal(filterApplications([a, b], { ...f, query: 'no match' }).length, 0);
  assert.equal(findApplication([a, b], 'imported-1'), a);
  assert.equal(f.query, 'cedar');
});
test('application defaults show verified successful submissions most recently submitted', () => {
  assert.deepEqual(initialFilters, { query: '', submission: 'completed', sort: 'source-desc' });
  const completed = {
    source_application_id: '1',
    company: 'Cedar',
    role: 'Engineer',
    source_status: 'COMPLETED',
    submitted_at: '2026-09-02T01:00:00Z',
  };
  const failed = {
    ...completed,
    source_application_id: '2',
    source_status: 'FAILED',
    submitted_at: '2026-09-03T01:00:00Z',
  };
  assert.deepEqual(filterApplications([failed, completed], initialFilters), [completed]);
});
test('queue groups use actual submission timestamps and put missing dates last', () => {
  const contacts = [
    {
      id: 1,
      application_id: 'missing',
      application_company: 'Alpha',
      role: 'A',
      application_submitted_at: null,
    },
    {
      id: 2,
      application_id: 'old',
      application_company: 'Cedar',
      role: 'C',
      application_submitted_at: '2026-08-01T12:00:00-04:00',
    },
    {
      id: 3,
      application_id: 'new',
      application_company: 'Beta',
      role: 'B',
      application_submitted_at: '2026-09-01T15:00:00Z',
    },
    {
      id: 4,
      application_id: 'new',
      application_company: 'Beta',
      role: 'B',
      application_submitted_at: '2026-09-01T15:00:00Z',
    },
  ];
  const groups = groupQueueContacts(contacts);
  assert.deepEqual(
    groups.map(g => g.application_id),
    ['new', 'old', 'missing'],
  );
  assert.equal(groups[0].contacts.length, 2);
});
test('queue company groups keep applications distinct and sort by newest submission', () => {
  const contacts = [
    {
      id: 1,
      application_id: 'cedar-old',
      application_company: 'Cedar',
      role: 'Engineer',
      application_submitted_at: '2026-08-01T16:00:00Z',
    },
    {
      id: 2,
      application_id: 'cedar-new',
      application_company: ' cedar ',
      role: 'Lead',
      application_submitted_at: '2026-09-04T12:00:00-04:00',
    },
    {
      id: 3,
      application_id: 'cedar-new',
      application_company: 'Cedar',
      role: 'Lead',
      application_submitted_at: '2026-09-04T16:00:00Z',
    },
    {
      id: 4,
      application_id: 'alpha-missing',
      application_company: 'Alpha',
      role: 'Analyst',
      application_submitted_at: null,
    },
    {
      id: 5,
      application_id: 'beta',
      application_company: 'Beta',
      role: 'Designer',
      application_submitted_at: '2026-09-03T00:00:00Z',
    },
  ];
  const groups = groupQueueCompanies(contacts);
  assert.deepEqual(
    groups.map(group => group.company),
    ['cedar', 'Beta', 'Alpha'],
  );
  assert.equal(groups[0].contact_count, 3);
  assert.deepEqual(
    groups[0].applications.map(application => application.application_id),
    ['cedar-new', 'cedar-old'],
  );
  assert.equal(groups[0].applications[0].contacts.length, 2);
});
test('preparation dashboard separates queued, active, failed, and completed state', () => {
  const app = (id, state, stage = state) => ({
    source_application_id: id,
    job: { state, stage, updated_at: '2026-09-01T00:00:00Z' },
  });
  const groups = preparationGroups([
    app('q', 'queued'),
    app('r', 'running', 'drafting_messages'),
    app('x', 'retry', 'retry'),
    app('f', 'failed'),
    app('d', 'done'),
  ]);
  assert.deepEqual(
    groups.queued.map(a => a.source_application_id),
    ['q'],
  );
  assert.deepEqual(
    groups.running.map(a => a.source_application_id),
    ['r', 'x'],
  );
  assert.deepEqual(
    groups.failed.map(a => a.source_application_id),
    ['f'],
  );
  assert.deepEqual(
    groups.completed.map(a => a.source_application_id),
    ['d'],
  );
});
test('tracker excludes unsent drafts and undone-only history', () => {
  assert.equal(inTracker(base), false);
  assert.equal(inTracker({ ...base, events: [event('dm_sent', 1, '2026-09-02')] }), false);
  assert.equal(inTracker({ ...base, events: [event('closed')] }), false);
  for (const kind of ['invitation_sent', 'connection_accepted', 'dm_sent', 'reply'])
    assert.equal(inTracker({ ...base, events: [event(kind)] }), true);
});
test('tracker separates invitation and message states and filters actual activity', () => {
  const pending = {
    ...base,
    name: 'Avery',
    application_company: 'Cedar',
    events: [event('invitation_sent')],
    conversation: { ...base.conversation, invitation_pending: true },
  };
  const replied = {
    ...pending,
    name: 'Morgan',
    events: [event('dm_sent'), event('reply', 2)],
    conversation: {
      ...base.conversation,
      dm_sent: true,
      closed_reason: 'reply',
      followup_due: true,
    },
  };
  assert.equal(trackerStatus(pending).invitation, 'Invitation pending');
  assert.equal(trackerStatus(pending).message, '');
  assert.deepEqual(filterTracker([pending, replied, base], 'pending'), [pending]);
  assert.deepEqual(filterTracker([pending, replied], 'replied', 'morgan'), [replied]);
  assert.equal(trackerStatus(replied).group, 'replied');
  assert.equal(allowedEvents(replied).includes('followup_sent'), false);
  assert.equal(trackerStatus({ ...replied, hiring_outcome: 'rejected' }).group, 'closed');
});
test('placeholder source values are absent without damaging valid company names', () => {
  for (const v of [null, 'Unknown Company', 'UNAVAILABLE', 'unknown'])
    assert.equal(displayValue(v), '');
  assert.equal(displayValue('Unknown Ventures'), 'Unknown Ventures');
});

test('queue shares every application sort while ignoring application-only filters', () => {
  const rows = [
    {
      source_application_id: 'a',
      company: 'Cedar',
      role: 'Engineer',
      submitted_at: '2026-09-04T12:00:00-04:00',
      first_seen: '2026-09-01',
      source_status: 'COMPLETED',
    },
    {
      source_application_id: 'b',
      company: 'Birch',
      role: 'Engineer',
      submitted_at: '2026-09-04T16:00:00Z',
      first_seen: '2026-09-02',
      source_status: 'FAILED',
    },
    {
      source_application_id: 'c',
      company: 'Cedar',
      role: 'Lead',
      submitted_at: '2026-08-01',
      first_seen: '2026-09-03',
      source_status: 'COMPLETED',
    },
    {
      source_application_id: 'd',
      company: 'Elm',
      role: 'Engineer',
      submitted_at: 'invalid',
      first_seen: null,
      source_status: 'COMPLETED',
    },
    {
      source_application_id: 'e',
      company: 'Fir',
      role: 'Engineer',
      submitted_at: null,
      first_seen: '2026-09-05',
      source_status: 'COMPLETED',
    },
  ];
  const contacts = rows.map((a, i) => ({
    id: i,
    application_id: a.source_application_id,
    application_company: a.company,
    role: a.role,
    created_at: '2030-01-01',
  }));
  for (const sort of ['submitted-desc', 'submitted-asc', 'observed-desc', 'observed-asc']) {
    const ordered = filterApplications(rows, { query: '', submission: 'all', sort });
    const groups = groupQueueCompanies(contacts, rows, sort);
    assert.deepEqual(
      groups.map(g => g.company),
      [...new Set(ordered.map(a => a.company))],
    );
    for (const g of groups)
      assert.deepEqual(
        g.applications.map(a => a.application_id),
        ordered.filter(a => a.company === g.company).map(a => a.source_application_id),
      );
    assert.equal(
      groups.reduce((n, g) => n + g.contact_count, 0),
      5,
    );
  }
  assert.equal(
    filterApplications(rows, { query: 'no match', submission: 'completed', sort: 'submitted-desc' })
      .length,
    0,
  );
  assert.equal(groupQueueCompanies(contacts, rows).length, 4);
});

test('relevance labels use evidence assessment, never rank or confidence', async () => {
  const { relevanceLabel } = await import('../src/workflow.mjs');
  for (const level of ['high', 'medium', 'low'])
    assert.equal(
      relevanceLabel({ rank: 1, relevance_assessment: { level } }),
      level[0].toUpperCase() + level.slice(1) + ' relevance',
    );
  assert.equal(relevanceLabel({ rank: 1, review_status: 'supported' }), 'Not assessed');
});

test('contacts sort by relevance level, optional score, then stable name and ID', async () => {
  const { compareContactRelevance } = await import('../src/workflow.mjs');
  const make = (id, name, level, score) => ({
    id,
    name,
    application_id: 'app',
    application_company: 'Cedar',
    role: 'Engineer',
    relevance_assessment: { level, score },
  });
  const contacts = [
    make(9, 'Zed', 'unassessed'),
    make(8, 'Low', 'low', 999),
    make(7, 'Medium', 'medium', 999),
    make(6, 'Zed', 'high', 90),
    make(5, 'Bea', 'high', 90),
    make(4, 'Ada', 'high', 80),
    make(3, 'Same', 'high'),
    make(2, 'Same', 'high'),
    make(1, 'Ada', 'high'),
  ];
  const original = contacts.map(c => c.id);
  const expected = [5, 6, 4, 1, 2, 3, 7, 8, 9];
  const grouped = groupQueueCompanies(contacts);
  assert.deepEqual(
    grouped[0].applications[0].contacts.map(c => c.id),
    expected,
  );
  assert.deepEqual(
    contacts.map(c => c.id),
    original,
    'does not mutate source records',
  );
  assert.deepEqual(
    JSON.parse(JSON.stringify(contacts))
      .reverse()
      .sort(compareContactRelevance)
      .map(c => c.id),
    expected,
    'refresh order does not affect ties',
  );
  assert.deepEqual(
    groupQueueCompanies(contacts.filter(c => c.name === 'Same'))[0].applications[0].contacts.map(
      c => c.id,
    ),
    [2, 3],
  );
  const updated = contacts.map(c =>
    c.id === 9 ? { ...c, relevance_assessment: { level: 'high', score: 100 } } : c,
  );
  assert.equal(
    groupQueueCompanies(updated)[0].applications[0].contacts[0].id,
    9,
    'relevance updates reorder automatically',
  );
  assert.ok(
    compareContactRelevance(make(1, 'A', 'high', 0), make(2, 'B', 'high', NaN)) < 0,
    'zero is a real score; NaN is missing',
  );
});

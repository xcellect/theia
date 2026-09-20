import test from 'node:test';
import assert from 'node:assert/strict';
import { localBase, runResearchSmoke, verifyReport } from '../scripts/research-smoke.mjs';

const report = '# Test\n\n## Answer\nVerified [S1](/api/research/runs/run-1/sources/S1).\n\n## Evidence and analysis\nEvidence.\n\n## Limitations and open questions\nExcerpt only.\n\n## Sources analyzed\nS1';
const completedEvents = [
  ['routing.completed', { answers: { intent: { choice: 'explain' } } }],
  ['source.read', { source: { id: 'S1' } }],
  ['agent.delta', { agent: 'evidence', text: 'A finding' }],
  ['agent.completed', { agent: 'evidence', text: 'A finding' }],
  ['agent.completed', { agent: 'critic', text: 'A limitation' }],
  ['report.completed', { markdown: report, partial: false }],
  ['run.completed', { status: 'completed', partial: false }],
];
function backend(events = completedEvents, visited = []) {
  return async (url, options) => {
    visited.push({ url, options });
    if (url.endsWith('/health')) return Response.json({ configured: true });
    if (url.endsWith('/cancel')) return Response.json({ runId: 'run-1', status: 'cancelled' });
    if (url.endsWith('/runs')) return Response.json({ runId: 'run-1' }, { status: 202 });
    const text = events.map(([type, payload], index) => `id: ${index + 1}\ndata: ${JSON.stringify({ runId: 'run-1', seq: index + 1, type, payload })}\n\n`).join('');
    return new Response(text, { headers: { 'content-type': 'text/event-stream' } });
  };
}

test('live smoke contract accepts complete routed two-agent stream and prints no content', async () => {
  const visited = [];
  const summary = await runResearchSmoke({ fetchImpl: backend(completedEvents, visited) });
  assert.equal(summary.result, 'PASS');
  assert.equal(summary.completedAgents, 2);
  assert.equal(summary.reportCitations, 1);
  assert.doesNotMatch(JSON.stringify(summary), /A finding|A limitation|# Test/);
  assert.equal(visited[1].options.headers.Origin, 'http://127.0.0.1:3000');
  assert.equal(visited.length, 3);
});

test('smoke rejects unlinked, unknown, fabricated-range citations and missing report headings', () => {
  const ids = new Set(['S1']);
  for (const invalid of [
    report.replace('[S1](/api/research/runs/run-1/sources/S1)', '[S1 lines 1-50]'),
    report.replaceAll('S1', 'S999'),
    report.replace('## Evidence and analysis', '## Other'),
    report.replace('/api/research/runs/run-1/sources/S1', 'https://invented.example'),
  ]) assert.throws(() => verifyReport(invalid, 'run-1', ids));
});

test('smoke rejects partial/truncated runs and cancels unfinished work', async () => {
  const visited = [];
  await assert.rejects(runResearchSmoke({ fetchImpl: backend(completedEvents.slice(0, 3), visited) }), /did not complete/);
  assert.match(visited.at(-1).url, /\/cancel$/);
  assert.equal(visited.at(-1).options.body, '{}');
  const partial = completedEvents.map(([type, payload]) => [type, type === 'report.completed' ? { ...payload, partial: true } : payload]);
  await assert.rejects(runResearchSmoke({ fetchImpl: backend(partial) }), /did not complete/);
});

test('smoke accepts only local origins and never echoes rejected configuration', () => {
  assert.equal(localBase('http://localhost:3001'), 'http://localhost:3001');
  for (const invalid of ['https://external.example', 'http://private@localhost:3000', 'http://localhost:3000/private', 'http://localhost:3000/?key=private']) {
    assert.throws(() => localBase(invalid), error => !error.message.includes('private'));
  }
});

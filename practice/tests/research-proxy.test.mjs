import test from 'node:test';
import assert from 'node:assert/strict';
import { proxyResearch } from '../lib/research-proxy.mjs';

function request(path = 'runs', options = {}) {
  const method = path === 'runs' || path.endsWith('/cancel') || path.endsWith('/offer') ? 'POST' : 'GET';
  return new Request(`http://localhost:3000/api/research/${path}`, {
    method, ...(method === 'POST' ? { body: JSON.stringify({ question: 'Explain the paper' }) } : {}),
    headers: { host: '127.0.0.1:3000', origin: 'http://127.0.0.1:3000', 'content-type': 'application/json' },
    ...options,
  });
}

const mustNotFetch = () => { throw new Error('must not fetch'); };

test('research mutations require the local same origin and JSON', async () => {
  for (const [headers, status] of [
    [{}, 403],
    [{ origin: 'https://untrusted.example' }, 403],
    [{ origin: 'http://localhost:3000', 'sec-fetch-site': 'cross-site' }, 403],
    [{ host: 'untrusted.example', origin: 'http://untrusted.example' }, 403],
    [{ host: 'localhost:3000/path', origin: 'http://localhost:3000' }, 403],
    [{ origin: 'http://localhost:3000', 'content-type': 'text/plain' }, 415],
  ]) {
    const response = await proxyResearch(request('runs', { headers }), 'runs', { fetchImpl: mustNotFetch });
    assert.equal(response.status, status);
  }
});

test('route allowlist rejects traversal, arbitrary endpoints, methods and oversized bodies', async () => {
  for (const path of ['https://untrusted.example', 'runs/../health', 'runs/%2e%2e/events', 'runs/id/events/extra', 'sources/S1', 'voice/arbitrary', ['runs', 'id/evil', 'events']]) {
    assert.equal((await proxyResearch(request(), path, { fetchImpl: mustNotFetch })).status, 404);
  }
  assert.equal((await proxyResearch(request('health', { method: 'DELETE' }), 'health', { fetchImpl: mustNotFetch })).status, 405);
  for (const body of ['[]', 'null', 'not JSON', JSON.stringify({ text: 'x'.repeat(128 * 1024) })]) {
    assert.equal((await proxyResearch(request('runs', { body }), 'runs', { fetchImpl: mustNotFetch })).status, 400);
  }
});

test('run creation uses fixed backend without forwarding browser credentials and retains 202', async () => {
  const response = await proxyResearch(request('runs', {
    headers: { host: 'localhost:3000', origin: 'http://localhost:3000', 'content-type': 'application/json', cookie: 'private', authorization: 'private' },
  }), ['runs'], { fetchImpl: async (url, options) => {
    assert.equal(url, 'http://127.0.0.1:7860/research/runs');
    assert.deepEqual(options.headers, { 'Content-Type': 'application/json', 'X-Pipecat-Proxy': 'practice-web' });
    assert.equal(options.method, 'POST');
    assert.equal(options.redirect, 'error');
    assert.equal(options.cache, 'no-store');
    assert.ok(options.signal instanceof AbortSignal);
    assert.deepEqual(JSON.parse(options.body), { question: 'Explain the paper' });
    return Response.json({ runId: 'run-1', internalKey: 'private' }, { status: 202 });
  } });
  assert.equal(response.status, 202);
  assert.deepEqual(await response.json(), { runId: 'run-1' });
  assert.match(response.headers.get('cache-control'), /no-store/);
});

test('health preserves source and provider readiness without configuration secrets', async () => {
  const data = {
    status: 'ok', configured: false, missing: ['TYPESAFE_API_KEY', 'EXA_API_KEY', 'private'], configError: 'private', activeRunId: null, latestRunId: 'run-1',
    activeSessionId: null, latestSessionId: 'tab-1', search: { configured: true, provider: 'Exa', apiKey: 'private' },
    paper2agent: { available: true, mode: 'draft', supported: 'arxiv', root: '/private/repo', config: 'private' },
    sources: [{ id: 'paper2agent-paper', title: 'Paper2Agent', kind: 'paper', description: 'Bundled manuscript', private: 'private' }],
    providers: { routing: 'Jev', analysis: 'General Compute', model: 'configured-model', apiKey: 'private' },
    internalConfig: { apiKey: 'private' },
  };
  const response = await proxyResearch(request('health', { headers: {} }), 'health', { fetchImpl: async () => Response.json(data) });
  const result = await response.json();
  assert.equal(result.configured, false);
  assert.deepEqual(result.missing, ['TYPESAFE_API_KEY', 'EXA_API_KEY']);
  assert.deepEqual(result.sources, [{ id: 'paper2agent-paper', title: 'Paper2Agent', kind: 'paper', description: 'Bundled manuscript' }]);
  assert.deepEqual(result.providers, { routing: 'Jev', analysis: 'General Compute', model: 'configured-model' });
  assert.equal(result.activeRunId, null);
  assert.equal(result.latestRunId, 'run-1');
  assert.equal(result.activeSessionId, null);
  assert.equal(result.latestSessionId, 'tab-1');
  assert.deepEqual(result.search, { configured: true, provider: 'Exa' });
  assert.deepEqual(result.paper2agent, { available: true, mode: 'draft', supported: 'arxiv' });
  assert.doesNotMatch(JSON.stringify(result), /private/);
});

test('health permits nullable latest run recovery IDs but strips invalid values', async () => {
  for (const latestRunId of [null, '../private', 42, 'https://private.example']) {
    const response = await proxyResearch(request('health'), 'health', {
      fetchImpl: async () => Response.json({ configured: true, missing: [], latestRunId }),
    });
    const data = await response.json();
    if (latestRunId === null) assert.equal(data.latestRunId, null);
    else assert.equal(Object.hasOwn(data, 'latestRunId'), false);
  }
});

test('health only exposes supported Paper2Agent draft preparation metadata', async () => {
  for (const paper2agent of [
    { available: false, mode: 'draft', supported: 'arxiv' },
    { available: true, mode: 'verified', supported: 'arxiv' },
    { available: true, mode: 'draft', supported: 'arbitrary' },
    { available: 'private', mode: 'draft', supported: 'arxiv' },
  ]) {
    const response = await proxyResearch(request('health'), 'health', {
      fetchImpl: async () => Response.json({ configured: true, missing: [], paper2agent }),
    });
    const data = await response.json();
    if (paper2agent.available === false) assert.deepEqual(data.paper2agent, paper2agent);
    else assert.equal(Object.hasOwn(data, 'paper2agent'), false);
  }
});

test('SSE returns before completion, preserves chunks and Last-Event-ID, and cancels upstream', async () => {
  let enqueue;
  let cancelled = false;
  let upstreamSignal;
  const source = new ReadableStream({
    start(controller) { enqueue = text => controller.enqueue(new TextEncoder().encode(text)); },
    cancel() { cancelled = true; },
  });
  const response = await proxyResearch(request('runs/run-1/events', {
    headers: { 'last-event-id': '12', host: 'localhost:3000' },
  }), ['runs', 'run-1', 'events'], { fetchImpl: async (url, options) => {
    assert.equal(url, 'http://127.0.0.1:7860/research/runs/run-1/events');
    assert.equal(options.headers['Last-Event-ID'], '12');
    assert.equal(options.headers.Accept, 'text/event-stream');
    assert.equal(options.headers.Origin, undefined);
    upstreamSignal = options.signal;
    return new Response(source, { headers: { 'content-type': 'text/event-stream' } });
  } });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('x-accel-buffering'), 'no');
  assert.match(response.headers.get('cache-control'), /no-store/);
  const reader = response.body.getReader();
  const first = 'id: 13\ndata: {"type":"agent.delta","payload":{"delta":"Hello"}}\n\n';
  enqueue(first);
  assert.equal(new TextDecoder().decode((await reader.read()).value), first);
  assert.equal(upstreamSignal.aborted, false);
  await reader.cancel();
  assert.equal(upstreamSignal.aborted, true);
  assert.equal(cancelled, true);
});

test('browser disconnect propagates to the backend fetch signal', async () => {
  const abort = new AbortController();
  let upstreamSignal;
  const response = await proxyResearch(request('runs/run-1/events', { signal: abort.signal }), 'runs/run-1/events', {
    fetchImpl: async (_url, options) => {
      upstreamSignal = options.signal;
      return new Response(new ReadableStream({}), { headers: { 'content-type': 'text/event-stream' } });
    },
  });
  abort.abort();
  assert.equal(upstreamSignal.aborted, true);
  await response.body.cancel();
});

test('event replay rejects invalid sequence headers and preserves expired replay status', async () => {
  for (const lastEventId of ['-1', 'one', '1/../../health', '12345678901']) {
    const response = await proxyResearch(request('runs/id/events', { headers: { 'last-event-id': lastEventId } }), 'runs/id/events', { fetchImpl: mustNotFetch });
    assert.equal(response.status, 400);
  }
  const expired = await proxyResearch(request('runs/id/events'), 'runs/id/events', {
    fetchImpl: async () => Response.json({ error: { code: 'REPLAY_EXPIRED', message: 'private' } }, { status: 410 }),
  });
  assert.equal(expired.status, 410);
  assert.equal((await expired.json()).error.code, 'REPLAY_EXPIRED');
});

test('cancel retains actual terminal state and sources expose only registered public fields', async () => {
  for (const status of ['completed', 'cancelled']) {
    const response = await proxyResearch(request('runs/id/cancel', { body: '{}' }), 'runs/id/cancel', {
      fetchImpl: async (url, options) => {
        assert.equal(url, 'http://127.0.0.1:7860/research/runs/id/cancel');
        assert.equal(options.body, '{}');
        return Response.json({ runId: 'id', status, private: 'private' });
      },
    });
    assert.deepEqual(await response.json(), { runId: 'id', status });
  }
  const response = await proxyResearch(request('runs/id/sources/S1'), 'runs/id/sources/S1', {
    fetchImpl: async () => Response.json({ id: 'S1', title: 'Paper', text: 'An exact excerpt.', section: 'Overview', url: 'javascript:alert(1)', path: '/private/secret', startLine: 1, endLine: 3, private: 'private' }),
  });
  assert.deepEqual(await response.json(), { id: 'S1', title: 'Paper', text: 'An exact excerpt.', section: 'Overview', startLine: 1, endLine: 3 });
});

test('voice health and signaling use research-specific backend routes', async () => {
  const health = await proxyResearch(request('voice/health'), 'voice/health', { fetchImpl: async url => {
    assert.equal(url, 'http://127.0.0.1:7860/research/voice/health');
    return Response.json({ configured: true, missing: [], activeSessions: 0 });
  } });
  assert.equal((await health.json()).configured, true);
  for (const method of ['POST', 'PATCH']) {
    const response = await proxyResearch(request('voice/offer', { method }), 'voice/offer', { fetchImpl: async (url, options) => {
      assert.equal(url, 'http://127.0.0.1:7860/research/voice/offer');
      assert.equal(options.method, method);
      return method === 'PATCH' ? new Response(null, { status: 204 }) : Response.json({ sdp: 'answer', type: 'answer', pc_id: 'pc-1', private: 'private' });
    } });
    assert.deepEqual(await response.json(), method === 'PATCH' ? { status: 'ok' } : { sdp: 'answer', type: 'answer', pc_id: 'pc-1' });
  }
});

test('voice context forwards bounded same-origin JSON to a fixed endpoint and sanitizes acknowledgment', async () => {
  const payload = { sourceIds: ['paper2agent-code'], pastedText: 'function example() {}', pastedKind: 'code', paper2agentEnabled: true };
  const response = await proxyResearch(request('context', { method: 'POST', body: JSON.stringify(payload) }), ['context'], {
    fetchImpl: async (url, options) => {
      assert.equal(url, 'http://127.0.0.1:7860/research/context');
      assert.equal(options.method, 'POST');
      assert.deepEqual(JSON.parse(options.body), payload);
      assert.deepEqual(options.headers, { 'Content-Type': 'application/json', 'X-Pipecat-Proxy': 'practice-web' });
      return Response.json({ status: 'ok', internalState: 'private' });
    },
  });
  assert.deepEqual(await response.json(), { status: 'ok' });
  assert.match(response.headers.get('cache-control'), /no-store/);
  assert.equal((await proxyResearch(request('context'), 'context', { fetchImpl: mustNotFetch })).status, 405);
  assert.equal((await proxyResearch(request('context', { method: 'POST', body: '{}', headers: {} }), 'context', { fetchImpl: mustNotFetch })).status, 403);
  assert.equal((await proxyResearch(request('context', { method: 'POST', body: JSON.stringify({ pastedText: 'x'.repeat(128 * 1024) }) }), 'context', { fetchImpl: mustNotFetch })).status, 400);
  const malformed = await proxyResearch(request('context', { method: 'POST', body: '{}' }), 'context', {
    fetchImpl: async () => Response.json({ status: 'private', internalState: 'private' }),
  });
  assert.equal(malformed.status, 503);
  assert.doesNotMatch(await malformed.text(), /private/);
});

test('unknown failures, malformed responses and offline backend cannot leak raw errors', async () => {
  for (const fetchImpl of [
    async () => { throw new Error('private'); },
    async () => new Response('private', { status: 500 }),
    async () => Response.json({ error: { code: 'INTERNAL', message: 'private', stack: 'private' } }, { status: 500 }),
    async () => Response.json({ internalConfig: 'private' }),
  ]) {
    const response = await proxyResearch(request(), 'runs', { fetchImpl });
    assert.ok(response.status >= 500);
    assert.doesNotMatch(await response.text(), /private/);
  }
  const missing = await proxyResearch(request(), 'runs', { fetchImpl: async () => Response.json({ error: {
    code: 'MISSING_CONFIG', message: 'private', missing: ['TYPESAFE_API_KEY', 'private'],
  } }, { status: 503 }) });
  assert.equal((await missing.json()).error.message, 'Missing variables: TYPESAFE_API_KEY');
});

test('persistent workspace routes expose only public session and job fields', async () => {
  const payload = { sessionId: 'session-1', secret: 'internal-secret', papers: [{ paperId: 'paper-a', title: 'Paper', path: '/private/work', reports: [{ runId: 'run-1', status: 'draft' }], jobs: [{ state: 'blocked_compute', reason: 'Insufficient RAM', privateLog: '/private/log', repository: { url: 'https://github.com/owner/repo', commit: 'a'.repeat(40), credentials: 'secret' }, capabilities: { ramAvailableBytes: 1234, secret: 'secret', gpu: [] } }] }], runs: [{ runId: 'run-1', question: 'Explain it', status: 'completed' }], messages: [] };
  const response = await proxyResearch(request('sessions/session-1'), 'sessions/session-1', { fetchImpl: async url => { assert.equal(url, 'http://127.0.0.1:7860/research/sessions/session-1'); return Response.json(payload); } });
  const data = await response.json();
  assert.equal(data.papers[0].jobs[0].state, 'blocked_compute');
  assert.equal(data.papers[0].jobs[0].capabilities.ramAvailableBytes, 1234);
  assert.ok(!JSON.stringify(data).includes('secret'));
  assert.ok(!JSON.stringify(data).includes('/private'));
  const listed = await proxyResearch(request('sessions'), 'sessions', { fetchImpl: async () => Response.json({ sessions: [{ sessionId: 'session-1', title: 'Paper', latestRunId: 'run-1', paperCount: 1, databasePath: '/private/state.sqlite' }] }) });
  assert.deepEqual((await listed.json()).sessions, [{ sessionId: 'session-1', title: 'Paper', latestRunId: 'run-1', paperCount: 1 }]);
});

test('conversation pages forward only a validated cursor and preserve full reports and turn metadata', async () => {
  const markdown = '# Complete report\n\n' + 'A cited finding. '.repeat(17000);
  const payload = {
    sessionId: 'session-1', papers: [], summary: '', totalRuns: 25, hasMore: true, nextBefore: 'run-5',
    runs: [{ runId: 'run-5', question: 'Explain it', markdown, done: true, partial: true, status: 'completed', createdAt: '2026-09-19', privateFile: '/private/path' }],
    messages: Array.from({ length: 40 }, (_, index) => ({ messageId: index, role: index % 2 ? 'assistant' : 'user', content: 'Turn content', runId: `run-${index >> 1}`, status: 'completed', createdAt: '2026-09-19', privateFile: '/private/path' })),
  };
  const response = await proxyResearch(request('sessions/session-1?before=run-25&host=untrusted'), ['sessions', 'session-1'], {
    fetchImpl: async (url, options) => {
      assert.equal(url, 'http://127.0.0.1:7860/research/sessions/session-1?before=run-25');
      assert.equal(options.method, 'GET');
      return Response.json(payload);
    },
  });
  assert.equal(response.status, 200);
  const data = await response.json();
  assert.equal(data.runs[0].markdown, markdown);
  assert.equal(data.runs[0].done, true);
  assert.equal(data.runs[0].partial, true);
  assert.equal(data.messages.length, 40);
  assert.equal(data.messages[0].createdAt, '2026-09-19');
  assert.equal(data.totalRuns, 25);
  assert.equal(data.nextBefore, 'run-5');
  assert.equal(data.hasMore, true);
  assert.doesNotMatch(JSON.stringify(data), /private/);
  for (const query of ['before=', 'before=..%2Frun', 'before=one&before=two']) {
    assert.equal((await proxyResearch(request(`sessions/session-1?${query}`), ['sessions', 'session-1'], { fetchImpl: mustNotFetch })).status, 400);
  }
});

test('conversation deletion is same-origin, allowlisted, sanitized and accepts empty or JSON bodies', async () => {
  for (const body of [undefined, '{}']) {
    const response = await proxyResearch(request('sessions/session-1', { method: 'DELETE', ...(body ? { body } : {}) }), ['sessions', 'session-1'], {
      fetchImpl: async (url, options) => {
        assert.equal(url, 'http://127.0.0.1:7860/research/sessions/session-1');
        assert.equal(options.method, 'DELETE');
        assert.equal(options.body, body);
        return Response.json({ sessionId: 'session-1', status: 'deleted', privatePath: '/private/path' });
      },
    });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { sessionId: 'session-1', status: 'deleted' });
  }
  for (const headers of [{}, { origin: 'https://untrusted.example' }, { origin: 'http://localhost:3000', 'sec-fetch-site': 'cross-site' }]) {
    assert.equal((await proxyResearch(request('sessions/session-1', { method: 'DELETE', headers }), ['sessions', 'session-1'], { fetchImpl: mustNotFetch })).status, 403);
  }
  for (const path of ['sessions', 'runs/run-1/events', 'runs']) {
    assert.equal((await proxyResearch(request(path, { method: 'DELETE', body: null }), path, { fetchImpl: mustNotFetch })).status, 405);
  }
  const busy = await proxyResearch(request('sessions/session-1', { method: 'DELETE' }), ['sessions', 'session-1'], {
    fetchImpl: async () => Response.json({ error: { code: 'SESSION_BUSY', message: 'private internals' } }, { status: 409 }),
  });
  assert.equal(busy.status, 409);
  assert.equal((await busy.json()).error.code, 'SESSION_BUSY');
  const malformed = await proxyResearch(request('sessions/session-1', { method: 'DELETE' }), ['sessions', 'session-1'], {
    fetchImpl: async () => Response.json({ sessionId: '../private', status: 'deleted', path: '/private' }),
  });
  assert.equal(malformed.status, 503);
  assert.doesNotMatch(await malformed.text(), /private/);
});

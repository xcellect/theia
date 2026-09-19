import test from 'node:test';
import assert from 'node:assert/strict';
import { proxyPipecat } from '../lib/pipecat-proxy.mjs';
import { readConfig, missingVariables } from '../lib/config.mjs';

const req = (path = 'offer', options = {}) => new Request(`http://localhost:3000/api/pipecat/${path}`, {
  ...(path === 'offer' ? { method: 'POST', body: JSON.stringify({ sdp: 'fixture-sdp', type: 'offer' }) } : {}),
  headers: { host: '127.0.0.1:3000', origin: 'http://127.0.0.1:3000', 'content-type': 'application/json' },
  ...options,
});

test('Pipecat configuration is independent of EVI config and secret', () => {
  assert.deepEqual(missingVariables('pipecat', { HUME_API_KEY: 'fixture' }), ['DEEPGRAM_API_KEY', 'SAMBANOVA_API_KEY', 'SAMBANOVA_MODEL', 'HUME_VOICE_ID']);
  assert.doesNotThrow(() => readConfig('pipecat', { HUME_API_KEY: 'fixture', HUME_VOICE_ID: 'fixture', DEEPGRAM_API_KEY: 'fixture', SAMBANOVA_API_KEY: 'fixture', SAMBANOVA_MODEL: 'fixture' }));
  assert.throws(() => readConfig('evi', { HUME_API_KEY: 'fixture' }), /HUME_SECRET_KEY, HUME_CONFIG_ID/);
});

test('signaling refuses absent/cross origins, public hosts and non-JSON before contacting backend', async () => {
  const fetchImpl = () => { throw new Error('must not fetch'); };
  for (const [headers, status] of [
    [{}, 403],
    [{ origin: 'https://elsewhere.example' }, 403],
    [{ origin: 'http://localhost:3000', 'sec-fetch-site': 'cross-site' }, 403],
    [{ origin: 'http://attacker.example', host: 'attacker.example' }, 403],
    [{ origin: 'http://localhost:3000', 'content-type': 'text/plain' }, 415],
  ]) assert.equal((await proxyPipecat(req('offer', { headers }), 'offer', { fetchImpl })).status, status);
});

test('POST and PATCH use the fixed backend, bounded signal and proxy header without forwarding secrets', async () => {
  for (const method of ['POST', 'PATCH']) {
    const response = await proxyPipecat(req('offer', { method }), 'offer', { fetchImpl: async (url, options) => {
      assert.equal(url, 'http://127.0.0.1:7860/api/offer');
      assert.equal(options.method, method);
      assert.deepEqual(options.headers, { 'Content-Type': 'application/json', 'X-Pipecat-Proxy': 'practice-web' });
      assert.equal(options.redirect, 'error');
      assert.ok(options.signal instanceof AbortSignal);
      return Response.json({ sdp: 'answer-sdp', type: 'answer', pc_id: 'session-1', secret: 'must-not-leak' });
    } });
    assert.equal(response.status, 200);
    assert.match(response.headers.get('cache-control'), /no-store/);
    assert.doesNotMatch(await response.text(), /must-not-leak/);
  }
});

test('health exposes only safe readiness fields and recognizes missing config and busy errors', async () => {
  const health = await proxyPipecat(req('health'), 'health', { fetchImpl: async () => Response.json({ configured: false, missing: ['DEEPGRAM_API_KEY', 'secret-value'], activeSessions: 0, secret: 'must-not-leak' }) });
  assert.deepEqual(await health.json(), { status: 'ok', configured: false, missing: ['DEEPGRAM_API_KEY'], activeSessions: 0 });
  const missing = await proxyPipecat(req(), 'offer', { fetchImpl: async () => Response.json({ error: { code: 'MISSING_CONFIG', missing: ['HUME_VOICE_ID', 'private-value'], message: 'raw-secret' } }, { status: 503 }) });
  assert.equal(missing.status, 503);
  assert.equal((await missing.json()).error.message, 'Missing variables: HUME_VOICE_ID');
  const busy = await proxyPipecat(req(), 'offer', { fetchImpl: async () => Response.json({ error: { code: 'SESSION_BUSY' } }, { status: 409 }) });
  assert.equal(busy.status, 409);
});

test('offline and malformed backend responses are actionable and sanitized', async () => {
  for (const fetchImpl of [async () => { throw new Error('private-value'); }, async () => new Response('private-value'), async () => Response.json({ sdp: 'incomplete' })]) {
    const response = await proxyPipecat(req(), 'offer', { fetchImpl });
    assert.equal(response.status, 503);
    const data = await response.json();
    assert.equal(data.error.code, 'BACKEND_UNAVAILABLE');
    assert.match(data.error.message, /npm run dev:pipecat/);
    assert.doesNotMatch(JSON.stringify(data), /private-value/);
  }
});

test('oversized and malformed browser payloads cannot reach the backend', async () => {
  for (const body of ['invalid json', '[]', JSON.stringify({ data: 'x'.repeat(128 * 1024) })]) {
    const response = await proxyPipecat(req('offer', { body }), 'offer', { fetchImpl: () => { throw new Error('must not fetch'); } });
    assert.equal(response.status, 400);
  }
});

test('Gradium configuration needs only its own keys, model and voice', () => {
  const env = { GENERALCOMPUTE_API_KEY: 'fixture-gc', GENERALCOMPUTE_MODEL: 'fixture-model', GRADIUM_API_KEY: 'fixture-gd', GRADIUM_VOICE_ID: 'fixture-voice' };
  assert.deepEqual(missingVariables('gradium', {}), Object.keys(env));
  const config = readConfig('gradium', env);
  assert.equal(config.baseURL, 'https://api.generalcompute.com/v1');
  assert.equal(config.region, 'auto');
  assert.equal(config.timeoutMs, 60000);
  assert.equal(config.gradiumVoiceId, 'fixture-voice');
  for (const bad of [
    { GENERALCOMPUTE_BASE_URL: 'https://key:private-value@example.com/v1' },
    { GENERALCOMPUTE_BASE_URL: 'http://localhost/v1' },
    { GENERALCOMPUTE_BASE_URL: 'https://example.com/v1?key=private-value' },
    { GRADIUM_REGION: 'private-value' },
  ]) assert.throws(() => readConfig('gradium', { ...env, ...bad }), error => !error.message.includes('private-value'));
});

test('Gradium proxy selects fixed routes and filters only Gradium configuration', async () => {
  for (const method of ['POST', 'PATCH']) {
    const response = await proxyPipecat(req('offer', { method, body: JSON.stringify({ type: 'offer', sdp: 'fixture', stack: 'pipecat', url: 'https://untrusted.example' }) }), 'offer', {
      stack: 'gradium', fetchImpl: async (url, options) => {
        assert.equal(url, 'http://127.0.0.1:7860/api/gradium/offer');
        assert.equal(options.headers['X-Pipecat-Proxy'], 'practice-web');
        return Response.json({ sdp: 'answer', type: 'answer', pc_id: 'gradium-1' });
      },
    });
    assert.equal(response.status, 200);
  }
  const response = await proxyPipecat(req('health'), 'health', {
    stack: 'gradium', fetchImpl: async url => {
      assert.equal(url, 'http://127.0.0.1:7860/gradium/health');
      return Response.json({ configured: false, missing: ['GRADIUM_API_KEY', 'HUME_SECRET_KEY', 'private-value'], activeSessions: 1 });
    },
  });
  assert.deepEqual(await response.json(), { status: 'ok', configured: false, missing: ['GRADIUM_API_KEY'], activeSessions: 1 });
  const missing = await proxyPipecat(req(), 'offer', { stack: 'gradium', fetchImpl: async () => Response.json({ error: { code: 'MISSING_CONFIG', missing: ['GENERALCOMPUTE_MODEL', 'private-value'] } }, { status: 503 }) });
  assert.equal((await missing.json()).error.message, 'Missing variables: GENERALCOMPUTE_MODEL');
});

test('Gradium signaling retains origin and payload restrictions and rejects unknown stacks', async () => {
  const fetchImpl = () => { throw new Error('must not fetch'); };
  const cross = await proxyPipecat(req('offer', { headers: { origin: 'https://untrusted.example' } }), 'offer', { stack: 'gradium', fetchImpl });
  assert.equal(cross.status, 403);
  const invalid = await proxyPipecat(req('offer', { body: 'not-json' }), 'offer', { stack: 'gradium', fetchImpl });
  assert.equal(invalid.status, 400);
  const unknown = await proxyPipecat(req(), 'offer', { stack: '__proto__', fetchImpl });
  assert.equal(unknown.status, 404);
});

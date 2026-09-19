import test from 'node:test';
import assert from 'node:assert/strict';
import { readConfig, missingVariables } from '../lib/config.mjs';
import { createHumeToken } from '../lib/hume-token.mjs';

const source = { HUME_API_KEY: 'fixture-api-value', HUME_SECRET_KEY: 'fixture-secret-value', HUME_CONFIG_ID: 'fixture-config', HUME_CONFIG_VERSION: '2' };
const request = (origin = 'http://localhost:3000') => new Request('http://localhost:3000/api/hume/token', { method: 'POST', headers: { origin } });

test('configuration validates only selected route and never reveals values', () => {
  assert.deepEqual(readConfig('fake', {}), {});
  assert.deepEqual(missingVariables('evi', { HUME_API_KEY: 'private-value' }), ['HUME_SECRET_KEY', 'HUME_CONFIG_ID']);
  assert.throws(() => readConfig('evi', { HUME_API_KEY: 'private-value' }), /^ConfigurationError: Missing variables: HUME_SECRET_KEY, HUME_CONFIG_ID$/);
  assert.throws(() => readConfig('unknown', {}), /Unknown route/);
  assert.throws(() => readConfig('sambanova', { SAMBANOVA_API_KEY: 'fixture', SAMBANOVA_MODEL: 'fixture', SAMBANOVA_BASE_URL: 'https://private:secret@example.com/' }), /HTTPS without credentials/);
  assert.throws(() => readConfig('evi', { ...source, PROVIDER_TIMEOUT_MS: '0' }), /PROVIDER_TIMEOUT_MS/);
  assert.equal(readConfig('evi', source).configVersion, 2);
  assert.throws(() => readConfig('evi', { ...source, HUME_CONFIG_VERSION: '9'.repeat(400) }), /safe nonnegative integer/);
});

test('token rejects absent/cross origin before any provider request', async () => {
  const fetchImpl = () => { throw new Error('must not call'); };
  assert.equal((await createHumeToken(request('https://other.example'), { source, fetchImpl })).status, 403);
  assert.equal((await createHumeToken(new Request('http://localhost:3000/api/hume/token', { method: 'POST' }), { source, fetchImpl })).status, 403);
});

test('missing config returns actionable names and no provider calls', async () => {
  const response = await createHumeToken(request(), { source: {}, fetchImpl: () => { throw new Error('must not call'); } });
  assert.equal(response.status, 503);
  assert.match((await response.json()).error, /HUME_API_KEY, HUME_SECRET_KEY, HUME_CONFIG_ID/);
  assert.match(response.headers.get('cache-control'), /no-store/);
});

test('local Host handles Next internal origin and hosted use requires a pinned HTTPS origin', async () => {
  const req = new Request('http://localhost:3100/api/hume/token', { method: 'POST', headers: { host: '127.0.0.1:3100', origin: 'http://127.0.0.1:3100' } });
  const response = await createHumeToken(req, { source: {} });
  assert.equal(response.status, 503);
  assert.match((await response.json()).error, /Missing variables/);
  const hosted = new Request('http://localhost:3000/api/hume/token', { method: 'POST', headers: { host: 'practice.example', origin: 'https://practice.example' } });
  assert.match((await (await createHumeToken(hosted, { source: {} })).json()).error, /APP_ORIGIN/);
  const pinned = await createHumeToken(hosted, { source: { APP_ORIGIN: 'https://practice.example' } });
  assert.match((await pinned.json()).error, /Missing variables/);
  const invalid = await createHumeToken(hosted, { source: { APP_ORIGIN: 'https://user:secret@practice.example' } });
  assert.equal((await invalid.json()).error, 'APP_ORIGIN must be a plain HTTPS origin.');
});

test('fresh access token is requested each time; only short-lived token/config reach browser', async () => {
  let calls = 0;
  const fetchImpl = async (url, options) => {
    assert.equal(url, 'https://api.hume.ai/oauth2-cc/token');
    assert.equal(options.cache, 'no-store');
    assert.equal(options.redirect, 'error');
    assert.equal(options.body, 'grant_type=client_credentials');
    assert.ok(options.signal);
    return Response.json({ access_token: `temporary-${++calls}` });
  };
  for (let n = 1; n <= 2; n++) {
    const response = await createHumeToken(request(), { source, fetchImpl });
    assert.deepEqual(await response.json(), { accessToken: `temporary-${n}`, configId: 'fixture-config', configVersion: 2 });
    assert.match(response.headers.get('cache-control'), /no-store/);
  }
});

test('provider auth, quota, malformed and transport errors are sanitized', async () => {
  for (const status of [401, 403, 429, 500]) {
    const response = await createHumeToken(request(), { source, fetchImpl: async () => new Response('fixture-secret-value', { status }) });
    const body = JSON.stringify(await response.json());
    assert.doesNotMatch(body, /fixture-secret-value/);
    assert.equal(response.status, status === 429 ? 429 : 502);
  }
  const broken = await createHumeToken(request(), { source, fetchImpl: async () => Response.json({ unexpected: 'private' }) });
  assert.equal(broken.status, 502);
  const offline = await createHumeToken(request(), { source, fetchImpl: async () => { throw new Error('fixture-secret-value'); } });
  assert.doesNotMatch(await offline.text(), /fixture-secret-value/);
});

test('provider timeout returns a bounded recoverable response', async () => {
  // Hold the event loop open because AbortSignal.timeout uses an unref timer.
  const hold = setTimeout(() => {}, 1000);
  try {
    const response = await createHumeToken(request(), { source: { ...source, PROVIDER_TIMEOUT_MS: '100' },
      fetchImpl: (_url, options) => new Promise((_, reject) => options.signal.addEventListener('abort', () => reject(options.signal.reason), { once: true })) });
    assert.equal(response.status, 502);
    assert.match((await response.json()).error, /timed out/);
  } finally { clearTimeout(hold); }
});

import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { setTimeout as sleep } from 'node:timers/promises';

const cwd = fileURLToPath(new URL('../', import.meta.url));
const origin = 'http://127.0.0.1:3100';
const child = spawn(process.execPath, ['node_modules/next/dist/bin/next', 'start', '--hostname', '127.0.0.1', '--port', '3100'], {
  cwd, stdio: ['ignore', 'pipe', 'pipe'],
  env: { ...process.env, HUME_API_KEY: '', HUME_SECRET_KEY: '', HUME_CONFIG_ID: '', SAMBANOVA_API_KEY: '', SAMBANOVA_MODEL: '', APP_ORIGIN: '', NEXT_TELEMETRY_DISABLED: '1' },
});
let started = false;
let launchError = false;
let output = '';
child.stdout.on('data', chunk => { output += chunk; if (output.includes('Ready in')) started = true; });
child.stderr.on('data', () => {}); // Never echo runtime logs that might contain secret values.
child.on('error', () => { launchError = true; });
try {
  for (let n = 0; n < 100 && !started && !launchError && child.exitCode === null; n++) await sleep(100);
  assert.ok(started && !launchError && child.exitCode === null, 'Test server failed to start. Ensure port 3100 is free and local listening is permitted.');
  const health = await fetch(`${origin}/api/health`, { signal: AbortSignal.timeout(5000) });
  assert.equal(health.status, 200);
  assert.deepEqual(await health.json(), { status: 'ok', practice: true, configured: { evi: false, sambanova: false } });
  assert.match(health.headers.get('cache-control'), /no-store/);
  const page = await fetch(origin, { signal: AbortSignal.timeout(5000) });
  assert.equal(page.status, 200);
  const html = await page.text();
  assert.match(html, /Voice AI/);
  assert.match(html, /Hume EVI/);
  assert.match(html, /Modular Pipecat/);
  assert.match(html, /Gradium \+ General Compute/);
  assert.equal(page.headers.get('permissions-policy'), 'microphone=(self), camera=()');
  const token = await fetch(`${origin}/api/hume/token`, { method: 'POST', headers: { Origin: origin }, signal: AbortSignal.timeout(5000) });
  assert.equal(token.status, 503);
  assert.deepEqual(await token.json(), { error: 'Missing variables: HUME_API_KEY, HUME_SECRET_KEY, HUME_CONFIG_ID' });
  assert.match(token.headers.get('cache-control'), /no-store, private/);
  const cross = await fetch(`${origin}/api/hume/token`, { method: 'POST', headers: { Origin: 'https://untrusted.example' }, signal: AbortSignal.timeout(5000) });
  assert.equal(cross.status, 403);
  const get = await fetch(`${origin}/api/hume/token`, { signal: AbortSignal.timeout(5000) });
  assert.equal(get.status, 405);
  for (const stack of ['pipecat', 'gradium']) {
    for (const method of ['POST', 'PATCH']) {
      const rejected = await fetch(`${origin}/api/${stack}/offer`, { method, headers: { Origin: 'https://untrusted.example', 'Content-Type': 'application/json' }, body: '{}', signal: AbortSignal.timeout(5000) });
      assert.equal(rejected.status, 403);
      assert.match(rejected.headers.get('cache-control'), /no-store/);
    }
    const invalidOffer = await fetch(`${origin}/api/${stack}/offer`, { method: 'POST', headers: { Origin: origin, 'Content-Type': 'application/json' }, body: 'not-json', signal: AbortSignal.timeout(5000) });
    assert.equal(invalidOffer.status, 400);
    const offerGet = await fetch(`${origin}/api/${stack}/offer`, { signal: AbortSignal.timeout(5000) });
    assert.equal(offerGet.status, 405);
  }
  console.log('PASS production HTTP: all three route choices rendered; health 200/no-store; missing EVI config 503; cross-origin token and both modular signaling routes 403; invalid signaling 400; GET token/offer 405; private no-store responses; microphone policy.');
  console.log('No provider requests. This is HTTP verification, not browser rendering or microphone/audio validation.');
} catch (error) {
  console.error(error instanceof assert.AssertionError ? error.message : 'HTTP verification failed: local connection or startup unavailable.');
  process.exitCode = 1;
} finally {
  child.kill('SIGTERM');
  for (let n = 0; n < 30 && child.exitCode === null && child.signalCode === null; n++) await sleep(100);
  if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
}

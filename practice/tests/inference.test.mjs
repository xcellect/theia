import test from 'node:test';
import assert from 'node:assert/strict';
import { readSSE } from '../lib/sse.mjs';
import { createSambaNovaProvider, createFakeProvider, createSanitizedWriter, sanitizedEndpoint, sanitizeText } from '../lib/sambanova.mjs';
import { createTaskBoard, runToolRoundTrip } from '../lib/sandbox-tools.mjs';

const config = { apiKey: 'fixture-secret-never-real', baseURL: 'https://example.invalid/v1', model: 'fixture-model', timeoutMs: 300 };
const messages = [{ role: 'user', content: 'Hello' }];
const encoder = new TextEncoder();
const collect = async (iterator) => { const result = []; for await (const item of iterator) result.push(item); return result; };
const bytes = (chunks) => new ReadableStream({ start(controller) { chunks.forEach((chunk) => controller.enqueue(typeof chunk === 'string' ? encoder.encode(chunk) : chunk)); controller.close(); } });
const event = (content) => `data: ${JSON.stringify({ choices: [{ delta: { content } }] })}\n\n`;
const response = (body) => new Response(body, { headers: { 'Content-Type': 'text/event-stream' } });
const providerWith = (fetchImpl, overrides = {}) => createSambaNovaProvider({ ...config, ...overrides }, { fetchImpl });
const code = (expected) => (error) => error.code === expected;

test('SSE parses every byte boundary, split UTF-8, CRLF, comments, and multiline data', async () => {
  const payload = encoder.encode(': ping\r\ndata: {"text":\r\ndata: "café"}\r\n\r\ndata: [DONE]\r\n\r\n');
  const results = await collect(readSSE(bytes([...payload].map((value) => new Uint8Array([value])))));
  assert.deepEqual(results, ['{"text":\n"café"}', '[DONE]']);
});

test('SSE supports CR-only line endings and discards an unterminated final event', async () => {
  assert.deepEqual(await collect(readSSE(bytes(['data: hello\r\rdata: incomplete']))), ['hello']);
});

test('SSE rejects an oversized unterminated event', async () => {
  await assert.rejects(() => collect(readSSE(bytes(['data: ', 'x'.repeat(65_536)]))), /size limit/);
});

test('non-streaming uses configured endpoint, model, secret header, and no redirect following', async () => {
  const provider = providerWith(async (url, options) => {
    assert.equal(url, 'https://example.invalid/v1/chat/completions');
    assert.equal(options.headers.Authorization, `Bearer ${config.apiKey}`);
    assert.equal(options.redirect, 'error');
    assert.deepEqual(JSON.parse(options.body), { model: config.model, messages, stream: false, max_tokens: 256 });
    return Response.json({ choices: [{ message: { role: 'assistant', content: 'Ready' } }] });
  });
  const result = await provider.complete(messages);
  assert.equal(result.text, 'Ready');
  assert.equal(result.demo, false);
  assert.ok(result.totalMs >= 0);
});

test('stream yields text before completion and ignores control/usage/empty events', async () => {
  let finish;
  let cancelled = false;
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode('data:\n\ndata: {"choices":[{"delta":{"role":"assistant","content":""}}]}\n\n'));
      controller.enqueue(encoder.encode(event('Hello')));
      finish = () => { controller.enqueue(encoder.encode(event(' world') + 'data: {"choices":[],"usage":{}}\n\ndata: [DONE]\n\n')); };
    },
    cancel() { cancelled = true; },
  });
  const stream = providerWith(async () => response(body)).stream(messages);
  const first = await stream.next();
  assert.equal(first.value.text, 'Hello');
  finish();
  const rest = await collect(stream);
  assert.equal(rest[0].text, ' world');
  assert.equal(rest[1].type, 'done');
  assert.equal(rest[1].firstTextMs, first.value.elapsedMs);
  assert.ok(rest[1].totalMs >= rest[1].firstTextMs);
  assert.equal(cancelled, true);
});

test('truncated, malformed, and non-SSE streams fail without exposing provider payloads', async () => {
  for (const payload of [event('partial'), 'data: {secret-token-broken-json}\n\n']) {
    await assert.rejects(() => collect(providerWith(async () => response(bytes([payload]))).stream(messages)), code('RESPONSE'));
  }
  await assert.rejects(() => collect(providerWith(async () => Response.json({ choices: [] })).stream(messages)), code('RESPONSE'));
});

test('empty completions and control-only streams fail', async () => {
  await assert.rejects(() => providerWith(async () => Response.json({ choices: [{ message: { role: 'assistant', content: '' } }] })).complete(messages), code('EMPTY'));
  await assert.rejects(() => collect(providerWith(async () => response(bytes(['data: {"choices":[]}\n\ndata: [DONE]\n\n']))).stream(messages)), code('EMPTY'));
});

test('provider HTTP failures are classified and hide body credentials', async () => {
  for (const [status, detail, expected] of [
    [401, 'invalid token', 'AUTH'], [403, 'no access', 'AUTH'], [404, 'not found', 'MODEL'],
    [400, 'model fixture-model does not exist', 'MODEL'], [429, 'rate limit', 'QUOTA'],
    [402, 'credit exhausted', 'QUOTA'], [400, 'invalid parameter', 'REQUEST'], [503, 'unavailable', 'TRANSPORT'],
  ]) {
    const provider = providerWith(async () => Response.json({ error: { message: `${detail}: ${config.apiKey}` } }, { status }));
    await assert.rejects(() => provider.complete(messages), (error) => {
      assert.equal(error.code, expected);
      assert.equal(error.status, status);
      assert.ok(!error.message.includes(config.apiKey));
      return true;
    });
  }
});

test('transport exception text is never exposed', async () => {
  const provider = providerWith(async () => { throw new Error(`url has ${config.apiKey}`); });
  await assert.rejects(() => provider.complete(messages), (error) => error.code === 'TRANSPORT' && !error.message.includes(config.apiKey));
});

test('timeouts bound fetch and body reads even if transport ignores cancellation', async () => {
  await assert.rejects(() => providerWith(() => new Promise(() => {}), { timeoutMs: 15 }).complete(messages), code('TIMEOUT'));
  await assert.rejects(() => providerWith(async () => new Response(new ReadableStream({})), { timeoutMs: 15 }).complete(messages), code('TIMEOUT'));
  await assert.rejects(() => collect(providerWith(async () => response(new ReadableStream({})), { timeoutMs: 15 }).stream(messages)), code('TIMEOUT'));
});

test('external cancellation works before a request and during stream read', async () => {
  const before = new AbortController();
  before.abort();
  let fetched = false;
  await assert.rejects(() => providerWith(async () => { fetched = true; }).complete(messages, { signal: before.signal }), code('CANCELLED'));
  assert.equal(fetched, false);
  const during = new AbortController();
  let cancelled = false;
  const provider = providerWith(async () => response(new ReadableStream({
    start(controller) { controller.enqueue(encoder.encode(event('first'))); },
    cancel() { cancelled = true; },
  })));
  const stream = provider.stream(messages, { signal: during.signal });
  assert.equal((await stream.next()).value.text, 'first');
  const pending = stream.next();
  during.abort();
  await assert.rejects(pending, code('CANCELLED'));
  assert.equal(cancelled, true);
});

test('consumer return aborts provider activity and cancels the response reader', async () => {
  let signal;
  let cancelled = false;
  const provider = providerWith(async (_url, options) => {
    signal = options.signal;
    return response(new ReadableStream({
      start(controller) { controller.enqueue(encoder.encode(event('first'))); },
      cancel() { cancelled = true; },
    }));
  });
  for await (const item of provider.stream(messages)) { assert.equal(item.text, 'first'); break; }
  assert.equal(cancelled, true);
  assert.equal(signal.aborted, true);
});

test('endpoint presentation and output sanitization hide credentials, controls, and split secrets', () => {
  assert.equal(sanitizedEndpoint('https://username:password@example.invalid/v1?api_key=secret#token'), 'https://example.invalid/v1');
  assert.equal(sanitizeText('hello\u001b secret-value', ['secret-value']), 'hello [REDACTED]');
  let output = '';
  const writer = createSanitizedWriter((text) => { output += text; }, ['secret-value']);
  writer.write('hello sec');
  assert.equal(output, 'hello ');
  writer.write('ret-value world');
  writer.end();
  assert.equal(output, 'hello [REDACTED] world');
});

test('provider refuses unsafe endpoint credentials, queries, plaintext, and malformed URLs', () => {
  for (const baseURL of ['http://example.invalid', 'https://user:secret@example.invalid', 'https://example.invalid?key=secret', 'secret-invalid-url']) {
    assert.throws(() => createSambaNovaProvider({ ...config, baseURL }), code('REQUEST'));
  }
});

test('fake provider is deterministic, visibly labeled, and streams through real parser', async () => {
  const provider = createFakeProvider({ chunkDelayMs: 0 });
  assert.equal(provider.demo, true);
  assert.equal((await provider.complete(messages)).text, 'DEMO DATA: Your inference practice environment is ready.');
  const events = await collect(provider.stream(messages));
  assert.equal(events.filter((item) => item.type === 'text').map((item) => item.text).join(''), 'DEMO DATA: Your inference practice environment is ready.');
  assert.ok(events.every((item) => item.demo));
  assert.equal(events.at(-1).type, 'done');
});

test('fake failure scenarios reproduce bounded error paths without a network request', async () => {
  for (const [scenario, expected] of [['auth', 'AUTH'], ['model', 'MODEL'], ['quota', 'QUOTA'], ['transport', 'TRANSPORT'], ['timeout', 'TIMEOUT']]) {
    await assert.rejects(() => createFakeProvider({ scenario, timeoutMs: 10 }).complete(messages), code(expected));
  }
});

test('tool validates schema, task, allowlist, JSON, and malicious extra fields without mutation', () => {
  const board = createTaskBoard();
  for (const args of ['bad json', 'null', '[]', '{}', JSON.stringify({ actionId: 'a', taskId: 'practice-task', status: 'erase' }), JSON.stringify({ actionId: 'a', taskId: 'practice-task', status: 'done', command: 'anything' })]) {
    assert.equal(board.execute('set_task_status', args).error.code, 'INVALID_ARGUMENTS');
  }
  assert.equal(board.execute('send_email', '{}').error.code, 'UNKNOWN_TOOL');
  assert.equal(board.execute('set_task_status', JSON.stringify({ actionId: 'a', taskId: 'unknown', status: 'done' })).error.code, 'UNKNOWN_TASK');
  assert.equal(board.snapshot()[0].status, 'todo');
});

test('same action is idempotent, conflicting IDs fail, and a new intent can undo the action', () => {
  const board = createTaskBoard();
  const args = { actionId: 'intent-1', taskId: 'practice-task', status: 'done' };
  const first = board.execute('set_task_status', JSON.stringify(args));
  assert.equal(first.changed, true);
  const repeated = board.execute('set_task_status', JSON.stringify({ status: 'done', taskId: 'practice-task', actionId: 'intent-1' }));
  assert.equal(repeated.changed, false);
  assert.equal(repeated.replayed, true);
  assert.equal(board.execute('set_task_status', JSON.stringify({ ...args, status: 'todo' })).error.code, 'ACTION_ID_CONFLICT');
  assert.equal(board.snapshot()[0].status, 'done');
  assert.equal(board.execute('set_task_status', JSON.stringify({ ...args, actionId: 'intent-2', status: 'todo' })).changed, true);
  assert.equal(board.snapshot()[0].status, 'todo');
  // A late retry of the original intent must not reapply it after a newer change.
  assert.equal(board.execute('set_task_status', JSON.stringify(args)).replayed, true);
  assert.equal(board.snapshot()[0].status, 'todo');
});

test('mutating a returned board/result cannot bypass validation or corrupt idempotency history', () => {
  const board = createTaskBoard();
  board.snapshot()[0].status = 'done';
  assert.equal(board.snapshot()[0].status, 'todo');
  const args = JSON.stringify({ actionId: 'a', taskId: 'practice-task', status: 'done' });
  board.execute('set_task_status', args).task.status = 'todo';
  assert.equal(board.execute('set_task_status', args).task.status, 'done');
});

test('tool round trip sends actual structured tool result and receives a second model response', async () => {
  const provider = createFakeProvider({ chunkDelayMs: 0 });
  let requests = 0;
  const wrapped = { ...provider, async complete(input, options) {
    requests++;
    if (requests === 2) {
      assert.equal(input.at(-1).role, 'tool');
      assert.equal(input.at(-1).tool_call_id, 'demo-call-1');
      assert.equal(JSON.parse(input.at(-1).content).task.status, 'done');
    }
    return provider.complete(input, options);
  } };
  const result = await runToolRoundTrip(wrapped);
  assert.equal(requests, 2);
  assert.equal(result.board[0].status, 'done');
  assert.match(result.text, /^DEMO DATA:/);
});

import { readSSE, withAbort } from './sse.mjs';

const messagesByCode = {
  AUTH: 'SambaNova rejected authentication. Check SAMBANOVA_API_KEY and endpoint access.',
  MODEL: 'The configured SambaNova model is unavailable. Confirm the exact SAMBANOVA_MODEL for this account and endpoint.',
  QUOTA: 'SambaNova quota or rate limit reached. Check account credits and limits before retrying.',
  REQUEST: 'SambaNova rejected the request. Check model capabilities and request parameters.',
  TRANSPORT: 'Could not complete the SambaNova connection. Check the endpoint and network.',
  TIMEOUT: 'SambaNova request exceeded its configured timeout.',
  CANCELLED: 'SambaNova request cancelled.',
  RESPONSE: 'SambaNova returned an invalid or incomplete response.',
  EMPTY: 'SambaNova returned no nonempty text.',
};

export class InferenceError extends Error {
  constructor(code, status) {
    super(messagesByCode[code] ?? messagesByCode.RESPONSE);
    this.name = 'InferenceError';
    this.code = code;
    if (status !== undefined) this.status = status;
  }
}

function httpError(status, payload) {
  // Inspect provider details for classification only; never return provider body text.
  const detail = JSON.stringify(payload ?? {}).toLowerCase();
  if (status === 401 || status === 403) return new InferenceError('AUTH', status);
  if (status === 402 || status === 429 || /quota|rate.limit|credit|insufficient/.test(detail)) return new InferenceError('QUOTA', status);
  if (status === 404 || /model.*(?:not.found|unavailable|invalid|not.exist|not.support)|(?:invalid|unknown).*model/.test(detail)) return new InferenceError('MODEL', status);
  return new InferenceError(status >= 500 ? 'TRANSPORT' : 'REQUEST', status);
}

function requestScope(timeoutMs, externalSignal) {
  const controller = new AbortController();
  let timedOut = false;
  const cancel = () => controller.abort();
  externalSignal?.addEventListener('abort', cancel, { once: true });
  if (externalSignal?.aborted) cancel();
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  return {
    signal: controller.signal,
    fail(error) {
      if (timedOut) return new InferenceError('TIMEOUT');
      if (controller.signal.aborted) return new InferenceError('CANCELLED');
      return error instanceof InferenceError ? error : new InferenceError('TRANSPORT');
    },
    close() { clearTimeout(timer); externalSignal?.removeEventListener('abort', cancel); controller.abort(); },
  };
}

async function readJSON(response, signal) {
  if (!response.body) throw new InferenceError('RESPONSE');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let output = '';
  let bytes = 0;
  try {
    while (true) {
      const { value, done } = await withAbort(reader.read(), signal);
      if (done) break;
      bytes += value.byteLength;
      if (bytes > 1_048_576) throw new InferenceError('RESPONSE');
      output += decoder.decode(value, { stream: true });
    }
    output += decoder.decode();
    try { return JSON.parse(output); } catch { throw new InferenceError('RESPONSE'); }
  } finally {
    reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export function sanitizedEndpoint(baseURL) {
  try {
    const url = new URL(baseURL);
    return `${url.protocol}//${url.host}${url.pathname.replace(/\/$/, '')}`;
  } catch { return '[invalid endpoint]'; }
}

export function sanitizeText(value, secrets = []) {
  let text = String(value);
  for (const secret of secrets.filter(Boolean).sort((a, b) => b.length - a.length)) text = text.split(secret).join('[REDACTED]');
  return text.replace(/[\x00-\x08\x0B-\x1F\x7F-\x9F]/g, '');
}

// Holds only suffixes that might begin a known secret, preserving incremental
// output while also redacting a credential split across adjacent text chunks.
export function createSanitizedWriter(write, secrets = []) {
  const values = [...new Set(secrets.filter(Boolean))].sort((a, b) => b.length - a.length);
  let pending = '';
  const flush = (final) => {
    let safe = '';
    while (pending) {
      const exact = values.find((secret) => pending.startsWith(secret));
      if (exact) { safe += '[REDACTED]'; pending = pending.slice(exact.length); continue; }
      if (!final && values.some((secret) => secret.startsWith(pending))) break;
      safe += pending[0];
      pending = pending.slice(1);
    }
    if (safe) write(sanitizeText(safe));
  };
  return { write(text) { pending += text; flush(false); }, end() { flush(true); } };
}

export function createSambaNovaProvider(config, { fetchImpl = globalThis.fetch } = {}) {
  const { apiKey, baseURL, model, timeoutMs = 30_000 } = config;
  if (!apiKey || !model) throw new InferenceError('REQUEST');
  let url;
  try { url = new URL(baseURL); } catch { throw new InferenceError('REQUEST'); }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) throw new InferenceError('REQUEST');
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0 || timeoutMs > 120_000) throw new InferenceError('REQUEST');
  const endpoint = `${url.href.replace(/\/$/, '')}/chat/completions`;
  const request = async (messages, options, stream, signal) => {
    signal.throwIfAborted();
    const body = { model, messages, stream, max_tokens: options.maxTokens ?? 256 };
    if (options.tools) body.tools = options.tools;
    if (options.toolChoice) body.tool_choice = options.toolChoice;
    const response = await withAbort(fetchImpl(endpoint, {
      method: 'POST', redirect: 'error', signal,
      headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json', Accept: stream ? 'text/event-stream' : 'application/json' },
      body: JSON.stringify(body),
    }), signal);
    if (!response.ok) {
      let payload;
      try { payload = await readJSON(response, signal); } catch (error) { if (signal.aborted) throw error; }
      throw httpError(response.status, payload);
    }
    return response;
  };
  return {
    name: 'sambanova', demo: false, model, endpoint: sanitizedEndpoint(baseURL),
    async complete(messages, options = {}) {
      const scope = requestScope(timeoutMs, options.signal);
      const start = performance.now();
      try {
        const response = await request(messages, options, false, scope.signal);
        const json = await readJSON(response, scope.signal);
        if (json.error) throw httpError(400, json.error);
        const message = json.choices?.[0]?.message;
        if (!message || message.role !== 'assistant') throw new InferenceError('RESPONSE');
        const text = typeof message.content === 'string' ? message.content : '';
        if (!text.trim() && !message.tool_calls?.length) throw new InferenceError('EMPTY');
        return { text, message, totalMs: performance.now() - start, demo: false };
      } catch (error) { throw scope.fail(error); } finally { scope.close(); }
    },
    async *stream(messages, options = {}) {
      const scope = requestScope(timeoutMs, options.signal);
      const start = performance.now();
      let firstTextMs = null;
      let textLength = 0;
      let terminated = false;
      try {
        const response = await request(messages, options, true, scope.signal);
        if (!response.headers.get('content-type')?.includes('text/event-stream')) throw new InferenceError('RESPONSE');
        for await (const data of readSSE(response.body, { signal: scope.signal })) {
          scope.signal.throwIfAborted();
          if (!data.trim()) continue;
          if (data.trim() === '[DONE]') { terminated = true; break; }
          let chunk;
          try { chunk = JSON.parse(data); } catch { throw new InferenceError('RESPONSE'); }
          if (chunk.error) throw httpError(400, chunk.error);
          const text = chunk.choices?.[0]?.delta?.content;
          if (typeof text !== 'string' || text.length === 0) continue;
          const elapsedMs = performance.now() - start;
          if (firstTextMs === null && text.trim()) firstTextMs = elapsedMs;
          textLength += text.length;
          if (textLength > 1_048_576) throw new InferenceError('RESPONSE');
          yield { type: 'text', text, elapsedMs, demo: false };
        }
        if (!terminated) throw new InferenceError('RESPONSE');
        if (firstTextMs === null) throw new InferenceError('EMPTY');
        yield { type: 'done', firstTextMs, totalMs: performance.now() - start, demo: false };
      } catch (error) { throw scope.fail(error); } finally { scope.close(); }
    },
  };
}

export function createFakeProvider({ scenario = 'success', chunkDelayMs = 25, timeoutMs = 1_000 } = {}) {
  if (!['success', 'auth', 'model', 'quota', 'transport', 'timeout'].includes(scenario)) throw new InferenceError('REQUEST');
  const fetchImpl = async (_url, options) => {
    if (scenario === 'transport') throw new Error('Simulated offline');
    if (scenario === 'timeout') return withAbort(new Promise(() => {}), options.signal);
    const status = { auth: 401, model: 404, quota: 429 }[scenario];
    if (status) return Response.json({ error: { code: scenario } }, { status });
    const request = JSON.parse(options.body);
    if (!request.stream) {
      const message = request.tools ? {
        role: 'assistant', content: null,
        tool_calls: [{ id: 'demo-call-1', type: 'function', function: { name: 'set_task_status', arguments: JSON.stringify({ actionId: 'smoke-action-1', taskId: 'practice-task', status: 'done' }) } }],
      } : { role: 'assistant', content: request.messages.some((message) => message.role === 'tool') ? 'DEMO DATA: The local practice task is done.' : 'DEMO DATA: Your inference practice environment is ready.' };
      return Response.json({ choices: [{ message }] });
    }
    const events = [
      ': keepalive\n\n',
      'data: {"choices":[{"delta":{"role":"assistant","content":""}}]}\n\n',
      ...['DEMO DATA: ', 'Your inference ', 'practice environment ', 'is ready.'].map((content) => `data: ${JSON.stringify({ choices: [{ delta: { content } }] })}\n\n`),
      'data: {"choices":[],"usage":{"completion_tokens":12}}\n\n',
      'data: [DONE]\n\n',
    ];
    let index = 0;
    let timer;
    let cancelled = false;
    let wake;
    return new Response(new ReadableStream({
      async pull(controller) {
        await new Promise((resolve) => { wake = resolve; timer = setTimeout(resolve, chunkDelayMs); });
        if (cancelled) return;
        if (options.signal.aborted) { controller.close(); return; }
        controller.enqueue(new TextEncoder().encode(events[index++]));
        if (index === events.length) controller.close();
      },
      cancel() { cancelled = true; clearTimeout(timer); wake?.(); },
    }), { headers: { 'Content-Type': 'text/event-stream' } });
  };
  const provider = createSambaNovaProvider({ apiKey: 'demo-local-only', baseURL: 'https://demo.invalid/v1', model: 'DEMO DATA', timeoutMs }, { fetchImpl });
  return {
    name: 'fake', demo: true, model: 'DEMO DATA', endpoint: 'local deterministic fake (no network)',
    async complete(messages, options) { return { ...await provider.complete(messages, options), demo: true }; },
    async *stream(messages, options) { for await (const event of provider.stream(messages, options)) yield { ...event, demo: true }; },
  };
}

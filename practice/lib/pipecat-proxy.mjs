// The Python server is deliberately local. Never accept a target URL from a browser.
const backend = 'http://127.0.0.1:7860';
const headers = { 'Cache-Control': 'no-store, private', 'Vary': 'Origin' };
const stacks = {
  pipecat: { health: '/health', offer: '/api/offer', required: ['DEEPGRAM_API_KEY', 'SAMBANOVA_API_KEY', 'SAMBANOVA_MODEL', 'HUME_API_KEY', 'HUME_VOICE_ID'] },
  gradium: { health: '/gradium/health', offer: '/api/gradium/offer', required: ['GENERALCOMPUTE_API_KEY', 'GENERALCOMPUTE_MODEL', 'GRADIUM_API_KEY', 'GRADIUM_VOICE_ID'] },
};
const limit = 128 * 1024;
const messages = {
  BACKEND_UNAVAILABLE: 'Start the Pipecat server with npm run dev:pipecat.',
  SESSION_BUSY: 'A Pipecat session is already running. End it before starting another.',
  INVALID_CONFIG: 'Check the Pipecat settings in practice/.env.local, then restart the Python server.',
  INVALID_REQUEST: 'The voice connection request was invalid. Refresh the page and try again.',
  CONNECTION_FAILED: 'Pipecat could not establish a voice connection. End the session and try again.',
};

function safeFailure(required, code, status, missing) {
  const safeMissing = Array.isArray(missing) ? required.filter(name => missing.includes(name)) : [];
  return Response.json({ error: {
    code, message: code === 'MISSING_CONFIG' ? `Missing variables: ${safeMissing.join(', ')}` : messages[code],
    ...(safeMissing.length ? { missing: safeMissing } : {}),
  } }, { status, headers });
}

async function readJson(stream) {
  if (!stream) throw new Error('Missing body');
  const reader = stream.getReader();
  let size = 0;
  const chunks = [];
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) throw new Error('Body too large');
      chunks.push(Buffer.from(value));
    }
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}

export async function proxyPipecat(request, path, { fetchImpl = fetch, stack = 'pipecat' } = {}) {
  // The route module chooses the stack. Browser payloads cannot choose a provider or target.
  if (!Object.hasOwn(stacks, stack)) return safeFailure([], 'INVALID_REQUEST', 404);
  const selected = stacks[stack];
  const required = selected.required;
  const failure = (code, status, missing) => safeFailure(required, code, status, missing);
  if (!['health', 'offer'].includes(path)) return failure('INVALID_REQUEST', 404);
  const url = new URL(request.url);
  let expected;
  try {
    expected = new URL(`${url.protocol}//${request.headers.get('host') || url.host}`);
    if (!['127.0.0.1', 'localhost', '[::1]'].includes(expected.hostname)) throw new Error();
  } catch { return failure('INVALID_REQUEST', 403); }
  const origin = request.headers.get('origin');
  if ((origin && origin !== expected.origin) || request.headers.get('sec-fetch-site') === 'cross-site' || (path === 'offer' && !origin)) {
    return failure('INVALID_REQUEST', 403);
  }
  const method = request.method;
  if ((path === 'health' && method !== 'GET') || (path === 'offer' && !['POST', 'PATCH'].includes(method))) return failure('INVALID_REQUEST', 405);
  let body;
  if (path === 'offer') {
    if (request.headers.get('content-type')?.split(';')[0].trim() !== 'application/json') return failure('INVALID_REQUEST', 415);
    try {
      const input = await readJson(request.body);
      if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error();
      body = JSON.stringify(input);
    } catch { return failure('INVALID_REQUEST', 400); }
  }
  try {
    const response = await fetchImpl(`${backend}${selected[path]}`, {
      method, headers: { 'Content-Type': 'application/json', 'X-Pipecat-Proxy': 'practice-web' },
      ...(body ? { body } : {}), cache: 'no-store', redirect: 'error',
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(path === 'health' ? 5000 : 25000)]),
    });
    const data = response.status === 204 ? {} : await readJson(response.body);
    if (!response.ok) {
      const code = data.error?.code;
      if (code === 'MISSING_CONFIG') return failure(code, 503, data.error.missing);
      if (code === 'SESSION_BUSY' || response.status === 409) return failure('SESSION_BUSY', 409);
      if (code === 'INVALID_CONFIG') return failure(code, 503);
      return failure('CONNECTION_FAILED', 502);
    }
    if (path === 'health') {
      if (typeof data.configured !== 'boolean' || !Array.isArray(data.missing)) throw new Error();
      return Response.json({ status: 'ok', configured: data.configured,
        missing: required.filter(name => data.missing.includes(name)),
        activeSessions: Number.isInteger(data.activeSessions) ? data.activeSessions : 0,
        ...(data.configError ? { configError: messages.INVALID_CONFIG } : {}),
      }, { headers });
    }
    if (method === 'PATCH') return Response.json({ status: 'ok' }, { headers });
    if (typeof data.sdp !== 'string' || data.type !== 'answer' || typeof data.pc_id !== 'string') throw new Error();
    return Response.json({ sdp: data.sdp, type: data.type, pc_id: data.pc_id }, { headers });
  } catch { return failure('BACKEND_UNAVAILABLE', 503); }
}

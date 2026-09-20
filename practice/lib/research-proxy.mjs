// Only this local process can be contacted. Browser input never chooses a host.
const backend = 'http://127.0.0.1:7860/research';
const noStore = { 'Cache-Control': 'no-store, private', Vary: 'Origin' };
const bodyLimit = 128 * 1024;
const responseLimit = 256 * 1024;
const workspaceResponseLimit = 4 * 1024 * 1024;
const idPattern = /^[A-Za-z0-9_-]{1,128}$/;
const knownSettings = [
  'TYPESAFE_API_KEY', 'TYPESAFE_MODEL', 'GENERALCOMPUTE_API_KEY',
  'GENERALCOMPUTE_MODEL', 'GENERALCOMPUTE_BASE_URL', 'GRADIUM_API_KEY',
  'GRADIUM_VOICE_ID', 'GRADIUM_REGION', 'PAPER2AGENT_ROOT', 'EXA_API_KEY',
];
const messages = {
  BACKEND_UNAVAILABLE: 'Start the research server with npm run dev:pipecat, then retry.',
  INVALID_REQUEST: 'The research request was invalid. Refresh the page and try again.',
  INVALID_CONFIG: 'Check the research settings in practice/.env.local and restart the Python server.',
  RUN_NOT_FOUND: 'This research run is no longer available. Submit your question again.',
  REPLAY_EXPIRED: 'This research stream has expired. Submit your question again.',
  SOURCE_NOT_FOUND: 'This source is no longer available for the selected run.',
  SESSION_NOT_FOUND: 'This conversation or voice session is no longer available. Start a new conversation.',
  SESSION_BUSY: 'Research or voice is active in this conversation. Stop it before continuing.',
  CONNECTION_FAILED: 'The voice connection could not be established. Try starting it again.',
  REQUEST_FAILED: 'The research server could not complete this request. Please retry.',
};

function missingSettings(value) {
  return Array.isArray(value) ? knownSettings.filter(name => value.includes(name)) : [];
}

function failure(code, status, missing) {
  const safeMissing = missingSettings(missing);
  return Response.json({ error: {
    code,
    message: code === 'MISSING_CONFIG'
      ? (safeMissing.length ? `Missing variables: ${safeMissing.join(', ')}` : messages.INVALID_CONFIG)
      : messages[code],
    ...(safeMissing.length ? { missing: safeMissing } : {}),
  } }, { status, headers: noStore });
}

function endpointFor(path) {
  const parts = Array.isArray(path) ? path : typeof path === 'string' ? path.split('/') : [];
  if (!parts.length || !parts.every(part => typeof part === 'string' && idPattern.test(part))) return null;
  const route = parts.join('/');
  if (route === 'health' || route === 'voice/health') return { route, kind: 'health', methods: ['GET'] };
  if (route === 'voice/offer') return { route, kind: 'offer', methods: ['POST', 'PATCH'] };
  if (route === 'context') return { route, kind: 'context', methods: ['POST'] };
  if (route === 'sessions') return { route, kind: 'workspace', methods: ['GET'] };
  if (parts[0] === 'sessions' && parts.length === 2) return { route, kind: 'workspace', methods: ['GET', 'DELETE'] };
  if (route === 'runs') return { route, kind: 'run', methods: ['POST'] };
  if (parts[0] === 'runs' && parts.length === 3 && parts[2] === 'events') return { route, kind: 'events', methods: ['GET'] };
  if (parts[0] === 'runs' && parts.length === 3 && parts[2] === 'cancel') return { route, kind: 'run', methods: ['POST'] };
  if (parts[0] === 'runs' && parts.length === 4 && parts[2] === 'sources') return { route, kind: 'source', methods: ['GET'] };
  return null;
}

async function readJson(stream, limit) {
  if (!stream) throw new Error('Missing body');
  const reader = stream.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) throw new Error('Body too large');
      chunks.push(Buffer.from(value));
    }
    const data = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('Expected an object');
    return data;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

function safeHealth(data) {
  if (typeof data.configured !== 'boolean' || !Array.isArray(data.missing)) throw new Error('Invalid health response');
  const result = { status: 'ok', configured: data.configured, missing: missingSettings(data.missing) };
  if (Number.isInteger(data.activeSessions) && data.activeSessions >= 0) result.activeSessions = data.activeSessions;
  if (data.configError) result.configError = messages.INVALID_CONFIG;
  for (const field of ['activeRunId', 'latestRunId', 'activeSessionId', 'latestSessionId']) {
    if (data[field] === null || (typeof data[field] === 'string' && idPattern.test(data[field]))) result[field] = data[field];
  }
  if (data.search && typeof data.search.configured === 'boolean') {
    result.search = { configured: data.search.configured, provider: 'Exa' };
  }
  if (data.paper2agent && typeof data.paper2agent.available === 'boolean' && data.paper2agent.mode === 'draft' && data.paper2agent.supported === 'arxiv') {
    result.paper2agent = { available: data.paper2agent.available, mode: 'draft', supported: 'arxiv' };
    if (Number.isInteger(data.paper2agent.maxPapers) && data.paper2agent.maxPapers >= 1 && data.paper2agent.maxPapers <= 8) result.paper2agent.maxPapers = data.paper2agent.maxPapers;
  }
  if (Array.isArray(data.sources)) result.sources = data.sources.slice(0, 30).map(source => {
    if (!source || typeof source !== 'object') throw new Error('Invalid source metadata');
    return Object.fromEntries(['id', 'title', 'kind', 'description'].filter(key => typeof source[key] === 'string').map(key => [key, source[key]]));
  });
  if (data.providers && typeof data.providers === 'object') result.providers = Object.fromEntries(
    ['routing', 'analysis', 'model'].filter(key => typeof data.providers[key] === 'string').map(key => [key, data.providers[key]]),
  );
  return result;
}

function safeSource(data) {
  if (typeof data.id !== 'string' || !idPattern.test(data.id) || typeof data.text !== 'string') throw new Error('Invalid source');
  const result = Object.fromEntries(['id', 'title', 'section', 'text', 'coverage', 'sha256']
    .filter(key => typeof data[key] === 'string').map(key => [key, data[key]]));
  for (const key of ['startLine', 'endLine']) if (Number.isInteger(data[key]) && data[key] >= 0) result[key] = data[key];
  if (typeof data.path === 'string' && !data.path.startsWith('/') && !data.path.includes('\\') && !data.path.split('/').includes('..')) result.path = data.path;
  if (typeof data.url === 'string') {
    try {
      const url = new URL(data.url);
      if (['https:', 'http:'].includes(url.protocol) && !url.username && !url.password) result.url = url.href;
    } catch { /* Optional original links must be ordinary public URLs. */ }
  }
  return result;
}

function fields(data, keys) {
  return Object.fromEntries(keys.filter(key => data && ['string', 'number', 'boolean'].includes(typeof data[key])).map(key => [key, data[key]]));
}

function safeWorkspace(data) {
  const run = item => fields(item, ['runId', 'question', 'status', 'createdAt', 'updatedAt', 'markdown', 'done', 'partial']);
  if (Array.isArray(data.sessions)) return { sessions: data.sessions.slice(0, 50).map(item => fields(item,
    ['sessionId', 'title', 'paperCount', 'latestRunId', 'status', 'createdAt', 'updatedAt'])) };
  if (typeof data.sessionId !== 'string' || !idPattern.test(data.sessionId) || !Array.isArray(data.papers) || !Array.isArray(data.runs)) throw new Error('Invalid workspace');
  return {
    sessionId: data.sessionId,
    summary: typeof data.summary === 'string' ? data.summary.slice(0, 3000) : '',
    runs: data.runs.slice(-20).map(run),
    messages: Array.isArray(data.messages) ? data.messages.slice(-40).map(item => fields(item, ['messageId', 'role', 'content', 'runId', 'status', 'createdAt'])) : [],
    totalRuns: Number.isSafeInteger(data.totalRuns) && data.totalRuns >= 0 ? data.totalRuns : data.runs.length,
    hasMore: data.hasMore === true,
    nextBefore: typeof data.nextBefore === 'string' && idPattern.test(data.nextBefore) ? data.nextBefore : null,
    papers: data.papers.slice(-50).map(paper => ({
      ...fields(paper, ['paperId', 'sourceId', 'title', 'url', 'coverage', 'status', 'version']),
      reports: Array.isArray(paper.reports) ? paper.reports.slice(-50).map(run) : [],
      jobs: Array.isArray(paper.jobs) ? paper.jobs.slice(-5).map(job => ({
        ...fields(job, ['jobId', 'paperId', 'runId', 'kind', 'state', 'reason', 'executed']),
        repository: fields(job.repository, ['status', 'url', 'commit', 'checkoutScope']),
        capabilities: {
          ...fields(job.capabilities, ['measuredAt', 'architecture', 'cpuCount', 'ramAvailableBytes', 'diskFreeBytes', 'cudaAvailable', 'mpsAvailable', 'isolatedExecutor']),
          gpu: Array.isArray(job.capabilities?.gpu) ? job.capabilities.gpu.map(gpu => fields(gpu, ['name', 'vramFreeBytes', 'vramTotalBytes'])) : [],
        },
        requirements: fields(job.requirements, ['runtime', 'cudaRequired', 'ramBytes', 'diskBytes', 'vramBytes', 'requirementsComplete']),
      })) : [],
    })),
  };
}

function safeResponse(data, kind, method) {
  if (kind === 'workspace' && method === 'DELETE') {
    if (data.status !== 'deleted' || typeof data.sessionId !== 'string' || !idPattern.test(data.sessionId)) throw new Error('Invalid deletion response');
    return { sessionId: data.sessionId, status: 'deleted' };
  }
  if (kind === 'workspace') return safeWorkspace(data);
  if (kind === 'health') return safeHealth(data);
  if (kind === 'source') return safeSource(data);
  if (kind === 'context') {
    if (data.status !== 'ok') throw new Error('Invalid context response');
    return { status: 'ok' };
  }
  if (kind === 'offer') {
    if (method === 'PATCH') return { status: 'ok' };
    if (typeof data.sdp !== 'string' || data.type !== 'answer' || typeof data.pc_id !== 'string') throw new Error('Invalid voice response');
    return { sdp: data.sdp, type: data.type, pc_id: data.pc_id };
  }
  if (typeof data.runId !== 'string' || !idPattern.test(data.runId)) throw new Error('Invalid run response');
  const result = { runId: data.runId };
  if (['queued', 'running', 'completed', 'cancelled', 'failed', 'partial', 'clarification'].includes(data.status)) result.status = data.status;
  return result;
}

// Pull one chunk at a time: events reach the browser immediately and downstream
// cancellation releases the Python stream rather than leaving a reader behind.
function forwardEvents(body, abortController) {
  const reader = body.getReader();
  let closed = false;
  return new ReadableStream({
    async pull(controller) {
      try {
        const { done, value } = await reader.read();
        if (closed) return;
        if (done) {
          closed = true;
          reader.releaseLock();
          controller.close();
        } else controller.enqueue(value);
      } catch {
        if (!closed) {
          closed = true;
          reader.releaseLock();
          abortController.abort();
          controller.error(new Error('Research event stream disconnected. Reconnect to continue.'));
        }
      }
    },
    async cancel(reason) {
      closed = true;
      abortController.abort();
      await reader.cancel(reason).catch(() => {});
      reader.releaseLock();
    },
  });
}

export async function proxyResearch(request, path, { fetchImpl = fetch } = {}) {
  const endpoint = endpointFor(path);
  if (!endpoint) return failure('INVALID_REQUEST', 404);
  let expected;
  try {
    const url = new URL(request.url);
    const host = request.headers.get('host') || url.host;
    expected = new URL(`${url.protocol}//${host}`);
    if (!['http:', 'https:'].includes(expected.protocol) || expected.host !== host ||
      !['127.0.0.1', 'localhost', '[::1]'].includes(expected.hostname)) throw new Error('Nonlocal host');
  } catch { return failure('INVALID_REQUEST', 403); }
  const origin = request.headers.get('origin');
  if ((origin && origin !== expected.origin) || request.headers.get('sec-fetch-site') === 'cross-site' ||
    (request.method !== 'GET' && !origin)) return failure('INVALID_REQUEST', 403);
  if (!endpoint.methods.includes(request.method)) return failure('INVALID_REQUEST', 405);

  let query = '';
  const before = new URL(request.url).searchParams.getAll('before');
  if (before.length) {
    if (request.method !== 'GET' || endpoint.kind !== 'workspace' || endpoint.route === 'sessions' ||
        before.length !== 1 || !idPattern.test(before[0])) return failure('INVALID_REQUEST', 400);
    query = `?before=${encodeURIComponent(before[0])}`;
  }

  let body;
  if (request.method !== 'GET' && (request.method !== 'DELETE' || request.body)) {
    if (request.headers.get('content-type')?.split(';')[0].trim() !== 'application/json') return failure('INVALID_REQUEST', 415);
    try { body = JSON.stringify(await readJson(request.body, bodyLimit)); }
    catch { return failure('INVALID_REQUEST', 400); }
  }
  const headers = { 'Content-Type': 'application/json', 'X-Pipecat-Proxy': 'practice-web' };
  if (endpoint.kind === 'events') {
    headers.Accept = 'text/event-stream';
    const lastEventId = request.headers.get('last-event-id');
    if (lastEventId !== null) {
      if (!/^\d{1,10}$/.test(lastEventId)) return failure('INVALID_REQUEST', 400);
      headers['Last-Event-ID'] = lastEventId;
    }
  }
  const disconnected = new AbortController();
  try {
    const response = await fetchImpl(`${backend}/${endpoint.route}${query}`, {
      method: request.method, headers, ...(body ? { body } : {}), cache: 'no-store', redirect: 'error',
      signal: AbortSignal.any([request.signal, disconnected.signal,
        AbortSignal.timeout(endpoint.kind === 'events' ? 390000 : endpoint.kind === 'health' ? 5000 : 25000)]),
    });
    if (response.ok && endpoint.kind === 'events') {
      if (!response.body || !response.headers.get('content-type')?.startsWith('text/event-stream')) throw new Error('Invalid event stream');
      return new Response(forwardEvents(response.body, disconnected), { status: response.status, headers: {
        ...noStore, 'Content-Type': 'text/event-stream; charset=utf-8', 'X-Accel-Buffering': 'no',
      } });
    }
    const data = response.status === 204 ? {} : await readJson(response.body, endpoint.kind === 'workspace' ? workspaceResponseLimit : responseLimit);
    if (!response.ok) {
      const code = data.error?.code;
      const safeCode = code === 'MISSING_CONFIG' || Object.hasOwn(messages, code) ? code : 'REQUEST_FAILED';
      return failure(safeCode, response.status >= 400 && response.status <= 599 ? response.status : 502, data.error?.missing);
    }
    return Response.json(safeResponse(data, endpoint.kind, request.method), {
      status: response.status === 204 ? 200 : response.status, headers: noStore,
    });
  } catch {
    disconnected.abort();
    return failure('BACKEND_UNAVAILABLE', 503);
  }
}

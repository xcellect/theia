// Explicit live check: starts one real Jev + General Compute research run.
// Deliberately prints aggregate results only, never source text or provider errors.
import { pathToFileURL } from 'node:url';
import { readSSE } from '../lib/sse.mjs';

export class SmokeFailure extends Error {}
const question = 'How does Paper2Agent turn a paper and its code into an agent, and what does it actually verify?';

export function localBase(value) {
  let url;
  try { url = new URL(value); } catch { throw new SmokeFailure('Use a valid local --base-url.'); }
  if (!['http:', 'https:'].includes(url.protocol) || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) ||
    url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new SmokeFailure('--base-url must be a loopback origin without a path or credentials.');
  }
  return url.origin;
}

export function verifyReport(markdown, runId, sourceIds) {
  if (typeof markdown !== 'string' || !markdown.trim()) throw new SmokeFailure('The final report was empty.');
  for (const heading of ['Answer', 'Evidence and analysis', 'Limitations and open questions', 'Sources analyzed']) {
    if (!new RegExp(`^##\\s+${heading}\\s*$`, 'mi').test(markdown)) throw new SmokeFailure(`The final report is missing its ${heading} section.`);
  }
  const body = markdown.split(/^##\s+Sources analyzed\s*$/mi)[0];
  const citations = [...body.matchAll(/\[(S\d+)([^\]\n]*)\](?:\(([^)\n]*)\))?/g)];
  if (!citations.length) throw new SmokeFailure('The report body has no source citations.');
  for (const [, id, extra, href] of citations) {
    if (!sourceIds.has(id) || extra || href !== `/api/research/runs/${runId}/sources/${id}`) {
      throw new SmokeFailure('The report contains an unresolved source citation or an unverified citation location.');
    }
  }
  if (/unverified source reference|no resolvable source citations/i.test(markdown)) throw new SmokeFailure('The report failed its citation check.');
  return citations.length;
}

export async function runResearchSmoke({ baseUrl = 'http://127.0.0.1:3000', fetchImpl = fetch, signal } = {}) {
  const base = localBase(baseUrl);
  const deadline = AbortSignal.any([...(signal ? [signal] : []), AbortSignal.timeout(110_000)]);
  const headers = { Origin: base, 'Content-Type': 'application/json' };
  const started = performance.now();
  let runId;
  let terminal = false;
  try {
    const healthResponse = await fetchImpl(`${base}/api/research/health`, {
      signal: AbortSignal.any([deadline, AbortSignal.timeout(10_000)]), cache: 'no-store', redirect: 'error',
    });
    if (!healthResponse.ok) throw new SmokeFailure('The local research health endpoint is unavailable. Start both servers.');
    const health = await healthResponse.json();
    if (!health.configured) throw new SmokeFailure('Research is not configured. Check provider settings and the prepared source package in the web app.');
    if (health.activeRunId) throw new SmokeFailure('An existing research run is active. Finish it before running this check.');

    const created = await fetchImpl(`${base}/api/research/runs`, {
      method: 'POST', headers, body: JSON.stringify({ clientRequestId: crypto.randomUUID(), question,
        sessionId: `smoke-${crypto.randomUUID()}`, searchEnabled: false, previousRunId: null,
        sourceIds: ['paper2agent-paper', 'paper2agent-code'] }),
      signal: AbortSignal.any([deadline, AbortSignal.timeout(15_000)]), redirect: 'error',
    });
    if (created.status !== 202) throw new SmokeFailure('The server did not accept the live research run. Check setup in the web app.');
    const accepted = await created.json();
    if (typeof accepted.runId !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(accepted.runId)) throw new SmokeFailure('The server returned an invalid run identifier.');
    runId = accepted.runId;

    const streamed = await fetchImpl(`${base}/api/research/runs/${runId}/events`, { signal: deadline, cache: 'no-store', redirect: 'error' });
    if (!streamed.ok || !streamed.headers.get('content-type')?.startsWith('text/event-stream')) throw new SmokeFailure('The research event stream was unavailable.');
    const sourceIds = new Set();
    const agents = new Set();
    let routing = false;
    let report = '';
    let partial = false;
    let lastSeq = 0;
    let firstFindingSeconds = null;
    for await (const data of readSSE(streamed.body, { signal: deadline })) {
      let event;
      try { event = JSON.parse(data); } catch { throw new SmokeFailure('The research stream contained invalid JSON.'); }
      if (event.runId !== runId || !Number.isSafeInteger(event.seq) || event.seq < 1) throw new SmokeFailure('The research event envelope was invalid.');
      if (event.seq <= lastSeq) continue;
      lastSeq = event.seq;
      const payload = event.payload ?? {};
      if (event.type === 'routing.completed') routing = typeof payload.answers?.intent?.choice === 'string';
      if (event.type === 'source.read' && /^S\d+$/.test(payload.source?.id)) sourceIds.add(payload.source.id);
      if (event.type === 'agent.delta' && typeof payload.text === 'string' && payload.text.trim() && firstFindingSeconds === null) firstFindingSeconds = (performance.now() - started) / 1000;
      if (event.type === 'agent.completed' && ['evidence', 'critic'].includes(payload.agent) && typeof payload.text === 'string' && payload.text.trim()) agents.add(payload.agent);
      if (event.type === 'agent.failed') partial = true;
      if (event.type === 'report.completed') { report = payload.markdown; partial ||= Boolean(payload.partial); }
      if (event.type === 'run.failed' || event.type === 'run.cancelled') {
        terminal = true;
        throw new SmokeFailure(event.type === 'run.failed' ? 'The live research run failed. Inspect its status in the web app.' : 'The live research run was cancelled.');
      }
      if (event.type === 'run.completed') {
        terminal = true;
        partial ||= Boolean(payload.partial);
        if (payload.status !== 'completed') throw new SmokeFailure('The run ended without a completed research report.');
        break;
      }
    }
    if (!terminal || !routing || agents.size !== 2 || !sourceIds.size || partial) throw new SmokeFailure('The run did not complete real routing, both specialists, and a complete sourced report.');
    const citations = verifyReport(report, runId, sourceIds);
    return { result: 'PASS', routingCompleted: routing, completedAgents: agents.size, sourceExcerpts: sourceIds.size,
      reportCitations: citations, reportCharacters: report.length,
      firstFindingSeconds: firstFindingSeconds === null ? null : Number(firstFindingSeconds.toFixed(2)),
      totalSeconds: Number(((performance.now() - started) / 1000).toFixed(2)),
      scope: 'Live service and citation-link checks; scientific claims still require manual source review.' };
  } finally {
    if (runId && !terminal) {
      await fetchImpl(`${base}/api/research/runs/${runId}/cancel`, {
        method: 'POST', headers, body: '{}', signal: AbortSignal.timeout(5000), redirect: 'error',
      }).catch(() => {});
    }
  }
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length === 1 && args[0] === '--help') {
    console.log('Usage: node scripts/research-smoke.mjs [--base-url http://127.0.0.1:3000]\nStarts one live Jev + General Compute research run; prints aggregate checks only.');
    return;
  }
  if (args.length && (args.length !== 2 || args[0] !== '--base-url')) throw new SmokeFailure('Usage: node scripts/research-smoke.mjs [--base-url http://127.0.0.1:3000]');
  const stop = new AbortController();
  const interrupt = () => stop.abort();
  process.once('SIGINT', interrupt);
  try {
    console.log(JSON.stringify(await runResearchSmoke({ baseUrl: args[1], signal: stop.signal }), null, 2));
  } finally { process.removeListener('SIGINT', interrupt); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => {
    console.error(`FAIL: ${error instanceof SmokeFailure ? error.message : 'The local research request timed out, disconnected, or returned an invalid response. Check the web app and retry.'}`);
    process.exitCode = 1;
  });
}

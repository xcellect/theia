import { loadPracticeEnv } from '../lib/env.mjs';
loadPracticeEnv();
const targets = ['https://api.hume.ai', 'https://api.sambanova.ai', 'https://api.generalcompute.com', 'https://api.gradium.ai', 'https://registry.npmjs.org', 'https://pypi.org'];
if (process.env.DEPLOYMENT_URL) {
  try {
    const url = new URL(process.env.DEPLOYMENT_URL);
    if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) throw new Error();
    targets.push(url.origin);
  } catch { console.error('Invalid DEPLOYMENT_URL: use a plain HTTPS URL.'); process.exit(1); }
}
if (process.env.SAMBANOVA_BASE_URL) {
  try {
    const url = new URL(process.env.SAMBANOVA_BASE_URL);
    if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) throw new Error();
    if (!targets.includes(url.origin)) targets.push(url.origin);
  } catch { console.error('Invalid SAMBANOVA_BASE_URL: use a plain HTTPS URL.'); process.exit(1); }
}
await Promise.all(targets.map(async url => {
  try {
    const response = await fetch(url, { method: 'HEAD', redirect: 'manual', signal: AbortSignal.timeout(10000) });
    console.log(`REACHABLE ${new URL(url).hostname}: HTTP ${response.status} (connectivity only, not authentication)`);
  } catch {
    console.log(`BLOCKED ${new URL(url).hostname}: DNS, TLS, network, or timeout failure`);
    process.exitCode = 1;
  }
}));
if (!process.env.DEPLOYMENT_URL) console.log('BLOCKED intended host: DEPLOYMENT_URL is not configured; no host selected.');

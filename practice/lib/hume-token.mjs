import { ConfigurationError, readConfig } from './config.mjs';

const headers = { 'Cache-Control': 'no-store, private', 'Pragma': 'no-cache', 'Vary': 'Origin' };

export async function createHumeToken(request, { source = process.env, fetchImpl = fetch } = {}) {
  // This is a local practice endpoint. An authorized host must protect the entire app.
  // Same-origin checks prevent cross-site use, but are not deployment authentication.
  const origin = request.headers.get('origin');
  const internal = new URL(request.url);
  // Next.js may use localhost internally for a request sent to 127.0.0.1.
  // Use the incoming Host for local practice; a hosted app must pin APP_ORIGIN.
  let expectedOrigin;
  try {
    if (source.APP_ORIGIN) {
      const configured = new URL(source.APP_ORIGIN);
      if (configured.protocol !== 'https:' || configured.username || configured.password || configured.search || configured.hash || configured.pathname !== '/') throw new Error();
      expectedOrigin = configured.origin;
    } else {
      const local = new URL(`${internal.protocol}//${request.headers.get('host') || internal.host}`);
      if (!['127.0.0.1', 'localhost', '[::1]'].includes(local.hostname)) {
        return Response.json({ error: 'Set APP_ORIGIN to the authorized HTTPS app origin before hosted use.' }, { status: 503, headers });
      }
      expectedOrigin = local.origin;
    }
  } catch {
    return Response.json({ error: 'APP_ORIGIN must be a plain HTTPS origin.' }, { status: 503, headers });
  }
  if (!origin || origin !== expectedOrigin || request.headers.get('sec-fetch-site') === 'cross-site') {
    return Response.json({ error: 'Start voice from this app’s own page.' }, { status: 403, headers });
  }
  let config;
  try { config = readConfig('evi', source); }
  catch (error) {
    return Response.json({ error: error instanceof ConfigurationError ? error.message : 'Voice configuration is unavailable.' }, { status: 503, headers });
  }
  try {
    const credentials = Buffer.from(`${config.apiKey}:${config.secretKey}`).toString('base64');
    const response = await fetchImpl('https://api.hume.ai/oauth2-cc/token', {
      method: 'POST',
      headers: { Authorization: `Basic ${credentials}`, 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'grant_type=client_credentials',
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(config.timeoutMs)]),
      cache: 'no-store', redirect: 'error',
    });
    if (!response.ok) {
      const error = response.status === 401 || response.status === 403
        ? 'Hume rejected the credentials. Check HUME_API_KEY and HUME_SECRET_KEY on the server.'
        : response.status === 429
          ? 'Hume rate or quota limit reached. Check account access before retrying.'
          : 'Hume token service is unavailable. Try Start again after checking the connection.';
      return Response.json({ error }, { status: response.status === 429 ? 429 : 502, headers });
    }
    const data = await response.json();
    if (typeof data.access_token !== 'string' || !data.access_token.trim()) throw new Error('Invalid token response');
    return Response.json({ accessToken: data.access_token, configId: config.configId,
      ...(config.configVersion !== undefined ? { configVersion: config.configVersion } : {}) }, { headers });
  } catch {
    return Response.json({ error: 'Voice authentication timed out, was cancelled, or lost its connection. Check the network and try Start again.' }, { status: 502, headers });
  }
}

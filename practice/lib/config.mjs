const required = {
  evi: ['HUME_API_KEY', 'HUME_SECRET_KEY', 'HUME_CONFIG_ID'],
  sambanova: ['SAMBANOVA_API_KEY', 'SAMBANOVA_MODEL'],
  pipecat: ['DEEPGRAM_API_KEY', 'SAMBANOVA_API_KEY', 'SAMBANOVA_MODEL', 'HUME_API_KEY', 'HUME_VOICE_ID'],
  gradium: ['GENERALCOMPUTE_API_KEY', 'GENERALCOMPUTE_MODEL', 'GRADIUM_API_KEY', 'GRADIUM_VOICE_ID'],
  fake: [],
};

export class ConfigurationError extends Error {
  constructor(message) { super(message); this.name = 'ConfigurationError'; }
}

export function missingVariables(route, source = process.env) {
  if (!Object.hasOwn(required, route)) throw new ConfigurationError('Unknown route. Choose evi, sambanova, pipecat, gradium, or fake.');
  return required[route].filter(name => !source[name]?.trim());
}

export function readConfig(route, source = process.env) {
  const missing = missingVariables(route, source);
  if (missing.length) throw new ConfigurationError(`Missing variables: ${missing.join(', ')}`);
  if (route === 'fake') return {};
  const timeoutMs = Number(source.PROVIDER_TIMEOUT_MS || (route === 'gradium' ? 60000 : 30000));
  if (!Number.isInteger(timeoutMs) || timeoutMs < 100 || timeoutMs > 120000) {
    throw new ConfigurationError('PROVIDER_TIMEOUT_MS must be an integer between 100 and 120000.');
  }
  if (route === 'evi') {
    const version = source.HUME_CONFIG_VERSION?.trim();
    if (version && (!/^\d+$/.test(version) || !Number.isSafeInteger(Number(version)))) throw new ConfigurationError('HUME_CONFIG_VERSION must be a safe nonnegative integer.');
    return { apiKey: source.HUME_API_KEY.trim(), secretKey: source.HUME_SECRET_KEY.trim(),
      configId: source.HUME_CONFIG_ID.trim(), ...(version ? { configVersion: Number(version) } : {}), timeoutMs };
  }
  if (route === 'pipecat') {
    return { ...readConfig('sambanova', source), deepgramApiKey: source.DEEPGRAM_API_KEY.trim(),
      humeApiKey: source.HUME_API_KEY.trim(), humeVoiceId: source.HUME_VOICE_ID.trim() };
  }
  if (route === 'gradium') {
    let url;
    const raw = source.GENERALCOMPUTE_BASE_URL?.trim() || 'https://api.generalcompute.com/v1';
    try { url = new URL(raw); }
    catch { throw new ConfigurationError('GENERALCOMPUTE_BASE_URL must be a valid HTTPS URL.'); }
    if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || /\s/.test(raw)) {
      throw new ConfigurationError('GENERALCOMPUTE_BASE_URL must use HTTPS without credentials, query, or fragment.');
    }
    const region = source.GRADIUM_REGION?.trim().toLowerCase() || 'auto';
    if (!['auto', 'us', 'eu'].includes(region)) throw new ConfigurationError('GRADIUM_REGION must be auto, us, or eu.');
    return { apiKey: source.GENERALCOMPUTE_API_KEY.trim(), baseURL: url.href.replace(/\/$/, ''),
      model: source.GENERALCOMPUTE_MODEL.trim(), gradiumApiKey: source.GRADIUM_API_KEY.trim(),
      gradiumVoiceId: source.GRADIUM_VOICE_ID.trim(), region, timeoutMs };
  }
  let url;
  try { url = new URL(source.SAMBANOVA_BASE_URL?.trim() || 'https://api.sambanova.ai/v1'); }
  catch { throw new ConfigurationError('SAMBANOVA_BASE_URL must be a valid HTTPS URL.'); }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) {
    throw new ConfigurationError('SAMBANOVA_BASE_URL must use HTTPS without credentials, query, or fragment.');
  }
  return { apiKey: source.SAMBANOVA_API_KEY.trim(), baseURL: url.href.replace(/\/$/, ''), model: source.SAMBANOVA_MODEL.trim(), timeoutMs };
}

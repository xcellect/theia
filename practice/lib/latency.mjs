export function summarizeLatency(data) {
  if (!data || !Array.isArray(data.turns) || !data.route || !data.model || !data.network || !data.measurement) {
    throw new Error('Record route, model, network, measurement, and a turns array.');
  }
  if (!['audio', 'transcript-proxy'].includes(data.measurement)) throw new Error('measurement must be audio or transcript-proxy.');
  if (!data.turns.length) throw new Error('No observed turns recorded. Do not replace live measurements with invented samples.');
  const delays = data.turns.map(turn => {
    const start = turn.userSpeechEndMs;
    const end = data.measurement === 'audio' ? turn.assistantAudioStartMs : turn.assistantTranscriptMs;
    if (![start, end].every(Number.isFinite) || end < start || start < 0) throw new Error('Each turn needs ordered finite timestamps from one aligned clock.');
    return end - start;
  }).sort((a, b) => a - b);
  const n = delays.length;
  return { measurement: data.measurement === 'audio' ? 'speech-to-audible-playback' : 'transcript proxy; NOT speech-to-speech',
    count: n, medianMs: n % 2 ? delays[(n - 1) / 2] : (delays[n / 2 - 1] + delays[n / 2]) / 2,
    slowestMs: delays[n - 1], tenTurnSampleComplete: n >= 10 };
}

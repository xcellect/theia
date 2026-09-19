import test from 'node:test';
import assert from 'node:assert/strict';
import { summarizeLatency } from '../lib/latency.mjs';
const meta = { route: 'fixture', model: 'fixture', network: 'fixture', measurement: 'audio' };
test('latency median handles even samples and names an incomplete sample', () => {
  const result = summarizeLatency({ ...meta, turns: [{ userSpeechEndMs: 0, assistantAudioStartMs: 3000 }, { userSpeechEndMs: 5000, assistantAudioStartMs: 6000 }] });
  assert.equal(result.medianMs, 2000); assert.equal(result.slowestMs, 3000);
  assert.equal(result.tenTurnSampleComplete, false);
});
test('latency rejects absent and negative measurements, labels transcript proxy', () => {
  assert.throws(() => summarizeLatency({ ...meta, turns: [] }), /No observed turns/);
  assert.throws(() => summarizeLatency({ ...meta, turns: [{ userSpeechEndMs: 10, assistantAudioStartMs: 5 }] }), /ordered finite/);
  const result = summarizeLatency({ ...meta, measurement: 'transcript-proxy', turns: [{ userSpeechEndMs: 0, assistantTranscriptMs: 1 }] });
  assert.match(result.measurement, /NOT speech-to-speech/);
});

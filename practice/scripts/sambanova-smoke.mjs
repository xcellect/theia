import { loadPracticeEnv } from '../lib/env.mjs';
import { readConfig } from '../lib/config.mjs';
import { createSambaNovaProvider, createFakeProvider, createSanitizedWriter, sanitizeText, InferenceError } from '../lib/sambanova.mjs';
import { runToolRoundTrip } from '../lib/sandbox-tools.mjs';

loadPracticeEnv();
const args = process.argv.slice(2);
const controller = new AbortController();
const cancel = () => controller.abort();
process.once('SIGINT', cancel);
const secrets = Object.entries(process.env).filter(([name]) => /(?:KEY|SECRET|TOKEN)$/.test(name)).map(([, value]) => value).filter(Boolean);
const print = (value) => console.log(sanitizeText(value, secrets));

try {
  if (args.some((arg) => !['--fake', '--tools'].includes(arg))) throw new Error('Usage: npm run smoke:sambanova -- [--tools], or npm run smoke:fake -- [--tools].');
  const fake = args.includes('--fake');
  const config = readConfig(fake ? 'fake' : 'sambanova');
  const provider = fake ? createFakeProvider() : createSambaNovaProvider(config);
  print(`Provider: ${fake ? 'DEMO DATA — deterministic fake; no provider request' : 'SambaNova — REAL REQUEST'}`);
  print(`Endpoint: ${provider.endpoint}`);
  print(`Model: ${provider.model}`);
  const messages = [{ role: 'user', content: 'Reply with one short sentence confirming this inference smoke test works.' }];
  const nonstream = await provider.complete(messages, { signal: controller.signal });
  print(`Non-streaming output: ${nonstream.text}`);
  print(`Non-streaming total: ${nonstream.totalMs.toFixed(1)} ms`);
  process.stdout.write('Streaming output: ');
  const writer = createSanitizedWriter((text) => process.stdout.write(text), secrets);
  let summary;
  try {
    for await (const event of provider.stream(messages, { signal: controller.signal })) {
      if (event.type === 'text') writer.write(event.text);
      else summary = event;
    }
  } finally { writer.end(); process.stdout.write('\n'); }
  print(`First nonempty text: ${summary.firstTextMs.toFixed(1)} ms`);
  print(`Streaming total: ${summary.totalMs.toFixed(1)} ms`);
  if (args.includes('--tools')) {
    const roundTrip = await runToolRoundTrip(provider, { signal: controller.signal });
    print(`Tool result (local tutorial only): ${JSON.stringify(roundTrip.result)}`);
    print(`Tool round-trip response: ${roundTrip.text}`);
  }
  print(`PASS (${fake ? 'DEMO DATA only; does not prove provider access' : 'configured SambaNova endpoint'})`);
} catch (error) {
  // Config errors contain variable names only. Provider failures use our fixed text.
  print(`FAIL: ${error instanceof InferenceError ? `${error.code}: ` : ''}${error.message}`);
  process.exitCode = controller.signal.aborted ? 130 : 1;
} finally {
  process.removeListener('SIGINT', cancel);
}

import { readFile } from 'node:fs/promises';
import { summarizeLatency } from '../lib/latency.mjs';
try {
  if (!process.argv[2]) throw new Error('Usage: npm run measure:latency -- path/to/observed-turns.json');
  const data = JSON.parse(await readFile(process.argv[2], 'utf8'));
  console.log(JSON.stringify({ route: data.route, model: data.model, network: data.network, ...summarizeLatency(data) }, null, 2));
} catch (error) { console.error(error instanceof SyntaxError ? 'Invalid measurement JSON.' : error.message); process.exitCode = 1; }

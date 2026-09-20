import { readFile, readdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { loadPracticeEnv } from '../lib/env.mjs';
loadPracticeEnv();
const root = fileURLToPath(new URL('../../', import.meta.url));
const keys = ['HUME_API_KEY', 'HUME_SECRET_KEY', 'SAMBANOVA_API_KEY', 'DEEPGRAM_API_KEY', 'GENERALCOMPUTE_API_KEY', 'GRADIUM_API_KEY', 'TYPESAFE_API_KEY', 'EXA_API_KEY', 'CLM_AUTH_SECRET'];
const secrets = keys.map(name => process.env[name]).filter(value => value && value.length >= 8);
const skip = new Set(['node_modules', '.venv', '.cache', '.git', 'local', '.next']);
let files = 0;
let failed = false;
async function scan(dir, bundle = false) {
  let entries;
  try { entries = await readdir(dir, { withFileTypes: true }); }
  catch (error) { if (error.code === 'ENOENT' && bundle) return; throw error; }
  for (const entry of entries) {
    if (entry.isSymbolicLink()) continue;
    const filename = path.join(dir, entry.name);
    if (entry.isDirectory()) { if (!skip.has(entry.name)) await scan(filename, bundle); continue; }
    if ((entry.name.startsWith('.env') && entry.name !== '.env.example') || entry.name.endsWith('.lock') || entry.name === 'package-lock.json') continue;
    if (!/\.(mjs|js|ts|tsx|json|md|css|py|toml|example)$/.test(entry.name)) continue;
    const content = await readFile(filename, 'utf8');
    files++;
    if (secrets.some(secret => content.includes(secret))) {
      console.error(`FAIL: configured credential value found in ${path.relative(root, filename)}`); failed = true;
    }
    if (/NEXT_PUBLIC_(?:HUME|SAMBANOVA|DEEPGRAM|GENERALCOMPUTE|GRADIUM|TYPESAFE|EXA|CLM)_[A-Z_]*(?:KEY|SECRET)/.test(content)) {
      console.error(`FAIL: public provider-secret variable in ${path.relative(root, filename)}`); failed = true;
    }
  }
}
await scan(root);
await scan(path.join(root, 'practice/.next/static'), true);
if (failed) process.exitCode = 1;
else console.log(`PASS: ${files} source/browser bundle files scanned. ${secrets.length} configured secret values checked; values never printed.`);
if (!secrets.length) console.log('LIMITATION: no actual credentials configured. Repeat with real local secrets before sharing; inspect browser requests during a live session.');

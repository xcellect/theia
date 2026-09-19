import { fileURLToPath } from 'node:url';
import { config } from 'dotenv';

// Resolve relative to this file, not the caller's working directory.
export function loadPracticeEnv() {
  for (const filename of ['../.env.local', '../.env']) {
    const result = config({ path: fileURLToPath(new URL(filename, import.meta.url)), override: false, quiet: true });
    if (result.error && result.error.code !== 'ENOENT') throw new Error('Cannot read practice environment file. Check local file permissions.');
  }
}

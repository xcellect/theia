import { loadPracticeEnv } from '../lib/env.mjs';
import { readConfig } from '../lib/config.mjs';
try {
  loadPracticeEnv();
  const route = process.argv[2] || 'evi';
  readConfig(route);
  console.log(`PASS: ${route} configuration is valid. Credentials were not tested.`);
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}

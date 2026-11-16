// Runs the browser-free JS unit checks (esbuild bundles of apps/web/src modules).
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const here = path.dirname(new URL(import.meta.url).pathname);
const files = fs.readdirSync(here).filter((f) => f.startsWith('test_') && f.endsWith('.mjs')).sort();
let failed = 0;
for (const file of files) {
  fs.mkdirSync(path.join('.data/checks', path.basename(file, '.mjs')), { recursive: true });
  const result = spawnSync(process.execPath, [path.join(here, file)], { encoding: 'utf8' });
  const ok = result.status === 0;
  if (!ok) failed += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${file}`);
  if (!ok) console.log((result.stderr || result.stdout).split('\n').slice(-8).join('\n'));
}
process.exit(failed ? 1 : 0);

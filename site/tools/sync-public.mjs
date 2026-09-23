// Copy the files the site serves as they are from their sources into public/.
//
// The downloads, explorer payloads, boundaries, manifest and suppression
// audit are pipeline outputs in data/processed/; the two client scripts are
// written in src/lib/. Until September 2026 public/ held committed copies,
// refreshed by hand, so a merged data refresh changed data/processed/ and
// left the served files on the previous month. Generating them on every
// build and dev start means a deploy always carries what main holds.
//
// Runs as the prebuild and predev npm scripts. The destination directories
// are emptied first so a file dropped from the source does not linger.

import { cpSync, existsSync, mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const site = join(dirname(fileURLToPath(import.meta.url)), '..');
const processed = join(site, '..', 'data', 'processed');
const publicDir = join(site, 'public');

// Every file served from /data/ comes from data/processed/. This list is
// the whole of what is published there; suppression has already run on it.
const DATA_FILES = ['manifest.json', 'suppression_audit.json'];
const DATA_DIRS = ['boundaries', 'csv', 'explorer'];
const SCRIPTS = ['explorer-client.js', 'csv.mjs'];

const missing = [...DATA_FILES, ...DATA_DIRS]
  .filter((name) => !existsSync(join(processed, name)));
if (missing.length) {
  console.error(`sync-public: data/processed/ lacks ${missing.join(', ')}; run make build first`);
  process.exit(1);
}

for (const dir of ['data', 'scripts']) {
  rmSync(join(publicDir, dir), { recursive: true, force: true });
  mkdirSync(join(publicDir, dir), { recursive: true });
}
for (const name of [...DATA_FILES, ...DATA_DIRS]) {
  cpSync(join(processed, name), join(publicDir, 'data', name), { recursive: true });
}
for (const name of SCRIPTS) {
  cpSync(join(site, 'src', 'lib', name), join(publicDir, 'scripts', name));
}
console.log(`sync-public: ${DATA_FILES.length + DATA_DIRS.length} data entries and ${SCRIPTS.length} scripts copied into public/`);

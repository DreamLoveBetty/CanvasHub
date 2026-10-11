// Cache-busting guard for the served pages. Every local script/stylesheet a page references
// must carry ?v=<key>, and whenever a file's content changes its key must change too —
// browsers cache these assets by URL, so a changed file under an old key keeps serving the
// old code. frontend/asset-versions.lock.json records, per page and asset, the key and the
// SHA-256 of the content that key was published with.
//
//   node tooling/asset-versions.mjs            check (also part of `npm run check`)
//   node tooling/asset-versions.mjs --update   record the current keys and contents
//
// --update refuses to record an asset whose content changed under an unchanged key, so it
// cannot paper over a missing bump. Tests assert behaviour and load order, not key strings.
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const LOCK = path.join(FRONTEND, 'asset-versions.lock.json');
const PAGES = ['desktop.html', 'index.html'];
// Local script/stylesheet references; remote URLs and data: are not ours to version.
const TAG = /<(?:script\b[^>]*\bsrc|link\b[^>]*\bhref)="((?:scripts|styles)\/[^"?#]+)(?:\?v=([^"#]*))?"/g;

const sha256 = buffer => createHash('sha256').update(buffer).digest('hex');

export async function scan() {
  const pages = {};
  for (const page of PAGES) {
    const html = await readFile(path.join(FRONTEND, page), 'utf8');
    const assets = {};
    for (const [, asset, key] of html.matchAll(TAG)) {
      const content = await readFile(path.join(FRONTEND, asset)).catch(() => null);
      assets[asset] = { v: key ?? '', sha256: content ? sha256(content) : null };
    }
    pages[page] = Object.fromEntries(Object.entries(assets).sort(([a], [b]) => a.localeCompare(b)));
  }
  return pages;
}

async function readLock() {
  try { return JSON.parse(await readFile(LOCK, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return { schema: 1, pages: {} }; throw error; }
}

// Problems that block both check and update; drift only blocks check.
export function compare(current, lock) {
  const errors = [], drift = [];
  for (const [page, assets] of Object.entries(current)) {
    const locked = lock.pages?.[page] || {};
    for (const [asset, { v, sha256: hash }] of Object.entries(assets)) {
      const where = `${page}: ${asset}`;
      if (!hash) { errors.push(`${where} is referenced but missing`); continue; }
      if (!v) { errors.push(`${where} has no ?v= cache key`); continue; }
      const before = locked[asset];
      if (!before) { drift.push(`${where} is not recorded yet`); continue; }
      if (before.sha256 !== hash && before.v === v) errors.push(`${where} changed but still uses ?v=${v} — bump its cache key`);
      else if (before.sha256 !== hash || before.v !== v) drift.push(`${where} ?v=${before.v} → ${v} not recorded`);
    }
    for (const asset of Object.keys(locked)) if (!assets[asset]) drift.push(`${page}: ${asset} is no longer referenced`);
  }
  return { errors, drift };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const update = process.argv.includes('--update');
  const current = await scan();
  const { errors, drift } = compare(current, await readLock());
  if (errors.length) {
    console.error(errors.map(line => `✖ ${line}`).join('\n'));
    process.exit(1);
  }
  if (update) {
    await writeFile(LOCK, JSON.stringify({ schema: 1, pages: current }, null, 1) + '\n');
    console.log(`asset-versions.lock.json recorded ${Object.values(current).reduce((n, a) => n + Object.keys(a).length, 0)} assets${drift.length ? ` (${drift.length} updated)` : ''}`);
  } else if (drift.length) {
    console.error(drift.map(line => `• ${line}`).join('\n') + '\nKeys are bumped correctly; record them with: node frontend/tooling/asset-versions.mjs --update');
    process.exit(1);
  } else {
    console.log('asset cache keys are current');
  }
}

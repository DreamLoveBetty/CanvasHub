const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { pathToFileURL } = require('node:url');

const root = path.resolve(__dirname, '..');
const tool = path.join(root, 'frontend/tooling/asset-versions.mjs');

test('every served script/stylesheet has a cache key, and changed files carry a new one', () => {
  // Exits non-zero on a missing key, a changed file under an unchanged key, or keys not recorded.
  execFileSync(process.execPath, [tool], { stdio: 'pipe' });
  const lock = JSON.parse(fs.readFileSync(path.join(root, 'frontend/asset-versions.lock.json'), 'utf8'));
  assert.equal(lock.schema, 1);
  assert.ok(Object.keys(lock.pages['desktop.html']).length > 100);
  assert.ok(Object.keys(lock.pages['index.html']).length > 10);
  assert.match(JSON.parse(fs.readFileSync(path.join(root, 'frontend/package.json'), 'utf8')).scripts.check, /asset-versions\.mjs/);
});

test('compare: a content change needs a key change; update cannot record a missed bump', async () => {
  const { compare } = await import(pathToFileURL(tool).href);
  const lock = { schema: 1, pages: { 'desktop.html': { 'scripts/a.js': { v: 'k1', sha256: 'aaa' }, 'scripts/gone.js': { v: 'k', sha256: 'x' } } } };
  const page = assets => ({ 'desktop.html': assets });
  // Unchanged → clean apart from the dropped reference.
  let r = compare(page({ 'scripts/a.js': { v: 'k1', sha256: 'aaa' } }), lock);
  assert.deepEqual(r.errors, []);
  assert.match(r.drift.join('\n'), /scripts\/gone\.js is no longer referenced/);
  // Changed content, same key → hard error (blocks --update too).
  r = compare(page({ 'scripts/a.js': { v: 'k1', sha256: 'bbb' } }), lock);
  assert.match(r.errors.join('\n'), /scripts\/a\.js changed but still uses \?v=k1 — bump its cache key/);
  // Changed content, new key → only needs recording.
  r = compare(page({ 'scripts/a.js': { v: 'k2', sha256: 'bbb' } }), lock);
  assert.deepEqual(r.errors, []);
  assert.match(r.drift.join('\n'), /\?v=k1 → k2 not recorded/);
  // Missing key / missing file / new asset.
  r = compare(page({ 'scripts/a.js': { v: '', sha256: 'aaa' }, 'scripts/b.js': { v: 'k', sha256: null }, 'scripts/c.js': { v: 'k', sha256: 'c' } }), lock);
  assert.match(r.errors.join('\n'), /scripts\/a\.js has no \?v= cache key/);
  assert.match(r.errors.join('\n'), /scripts\/b\.js is referenced but missing/);
  assert.match(r.drift.join('\n'), /scripts\/c\.js is not recorded yet/);
});

test('feature tests do not pin cache-key strings', () => {
  const pinned = fs.readdirSync(__dirname)
    .filter(name => /^test_.*\.(cjs|py)$/.test(name) && !/_local\./.test(name) && name !== path.basename(__filename))
    .filter(name => /\?v=20\d{6}-|'20\d{6}-[a-z][\w.-]*'|"20\d{6}-[a-z][\w.-]*"/.test(fs.readFileSync(path.join(__dirname, name), 'utf8')));
  assert.deepEqual(pinned, [], 'use hasCacheKey(...) / a ?v= presence regex; the lock checks bumps');
});

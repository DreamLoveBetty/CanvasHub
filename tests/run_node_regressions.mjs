#!/usr/bin/env node
// Run stable and machine-local Node regressions as separate suites.
// Mirrors tests/run_regressions.py: stable excludes *_local.* and tests/local|manual.

import { spawnSync } from 'node:child_process';
import { readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TEST_ROOT = path.join(PROJECT_ROOT, 'tests');
const GENERATED_DIRS = new Set([
  'output', 'artifacts', 'reports', 'test-results', 'playwright-report',
  'coverage', 'tmp', '__pycache__', 'node_modules',
]);
const LOCAL_DIRS = new Set(['local', 'manual']);
const TEST_FILE = /^test_.*\.(cjs|mjs|js)$/;
const LOCAL_FILE = /_local\.(cjs|mjs|js)$/;

function testFiles(directory, insideLocal) {
  const result = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      if (GENERATED_DIRS.has(entry.name)) continue;
      result.push(...testFiles(file, insideLocal || LOCAL_DIRS.has(entry.name)));
    } else if (entry.isFile() && TEST_FILE.test(entry.name)) {
      result.push({ file, local: insideLocal || LOCAL_FILE.test(entry.name) });
    }
  }
  return result;
}

const args = process.argv.slice(2);
const scopeIndex = args.indexOf('--scope');
const scope = scopeIndex >= 0 ? args[scopeIndex + 1] : 'stable';
if (!['stable', 'local', 'all'].includes(scope)) {
  console.error('usage: node tests/run_node_regressions.mjs [--scope stable|local|all]');
  process.exit(2);
}

const files = testFiles(TEST_ROOT, false)
  .filter(({ local }) => scope === 'all' || (scope === 'local') === local)
  .map(({ file }) => path.relative(PROJECT_ROOT, file))
  .sort();
if (!files.length) {
  console.error(`No Node tests found for scope "${scope}".`);
  process.exit(1);
}

// Tests read sources via project-relative paths, so always run from the root.
const run = spawnSync(process.execPath, ['--test', ...files], { cwd: PROJECT_ROOT, stdio: 'inherit' });
process.exit(run.status ?? 1);

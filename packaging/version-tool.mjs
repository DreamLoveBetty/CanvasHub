import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const files = {
  package: path.join(root, 'desktop/electron/package.json'),
  lock: path.join(root, 'desktop/electron/package-lock.json'),
  python: path.join(root, 'backend/version.py'),
  electron: path.join(root, 'desktop/electron/src/main.ts'),
  frontend: path.join(root, 'frontend/desktop.html'),
};
const versionPattern = /^\d+\.\d+\.\d+$/;

function assertVersion(value, label = 'version') {
  if (!versionPattern.test(String(value || ''))) {
    throw new Error(`${label} must use MAJOR.MINOR.PATCH format: ${value || '(empty)'}`);
  }
  return String(value);
}

async function readJson(file) {
  return JSON.parse(await readFile(file, 'utf8'));
}

async function currentVersion() {
  const packageJson = await readJson(files.package);
  return assertVersion(packageJson.version, 'package.json version');
}

function nextVersion(current, level) {
  const parts = assertVersion(current).split('.').map(Number);
  if (level === 'patch') parts[2] += 1;
  else if (level === 'minor') {
    parts[1] += 1;
    parts[2] = 0;
  } else if (level === 'major') {
    parts[0] += 1;
    parts[1] = 0;
    parts[2] = 0;
  } else {
    throw new Error(`unknown release level: ${level}`);
  }
  return parts.join('.');
}

function replaceExactly(source, pattern, replacement, label) {
  const matches = source.match(pattern) || [];
  if (matches.length !== 1) {
    throw new Error(`${label}: expected exactly one version declaration, found ${matches.length}`);
  }
  return source.replace(pattern, replacement);
}

async function setVersion(target) {
  assertVersion(target, 'target version');
  const packageJson = await readJson(files.package);
  const packageLock = await readJson(files.lock);
  packageJson.version = target;
  packageLock.version = target;
  if (!packageLock.packages?.['']) {
    throw new Error('package-lock.json is missing the root package entry');
  }
  packageLock.packages[''].version = target;

  const python = replaceExactly(
    await readFile(files.python, 'utf8'),
    /^APP_VERSION = "\d+\.\d+\.\d+"$/gm,
    `APP_VERSION = "${target}"`,
    'backend/version.py',
  );
  const electron = replaceExactly(
    await readFile(files.electron, 'utf8'),
    /^const APP_VERSION = '\d+\.\d+\.\d+';$/gm,
    `const APP_VERSION = '${target}';`,
    'desktop/electron/src/main.ts',
  );
  const frontendSource = await readFile(files.frontend, 'utf8');
  const frontendVersions = frontendSource.match(/V\d+(?:\.\d+){2,3}/g) || [];
  if (frontendVersions.length < 4) {
    throw new Error(`frontend/desktop.html: expected at least four app version labels, found ${frontendVersions.length}`);
  }
  const frontend = frontendSource.replace(/V\d+(?:\.\d+){2,3}/g, `V${target}`);

  await Promise.all([
    writeFile(files.package, `${JSON.stringify(packageJson, null, 2)}\n`, 'utf8'),
    writeFile(files.lock, `${JSON.stringify(packageLock, null, 2)}\n`, 'utf8'),
    writeFile(files.python, python, 'utf8'),
    writeFile(files.electron, electron, 'utf8'),
    writeFile(files.frontend, frontend, 'utf8'),
  ]);
}

async function checkVersion(expected) {
  assertVersion(expected, 'expected version');
  const packageJson = await readJson(files.package);
  const packageLock = await readJson(files.lock);
  const python = await readFile(files.python, 'utf8');
  const electron = await readFile(files.electron, 'utf8');
  const frontend = await readFile(files.frontend, 'utf8');
  const checks = [
    ['package.json', packageJson.version === expected],
    ['package-lock.json', packageLock.version === expected && packageLock.packages?.['']?.version === expected],
    ['backend/version.py', python.includes(`APP_VERSION = "${expected}"`)],
    ['desktop/electron/src/main.ts', electron.includes(`const APP_VERSION = '${expected}';`)],
    ['frontend/desktop.html', (frontend.match(new RegExp(`V${expected.replaceAll('.', '\\.')}\\b`, 'g')) || []).length >= 4],
  ];
  const failed = checks.filter(([, ok]) => !ok).map(([name]) => name);
  if (failed.length) {
    throw new Error(`version ${expected} is not synchronized in: ${failed.join(', ')}`);
  }
}

const [command, argument] = process.argv.slice(2);
const current = await currentVersion();

if (command === 'current') {
  process.stdout.write(`${current}\n`);
} else if (command === 'next') {
  process.stdout.write(`${nextVersion(current, argument)}\n`);
} else if (command === 'set') {
  await setVersion(argument);
  await checkVersion(argument);
  process.stdout.write(`${argument}\n`);
} else if (command === 'check') {
  await checkVersion(argument || current);
  process.stdout.write(`${argument || current}\n`);
} else {
  throw new Error('usage: node packaging/version-tool.mjs <current|next|set|check> [value]');
}

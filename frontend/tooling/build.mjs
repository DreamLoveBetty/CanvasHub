import * as esbuild from 'esbuild';
import { createHash } from 'node:crypto';
import * as fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const MARKER = '.canvashub-web-build';
const MARKER_CONTENT = 'canvashub-web-v1\n';
const MANIFEST = 'frontend/asset-manifest.json';
const PAGES = ['desktop.html', 'index.html'];
const PUBLIC_DIRECTORIES = ['frontend/assets', 'frontend/vendor', 'static'];
const isPublicResource = file => path.basename(file) !== 'prompt-library-guide.png';
const slash = value => value.split(path.sep).join('/');
const digest = value => createHash('sha256').update(value).digest('hex');
const sorted = values => Object.fromEntries(Object.entries(values).sort(([a], [b]) => a.localeCompare(b)));

function confined(base, relative) {
  const target = path.resolve(base, relative);
  const rel = path.relative(base, target);
  if (path.isAbsolute(relative) || rel === '..' || rel.startsWith('..' + path.sep)) {
    throw new Error('Path escapes its resource root: ' + relative);
  }
  return target;
}

async function exists(file) {
  try { await fs.access(file); return true; } catch (error) {
    if (error.code === 'ENOENT') return false;
    throw error;
  }
}

// Resolve existing ancestors too: an output may not exist yet, while its parent
// is a symlink back into frontend/. Keep the original path for ownership checks.
async function physicalPath(file) {
  let ancestor = path.resolve(file);
  const suffix = [];
  while (true) {
    try {
      return path.join(await fs.realpath(ancestor), ...suffix.reverse());
    } catch (error) {
      if (error.code !== 'ENOENT' || path.dirname(ancestor) === ancestor) throw error;
      suffix.push(path.basename(ancestor));
      ancestor = path.dirname(ancestor);
    }
  }
}

async function filesUnder(directory, { hidden = false } = {}) {
  const result = [];
  if (!await exists(directory)) return result;
  if ((await fs.lstat(directory)).isSymbolicLink()) throw new Error('Resource directory must not be a symlink: ' + directory);
  for (const entry of (await fs.readdir(directory, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
    if (!hidden && entry.name.startsWith('.')) continue;
    const file = path.join(directory, entry.name);
    if (entry.isSymbolicLink()) throw new Error('Public resources must not be symlinks: ' + file);
    if (entry.isDirectory()) result.push(...await filesUnder(file, { hidden }));
    else if (entry.isFile()) result.push(file);
  }
  return result;
}

// Keep the original HTML, script order, classic-script scope, and attributes.
// Only external script / stylesheet URL attributes are rewritten.
function assetTags(html) {
  const tags = [];
  const pattern = /<!--[\s\S]*?-->|<(script|link)\b(?:[^>"']|"[^"]*"|'[^']*')*>/gi;
  let skipUntil = 0;
  for (const match of html.matchAll(pattern)) {
    if (!match[1] || match.index < skipUntil) continue;
    const script = match[1].toLowerCase() === 'script';
    if (script) {
      const closing = /<\/script\s*>/gi;
      closing.lastIndex = match.index + match[0].length;
      const end = closing.exec(html);
      skipUntil = end ? end.index + end[0].length : html.length;
    }
    const attributes = new Map();
    for (const attr of match[0].matchAll(/\s([\w-]+)\s*=\s*("([^"]*)"|'([^']*)')/g)) {
      attributes.set(attr[1].toLowerCase(), {
        value: attr[3] ?? attr[4],
        start: attr.index + attr[0].indexOf(attr[2]) + 1,
      });
    }
    if (!script && attributes.get('rel')?.value.toLowerCase() !== 'stylesheet') continue;
    const attr = attributes.get(script ? 'src' : 'href');
    if (!attr || /^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(attr.value)) continue;
    const url = new URL(attr.value.replaceAll('&amp;', '&'), 'http://build.invalid/');
    const source = decodeURIComponent(url.pathname.slice(1));
    if (!/^(scripts|styles|vendor)\//.test(source)) {
      throw new Error('Unsupported local entry asset: ' + attr.value);
    }
    tags.push({
      source, url, original: attr.value,
      start: match.index + attr.start, end: match.index + attr.start + attr.value.length,
      kind: !script ? 'css' : attributes.get('type')?.value === 'module' ? 'module' : 'classic',
    });
  }
  return tags;
}

async function requireOwnedOutput(outDir) {
  if (!await exists(outDir)) return;
  if (!await exists(path.join(outDir, MARKER)) ||
      await fs.readFile(path.join(outDir, MARKER), 'utf8') !== MARKER_CONTENT) {
    throw new Error('Refusing to replace a directory not created by this builder: ' + outDir);
  }
  const manifest = JSON.parse(await fs.readFile(path.join(outDir, MANIFEST), 'utf8'));
  const managed = new Set([...Object.keys(manifest.files), MANIFEST, MARKER]);
  for (const file of await filesUnder(outDir, { hidden: true })) {
    if (!managed.has(slash(path.relative(outDir, file)))) {
      throw new Error('Refusing to remove an unmanaged output file: ' + file);
    }
  }
}

export async function checkBuild(root, outDir, { sources = true } = {}) {
  const manifest = JSON.parse(await fs.readFile(path.join(outDir, MANIFEST), 'utf8'));
  if (manifest.schema_version !== 1) throw new Error('Unsupported frontend manifest');
  for (const [rel, expected] of Object.entries(manifest.files)) {
    const file = confined(outDir, rel);
    if (!(await fs.lstat(file)).isFile() || digest(await fs.readFile(file)) !== expected) {
      throw new Error('Built resource changed or is incomplete: ' + rel);
    }
  }
  if (sources) {
    for (const [rel, expected] of Object.entries(manifest.source_hashes)) {
      if (digest(await fs.readFile(confined(root, rel))) !== expected) {
        throw new Error('Frontend source changed; rebuild required: ' + rel);
      }
    }
    for (const directory of PUBLIC_DIRECTORIES) {
      for (const file of (await filesUnder(path.join(root, directory))).filter(isPublicResource)) {
        const rel = slash(path.relative(root, file));
        if (!manifest.source_hashes[rel]) throw new Error('New public resource; rebuild required: ' + rel);
      }
    }
  }
  for (const page of PAGES) {
    const html = await fs.readFile(path.join(outDir, 'frontend', page), 'utf8');
    for (const asset of assetTags(html)) {
      if (!manifest.files['frontend/' + asset.source]) {
        throw new Error('HTML references a missing built asset: ' + asset.source);
      }
    }
  }
  return manifest;
}

export async function buildFrontend(root, outDir) {
  root = path.resolve(root);
  outDir = path.resolve(outDir);
  const outputLocation = await physicalPath(outDir);
  const sourceDirectories = [root, path.join(root, 'frontend'), path.join(root, 'static'), path.join(root, 'backend')];
  for (const [index, directory] of sourceDirectories.entries()) {
    const source = await physicalPath(directory);
    if (outputLocation === source || source.startsWith(outputLocation + path.sep) ||
        (index !== 0 && outputLocation.startsWith(source + path.sep))) {
      throw new Error('Output must not overlap source directories: ' + outDir);
    }
  }
  await requireOwnedOutput(outDir);
  await fs.mkdir(path.dirname(outDir), { recursive: true });
  const stage = await fs.mkdtemp(path.join(path.dirname(outDir), '.canvashub-web-'));
  const frontend = path.join(root, 'frontend');
  const outputFrontend = path.join(stage, 'frontend');
  const sourceHashes = {};
  const entries = {};
  const immutable = new Set();
  const warnings = [];
  const sourceBytes = async file => {
    confined(root, path.relative(root, await fs.realpath(file)));
    if ((await fs.lstat(file)).isSymbolicLink()) throw new Error('Source must not be a symlink: ' + file);
    const rel = slash(path.relative(root, file));
    confined(root, rel);
    const data = await fs.readFile(file);
    const hash = digest(data);
    if (sourceHashes[rel] && sourceHashes[rel] !== hash) throw new Error('Source changed during build: ' + rel);
    sourceHashes[rel] = hash;
    return data;
  };
  const write = async (file, data) => {
    await fs.mkdir(path.dirname(file), { recursive: true });
    await fs.writeFile(file, data);
  };
  try {
    const pages = new Map();
    const kinds = new Map();
    for (const page of PAGES) {
      const html = (await sourceBytes(path.join(frontend, page))).toString('utf8');
      const tags = assetTags(html);
      pages.set(page, { html, tags });
      for (const tag of tags) {
        if (kinds.has(tag.source) && kinds.get(tag.source) !== tag.kind) {
          throw new Error('Entry used as both classic and module script: ' + tag.source);
        }
        kinds.set(tag.source, tag.kind);
      }
    }
    // Public resource directories only; never copy config, databases, tooling,
    // node_modules, or the project root into the distributable.
    for (const directory of PUBLIC_DIRECTORIES) {
      const from = path.join(root, directory);
      const to = path.join(stage, directory);
      await fs.mkdir(to, { recursive: true });
      for (const file of await filesUnder(from)) {
        if (!isPublicResource(file)) continue; // local design-review capture
        await write(path.join(to, path.relative(from, file)), await sourceBytes(file));
      }
    }
    // Third-party classic bundles remain byte-for-byte intact (UMD globals).
    for (const [source] of kinds) {
      if (!source.startsWith('vendor/')) continue;
      const bytes = await sourceBytes(confined(frontend, source));
      const ext = path.extname(source);
      const output = source.slice(0, -ext.length) + '-' + digest(bytes).slice(0, 16) + ext;
      entries[source] = output;
      immutable.add('/' + output);
      await write(confined(outputFrontend, output), bytes);
    }
    for (const kind of ['classic', 'module', 'css']) {
      const entryPoints = [...kinds].filter(([source, value]) => value === kind && !source.startsWith('vendor/'))
        .map(([source]) => confined(frontend, source));
      if (!entryPoints.length) continue;
      for (const file of entryPoints) await sourceBytes(file);
      const result = await esbuild.build({
        absWorkingDir: root, entryPoints, outbase: frontend, outdir: outputFrontend,
        entryNames: '[dir]/[name]-[hash]', assetNames: 'assets/[name]-[hash]',
        bundle: kind !== 'classic',
        ...(kind === 'module' ? { format: 'esm' } : {}),
        platform: 'browser', target: 'es2022', charset: 'utf8',
        minify: false, treeShaking: kind !== 'classic', legalComments: 'inline',
        metafile: true, write: false, logLevel: 'silent',
        loader: { '.svg': 'file', '.png': 'file', '.webp': 'file', '.woff': 'file', '.woff2': 'file' },
        plugins: [{
          name: 'existing-public-static-paths',
          setup(build) {
            build.onResolve({ filter: /^\.\.\/static\// }, args => ({
              path: confined(path.join(root, 'static'), args.path.slice('../static/'.length)),
            }));
            build.onLoad({ filter: /.*/, namespace: 'file' }, async args => {
              const loaders = { '.js': 'js', '.css': 'css', '.json': 'json', ...build.initialOptions.loader };
              const loader = loaders[path.extname(args.path)];
              if (!loader) throw new Error('Unsupported resource dependency: ' + args.path);
              return { contents: await sourceBytes(args.path), loader };
            });
          },
        }],
      });
      warnings.push(...result.warnings.map(warning => ({
        id: warning.id, text: warning.text, file: warning.location?.file, line: warning.location?.line,
      })));
      for (const input of Object.keys(result.metafile.inputs)) await sourceBytes(path.resolve(root, input));
      for (const output of result.outputFiles) {
        await write(output.path, output.contents);
        immutable.add('/' + slash(path.relative(outputFrontend, output.path)));
      }
      for (const [output, info] of Object.entries(result.metafile.outputs)) {
        if (!info.entryPoint) continue;
        const source = slash(path.relative(frontend, path.resolve(root, info.entryPoint)));
        entries[source] = slash(path.relative(outputFrontend, path.resolve(root, output)));
      }
    }
    for (const [page, { html, tags }] of pages) {
      let rendered = html;
      for (const tag of [...tags].reverse()) {
        if (!entries[tag.source]) throw new Error('Entry was not built: ' + tag.source);
        tag.url.searchParams.delete('v');
        const suffix = tag.url.search + tag.url.hash;
        const value = (tag.original.startsWith('/') ? '/' : '') + entries[tag.source] + suffix;
        rendered = rendered.slice(0, tag.start) + value.replaceAll('&', '&amp;') + rendered.slice(tag.end);
      }
      await write(path.join(outputFrontend, page), rendered);
    }
    for (const rel of ['frontend/tooling/build.mjs', 'frontend/package.json', 'frontend/package-lock.json']) {
      if (await exists(path.join(root, rel))) await sourceBytes(path.join(root, rel));
    }
    const files = {};
    for (const file of await filesUnder(stage)) files[slash(path.relative(stage, file))] = digest(await fs.readFile(file));
    const manifest = {
      schema_version: 1, builder: 'esbuild-' + esbuild.version,
      build_id: digest(JSON.stringify(sorted(files))).slice(0, 16),
      entries: sorted(entries), immutable_paths: [...immutable].sort(),
      files: sorted(files), source_hashes: sorted(sourceHashes), warnings,
    };
    await write(path.join(stage, MANIFEST), JSON.stringify(manifest, null, 2) + '\n');
    await write(path.join(stage, MARKER), MARKER_CONTENT);
    await checkBuild(root, stage);
    // Build completion is separate from deploying/restarting a running service.
    // A failed build never replaces the previous output or edits source HTML.
    let previous;
    if (await exists(outDir)) {
      await requireOwnedOutput(outDir);
      previous = await fs.mkdtemp(path.join(path.dirname(outDir), '.canvashub-web-old-'));
      await fs.rmdir(previous);
      await fs.rename(outDir, previous);
    }
    try {
      await fs.rename(stage, outDir);
    } catch (error) {
      if (previous) await fs.rename(previous, outDir);
      throw error;
    }
    if (previous) await fs.rm(previous, { recursive: true });
    if (warnings.length) console.warn('esbuild warnings: ' + warnings.length + '; details recorded in asset-manifest.json');
    return manifest;
  } finally {
    await fs.rm(stage, { recursive: true, force: true });
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    let root = PROJECT_ROOT;
    let outDir;
    let check = false;
    const args = process.argv.slice(2);
    while (args.length) {
      const arg = args.shift();
      if (arg === '--check') check = true;
      else if (arg === '--outdir' && args[0]) outDir = path.resolve(args.shift());
      else if (arg === '--root' && args[0]) root = path.resolve(args.shift());
      else throw new Error('Usage: build.mjs [--check] [--root DIR] [--outdir DIR]');
    }
    outDir ||= path.join(root, 'dist', 'web');
    const manifest = check ? await checkBuild(root, outDir) : await buildFrontend(root, outDir);
    console.log((check ? 'Verified' : 'Built') + ' frontend ' + manifest.build_id + ' → ' + outDir);
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}

// desktop-liquid.css plus the desktop-legacy-*.css files split out of it and the
// desktop-<domain>-geometry.css files migrated domains moved to, read together in
// desktop.html load order (see tests/legacy_css.py).
const fs = require('node:fs');
const path = require('node:path');

const FRONTEND = path.resolve(__dirname, '..', 'frontend');

function legacyCssFiles() {
  const html = fs.readFileSync(path.join(FRONTEND, 'desktop.html'), 'utf8');
  return [...html.matchAll(/href="styles\/(desktop-(?:liquid|legacy-[\w-]+|[\w-]+-geometry)\.css)\?/g)].map(m => path.join(FRONTEND, 'styles', m[1]));
}

function readLegacyCss() {
  return legacyCssFiles().map(file => fs.readFileSync(file, 'utf8')).join('\n');
}

module.exports = { legacyCssFiles, readLegacyCss };

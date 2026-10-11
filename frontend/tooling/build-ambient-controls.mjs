// Generates frontend/styles/desktop-ambient-controls.css from the pinned, unmodified
// Ambient CSS in frontend/vendor/ambientcss/.
//
// Upstream declares :root, * and @property globally and styles elements through its
// own classes (.ambient, .amb-surface, .amb-mat-*, .amb-button-cap...). CanvasHub must
// not load that into every page, nor add classes to buttons rendered by nine node
// modules. This tool copies only the rule blocks the button skin needs — declaration
// bodies byte-for-byte — and rewrites their selectors onto the production buttons,
// scoped to the opt-in body attributes owned by desktop-control-material.js.
//
//   node tooling/build-ambient-controls.mjs          write the generated file
//   node tooling/build-ambient-controls.mjs --check  fail if it is missing or stale
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const VENDOR = path.join(FRONTEND, 'vendor/ambientcss');
const OUTPUT = path.join(FRONTEND, 'styles/desktop-ambient-controls.css');
const COMMIT = 'f829df728ca34a1addecb475ca62b6493733b898';
const PINNED = {
  'ambient.css': '0498bab2fc1dfb9b7feb31a072744aea19631694752a1e43e1cdcd8cd4a3280b',
  'components.css': '60e7636ef506b0b80c2f3cd1fdd0b611212b6481ff4779422f3d6e20ba7458a2',
};

// Scope: opt-in material on <body id="deskApp">. Key caps (T): buttons inside canvas
// nodes and settings-centre action rows — generic .desk-button, node delete, generate actions that skip .desk-button
// (music, ReShot, Topaz Video) and .desk-key, a style-free hook node templates put on
// their own push buttons. Segmented controls take upstream's Select (lamp-lit bank): a
// .desk-key-bank hook on the container in nodes and the settings centre. The container
// is the rail (BANK); each direct button (K) is the key's pocket floor, its ::before the
// LED lens and its ::after the frosted diffuser cap (always glass, as upstream casts it),
// so the production markup stays one element per option. Switches take upstream's
// Switch (dark stadium recess + convex pill) with an LED: the track is a .desk-switch's
// <span> or, for plain checkboxes, the checkbox itself (appearance: none); the pill is
// its ::after and the LED its ::before. Text fields (FIELD) are grooves cut into the panel,
// under their own opt-in (FS: data-field-style="groove"), independent of the button material,
// so the upstream lighting tokens (:root) are provided on that scope too.
// Drop zones, the audio transport, the settings search bar, dropdown-backed inputs
// (.desk-select), inline renames and the code/prompt editors keep their look.
const S = '#deskApp[data-control-material="ambient"]';
// Node push buttons, plus the settings centre's action rows (every settings card places its
// commands in one of these rows, whatever account/runtime state is showing) and the colour
// pickers' reset buttons.
const T = ':is(.desk-node :is(.desk-button, .desk-node-delete, .desk-generation-action, .desk-key), '
  + '.desk-settings :is(.desk-settings-form__actions, .desk-settings-account__actions, .desk-lora-actions, '
  + '.desk-qwen21-tools__inspection, .desk-qwen21-tools__model, .desk-qwen21-tools__progress, '
  + '.desk-krea2-tools__model, .desk-krea2-tools__progress) > button, .desk-settings .desk-color-bloom__control > .desk-button)';
const BANK = ':is(.desk-node, .desk-settings) .desk-key-bank';
const K = `${BANK} > button`;
const ON = `${K}:is(.is-active, [aria-pressed="true"])`;
const CAP = `${S} ${K}::after`;
const SW = ':is(.desk-node, .desk-settings)';
const BOX = 'input[type="checkbox"]:not(.desk-switch > input)';
const TRACK = `${SW} :is(.desk-switch > span, ${BOX})`;
const TRACK_OFF = `${SW} :is(.desk-switch > input:not(:checked) + span, ${BOX}:not(:checked))`;
const TRACK_HOVER = `${SW} :is(.desk-switch:hover > span, ${BOX}:hover)`;
const PILL = `${S} ${TRACK}::after`;
const FIELD = ':is(.desk-node, .desk-settings) :is(input:is([type="text"], [type="number"], [type="password"], [type="email"], [type="url"], :not([type])), textarea.desk-settings-textarea)'
  + ':not(.desk-select):not(.desk-settings-search__input):not(.desk-text-node__alias input)';
const FS = '#deskApp[data-field-style="groove"]';
const finish = name => `${S}[data-control-finish="${name}"]`;
const list = (...selectors) => selectors.join(',\n');
const MAP = {
  'ambient.css': [
    ['@property --amb-elevation', '@property --amb-elevation'],
    [':root', list(S, FS)],
    // Derived per-element tones; the lens and cap pseudo-elements inherit them from K.
    // The switch pill also derives its own tones, so the dark theme can give it its own body.
    ['*', list(`${S} ${T}`, `${S} ${K}`, `${S} ${BANK}`, `${S} ${TRACK}`, PILL)],
    ['.amb-chamfer', list(`${S} ${T}`, CAP)],
    ['.amb-fillet', PILL],
    ['.amb-groove', list(`${S} ${BANK}`, `${S} ${TRACK}`, `${FS} ${FIELD}`)],
    ['.amb-mat-glass', list(`${finish('glass')} ${T}`, CAP)],
    ['.ambient', list(`${S} ${T}`, CAP, PILL)],
    ['.amb-surface', `${S} ${T}`],
    ['.amb-groove', list(`${S} ${BANK}`, `${S} ${TRACK}`, `${FS} ${FIELD}`)],
    ['.amb-mat-shiny', `${finish('shiny')} ${T}`],
    ['.amb-mat-glass', list(`${finish('glass')} ${T}`, CAP)],
    [':where(.amb-mat-glass)', `:where(${list(`${finish('glass')} ${T}`, CAP)})`],
    // The button itself is the cap, and the cap dish already owns ::after. The Select
    // cap is itself a pseudo-element, so its glass shadow ring has no layer left.
    ['.amb-mat-glass::after', `${finish('glass')} ${T}::before`],
    ['.amb-surface-convex', list(`${finish('matte')}[data-control-surface="convex"] ${T}`, PILL)],
  ],
  'components.css': [
    [':root', S],
    ['.amb-button-cap::after', `${S} ${T}::after`],
    ['.amb-led', `${S} ${TRACK}::before`],
    ['.amb-led-off', `${S} ${TRACK_OFF}::before`],
    ['.amb-switch:hover .amb-switch-pill', `${S} ${TRACK_HOVER}::after`],
    ['.amb-select .ambx-key:disabled .amb-select-lens', `${S} ${K}:disabled::before`],
    ['.amb-select-lens', `${S} ${K}::before`],
    ['.amb-select .ambx-key[data-on] .amb-select-lens', `${S} ${ON}::before`],
    ['.amb-select .ambx-key[data-on] .amb-select-cap', `${S} ${ON}::after`],
    ['.amb-select .ambx-key[data-on]', `${S} ${ON}`],
  ],
};

// Top-level blocks with comment-aware brace matching; bodies are kept verbatim.
function blocks(source) {
  const result = [];
  let depth = 0, start = 0, open = -1;
  for (let i = 0; i < source.length; i++) {
    if (source.startsWith('/*', i)) { i = source.indexOf('*/', i + 2) + 1; continue; }
    const ch = source[i];
    if (ch === '{') { if (depth === 0) open = i; depth++; }
    else if (ch === '}') {
      depth--;
      if (depth === 0) {
        const selector = source.slice(start, open).replace(/\/\*[\s\S]*?\*\//g, '').trim().replace(/\s+/g, ' ');
        result.push({ selector, body: source.slice(open, i + 1) });
        start = i + 1;
      }
    }
  }
  return result;
}

export async function generate() {
  const parts = [
    `/* GENERATED by frontend/tooling/build-ambient-controls.mjs — do not edit.\n` +
    `   Source: Ambient CSS ${COMMIT} (MIT, frontend/vendor/ambientcss/LICENSE).\n` +
    `   Declaration bodies are copied verbatim; only selectors are rewritten so the rules\n` +
    `   apply to buttons inside canvas nodes while <body id="deskApp"> carries\n` +
    `   data-control-material="ambient". Layout/state adaptation: desktop-control-material.css. */\n`,
  ];
  for (const [file, rules] of Object.entries(MAP)) {
    const source = await readFile(path.join(VENDOR, file), 'utf8');
    const digest = createHash('sha256').update(source).digest('hex');
    if (digest !== PINNED[file]) throw new Error(`${file} does not match the pinned upstream hash`);
    const available = blocks(source);
    let cursor = 0;
    for (const [selector, target] of rules) {
      // Upstream order matters (later blocks override earlier ones), so match in sequence.
      const index = available.findIndex((block, i) => i >= cursor && block.selector === selector);
      if (index < 0) throw new Error(`${file}: upstream rule "${selector}" not found in order`);
      cursor = index + 1;
      parts.push(`\n/* ${file}: ${selector} */\n${target} ${available[index].body}\n`);
    }
  }
  return parts.join('');
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const css = await generate();
  if (process.argv.includes('--check')) {
    const current = await readFile(OUTPUT, 'utf8').catch(() => '');
    if (current !== css) {
      console.error('desktop-ambient-controls.css is stale; run node frontend/tooling/build-ambient-controls.mjs');
      process.exit(1);
    }
    console.log('desktop-ambient-controls.css is up to date');
  } else {
    await writeFile(OUTPUT, css);
    console.log(`Wrote ${path.relative(process.cwd(), OUTPUT)} (${css.length} bytes)`);
  }
}

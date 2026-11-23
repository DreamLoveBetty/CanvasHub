'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { hasCacheKey } = require('./asset_keys.cjs');

const ROOT = path.resolve(__dirname, '..');
const read = rel => fs.readFileSync(path.join(ROOT, rel), 'utf8');

test('mobile ComfyUI workbench in cinematic mode exposes submit button and scopes classic overrides away', () => {
  const indexHtml = read('frontend/index.html');
  const uiShell = read('frontend/scripts/ui-shell.js');
  const cinematicCss = read('frontend/styles/cinematic-shell-stream.css');
  const overridesCss = read('frontend/styles/theme-overrides.css');
  const baseCss = read('frontend/styles/base.css');

  assert.match(uiShell, /isCinematicComfy\s*=\s*currentLayoutMode === 'cinematic'[\s\S]*is-cinematic-comfy-workbench/);
  assert.match(cinematicCss, /html\[data-layout="cinematic"\] body\.is-cinematic-comfy-workbench\s*\{[\s\S]*--panel-bg:/);
  assert.match(cinematicCss, /body\.is-cinematic-comfy-workbench\.settings-open #view-comfy\s*\{\s*z-index:\s*270;/);
  assert.match(cinematicCss, /body\.is-cinematic-comfy-workbench #btnComfy\s*\{[\s\S]*display:\s*flex !important;/);
  assert.doesNotMatch(overridesCss, /html\[data-skin="(?:midnight|cassette-light|skeuo-tech)"\](?!:not\(\[data-layout="cinematic"\]\))/);
  assert.match(baseCss, /\.settings-trigger\s*\{[^}]*width:\s*100%;/);
  assert.doesNotMatch(indexHtml, /id="comfyUploadArea"[^>]*style="background:#fff/);
  assert.ok(hasCacheKey(indexHtml, 'styles/cinematic-shell-stream.css'));
  assert.ok(hasCacheKey(indexHtml, 'styles/theme-overrides.css'));
  assert.ok(hasCacheKey(indexHtml, 'scripts/ui-shell.js'));
});

test('desktop prompt assistant and agent drawer keep button hierarchy, unclipped handle, and zoom clearance', () => {
  const desktopHtml = read('frontend/desktop.html');
  const promptCss = read('frontend/styles/desktop-prompt-assistant.css');
  const promptGeom = read('frontend/styles/desktop-prompt-assistant-geometry.css');
  const geomCss = read('frontend/styles/desktop-geometry.css');
  const graphiteCss = read('frontend/styles/desktop-graphite.css');

  assert.match(desktopHtml, /class="desk-prompt-btn--ghost" id="deskPromptDrawerClear"/);
  assert.match(desktopHtml, /class="desk-prompt-btn--secondary" id="deskPromptChatRefresh"/);
  assert.match(promptCss, /:not\(\[role="radio"\]\):not\(\.desk-prompt-expand-btn\):not\(\.desk-prompt-btn--secondary\):not\(\.desk-prompt-btn--ghost\)/);
  assert.match(promptGeom, /\.desk-prompt-drawer\.is-open \.desk-prompt-drawer__handle\s*\{[^}]*top:\s*-16px;/);
  assert.match(geomCss, /\.desk-prompt-chat__input\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s*minmax\(108px,\s*auto\);/);
  assert.match(geomCss, /\.desk-prompt-drawer\.is-open\.is-agent\s*\{[^}]*calc\(100vw - 476px\)/);
  assert.match(graphiteCss, /--desk-prompt-assistant-disabled-ink:\s*var\(--desk-graphite-muted\);/);
  assert.match(graphiteCss, /--desk-prompt-assistant-secondary-background:\s*var\(--desk-graphite-card\);/);
});

test('open workbenches hide collapsed prompt handle and close open drawer cleanly', () => {
  const promptGeom = read('frontend/styles/desktop-prompt-assistant-geometry.css');
  const historyJs = read('frontend/scripts/desktop-history.js');

  assert.match(promptGeom, /\.desk-workbench-open \.desk-prompt-drawer:not\(\.is-open\)\s*\{[^}]*opacity:\s*0;[^}]*visibility:\s*hidden;/);
  assert.match(historyJs, /DesktopPromptDrawer\?\.setOpen\?\.\(false,\s*false\)/);
});

test('settings hints use muted ink, idle stop button stays calm, gallery tabs unify visually, and graphite auth is neutral', () => {
  const tokensCss = read('frontend/styles/desktop-tokens.css');
  const settingsCss = read('frontend/styles/desktop-settings-auth.css');
  const settingsJs = read('frontend/scripts/desktop-settings.js');
  const shellCss = read('frontend/styles/desktop-shell.css');
  const historyJs = read('frontend/scripts/desktop-history.js');
  const galleryGeom = read('frontend/styles/desktop-gallery-geometry.css');
  const galleryCss = read('frontend/styles/desktop-gallery.css');
  const geomCss = read('frontend/styles/desktop-geometry.css');
  const graphiteCss = read('frontend/styles/desktop-graphite.css');

  const hintMatches = tokensCss.match(/--desk-settings-hint-ink:\s*var\(--desk-settings-muted-ink\);/g) || [];
  assert.equal(hintMatches.length, 2, 'both light and dark themes must map --desk-settings-hint-ink to muted ink');
  assert.match(settingsCss, /\.desk-settings-form__hint--warn\s*\{[^}]*color:\s*var\(--desk-settings-summary-warn-ink\);/);

  assert.match(historyJs, /stopBtn\.classList\.toggle\('is-active',\s*hasActive\)/);
  assert.match(shellCss, /\.desk-status-stop:not\(\.is-active\):not\(:hover\)\s*\{[^}]*opacity:\s*0\.68;/);

  assert.match(galleryGeom, /\.desk-gallery-tab-groups > \.desk-gallery-tabs--models::before\s*\{[^}]*width:\s*1px;/);
  assert.match(galleryCss, /--desk-gallery-tab-group-divider/);

  assert.match(settingsJs, /renderKv\('Nano Banana Key'/);
  assert.match(settingsJs, /renderKv\('GPT Image 2 Key'/);
  assert.match(settingsJs, /renderPath\('图片归档'/);
  assert.match(settingsJs, /renderPath\('参考图目录'/);
  assert.match(settingsJs, /renderPath\('任务数据库'/);
  assert.match(geomCss, /\.desk-settings-tabs button\.is-active::before\s*\{[^}]*left:\s*5px;/);

  assert.match(graphiteCss, /--desk-auth-card-background:\s*var\(--desk-graphite-card\);/);
  assert.match(graphiteCss, /--desk-auth-overlay-background:\s*var\(--desk-graphite-auth-backdrop\);/);
});

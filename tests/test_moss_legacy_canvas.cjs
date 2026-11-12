// Regression: a canvas saved before the MOSS custom preset has nodes without samplerParams, and
// saved nodes render (ensureGraphDom -> nodeHtml) before mount() normalizes them. Reading
// node.samplerParams.steps there threw inside DesktopCanvas.init and blanked the whole canvas.
const test = require('node:test');
const assert = require('node:assert/strict');
const { setup } = require('./moss_frontend_fixture.cjs');

test('a saved MOSS node without sampler params still renders with the defaults', () => {
  const t = setup({ node: { preset: 'turbo' } });
  const saved = { ...t.moss };
  delete saved.samplerParams;
  const html = t.controller.nodeHtml(saved);
  const { steps, cfg, shift } = t.M.SAMPLER_DEFAULTS;
  assert.match(html, new RegExp(`value="${steps}" data-stepper="off" data-moss-sampler="steps"`));
  assert.match(html, new RegExp(`value="${cfg}" data-stepper="off" data-moss-sampler="cfg"`));
  assert.match(html, new RegExp(`value="${shift}" data-stepper="off" data-moss-sampler="shift"`));
  assert.equal(saved.samplerParams, undefined, 'rendering does not rewrite the saved node');
});

test('a MOSS draft from a newer schema renders instead of throwing', () => {
  const t = setup();
  const newer = { ...t.moss, schemaVersion: t.M.SCHEMA_VERSION + 1 };
  delete newer.samplerParams;
  t.M.normalize(newer);
  assert.equal(newer.samplerParams, undefined, 'normalize leaves a newer draft untouched');
  assert.doesNotThrow(() => t.controller.nodeHtml(newer));
});

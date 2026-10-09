const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('frontend/scripts/desktop-prompt-library.js', 'utf8');
const CUSTOM_KEY = 'desk_prompt_custom_colors_v1';
const FAVORITES_KEY = 'desk_prompt_color_favorites_v1';

function color(id, custom, favorite = false) {
  return {
    id,
    name: custom ? '旧版自定义' : '珊瑚日出',
    description: '测试配色',
    colors: ['#112233', '#445566', '#778899', '#DDEEFF', '#101820'],
    categories: ['cool'],
    scenes: ['界面系统'],
    tags: ['测试'],
    prompt: '使用测试配色。',
    industry: custom ? 'uiux' : '',
    formula: custom ? 'monochromatic' : 'analogous',
    base_color: '#112233',
    contrast: 'balanced',
    temperature: 'cool',
    neutral_balance: true,
    use_ratio: true,
    custom,
    favorite,
  };
}

function makeStorage(values) {
  const data = new Map(Object.entries(values));
  return {
    getItem: key => data.has(key) ? data.get(key) : null,
    removeItem: key => data.delete(key),
    setItem: (key, value) => data.set(key, String(value)),
    has: key => data.has(key),
  };
}

function loadLibrary(storage, api) {
  const document = {
    getElementById: () => null,
    addEventListener: () => {},
    querySelector: () => null,
    body: { appendChild: () => {} },
    activeElement: null,
  };
  const window = {
    localStorage: storage,
    DesktopApi: api,
    setTimeout,
    clearTimeout,
    requestAnimationFrame: callback => callback(),
  };
  const context = vm.createContext({
    window,
    document,
    console,
    setTimeout,
    clearTimeout,
    requestAnimationFrame: callback => callback(),
    URL,
  });
  vm.runInContext(source, context, { filename: 'desktop-prompt-library.js' });
  return window.DesktopPromptLibrary;
}

(async () => {
  const legacyCustom = color('custom-color-legacy', true, false);
  const storage = makeStorage({
    [CUSTOM_KEY]: JSON.stringify([legacyCustom]),
    [FAVORITES_KEY]: JSON.stringify(['coral-sunrise']),
  });
  let migrationPayload = null;
  const library = loadLibrary(storage, {
    migrateLegacyPromptColorSchemes: async payload => {
      migrationPayload = payload;
      return { migration_complete: true, color_schemes: [color('custom-color-legacy', true), color('coral-sunrise', false, true)] };
    },
    getPromptColorSchemes: async () => { throw new Error('migration response should be reused'); },
  });
  const schemes = await library.ensureColorSchemes();
  assert.strictEqual(migrationPayload.custom_schemes[0].id, 'custom-color-legacy');
  assert.deepStrictEqual(Array.from(migrationPayload.favorite_ids), ['coral-sunrise']);
  assert.strictEqual(schemes.length, 2);
  assert.strictEqual(schemes[1].favorite, true);
  assert.strictEqual(storage.has(CUSTOM_KEY), false);
  assert.strictEqual(storage.has(FAVORITES_KEY), false);

  const failingStorage = makeStorage({
    [CUSTOM_KEY]: JSON.stringify([legacyCustom]),
    [FAVORITES_KEY]: JSON.stringify([]),
  });
  const failingLibrary = loadLibrary(failingStorage, {
    migrateLegacyPromptColorSchemes: async () => { throw new Error('offline'); },
    getPromptColorSchemes: async () => ({ color_schemes: [] }),
  });
  await assert.rejects(() => failingLibrary.ensureColorSchemes(), /offline/);
  assert.strictEqual(failingStorage.has(CUSTOM_KEY), true);
  assert.strictEqual(failingStorage.has(FAVORITES_KEY), true);

  const conflictStorage = makeStorage({
    [CUSTOM_KEY]: JSON.stringify([legacyCustom]),
    [FAVORITES_KEY]: JSON.stringify([]),
  });
  const conflictLibrary = loadLibrary(conflictStorage, {
    migrateLegacyPromptColorSchemes: async () => ({ migration_complete: false, skipped_items: 1, color_schemes: [color('coral-sunrise', false)] }),
    getPromptColorSchemes: async () => ({ color_schemes: [] }),
  });
  const conflictSchemes = await conflictLibrary.ensureColorSchemes();
  assert.strictEqual(conflictSchemes.length, 1);
  assert.strictEqual(conflictSchemes[0].id, 'coral-sunrise');
  assert.strictEqual(conflictStorage.has(CUSTOM_KEY), true);
  assert.strictEqual(conflictStorage.has(FAVORITES_KEY), true);

  console.log('prompt color frontend migration: ok');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});

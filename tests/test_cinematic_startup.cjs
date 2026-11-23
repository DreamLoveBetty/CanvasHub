// Mini App (index.html) startup must load cinematic dependencies and keep
// boot errors attributable. Tests drive the real page scripts in document
// order against a document built from the real HTML. They do not stub
// switchCinematicSection or swallow a missing script.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { EventEmitter } = require('node:events');

const ROOT = path.join(__dirname, '..');
const INDEX = path.join(ROOT, 'frontend/index.html');

function readIndex() {
  return fs.readFileSync(INDEX, 'utf8');
}

function scriptSources(html) {
  return [...html.matchAll(/<script src="(scripts\/[^"]+)"/g)].map((match) => match[1].split('?')[0]);
}

function inlineScripts(html) {
  const out = [];
  const re = /<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi;
  let match;
  while ((match = re.exec(html))) {
    if (/\bsrc\s*=/.test(match[0])) continue;
    out.push(match[1]);
  }
  return out;
}

function classList(el) {
  const tokens = new Set(String(el.className || '').split(/\s+/).filter(Boolean));
  const syncFromEl = () => {
    tokens.clear();
    String(el.className || '').split(/\s+/).filter(Boolean).forEach((name) => tokens.add(name));
  };
  const sync = () => {
    el.className = [...tokens].join(' ');
  };
  return {
    add(...names) { syncFromEl(); names.forEach((n) => tokens.add(n)); sync(); },
    remove(...names) { syncFromEl(); names.forEach((n) => tokens.delete(n)); sync(); },
    contains(name) { syncFromEl(); return tokens.has(name); },
    toggle(name, force) {
      syncFromEl();
      const should = force === undefined ? !tokens.has(name) : !!force;
      if (should) tokens.add(name); else tokens.delete(name);
      sync();
      return should;
    },
  };
}

function styleBag() {
  const props = Object.create(null);
  const style = {
    display: '',
    cssText: '',
    setProperty(name, value) { props[name] = String(value ?? ''); },
    getPropertyValue(name) { return props[name] || ''; },
    removeProperty(name) { const prev = props[name]; delete props[name]; return prev || ''; },
  };
  return style;
}

function parseHtmlDocument(html) {
  const byId = new Map();
  const all = [];
  const documentElement = makeEl('html');
  const head = makeEl('head');
  const body = makeEl('body');
  documentElement.appendChild(head);
  documentElement.appendChild(body);

  function makeEl(tag, attrs = {}) {
    const el = {
      tagName: String(tag || 'div').toUpperCase(),
      id: '',
      className: attrs.class || '',
      name: attrs.name || '',
      hidden: Object.prototype.hasOwnProperty.call(attrs, 'hidden'),
      value: attrs.value || '',
      disabled: false,
      checked: Object.prototype.hasOwnProperty.call(attrs, 'checked'),
      textContent: '',
      innerHTML: '',
      src: attrs.src || '',
      href: attrs.href || '',
      placeholder: attrs.placeholder || '',
      type: attrs.type || '',
      dataset: {},
      style: styleBag(),
      children: [],
      childNodes: [],
      parentNode: null,
      attributes: { ...attrs },
      getBoundingClientRect() {
        return { top: 80, bottom: 640, left: 0, right: 390, width: 390, height: 560 };
      },
      focus() {},
      scrollIntoView() {},
      scrollTo() {},
      blur() {},
      _listeners: Object.create(null),
      addEventListener(type, fn) {
        if (typeof fn !== 'function') return;
        const key = String(type);
        if (!this._listeners[key]) this._listeners[key] = [];
        this._listeners[key].push(fn);
      },
      removeEventListener(type, fn) {
        const key = String(type);
        const list = this._listeners[key];
        if (!list) return;
        this._listeners[key] = list.filter((handler) => handler !== fn);
      },
      dispatchEvent(event) {
        const ev = event && typeof event === 'object' ? event : { type: event };
        ev.type = ev.type || 'click';
        ev.target = ev.target || this;
        ev.currentTarget = this;
        ev.defaultPrevented = !!ev.defaultPrevented;
        ev.stopPropagation = ev.stopPropagation || function stopPropagation() { ev._stopped = true; };
        ev.preventDefault = ev.preventDefault || function preventDefault() { ev.defaultPrevented = true; };
        const list = (this._listeners[ev.type] || []).slice();
        for (const fn of list) fn.call(this, ev);
        if (!ev._stopped && this.parentNode && typeof this.parentNode.dispatchEvent === 'function') {
          this.parentNode.dispatchEvent(ev);
        }
        return !ev.defaultPrevented;
      },
      click() {
        this.dispatchEvent({ type: 'click' });
      },
      setAttribute(name, value) {
        this.attributes[name] = value == null ? '' : String(value);
        if (name === 'id') {
          this.id = this.attributes[name];
          if (this.id) byId.set(this.id, this);
        }
        if (name === 'class') this.className = this.attributes[name];
        if (name === 'hidden') this.hidden = true;
        if (name.startsWith('data-')) {
          const key = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
          this.dataset[key] = this.attributes[name];
        }
      },
      getAttribute(name) {
        if (name === 'id') return this.id || null;
        if (name === 'class') return this.className || null;
        if (name === 'hidden') return this.hidden ? '' : null;
        return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
      },
      hasAttribute(name) {
        if (name === 'hidden') return !!this.hidden;
        return this.getAttribute(name) != null;
      },
      removeAttribute(name) {
        delete this.attributes[name];
        if (name === 'hidden') this.hidden = false;
      },
      toggleAttribute(name, force) {
        const should = force === undefined ? !this.hasAttribute(name) : !!force;
        if (should) this.setAttribute(name, '');
        else this.removeAttribute(name);
        return should;
      },
      appendChild(child) {
        if (child && child._isFragment) {
          const kids = child.children.slice();
          for (const kid of kids) this.appendChild(kid);
          return child;
        }
        if (child.parentNode) child.parentNode.removeChild(child);
        child.parentNode = this;
        this.children.push(child);
        this.childNodes.push(child);
        return child;
      },
      removeChild(child) {
        this.children = this.children.filter((c) => c !== child);
        this.childNodes = this.childNodes.filter((c) => c !== child);
        if (child.parentNode === this) child.parentNode = null;
        return child;
      },
      remove() {
        if (this.parentNode) this.parentNode.removeChild(this);
      },
      closest(sel) {
        let node = this;
        while (node) {
          if (matches(node, sel)) return node;
          node = node.parentNode;
        }
        return null;
      },
      querySelector(sel) { return queryAll(this, sel)[0] || null; },
      querySelectorAll(sel) { return queryAll(this, sel); },
    };
    el.classList = classList(el);
    if (el.tagName === 'SELECT') {
      Object.defineProperty(el, 'options', {
        configurable: true,
        get() { return this.children.filter((child) => child.tagName === 'OPTION'); },
      });
    }
    let innerHTMLValue = '';
    Object.defineProperty(el, 'innerHTML', {
      configurable: true,
      enumerable: true,
      get() { return innerHTMLValue; },
      set(value) {
        innerHTMLValue = value == null ? '' : String(value);
        if (innerHTMLValue === '') {
          for (const child of this.children.slice()) this.removeChild(child);
        }
      },
    });
    Object.defineProperty(el, 'id', {
      configurable: true,
      enumerable: true,
      get() { return this._id || ''; },
      set(value) {
        const next = String(value || '');
        if (this._id && byId.get(this._id) === this) byId.delete(this._id);
        this._id = next;
        if (next) byId.set(next, this);
      },
    });
    if (attrs.id) el.id = attrs.id;
    for (const [name, value] of Object.entries(attrs)) {
      if (name === 'id' || name === 'class') continue;
      if (name.startsWith('data-')) {
        const key = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        el.dataset[key] = value;
      }
    }
    if (el.id) byId.set(el.id, el);
    all.push(el);
    return el;
  }

  const fragment = html.replace(/<!--[\s\S]*?-->/g, '');
  const stack = [body];
  const tagRe = /<\/?([a-zA-Z0-9-]+)([^>]*)>|([^<]+)/g;
  let match;
  const voidTags = new Set(['meta','link','img','input','br','hr','source','area','base','col','embed','param','track','wbr']);
  let guard = 0;
  while ((match = tagRe.exec(fragment))) {
    if (++guard > fragment.length + 100) throw new Error('HTML parser stalled');
    if (match[0] === '') { tagRe.lastIndex += 1; continue; }
    if (match[3] != null) {
      const text = match[3];
      const parent = stack[stack.length - 1];
      if (parent && text.trim()) parent.textContent += text.replace(/\s+/g, ' ').trim();
      continue;
    }
    const tag = match[1].toLowerCase();
    const closing = match[0][1] === '/';
    if (tag === 'script' || tag === 'style') {
      if (!closing) {
        const close = `</${tag}>`;
        const at = fragment.toLowerCase().indexOf(close, tagRe.lastIndex);
        tagRe.lastIndex = at >= 0 ? at + close.length : fragment.length;
      }
      continue;
    }
    if (!/^[a-zA-Z]/.test(tag)) {
      continue;
    }
    if (closing) {
      for (let i = stack.length - 1; i >= 0; i--) {
        if (stack[i].tagName === tag.toUpperCase()) {
          stack.length = i;
          break;
        }
      }
      continue;
    }
    const attrs = {};
    const attrRe = /([:A-Za-z_0-9-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g;
    let am;
    while ((am = attrRe.exec(match[2] || ''))) {
      attrs[am[1]] = am[2] ?? am[3] ?? am[4] ?? '';
    }
    const el = makeEl(tag, attrs);
    let parent = stack[stack.length - 1];
    if (tag === 'html') {
      Object.assign(documentElement, { id: el.id, className: el.className, dataset: el.dataset, style: el.style, classList: el.classList });
      continue;
    }
    if (tag === 'head') { parent = documentElement; stack.push(head); continue; }
    if (tag === 'body') { parent = documentElement; stack.push(body); continue; }
    if (tag === 'head' || parent === head) parent = head;
    parent.appendChild(el);
    if (!voidTags.has(tag) && !String(match[0]).endsWith('/>')) stack.push(el);
  }

  function parseSimpleSelector(part) {
    const spec = { tag: null, id: null, classes: [], attrs: [], lastChild: false };
    let rest = part.trim();
    if (rest.endsWith(':last-child')) {
      spec.lastChild = true;
      rest = rest.slice(0, -':last-child'.length);
    }
    const tagMatch = rest.match(/^([a-zA-Z][\w-]*)/);
    if (tagMatch) {
      spec.tag = tagMatch[1].toUpperCase();
      rest = rest.slice(tagMatch[1].length);
    }
    const idMatch = rest.match(/^#([A-Za-z_][\w-]*)/);
    if (idMatch) {
      spec.id = idMatch[1];
      rest = rest.slice(idMatch[0].length);
    }
    let bit;
    const bitRe = /\.([A-Za-z_][\w-]*)|\[([A-Za-z_][\w-]*)([~|^$*]?=)?(?:"([^"]*)"|'([^']*)'|([^\]]*))?\]/g;
    while ((bit = bitRe.exec(rest))) {
      if (bit[1]) spec.classes.push(bit[1]);
      else spec.attrs.push({ name: bit[2], op: bit[3] || '', value: bit[4] ?? bit[5] ?? bit[6] ?? '' });
    }
    return spec;
  }

  function matches(el, selector) {
    if (!el || !el.tagName) return false;
    const parts = String(selector).trim().split(/\s+/).filter(Boolean);
    // single compound for .closest / simple matches
    if (parts.length === 1) return matchesCompound(el, parseSimpleSelector(parts[0]));
    // descendant: used only via queryAll
    return matchesCompound(el, parseSimpleSelector(parts[parts.length - 1]));
  }

  function matchesCompound(el, spec) {
    if (spec.tag && el.tagName !== spec.tag) return false;
    if (spec.id && el.id !== spec.id) return false;
    if (spec.classes.some((name) => !String(el.className || '').split(/\s+/).includes(name))) return false;
    for (const attr of spec.attrs) {
      const actual = el.getAttribute(attr.name);
      if (attr.op === '') {
        if (actual == null) return false;
      } else if (actual != el.value && actual !== attr.value && String(actual || '') !== attr.value) {
        if (attr.op === '=' && actual !== attr.value) return false;
      }
    }
    if (spec.lastChild) {
      const parent = el.parentNode;
      if (!parent || parent.children[parent.children.length - 1] !== el) return false;
    }
    return true;
  }

  function queryAll(root, selector) {
    const groups = String(selector).split(',').map((s) => s.trim()).filter(Boolean);
    const found = [];
    for (const group of groups) {
      const parts = group.split(/\s+/).filter(Boolean).map(parseSimpleSelector);
      const walk = (node, index) => {
        for (const child of node.children || []) {
          const matched = matchesCompound(child, parts[index]);
          if (matched && index === parts.length - 1) found.push(child);
          walk(child, matched ? Math.min(index + 1, parts.length - 1) === index && !matched ? index : (matched ? index + 1 : index) : index);
          // simpler recursive descendant search:
        }
      };
      // Correct descendant query:
      const collect = (node, partIndex, depth) => {
        if (!node || depth > 80) return;
        for (const child of node.children || []) {
          if (matchesCompound(child, parts[partIndex])) {
            if (partIndex === parts.length - 1) found.push(child);
            else collect(child, partIndex + 1, depth + 1);
          }
          collect(child, partIndex, depth + 1);
        }
      };
      collect(root, 0, 0);
    }
    return found;
  }

  const document = {
    documentElement,
    head,
    body,
    readyState: 'loading',
    getElementById: (id) => byId.get(String(id)) || null,
    querySelector(sel) {
      if (String(sel).startsWith('#') && !/\s/.test(sel) && !sel.includes('[')) return byId.get(sel.slice(1)) || null;
      return queryAll(this.documentElement || this, sel)[0] || null;
    },
    querySelectorAll(sel) { return queryAll(this.documentElement || this, sel); },
    createElement(tag) { return makeEl(tag); },
    createDocumentFragment() {
      const frag = makeEl('#fragment');
      frag._isFragment = true;
      return frag;
    },
    addEventListener(type, fn, options) { this._ee.on(type, fn); this._once = this._once || {}; if (options && options.once) this._once[type] = this._once[type] || new Set(), this._once[type].add(fn); },
    removeEventListener(type, fn) { this._ee.off(type, fn); },
    dispatchEvent(event) {
      const type = event.type || event;
      const listeners = this._ee.listeners(type).slice();
      for (const fn of listeners) {
        fn(event);
        if (this._once && this._once[type] && this._once[type].has(fn)) {
          this._ee.off(type, fn);
          this._once[type].delete(fn);
        }
      }
      return true;
    },
    _ee: new EventEmitter(),
    _once: {},
  };
  document.documentElement.dataset = documentElement.dataset;
  return { document, byId, all, queryAll };
}

function makeWindow(html, { layoutMode = 'cinematic', cinematicSection = 'records', settings = 'default', mobileViewport = true } = {}) {
  const { document, all } = parseHtmlDocument(html);
  const storedSettings = settings === 'none'
    ? null
    : (settings && typeof settings === 'object')
      ? settings
      : {
          themeVersion: 2,
          theme: 'skeuo-tech',
          layoutMode,
          cinematicSection,
          cinematicProvider: 'google',
        };
  const store = {};
  if (storedSettings) store.miniapp_ui_settings_v1 = JSON.stringify(storedSettings);
  const localStorage = {
    getItem: (k) => (Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
  };
  const windowEvents = new EventEmitter();
  const windowObj = {};
  const ctx = {
    window: windowObj,
    document,
    localStorage,
    console,
    setTimeout(fn) { const id = setTimeout(() => { try { fn(); } catch (error) { ctx.__asyncErrors.push(error); } }, 0); return id; },
    clearTimeout,
    setInterval() { return 0; },
    clearInterval() {},
    requestAnimationFrame(fn) { try { fn(0); } catch (error) { ctx.__asyncErrors.push(error); } return 1; },
    cancelAnimationFrame() {},
    matchMedia: (query) => ({
      matches: mobileViewport && /max-width:\s*768px/.test(query),
      media: query,
      addListener() {},
      removeListener() {},
      addEventListener() {},
      removeEventListener() {},
    }),
    Telegram: { WebApp: { initData: '', ready() {}, expand() {}, themeParams: {} } },
    fetch: async (url) => ({
      ok: true,
      status: 200,
      json: async () => ({}),
      text: async () => '',
    }),
    alert() {},
    confirm() { return false; },
    prompt() { return null; },
    CSS: { escape: (s) => String(s) },
    URL,
    URLSearchParams,
    JSON,
    Math,
    Date,
    Array,
    Object,
    String,
    Number,
    Boolean,
    Error,
    TypeError,
    ReferenceError,
    Promise,
    Map,
    Set,
    WeakMap,
    WeakSet,
    Symbol,
    RegExp,
    parseInt,
    parseFloat,
    isNaN,
    isFinite,
    encodeURIComponent,
    decodeURIComponent,
    undefined,
    navigator: { userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15' },
    location: { href: 'http://127.0.0.1:18463/', search: '', hash: '', pathname: '/', protocol: 'http:', host: '127.0.0.1:18463' },
    history: { replaceState() {}, pushState() {} },
    Image: function Image() { this.onload = null; this.src = ''; },
    Blob: class Blob {
      constructor(parts = [], options = {}) {
        this._parts = parts;
        this.type = (options && options.type) || '';
        this.size = parts.reduce((sum, part) => sum + String(part || '').length, 0);
        this._dataUrl = '';
      }
    },
    FileReader: class FileReader {
      constructor() {
        this.onload = null;
        this.onerror = null;
        this.result = null;
      }
      readAsDataURL(blob) {
        Promise.resolve().then(() => {
          this.result = (blob && blob._dataUrl) || 'data:image/png;base64,AAA';
          if (typeof this.onload === 'function') this.onload({ target: this });
        });
      }
    },
    Headers: class Headers {
      constructor(init = {}) {
        this._map = new Map();
        Object.entries(init || {}).forEach(([key, value]) => this.set(key, value));
      }
      set(key, value) { this._map.set(String(key).toLowerCase(), String(value)); }
      get(key) { return this._map.get(String(key).toLowerCase()); }
    },
    CustomEvent: class CustomEvent {
      constructor(type, init = {}) { this.type = type; this.detail = init.detail; this.bubbles = !!init.bubbles; }
    },
    Event: class Event { constructor(type) { this.type = type; } },
    getComputedStyle() { return { getPropertyValue() { return ''; } }; },
    innerWidth: 390,
    innerHeight: 844,
    scrollY: 0,
    addEventListener(type, fn) { windowEvents.on(type, fn); },
    removeEventListener(type, fn) { windowEvents.off(type, fn); },
    dispatchEvent(event) { windowEvents.emit(event.type, event); return true; },
    __asyncErrors: [],
  };
  ctx.window = ctx;
  ctx.globalThis = ctx;
  ctx.self = ctx;
  ctx.document.defaultView = ctx;
  const context = vm.createContext(ctx);
  bindInlineDomHandlers(context, all);
  return context;
}

function bindInlineDomHandlers(ctx, elements) {
  for (const el of elements || []) {
    const src = el.attributes && el.attributes.onclick;
    if (!src) continue;
    el.addEventListener('click', function (event) {
      ctx.__inlineEventTarget = el;
      ctx.__inlineEvent = event;
      ctx.__inlineHandlerSource = src;
      vm.runInContext(
        '(function(event){ eval(__inlineHandlerSource); }).call(__inlineEventTarget, __inlineEvent)',
        ctx
      );
    });
  }
}

function loadInlineBoot(ctx, html) {
  const scripts = inlineScripts(html);
  assert.ok(scripts[0] && scripts[0].includes('showBootError'), 'index.html must ship the boot error hook first');
  vm.runInContext(scripts[0], ctx, { filename: 'index.html:boot-error' });
}

function loadAppScripts(ctx, html, { omit = [], runBootstrap = false } = {}) {
  const sources = scriptSources(html).filter((src) => !omit.includes(src));
  const loaded = [];
  for (const src of sources) {
    const code = fs.readFileSync(path.join(ROOT, 'frontend', src), 'utf8');
    const filename = src;
    const body = (!runBootstrap && src === 'scripts/bootstrap.js')
      ? code.replace(/\n\s*bootstrapApp\(\);\s*$/, '\n')
      : code;
    vm.runInContext(body, ctx, { filename });
    loaded.push(src);
  }
  return loaded;
}

function bootErrorText(ctx) {
  const box = ctx.document.getElementById('bootErrorBox');
  return box ? String(box.textContent || '') : '';
}

function comfyHistoryItem() {
  return {
    task_id: 'fixture-comfy-image-20261119',
    timestamp: 1763540000,
    status: 'succeeded',
    type: 'comfy',
    prompt: 'cinematic comfy still fixture',
    params: {
      comfy_output_kind: 'image',
      width: 1024,
      height: 1024,
      comfy_image: { filename: 'comfy_fixture_00001.png', subfolder: '', type: 'output' },
    },
    output_file: 'comfy_fixture_00001.png',
    output_files: ['comfy_fixture_00001.png'],
    result_files: ['comfy_fixture_00001.png'],
    image_paths: ['/image/comfy_fixture_00001.png'],
  };
}

function bootCinematicApp(options = {}) {
  const html = readIndex();
  const ctx = makeWindow(html, {
    layoutMode: options.layoutMode || 'cinematic',
    cinematicSection: options.cinematicSection || 'records',
    settings: options.settings || 'default',
    mobileViewport: options.mobileViewport !== false,
  });
  loadInlineBoot(ctx, html);
  const inlines = inlineScripts(html);
  if (inlines[1]) vm.runInContext(inlines[1], ctx, { filename: 'index.html:layout' });
  const loaded = loadAppScripts(ctx, html, { omit: options.omit || [], runBootstrap: false });
  vm.runInContext(`
    loadUiSettings();
    applyPersistedSettings();
  `, ctx);
  return { html, ctx, loaded };
}

function renderComfyHistory(ctx, item = comfyHistoryItem()) {
  ctx.__historyFixture = item;
  return vm.runInContext(`
    (function () {
      applyHistoryRecords([window.__historyFixture]);
      const card = document.querySelector('#cinematicHistoryList .cinematic-record-card');
      const body = card && card.querySelector('.cinematic-record-body');
      const media = card && card.querySelector('.cinematic-record-media, button, .cinematic-record-thumb');
      return {
        cardCount: document.querySelectorAll('#cinematicHistoryList .cinematic-record-card').length,
        title: card ? (card.querySelector('.cinematic-record-title') || {}).textContent || '' : '',
        hasBody: !!body,
        hasMedia: !!media,
      };
    })()
  `, ctx);
}

function clickRecordBody(ctx) {
  const body = ctx.document.querySelector('#cinematicHistoryList .cinematic-record-body');
  if (!body) throw new Error('expected a rendered cinematic record body');
  body.click();
}

function viewerState(ctx) {
  return vm.runInContext(`
    (function () {
      const page = document.getElementById('cinematicViewerPage');
      return {
        open: !!(page && page.classList.contains('is-open')),
        ariaHidden: page ? page.getAttribute('aria-hidden') : null,
      };
    })()
  `, ctx);
}

function layoutSnapshot(ctx) {
  return vm.runInContext(`
    (function () {
      let stored = null;
      try { stored = JSON.parse(localStorage.getItem('miniapp_ui_settings_v1') || 'null'); } catch (e) {}
      const shell = document.getElementById('cinematicShell');
      return {
        dataset: document.documentElement.dataset.layout || '',
        current: typeof currentLayoutMode === 'string' ? currentLayoutMode : '',
        stored: stored && stored.layoutMode,
        shellHidden: !!(shell && shell.getAttribute('aria-hidden') === 'true'),
        records: !!(document.getElementById('cinematicRecordsSection') && document.getElementById('cinematicRecordsSection').classList.contains('is-active')),
        hasLayoutSelect: !!document.getElementById('layoutModeSelect'),
        hasSwitchClassic: !!document.querySelector('[onclick="switchToClassicFromCinematicMenu()"]'),
      };
    })()
  `, ctx);
}


function installSubmitAndAssetMocks(ctx, options = {}) {
  const imageBodies = options.imageBodies || {};
  const imageFailures = options.imageFailures || {};
  ctx.__fetchCalls = [];
  const previous = ctx.fetch;
  ctx.fetch = async (url, request = {}) => {
    const path = String(url || '');
    ctx.__fetchCalls.push({ url: path, method: request.method || 'GET', body: request.body || '' });
    if (Object.prototype.hasOwnProperty.call(imageFailures, path)) {
      const failure = imageFailures[path];
      if (failure === 'network') throw new Error('Failed to fetch');
      const status = Number(failure) || 500;
      return {
        ok: false,
        status,
        json: async () => ({}),
        text: async () => '',
        blob: async () => { throw new Error('HTTP ' + status); },
      };
    }
    const matchedImage = Object.prototype.hasOwnProperty.call(imageBodies, path)
      || /\/image\/|\/gpt_outputs\//.test(path);
    if (matchedImage && request.method !== 'POST') {
      const dataUrl = imageBodies[path] || 'data:image/png;base64,HISTREF';
      const blob = new ctx.Blob(['img']);
      blob._dataUrl = dataUrl;
      return { ok: true, status: 200, blob: async () => blob, json: async () => ({}), text: async () => '' };
    }
    if (path.includes('/api/gpt/edit') || path.includes('/api/gpt/generate') || path === '/edit' || path === '/generate') {
      return { ok: true, status: 200, json: async () => ({ status: 'ok', task_id: 'task-fixture-1' }), text: async () => '' };
    }
    if (path.includes('/api/status/')) {
      return { ok: true, status: 200, json: async () => ({ status: 'succeeded_no_telegram', task_id: 'task-fixture-1' }), text: async () => '' };
    }
    if (path.includes('/api/comfy/workflows')) {
      return { ok: true, status: 200, json: async () => ({ workflows: ['demo_workflow.json'] }), text: async () => '' };
    }
    if (typeof previous === 'function') return previous(url, request);
    return { ok: true, status: 200, json: async () => ({}), text: async () => '' };
  };
}


function hostValue(value) {
  return JSON.parse(JSON.stringify(value));
}

function submitCalls(ctx) {
  const calls = ctx.__fetchCalls || [];
  return {
    edit: calls.filter((call) => call.method === 'POST' && (call.url === '/edit' || String(call.url).endsWith('/edit')) && !String(call.url).includes('/api/gpt/')),
    gptEdit: calls.filter((call) => String(call.url).includes('/api/gpt/edit')),
    gptGen: calls.filter((call) => String(call.url).includes('/api/gpt/generate')),
    generate: calls.filter((call) => call.url === '/generate' || (String(call.url).endsWith('/generate') && !String(call.url).includes('/api/gpt/'))),
  };
}

function googleHistoryItem(overrides = {}) {
  return {
    task_id: 'fixture-google-gen-continue',
    timestamp: 1763540000,
    status: 'succeeded',
    type: 'google-gen',
    prompt: 'continue edit provider fixture',
    params: { ratio: '16:9', model: 'gemini-3-pro-image', quality: '2k' },
    output_file: 'google_fixture_00001.png',
    output_files: ['google_fixture_00001.png'],
    image_paths: ['/image/google_fixture_00001.png'],
    ...overrides,
  };
}

function gptHistoryItem(overrides = {}) {
  return {
    task_id: 'fixture-gpt-route-1',
    timestamp: 1763540000,
    status: 'succeeded',
    type: 'gpt',
    prompt: 'gpt refill fixture',
    params: {
      ratio: '16:9',
      resolution: '2k',
      quality: 'high',
      image_count: 3,
      moderation: 'low',
      gpt_provider_route: 'chatgpt_pool',
      use_third_party_api: false,
    },
    output_file: 'gpt_fixture_00001.png',
    output_files: ['gpt_fixture_00001.png'],
    ...overrides,
  };
}

async function flushPromises(times = 8) {
  for (let i = 0; i < times; i++) await Promise.resolve();
}

function clickHistoryRetry(ctx) {
  const button = ctx.document.querySelector('#cinematicHistoryList .cinematic-record-action');
  if (!button) throw new Error('expected a cinematic history retry button');
  button.click();
}

function installComfyMocks(ctx) {
  ctx.__fetchCalls = [];
  const previous = ctx.fetch;
  ctx.fetch = async (url, options = {}) => {
    const path = String(url || '');
    ctx.__fetchCalls.push({ url: path, method: (options.method || 'GET'), body: options.body || '' });
    if (path.includes('/api/comfy/workflows')) {
      return { ok: true, status: 200, json: async () => ({ workflows: ['demo_workflow.json'] }), text: async () => '' };
    }
    if (path.includes('/api/comfy/run')) {
      return { ok: true, status: 200, json: async () => ({ status: 'queued', task_id: 'comfy-task-1', prompt_id: 'comfy-prompt-1' }), text: async () => '' };
    }
    if (path.includes('/api/comfy/history')) {
      const id = 'comfy-prompt-1';
      return { ok: true, status: 200, json: async () => ({ [id]: { status: { completed: true }, outputs: {} } }), text: async () => '' };
    }
    if (typeof previous === 'function') return previous(url, options);
    return { ok: true, status: 200, json: async () => ({}), text: async () => '' };
  };
}

function comfyWorkbenchState(ctx) {
  return vm.runInContext(`
    (function () {
      const bench = document.getElementById('cinematicComfyWorkbench');
      const view = document.getElementById('view-comfy');
      return {
        layout: document.documentElement.dataset.layout || '',
        open: !!(bench && bench.classList.contains('is-open') && bench.getAttribute('aria-hidden') !== 'true'),
        bodyClass: !!(document.body && document.body.classList.contains('is-cinematic-comfy-workbench')),
        viewActive: !!(view && (view.classList.contains('active') || view.classList.contains('is-cinematic-workbench'))),
        prompt: (document.getElementById('comfyPrompt') || {}).value || '',
        workflow: (document.getElementById('comfyWorkflow') || {}).value || '',
      };
    })()
  `, ctx);
}


test('boot error toast includes the failing script filename and line', () => {
  const html = readIndex();
  const ctx = makeWindow(html);
  loadInlineBoot(ctx, html);
  ctx.document.readyState = 'complete';
  ctx.document.dispatchEvent({ type: 'DOMContentLoaded' });
  ctx.dispatchEvent({
    type: 'error',
    message: "ReferenceError: Can't find variable: switchCinematicSection",
    filename: 'http://127.0.0.1:18463/scripts/cinematic-composer.js?v=cache-key',
    lineno: 451,
    colno: 12,
  });
  const text = bootErrorText(ctx);
  assert.match(text, /启动错误：/);
  assert.match(text, /Can't find variable: switchCinematicSection|switchCinematicSection is not defined/);
  assert.match(text, /cinematic-composer\.js/);
  assert.match(text, /451/);
});

test('the first startup error stays visible when a later ReferenceError arrives', () => {
  const html = readIndex();
  const ctx = makeWindow(html);
  loadInlineBoot(ctx, html);
  ctx.document.dispatchEvent({ type: 'DOMContentLoaded' });
  ctx.dispatchEvent({
    type: 'error',
    message: 'SyntaxError: Unexpected token "."',
    filename: 'http://127.0.0.1:18463/scripts/cinematic-composer.js?v=old',
    lineno: 12,
    colno: 1,
  });
  ctx.dispatchEvent({
    type: 'error',
    message: "ReferenceError: Can't find variable: switchCinematicSection",
    filename: 'http://127.0.0.1:18463/scripts/bootstrap.js?v=cache-key',
    lineno: 83,
    colno: 3,
  });
  const text = bootErrorText(ctx);
  assert.match(text, /SyntaxError: Unexpected token/);
  assert.match(text, /cinematic-composer\.js/);
  assert.match(text, /12/);
  assert.match(text, /switchCinematicSection/);
});

test('a late error after DOMContentLoaded still mounts the toast', () => {
  const html = readIndex();
  const ctx = makeWindow(html);
  loadInlineBoot(ctx, html);
  ctx.document.readyState = 'complete';
  ctx.document.dispatchEvent({ type: 'DOMContentLoaded' });
  ctx.dispatchEvent({
    type: 'error',
    message: "ReferenceError: Can't find variable: switchCinematicSection",
    filename: 'scripts/cinematic-composer.js',
    lineno: 451,
    colno: 1,
  });
  const box = ctx.document.getElementById('bootErrorBox');
  assert.ok(box, 'boot error box should exist');
  assert.ok(box.parentNode === ctx.document.body, 'toast must be attached even after DOMContentLoaded');
  assert.match(String(box.textContent || ''), /cinematic-composer\.js/);
});

test('Cinematic startup uses the real composer and can switch sections without leaving Cinematic', () => {
  const html = readIndex();
  const ctx = makeWindow(html, { layoutMode: 'cinematic', cinematicSection: 'records' });
  loadInlineBoot(ctx, html);
  vm.runInContext(inlineScripts(html)[1], ctx, { filename: 'index.html:layout' });
  const loaded = loadAppScripts(ctx, html, { runBootstrap: false });
  assert.ok(loaded.includes('scripts/cinematic-composer.js'));
  assert.equal(vm.runInContext('typeof switchCinematicSection', ctx), 'function');
  assert.equal(vm.runInContext('typeof applyPersistedSettings', ctx), 'function');

  const result = vm.runInContext(`
    (function () {
      loadUiSettings();
      applyPersistedSettings();
      const sectionActive = (id) => document.getElementById(id)?.classList.contains('is-active');
      const before = {
        layout: document.documentElement.dataset.layout,
        records: sectionActive('cinematicRecordsSection'),
        discover: sectionActive('cinematicDiscoverSection'),
        spell: sectionActive('cinematicSpellSection'),
        dockHidden: !!document.querySelector('.cinematic-composer-dock')?.hidden,
      };
      switchCinematicSection('discover', false);
      const discover = {
        records: sectionActive('cinematicRecordsSection'),
        discover: sectionActive('cinematicDiscoverSection'),
        spell: sectionActive('cinematicSpellSection'),
        dockHidden: !!document.querySelector('.cinematic-composer-dock')?.hidden,
      };
      switchCinematicSection('spell', false);
      const spell = {
        records: sectionActive('cinematicRecordsSection'),
        discover: sectionActive('cinematicDiscoverSection'),
        spell: sectionActive('cinematicSpellSection'),
      };
      switchCinematicSection('records', false);
      applyLayoutMode('classic', false);
      return {
        before, discover, spell,
        afterForcedClassic: document.documentElement.dataset.layout,
        recordsRestored: sectionActive('cinematicRecordsSection'),
      };
    })()
  `, ctx);

  assert.equal(result.before.layout, 'cinematic');
  assert.equal(result.before.records, true);
  assert.equal(result.before.discover, false);
  assert.equal(result.discover.records, false);
  assert.equal(result.discover.discover, true);
  assert.equal(result.discover.dockHidden, true);
  assert.equal(result.spell.spell, true);
  assert.equal(result.spell.discover, false);
  assert.equal(result.afterForcedClassic, 'cinematic');
  assert.equal(result.recordsRestored, true);
});

test('a stored Classic preference is migrated to Cinematic and cannot be restored', () => {
  const html = readIndex();
  const ctx = makeWindow(html, { layoutMode: 'classic', cinematicSection: 'records' });
  loadInlineBoot(ctx, html);
  vm.runInContext(inlineScripts(html)[1], ctx, { filename: 'index.html:layout' });
  loadAppScripts(ctx, html, { runBootstrap: false });
  const result = vm.runInContext(`
    (function () {
      loadUiSettings();
      applyPersistedSettings();
      const started = document.documentElement.dataset.layout;
      let stored = null;
      try { stored = JSON.parse(localStorage.getItem('miniapp_ui_settings_v1') || 'null'); } catch (e) {}
      switchCinematicSection('spell', false);
      applyLayoutMode('classic', false);
      return {
        started,
        stored: stored && stored.layoutMode,
        spell: document.getElementById('cinematicSpellSection')?.classList.contains('is-active'),
        ended: document.documentElement.dataset.layout,
      };
    })()
  `, ctx);
  assert.equal(result.started, 'cinematic');
  assert.equal(result.stored, 'cinematic');
  assert.equal(result.spell, true);
  assert.equal(result.ended, 'cinematic');
});

test('a missing cinematic-composer script fails with that filename, not a bare identifier error', () => {
  const html = readIndex();
  const ctx = makeWindow(html, { layoutMode: 'cinematic' });
  loadInlineBoot(ctx, html);
  loadAppScripts(ctx, html, { omit: ['scripts/cinematic-composer.js'], runBootstrap: false });
  assert.equal(vm.runInContext('typeof switchCinematicSection', ctx), 'undefined');
  const result = vm.runInContext(`
    (function () {
      try {
        if (typeof loadUiSettings === 'function') loadUiSettings();
        if (typeof assertMiniappScriptContracts === 'function') assertMiniappScriptContracts();
        else if (typeof initAppUi === 'function') initAppUi();
        else applyPersistedSettings();
        return { ok: true };
      } catch (error) {
        return { ok: false, name: error.name, message: String(error && error.message || error) };
      }
    })()
  `, ctx);
  assert.equal(result.ok, false);
  assert.match(result.message, /cinematic-composer\.js/);
  assert.doesNotMatch(result.message, /Can't find variable: switchCinematicSection/);
});

test('a missing modal-view script still renders Comfy cards but opening one throws openDetailModal', () => {
  const { ctx, loaded } = bootCinematicApp({ omit: ['scripts/modal-view.js'] });
  assert.ok(!loaded.includes('scripts/modal-view.js'));
  assert.equal(vm.runInContext('typeof openDetailModal', ctx), 'undefined');
  assert.equal(vm.runInContext('typeof window.openDetailModal', ctx), 'undefined');
  const rendered = renderComfyHistory(ctx);
  assert.equal(rendered.cardCount, 1);
  assert.match(rendered.title, /ComfyUI|comfy/i);
  assert.equal(rendered.hasBody, true);
  assert.throws(
    () => clickRecordBody(ctx),
    (error) => {
      assert.equal(error.name, 'ReferenceError');
      assert.match(String(error.message || error), /openDetailModal/);
      assert.doesNotMatch(String(error.message || error), /is not a function/);
      return true;
    }
  );
  assert.equal(viewerState(ctx).open, false);
});

test('Cinematic startup with a Comfy history card opens and closes the real detail viewer', () => {
  const { ctx, loaded } = bootCinematicApp();
  assert.ok(loaded.includes('scripts/modal-view.js'));
  assert.ok(loaded.includes('scripts/cinematic-history-stream.js'));
  assert.ok(loaded.includes('scripts/cinematic-detail.js'));
  assert.equal(vm.runInContext('typeof openDetailModal', ctx), 'function');
  assert.equal(vm.runInContext('typeof window.openDetailModal', ctx), 'function');
  assert.equal(vm.runInContext('typeof openCinematicViewer', ctx), 'function');
  const rendered = renderComfyHistory(ctx);
  assert.equal(rendered.cardCount, 1);
  assert.match(rendered.title, /ComfyUI|comfy/i);
  clickRecordBody(ctx);
  const opened = viewerState(ctx);
  assert.equal(opened.open, true);
  assert.equal(opened.ariaHidden, 'false');
  const afterClose = vm.runInContext(`
    (function () {
      closeCinematicViewer();
      const page = document.getElementById('cinematicViewerPage');
      switchCinematicSection('discover', false);
      const discover = document.getElementById('cinematicDiscoverSection')?.classList.contains('is-active');
      switchCinematicSection('records', false);
      const records = document.getElementById('cinematicRecordsSection')?.classList.contains('is-active');
      applyLayoutMode('classic', false);
      return {
        viewerOpen: !!(page && page.classList.contains('is-open')),
        ariaHidden: page ? page.getAttribute('aria-hidden') : null,
        discover,
        records,
        layout: document.documentElement.dataset.layout,
      };
    })()
  `, ctx);
  assert.equal(afterClose.viewerOpen, false);
  assert.equal(afterClose.ariaHidden, 'true');
  assert.equal(afterClose.discover, true);
  assert.equal(afterClose.records, true);
  assert.equal(afterClose.layout, 'cinematic');
});

test('a missing modal-view script fails the startup contract with that filename, not only a late click error', () => {
  const html = readIndex();
  const ctx = makeWindow(html, { layoutMode: 'cinematic' });
  loadInlineBoot(ctx, html);
  loadAppScripts(ctx, html, { omit: ['scripts/modal-view.js'], runBootstrap: false });
  const result = vm.runInContext(`
    (function () {
      try {
        if (typeof loadUiSettings === 'function') loadUiSettings();
        if (typeof assertMiniappScriptContracts === 'function') assertMiniappScriptContracts();
        else if (typeof initAppUi === 'function') initAppUi();
        else applyPersistedSettings();
        return { ok: true };
      } catch (error) {
        return { ok: false, name: error.name, message: String(error && error.message || error) };
      }
    })()
  `, ctx);
  assert.equal(result.ok, false);
  assert.equal(result.name, 'ReferenceError');
  assert.match(result.message, /openDetailModal/);
  assert.match(result.message, /modal-view\.js/);
  assert.doesNotMatch(result.message, /Can't find variable: openDetailModal/);
});

test('index defaults to Cinematic when no UI preference is stored', () => {
  const html = readIndex();
  const ctx = makeWindow(html, { settings: 'none' });
  loadInlineBoot(ctx, html);
  vm.runInContext(inlineScripts(html)[1], ctx, { filename: 'index.html:layout' });
  loadAppScripts(ctx, html, { runBootstrap: false });
  vm.runInContext('loadUiSettings(); applyPersistedSettings();', ctx);
  const snap = layoutSnapshot(ctx);
  assert.equal(snap.dataset, 'cinematic');
  assert.equal(snap.current, 'cinematic');
  assert.equal(snap.shellHidden, false);
  assert.equal(snap.hasLayoutSelect, false);
  assert.equal(snap.hasSwitchClassic, false);
});

test('an invalid stored layout still boots and stays on Cinematic', () => {
  const html = readIndex();
  const ctx = makeWindow(html, { settings: { themeVersion: 2, theme: 'skeuo-tech', layoutMode: 'nope' } });
  loadInlineBoot(ctx, html);
  vm.runInContext(inlineScripts(html)[1], ctx, { filename: 'index.html:layout' });
  loadAppScripts(ctx, html, { runBootstrap: false });
  vm.runInContext('loadUiSettings(); applyPersistedSettings();', ctx);
  const snap = layoutSnapshot(ctx);
  assert.equal(snap.dataset, 'cinematic');
  assert.equal(snap.current, 'cinematic');
  assert.equal(snap.stored, 'cinematic');
});

test('a wide viewport still locks Cinematic and ignores Classic API calls', () => {
  const html = readIndex();
  const ctx = makeWindow(html, { settings: 'none', mobileViewport: false });
  loadInlineBoot(ctx, html);
  vm.runInContext(inlineScripts(html)[1], ctx, { filename: 'index.html:layout' });
  loadAppScripts(ctx, html, { runBootstrap: false });
  vm.runInContext(`
    loadUiSettings();
    applyPersistedSettings();
    if (typeof setLayoutMode === 'function') setLayoutMode('classic');
    if (typeof openWorkspace === 'function') openWorkspace('google');
    if (typeof applyLayoutMode === 'function') applyLayoutMode('classic', true);
  `, ctx);
  const snap = layoutSnapshot(ctx);
  assert.equal(snap.dataset, 'cinematic');
  assert.equal(snap.current, 'cinematic');
  assert.equal(snap.shellHidden, false);
  assert.equal(ctx.matchMedia('(max-width: 768px)').matches, false);
});

test('selecting Comfy in Cinematic opens a workbench panel and close returns without leaving Cinematic', async () => {
  const { ctx } = bootCinematicApp();
  installComfyMocks(ctx);
  vm.runInContext(`
    selectCinematicProvider('comfyui');
    setCinematicPromptText('workbench prompt fixture');
    submitCinematicComposer();
  `, ctx);
  await Promise.resolve();
  await Promise.resolve();
  const opened = comfyWorkbenchState(ctx);
  assert.equal(opened.layout, 'cinematic');
  assert.equal(opened.open, true);
  assert.equal(opened.bodyClass, true);
  assert.equal(opened.prompt, 'workbench prompt fixture');
  vm.runInContext('closeCinematicComfyWorkbench()', ctx);
  const closed = comfyWorkbenchState(ctx);
  assert.equal(closed.open, false);
  assert.equal(closed.bodyClass, false);
  assert.equal(closed.layout, 'cinematic');
  assert.equal(layoutSnapshot(ctx).dataset, 'cinematic');
});

test('Comfy history refill opens the cinematic workbench instead of Classic', async () => {
  const { ctx } = bootCinematicApp();
  installComfyMocks(ctx);
  const item = comfyHistoryItem();
  item.params.workflow = 'demo_workflow.json';
  item.prompt = 'history refill prompt';
  renderComfyHistory(ctx, item);
  assert.equal(layoutSnapshot(ctx).dataset, 'cinematic');
  await vm.runInContext('applyComfyItemToComposer(window.__historyFixture)', ctx);
  await Promise.resolve();
  const bench = comfyWorkbenchState(ctx);
  assert.equal(bench.layout, 'cinematic');
  assert.equal(bench.open, true);
  assert.equal(bench.prompt, 'history refill prompt');
  assert.equal(layoutSnapshot(ctx).dataset, 'cinematic');
});

test('Comfy workbench submit uses real runComfy and does not change layout', async () => {
  const { ctx } = bootCinematicApp();
  installComfyMocks(ctx);
  vm.runInContext(`
    selectCinematicProvider('comfyui');
    setCinematicPromptText('run comfy fixture');
    submitCinematicComposer();
  `, ctx);
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(comfyWorkbenchState(ctx).open, true);
  vm.runInContext(`
    const sel = document.getElementById('comfyWorkflow');
    if (sel) sel.value = 'demo_workflow.json';
    if (typeof pickComfyWorkflow === 'function') pickComfyWorkflow('demo_workflow.json');
    document.getElementById('btnComfy').click();
  `, ctx);
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  const runCalls = (ctx.__fetchCalls || []).filter((call) => String(call.url).includes('/api/comfy/run'));
  assert.equal(runCalls.length, 1);
  assert.match(String(runCalls[0].body || ''), /demo_workflow\\.json|run comfy fixture/);
  assert.equal(layoutSnapshot(ctx).dataset, 'cinematic');
  assert.equal(comfyWorkbenchState(ctx).open, true);
});

test('GPT route and Google edit feature pills stay in sync with classic fields', () => {
  const { ctx } = bootCinematicApp();
  vm.runInContext(`
    selectCinematicProvider('gpt');
    syncCinematicComposerUi();
  `, ctx);
  const routeWrap = ctx.document.getElementById('cinematicGptRouteWrap');
  assert.ok(routeWrap, 'expected cinematic GPT route pill');
  assert.equal(routeWrap.hidden, false);
  const poolOption = ctx.document.querySelector('#cinematicGptRouteMenu [data-gpt-route="chatgpt_pool"]');
  assert.ok(poolOption, 'expected chatgpt_pool route option');
  poolOption.click();
  assert.equal(ctx.document.getElementById('gptProviderRouteSelect').value, 'chatgpt_pool');
  assert.equal(vm.runInContext('gptState.gptProviderRoute', ctx), 'chatgpt_pool');
  assert.equal(layoutSnapshot(ctx).dataset, 'cinematic');

  vm.runInContext(`
    uploadedImages = [{ id: 1, base64: 'data:image/png;base64,AAA' }];
    selectCinematicProvider('google');
    syncCinematicComposerUi();
  `, ctx);
  const featureWrap = ctx.document.getElementById('cinematicEditFeatureWrap');
  assert.ok(featureWrap, 'expected cinematic Google edit feature pill');
  assert.equal(featureWrap.hidden, false);
  const upscaleOption = ctx.document.querySelector('#cinematicEditFeatureMenu [data-edit-feature="upscale"]');
  assert.ok(upscaleOption, 'expected upscale feature option');
  upscaleOption.click();
  assert.equal(ctx.document.getElementById('editFeature').value, 'upscale');
  assert.equal(vm.runInContext('editState.feature', ctx), 'upscale');
  assert.equal(layoutSnapshot(ctx).dataset, 'cinematic');
});

test('Google and GPT cinematic submit still call real provider paths', async () => {
  const { ctx } = bootCinematicApp();
  ctx.__fetchCalls = [];
  const previous = ctx.fetch;
  ctx.fetch = async (url, options = {}) => {
    const path = String(url || '');
    ctx.__fetchCalls.push({ url: path, method: (options.method || 'GET'), body: options.body || '' });
    if (path.includes('/generate') || path.includes('/edit') || path.includes('/api/gpt/generate') || path.includes('/api/gpt/edit')) {
      return { ok: true, status: 200, json: async () => ({ status: 'ok', task_id: 'task-fixture-1' }), text: async () => '' };
    }
    if (path.includes('/api/status/')) {
      return { ok: true, status: 200, json: async () => ({ status: 'succeeded_no_telegram', task_id: 'task-fixture-1' }), text: async () => '' };
    }
    if (typeof previous === 'function') return previous(url, options);
    return { ok: true, status: 200, json: async () => ({}), text: async () => '' };
  };

  vm.runInContext(`
    selectCinematicProvider('google');
    setCinematicPromptText('google gen fixture');
    submitCinematicComposer();
  `, ctx);
  await Promise.resolve();
  await Promise.resolve();
  const genCalls = (ctx.__fetchCalls || []).filter((call) => String(call.url) === '/generate' || String(call.url).endsWith('/generate'));
  assert.equal(genCalls.length, 1);
  assert.match(String(genCalls[0].body || ''), /google gen fixture/);
  assert.equal(ctx.document.getElementById('genPrompt').value, 'google gen fixture');
  assert.equal(layoutSnapshot(ctx).dataset, 'cinematic');

  vm.runInContext(`
    uploadedImages = [{ id: 1, base64: 'data:image/png;base64,AAA' }];
    pickFeature('face_fix');
    setCinematicPromptText('google edit fixture');
    syncCinematicComposerUi();
    submitCinematicComposer();
  `, ctx);
  await Promise.resolve();
  await Promise.resolve();
  const editCalls = (ctx.__fetchCalls || []).filter((call) => String(call.url) === '/edit' || String(call.url).endsWith('/edit'));
  assert.equal(editCalls.length, 1);
  assert.match(String(editCalls[0].body || ''), /google edit fixture/);
  assert.match(String(editCalls[0].body || ''), /face_fix/);
  assert.equal(ctx.document.getElementById('editPrompt').value, 'google edit fixture');
  assert.equal(layoutSnapshot(ctx).dataset, 'cinematic');

  vm.runInContext(`
    uploadedImages = [];
    selectCinematicProvider('gpt');
    pickProviderRouteGpt('third_party_image_api');
    setCinematicPromptText('gpt gen fixture');
    syncCinematicComposerUi();
    submitCinematicComposer();
  `, ctx);
  await Promise.resolve();
  await Promise.resolve();
  const gptCalls = (ctx.__fetchCalls || []).filter((call) => String(call.url).includes('/api/gpt/generate'));
  assert.equal(gptCalls.length, 1);
  assert.match(String(gptCalls[0].body || ''), /gpt gen fixture/);
  assert.equal(ctx.document.getElementById('gptPrompt').value, 'gpt gen fixture');
  assert.equal(vm.runInContext('gptState.gptProviderRoute', ctx), 'third_party_image_api');
  assert.equal(layoutSnapshot(ctx).dataset, 'cinematic');
});

test('cinematic detail continue-edit stays in Cinematic and fills the composer', async () => {
  const { ctx } = bootCinematicApp();
  renderComfyHistory(ctx, {
    task_id: 'fixture-google-gen-20261120',
    timestamp: 1763540000,
    status: 'succeeded',
    type: 'google-gen',
    prompt: 'continue edit fixture',
    params: { ratio: '16:9', model: 'gemini-3-pro-image' },
    output_file: 'google_fixture_00001.png',
    output_files: ['google_fixture_00001.png'],
    image_paths: ['/image/google_fixture_00001.png'],
  });
  vm.runInContext(`
    loadImageAsDataUrl = async function () { return 'data:image/png;base64,AAA'; };
  `, ctx);
  clickRecordBody(ctx);
  assert.equal(viewerState(ctx).open, true);
  await vm.runInContext('continueEditFromCinematicViewer()', ctx);
  await Promise.resolve();
  await Promise.resolve();
  const result = vm.runInContext(`
    ({
      layout: document.documentElement.dataset.layout,
      viewerOpen: !!(document.getElementById('cinematicViewerPage') && document.getElementById('cinematicViewerPage').classList.contains('is-open')),
      prompt: (document.getElementById('cinematicPrompt') || {}).value || '',
      editPrompt: (document.getElementById('editPrompt') || {}).value || '',
      refs: uploadedImages.length,
    })
  `, ctx);
  assert.equal(result.layout, 'cinematic');
  assert.equal(result.viewerOpen, false);
  assert.equal(result.prompt, 'continue edit fixture');
  assert.equal(result.editPrompt, 'continue edit fixture');
  assert.equal(result.refs, 1);
});

function hasClassicSkinPicker(root) {
  if (!root) return false;
  const visit = (node) => {
    if (!node || !node.tagName) return false;
    if (node.id === 'skinSelect' || node.id === 'cinematicSkinSelect') return true;
    const onchange = node.attributes && node.attributes.onchange;
    if (onchange && String(onchange).includes('setSkin')) return true;
    const className = String(node.className || '');
    if (className.split(/\s+/).includes('menu-skin-select')) return true;
    return (node.children || []).some(visit);
  };
  return visit(root);
}

function themeSnapshot(ctx) {
  const snap = vm.runInContext(`
    (function () {
      let stored = null;
      try { stored = JSON.parse(localStorage.getItem('miniapp_ui_settings_v1') || 'null'); } catch (e) {}
      const colorButtons = [...document.querySelectorAll('#cinematicMenu [data-cinematic-color-scheme-option]')].map((button) => ({
        scheme: button.dataset.cinematicColorSchemeOption,
        active: button.classList.contains('is-active'),
        pressed: button.getAttribute('aria-pressed'),
      }));
      return {
        layout: document.documentElement.dataset.layout || '',
        skin: document.documentElement.dataset.skin || '',
        colorScheme: document.documentElement.dataset.cinematicColorScheme || '',
        storedTheme: stored && stored.theme,
        storedThemeVersion: stored && stored.themeVersion,
        storedColorScheme: stored && stored.cinematicColorScheme,
        storedProvider: stored && stored.cinematicProvider,
        storedGptRoute: stored && stored.gpt && stored.gpt.gptProviderRoute,
        hasSkinSelect: !!document.getElementById('skinSelect'),
        hasCinematicSkinSelect: !!document.getElementById('cinematicSkinSelect'),
        hasColorSection: !!document.querySelector('#cinematicMenu [aria-label="Cinematic 配色系统"]'),
        colorLabel: (document.getElementById('cinematicColorSystemCurrent') || {}).textContent || '',
        cinematicMenuText: (document.getElementById('cinematicMenu') || {}).textContent || '',
        mainMenuText: (document.getElementById('mainMenu') || {}).textContent || '',
        colorButtons,
      };
    })()
  `, ctx);
  snap.hasSkinPickerInCinematicMenu = hasClassicSkinPicker(ctx.document.getElementById('cinematicMenu'));
  snap.hasSkinPickerInMainMenu = hasClassicSkinPicker(ctx.document.getElementById('mainMenu'));
  return snap;
}

test('Cinematic menus have no Classic skin picker and keep color-scheme controls', () => {
  const { ctx } = bootCinematicApp();
  const snap = themeSnapshot(ctx);
  assert.equal(snap.layout, 'cinematic');
  assert.equal(snap.hasSkinSelect, false);
  assert.equal(snap.hasCinematicSkinSelect, false);
  assert.equal(snap.hasSkinPickerInCinematicMenu, false);
  assert.equal(snap.hasSkinPickerInMainMenu, false);
  assert.doesNotMatch(snap.cinematicMenuText, /风格皮肤|Skeuo Tech|Cassette Light|Midnight/);
  assert.doesNotMatch(snap.mainMenuText, /风格皮肤|Skeuo Tech|Cassette Light|Midnight/);
  assert.equal(snap.hasColorSection, true);
  assert.ok(snap.colorButtons.some((button) => button.scheme === 'aether-gold'));
  assert.ok(snap.colorButtons.some((button) => button.scheme === 'production-suite'));
  assert.ok(snap.colorButtons.some((button) => button.scheme === 'cinematic-lens'));
  assert.equal(snap.colorButtons.length, 3);
});

test('a stored Classic skin is normalized without dropping Cinematic color or other prefs', () => {
  const html = readIndex();
  const ctx = makeWindow(html, {
    settings: {
      themeVersion: 2,
      theme: 'midnight',
      layoutMode: 'cinematic',
      cinematicColorScheme: 'cinematic-lens',
      cinematicProvider: 'gpt',
      gpt: { gptProviderRoute: 'chatgpt_pool' },
    },
  });
  loadInlineBoot(ctx, html);
  vm.runInContext(inlineScripts(html)[1], ctx, { filename: 'index.html:layout' });
  assert.equal(ctx.document.documentElement.dataset.skin, 'skeuo-tech');
  loadAppScripts(ctx, html, { runBootstrap: false });
  vm.runInContext('loadUiSettings(); applyPersistedSettings();', ctx);
  const snap = themeSnapshot(ctx);
  assert.equal(snap.layout, 'cinematic');
  assert.equal(snap.skin, 'skeuo-tech');
  assert.equal(snap.storedTheme, 'skeuo-tech');
  assert.equal(snap.colorScheme, 'cinematic-lens');
  assert.equal(snap.storedColorScheme, 'cinematic-lens');
  assert.equal(snap.storedProvider, 'gpt');
  assert.equal(snap.storedGptRoute, 'chatgpt_pool');
  assert.equal(snap.hasSkinSelect, false);
  assert.equal(snap.hasCinematicSkinSelect, false);
  assert.equal(snap.colorLabel, 'Cinematic Lens');
  const lens = snap.colorButtons.find((button) => button.scheme === 'cinematic-lens');
  assert.ok(lens);
  assert.equal(lens.active, true);
  assert.equal(lens.pressed, 'true');
});

test('Cinematic color scheme clicks update the live theme and keep layout locked', () => {
  const { ctx } = bootCinematicApp();
  const option = ctx.document.querySelector('#cinematicMenu [data-cinematic-color-scheme-option="production-suite"]');
  assert.ok(option, 'expected Production Suite color option');
  option.click();
  const snap = themeSnapshot(ctx);
  assert.equal(snap.layout, 'cinematic');
  assert.equal(snap.colorScheme, 'production-suite');
  assert.equal(snap.storedColorScheme, 'production-suite');
  assert.equal(snap.colorLabel, 'Production Suite');
  assert.equal(snap.hasSkinSelect, false);
  assert.equal(snap.hasCinematicSkinSelect, false);
  const gold = ctx.document.querySelector('#cinematicMenu [data-cinematic-color-scheme-option="aether-gold"]');
  gold.click();
  const back = themeSnapshot(ctx);
  assert.equal(back.colorScheme, 'aether-gold');
  assert.equal(back.storedColorScheme, 'aether-gold');
  assert.equal(back.layout, 'cinematic');
  assert.equal(back.skin, 'skeuo-tech');
});

test('continue-edit from GPT or Comfy enters Google edit and submitEdit', async () => {
  for (const startProvider of ['gpt', 'comfyui']) {
    const { ctx } = bootCinematicApp();
    installSubmitAndAssetMocks(ctx, {
      imageBodies: { '/image/google_fixture_00001.png': 'data:image/png;base64,GOOGLEREF' },
    });
    renderComfyHistory(ctx, googleHistoryItem());
    vm.runInContext(`
      selectCinematicProvider('${startProvider}');
      uploadedImages = [{ id: 7, base64: 'data:image/png;base64,OLDREF' }];
      if ('${startProvider}' === 'comfyui' && typeof openCinematicComfyWorkbench === 'function') {
        openCinematicComfyWorkbench();
      }
    `, ctx);
    clickRecordBody(ctx);
    assert.equal(viewerState(ctx).open, true);
    ctx.document.getElementById('cinematicViewerEditBtn').click();
    await flushPromises();
    const after = vm.runInContext(`({
      layout: document.documentElement.dataset.layout,
      provider: currentCinematicProvider,
      refs: uploadedImages.map((item) => item.base64),
      editPrompt: (document.getElementById('editPrompt') || {}).value || '',
      cinematicPrompt: (document.getElementById('cinematicPrompt') || {}).value || '',
      workbench: typeof isCinematicComfyWorkbenchOpen === 'function' && isCinematicComfyWorkbenchOpen(),
    })`, ctx);
    assert.equal(after.layout, 'cinematic');
    assert.equal(after.provider, 'google', startProvider);
    assert.deepEqual(hostValue(after.refs), ['data:image/png;base64,GOOGLEREF']);
    assert.equal(after.editPrompt, 'continue edit provider fixture');
    assert.equal(after.cinematicPrompt, 'continue edit provider fixture');
    assert.equal(after.workbench, false);
    vm.runInContext('submitCinematicComposer()', ctx);
    await flushPromises();
    const calls = submitCalls(ctx);
    assert.equal(calls.edit.length, 1, startProvider);
    assert.equal(calls.gptEdit.length, 0, startProvider);
    assert.equal(calls.gptGen.length, 0, startProvider);
    assert.match(String(calls.edit[0].body || ''), /continue edit provider fixture/);
    assert.match(String(calls.edit[0].body || ''), /GOOGLEREF/);
    assert.doesNotMatch(String(calls.edit[0].body || ''), /OLDREF/);
    assert.equal(layoutSnapshot(ctx).dataset, 'cinematic');
  }
});

test('continue-edit does not leave a half-switched state or auto-submit when the image fails to load', async () => {
  const { ctx } = bootCinematicApp();
  installSubmitAndAssetMocks(ctx, {
    imageFailures: { '/image/google_fixture_00001.png': 500 },
  });
  renderComfyHistory(ctx, googleHistoryItem());
  vm.runInContext(`
    selectCinematicProvider('gpt');
    pickProviderRouteGpt('chatgpt_pool');
    uploadedImages = [{ id: 7, base64: 'data:image/png;base64,OLDREF' }];
  `, ctx);
  clickRecordBody(ctx);
  ctx.document.getElementById('cinematicViewerEditBtn').click();
  await flushPromises();
  const after = vm.runInContext(`({
    provider: currentCinematicProvider,
    refs: uploadedImages.map((item) => item.base64),
    route: gptState.gptProviderRoute,
    editPrompt: (document.getElementById('editPrompt') || {}).value || '',
    cinematicPrompt: (document.getElementById('cinematicPrompt') || {}).value || '',
  })`, ctx);
  assert.equal(after.provider, 'gpt');
  assert.deepEqual(hostValue(after.refs), ['data:image/png;base64,OLDREF']);
  assert.equal(after.route, 'chatgpt_pool');
  const calls = submitCalls(ctx);
  assert.equal(calls.edit.length, 0);
  assert.equal(calls.gptEdit.length, 0);
  assert.equal(calls.gptGen.length, 0);
  assert.equal(layoutSnapshot(ctx).dataset, 'cinematic');
});

test('gpt-edit refill replaces leftover or empty references and submitGptEdit uses the history image', async () => {
  for (const startRefs of [[], [{ id: 7, base64: 'data:image/png;base64,OLDREF' }]]) {
    const { ctx } = bootCinematicApp();
    installSubmitAndAssetMocks(ctx, {
      imageBodies: { '/gpt_outputs/gpt_edit_fixture_00001.png': 'data:image/png;base64,GPTEDITREF' },
    });
    const item = gptHistoryItem({
      task_id: 'fixture-gpt-edit-1',
      type: 'gpt-edit',
      prompt: 'gpt edit refill fixture',
      params: { ratio: '1:1', gpt_provider_route: 'third_party_image_api' },
      output_file: 'gpt_edit_fixture_00001.png',
      output_files: ['gpt_edit_fixture_00001.png'],
    });
    renderComfyHistory(ctx, item);
    ctx.__startRefs = startRefs;
    vm.runInContext(`
      selectCinematicProvider('gpt');
      pickProviderRouteGpt('codex');
      uploadedImages = window.__startRefs;
    `, ctx);
    clickHistoryRetry(ctx);
    await flushPromises();
    const after = vm.runInContext(`({
      provider: currentCinematicProvider,
      refs: uploadedImages.map((item) => item.base64),
      prompt: (document.getElementById('cinematicPrompt') || {}).value || '',
      gptPrompt: (document.getElementById('gptPrompt') || {}).value || '',
      route: gptState.gptProviderRoute,
      select: (document.getElementById('gptProviderRouteSelect') || {}).value || '',
    })`, ctx);
    assert.equal(after.provider, 'gpt');
    assert.deepEqual(hostValue(after.refs), ['data:image/png;base64,GPTEDITREF']);
    assert.equal(after.prompt, 'gpt edit refill fixture');
    assert.equal(after.gptPrompt, 'gpt edit refill fixture');
    assert.equal(after.route, 'third_party_image_api');
    assert.equal(after.select, 'third_party_image_api');
    vm.runInContext('submitCinematicComposer()', ctx);
    await flushPromises();
    const calls = submitCalls(ctx);
    assert.equal(calls.gptEdit.length, 1);
    assert.equal(calls.gptGen.length, 0);
    assert.equal(calls.edit.length, 0);
    assert.match(String(calls.gptEdit[0].body || ''), /gpt edit refill fixture/);
    assert.match(String(calls.gptEdit[0].body || ''), /GPTEDITREF/);
    assert.doesNotMatch(String(calls.gptEdit[0].body || ''), /OLDREF/);
    assert.equal(layoutSnapshot(ctx).dataset, 'cinematic');
  }
});

test('gpt-edit refill with a missing history image does not keep leftover refs or fabricate a new one', async () => {
  const { ctx } = bootCinematicApp();
  installSubmitAndAssetMocks(ctx, {
    imageFailures: { '/gpt_outputs/gpt_edit_fixture_00001.png': 404 },
  });
  renderComfyHistory(ctx, gptHistoryItem({
    task_id: 'fixture-gpt-edit-missing',
    type: 'gpt-edit',
    prompt: 'missing gpt edit fixture',
    params: { ratio: '1:1', gpt_provider_route: 'chatgpt_pool' },
    output_file: 'gpt_edit_fixture_00001.png',
    output_files: ['gpt_edit_fixture_00001.png'],
  }));
  vm.runInContext(`
    selectCinematicProvider('gpt');
    uploadedImages = [{ id: 7, base64: 'data:image/png;base64,OLDREF' }];
  `, ctx);
  clickHistoryRetry(ctx);
  await flushPromises();
  const after = vm.runInContext(`({
    provider: currentCinematicProvider,
    refs: uploadedImages.length,
    prompt: (document.getElementById('cinematicPrompt') || {}).value || '',
    route: gptState.gptProviderRoute,
  })`, ctx);
  assert.equal(after.provider, 'gpt');
  assert.equal(after.refs, 0);
  assert.equal(after.prompt, 'missing gpt edit fixture');
  assert.equal(after.route, 'chatgpt_pool');
  const calls = submitCalls(ctx);
  assert.equal(calls.gptEdit.length, 0);
  assert.equal(calls.gptGen.length, 0);
  assert.equal(calls.edit.length, 0);
});

test('GPT history refill restores provider routes into state, select, capsule and the next submit body', async () => {
  const cases = [
    { stored: { gpt_provider_route: 'chatgpt_pool' }, expected: 'chatgpt_pool', start: 'codex', capsule: '账号池 API' },
    { stored: { gpt_provider_route: 'third_party_image_api' }, expected: 'third_party_image_api', start: 'codex', capsule: '第三方 API' },
    { stored: { gpt_provider_route: 'codex' }, expected: 'codex', start: 'chatgpt_pool', capsule: '本地 Codex' },
    { stored: { use_third_party_api: true }, expected: 'third_party_image_api', start: 'codex', capsule: '第三方 API' },
    { stored: { gpt_provider_route: 'nope' }, expected: 'codex', start: 'chatgpt_pool', capsule: '本地 Codex' },
  ];
  for (const { stored, expected, start, capsule } of cases) {
    const { ctx } = bootCinematicApp();
    installSubmitAndAssetMocks(ctx);
    renderComfyHistory(ctx, gptHistoryItem({
      prompt: `route ${expected} fixture`,
      params: { ratio: '9:16', resolution: '1k', quality: 'auto', image_count: 1, moderation: 'auto', ...stored },
    }));
    vm.runInContext(`pickProviderRouteGpt('${start}'); selectCinematicProvider('google');`, ctx);
    clickHistoryRetry(ctx);
    await flushPromises();
    const after = vm.runInContext(`({
      provider: currentCinematicProvider,
      route: gptState.gptProviderRoute,
      select: (document.getElementById('gptProviderRouteSelect') || {}).value || '',
      capsule: ((document.getElementById('cinematicGptRouteBtn') || {}).querySelector('.cinematic-pill-value') || {}).textContent || '',
      prompt: (document.getElementById('cinematicPrompt') || {}).value || '',
    })`, ctx);
    assert.equal(after.provider, 'gpt', expected);
    assert.equal(after.route, expected);
    assert.equal(after.select, expected);
    assert.equal(after.capsule, capsule);
    assert.equal(after.prompt, `route ${expected} fixture`);
    vm.runInContext('submitCinematicComposer()', ctx);
    await flushPromises();
    const calls = submitCalls(ctx);
    assert.equal(calls.gptGen.length, 1, expected);
    assert.match(String(calls.gptGen[0].body || ''), new RegExp(`route ${expected} fixture`));
    assert.match(String(calls.gptGen[0].body || ''), new RegExp(expected));
  }
});

test('GPT history refill leaves the current route unchanged when params have no route fields', async () => {
  const { ctx } = bootCinematicApp();
  installSubmitAndAssetMocks(ctx);
  renderComfyHistory(ctx, gptHistoryItem({
    prompt: 'route missing fixture',
    params: { ratio: '1:1', resolution: '1k', quality: 'auto', image_count: 1, moderation: 'auto' },
  }));
  vm.runInContext(`selectCinematicProvider('gpt'); pickProviderRouteGpt('chatgpt_pool');`, ctx);
  clickHistoryRetry(ctx);
  await flushPromises();
  const after = vm.runInContext(`({
    route: gptState.gptProviderRoute,
    select: (document.getElementById('gptProviderRouteSelect') || {}).value || '',
  })`, ctx);
  assert.equal(after.route, 'chatgpt_pool');
  assert.equal(after.select, 'chatgpt_pool');
});

function cinematicCardMedia(ctx) {
  return vm.runInContext(`({
    cardCount: document.querySelectorAll('#cinematicHistoryList .cinematic-record-card').length,
    titles: Array.from(document.querySelectorAll('#cinematicHistoryList .cinematic-record-title')).map((el) => el.textContent || ''),
    missingCopy: Array.from(document.querySelectorAll('#cinematicHistoryList .cinematic-record-media, #cinematicHistoryList .cinematic-record-source')).map((el) => el.textContent || ''),
    mediaHasMissing: !!(document.querySelector('#cinematicHistoryList .cinematic-record-media.is-missing')),
    mediaText: ((document.querySelector('#cinematicHistoryList .cinematic-record-media') || {}).textContent || ''),
    sourceText: ((document.querySelector('#cinematicHistoryList .cinematic-record-source') || {}).textContent || ''),
    imgSrc: ((document.querySelector('#cinematicHistoryList .cinematic-record-media img') || {}).src || (document.querySelector('#cinematicHistoryList .cinematic-record-media img') || {}).dataset?.src || ''),
    imgFallback: ((document.querySelector('#cinematicHistoryList .cinematic-record-media img') || {}).dataset || {}).fallback || '',
    videoSrc: ((document.querySelector('#cinematicHistoryList .cinematic-record-media video') || {}).src || ''),
    videoCount: document.querySelectorAll('#cinematicHistoryList .cinematic-record-media video').length,
    markedMissing: !!(window.__historyFixture && window.__historyFixture.__assetMissing),
    imageSource: typeof getHistoryImageSource === 'function' ? getHistoryImageSource(window.__historyFixture) : '',
    thumb: typeof getHistoryThumbMeta === 'function' ? getHistoryThumbMeta(window.__historyFixture) : null,
  })`, ctx);
}

function archivedComfyImageItem(overrides = {}) {
  return {
    task_id: 'fixture-comfy-archive-image',
    timestamp: 1795002550,
    status: 'succeeded_no_telegram',
    type: 'comfy',
    prompt: 'archived comfy image fixture',
    params: {
      comfy_output_kind: 'image',
      ratio: '1:1',
      workflow: 'minimax_h3_image.json',
      archive_enabled: true,
      archive_file: 'comfy_archived_minimax_h3_image_00029_abc123.png',
      comfy_image: { filename: 'minimax_h3_image_00029_.png', subfolder: '', type: 'output' },
    },
    output_file: 'comfy_archived_minimax_h3_image_00029_abc123.png',
    output_files: ['comfy_archived_minimax_h3_image_00029_abc123.png'],
    result_files: ['comfy_archived_minimax_h3_image_00029_abc123.png'],
    image_paths: ['/image/comfy_archived_minimax_h3_image_00029_abc123.png'],
    ...overrides,
  };
}

function archivedComfyVideoItem(overrides = {}) {
  return {
    task_id: 'fixture-comfy-archive-video',
    timestamp: 1794996070,
    status: 'succeeded_no_telegram',
    type: 'comfy',
    prompt: 'archived comfy video fixture',
    params: {
      comfy_output_kind: 'video',
      ratio: '1:1',
      workflow: 'Minimax H3 Selflift.json',
      archive_enabled: true,
      archive_file: 'comfy_archived_selflift_00011_abc123.mp4',
      comfy_image: { filename: 'selfliftAvatar_00011-audio.mp4', subfolder: '', type: 'output' },
    },
    output_file: 'comfy_archived_selflift_00011_abc123.mp4',
    output_files: ['comfy_archived_selflift_00011_abc123.mp4'],
    result_files: ['comfy_archived_selflift_00011_abc123.mp4'],
    image_paths: [],
    video_path: '/video/comfy_archived_selflift_00011_abc123.mp4',
    video_paths: ['/video/comfy_archived_selflift_00011_abc123.mp4'],
    ...overrides,
  };
}

function expectedHistoryThumbUrl(original, size = 420) {
  const path = String(original || '').split('?')[0];
  return '/thumb/' + encodeURIComponent(path) + '.webp?w=' + size;
}

function isHeavyMediaUrl(url) {
  const path = String(url || '').split('?')[0];
  if (!path || path.startsWith('/thumb/')) return false;
  return (
    path.startsWith('/image/')
    || path.startsWith('/video/')
    || path.startsWith('/api/comfy/image')
    || /\.(mp4|webm|mov|m4v)$/i.test(path)
  );
}

function installImageAutoload(ctx) {
  ctx.Image = function Image() {
    this.onload = null;
    this.onerror = null;
    this._src = '';
    Object.defineProperty(this, 'src', {
      configurable: true,
      get() { return this._src; },
      set(value) {
        this._src = String(value || '');
        const self = this;
        Promise.resolve().then(() => {
          if (typeof self.onload === 'function') self.onload({ type: 'load', target: self });
        });
      },
    });
  };
}



test('cinematic archive image cards use a light thumb, not the archive original', () => {
  const { ctx } = bootCinematicApp();
  const original = '/image/comfy_archived_minimax_h3_image_00029_abc123.png';
  const live = '/api/comfy/image?filename=minimax_h3_image_00029_.png&subfolder=&type=output';
  const thumb = expectedHistoryThumbUrl(original);
  renderComfyHistory(ctx, archivedComfyImageItem());
  const media = cinematicCardMedia(ctx);
  const img = ctx.document.querySelector('#cinematicHistoryList .cinematic-record-media img');
  const src = (img && (img.src || (img.dataset && img.dataset.src))) || '';
  const fallback = (img && img.dataset && img.dataset.fallback) || '';
  assert.equal(media.cardCount, 1);
  assert.equal(media.imageSource, original);
  assert.equal(src, thumb);
  assert.equal(isHeavyMediaUrl(src), false);
  assert.equal(isHeavyMediaUrl(fallback), false);
  assert.doesNotMatch(src, /\/api\/comfy\/image/);
  assert.notEqual(src, original);
  assert.notEqual(fallback, original);
  assert.notEqual(fallback, live);
  assert.equal(media.mediaHasMissing, false);
  assert.doesNotMatch(media.mediaText, /FILE MISSING/);
  assert.doesNotMatch(media.sourceText, /原始图片文件已丢失/);
});

function listMediaRequestUrls(ctx) {
  const fetchUrls = (ctx.__fetchCalls || []).map((call) => String(call.url || ''));
  const domUrls = vm.runInContext(`Array.from(document.querySelectorAll('#cinematicHistoryList img, #cinematicHistoryList video, #sidebarHistoryList img, #sidebarHistoryList video')).map((el) => el.src || (el.dataset && el.dataset.src) || el.getAttribute('src') || '').filter(Boolean)`, ctx);
  return [...fetchUrls, ...domUrls];
}

function historyRecordCount(ctx, taskId) {
  return vm.runInContext(`historyRecords.filter((item) => item && item.task_id === ${JSON.stringify(taskId)}).length`, ctx);
}

function mixedImageAfterVideoItem(overrides = {}) {
  return {
    task_id: 'fixture-comfy-mixed-image-video',
    timestamp: 1795003000,
    status: 'succeeded_no_telegram',
    type: 'comfy',
    prompt: 'mixed image and video fixture',
    params: {
      comfy_output_kind: 'video',
      workflow: 'Minimax H3 Selflift.json',
      archive_enabled: true,
    },
    output_file: 'comfy_archived_clip.mp4',
    output_files: ['comfy_archived_clip.mp4', 'comfy_archived_still.png'],
    result_files: ['comfy_archived_clip.mp4', 'comfy_archived_still.png'],
    image_paths: [],
    video_path: '/video/comfy_archived_clip.mp4',
    video_paths: ['/video/comfy_archived_clip.mp4'],
    ...overrides,
  };
}

function audioHistoryItem(overrides = {}) {
  return {
    task_id: 'fixture-audio-result',
    timestamp: 1795004000,
    status: 'success',
    type: 'comfy',
    prompt: 'audio result fixture',
    params: { comfy_output_kind: 'audio', artifact_type: 'audio' },
    artifact_type: 'audio',
    output_file: 'comfy_archived_track.flac',
    output_files: ['comfy_archived_track.flac'],
    result_files: ['comfy_archived_track.flac'],
    image_paths: [],
    ...overrides,
  };
}

test('pure video results are hidden from mobile cards and do not request a cover or original', () => {
  const { ctx } = bootCinematicApp();
  const original = '/video/comfy_archived_selflift_00011_abc123.mp4';
  const thumb = expectedHistoryThumbUrl(original);
  installSubmitAndAssetMocks(ctx);
  const rendered = renderComfyHistory(ctx, archivedComfyVideoItem());
  const media = cinematicCardMedia(ctx);
  const listHtml = vm.runInContext(`({
    cinematicText: document.getElementById('cinematicHistoryList') ? document.getElementById('cinematicHistoryList').textContent || '' : '',
    cinematicVideoCount: document.querySelectorAll('#cinematicHistoryList video').length,
    cinematicImgCount: document.querySelectorAll('#cinematicHistoryList img').length,
    sidebarCardCount: document.querySelectorAll('#sidebarHistoryList .history-card').length,
    sidebarVideoCount: document.querySelectorAll('#sidebarHistoryList video').length,
    sidebarImgCount: document.querySelectorAll('#sidebarHistoryList img').length,
  })`, ctx);
  const requestUrls = listMediaRequestUrls(ctx);
  assert.equal(rendered.cardCount, 0);
  assert.equal(media.cardCount, 0);
  assert.equal(listHtml.cinematicVideoCount, 0);
  assert.equal(listHtml.cinematicImgCount, 0);
  assert.equal(listHtml.sidebarCardCount, 0);
  assert.equal(listHtml.sidebarVideoCount, 0);
  assert.doesNotMatch(listHtml.cinematicText, /FILE MISSING/);
  assert.doesNotMatch(listHtml.cinematicText, /NO PREVIEW/);
  assert.ok(!requestUrls.some((url) => url === original || url === thumb || url.startsWith('/video/') || url.includes('/thumb/') && url.includes('comfy_archived_selflift')), 'list must not request a video cover, thumb, or original');
  assert.equal(historyRecordCount(ctx, 'fixture-comfy-archive-video'), 1);
});

test('h3 and cyimg video types are also hidden from mobile result cards', () => {
  const { ctx } = bootCinematicApp();
  installSubmitAndAssetMocks(ctx);
  ctx.__historyFixtureList = [
    archivedComfyImageItem(),
    {
      task_id: 'fixture-h3-video',
      timestamp: 1795004100,
      status: 'success',
      type: 'minimax-h3-video',
      prompt: 'h3 video fixture',
      output_file: 'h3_clip.mp4',
      output_files: ['h3_clip.mp4'],
      result_files: ['h3_clip.mp4'],
      video_path: '/video/h3_clip.mp4',
      video_paths: ['/video/h3_clip.mp4'],
      image_paths: [],
    },
    {
      task_id: 'fixture-cyimg-video',
      timestamp: 1795004200,
      status: 'success',
      type: 'cyimg-video',
      prompt: 'cyimg video fixture',
      output_file: 'cyimg_clip.webm',
      output_files: ['cyimg_clip.webm'],
      result_files: ['cyimg_clip.webm'],
      video_paths: ['/video/cyimg_clip.webm'],
      image_paths: [],
    },
  ];
  vm.runInContext('applyHistoryRecords(window.__historyFixtureList)', ctx);
  const snap = vm.runInContext(`({
    prompts: Array.from(document.querySelectorAll('#cinematicHistoryList .cinematic-record-prompt')).map((el) => el.textContent || ''),
    cardCount: document.querySelectorAll('#cinematicHistoryList .cinematic-record-card').length,
    stored: historyRecords.length,
  })`, ctx);
  assert.equal(snap.prompts.includes('archived comfy image fixture'), true);
  assert.equal(snap.prompts.includes('h3 video fixture'), false);
  assert.equal(snap.prompts.includes('cyimg video fixture'), false);
  assert.equal(snap.cardCount, 1);
  assert.equal(snap.stored, 3);
});

test('a missing card thumb does not fall back to the archive original or a live Comfy file', () => {
  const { ctx } = bootCinematicApp();
  const original = '/image/comfy_archived_minimax_h3_image_00029_abc123.png';
  const live = '/api/comfy/image?filename=minimax_h3_image_00029_.png&subfolder=&type=output';
  renderComfyHistory(ctx, archivedComfyImageItem());
  const img = ctx.document.querySelector('#cinematicHistoryList .cinematic-record-media img');
  assert.ok(img, 'expected a thumb image');
  if (img.dataset) img.dataset.fallback = original;
  if (typeof img.onerror === 'function') img.onerror();
  const afterSrc = img.src || (img.dataset && img.dataset.src) || '';
  const media = cinematicCardMedia(ctx);
  assert.equal(media.cardCount, 1);
  assert.notEqual(afterSrc, original);
  assert.notEqual(afterSrc, live);
  assert.equal(isHeavyMediaUrl(afterSrc) && afterSrc !== expectedHistoryThumbUrl(original), false);
  assert.equal(media.markedMissing, false);
  assert.doesNotMatch(media.sourceText, /原始图片文件已丢失/);
  assert.doesNotMatch(media.mediaText, /FILE MISSING/);
});

test('archive originals still open in the detail viewer after clicking a card', async () => {
  const { ctx } = bootCinematicApp();
  installImageAutoload(ctx);
  installSubmitAndAssetMocks(ctx, {
    imageBodies: {
      [expectedHistoryThumbUrl('/image/comfy_archived_minimax_h3_image_00029_abc123.png')]: 'data:image/webp;base64,THUMB',
      '/image/comfy_archived_minimax_h3_image_00029_abc123.png': 'data:image/png;base64,ARCHIVEREF',
    },
  });
  renderComfyHistory(ctx, archivedComfyImageItem());
  const img = ctx.document.querySelector('#cinematicHistoryList .cinematic-record-media img');
  assert.equal((img && (img.src || (img.dataset && img.dataset.src))) || '', expectedHistoryThumbUrl('/image/comfy_archived_minimax_h3_image_00029_abc123.png'));
  clickRecordBody(ctx);
  await flushPromises();
  const opened = vm.runInContext(`({
    open: !!(document.getElementById('cinematicViewerPage') && document.getElementById('cinematicViewerPage').classList.contains('is-open')),
    download: currentCinematicViewerDownloadUrl || '',
    imgSrc: (document.getElementById('cinematicViewerImg') || {}).src || '',
    videoSrc: (document.getElementById('cinematicViewerVideo') || {}).src || '',
  })`, ctx);
  assert.equal(opened.open, true);
  assert.equal(opened.download, '/image/comfy_archived_minimax_h3_image_00029_abc123.png');
  assert.equal(opened.imgSrc, '/image/comfy_archived_minimax_h3_image_00029_abc123.png');
  assert.equal(opened.videoSrc, '');
});

test('mixed video-then-image results keep the later image and open that original, not the video', async () => {
  const { ctx } = bootCinematicApp();
  const imageOriginal = '/image/comfy_archived_still.png';
  const videoOriginal = '/video/comfy_archived_clip.mp4';
  installImageAutoload(ctx);
  installSubmitAndAssetMocks(ctx, {
    imageBodies: {
      [expectedHistoryThumbUrl(imageOriginal)]: 'data:image/webp;base64,THUMB',
      [imageOriginal]: 'data:image/png;base64,STILLREF',
    },
  });
  renderComfyHistory(ctx, mixedImageAfterVideoItem());
  const media = cinematicCardMedia(ctx);
  const src = media.imgSrc;
  const requestUrls = listMediaRequestUrls(ctx);
  assert.equal(media.cardCount, 1);
  assert.equal(media.videoCount, 0);
  assert.equal(src, expectedHistoryThumbUrl(imageOriginal));
  assert.notEqual(src, expectedHistoryThumbUrl(videoOriginal));
  assert.ok(!requestUrls.some((url) => url === videoOriginal || url === expectedHistoryThumbUrl(videoOriginal) || url.startsWith('/video/')));
  clickRecordBody(ctx);
  await flushPromises();
  const opened = vm.runInContext(`({
    open: !!(document.getElementById('cinematicViewerPage') && document.getElementById('cinematicViewerPage').classList.contains('is-open')),
    download: currentCinematicViewerDownloadUrl || '',
    imgSrc: (document.getElementById('cinematicViewerImg') || {}).src || '',
    videoSrc: (document.getElementById('cinematicViewerVideo') || {}).src || '',
  })`, ctx);
  assert.equal(opened.open, true);
  assert.equal(opened.download, imageOriginal);
  assert.equal(opened.imgSrc, imageOriginal);
  assert.equal(opened.videoSrc, '');
  assert.equal(historyRecordCount(ctx, 'fixture-comfy-mixed-image-video'), 1);
});

test('audio and other non-image results are not shown as mobile image cards', () => {
  const { ctx } = bootCinematicApp();
  installSubmitAndAssetMocks(ctx);
  renderComfyHistory(ctx, audioHistoryItem());
  const media = cinematicCardMedia(ctx);
  const listText = vm.runInContext(`(document.getElementById('cinematicHistoryList') || {}).textContent || ''`, ctx);
  const requestUrls = listMediaRequestUrls(ctx);
  assert.equal(media.cardCount, 0);
  assert.doesNotMatch(listText, /FILE MISSING/);
  assert.doesNotMatch(listText, /NO PREVIEW/);
  assert.ok(!requestUrls.some((url) => String(url).includes('comfy_archived_track') || String(url).includes('/audio/')));
  assert.equal(historyRecordCount(ctx, 'fixture-audio-result'), 1);
});

test('in-progress video tasks stay visible for status tracking before a result exists', () => {
  const { ctx } = bootCinematicApp();
  const pending = {
    task_id: 'fixture-pending-video',
    timestamp: 1795004300,
    status: 'processing',
    type: 'comfy',
    prompt: 'pending video fixture',
    params: { comfy_output_kind: 'video', workflow: 'Minimax H3 Selflift.json' },
    __pending: true,
    __pendingText: '任务已提交，正在生成中',
  };
  renderComfyHistory(ctx, pending);
  const media = cinematicCardMedia(ctx);
  assert.equal(media.cardCount, 1);
  assert.equal(media.videoCount, 0);
  assert.doesNotMatch(media.mediaText, /FILE MISSING/);
  const hasGlow = vm.runInContext(`!!document.querySelector('#cinematicHistoryList .cinematic-pending-glow, #cinematicHistoryList .cinematic-record-card.is-pending-task')`, ctx);
  assert.equal(hasGlow, true);
});

test('a temporary preview failure is not treated as a deleted original', () => {
  const { ctx } = bootCinematicApp();
  renderComfyHistory(ctx, archivedComfyImageItem({
    output_file: '',
    output_files: [],
    result_files: [],
    image_paths: [],
    missing_result_files: false,
  }));
  const img = ctx.document.querySelector('#cinematicHistoryList .cinematic-record-media img');
  if (img) {
    if (img.dataset) img.dataset.fallback = '/image/should-not-load.png';
    if (typeof img.onerror === 'function') img.onerror();
  }
  const media = cinematicCardMedia(ctx);
  assert.equal(media.cardCount, 1);
  assert.equal(media.markedMissing, false);
  assert.doesNotMatch(media.sourceText, /原始图片文件已丢失/);
  assert.doesNotMatch(media.mediaText, /FILE MISSING/);
  if (img) {
    const afterSrc = img.src || (img.dataset && img.dataset.src) || '';
    assert.notEqual(afterSrc, '/image/should-not-load.png');
  }
});

test('cinematic history hides explicitly deleted tasks and keeps mixed or unattributable rows', () => {
  const { ctx } = bootCinematicApp();
  const keptArchive = archivedComfyImageItem();
  const mixed = archivedComfyImageItem({
    task_id: 'fixture-comfy-partial-missing',
    output_files: ['comfy_archived_ok.png', 'comfy_archived_gone.png'],
    result_files: ['comfy_archived_ok.png', 'comfy_archived_gone.png'],
    image_paths: ['/image/comfy_archived_ok.png'],
    output_file: 'comfy_archived_ok.png',
  });
  const unattributable = archivedComfyImageItem({
    task_id: 'fixture-comfy-unattributable-missing',
    missing_result_files: true,
    output_file: 'comfy_archived_gone.png',
    output_files: ['comfy_archived_gone.png'],
    result_files: ['comfy_archived_gone.png'],
    image_paths: [],
  });
  const noResult = {
    task_id: 'fixture-comfy-canceled-no-result',
    timestamp: 1794700000,
    status: 'canceled',
    type: 'comfy',
    prompt: 'canceled comfy fixture',
    params: { comfy_output_kind: 'video', workflow: 'Minimax H3 Selflift.json' },
  };
  const canceledImage = archivedComfyImageItem({
    task_id: 'fixture-comfy-canceled-image-no-result',
    timestamp: 1794700100,
    status: 'canceled',
    prompt: 'canceled image fixture',
    output_file: '',
    output_files: [],
    result_files: [],
    image_paths: [],
    params: { comfy_output_kind: 'image', workflow: 'minimax_h3_image.json' },
  });
  const deleted = archivedComfyImageItem({
    task_id: 'fixture-comfy-user-deleted',
    deleted: true,
    prompt: 'deleted comfy fixture',
  });
  ctx.__historyFixtureList = [keptArchive, mixed, unattributable, noResult, canceledImage, deleted];
  vm.runInContext(`applyHistoryRecords(window.__historyFixtureList)`, ctx);
  const snap = vm.runInContext(`({
    cardCount: document.querySelectorAll('#cinematicHistoryList .cinematic-record-card').length,
    prompts: Array.from(document.querySelectorAll('#cinematicHistoryList .cinematic-record-prompt')).map((el) => el.textContent || ''),
    mediaSrcs: Array.from(document.querySelectorAll('#cinematicHistoryList .cinematic-record-media img')).map((el) => el.src || (el.dataset && el.dataset.src) || ''),
    stored: historyRecords.length,
  })`, ctx);
  assert.equal(snap.prompts.includes('deleted comfy fixture'), false);
  assert.equal(snap.prompts.includes('archived comfy image fixture'), true);
  assert.equal(snap.prompts.includes('canceled comfy fixture'), false);
  assert.equal(snap.prompts.includes('canceled image fixture'), true);
  assert.ok(snap.cardCount >= 3);
  assert.ok(snap.cardCount <= 5);
  assert.ok(snap.mediaSrcs.every((src) => !isHeavyMediaUrl(src)));
  const mixedSrc = snap.mediaSrcs.find((src) => String(src).includes('comfy_archived_ok'));
  if (mixedSrc) assert.equal(mixedSrc, expectedHistoryThumbUrl('/image/comfy_archived_ok.png'));
  assert.equal(snap.stored, 6);
});

test('Batch 4 mobile composer shows all active provider pills immediately, clear submit labels, and 2-tap clear-all confirm', () => {
  const html = readIndex();
  assert.doesNotMatch(html, /user-scalable=no/i);
  assert.match(html, /viewport-fit=cover/i);
  assert.doesNotMatch(html, /第一个功能先做完整/);
  assert.doesNotMatch(html, /等待施法/);
  assert.doesNotMatch(fs.readFileSync(path.join(ROOT, 'frontend/styles/base.css'), 'utf8'), /fonts\.googleapis\.com/);

  const { ctx } = bootCinematicApp();
  const initialGoogle = vm.runInContext(`({
    modelHidden: document.getElementById('cinematicModelWrap').hidden,
    qualityHidden: document.getElementById('cinematicQualityWrap').hidden,
    ratioHidden: document.getElementById('cinematicRatioWrap').hidden,
    submitHtml: document.getElementById('cinematicSubmitBtn').innerHTML,
    submitAria: document.getElementById('cinematicSubmitBtn').getAttribute('aria-label'),
    clearAllHidden: document.getElementById('cinematicRefClearAllBtn').hidden,
    spellPlaceholder: getCinematicSpellPlaceholder('json'),
  })`, ctx);
  assert.equal(initialGoogle.modelHidden, false);
  assert.equal(initialGoogle.qualityHidden, false);
  assert.equal(initialGoogle.ratioHidden, false);
  assert.match(initialGoogle.submitHtml, /生成/);
  assert.match(initialGoogle.submitAria || '', /Google/);
  assert.equal(initialGoogle.clearAllHidden, true);
  assert.equal(initialGoogle.spellPlaceholder, '尚未生成提示词');

  const afterGptAndTwoRefs = vm.runInContext(`(function () {
    selectCinematicProvider('gpt');
    uploadedImages = [{ id: 1, base64: 'data:image/png;base64,AAA' }, { id: 2, base64: 'data:image/png;base64,BBB' }];
    renderGrid();
    const beforeArm = {
      routeHidden: document.getElementById('cinematicGptRouteWrap').hidden,
      qualityHidden: document.getElementById('cinematicQualityWrap').hidden,
      ratioHidden: document.getElementById('cinematicRatioWrap').hidden,
      gptQualityHidden: document.getElementById('cinematicGptQualityWrap').hidden,
      gptModerationHidden: document.getElementById('cinematicGptModerationWrap').hidden,
      clearAllHidden: document.getElementById('cinematicRefClearAllBtn').hidden,
      submitHtml: document.getElementById('cinematicSubmitBtn').innerHTML,
    };
    handleCinematicRefClearAllClick();
    const armed = {
      count: uploadedImages.length,
      text: document.getElementById('cinematicRefClearAllBtn').textContent,
      confirming: document.getElementById('cinematicRefClearAllBtn').classList.contains('is-confirming'),
    };
    handleCinematicRefClearAllClick();
    const cleared = {
      count: uploadedImages.length,
      clearAllHidden: document.getElementById('cinematicRefClearAllBtn').hidden,
    };
    return { beforeArm, armed, cleared };
  })()`, ctx);
  assert.equal(afterGptAndTwoRefs.beforeArm.routeHidden, false);
  assert.equal(afterGptAndTwoRefs.beforeArm.qualityHidden, false);
  assert.equal(afterGptAndTwoRefs.beforeArm.ratioHidden, false);
  assert.equal(afterGptAndTwoRefs.beforeArm.gptQualityHidden, false);
  assert.equal(afterGptAndTwoRefs.beforeArm.gptModerationHidden, false);
  assert.equal(afterGptAndTwoRefs.beforeArm.clearAllHidden, false);
  assert.match(afterGptAndTwoRefs.beforeArm.submitHtml, /编辑/);
  assert.equal(afterGptAndTwoRefs.armed.count, 2);
  assert.equal(afterGptAndTwoRefs.armed.text, '确认清空');
  assert.equal(afterGptAndTwoRefs.armed.confirming, true);
  assert.equal(afterGptAndTwoRefs.cleared.count, 0);
  assert.equal(afterGptAndTwoRefs.cleared.clearAllHidden, true);
});

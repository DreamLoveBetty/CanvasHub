// Generic local-extension registry for optional canvas nodes and UI adapters.
// Core modules know nothing about specific local-only plugins; extensions load after this
// file (via <!-- local-extensions:scripts -->) and register capabilities dynamically.
// Keep lookups live (do not cache extension lists at core IIFE parse time).
(function () {
  'use strict';

  const extensions = [];

  function register(extension) {
    if (!extension || typeof extension !== 'object') return false;
    const id = String(extension.id || '').trim();
    if (!id) return false;
    const next = { ...extension, id };
    const existing = extensions.findIndex(item => item.id === id);
    if (existing >= 0) extensions.splice(existing, 1, next);
    else extensions.push(next);
    return true;
  }

  function clear() {
    extensions.length = 0;
  }

  function list() {
    return extensions.slice();
  }

  function menuItems() {
    const items = [];
    for (const ext of extensions) {
      if (!Array.isArray(ext.menuItems)) continue;
      for (const item of ext.menuItems) {
        if (item && item.type) items.push({ ...item });
      }
    }
    return items;
  }

  function nodeTypes() {
    const seen = new Set();
    for (const ext of extensions) {
      if (Array.isArray(ext.nodeTypes)) {
        ext.nodeTypes.forEach(t => { if (t) seen.add(String(t)); });
      }
      if (Array.isArray(ext.menuItems)) {
        ext.menuItems.forEach(item => { if (item?.type) seen.add(String(item.type)); });
      }
      if (Array.isArray(ext.definitions)) {
        ext.definitions.forEach(def => {
          (def?.types || []).forEach(t => { if (t) seen.add(String(t)); });
        });
      }
    }
    return [...seen];
  }

  function outputTypeFor(nodeType) {
    for (const ext of extensions) {
      if (!Array.isArray(ext.outputStateTypes)) continue;
      const found = ext.outputStateTypes.find(entry => entry && entry.type === nodeType);
      if (found) return String(found.outputType || found.type || '');
    }
    return '';
  }

  function isImageOutputSourceType(nodeType) {
    for (const ext of extensions) {
      if (Array.isArray(ext.imageOutputSourceTypes) && ext.imageOutputSourceTypes.includes(nodeType)) {
        return true;
      }
    }
    return false;
  }

  function notchedSelectors() {
    const selectors = [];
    for (const ext of extensions) {
      if (Array.isArray(ext.notchedSelectors)) {
        ext.notchedSelectors.forEach(sel => {
          const clean = String(sel || '').trim();
          if (clean) selectors.push(clean);
        });
      }
    }
    return selectors;
  }

  function stepperScopes() {
    const scopes = [];
    for (const ext of extensions) {
      if (Array.isArray(ext.stepperScopes)) {
        ext.stepperScopes.forEach(sel => {
          const clean = String(sel || '').trim();
          if (clean) scopes.push(clean);
        });
      }
    }
    return scopes;
  }

  function matchSelectVariant(selectEl) {
    if (!selectEl?.closest) return '';
    for (const ext of extensions) {
      if (!Array.isArray(ext.selectVariants)) continue;
      for (const rule of ext.selectVariants) {
        if (rule?.selector && rule?.variant && selectEl.closest(rule.selector)) {
          return String(rule.variant);
        }
      }
    }
    return '';
  }

  function videoSourcePaths() {
    const paths = [];
    for (const ext of extensions) {
      if (Array.isArray(ext.videoSourcePaths)) {
        ext.videoSourcePaths.forEach(p => { if (p) paths.push(String(p)); });
      }
    }
    return paths;
  }

  function getSubmitProvider(provider) {
    for (const ext of extensions) {
      const fn = ext.submitProviders?.[provider];
      if (typeof fn === 'function') return fn;
    }
    return null;
  }

  function matchHistoryProvider(type, provider, item) {
    for (const ext of extensions) {
      if (!Array.isArray(ext.historyProviders)) continue;
      for (const entry of ext.historyProviders) {
        if (entry?.key && typeof entry.match === 'function' && entry.match(type, provider, item)) {
          return String(entry.key);
        }
      }
    }
    return '';
  }

  function historyProviderLabel(key) {
    for (const ext of extensions) {
      if (!Array.isArray(ext.historyProviders)) continue;
      const found = ext.historyProviders.find(entry => entry && entry.key === key);
      if (found?.label) return String(found.label);
    }
    return '';
  }

  function resultLabel(type) {
    for (const ext of extensions) {
      const label = ext.resultLabels?.[type];
      if (label) return String(label);
    }
    return '';
  }

  function migrateNode(node) {
    let changed = false;
    for (const ext of extensions) {
      if (!Array.isArray(ext.definitions)) continue;
      for (const def of ext.definitions) {
        if (typeof def?.migrate === 'function' && def.migrate(node)) {
          changed = true;
        }
      }
    }
    return changed;
  }

  function normalizeNode(node) {
    if (!node || !node.type) return false;
    for (const ext of extensions) {
      if (!Array.isArray(ext.definitions)) continue;
      for (const def of ext.definitions) {
        if (Array.isArray(def?.types) && def.types.includes(node.type) && typeof def.normalize === 'function') {
          def.normalize(node);
          return true;
        }
      }
    }
    return false;
  }

  function createCanvasDomains(host) {
    const domains = [];
    for (const ext of extensions) {
      if (typeof ext.createCanvasDomain !== 'function') continue;
      const domain = ext.createCanvasDomain(host);
      if (domain) domains.push(domain);
    }
    return domains;
  }

  function createModelTools(host) {
    const items = [];
    for (const ext of extensions) {
      if (typeof ext.createModelTools !== 'function') continue;
      const created = ext.createModelTools(host);
      const list = Array.isArray(created) ? created : [created];
      for (const tool of list) {
        if (!tool || typeof tool !== 'object') continue;
        const tab = String(tool.tab || 'common').trim() || 'common';
        items.push({ ...tool, tab });
      }
    }
    return items;
  }

  window.DesktopLocalExtensions = Object.freeze({
    register,
    clear,
    list,
    menuItems,
    nodeTypes,
    outputTypeFor,
    isImageOutputSourceType,
    notchedSelectors,
    stepperScopes,
    matchSelectVariant,
    videoSourcePaths,
    getSubmitProvider,
    matchHistoryProvider,
    historyProviderLabel,
    resultLabel,
    migrateNode,
    normalizeNode,
    createCanvasDomains,
    createModelTools,
  });
})();

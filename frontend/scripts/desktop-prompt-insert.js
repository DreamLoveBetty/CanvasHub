(function () {
  const state = {
    menu: null,
    mode: 'insert',
    trigger: '/',
    target: null,
    token: null,
    range: null,
    slashStart: -1,
    query: '',
    moduleType: '',
    currentBlockId: '',
    blocks: [],
    colors: [],
    moduleLabels: {},
    filtered: [],
    activeIndex: 0,
    loaded: false,
    loading: false,
    loadPromise: null,
    openRequestId: 0,
    error: '',
  };
  const TARGET_SELECTOR = '[data-text-node-input], #deskPromptChatInput, .desk-prompt-library textarea';
  const TOKEN_SELECTOR = '[data-prompt-block-token]';
  const MENU_ID = 'deskPromptBlockPicker';

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  }
  function moduleLabel(value) {
    const labels = { identity: '身份', appearance: '外貌', pose: '姿态', expression: '表情', clothing: '服装', makeup_hair: '妆发', accessories: '配饰', subject: '主体', style: '风格', lighting: '光线', composition: '构图', camera: '镜头', color: '色彩', scene: '场景', material: '材质', quality: '质量', constraints: '约束', goal: '生成目标', custom: '自定义' };
    return state.moduleLabels[value] || window.DesktopPromptLibrary?.getModuleLabel?.(value) || labels[value] || value || '素材';
  }
  function ensureMenu() {
    if (state.menu) return state.menu;
    const menu = document.createElement('div');
    menu.className = 'desk-prompt-slash-menu';
    menu.id = `${MENU_ID}Popup`;
    menu.innerHTML = `<div class="desk-prompt-slash-menu__head" aria-hidden="true"><strong data-prompt-picker-title>/ 提示词素材块</strong><span data-prompt-picker-hint>↑↓ 选择 · Enter 插入 · Esc 关闭</span></div><div class="desk-prompt-slash-menu__list" id="${MENU_ID}" role="listbox" tabindex="-1" aria-label="提示词素材块"></div>`;
    document.body.appendChild(menu);
    menu.addEventListener('mousedown', event => event.preventDefault());
    menu.addEventListener('click', event => {
      if (event.target.closest('[data-prompt-picker-retry]')) {
        retryLoad();
        return;
      }
      const button = event.target.closest('[data-prompt-slash-index]');
      if (!button) return;
      choose(Number(button.dataset.promptSlashIndex || 0));
    });
    menu.addEventListener('mousemove', event => {
      const button = event.target.closest('[data-prompt-slash-index]');
      if (!button) return;
      const index = Number(button.dataset.promptSlashIndex || 0);
      if (index === state.activeIndex) return;
      state.activeIndex = index;
      updateActiveOption({ scroll: false });
    });
    state.menu = menu;
    return menu;
  }
  async function loadBlocks(force = false) {
    if (state.loadPromise) {
      await state.loadPromise;
      if (!force) return state.blocks;
    }
    if (state.loaded && !force) return state.blocks;
    state.loading = true;
    state.error = '';
    const request = (async () => {
      const local = !force ? window.DesktopPromptLibrary?.getBlocks?.() : [];
      const blocksPromise = Array.isArray(local) && local.length
        ? Promise.resolve(local)
        : Promise.resolve(window.DesktopApi?.getPromptBlocks?.({ limit: 1000 })).then(result => Array.isArray(result?.items) ? result.items : []);
      const templatesPromise = Promise.resolve(window.DesktopApi?.getPromptTemplates?.()).catch(() => null);
      const [blocks, templateResult] = await Promise.all([blocksPromise, templatesPromise]);
      state.blocks = blocks;
      state.moduleLabels = {};
      (templateResult?.templates || []).forEach(template => (template.modules || []).forEach(module => {
        if (module?.key && module?.label) state.moduleLabels[module.key] = module.label;
      }));
      state.loaded = true;
      return state.blocks;
    })();
    state.loadPromise = request;
    try {
      return await request;
    } catch (error) {
      state.error = '素材块加载失败，点击重试';
      throw error;
    } finally {
      if (state.loadPromise === request) state.loadPromise = null;
      state.loading = false;
    }
  }
  function loadColors() {
    const colors = window.DesktopPromptLibrary?.getColorSchemes?.();
    state.colors = Array.isArray(colors) ? colors : [];
    return state.colors;
  }
  function loadChoices(force = false) {
    return state.trigger === '#' ? Promise.resolve(loadColors()) : loadBlocks(force);
  }
  function matchesTarget(target) { return target?.matches?.(TARGET_SELECTOR) || false; }
  function detectTextarea(target) {
    const caret = Number(target.selectionStart ?? 0);
    const before = String(target.value || '').slice(0, caret);
    const match = before.match(/(^|[\s，,。；;、])([/#])([^\s/#，,。；;、]*)$/);
    if (!match) return null;
    return { target, trigger: match[2], query: match[3] || '', slashStart: caret - (match[3] || '').length - 1, range: null };
  }
  function detectContentEditable(target) {
    const selection = window.getSelection?.();
    if (!selection || !selection.rangeCount) return null;
    const caretRange = selection.getRangeAt(0);
    if (!caretRange.collapsed || !target.contains(caretRange.startContainer) || caretRange.startContainer.nodeType !== Node.TEXT_NODE) return null;
    const text = caretRange.startContainer.nodeValue || '';
    const before = text.slice(0, caretRange.startOffset);
    const match = before.match(/(^|[\s，,。；;、])([/#])([^\s/#，,。；;、]*)$/);
    if (!match) return null;
    const range = document.createRange();
    range.setStart(caretRange.startContainer, caretRange.startOffset - (match[3] || '').length - 1);
    range.setEnd(caretRange.startContainer, caretRange.startOffset);
    return { target, trigger: match[2], query: match[3] || '', slashStart: -1, range };
  }
  function detect(target) {
    if (!matchesTarget(target)) return null;
    return target.isContentEditable ? detectContentEditable(target) : detectTextarea(target);
  }
  function filterBlocks() {
    const query = state.query.trim().toLowerCase();
    const limit = state.mode === 'replace' ? 60 : 30;
    const source = state.trigger === '#' ? state.colors : state.blocks;
    state.filtered = source.filter(block => {
      if (state.mode === 'replace') {
        if (state.trigger === '/') {
          if (!state.moduleType || block.module_type !== state.moduleType) return false;
          if (state.currentBlockId && String(block.id || '') === state.currentBlockId) return false;
        } else if (state.currentBlockId && `color-scheme:${block.id}` === state.currentBlockId) return false;
      }
      const searchable = state.trigger === '#'
        ? [block.name, block.description, block.prompt, ...(block.colors || []), ...(block.categories || []), ...(block.scenes || []), ...(block.tags || [])]
        : [block.name, block.content, block.compact_content, block.english_content, block.module_type, moduleLabel(block.module_type), ...(block.tags || [])];
      return !query || searchable.join(' ').toLowerCase().includes(query);
    }).slice(0, limit);
    state.activeIndex = Math.min(state.activeIndex, Math.max(0, state.filtered.length - 1));
  }
  function updateActiveDescendant() {
    const activeId = !state.error && state.filtered.length ? `${MENU_ID}Option${state.activeIndex}` : '';
    const owner = state.mode === 'replace' ? state.menu?.querySelector('.desk-prompt-slash-menu__list') : state.target;
    if (activeId) owner?.setAttribute?.('aria-activedescendant', activeId);
    else owner?.removeAttribute?.('aria-activedescendant');
  }
  function updateActiveOption(options = {}) {
    const list = state.menu?.querySelector('.desk-prompt-slash-menu__list');
    if (!list) return;
    list.querySelectorAll('[data-prompt-slash-index]').forEach(button => {
      const active = Number(button.dataset.promptSlashIndex || 0) === state.activeIndex;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    updateActiveDescendant();
    if (options.scroll !== false) list.querySelector('.is-active')?.scrollIntoView?.({ block: 'nearest' });
  }
  function render() {
    const menu = ensureMenu();
    const colorMode = state.trigger === '#';
    menu.classList.toggle('is-replace-mode', state.mode === 'replace');
    menu.classList.toggle('is-color-mode', colorMode);
    const title = menu.querySelector('[data-prompt-picker-title]');
    const hint = menu.querySelector('[data-prompt-picker-hint]');
    const list = menu.querySelector('.desk-prompt-slash-menu__list');
    if (state.mode === 'replace') {
      if (title) title.textContent = colorMode ? '# 替换色彩方案' : `替换·${moduleLabel(state.moduleType)}`;
      if (hint) hint.textContent = '↑↓ 选择 · Enter 替换 · Esc 关闭';
      list.setAttribute('aria-label', colorMode ? '选择替换色彩方案' : `选择同类型${moduleLabel(state.moduleType)}素材块`);
    } else {
      if (title) title.textContent = colorMode ? '# 色彩方案' : '/ 提示词素材块';
      if (hint) hint.textContent = '↑↓ 选择 · Enter 插入 · Esc 关闭';
      list.setAttribute('aria-label', colorMode ? '插入色彩方案' : '插入提示词素材块');
    }
    if (state.error) {
      list.innerHTML = `<button type="button" class="desk-prompt-slash-menu__retry" data-prompt-picker-retry>${escapeHtml(state.error)}</button>`;
      updateActiveDescendant();
      return;
    }
    if (!state.filtered.length) {
      const emptyMessage = state.loading
        ? '正在读取素材块…'
        : state.mode === 'replace'
        ? (state.moduleType ? '该类型暂无其它素材块' : '无法识别该素材块的类型')
        : colorMode ? '没有匹配的色彩方案' : '没有匹配的素材块';
      list.innerHTML = `<div class="desk-prompt-library__empty" role="option" aria-disabled="true">${emptyMessage}</div>`;
      updateActiveDescendant();
      return;
    }
    list.innerHTML = state.filtered.map((block, index) => {
      const preview = colorMode
        ? `<span class="desk-prompt-slash-menu__palette" aria-hidden="true">${(block.colors || []).slice(0, 5).map(color => `<i style="background:${escapeHtml(color)}"></i>`).join('')}</span>`
        : `<span class="desk-prompt-slash-menu__icon">${escapeHtml(moduleLabel(block.module_type).slice(0, 1))}</span>`;
      const summary = colorMode ? block.description : (block.compact_content || block.content || '');
      const type = colorMode ? (block.custom ? '自定义' : `${(block.colors || []).length} 色`) : moduleLabel(block.module_type);
      return `<button type="button" id="${MENU_ID}Option${index}" class="desk-prompt-slash-menu__item ${index === state.activeIndex ? 'is-active' : ''}" role="option" aria-selected="${index === state.activeIndex}" aria-posinset="${index + 1}" aria-setsize="${state.filtered.length}" data-prompt-slash-index="${index}">
        ${preview}
        <span class="desk-prompt-slash-menu__copy"><strong>${escapeHtml(block.name || (colorMode ? '未命名配色' : '未命名素材块'))}</strong><span>${escapeHtml(summary)}</span></span>
        <span class="desk-prompt-slash-menu__type">${escapeHtml(type)}</span>
      </button>`;
    }).join('');
    updateActiveOption();
  }
  async function retryLoad() {
    if (state.loading || !state.menu?.classList.contains('is-open')) return;
    const requestId = state.openRequestId;
    const mode = state.mode;
    const target = state.target;
    const token = state.token;
    state.loaded = false;
    state.blocks = [];
    const blocksPromise = loadChoices(true);
    filterBlocks(); render(); positionMenu();
    try {
      await blocksPromise;
      if (requestId !== state.openRequestId || mode !== state.mode || target !== state.target || token !== state.token) return;
      filterBlocks(); render(); positionMenu();
    } catch (error) {
      if (requestId !== state.openRequestId) return;
      console.error('[PromptInsert]', error);
      filterBlocks(); render(); positionMenu();
    }
  }
  function positionMenu() {
    const menu = ensureMenu();
    let rect = null;
    if (state.token) rect = state.token.getBoundingClientRect?.();
    if (!rect && state.range) {
      try { rect = state.range.getBoundingClientRect(); } catch (error) { rect = null; }
    }
    if (!rect || (!rect.width && !rect.height)) rect = state.target?.getBoundingClientRect?.();
    if (!rect) return;
    const width = Math.min(340, window.innerWidth - 24);
    const estimatedHeight = Math.min(310, 48 + Math.max(1, state.filtered.length) * 42);
    const left = Math.max(12, Math.min(window.innerWidth - width - 12, rect.left + 8));
    const below = rect.bottom + 7;
    const top = below + estimatedHeight <= window.innerHeight - 10 ? below : Math.max(10, rect.top - estimatedHeight - 7);
    menu.style.left = `${left}px`; menu.style.top = `${top}px`;
  }
  function clearOwnerAria() {
    const owner = state.mode === 'replace' ? state.token : state.target;
    owner?.setAttribute?.('aria-expanded', 'false');
    owner?.removeAttribute?.('aria-controls');
    owner?.removeAttribute?.('aria-activedescendant');
  }
  function setOwnerAria(owner) {
    owner?.setAttribute?.('aria-haspopup', 'listbox');
    owner?.setAttribute?.('aria-controls', MENU_ID);
    owner?.setAttribute?.('aria-expanded', 'true');
  }
  async function openFor(match) {
    clearOwnerAria();
    const requestId = ++state.openRequestId;
    state.mode = 'insert'; state.trigger = match.trigger || '/'; state.target = match.target; state.token = null; state.query = match.query; state.moduleType = ''; state.currentBlockId = '';
    state.slashStart = match.slashStart; state.range = match.range; state.activeIndex = 0;
    setOwnerAria(state.target);
    ensureMenu().classList.add('is-open');
    const blocksPromise = loadChoices();
    filterBlocks(); render(); positionMenu();
    try { await blocksPromise; if (requestId !== state.openRequestId || state.target !== match.target || state.mode !== 'insert') return; filterBlocks(); render(); positionMenu(); }
    catch (error) { console.error('[PromptInsert]', error); filterBlocks(); render(); positionMenu(); }
  }
  function tokenData(token, names) {
    for (const name of names) {
      const value = String(token?.dataset?.[name] || '').trim();
      if (value) return value;
    }
    return '';
  }
  function tokenModuleType(token) {
    return tokenData(token, ['promptBlockModuleType', 'promptModuleType', 'moduleType', 'promptBlockType']);
  }
  function tokenBlockId(token) {
    return tokenData(token, ['promptBlockId', 'blockId']);
  }
  function inferTokenBlock(token) {
    const ids = [tokenBlockId(token), tokenData(token, ['promptBlockToken'])].filter(Boolean);
    return state.blocks.find(block => ids.includes(String(block.id || ''))) || null;
  }
  async function openForToken(token) {
    if (!token?.closest?.('[data-text-node-input]')) return;
    clearOwnerAria();
    const requestId = ++state.openRequestId;
    state.mode = 'replace'; state.target = null; state.token = token; state.range = null; state.slashStart = -1; state.query = '';
    state.moduleType = tokenModuleType(token); state.currentBlockId = tokenBlockId(token); state.trigger = state.currentBlockId.startsWith('color-scheme:') ? '#' : '/'; state.activeIndex = 0;
    setOwnerAria(token);
    const menu = ensureMenu();
    menu.classList.add('is-open');
    const blocksPromise = loadChoices();
    filterBlocks(); render(); positionMenu();
    requestAnimationFrame(() => { if (state.token === token && state.mode === 'replace') menu.querySelector('.desk-prompt-slash-menu__list')?.focus({ preventScroll: true }); });
    try {
      await blocksPromise;
      if (requestId !== state.openRequestId || state.token !== token || state.mode !== 'replace') return;
      const currentBlock = inferTokenBlock(token);
      if (!state.moduleType) state.moduleType = currentBlock?.module_type || '';
      if (!state.currentBlockId && currentBlock?.id) state.currentBlockId = String(currentBlock.id);
      filterBlocks(); render(); positionMenu();
    } catch (error) {
      if (requestId !== state.openRequestId) return;
      console.error('[PromptInsert]', error); filterBlocks(); render(); positionMenu();
    }
  }
  function close(options = {}) {
    const restoreToken = options.restoreFocus && state.mode === 'replace' ? state.token : null;
    clearOwnerAria();
    state.openRequestId += 1;
    state.menu?.classList.remove('is-open');
    state.menu?.classList.remove('is-replace-mode');
    state.menu?.querySelector('.desk-prompt-slash-menu__list')?.removeAttribute('aria-activedescendant');
    state.mode = 'insert'; state.trigger = '/'; state.target = null; state.token = null; state.range = null; state.slashStart = -1; state.query = ''; state.moduleType = ''; state.currentBlockId = ''; state.filtered = []; state.activeIndex = 0;
    if (restoreToken?.isConnected) restoreToken.focus?.({ preventScroll: true });
  }
  function dispatchInput(target) {
    target.dispatchEvent(new Event('input', { bubbles: true, inputType: 'insertText' }));
    target.dispatchEvent(new CustomEvent('prompt-editor:change', { bubbles: true }));
  }
  function insertTextarea(target, block) {
    const caret = Number(target.selectionStart ?? target.value.length);
    const start = state.slashStart >= 0 ? state.slashStart : caret;
    const before = target.value.slice(0, start); const after = target.value.slice(caret);
    const content = String(block.content || '').trim();
    const lead = before && !/[\s，,。；;、]$/.test(before) ? '，' : '';
    const trail = after && !/^[\s，,。；;、]/.test(after) ? '，' : '';
    target.value = `${before}${lead}${content}${trail}${after}`;
    const position = before.length + lead.length + content.length + trail.length;
    target.focus({ preventScroll: true }); target.setSelectionRange?.(position, position); dispatchInput(target);
  }
  function insertContentEditable(target, block) {
    target.focus({ preventScroll: true });
    const range = state.range?.cloneRange();
    if (!range || !target.contains(range.startContainer)) return;
    range.deleteContents();
    const textNode = document.createTextNode(`${String(block.content || '').trim()} `);
    range.insertNode(textNode);
    const caret = document.createRange(); caret.setStartAfter(textNode); caret.collapse(true);
    const selection = window.getSelection?.(); selection?.removeAllRanges(); selection?.addRange(caret); dispatchInput(target);
  }
  function insertTextNodeToken(target, block) {
    const canvas = window.DesktopCanvas;
    if (!canvas?.insertPromptBlockToken) throw new Error('画布素材块编辑器未加载');
    const nodeId = target.closest?.('.desk-node--text[data-node-id]')?.dataset.nodeId || '';
    const targetInfo = canvas.getPromptTargetInfo?.(nodeId) || (nodeId ? { nodeId, type: 'text', label: '文本节点' } : null);
    const range = state.range?.cloneRange?.() || state.range;
    canvas.insertPromptBlockToken(block, { target, range, targetInfo });
  }
  function replaceToken(token, block) {
    const canvas = window.DesktopCanvas;
    if (!canvas?.replacePromptBlockToken) throw new Error('画布素材块编辑器未加载');
    canvas.replacePromptBlockToken(token, block);
  }
  function reportError(error) {
    console.error('[PromptInsert]', error);
    if (window.DesktopResults?.showError) window.DesktopResults.showError(error instanceof Error ? error : new Error(String(error || '素材块操作失败')));
    else window.DesktopResults?.showTransientMessage?.(error?.message || '素材块操作失败', 'error');
  }
  function choiceBlock(choice) {
    if (state.trigger !== '#') return choice;
    return window.DesktopPromptLibrary?.colorPromptBlock?.(choice) || {
      id: `color-scheme:${choice.id}`,
      name: `配色 · ${choice.name || '未命名配色'}`,
      module_type: 'color',
      content: String(choice.prompt || '').trim(),
      compact_content: `${choice.description || ''} ${(choice.colors || []).join(' ')}`.trim(),
      english_content: '',
      applicable_types: [],
      colors: (choice.colors || []).slice(0, 5),
      tags: [...(choice.tags || []), ...(choice.colors || [])],
    };
  }
  function choose(index) {
    const choice = state.filtered[index];
    if (!choice) return;
    const trigger = state.trigger;
    const block = choiceBlock(choice);
    if (!block?.content) return;
    try {
      if (state.mode === 'replace') {
        if (!state.token) return;
        replaceToken(state.token, block);
      } else {
        const target = state.target;
        if (!target) return;
        if (target.matches?.('[data-text-node-input]') && target.isContentEditable) insertTextNodeToken(target, block);
        else if (target.isContentEditable) insertContentEditable(target, block);
        else insertTextarea(target, block);
      }
      if (trigger === '/' && block.id) window.DesktopApi?.markPromptBlockUsed?.(block.id).catch(() => {});
      close();
    } catch (error) { reportError(error); }
  }
  function onInput(event) {
    const target = event.target?.closest?.(TARGET_SELECTOR);
    if (!target) return;
    const match = detect(target);
    if (!match) { if (state.target === target) close(); return; }
    openFor(match);
  }
  function onKeydown(event) {
    if (event.isComposing || event.keyCode === 229) return;
    const token = event.target?.closest?.(TOKEN_SELECTOR);
    if (!state.menu?.classList.contains('is-open')) {
      if (token?.closest?.('[data-text-node-input]') && ['Enter', ' ', 'ArrowDown'].includes(event.key)) {
        event.preventDefault(); event.stopPropagation(); openForToken(token);
      }
      return;
    }
    if (state.error && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault(); event.stopPropagation(); retryLoad(); return;
    }
    if (event.key === 'ArrowDown') { event.preventDefault(); event.stopPropagation(); state.activeIndex = (state.activeIndex + 1) % Math.max(1, state.filtered.length); updateActiveOption(); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); event.stopPropagation(); state.activeIndex = (state.activeIndex - 1 + Math.max(1, state.filtered.length)) % Math.max(1, state.filtered.length); updateActiveOption(); }
    else if ((event.key === 'Enter' || (event.key === 'Tab' && state.mode === 'insert')) && !state.error && state.filtered.length) { event.preventDefault(); event.stopPropagation(); choose(state.activeIndex); }
    else if (event.key === 'Tab' && state.mode === 'replace') { event.preventDefault(); event.stopPropagation(); close({ restoreFocus: true }); }
    else if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close({ restoreFocus: true }); }
  }
  function onTokenClick(event) {
    const token = event.target?.closest?.(TOKEN_SELECTOR);
    if (!token?.closest?.('[data-text-node-input]')) return;
    event.preventDefault();
    if (state.mode === 'replace' && state.token === token && state.menu?.classList.contains('is-open')) close({ restoreFocus: true });
    else openForToken(token);
  }
  function init() {
    ensureMenu();
    document.addEventListener('input', onInput, true);
    document.addEventListener('keydown', onKeydown, true);
    document.addEventListener('click', onTokenClick, true);
    document.addEventListener('mousedown', event => { if (state.menu?.contains(event.target) || state.token?.contains?.(event.target) || event.target?.closest?.(TARGET_SELECTOR) === state.target) return; close(); }, true);
    document.addEventListener('scroll', event => {
      if (!state.menu?.classList.contains('is-open') || state.menu.contains(event.target)) return;
      close({ restoreFocus: state.mode === 'replace' });
    }, true);
    window.addEventListener('resize', () => { if (state.target || state.token) positionMenu(); });
    window.visualViewport?.addEventListener('resize', () => {
      if (state.menu?.classList.contains('is-open')) close({ restoreFocus: state.mode === 'replace' });
    });
  }
  window.DesktopPromptInsert = {
    init,
    close,
    isOpen: () => !!state.menu?.classList.contains('is-open'),
    refresh: async () => {
      state.loaded = false;
      loadColors();
      try {
        return await loadBlocks(true);
      } finally {
        if (state.menu?.classList.contains('is-open')) { filterBlocks(); render(); positionMenu(); }
      }
    },
  };
})();

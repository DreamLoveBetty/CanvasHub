(function () {
  const els = {};
  let canvas = null;
  let activeNodeId = '';
  let syncingSelection = false;
  let activeProjectMeta = null;
  let activePageId = 'page_1';
  let selectedPresetId = 'xhs_3_4';
  let selectedTemplateId = 'xhs_seed_cover';
  let stageZoomMode = 'fit';
  let stageZoom = 1;
  let layersPanelCollapsed = false;
  let pageTreeCollapsed = false;
  let draggingLayerIndex = null;
  let renamingLayerIndex = null;
  let renamingGroupId = '';
  let renamingPageId = null;
  let selectedLayerIndices = [];
  let collapsedGroupIds = new Set();
  let editingGroupImageObject = null;
  let editingGroupImageLayerIndex = -1;
  let isolatedGroupId = '';
  let isolationObjectStates = new Map();
  let isolationCanvasSelection = true;
  let isolationVisualsSuspended = false;
  let layerFocusFrame = 0;
  let lastGroupImageClickTarget = null;
  let lastGroupImageClickAt = 0;
  let syncingLayerSelection = false;
  let activeMultiDrag = null;
  let layoutClipboard = null;
  let pendingTemplateImageVariable = '';
  let pendingImageReplacement = false;
  let projectFonts = [];
  let fontsReadyPromise = null;
  let undoStack = [];
  let redoStack = [];
  let historySnapshotKey = '';
  let historyTimer = null;
  let pendingHistoryLabel = '';
  let isRestoringHistory = false;

  const defaultTextFont = '思源宋体';
  const systemFonts = [
    { family: 'PingFang SC', label: '苹方 SC（系统）', source: 'system' },
    { family: 'Microsoft YaHei', label: '微软雅黑（系统）', source: 'system' },
    { family: 'SimHei', label: '黑体（系统）', source: 'system' },
    { family: 'SimSun', label: '宋体（系统）', source: 'system' },
    { family: 'Arial', label: 'Arial', source: 'system' }
  ];

  const fontWeightOptions = [
    { value: 100, label: '100 极细' },
    { value: 200, label: '200 纤细' },
    { value: 300, label: '300 细体' },
    { value: 400, label: '400 常规' },
    { value: 500, label: '500 中等' },
    { value: 600, label: '600 半粗' },
    { value: 700, label: '700 粗体' },
    { value: 800, label: '800 特粗' },
    { value: 900, label: '900 黑体' }
  ];

  const historyLimit = 30;
  const layerPasteOffset = 12;
  const layerDuplicateOffset = 8;
  const maxPasteOffsetSteps = 3;

  const canvasPresets = [
    { id: 'xhs_3_4', platform: 'xhs', name: '小红书封面 / 图文页', width: 1080, height: 1440, ratio: '3:4', note: '首图和组图主力尺寸' },
    { id: 'xhs_square', platform: 'xhs', name: '小红书方图', width: 1080, height: 1080, ratio: '1:1', note: '产品、清单、对比图' },
    { id: 'xhs_story', platform: 'xhs', name: '小红书竖版海报', width: 1080, height: 1920, ratio: '9:16', note: '长图切片、视频封面' },
    { id: 'wechat_cover', platform: 'wechat', name: '公众号头条封面', width: 900, height: 383, ratio: '2.35:1', note: '列表封面标准比例' },
    { id: 'wechat_cover_hd', platform: 'wechat', name: '公众号高清封面', width: 1080, height: 460, ratio: '2.35:1', note: '按头条比例放大' },
    { id: 'wechat_square', platform: 'wechat', name: '公众号次条缩略图', width: 500, height: 500, ratio: '1:1', note: '多图文次条封面' },
    { id: 'wide_16_9', platform: 'general', name: '通用横图', width: 1920, height: 1080, ratio: '16:9', note: '横版海报、视频封面' }
  ];

  const layoutTemplates = [
    { id: 'xhs_seed_cover', platform: 'xhs', name: '种草封面', desc: '大标题 + 主图 + 卖点标签', accent: '#ff6f91' },
    { id: 'xhs_checklist', platform: 'xhs', name: '清单教程', desc: '标题 + 步骤清单 + 重点卡片', accent: '#36d2b0' },
    { id: 'xhs_compare', platform: 'xhs', name: '对比页', desc: '左右对比 / 前后对比', accent: '#8b5cf6' },
    { id: 'wechat_headline', platform: 'wechat', name: '公众号头图', desc: '标题 + 摘要 + 署名', accent: '#084fbd' },
    { id: 'wechat_digest', platform: 'wechat', name: '摘要封面', desc: '大标题 + 摘要块 + 背景区', accent: '#111827' },
    { id: 'general_poster', platform: 'general', name: '通用海报', desc: '主视觉 + 标题 + 行动文案', accent: '#084fbd' },
    { id: 'blank', platform: 'all', name: '空白生产画布', desc: '只创建真实尺寸画布', accent: '#637182' }
  ];

  function $(id) {
    return document.getElementById(id);
  }

  function collectElements() {
    [
      'deskLayoutEditor',
      'deskLayoutLayersPanel',
      'deskLayoutLayersCollapseBtn',
      'deskLayoutIsolationBar',
      'deskLayoutIsolationTitle',
      'deskLayoutIsolationMeta',
      'deskLayoutIsolationExitBtn',
      'deskLayoutTitle',
      'deskLayoutMeta',
      'deskLayoutStage',
      'deskLayoutPageShell',
      'deskLayoutPage',
      'deskLayoutCanvas',
      'deskLayoutPageList',
      'deskLayoutLayerList',
      'deskLayoutStatus',
      'deskLayoutDraftSelect',
      'deskLayoutLoadBtn',
      'deskLayoutTemplateBtn',
      'deskLayoutFitBtn',
      'deskLayoutSafeAreaBtn',
      'deskLayoutSnapBtn',
      'deskLayoutZoomSelect',
      'deskLayoutUndoBtn',
      'deskLayoutRedoBtn',
      'deskLayoutAddTextBtn',
      'deskLayoutAddImageBtn',
      'deskLayoutSaveBtn',
      'deskLayoutExportBtn',
      'deskLayoutCloseBtn',
      'deskLayoutImageInput',
      'deskLayoutCreate',
      'deskLayoutPresetList',
      'deskLayoutTemplateList',
      'deskLayoutCreateHint',
      'deskLayoutCreateBtn',
      'deskLayoutObjectToolbar',
      'deskLayoutAssistOverlay',
      'deskLayoutSafeAreaGuide',
      'deskLayoutGroupSelectionBox',
      'deskLayoutGuideV',
      'deskLayoutGuideH',
      'deskLayoutToolbarMeta',
      'deskLayoutBoldBtn',
      'deskLayoutInspectorEmpty',
      'deskLayoutSelectionMeta',
      'deskLayoutSelectionMetaText',
      'deskLayoutReturnGroupBtn',
      'deskLayoutTemplateControls',
      'deskLayoutTemplateFields',
      'deskLayoutTextControls',
      'deskLayoutImageControls',
      'deskLayoutObjectControls',
      'deskLayoutTextInput',
      'deskLayoutFontFamilySelect',
      'deskLayoutFontWeightSelect',
      'deskLayoutFontSizeInput',
      'deskLayoutLineHeightInput',
      'deskLayoutCharSpacingInput',
      'deskLayoutColorInput',
      'deskLayoutObjectXInput',
      'deskLayoutObjectYInput',
      'deskLayoutObjectWInput',
      'deskLayoutObjectHInput',
      'deskLayoutObjectAngleInput',
      'deskLayoutObjectOpacityInput',
      'deskLayoutAlignScopeSelect',
      'deskLayoutImageFitSelect',
      'deskLayoutImageFocalXInput',
      'deskLayoutImageFocalYInput',
      'deskLayoutImageCropZoomInput',
      'deskLayoutImageCropResetBtn',
      'deskLayoutReplaceImageBtn',
      'deskLayoutForwardBtn',
      'deskLayoutBackwardBtn',
      'deskLayoutCopyBtn',
      'deskLayoutPasteBtn',
      'deskLayoutDuplicateBtn',
      'deskLayoutGroupBtn',
      'deskLayoutUngroupBtn',
      'deskLayoutDeleteBtn'
    ].forEach(id => {
      els[id] = $(id);
    });
  }

  function getActiveNode() {
    return activeNodeId ? DesktopState.state.canvas.nodes[activeNodeId] : null;
  }

  function getPreset(id) {
    return canvasPresets.find(preset => preset.id === id) || canvasPresets[0];
  }

  function getTemplate(id) {
    return layoutTemplates.find(template => template.id === id) || layoutTemplates[0];
  }

  function getTemplatesForPreset(presetId) {
    const preset = getPreset(presetId);
    const matches = layoutTemplates.filter(template => template.platform === 'all' || template.platform === preset.platform);
    return matches.length ? matches : layoutTemplates;
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function cssEscape(value) {
    if (window.CSS?.escape) return window.CSS.escape(String(value));
    return String(value ?? '').replace(/["\\]/g, '\\$&');
  }

  function cssString(value) {
    return String(value ?? '').replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  }

  function normalizeFontRecord(font) {
    const family = String(font?.family || font?.label || '').trim();
    if (!family) return null;
    const faces = Array.isArray(font.faces) ? font.faces : [];
    return {
      family,
      label: String(font.label || family).trim(),
      source: font.source || 'project',
      faces: faces
        .map(face => ({
          url: String(face?.url || '').trim(),
          weight: Number(face?.weight) || 400,
          style: String(face?.style || 'normal')
        }))
        .filter(face => face.url)
        .sort((a, b) => a.weight - b.weight)
    };
  }

  function getTextFonts() {
    const map = new Map();
    [...projectFonts, ...systemFonts].forEach(font => {
      const normalized = normalizeFontRecord(font);
      if (!normalized || map.has(normalized.family)) return;
      map.set(normalized.family, normalized);
    });
    return [...map.values()];
  }

  function getFontRecord(family) {
    const key = String(family || '').trim();
    if (!key) return null;
    return getTextFonts().find(font => font.family === key) || null;
  }

  function clampNumber(value, min, max, fallback) {
    const number = Number(value);
    if (!Number.isFinite(number)) return fallback;
    return Math.max(min, Math.min(max, number));
  }

  function formatCompactNumber(value, fallback = 0) {
    const number = Number.isFinite(Number(value)) ? Number(value) : fallback;
    const formatted = String(Math.round(number * 100) / 100).replace(/\.?0+$/, '');
    return formatted || '0';
  }

  function formatInspectorNumber(value, fallback = 0) {
    const number = Number.isFinite(Number(value)) ? Number(value) : fallback;
    return String(Math.round(number));
  }

  function normalizeFontWeight(value) {
    const raw = String(value ?? '').trim().toLowerCase();
    if (raw === 'bold') return 700;
    if (raw === 'normal' || raw === '') return 400;
    return Math.round(clampNumber(Number(raw), 100, 900, 400) / 100) * 100;
  }

  function getDefaultTextFont() {
    return getFontRecord(defaultTextFont)?.family || systemFonts[systemFonts.length - 1]?.family || 'Arial';
  }

  function fontCssStack(family) {
    return family ? `"${cssString(family)}", "PingFang SC", Arial, sans-serif` : '';
  }

  function registerProjectFontFaces(fonts) {
    const rules = (fonts || [])
      .flatMap(font => (font.faces || []).map(face => {
        return [
          '@font-face {',
          `  font-family: "${cssString(font.family)}";`,
          `  src: url("${cssString(face.url)}");`,
          `  font-weight: ${Number(face.weight) || 400};`,
          `  font-style: ${face.style || 'normal'};`,
          '  font-display: swap;',
          '}'
        ].join('\n');
      }))
      .join('\n\n');
    let style = document.getElementById('desk-layout-project-fonts');
    if (!style) {
      style = document.createElement('style');
      style.id = 'desk-layout-project-fonts';
      document.head.appendChild(style);
    }
    style.textContent = rules;
  }

  function renderFontFamilyOptions(selectedFamily = '') {
    if (!els.deskLayoutFontFamilySelect) return;
    const selected = String(selectedFamily || '').trim();
    const fonts = getTextFonts();
    const hasSelected = !selected || fonts.some(font => font.family === selected);
    const projectOptions = fonts
      .filter(font => font.source !== 'system')
      .map(font => `<option value="${escapeHtml(font.family)}">${escapeHtml(font.label)}</option>`);
    const systemOptions = fonts
      .filter(font => font.source === 'system')
      .map(font => `<option value="${escapeHtml(font.family)}">${escapeHtml(font.label)}</option>`);
    els.deskLayoutFontFamilySelect.innerHTML = [
      !hasSelected ? `<optgroup label="当前字体"><option value="${escapeHtml(selected)}">${escapeHtml(selected)}</option></optgroup>` : '',
      projectOptions.length ? `<optgroup label="项目字体">${projectOptions.join('')}</optgroup>` : '',
      systemOptions.length ? `<optgroup label="系统字体">${systemOptions.join('')}</optgroup>` : ''
    ].filter(Boolean).join('');
    if (selected) els.deskLayoutFontFamilySelect.value = selected;
    if (!els.deskLayoutFontFamilySelect.value) {
      els.deskLayoutFontFamilySelect.value = getDefaultTextFont();
    }
    els.deskLayoutFontFamilySelect.style.fontFamily = fontCssStack(els.deskLayoutFontFamilySelect.value);
  }

  function renderFontWeightOptions(selectedWeight = 400) {
    if (!els.deskLayoutFontWeightSelect) return;
    const selected = normalizeFontWeight(selectedWeight);
    els.deskLayoutFontWeightSelect.innerHTML = fontWeightOptions
      .map(option => `<option value="${option.value}">${escapeHtml(option.label)}</option>`)
      .join('');
    els.deskLayoutFontWeightSelect.value = String(selected);
    if (!els.deskLayoutFontWeightSelect.value) {
      els.deskLayoutFontWeightSelect.value = '400';
    }
  }

  async function ensureLayoutFonts() {
    if (fontsReadyPromise) return fontsReadyPromise;
    renderFontFamilyOptions(getDefaultTextFont());
    fontsReadyPromise = (async () => {
      try {
        const data = await window.DesktopApi?.listLayoutFonts?.();
        const fonts = Array.isArray(data?.fonts) ? data.fonts : [];
        projectFonts = fonts.map(normalizeFontRecord).filter(font => font && font.faces.length);
        registerProjectFontFaces(projectFonts);
        const currentValue = els.deskLayoutFontFamilySelect?.value || '';
        const shouldUseProjectDefault = !currentValue || currentValue === 'Arial';
        renderFontFamilyOptions(shouldUseProjectDefault ? getDefaultTextFont() : currentValue);
      } catch (error) {
        projectFonts = [];
        renderFontFamilyOptions(els.deskLayoutFontFamilySelect?.value || getDefaultTextFont());
        fontsReadyPromise = null;
      }
      await loadFontFamily(getDefaultTextFont());
      return projectFonts;
    })();
    return fontsReadyPromise;
  }

  async function loadFontFamily(family, weight = 400, sampleText = '排版字体Aa123') {
    const fontFamily = String(family || '').trim();
    if (!fontFamily || !document.fonts?.load) return;
    const numericWeight = Math.max(100, Math.min(900, Number(weight) || 400));
    try {
      await document.fonts.load(`${numericWeight} 32px "${cssString(fontFamily)}"`, String(sampleText || '排版字体Aa123'));
    } catch (error) {
      // 字体文件可能来自用户手动放入目录，失败时保持系统降级字体。
    }
  }

  function refreshTextObjectMetrics(object) {
    if (!object || !isTextObject(object)) return;
    object.dirty = true;
    if (typeof object._clearCache === 'function') object._clearCache();
    if (typeof object.initDimensions === 'function') object.initDimensions();
    if (typeof object.setCoords === 'function') object.setCoords();
  }

  async function ensureCanvasFontsLoaded(targetCanvas = canvas) {
    if (!targetCanvas) return;
    await ensureLayoutFonts();
    const fonts = targetCanvas.getObjects()
      .filter(object => ['i-text', 'text', 'textbox'].includes(object.type))
      .map(object => ({
        object,
        family: String(object.fontFamily || '').trim(),
        weight: object.fontWeight || 400,
        sampleText: object.text || '排版字体Aa123'
      }))
      .filter(item => item.family);
    await Promise.all(fonts.map(item => loadFontFamily(item.family, item.weight, item.sampleText)));
    fonts.forEach(item => refreshTextObjectMetrics(item.object));
    try {
      await document.fonts?.ready;
    } catch (error) {
      // 输出前尽量等待字体，失败时让浏览器使用降级渲染。
    }
  }

  function clearGroupImageEditTarget() {
    editingGroupImageObject = null;
    editingGroupImageLayerIndex = -1;
  }

  function setGroupImageEditTarget(object) {
    editingGroupImageObject = object || null;
    editingGroupImageLayerIndex = object && canvas ? canvas.getObjects().indexOf(object) : -1;
  }

  function getGroupImageEditTarget() {
    if (!canvas) return null;
    const objects = canvas.getObjects();
    if (editingGroupImageObject && objects.includes(editingGroupImageObject)) return editingGroupImageObject;
    const indexedObject = editingGroupImageLayerIndex >= 0 ? objects[editingGroupImageLayerIndex] : null;
    if (isImageObject(indexedObject)) {
      editingGroupImageObject = indexedObject;
      return indexedObject;
    }
    return null;
  }

  function resolveCanvasGroupImageObject(target, group) {
    if (!canvas || !group) return null;
    const objects = canvas.getObjects();
    if (objects.includes(target)) return target;
    const targetName = String(target?.name || '').trim();
    return group.objects.find(object => isImageObject(object) && targetName && object.name === targetName)
      || group.objects.find(isImageObject)
      || null;
  }

  function getIsolatedGroup() {
    return isolatedGroupId ? getGroupById(isolatedGroupId) : null;
  }

  function isGroupIsolated(groupId) {
    return Boolean(isolatedGroupId && groupId && isolatedGroupId === String(groupId));
  }

  function isObjectInIsolatedGroup(object) {
    return Boolean(object && isolatedGroupId && getLayerGroupId(object) === isolatedGroupId);
  }

  function updateLayerIsolationBar(group = getIsolatedGroup()) {
    const bar = els.deskLayoutIsolationBar;
    if (!bar) return;
    const active = Boolean(group && isolatedGroupId);
    bar.hidden = !active;
    els.deskLayoutLayerList?.classList.toggle('is-isolating', active);
    if (!active) return;
    const visibleCount = group.objects.filter(object => object && object.visible !== false).length;
    if (els.deskLayoutIsolationTitle) {
      els.deskLayoutIsolationTitle.textContent = `隔离编辑 · ${group.name || '组合图层'}`;
    }
    if (els.deskLayoutIsolationMeta) {
      els.deskLayoutIsolationMeta.textContent = `${visibleCount || group.objects.length} 个组内图层可编辑`;
    }
  }

  function focusLayerListOnIsolation() {
    if (!isolatedGroupId || !els.deskLayoutLayerList || layerFocusFrame) return;
    layerFocusFrame = requestAnimationFrame(() => {
      layerFocusFrame = 0;
      const list = els.deskLayoutLayerList;
      if (!list || !isolatedGroupId || list.hidden) return;
      const row = list.querySelector('.desk-layout-layer.is-active:not(.is-isolation-muted)')
        || list.querySelector(`.desk-layout-layer[data-layer-group-id="${cssEscape(isolatedGroupId)}"]`);
      if (!row) return;
      const listRect = list.getBoundingClientRect();
      const rowRect = row.getBoundingClientRect();
      if (rowRect.top < listRect.top || rowRect.bottom > listRect.bottom) {
        row.scrollIntoView({ block: 'nearest' });
      }
    });
  }

  function warnIsolationLocked() {
    const group = getIsolatedGroup();
    setStatus(`正在隔离编辑：${group?.name || '组合图层'}，请先退出隔离再编辑其它图层`, 'error');
  }

  function assignObjectToIsolatedGroup(object) {
    const group = getIsolatedGroup();
    if (!object || !group) return false;
    object.set({
      layoutGroupId: group.id,
      layoutGroupName: group.name || '组合图层'
    });
    return true;
  }

  function rememberIsolationState(object) {
    if (!object || isolationObjectStates.has(object)) return;
    isolationObjectStates.set(object, {
      opacity: object.opacity,
      selectable: object.selectable,
      evented: object.evented,
      hoverCursor: object.hoverCursor,
      moveCursor: object.moveCursor
    });
  }

  function restoreIsolationVisuals(options = {}) {
    if (!canvas || !isolationObjectStates.size) return;
    isolationObjectStates.forEach((state, object) => {
      if (!object) return;
      object.set({
        opacity: state.opacity,
        selectable: state.selectable,
        evented: state.evented,
        hoverCursor: state.hoverCursor,
        moveCursor: state.moveCursor
      });
      object.dirty = true;
      object.setCoords?.();
    });
    canvas.selection = isolationCanvasSelection;
    if (!options.keepState) isolationObjectStates = new Map();
    canvas.requestRenderAll();
  }

  function applyIsolationVisuals() {
    if (!canvas || !isolatedGroupId || isolationVisualsSuspended) return;
    const group = getIsolatedGroup();
    if (!group) {
      exitGroupIsolation({ silent: true });
      return;
    }
    const groupObjects = new Set(group.objects);
    canvas.getObjects().forEach(object => {
      rememberIsolationState(object);
      const state = isolationObjectStates.get(object) || {};
      if (groupObjects.has(object)) {
        object.set({
          opacity: state.opacity,
          selectable: state.selectable,
          evented: state.evented,
          hoverCursor: state.hoverCursor,
          moveCursor: state.moveCursor
        });
      } else {
        object.set({
          opacity: Math.max(0.1, Number(state.opacity ?? 1) * 0.22),
          selectable: false,
          evented: false,
          hoverCursor: 'default',
          moveCursor: 'default'
        });
      }
      object.dirty = true;
      object.setCoords?.();
    });
    canvas.selection = false;
    canvas.requestRenderAll();
  }

  function withIsolationVisualsSuspended(callback) {
    if (!isolatedGroupId || !canvas || isolationVisualsSuspended) return callback();
    isolationVisualsSuspended = true;
    restoreIsolationVisuals({ keepState: true });
    try {
      return callback();
    } finally {
      isolationVisualsSuspended = false;
      applyIsolationVisuals();
    }
  }

  function enterGroupIsolation(groupId, preferredObject = null) {
    if (!canvas) return false;
    const group = getGroupById(groupId);
    if (!group || group.objects.filter(object => object.visible !== false).length <= 1) return false;
    if (group.locked) {
      selectLayerGroup(group.id, preferredObject);
      setStatus('组合已锁定，先解锁后再进入隔离编辑', 'error');
      return false;
    }
    if (isolatedGroupId && isolatedGroupId !== group.id) {
      restoreIsolationVisuals();
    }
    if (!isolatedGroupId) {
      isolationCanvasSelection = canvas.selection;
    }
    isolatedGroupId = group.id;
    els.deskLayoutEditor?.classList.add('is-group-isolated');
    pageTreeCollapsed = false;
    collapsedGroupIds.delete(group.id);
    renderPages(activeProjectMeta);
    updateLayerIsolationBar(group);
    applyIsolationVisuals();
    selectLayerGroup(group.id, preferredObject);
    focusLayerListOnIsolation();
    setStatus(`隔离编辑：${group.name || '组合图层'}`, '');
    return true;
  }

  function exitGroupIsolation(options = {}) {
    if (!isolatedGroupId && !isolationObjectStates.size) return;
    const previousGroupId = isolatedGroupId;
    const previousGroupName = getGroupById(previousGroupId)?.name || '组合图层';
    isolatedGroupId = '';
    clearGroupImageEditTarget();
    restoreIsolationVisuals();
    els.deskLayoutEditor?.classList.remove('is-group-isolated');
    updateLayerIsolationBar(null);
    if (!options.keepSelection && previousGroupId && getGroupById(previousGroupId)) {
      selectLayerGroup(previousGroupId);
    } else if (!options.skipUi) {
      updateSelectionUi();
    }
    renderLayers();
    if (!options.silent) {
      setStatus(`已退出隔离：${previousGroupName}`, '');
    }
  }

  function handleCanvasSelectionChange() {
    if (!syncingLayerSelection && !isRestoringHistory) {
      const imageEditTarget = getGroupImageEditTarget();
      if (imageEditTarget && canvas?.getActiveObject?.() && canvas.getActiveObject() !== imageEditTarget) {
        clearGroupImageEditTarget();
      }
      if (isolatedGroupId) {
        const active = canvas?.getActiveObject?.();
        const activeObjects = active?.type === 'activeSelection' && typeof active.getObjects === 'function'
          ? active.getObjects().filter(Boolean)
          : (active ? [active] : []);
        const group = getIsolatedGroup();
        if (!group) {
          exitGroupIsolation({ silent: true });
        } else if (!activeObjects.length || activeObjects.some(object => !isObjectInIsolatedGroup(object))) {
          selectLayerGroup(group.id);
          return;
        }
        selectedLayerIndices = [];
        updateSelectionUi();
        return;
      }
      if (promoteCanvasSelectionToGroup()) return;
      selectedLayerIndices = [];
      clearGroupImageEditTarget();
    }
    updateSelectionUi();
  }

  function promoteCanvasSelectionToGroup() {
    if (!canvas) return false;
    const active = canvas.getActiveObject();
    const objects = active?.type === 'activeSelection' && typeof active.getObjects === 'function'
      ? active.getObjects().filter(Boolean)
      : (active ? [active] : []);
    if (objects.length !== 1) return false;
    const groupId = getLayerGroupId(objects[0]);
    const group = groupId ? getGroupById(groupId) : null;
    if (!group || group.objects.filter(object => object.visible !== false).length <= 1) return false;
    if (isGroupIsolated(groupId)) {
      selectedLayerIndices = [];
      updateSelectionUi();
      return true;
    }
    if (objects[0] !== getGroupImageEditTarget()) clearGroupImageEditTarget();
    selectLayerGroup(groupId, objects[0]);
    return true;
  }

  function handleCanvasDoubleClick(event) {
    const target = event?.target;
    if (!target) return;
    const groupId = getLayerGroupId(target);
    const group = groupId ? getGroupById(groupId) : null;
    if (!group || group.objects.filter(object => object.visible !== false).length <= 1) return;
    if (group.locked) {
      clearGroupImageEditTarget();
      selectLayerGroup(groupId, target);
      setStatus('组合已锁定，先解锁后再进入隔离编辑', 'error');
      return;
    }
    enterGroupIsolation(groupId, target);
    if (!isImageObject(target)) return;
    if (isLayerLocked(target)) {
      clearGroupImageEditTarget();
      selectLayerGroup(groupId, target);
      setStatus('图层已锁定，先解锁后再编辑图片', 'error');
      return;
    }
    window.setTimeout(() => {
      const latestGroup = getGroupById(groupId);
      if (!latestGroup || latestGroup.locked || isLayerLocked(target)) {
        clearGroupImageEditTarget();
        updateSelectionUi();
        return;
      }
      const editObject = resolveCanvasGroupImageObject(target, latestGroup);
      if (!editObject) return;
      setGroupImageEditTarget(editObject);
      rememberImageFrame(editObject);
      selectLayerGroup(groupId, editObject);
      updateSelectionUi();
      setStatus('正在编辑组内图片，可替换、适配或微调裁剪', '');
    }, 80);
  }

  function handleCanvasMouseDown(event) {
    const target = event?.target;
    const now = performance.now();
    if (target && getLayerGroupId(target)) {
      const isRepeatClick = lastGroupImageClickTarget === target && now - lastGroupImageClickAt < 360;
      lastGroupImageClickTarget = target;
      lastGroupImageClickAt = now;
      if (isRepeatClick) {
        lastGroupImageClickTarget = null;
        lastGroupImageClickAt = 0;
        handleCanvasDoubleClick(event);
        return;
      }
    } else {
      lastGroupImageClickTarget = null;
      lastGroupImageClickAt = 0;
    }
    beginMultiDrag(target);
  }

  function isLegacyTestProject(project) {
    return Number(project?.width) === 360 && Number(project?.height) === 520 && !project?.canvasJson;
  }

  function hasEditableProject(node) {
    if (!node) return false;
    if (node.layoutDraftId) return true;
    if (!node.layoutProject) return false;
    return !isLegacyTestProject(node.layoutProject);
  }

  function ensureFabricCanvas() {
    if (canvas) return canvas;
    if (!window.fabric || !els.deskLayoutCanvas) {
      throw new Error('Fabric.js 未加载');
    }
    canvas = new fabric.Canvas(els.deskLayoutCanvas, {
      backgroundColor: '#ffffff',
      preserveObjectStacking: true,
      selection: true
    });
    canvas.on('selection:created', handleCanvasSelectionChange);
    canvas.on('selection:updated', handleCanvasSelectionChange);
    canvas.on('selection:cleared', handleCanvasSelectionChange);
    canvas.on('mouse:down', handleCanvasMouseDown);
    canvas.on('mouse:dblclick', handleCanvasDoubleClick);
    canvas.on('object:moving', handleObjectMoving);
    canvas.on('object:scaling', handleObjectTransforming);
    canvas.on('object:rotating', handleObjectTransforming);
    canvas.on('text:editing:entered', updateSelectionUi);
    canvas.on('text:editing:exited', updateSelectionUi);
    canvas.on('object:modified', event => {
      const target = event?.target;
      getActiveArrangeObjects().forEach(object => {
        if (isImageObject(object)) rememberImageFrame(object);
        if (isTextObject(object)) refreshTextObjectMetrics(object);
        object.setCoords?.();
      });
      if (isImageObject(target)) rememberImageFrame(target);
      hideLayoutGuides();
      activeMultiDrag = null;
      persistActivePage({ thumbnail: true });
      renderPages(activeProjectMeta);
      renderLayers();
      updateSelectionUi();
      recordHistory('图层已调整');
    });
    canvas.on('object:added', renderLayers);
    canvas.on('object:removed', renderLayers);
    canvas.on('mouse:up', () => {
      activeMultiDrag = null;
      hideLayoutGuides();
    });
    return canvas;
  }

  function defaultProject(presetId = 'xhs_3_4', templateId = 'xhs_seed_cover') {
    const preset = getPreset(presetId);
    return {
      version: 3,
      presetId: preset.id,
      templateId,
      presetLabel: preset.name,
      width: preset.width,
      height: preset.height,
      background: '#ffffff',
      activePageId: 'page_1',
      pages: [{ id: 'page_1', name: '封面', canvasJson: null, thumbnailDataUrl: '' }],
      safeAreas: [],
      assist: { showSafeArea: true, snapEnabled: true },
      templateVariables: {},
      canvasJson: null
    };
  }

  function createProject(presetId, templateId) {
    return defaultProject(presetId, templateId);
  }

  function getProject(node) {
    return {
      ...defaultProject(node?.layoutPresetId || selectedPresetId, node?.layoutTemplateId || selectedTemplateId),
      ...(node?.layoutProject || {})
    };
  }

  function createPageId() {
    return `page_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
  }

  function createBlankCanvasJson(background = '#ffffff') {
    return {
      version: window.fabric?.version || '5.3.0',
      objects: [],
      background
    };
  }

  function clonePlain(value) {
    return value ? JSON.parse(JSON.stringify(value)) : value;
  }

  function stripProjectForHistory(project) {
    const snapshot = clonePlain(project);
    if (!snapshot) return null;
    snapshot.pages = (snapshot.pages || []).map(page => ({
      ...page,
      thumbnailDataUrl: ''
    }));
    return snapshot;
  }

  function createHistorySnapshot() {
    if (!activeProjectMeta || !canvas) return null;
    persistActivePage({ thumbnail: false });
    const project = normalizeProject(activeProjectMeta);
    activeProjectMeta = project;
    activePageId = project.activePageId;
    const activePage = getActivePage(project);
    const activeObject = canvas.getActiveObject();
    const canvasObjects = canvas.getObjects();
    const customSelection = selectedLayerIndices
      .map(index => Number(index))
      .filter(index => Number.isInteger(index) && index >= 0 && canvasObjects[index]?.visible !== false);
    const activeObjectIndices = customSelection.length > 1
      ? customSelection
      : (activeObject?.type === 'activeSelection' && typeof activeObject.getObjects === 'function'
        ? activeObject.getObjects().map(object => canvasObjects.indexOf(object)).filter(index => index >= 0)
        : []);
    const activeObjectIndex = activeObject && !activeObjectIndices.length ? canvasObjects.indexOf(activeObject) : -1;
    return stripProjectForHistory({
      ...project,
      version: 3,
      width: canvas.getWidth(),
      height: canvas.getHeight(),
      background: canvas.backgroundColor || '#ffffff',
      assist: { ...getAssistSettings() },
      templateVariables: collectTemplateVariables(),
      activePageId,
      pages: project.pages,
      canvasJson: activePage?.canvasJson || currentCanvasJson(),
      _activeObjectIndex: activeObjectIndex >= 0 ? activeObjectIndex : null,
      _activeObjectIndices: activeObjectIndices.length > 1 ? activeObjectIndices : null
    });
  }

  function historyKey(snapshot) {
    return snapshot ? JSON.stringify(snapshot) : '';
  }

  function updateHistoryButtons() {
    if (els.deskLayoutUndoBtn) {
      els.deskLayoutUndoBtn.disabled = undoStack.length <= 1;
      els.deskLayoutUndoBtn.setAttribute('aria-disabled', undoStack.length <= 1 ? 'true' : 'false');
    }
    if (els.deskLayoutRedoBtn) {
      els.deskLayoutRedoBtn.disabled = redoStack.length === 0;
      els.deskLayoutRedoBtn.setAttribute('aria-disabled', redoStack.length === 0 ? 'true' : 'false');
    }
  }

  function clearPendingHistory() {
    if (historyTimer) {
      clearTimeout(historyTimer);
      historyTimer = null;
    }
    pendingHistoryLabel = '';
  }

  function resetHistory(options = {}) {
    clearPendingHistory();
    undoStack = [];
    redoStack = [];
    if (options.empty) {
      historySnapshotKey = '';
      updateHistoryButtons();
      return;
    }
    const snapshot = createHistorySnapshot();
    historySnapshotKey = snapshot ? historyKey(snapshot) : '';
    if (snapshot) undoStack.push(snapshot);
    updateHistoryButtons();
  }

  function refreshCurrentHistorySnapshot() {
    if (isRestoringHistory || !undoStack.length) return;
    const snapshot = createHistorySnapshot();
    if (!snapshot) return;
    undoStack[undoStack.length - 1] = snapshot;
    historySnapshotKey = historyKey(snapshot);
    updateHistoryButtons();
  }

  function recordHistory(label = '') {
    if (isRestoringHistory) return;
    const snapshot = createHistorySnapshot();
    if (!snapshot) {
      updateHistoryButtons();
      return;
    }
    const nextKey = historyKey(snapshot);
    if (!nextKey || nextKey === historySnapshotKey) {
      updateHistoryButtons();
      return;
    }
    undoStack.push(snapshot);
    if (undoStack.length > historyLimit) undoStack.splice(0, undoStack.length - historyLimit);
    redoStack = [];
    historySnapshotKey = nextKey;
    updateHistoryButtons();
    if (label) setStatus(`${label}，记得保存`, '');
  }

  function scheduleHistoryRecord(label = '已修改', delay = 520) {
    if (isRestoringHistory) return;
    pendingHistoryLabel = label;
    if (historyTimer) clearTimeout(historyTimer);
    historyTimer = setTimeout(() => {
      historyTimer = null;
      const nextLabel = pendingHistoryLabel;
      pendingHistoryLabel = '';
      recordHistory(nextLabel);
    }, delay);
  }

  function flushPendingHistory() {
    if (!historyTimer) return;
    clearTimeout(historyTimer);
    historyTimer = null;
    const nextLabel = pendingHistoryLabel;
    pendingHistoryLabel = '';
    recordHistory(nextLabel);
  }

  function normalizeProject(project = {}) {
    const base = defaultProject(project.presetId || selectedPresetId, project.templateId || selectedTemplateId);
    const merged = {
      ...base,
      ...project
    };
    const sourcePages = Array.isArray(merged.pages) && merged.pages.length ? merged.pages : base.pages;
    merged.pages = sourcePages.map((page, index) => ({
      id: String(page?.id || `page_${index + 1}`),
      name: String(page?.name || (index === 0 ? '封面' : `第 ${index + 1} 页`)),
      canvasJson: page?.canvasJson || (index === 0 ? merged.canvasJson || null : null),
      thumbnailDataUrl: page?.thumbnailDataUrl || page?.thumbnail || ''
    }));
    merged.assist = {
      showSafeArea: true,
      snapEnabled: true,
      ...(merged.assist || {})
    };
    if (!merged.pages.length) {
      merged.pages = [{ id: 'page_1', name: '封面', canvasJson: merged.canvasJson || null, thumbnailDataUrl: '' }];
    }
    const desiredActiveId = merged.activePageId || activePageId || merged.pages[0].id;
    merged.activePageId = merged.pages.some(page => page.id === desiredActiveId) ? desiredActiveId : merged.pages[0].id;
    return merged;
  }

  function getActivePage(project = activeProjectMeta) {
    const pages = project?.pages || [];
    return pages.find(page => page.id === activePageId) || pages[0] || null;
  }

  function getActivePageIndex(project = activeProjectMeta) {
    const pages = project?.pages || [];
    const index = pages.findIndex(page => page.id === activePageId);
    return index >= 0 ? index : 0;
  }

  function canvasJsonProps() {
    return [
      'name',
      'layoutRole',
      'layoutVariable',
      'layoutSourceId',
      'layoutGroupId',
      'layoutGroupName',
      'sourceNodeId',
      'sourceImageUrl',
      'isTemplatePlaceholder',
      'objectFit',
      'layoutLocked',
      'layoutFrameLeft',
      'layoutFrameTop',
      'layoutFrameWidth',
      'layoutFrameHeight',
      'layoutFocalX',
      'layoutFocalY',
      'layoutCropZoom'
    ];
  }

  function currentCanvasJson() {
    return canvas ? withIsolationVisualsSuspended(() => canvas.toJSON(canvasJsonProps())) : null;
  }

  function currentCanvasThumbnail() {
    if (!canvas) return '';
    try {
      const longEdge = Math.max(canvas.getWidth(), canvas.getHeight(), 1);
      const multiplier = Math.min(0.14, Math.max(0.045, 180 / longEdge));
      return withIsolationVisualsSuspended(() => canvas.toDataURL({
        format: 'png',
        multiplier,
        enableRetinaScaling: false
      }));
    } catch (error) {
      return '';
    }
  }

  function persistActivePage(options = {}) {
    if (!activeProjectMeta || !canvas) return;
    const page = getActivePage(activeProjectMeta);
    if (!page) return;
    page.canvasJson = currentCanvasJson();
    if (options.thumbnail) {
      page.thumbnailDataUrl = currentCanvasThumbnail() || page.thumbnailDataUrl || '';
    }
    activeProjectMeta.activePageId = page.id;
    activeProjectMeta.canvasJson = page.canvasJson;
  }

  function getAssistSettings() {
    if (!activeProjectMeta) return { showSafeArea: true, snapEnabled: true };
    activeProjectMeta.assist = {
      showSafeArea: true,
      snapEnabled: true,
      ...(activeProjectMeta.assist || {})
    };
    return activeProjectMeta.assist;
  }

  function getSafeMargin() {
    const width = canvas?.getWidth?.() || activeProjectMeta?.width || 1080;
    const height = canvas?.getHeight?.() || activeProjectMeta?.height || 1440;
    return Math.round(Math.max(32, Math.min(width, height) * 0.075));
  }

  function updateAssistUi() {
    const settings = getAssistSettings();
    const margin = getSafeMargin();
    els.deskLayoutSafeAreaBtn?.classList.toggle('is-active', Boolean(settings.showSafeArea));
    els.deskLayoutSnapBtn?.classList.toggle('is-active', Boolean(settings.snapEnabled));
    els.deskLayoutSafeAreaBtn?.setAttribute('aria-pressed', settings.showSafeArea ? 'true' : 'false');
    els.deskLayoutSnapBtn?.setAttribute('aria-pressed', settings.snapEnabled ? 'true' : 'false');
    if (els.deskLayoutAssistOverlay && canvas) {
      els.deskLayoutAssistOverlay.style.width = `${canvas.getWidth()}px`;
      els.deskLayoutAssistOverlay.style.height = `${canvas.getHeight()}px`;
    }
    if (els.deskLayoutSafeAreaGuide) {
      els.deskLayoutSafeAreaGuide.hidden = !settings.showSafeArea;
      els.deskLayoutSafeAreaGuide.style.inset = `${margin}px`;
    }
  }

  function hideLayoutGuides() {
    if (els.deskLayoutGuideV) els.deskLayoutGuideV.hidden = true;
    if (els.deskLayoutGuideH) els.deskLayoutGuideH.hidden = true;
  }

  function showLayoutGuides(guides = {}) {
    if (els.deskLayoutGuideV) {
      if (Number.isFinite(guides.x)) {
        els.deskLayoutGuideV.hidden = false;
        els.deskLayoutGuideV.style.left = `${guides.x}px`;
      } else {
        els.deskLayoutGuideV.hidden = true;
      }
    }
    if (els.deskLayoutGuideH) {
      if (Number.isFinite(guides.y)) {
        els.deskLayoutGuideH.hidden = false;
        els.deskLayoutGuideH.style.top = `${guides.y}px`;
      } else {
        els.deskLayoutGuideH.hidden = true;
      }
    }
  }

  function updateGroupSelectionBox(objects = getCustomSelectedLayerObjects()) {
    const box = els.deskLayoutGroupSelectionBox;
    if (!box || !canvas) return;
    const groupId = getSelectedGroupId(objects);
    const group = groupId ? getGroupById(groupId) : null;
    const visibleObjects = group?.objects?.filter(object => object && object.visible !== false) || [];
    const bounds = visibleObjects.length ? combinedObjectBounds(visibleObjects) : null;
    if (!group || !bounds) {
      box.hidden = true;
      box.removeAttribute('data-name');
      box.removeAttribute('data-locked');
      return;
    }
    const padding = Math.max(3, Math.round(4 / Math.max(stageZoom, 0.2)));
    box.hidden = false;
    box.dataset.name = group.locked ? `${group.name || '组合图层'} · 已锁定` : (group.name || '组合图层');
    box.dataset.locked = group.locked ? 'true' : 'false';
    box.style.left = `${Math.round(bounds.left - padding)}px`;
    box.style.top = `${Math.round(bounds.top - padding)}px`;
    box.style.width = `${Math.round(bounds.width + padding * 2)}px`;
    box.style.height = `${Math.round(bounds.height + padding * 2)}px`;
  }

  function objectBounds(object) {
    if (!object) return null;
    object.setCoords?.();
    const rect = object.getBoundingRect(true, true);
    return {
      left: rect.left,
      top: rect.top,
      right: rect.left + rect.width,
      bottom: rect.top + rect.height,
      centerX: rect.left + rect.width / 2,
      centerY: rect.top + rect.height / 2,
      width: rect.width,
      height: rect.height
    };
  }

  function getSnapTargets(excludedObjects = []) {
    if (!canvas) return { vertical: [], horizontal: [] };
    const excluded = new Set(Array.isArray(excludedObjects) ? excludedObjects : [excludedObjects]);
    const width = canvas.getWidth();
    const height = canvas.getHeight();
    const margin = getSafeMargin();
    const vertical = [0, margin, width / 2, width - margin, width].map(value => ({ value }));
    const horizontal = [0, margin, height / 2, height - margin, height].map(value => ({ value }));
    canvas.getObjects().forEach(item => {
      if (!item || excluded.has(item) || item.visible === false) return;
      const bounds = objectBounds(item);
      if (!bounds) return;
      vertical.push({ value: bounds.left }, { value: bounds.centerX }, { value: bounds.right });
      horizontal.push({ value: bounds.top }, { value: bounds.centerY }, { value: bounds.bottom });
    });
    return { vertical, horizontal };
  }

  function nearestSnap(points, targets) {
    const threshold = Math.max(4, 8 / Math.max(stageZoom, 0.1));
    let best = null;
    points.forEach(point => {
      targets.forEach(target => {
        const diff = target.value - point.value;
        if (Math.abs(diff) <= threshold && (!best || Math.abs(diff) < Math.abs(best.diff))) {
          best = { diff, target: target.value };
        }
      });
    });
    return best;
  }

  function resolveBoundsGuides(bounds, excludedObjects = [], shouldSnap = false, applySnap = null) {
    if (!canvas || !bounds) return {};
    const settings = getAssistSettings();
    if (!settings.snapEnabled) {
      hideLayoutGuides();
      return {};
    }
    const targets = getSnapTargets(excludedObjects);
    const xSnap = nearestSnap([
      { value: bounds.left },
      { value: bounds.centerX },
      { value: bounds.right }
    ], targets.vertical);
    const ySnap = nearestSnap([
      { value: bounds.top },
      { value: bounds.centerY },
      { value: bounds.bottom }
    ], targets.horizontal);
    if (shouldSnap) {
      const dx = xSnap?.diff || 0;
      const dy = ySnap?.diff || 0;
      if ((dx || dy) && typeof applySnap === 'function') applySnap(dx, dy);
    }
    const guides = {
      x: xSnap?.target,
      y: ySnap?.target
    };
    showLayoutGuides(guides);
    return guides;
  }

  function resolveObjectGuides(object, shouldSnap = false) {
    if (!canvas || !object || isLayerLocked(object)) return {};
    const bounds = objectBounds(object);
    return resolveBoundsGuides(bounds, [object], shouldSnap, (dx, dy) => {
      moveArrangedObject(object, dx, dy);
      object.setCoords?.();
    });
  }

  function resolveSelectionGuides(objects = [], shouldSnap = false) {
    const selectedObjects = objects.filter(object => object && object.visible !== false && !isLayerLocked(object));
    if (!selectedObjects.length) return {};
    const bounds = combinedObjectBounds(selectedObjects);
    return resolveBoundsGuides(bounds, selectedObjects, shouldSnap, (dx, dy) => {
      selectedObjects.forEach(object => {
        moveArrangedObject(object, dx, dy);
        object.setCoords?.();
      });
    });
  }

  function isGroupImageEditObject(object, selectedObjects = getCustomSelectedLayerObjects()) {
    if (!object || getGroupImageEditTarget() !== object || !isImageObject(object)) return false;
    if (!selectedObjects.includes(object)) return false;
    const groupId = selectedObjects.length > 1 ? getSelectedGroupId(selectedObjects) : '';
    const group = groupId ? getGroupById(groupId) : null;
    return Boolean(group && !group.locked && !isLayerLocked(object));
  }

  function beginMultiDrag(target) {
    const selectedObjects = getCustomSelectedLayerObjects();
    if (isGroupImageEditObject(target, selectedObjects)) {
      activeMultiDrag = null;
      return;
    }
    if (
      !target ||
      selectedObjects.length <= 1 ||
      !selectedObjects.includes(target) ||
      selectedObjects.some(object => isLayerLocked(object))
    ) {
      activeMultiDrag = null;
      return;
    }
    activeMultiDrag = {
      target,
      objects: selectedObjects,
      lastLeft: Number(target.left || 0),
      lastTop: Number(target.top || 0)
    };
    refreshCurrentHistorySnapshot();
  }

  function handleObjectMoving(event) {
    const target = event?.target;
    const selectedObjects = getCustomSelectedLayerObjects();
    if (target && isGroupImageEditObject(target, selectedObjects)) {
      resolveObjectGuides(target, true);
      updateObjectMetricInputs(target, { forceSingle: true });
      updateGroupSelectionBox(selectedObjects);
      canvas?.requestRenderAll();
      return;
    }
    if (target && selectedObjects.length > 1 && selectedObjects.includes(target)) {
      if (selectedObjects.some(object => isLayerLocked(object))) {
        activeMultiDrag = null;
        selectedObjects.forEach(object => object.setCoords?.());
        updateObjectMetricInputs(null);
        updateGroupSelectionBox(selectedObjects);
        canvas?.requestRenderAll();
        return;
      }
      if (!activeMultiDrag || activeMultiDrag.target !== target) beginMultiDrag(target);
      const dx = Number(target.left || 0) - Number(activeMultiDrag?.lastLeft || 0);
      const dy = Number(target.top || 0) - Number(activeMultiDrag?.lastTop || 0);
      selectedObjects.forEach(object => {
        if (object !== target) moveArrangedObject(object, dx, dy);
        object.setCoords?.();
      });
      resolveSelectionGuides(selectedObjects, true);
      if (activeMultiDrag) {
        activeMultiDrag.lastLeft = Number(target.left || 0);
        activeMultiDrag.lastTop = Number(target.top || 0);
      }
      updateObjectMetricInputs(null);
      updateGroupSelectionBox(selectedObjects);
      canvas?.requestRenderAll();
      return;
    }
    resolveObjectGuides(target, true);
    updateObjectMetricInputs(target || canvas?.getActiveObject());
    updateGroupSelectionBox();
  }

  function handleObjectTransforming(event) {
    const target = event?.target;
    if (target && isGroupImageEditObject(target)) {
      resolveObjectGuides(target, false);
      updateObjectMetricInputs(target, { forceSingle: true });
      updateGroupSelectionBox();
      return;
    }
    resolveObjectGuides(event?.target, false);
    updateObjectMetricInputs(event?.target || canvas?.getActiveObject());
    updateGroupSelectionBox();
  }

  function setStatus(message, tone = '') {
    if (!els.deskLayoutStatus) return;
    els.deskLayoutStatus.textContent = message || '';
    els.deskLayoutStatus.classList.toggle('is-saving', tone === 'saving');
    els.deskLayoutStatus.classList.toggle('is-error', tone === 'error');
    els.deskLayoutStatus.classList.toggle('is-saved', tone === 'saved');
  }

  function formatDraftOption(draft) {
    const title = draft?.title || '排版工作区';
    const date = draft?.updated_at
      ? new Date(draft.updated_at * 1000).toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
      })
      : '';
    return date ? `${title} · ${date}` : title;
  }

  async function refreshDraftList(selectedId = '') {
    if (!els.deskLayoutDraftSelect) return;
    try {
      const data = await DesktopApi.listLayoutDrafts(50, 0);
      const drafts = Array.isArray(data.drafts) ? data.drafts : [];
      els.deskLayoutDraftSelect.innerHTML = [
        '<option value="">最近草稿</option>',
        ...drafts.map(draft => {
          const value = String(draft.draft_id || '');
          const selected = value && value === selectedId ? ' selected' : '';
          return `<option value="${value}"${selected}>${formatDraftOption(draft)}</option>`;
        })
      ].join('');
    } catch (error) {
      setStatus(`草稿列表失败：${error.message}`, 'error');
    }
  }

  function addTemplateText(text, options = {}) {
    const object = new fabric.Textbox(text, {
      fontFamily: getDefaultTextFont(),
      fontSize: 42,
      fontWeight: 700,
      fill: '#111827',
      splitByGrapheme: true,
      layoutRole: options.layoutRole || '',
      layoutVariable: options.layoutVariable || '',
      ...options
    });
    canvas.add(object);
    return object;
  }

  function addTemplateShape(options = {}) {
    const object = new fabric.Rect({
      fill: '#eef5f9',
      rx: 24,
      ry: 24,
      layoutRole: options.layoutRole || '',
      layoutVariable: options.layoutVariable || '',
      isTemplatePlaceholder: options.isTemplatePlaceholder === true,
      objectFit: options.objectFit || '',
      ...options
    });
    canvas.add(object);
    return object;
  }

  function seedCanvas(project) {
    const width = canvas.getWidth();
    const height = canvas.getHeight();
    const templateId = project.templateId || 'xhs_seed_cover';
    const accent = getTemplate(templateId).accent || '#084fbd';

    if (templateId === 'blank') {
      canvas.discardActiveObject();
      return;
    }

    if (templateId === 'wechat_headline' || templateId === 'wechat_digest' || project.presetId?.startsWith('wechat')) {
      const pad = Math.round(width * 0.075);
      addTemplateShape({
        left: Math.round(width * 0.63),
        top: Math.round(height * 0.16),
        width: Math.round(width * 0.26),
        height: Math.round(height * 0.58),
        fill: 'rgba(8, 79, 189, 0.1)',
        stroke: 'rgba(8, 79, 189, 0.22)',
        strokeWidth: 2,
        name: '封面主图占位',
        layoutRole: 'heroImage',
        isTemplatePlaceholder: true,
        objectFit: 'cover'
      });
      const title = addTemplateText('这是一篇值得打开的文章', {
        left: pad,
        top: Math.round(height * 0.2),
        width: Math.round(width * 0.52),
        fontSize: Math.max(38, Math.round(height * 0.14)),
        fontWeight: 800,
        lineHeight: 0.95,
        name: '标题',
        layoutRole: 'title',
        layoutVariable: 'title'
      });
      addTemplateText('副标题 / 摘要一句话说清价值', {
        left: pad,
        top: Math.round(height * 0.58),
        width: Math.round(width * 0.48),
        fontSize: Math.max(18, Math.round(height * 0.06)),
        fontWeight: 500,
        fill: '#637182',
        name: '摘要',
        layoutRole: 'subtitle',
        layoutVariable: 'subtitle'
      });
      addTemplateText('公众号 · 今日更新', {
        left: pad,
        top: Math.round(height * 0.78),
        width: Math.round(width * 0.36),
        fontSize: Math.max(14, Math.round(height * 0.042)),
        fontWeight: 700,
        fill: accent,
        name: '署名',
        layoutRole: 'byline',
        layoutVariable: 'byline'
      });
      canvas.setActiveObject(title);
      return;
    }

    if (templateId === 'xhs_checklist') {
      const title = addTemplateText('3 个方法\n让图片更高级', {
        left: 72,
        top: 82,
        width: width - 144,
        fontSize: Math.round(width * 0.085),
        fontWeight: 800,
        lineHeight: 0.96,
        name: '标题',
        layoutRole: 'title',
        layoutVariable: 'title'
      });
      [0, 1, 2].forEach(index => {
        const top = 330 + index * 250;
        addTemplateShape({ left: 72, top, width: width - 144, height: 184, fill: '#f8fafc', stroke: 'rgba(67, 86, 106, 0.1)', strokeWidth: 2, name: `步骤 ${index + 1} 卡片` });
        addTemplateText(`0${index + 1}`, { left: 112, top: top + 38, width: 120, fontSize: 54, fontWeight: 800, fill: accent, name: `步骤 ${index + 1}`, layoutRole: 'stepNumber', layoutVariable: `step${index + 1}Number` });
        addTemplateText(['先确定主体', '再压住留白', '最后统一色彩'][index], { left: 245, top: top + 45, width: width - 360, fontSize: 42, fontWeight: 750, name: `步骤 ${index + 1} 标题`, layoutRole: 'stepTitle', layoutVariable: `step${index + 1}Title` });
        addTemplateText('一句话说明这个步骤怎么做。', { left: 245, top: top + 106, width: width - 360, fontSize: 26, fontWeight: 500, fill: '#637182', name: `步骤 ${index + 1} 说明`, layoutRole: 'stepDescription', layoutVariable: `step${index + 1}Description` });
      });
      canvas.setActiveObject(title);
      return;
    }

    if (templateId === 'xhs_compare') {
      const title = addTemplateText('前后对比\n一眼看懂差别', {
        left: 72,
        top: 72,
        width: width - 144,
        fontSize: Math.round(width * 0.078),
        fontWeight: 850,
        lineHeight: 0.98,
        name: '标题',
        layoutRole: 'title',
        layoutVariable: 'title'
      });
      const cardWidth = Math.round((width - 180) / 2);
      ['Before', 'After'].forEach((label, index) => {
        const left = 72 + index * (cardWidth + 36);
        addTemplateShape({ left, top: 340, width: cardWidth, height: Math.round(height * 0.48), fill: index ? 'rgba(8,79,189,0.08)' : '#f8fafc', stroke: 'rgba(67,86,106,0.12)', strokeWidth: 2, name: `${label} 图片占位`, layoutRole: index ? 'heroImageAfter' : 'heroImageBefore', isTemplatePlaceholder: true, objectFit: 'cover' });
        addTemplateText(label, { left: left + 32, top: 380, width: cardWidth - 64, fontSize: 44, fontWeight: 850, fill: index ? accent : '#637182', name: `${label} 标记`, layoutRole: 'label', layoutVariable: index ? 'afterLabel' : 'beforeLabel' });
      });
      addTemplateText('把关键变化写在这里，适合产品、设计、修图、教程类内容。', { left: 72, top: height - 210, width: width - 144, fontSize: 34, fontWeight: 600, fill: '#374151', name: '结论说明', layoutRole: 'caption', layoutVariable: 'caption' });
      canvas.setActiveObject(title);
      return;
    }

    if (templateId === 'general_poster' || project.presetId === 'wide_16_9') {
      addTemplateShape({ left: Math.round(width * 0.53), top: Math.round(height * 0.1), width: Math.round(width * 0.38), height: Math.round(height * 0.78), fill: 'rgba(8,79,189,0.08)', stroke: 'rgba(8,79,189,0.18)', strokeWidth: 2, name: '主视觉占位', layoutRole: 'heroImage', isTemplatePlaceholder: true, objectFit: 'cover' });
      const title = addTemplateText('视觉标题\n放在这里', { left: Math.round(width * 0.08), top: Math.round(height * 0.18), width: Math.round(width * 0.42), fontSize: Math.round(height * 0.1), fontWeight: 850, lineHeight: 0.96, name: '标题', layoutRole: 'title', layoutVariable: 'title' });
      addTemplateText('一句话说明这张图的用途和价值。', { left: Math.round(width * 0.08), top: Math.round(height * 0.54), width: Math.round(width * 0.38), fontSize: Math.round(height * 0.04), fill: '#637182', name: '说明', layoutRole: 'subtitle', layoutVariable: 'subtitle' });
      canvas.setActiveObject(title);
      return;
    }

    const title = addTemplateText('夏日凉爽\n一级标题', {
      left: 72,
      top: 82,
      width: width - 144,
      fontSize: Math.round(width * 0.082),
      fontWeight: 850,
      lineHeight: 0.95,
      name: '标题',
      layoutRole: 'title',
      layoutVariable: 'title'
    });
    addTemplateShape({
      left: 96,
      top: 300,
      width: width - 192,
      height: Math.round(height * 0.46),
      fill: 'rgba(8, 79, 189, 0.07)',
      stroke: 'rgba(8, 79, 189, 0.18)',
      strokeWidth: 2,
      name: '主图占位',
      layoutRole: 'heroImage',
      isTemplatePlaceholder: true,
      objectFit: 'cover'
    });
    addTemplateText('主图区域', {
      left: 130,
      top: Math.round(height * 0.46),
      width: width - 260,
      fontSize: 34,
      fontWeight: 700,
      fill: '#637182',
      textAlign: 'center',
      name: '占位说明',
      layoutRole: 'placeholderLabel'
    });
    ['轻盈', '清爽', '高级感'].forEach((label, index) => {
      const left = 96 + index * Math.round((width - 192) / 3);
      addTemplateShape({ left, top: height - 230, width: Math.round((width - 240) / 3), height: 86, fill: '#f8fafc', stroke: 'rgba(67,86,106,0.1)', strokeWidth: 2, name: `${label} 标签底` });
      addTemplateText(label, { left: left + 24, top: height - 208, width: Math.round((width - 300) / 3), fontSize: 30, fontWeight: 750, fill: accent, textAlign: 'center', name: `${label} 标签`, layoutRole: 'tag', layoutVariable: `tag${index + 1}` });
    });
    addTemplateText('小红书图文模板 · 可替换为真实卖点', {
      left: 72,
      top: height - 100,
      width: width - 144,
      fontSize: 24,
      fontWeight: 600,
      fill: '#637182',
      textAlign: 'center',
      name: '脚注',
      layoutRole: 'caption',
      layoutVariable: 'caption'
    });
    canvas.setActiveObject(title);
  }

  function applyDraftMeta(node, draft) {
    if (!node || !draft) return;
    node.layoutDraftId = draft.draft_id || node.layoutDraftId || '';
    node.layoutTitle = draft.title || node.layoutTitle || '排版工作区';
    node.layoutPreview = draft.preview_url ? DesktopApi.addCacheBuster(draft.preview_url, Date.now()) : (node.layoutPreview || '');
    node.layoutExport = draft.export_url ? DesktopApi.addCacheBuster(draft.export_url, Date.now()) : (node.layoutExport || node.layoutPreview || '');
    if (draft.draft_id) {
      delete node.layoutProject;
    }
  }

  function loadCanvasJson(nextCanvas, project, options = {}) {
    const seedIfEmpty = options.seedIfEmpty !== false;
    return new Promise(resolve => {
      if (!project.canvasJson) {
        if (seedIfEmpty) seedCanvas(project);
        nextCanvas.renderAll();
        renderLayers();
        updateSelectionUi();
        resolve();
        return;
      }
      nextCanvas.loadFromJSON(project.canvasJson, () => {
        nextCanvas.renderAll();
        renderLayers();
        updateSelectionUi();
        resolve();
      });
    });
  }

  async function loadProject(node) {
    let project = getProject(node);
    if (node?.layoutDraftId) {
      try {
        const draft = await DesktopApi.loadLayoutDraft(node.layoutDraftId);
        applyDraftMeta(node, draft);
        project = {
          ...defaultProject(draft.project?.presetId, draft.project?.templateId),
          ...(draft.project || {})
        };
        node.layoutPresetId = project.presetId || node.layoutPresetId;
        node.layoutTemplateId = project.templateId || node.layoutTemplateId;
        node.layoutPresetLabel = getPreset(project.presetId).name;
        DesktopState.saveSettings();
        DesktopCanvas.refreshLayoutNode?.(node.id);
      } catch (error) {
        DesktopResults.showError(error);
      }
    }
    activeProjectMeta = normalizeProject(project);
    activePageId = activeProjectMeta.activePageId;
    const activePage = getActivePage(activeProjectMeta);
    const nextCanvas = ensureFabricCanvas();
    exitGroupIsolation({ silent: true, skipUi: true, keepSelection: true });
    nextCanvas.setWidth(activeProjectMeta.width);
    nextCanvas.setHeight(activeProjectMeta.height);
    nextCanvas.clear();
    nextCanvas.backgroundColor = activeProjectMeta.background || '#ffffff';
    await loadCanvasJson(nextCanvas, {
      ...activeProjectMeta,
      canvasJson: activePage?.canvasJson || null
    }, { seedIfEmpty: true });
    migrateTemplateObjects();
    normalizeLayerObjects();
    await ensureCanvasFontsLoaded(nextCanvas);
    persistActivePage({ thumbnail: true });
    nextCanvas.requestRenderAll();
    if (els.deskLayoutMeta) {
      const preset = getPreset(activeProjectMeta.presetId);
      els.deskLayoutMeta.textContent = `${activeProjectMeta.width} x ${activeProjectMeta.height} · ${preset.ratio || ''}`;
    }
    if (els.deskLayoutPage) {
      els.deskLayoutPage.dataset.size = `${activeProjectMeta.width} x ${activeProjectMeta.height}`;
    }
    updateAssistUi();
    renderPages(activeProjectMeta);
    requestAnimationFrame(() => {
      if (stageZoomMode === 'fit') fitStageToView();
      else applyStageZoom(stageZoom, stageZoomMode);
    });
  }

  function serializeProject() {
    persistActivePage({ thumbnail: true });
    const project = normalizeProject(activeProjectMeta || defaultProject());
    activeProjectMeta = project;
    activePageId = project.activePageId;
    const activePage = getActivePage(project);
    return {
      ...project,
      version: 3,
      width: canvas.getWidth(),
      height: canvas.getHeight(),
      background: canvas.backgroundColor || '#ffffff',
      assist: { ...getAssistSettings() },
      templateVariables: collectTemplateVariables(),
      activePageId,
      pages: project.pages,
      canvasJson: activePage?.canvasJson || currentCanvasJson()
    };
  }

  function collectTemplateVariables() {
    if (!canvas) return {};
    return canvas.getObjects().reduce((variables, object) => {
      const key = String(object.layoutVariable || '').trim();
      if (!key || typeof object.text !== 'string') return variables;
      variables[key] = object.text;
      return variables;
    }, {});
  }

  async function ensureDraftForActiveNode() {
    const node = getActiveNode();
    if (!node) throw new Error('排版节点不存在');
    if (node.layoutDraftId) return node.layoutDraftId;
    const draft = await DesktopApi.saveLayoutDraft({
      title: node.layoutTitle || '排版工作区',
      nodeId: node.id,
      project: canvas ? serializeProject() : getProject(node)
    });
    applyDraftMeta(node, draft);
    DesktopState.saveSettings();
    DesktopCanvas.refreshLayoutNode?.(node.id);
    return node.layoutDraftId;
  }

  async function saveToNode() {
    const node = getActiveNode();
    if (!node || !canvas) return '';
    flushPendingHistory();
    setStatus('保存中...', 'saving');
    if (els.deskLayoutSaveBtn) {
      els.deskLayoutSaveBtn.disabled = true;
      els.deskLayoutSaveBtn.textContent = '保存中';
    }
    await ensureCanvasFontsLoaded(canvas);
    const project = serializeProject();
    const dataUrl = withIsolationVisualsSuspended(() => canvas.toDataURL({
      format: 'png',
      multiplier: 1,
      enableRetinaScaling: true
    }));
    try {
      const draft = await DesktopApi.saveLayoutDraft({
        draftId: node.layoutDraftId || '',
        title: node.layoutTitle || '排版工作区',
        nodeId: node.id,
        project,
        previewDataUrl: dataUrl,
        exportDataUrl: dataUrl
      });
      applyDraftMeta(node, draft);
      DesktopState.saveSettings();
      DesktopCanvas.refreshLayoutNode?.(node.id);
      await refreshDraftList(node.layoutDraftId || '');
      setStatus('已保存到后端草稿', 'saved');
      return node.layoutExport || node.layoutPreview || dataUrl;
    } catch (error) {
      setStatus(`保存失败：${error.message}`, 'error');
      throw error;
    } finally {
      if (els.deskLayoutSaveBtn) {
        els.deskLayoutSaveBtn.disabled = false;
        els.deskLayoutSaveBtn.textContent = '保存';
      }
    }
  }

  function objectLabel(object, index) {
    if (!object) return `图层 ${index + 1}`;
    if (object.type === 'activeSelection') return `已选 ${object.getObjects?.().length || 0} 个图层`;
    if (object.name) return object.name;
    if (object.type === 'image') return `图片 ${index + 1}`;
    if (object.text) return object.text.slice(0, 18) || `文字 ${index + 1}`;
    return `图层 ${index + 1}`;
  }

  function objectKindLabel(object) {
    if (!object) return '';
    if (object.type === 'activeSelection') return '多选图层';
    if (object.type === 'image') return '图片图层';
    if (['i-text', 'text', 'textbox'].includes(object.type)) return '文字图层';
    if (object.type === 'rect') return '形状图层';
    return '图层';
  }

  function isTextObject(object) {
    return Boolean(object && ['i-text', 'text', 'textbox'].includes(object.type));
  }

  function isTemplateTextObject(object) {
    return isTextObject(object) && Boolean(String(object.layoutVariable || '').trim());
  }

  function isTemplateImageObject(object) {
    return Boolean(object && String(object.layoutRole || '').startsWith('heroImage'));
  }

  function templateFieldLabel(key, role = '') {
    const labels = {
      title: '标题',
      subtitle: '摘要',
      byline: '署名',
      caption: '说明',
      heroImage: '主图',
      heroImageBefore: 'Before 图片',
      heroImageAfter: 'After 图片',
      beforeLabel: 'Before 标记',
      afterLabel: 'After 标记'
    };
    if (labels[key]) return labels[key];
    if (/^tag\d+$/i.test(key)) return `标签 ${key.replace(/\D/g, '')}`;
    if (/^step\d+Number$/i.test(key)) return `步骤 ${key.match(/\d+/)?.[0] || ''} 编号`;
    if (/^step\d+Title$/i.test(key)) return `步骤 ${key.match(/\d+/)?.[0] || ''} 标题`;
    if (/^step\d+Description$/i.test(key)) return `步骤 ${key.match(/\d+/)?.[0] || ''} 说明`;
    if (role === 'tag') return '标签';
    if (role === 'caption') return '说明';
    return key;
  }

  function templateFieldOrder(key) {
    const order = ['title', 'subtitle', 'byline', 'caption', 'heroImage', 'heroImageBefore', 'heroImageAfter'];
    const found = order.indexOf(key);
    if (found >= 0) return found;
    if (/^tag\d+$/i.test(key)) return 20 + Number(key.replace(/\D/g, ''));
    if (/^step\d+/i.test(key)) return 40 + Number(key.match(/\d+/)?.[0] || 0);
    return 100;
  }

  function collectTemplateFields() {
    if (!canvas) return { texts: [], images: [] };
    const textMap = new Map();
    const imageMap = new Map();
    canvas.getObjects().forEach(object => {
      if (isTemplateTextObject(object)) {
        const key = String(object.layoutVariable || '').trim();
        if (!textMap.has(key)) {
          textMap.set(key, {
            key,
            role: object.layoutRole || '',
            label: templateFieldLabel(key, object.layoutRole),
            value: object.text || '',
            objects: []
          });
        }
        textMap.get(key).objects.push(object);
      }
      if (isTemplateImageObject(object)) {
        const key = String(object.layoutVariable || object.layoutRole || '').trim();
        if (!key) return;
        if (!imageMap.has(key)) {
          imageMap.set(key, {
            key,
            role: object.layoutRole || '',
            label: templateFieldLabel(key, object.layoutRole),
            objects: [],
            hasImage: false,
            hasPlaceholder: false
          });
        }
        const field = imageMap.get(key);
        field.objects.push(object);
        field.hasImage = field.hasImage || object.type === 'image';
        field.hasPlaceholder = field.hasPlaceholder || object.isTemplatePlaceholder === true;
      }
    });
    return {
      texts: Array.from(textMap.values()).sort((a, b) => templateFieldOrder(a.key) - templateFieldOrder(b.key)),
      images: Array.from(imageMap.values()).sort((a, b) => templateFieldOrder(a.key) - templateFieldOrder(b.key))
    };
  }

  function layerActionIcon(name) {
    const icons = {
      drag: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3h.01M10 3h.01M6 8h.01M10 8h.01M6 13h.01M10 13h.01"></path></svg>',
      visible: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 8s2.2-4 6-4 6 4 6 4-2.2 4-6 4-6-4-6-4z"></path><circle cx="8" cy="8" r="1.8"></circle></svg>',
      hidden: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 8s2.2-4 6-4c1.1 0 2 .3 2.8.8M13.2 6.5c.6.7.8 1.5.8 1.5s-2.2 4-6 4c-1 0-1.9-.3-2.7-.7M2.5 2.5l11 11"></path></svg>',
      unlocked: '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3.5" y="7" width="9" height="6" rx="1.4"></rect><path d="M5.5 7V5.3A2.5 2.5 0 0 1 10 3.8"></path></svg>',
      locked: '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3.5" y="7" width="9" height="6" rx="1.4"></rect><path d="M5.5 7V5.5a2.5 2.5 0 0 1 5 0V7"></path></svg>',
      rename: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 11.5V13h1.5L12 5.5 10.5 4 3 11.5z"></path><path d="M9.8 4.7l1.5 1.5"></path></svg>'
    };
    return icons[name] || '';
  }

  function isLayerLocked(object) {
    return Boolean(object?.layoutLocked);
  }

  function applyLayerLock(object, locked) {
    if (!object) return;
    object.set({
      layoutLocked: Boolean(locked),
      lockMovementX: Boolean(locked),
      lockMovementY: Boolean(locked),
      lockScalingX: Boolean(locked),
      lockScalingY: Boolean(locked),
      lockRotation: Boolean(locked),
      hasControls: !locked,
      borderColor: locked ? '#94a3b8' : '#084fbd',
      cornerColor: locked ? '#94a3b8' : '#084fbd',
      hoverCursor: locked ? 'not-allowed' : 'move',
      moveCursor: locked ? 'not-allowed' : 'move'
    });
    if ('editable' in object) object.set('editable', !locked);
    if (locked && object.isEditing && typeof object.exitEditing === 'function') {
      object.exitEditing();
    }
  }

  function normalizeLayerObjects() {
    if (!canvas) return;
    canvas.getObjects().forEach(object => {
      if (typeof object.visible !== 'boolean') object.visible = true;
      applyLayerLock(object, Boolean(object.layoutLocked));
    });
  }

  function inferTemplateRole(object) {
    const name = String(object?.name || object?.text || '').trim();
    if (!name) return;
    if (object.type === 'rect' && name.includes('主图') && name.includes('占位')) {
      object.set({
        layoutRole: 'heroImage',
        isTemplatePlaceholder: true,
        objectFit: 'cover'
      });
      return;
    }
    if (object.type === 'rect' && name.includes('Before') && name.includes('图片')) {
      object.set({
        layoutRole: 'heroImageBefore',
        isTemplatePlaceholder: true,
        objectFit: 'cover'
      });
      return;
    }
    if (object.type === 'rect' && name.includes('After') && name.includes('图片')) {
      object.set({
        layoutRole: 'heroImageAfter',
        isTemplatePlaceholder: true,
        objectFit: 'cover'
      });
      return;
    }
    if (object.type === 'rect' && name.includes('图片') && name.includes('占位')) {
      object.set({
        layoutRole: 'heroImage',
        isTemplatePlaceholder: true,
        objectFit: 'cover'
      });
      return;
    }
    if (['i-text', 'text', 'textbox'].includes(object.type)) {
      if (name === '标题') object.set({ layoutRole: 'title', layoutVariable: 'title' });
      if (name === '摘要') object.set({ layoutRole: 'subtitle', layoutVariable: 'subtitle' });
      if (name === '署名') object.set({ layoutRole: 'byline', layoutVariable: 'byline' });
      if (name.includes('标签')) object.set({ layoutRole: 'tag', layoutVariable: object.layoutVariable || 'tag' });
      if (name.includes('脚注') || name.includes('说明')) object.set({ layoutRole: 'caption', layoutVariable: object.layoutVariable || 'caption' });
      if (name.includes('占位说明') || String(object.text || '').includes('主图区域')) object.set({ layoutRole: 'placeholderLabel' });
    }
  }

  function migrateTemplateObjects() {
    if (!canvas) return;
    canvas.getObjects().forEach(inferTemplateRole);
  }

  function pageActionIcon(name) {
    const icons = {
      add: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M3 8h10"></path></svg>',
      duplicate: '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="5" y="3" width="8" height="8" rx="1.4"></rect><path d="M3 5v8h8"></path></svg>',
      rename: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 11.5V13h1.5L12 5.5 10.5 4 3 11.5z"></path><path d="M9.8 4.7l1.5 1.5"></path></svg>',
      delete: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4h10M6 4V2.8h4V4M5 6v7M8 6v7M11 6v7"></path></svg>'
    };
    return icons[name] || '';
  }

  function renderPages(project = activeProjectMeta) {
    if (!els.deskLayoutPageList) return;
    const layerList = els.deskLayoutLayerList;
    if (layerList?.parentElement === els.deskLayoutPageList) {
      layerList.remove();
    }
    const normalized = normalizeProject(project || defaultProject());
    const preset = getPreset(normalized.presetId);
    const desiredActiveId = activePageId || normalized.activePageId;
    const activeId = normalized.pages.some(page => page.id === desiredActiveId) ? desiredActiveId : normalized.activePageId;
    const pageRows = normalized.pages.map((page, index) => {
      const isActive = page.id === activeId;
      const expanded = isActive && !pageTreeCollapsed;
      const thumb = page.thumbnailDataUrl || '';
      const thumbStyle = thumb ? ` style="background-image:url('${escapeHtml(thumb)}')"` : '';
      const title = escapeHtml(page.name || `第 ${index + 1} 页`);
      const meta = `${index + 1} / ${normalized.pages.length} · ${preset.name}`;
      return `
        <div class="desk-layout-page-node${isActive ? ' is-active' : ''}" data-page-node="${escapeHtml(page.id)}">
          <button type="button" class="desk-layout-page-item${isActive ? ' is-active' : ''}" data-page-id="${escapeHtml(page.id)}" aria-expanded="${expanded ? 'true' : 'false'}">
            <i>${isActive ? (expanded ? '▾' : '▸') : ''}</i>
            <b class="desk-layout-page-thumb${thumb ? ' has-thumb' : ''}"${thumbStyle}><em>${index + 1}</em></b>
            <span>
              ${renamingPageId === page.id
                ? `<input class="desk-layout-page-name-input" data-page-name-input data-page-id="${escapeHtml(page.id)}" value="${title}" aria-label="页面名称">`
                : `<strong>${title}</strong>`}
              <em>${escapeHtml(meta)}</em>
            </span>
          </button>
        </div>
      `;
    }).join('');
    els.deskLayoutPageList.innerHTML = `
      <div class="desk-layout-page-actions" aria-label="页面操作">
        <button type="button" data-page-action="add" title="新增页面" aria-label="新增页面">${pageActionIcon('add')}</button>
        <button type="button" data-page-action="duplicate" title="复制当前页" aria-label="复制当前页">${pageActionIcon('duplicate')}</button>
        <button type="button" data-page-action="rename" title="重命名当前页" aria-label="重命名当前页">${pageActionIcon('rename')}</button>
        <button type="button" data-page-action="delete" title="删除当前页" aria-label="删除当前页"${normalized.pages.length <= 1 ? ' disabled' : ''}>${pageActionIcon('delete')}</button>
      </div>
      ${pageRows}
    `;
    const activeNode = els.deskLayoutPageList.querySelector(`[data-page-node="${cssEscape(activeId)}"]`);
    if (layerList) {
      (activeNode || els.deskLayoutPageList).after(layerList);
      layerList.hidden = pageTreeCollapsed;
    }
    focusRenamingPage();
  }

  function focusRenamingPage() {
    if (!renamingPageId || !els.deskLayoutPageList) return;
    requestAnimationFrame(() => {
      const input = els.deskLayoutPageList?.querySelector(`[data-page-name-input][data-page-id="${cssEscape(renamingPageId)}"]`);
      if (!input) return;
      input.focus();
      input.select();
    });
  }

  async function loadPageIntoCanvas(page, options = {}) {
    if (!activeProjectMeta || !page) return;
    const nextCanvas = ensureFabricCanvas();
    exitGroupIsolation({ silent: true, skipUi: true, keepSelection: true });
    nextCanvas.setWidth(activeProjectMeta.width);
    nextCanvas.setHeight(activeProjectMeta.height);
    nextCanvas.clear();
    nextCanvas.discardActiveObject();
    nextCanvas.backgroundColor = activeProjectMeta.background || '#ffffff';
    renamingLayerIndex = null;
    renamingGroupId = '';
    draggingLayerIndex = null;
    selectedLayerIndices = [];
    clearGroupImageEditTarget();
    await loadCanvasJson(nextCanvas, {
      ...activeProjectMeta,
      canvasJson: page.canvasJson || null
    }, { seedIfEmpty: options.seedIfEmpty === true });
    migrateTemplateObjects();
    normalizeLayerObjects();
    await ensureCanvasFontsLoaded(nextCanvas);
    activeProjectMeta.canvasJson = page.canvasJson || currentCanvasJson();
    nextCanvas.requestRenderAll();
    if (els.deskLayoutMeta) {
      const preset = getPreset(activeProjectMeta.presetId);
      els.deskLayoutMeta.textContent = `${activeProjectMeta.width} x ${activeProjectMeta.height} · ${preset.ratio || ''}`;
    }
    if (els.deskLayoutPage) {
      els.deskLayoutPage.dataset.size = `${activeProjectMeta.width} x ${activeProjectMeta.height}`;
    }
    updateAssistUi();
    renderPages(activeProjectMeta);
    renderLayers();
    updateSelectionUi();
    await renderCanvasImmediately();
    requestAnimationFrame(() => {
      if (stageZoomMode === 'fit') fitStageToView();
      else applyStageZoom(stageZoom, stageZoomMode);
    });
  }

  async function restoreHistorySnapshot(snapshot, label = '') {
    if (!snapshot) return;
    isRestoringHistory = true;
    try {
      const nextSnapshot = clonePlain(snapshot);
      const rawActiveObjectIndex = nextSnapshot?._activeObjectIndex;
      const activeObjectIndex = rawActiveObjectIndex !== null && rawActiveObjectIndex !== undefined && Number.isInteger(Number(rawActiveObjectIndex))
        ? Number(nextSnapshot._activeObjectIndex)
        : -1;
      const activeObjectIndices = Array.isArray(nextSnapshot?._activeObjectIndices)
        ? nextSnapshot._activeObjectIndices.map(Number).filter(index => Number.isInteger(index) && index >= 0)
        : [];
      delete nextSnapshot._activeObjectIndex;
      delete nextSnapshot._activeObjectIndices;
      activeProjectMeta = normalizeProject(nextSnapshot);
      activePageId = activeProjectMeta.activePageId;
      pageTreeCollapsed = false;
      renamingPageId = null;
      renamingLayerIndex = null;
      renamingGroupId = '';
      clearGroupImageEditTarget();
      const page = getActivePage(activeProjectMeta);
      await loadPageIntoCanvas(page, { seedIfEmpty: false });
      const canvasObjects = canvas?.getObjects?.() || [];
      const selectedObjects = activeObjectIndices
        .map(index => canvasObjects[index])
        .filter(object => object && object.visible !== false);
      if (selectedObjects.length > 1) {
        selectedLayerIndices = activeObjectIndices.filter(index => canvasObjects[index]?.visible !== false);
        syncingLayerSelection = true;
        try {
          canvas.discardActiveObject();
          canvas.setActiveObject(selectedObjects[0]);
        } finally {
          syncingLayerSelection = false;
        }
        canvas.requestRenderAll();
      } else {
        selectedLayerIndices = [];
        const selectedObject = activeObjectIndex >= 0 ? canvasObjects[activeObjectIndex] : selectedObjects[0] || null;
        if (selectedObject && selectedObject.visible !== false) {
          canvas.setActiveObject(selectedObject);
          canvas.requestRenderAll();
        }
      }
      persistActivePage({ thumbnail: false });
      renderPages(activeProjectMeta);
      renderLayers();
      updateSelectionUi();
      historySnapshotKey = historyKey(snapshot);
      updateHistoryButtons();
      if (label) setStatus(label, '');
    } finally {
      isRestoringHistory = false;
    }
  }

  async function undoLayoutEdit() {
    flushPendingHistory();
    if (undoStack.length <= 1) {
      updateHistoryButtons();
      return;
    }
    const current = undoStack.pop();
    if (current) redoStack.push(current);
    const previous = undoStack[undoStack.length - 1];
    historySnapshotKey = historyKey(previous);
    await restoreHistorySnapshot(previous, '已撤销');
  }

  async function redoLayoutEdit() {
    flushPendingHistory();
    const next = redoStack.pop();
    if (!next) {
      updateHistoryButtons();
      return;
    }
    undoStack.push(next);
    if (undoStack.length > historyLimit) undoStack.splice(0, undoStack.length - historyLimit);
    historySnapshotKey = historyKey(next);
    await restoreHistorySnapshot(next, '已重做');
  }

  async function switchPage(pageId) {
    if (!activeProjectMeta || !pageId || pageId === activePageId) {
      if (pageId === activePageId) {
        pageTreeCollapsed = !pageTreeCollapsed;
        renderPages(activeProjectMeta);
        renderLayers();
      }
      return;
    }
    flushPendingHistory();
    persistActivePage({ thumbnail: true });
    activePageId = pageId;
    activeProjectMeta.activePageId = pageId;
    renamingPageId = null;
    const page = getActivePage(activeProjectMeta);
    await loadPageIntoCanvas(page);
    recordHistory('页面已切换');
    setStatus(`${page.name || '页面'} 已切换`, '');
  }

  async function addPage() {
    if (!activeProjectMeta) return;
    flushPendingHistory();
    persistActivePage({ thumbnail: true });
    const page = {
      id: createPageId(),
      name: `第 ${activeProjectMeta.pages.length + 1} 页`,
      canvasJson: createBlankCanvasJson(activeProjectMeta.background || '#ffffff'),
      thumbnailDataUrl: ''
    };
    activeProjectMeta.pages.push(page);
    activePageId = page.id;
    activeProjectMeta.activePageId = page.id;
    pageTreeCollapsed = false;
    await loadPageIntoCanvas(page);
    persistActivePage({ thumbnail: true });
    renderPages(activeProjectMeta);
    recordHistory('已新增页面');
    setStatus('已新增空白页面，记得保存', '');
  }

  async function duplicatePage() {
    if (!activeProjectMeta) return;
    flushPendingHistory();
    persistActivePage({ thumbnail: true });
    const index = getActivePageIndex(activeProjectMeta);
    const current = getActivePage(activeProjectMeta);
    if (!current) return;
    const page = {
      id: createPageId(),
      name: `${current.name || `第 ${index + 1} 页`} 副本`,
      canvasJson: clonePlain(current.canvasJson || currentCanvasJson()),
      thumbnailDataUrl: current.thumbnailDataUrl || ''
    };
    activeProjectMeta.pages.splice(index + 1, 0, page);
    activePageId = page.id;
    activeProjectMeta.activePageId = page.id;
    pageTreeCollapsed = false;
    await loadPageIntoCanvas(page);
    recordHistory('已复制页面');
    setStatus('已复制当前页面，记得保存', '');
  }

  async function deletePage() {
    if (!activeProjectMeta || activeProjectMeta.pages.length <= 1) {
      setStatus('至少需要保留 1 个页面', 'error');
      return;
    }
    flushPendingHistory();
    const index = getActivePageIndex(activeProjectMeta);
    activeProjectMeta.pages.splice(index, 1);
    const nextIndex = Math.max(0, Math.min(index, activeProjectMeta.pages.length - 1));
    const nextPage = activeProjectMeta.pages[nextIndex];
    activePageId = nextPage.id;
    activeProjectMeta.activePageId = nextPage.id;
    pageTreeCollapsed = false;
    await loadPageIntoCanvas(nextPage);
    recordHistory('页面已删除');
    setStatus('页面已删除，记得保存', '');
  }

  function startPageRename(pageId) {
    if (!activeProjectMeta?.pages.some(page => page.id === pageId)) return;
    renamingPageId = pageId;
    renderPages(activeProjectMeta);
  }

  function commitPageRename(input) {
    if (!input || !activeProjectMeta) return;
    const page = activeProjectMeta.pages.find(item => item.id === input.dataset.pageId);
    renamingPageId = null;
    if (!page) {
      renderPages(activeProjectMeta);
      return;
    }
    const name = String(input.value || '').trim();
    if (name && page.name !== name.slice(0, 40)) {
      page.name = name.slice(0, 40);
      recordHistory('页面已重命名');
      setStatus('页面已重命名，记得保存', '');
    }
    renderPages(activeProjectMeta);
  }

  function applyLayersPanelState() {
    const collapsed = Boolean(layersPanelCollapsed);
    els.deskLayoutEditor?.classList.toggle('is-layers-collapsed', collapsed);
    els.deskLayoutLayersPanel?.classList.toggle('is-collapsed', collapsed);
    if (els.deskLayoutLayersCollapseBtn) {
      els.deskLayoutLayersCollapseBtn.textContent = collapsed ? '›' : '‹';
      els.deskLayoutLayersCollapseBtn.title = collapsed ? '展开页面与图层' : '折叠页面与图层';
      els.deskLayoutLayersCollapseBtn.setAttribute('aria-label', collapsed ? '展开页面与图层' : '折叠页面与图层');
      els.deskLayoutLayersCollapseBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    }
    if (stageZoomMode === 'fit') requestAnimationFrame(fitStageToView);
  }

  function toggleLayersPanel() {
    layersPanelCollapsed = !layersPanelCollapsed;
    applyLayersPanelState();
  }

  function renderCreateOptions() {
    if (!els.deskLayoutPresetList || !els.deskLayoutTemplateList) return;
    els.deskLayoutPresetList.innerHTML = canvasPresets.map(preset => `
      <button type="button" class="desk-layout-preset${preset.id === selectedPresetId ? ' is-active' : ''}" data-preset-id="${preset.id}">
        <strong>${escapeHtml(preset.name)}</strong>
        <span>${preset.width} x ${preset.height} · ${escapeHtml(preset.ratio)}</span>
        <em>${escapeHtml(preset.note)}</em>
      </button>
    `).join('');
    const templates = getTemplatesForPreset(selectedPresetId);
    if (!templates.some(template => template.id === selectedTemplateId)) {
      selectedTemplateId = templates[0]?.id || 'blank';
    }
    els.deskLayoutTemplateList.innerHTML = templates.map(template => `
      <button type="button" class="desk-layout-template${template.id === selectedTemplateId ? ' is-active' : ''}" data-template-id="${template.id}">
        <i style="--template-accent:${escapeHtml(template.accent)}"></i>
        <span>
          <strong>${escapeHtml(template.name)}</strong>
          <em>${escapeHtml(template.desc)}</em>
        </span>
      </button>
    `).join('');
    const preset = getPreset(selectedPresetId);
    const template = getTemplate(selectedTemplateId);
    if (els.deskLayoutCreateHint) {
      els.deskLayoutCreateHint.textContent = `${preset.name} · ${preset.width} x ${preset.height} · ${template.name}`;
    }
  }

  function showCreatePanel() {
    selectedPresetId = selectedPresetId || 'xhs_3_4';
    selectedTemplateId = getTemplatesForPreset(selectedPresetId)[0]?.id || 'blank';
    renderCreateOptions();
    els.deskLayoutCreate?.removeAttribute('hidden');
    setStatus('请选择尺寸和模板', '');
  }

  function hideCreatePanel() {
    els.deskLayoutCreate?.setAttribute('hidden', 'true');
  }

  function applyStageZoom(scale, mode = 'custom') {
    if (!canvas || !els.deskLayoutPage || !els.deskLayoutPageShell) return;
    const clamped = Math.max(0.08, Math.min(1.4, Number(scale) || 1));
    stageZoom = clamped;
    stageZoomMode = mode;
    const outerWidth = canvas.getWidth() + 38;
    const outerHeight = canvas.getHeight() + 38;
    els.deskLayoutPage.style.width = `${canvas.getWidth()}px`;
    els.deskLayoutPage.style.height = `${canvas.getHeight()}px`;
    els.deskLayoutPage.style.transform = `scale(${clamped})`;
    els.deskLayoutPageShell.style.width = `${outerWidth * clamped}px`;
    els.deskLayoutPageShell.style.height = `${outerHeight * clamped}px`;
    if (els.deskLayoutZoomSelect) {
      els.deskLayoutZoomSelect.value = mode === 'fit' ? 'fit' : String(clamped);
    }
    updateAssistUi();
  }

  function fitStageToView() {
    if (!canvas || !els.deskLayoutStage) return;
    const rect = els.deskLayoutStage.getBoundingClientRect();
    const outerWidth = canvas.getWidth() + 38;
    const outerHeight = canvas.getHeight() + 38;
    const availableWidth = Math.max(240, rect.width - 96);
    const availableHeight = Math.max(240, rect.height - 142);
    const scale = Math.min(1, availableWidth / outerWidth, availableHeight / outerHeight);
    applyStageZoom(scale, 'fit');
  }

  function getLayerGroupId(object) {
    return String(object?.layoutGroupId || '').trim();
  }

  function createLayerGroupId() {
    return `group_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
  }

  function collectLayerGroups(objects = canvas?.getObjects?.() || []) {
    const groups = new Map();
    objects.forEach((object, index) => {
      const groupId = getLayerGroupId(object);
      if (!groupId) return;
      if (!groups.has(groupId)) {
        groups.set(groupId, {
          id: groupId,
          name: String(object.layoutGroupName || '').trim() || '组合图层',
          indices: [],
          objects: [],
          topIndex: index,
          bottomIndex: index
        });
      }
      const group = groups.get(groupId);
      group.indices.push(index);
      group.objects.push(object);
      group.topIndex = Math.max(group.topIndex, index);
      group.bottomIndex = Math.min(group.bottomIndex, index);
      if (!group.name || group.name === '组合图层') {
        group.name = String(object.layoutGroupName || '').trim() || group.name;
      }
    });
    groups.forEach(group => {
      group.name = group.name || `组合 ${group.indices.length}`;
      group.hidden = group.objects.every(object => object.visible === false);
      group.locked = group.objects.every(object => isLayerLocked(object));
    });
    return groups;
  }

  function getSelectedGroupId(objects = getActiveLayerObjects()) {
    const selectedObjects = (objects || []).filter(Boolean);
    if (!selectedObjects.length) return '';
    const groupId = getLayerGroupId(selectedObjects[0]);
    if (!groupId || selectedObjects.some(object => getLayerGroupId(object) !== groupId)) return '';
    const groups = collectLayerGroups();
    const group = groups.get(groupId);
    return group && selectedObjects.length === group.objects.filter(object => object.visible !== false).length ? groupId : '';
  }

  function getGroupById(groupId) {
    const key = String(groupId || '').trim();
    return key ? collectLayerGroups().get(key) || null : null;
  }

  function isLayerMutedByIsolation(object) {
    return Boolean(isolatedGroupId && getLayerGroupId(object) !== isolatedGroupId);
  }

  function isGroupMutedByIsolation(group) {
    return Boolean(isolatedGroupId && group?.id !== isolatedGroupId);
  }

  function renderLayerRow(object, index, selectedObjects, options = {}) {
    const activeClass = selectedObjects.includes(object) ? ' is-active' : '';
    const hiddenClass = object.visible === false ? ' is-hidden' : '';
    const lockedClass = isLayerLocked(object) ? ' is-locked' : '';
    const draggingClass = draggingLayerIndex === index ? ' is-dragging' : '';
    const childClass = options.groupChild ? ' is-group-child' : '';
    const mutedByIsolation = isLayerMutedByIsolation(object);
    const isolatedChildClass = isObjectInIsolatedGroup(object) ? ' is-isolated-child' : '';
    const isolationClass = mutedByIsolation ? ' is-isolation-muted' : isolatedChildClass;
    const icon = object.type === 'image' ? '图' : (object.type === 'rect' ? '形' : 'T');
    const label = objectLabel(object, index);
    const escapedLabel = escapeHtml(label);
    const isRenaming = renamingLayerIndex === index;
    const visibilityTitle = object.visible === false ? '显示图层' : '隐藏图层';
    const lockTitle = isLayerLocked(object) ? '解锁图层' : '锁定图层';
    return `
      <div class="desk-layout-layer is-tree-child${childClass}${activeClass}${hiddenClass}${lockedClass}${draggingClass}${isolationClass}" draggable="${mutedByIsolation ? 'false' : 'true'}" data-layer-index="${index}"${mutedByIsolation ? ' aria-disabled="true"' : ''}>
        <button type="button" class="desk-layout-layer__grab" data-layer-control data-layer-grab title="拖拽调整层级" aria-label="拖拽调整层级">${layerActionIcon('drag')}</button>
        <div class="desk-layout-layer__main">
          <button type="button" class="desk-layout-layer__type" data-layer-select title="选中图层" aria-label="选中图层"><i>${icon}</i></button>
          ${isRenaming
            ? `<input class="desk-layout-layer__name-input" data-layer-name-input data-layer-index="${index}" value="${escapedLabel}" aria-label="图层名称">`
            : `<button type="button" class="desk-layout-layer__name" data-layer-select title="${escapedLabel}"><span>${escapedLabel}</span></button>`}
        </div>
        <div class="desk-layout-layer__actions" data-layer-control>
          <button type="button" class="desk-layout-layer__action" data-layer-visibility title="${visibilityTitle}" aria-label="${visibilityTitle}">${layerActionIcon(object.visible === false ? 'hidden' : 'visible')}</button>
          <button type="button" class="desk-layout-layer__action" data-layer-lock title="${lockTitle}" aria-label="${lockTitle}">${layerActionIcon(isLayerLocked(object) ? 'locked' : 'unlocked')}</button>
          <button type="button" class="desk-layout-layer__action" data-layer-rename title="重命名图层" aria-label="重命名图层">${layerActionIcon('rename')}</button>
        </div>
      </div>
    `;
  }

  function renderLayerGroupRow(group, isActive = false) {
    const collapsed = collapsedGroupIds.has(group.id);
    const hiddenClass = group.hidden ? ' is-hidden' : '';
    const lockedClass = group.locked ? ' is-locked' : '';
    const activeClass = isActive ? ' is-active' : '';
    const isolatedClass = isGroupIsolated(group.id) ? ' is-isolated' : '';
    const mutedClass = isGroupMutedByIsolation(group) ? ' is-isolation-muted' : '';
    const escapedName = escapeHtml(group.name || '组合图层');
    const isRenaming = renamingGroupId === group.id;
    const badge = isolatedClass ? '<em class="desk-layout-layer__badge">隔离</em>' : '';
    return `
      <div class="desk-layout-layer desk-layout-layer--group is-tree-child${activeClass}${hiddenClass}${lockedClass}${isolatedClass}${mutedClass}" data-layer-group-id="${escapeHtml(group.id)}">
        <button type="button" class="desk-layout-layer__grab" data-layer-group-toggle title="${collapsed ? '展开组合' : '折叠组合'}" aria-label="${collapsed ? '展开组合' : '折叠组合'}">${collapsed ? '▸' : '▾'}</button>
        <div class="desk-layout-layer__main">
          <button type="button" class="desk-layout-layer__type" data-layer-group-select title="选中组合" aria-label="选中组合"><i>组</i></button>
          ${isRenaming
            ? `<input class="desk-layout-layer__name-input" data-layer-group-name-input data-layer-group-id="${escapeHtml(group.id)}" value="${escapedName}" aria-label="组合名称">`
            : `<button type="button" class="desk-layout-layer__name" data-layer-group-select title="${escapedName}"><span><b>${escapedName} · ${group.objects.length} 层</b>${badge}</span></button>`}
        </div>
        <div class="desk-layout-layer__actions" data-layer-control>
          <button type="button" class="desk-layout-layer__action" data-layer-group-visibility title="${group.hidden ? '显示组合' : '隐藏组合'}" aria-label="${group.hidden ? '显示组合' : '隐藏组合'}">${layerActionIcon(group.hidden ? 'hidden' : 'visible')}</button>
          <button type="button" class="desk-layout-layer__action" data-layer-group-lock title="${group.locked ? '解锁组合' : '锁定组合'}" aria-label="${group.locked ? '解锁组合' : '锁定组合'}">${layerActionIcon(group.locked ? 'locked' : 'unlocked')}</button>
          <button type="button" class="desk-layout-layer__action" data-layer-group-rename title="重命名组合" aria-label="重命名组合">${layerActionIcon('rename')}</button>
        </div>
      </div>
    `;
  }

  function renderLayers() {
    if (!els.deskLayoutLayerList || !canvas) return;
    els.deskLayoutLayerList.hidden = pageTreeCollapsed;
    updateLayerIsolationBar();
    const objects = canvas.getObjects();
    const active = canvas.getActiveObject();
    const customSelectedObjects = selectedLayerIndices
      .map(index => objects[index])
      .filter(object => object && object.visible !== false);
    const selectedObjects = customSelectedObjects.length > 1
      ? customSelectedObjects
      : (active?.type === 'activeSelection' && typeof active.getObjects === 'function'
        ? active.getObjects()
        : (active ? [active] : []));
    if (!objects.length) {
      renamingLayerIndex = null;
      renamingGroupId = '';
      els.deskLayoutLayerList.innerHTML = `
        <div class="desk-layout-empty-state desk-layout-empty-state--layers is-tree-child">
          <strong>暂无图层</strong>
          <span>点击顶部“文本”或“插图”开始排版。</span>
        </div>
      `;
      return;
    }
    const groups = collectLayerGroups(objects);
    if (isolatedGroupId) {
      const isolatedGroup = groups.get(isolatedGroupId);
      if (isolatedGroup) collapsedGroupIds.delete(isolatedGroup.id);
    }
    const selectedGroupId = getSelectedGroupId(selectedObjects);
    const renderedGroups = new Set();
    const rows = [];
    objects.slice().reverse().forEach((object, reverseIndex) => {
      const index = objects.length - 1 - reverseIndex;
      const groupId = getLayerGroupId(object);
      const group = groupId ? groups.get(groupId) : null;
      if (group) {
        if (renderedGroups.has(groupId)) return;
        renderedGroups.add(groupId);
        rows.push(renderLayerGroupRow(group, selectedGroupId === groupId));
        if (!collapsedGroupIds.has(groupId)) {
          group.indices.slice().sort((a, b) => b - a).forEach(childIndex => {
            rows.push(renderLayerRow(objects[childIndex], childIndex, selectedObjects, { groupChild: true }));
          });
        }
        return;
      }
      rows.push(renderLayerRow(object, index, selectedObjects));
    });
    els.deskLayoutLayerList.innerHTML = rows.join('');
    focusRenamingLayer();
    focusRenamingGroup();
    focusLayerListOnIsolation();
  }

  function renderTemplateControls() {
    if (!els.deskLayoutTemplateControls || !els.deskLayoutTemplateFields || !canvas) return 0;
    const fields = collectTemplateFields();
    const count = fields.texts.length + fields.images.length;
    els.deskLayoutTemplateControls.hidden = count === 0;
    if (!count) {
      els.deskLayoutTemplateFields.innerHTML = '';
      return 0;
    }
    const textFields = fields.texts.map(field => {
      const rows = field.value.includes('\n') || ['title', 'subtitle', 'caption'].includes(field.key) || /Description$/i.test(field.key) ? 2 : 1;
      return `
        <label class="desk-layout-template-field">
          <span>${escapeHtml(field.label)}</span>
          <textarea rows="${rows}" data-template-text-var="${escapeHtml(field.key)}">${escapeHtml(field.value)}</textarea>
        </label>
      `;
    }).join('');
    const imageFields = fields.images.map(field => {
      const state = field.hasImage ? '已接入图片' : (field.hasPlaceholder ? '等待图片' : '未设置');
      return `
        <div class="desk-layout-template-image-field">
          <span>
            <strong>${escapeHtml(field.label)}</strong>
            <em>${escapeHtml(state)}</em>
          </span>
          <button type="button" data-template-image-var="${escapeHtml(field.key)}">${field.hasImage ? '替换' : '选择'}</button>
        </div>
      `;
    }).join('');
    els.deskLayoutTemplateFields.innerHTML = `${textFields}${imageFields}`;
    return count;
  }

  function findTemplateObjectsByVariable(variable) {
    const key = String(variable || '').trim();
    if (!key || !canvas) return [];
    return canvas.getObjects().filter(object => String(object.layoutVariable || object.layoutRole || '').trim() === key);
  }

  function focusTemplateObject(variable) {
    const object = findTemplateObjectsByVariable(variable).find(item => item.visible !== false);
    if (!object || !canvas) return;
    canvas.setActiveObject(object);
    canvas.requestRenderAll();
    renderLayers();
  }

  function updateTemplateTextVariable(variable, value) {
    const objects = findTemplateObjectsByVariable(variable).filter(isTextObject);
    if (!objects.length || !canvas) return;
    syncingSelection = true;
    objects.forEach(object => object.set('text', value));
    syncingSelection = false;
    const activeObject = canvas.getActiveObject();
    if (activeObject && objects.includes(activeObject) && els.deskLayoutTextInput) {
      els.deskLayoutTextInput.value = value;
    }
    canvas.requestRenderAll();
    persistActivePage({ thumbnail: false });
    renderLayers();
    scheduleHistoryRecord('模板字段已更新');
    setStatus('模板字段已更新，记得保存', '');
  }

  function findTemplateImageTarget(variable) {
    const objects = findTemplateObjectsByVariable(variable).filter(isTemplateImageObject);
    return objects.find(object => object.isTemplatePlaceholder === true)
      || objects.find(object => object.type === 'image')
      || objects[0]
      || null;
  }

  function focusRenamingLayer() {
    if (renamingLayerIndex === null || !els.deskLayoutLayerList) return;
    requestAnimationFrame(() => {
      const input = els.deskLayoutLayerList?.querySelector(`[data-layer-name-input][data-layer-index="${renamingLayerIndex}"]`);
      if (!input) return;
      input.focus();
      input.select();
    });
  }

  function focusRenamingGroup() {
    if (!renamingGroupId || !els.deskLayoutLayerList) return;
    requestAnimationFrame(() => {
      const input = els.deskLayoutLayerList?.querySelector(`[data-layer-group-name-input][data-layer-group-id="${cssEscape(renamingGroupId)}"]`);
      if (!input) return;
      input.focus();
      input.select();
    });
  }

  function getLayerByIndex(index) {
    if (!canvas) return null;
    const normalized = Number(index);
    if (!Number.isInteger(normalized)) return null;
    return canvas.getObjects()[normalized] || null;
  }

  function getCustomSelectedLayerObjects() {
    if (!canvas || selectedLayerIndices.length <= 1) return [];
    return selectedLayerIndices
      .map(index => getLayerByIndex(index))
      .filter(object => object && object.visible !== false);
  }

  function getActiveLayerObjects() {
    if (!canvas) return [];
    const selectedObjects = getCustomSelectedLayerObjects();
    if (selectedObjects.length > 1) return selectedObjects;
    const active = canvas.getActiveObject();
    if (!active || active.visible === false) return [];
    if (active.type === 'activeSelection' && typeof active.getObjects === 'function') {
      return active.getObjects().filter(object => object && object.visible !== false);
    }
    return [active];
  }

  function getLayerObjectsInStackOrder(objects = []) {
    const selected = new Set((objects || []).filter(Boolean));
    if (!canvas || !selected.size) return [];
    return canvas.getObjects().filter(object => selected.has(object));
  }

  function setActiveLayerObjects(objects = [], preferredObject = null) {
    if (!canvas) return;
    const visibleObjects = getLayerObjectsInStackOrder(objects).filter(object => object.visible !== false);
    const canvasObjects = canvas.getObjects();
    const activeObject = visibleObjects.includes(preferredObject) ? preferredObject : visibleObjects[0];
    selectedLayerIndices = visibleObjects.length > 1
      ? visibleObjects.map(object => canvasObjects.indexOf(object)).filter(index => index >= 0)
      : [];
    syncingLayerSelection = true;
    try {
      canvas.discardActiveObject();
      if (activeObject) {
        canvas.setActiveObject(activeObject);
      }
    } finally {
      syncingLayerSelection = false;
    }
    canvas.requestRenderAll();
    updateSelectionUi();
  }

  function selectLayer(index) {
    const object = getLayerByIndex(index);
    if (!object || !canvas) return;
    if (isolatedGroupId && !isObjectInIsolatedGroup(object)) {
      warnIsolationLocked();
      return;
    }
    if (object.visible === false) {
      if (canvas.getActiveObject() === object) canvas.discardActiveObject();
      canvas.requestRenderAll();
      updateSelectionUi();
      setStatus('隐藏图层需要先显示后再编辑', '');
      return;
    }
    selectedLayerIndices = [];
    canvas.setActiveObject(object);
    canvas.requestRenderAll();
    updateSelectionUi();
  }

  function getSelectedLayerIndices() {
    if (selectedLayerIndices.length > 1) return [...selectedLayerIndices];
    const objects = canvas?.getObjects?.() || [];
    return getActiveArrangeObjects()
      .map(object => objects.indexOf(object))
      .filter(index => index >= 0);
  }

  function selectLayerSet(indices = [], preferredObject = null) {
    if (!canvas) return;
    const unique = [...new Set(indices.map(Number).filter(index => Number.isInteger(index)))];
    const pairs = unique
      .map(index => ({ index, object: getLayerByIndex(index) }))
      .filter(item => item.object && item.object.visible !== false);
    const activeObject = pairs.some(item => item.object === preferredObject) ? preferredObject : pairs[0]?.object;
    selectedLayerIndices = pairs.length > 1 ? pairs.map(item => item.index) : [];
    syncingLayerSelection = true;
    try {
      canvas.discardActiveObject();
      if (activeObject) {
        canvas.setActiveObject(activeObject);
      }
    } finally {
      syncingLayerSelection = false;
    }
    canvas.requestRenderAll();
    updateSelectionUi();
  }

  function selectLayerGroup(groupId, preferredObject = null) {
    const group = getGroupById(groupId);
    if (!group) return;
    if (isolatedGroupId && group.id !== isolatedGroupId) {
      warnIsolationLocked();
      return;
    }
    selectLayerSet(group.indices, preferredObject);
  }

  function toggleLayerGroupCollapsed(groupId) {
    const key = String(groupId || '').trim();
    if (!key) return;
    if (isGroupIsolated(key)) {
      collapsedGroupIds.delete(key);
      renderLayers();
      setStatus('隔离编辑时当前组合保持展开', '');
      return;
    }
    if (collapsedGroupIds.has(key)) collapsedGroupIds.delete(key);
    else collapsedGroupIds.add(key);
    renderLayers();
  }

  function toggleLayerGroupVisibility(groupId) {
    const group = getGroupById(groupId);
    if (!group || !canvas) return;
    flushPendingHistory();
    refreshCurrentHistorySnapshot();
    const nextVisible = group.hidden;
    group.objects.forEach(object => object.set('visible', nextVisible));
    if (group.objects.includes(getGroupImageEditTarget())) clearGroupImageEditTarget();
    if (!nextVisible && isGroupIsolated(group.id)) {
      exitGroupIsolation({ silent: true, skipUi: true, keepSelection: true });
    }
    selectedLayerIndices = [];
    canvas.discardActiveObject();
    canvas.requestRenderAll();
    updateSelectionUi();
    recordHistory(nextVisible ? '组合已显示' : '组合已隐藏');
    setStatus(nextVisible ? '组合已显示，记得保存' : '组合已隐藏，记得保存', '');
  }

  function toggleLayerGroupLock(groupId) {
    const group = getGroupById(groupId);
    if (!group || !canvas) return;
    flushPendingHistory();
    refreshCurrentHistorySnapshot();
    const nextLocked = !group.locked;
    group.objects.forEach(object => applyLayerLock(object, nextLocked));
    if (nextLocked) {
      activeMultiDrag = null;
      if (group.objects.includes(getGroupImageEditTarget())) clearGroupImageEditTarget();
      if (isGroupIsolated(group.id)) {
        exitGroupIsolation({ silent: true, skipUi: true, keepSelection: true });
      }
    }
    canvas.requestRenderAll();
    updateSelectionUi();
    recordHistory(nextLocked ? '组合已锁定' : '组合已解锁');
    setStatus(nextLocked ? '组合已锁定，记得保存' : '组合已解锁，记得保存', '');
  }

  function getLayerBatchTargets(index) {
    const object = getLayerByIndex(index);
    if (!object) return [];
    if (selectedLayerIndices.length > 1 && selectedLayerIndices.includes(Number(index))) {
      const selectedObjects = getCustomSelectedLayerObjects();
      if (selectedObjects.length > 1) return selectedObjects;
    }
    return [object];
  }

  function toggleLayerVisibility(index) {
    const targets = getLayerBatchTargets(index);
    const object = targets[0];
    if (!object || !canvas) return;
    const nextVisible = object.visible === false;
    flushPendingHistory();
    refreshCurrentHistorySnapshot();
    targets.forEach(item => item.set('visible', nextVisible));
    if (!nextVisible && targets.includes(canvas.getActiveObject())) {
      canvas.discardActiveObject();
    }
    if (!nextVisible && targets.some(item => selectedLayerIndices.includes(canvas.getObjects().indexOf(item)))) {
      selectedLayerIndices = [];
    }
    canvas.requestRenderAll();
    updateSelectionUi();
    const label = targets.length > 1 ? `${targets.length} 个图层` : '图层';
    recordHistory(nextVisible ? `${label}已显示` : `${label}已隐藏`);
    setStatus(nextVisible ? `${label}已显示，记得保存` : `${label}已隐藏，记得保存`, '');
  }

  function toggleLayerLock(index) {
    const targets = getLayerBatchTargets(index);
    const object = targets[0];
    if (!object || !canvas) return;
    const nextLocked = !isLayerLocked(object);
    flushPendingHistory();
    refreshCurrentHistorySnapshot();
    targets.forEach(item => applyLayerLock(item, nextLocked));
    if (nextLocked && targets.includes(getGroupImageEditTarget())) clearGroupImageEditTarget();
    canvas.requestRenderAll();
    updateSelectionUi();
    const label = targets.length > 1 ? `${targets.length} 个图层` : '图层';
    recordHistory(nextLocked ? `${label}已锁定` : `${label}已解锁`);
    setStatus(nextLocked ? `${label}已锁定，记得保存` : `${label}已解锁，记得保存`, '');
  }

  function startLayerRename(index) {
    if (!getLayerByIndex(index)) return;
    renamingGroupId = '';
    renamingLayerIndex = Number(index);
    renderLayers();
  }

  function commitLayerRename(input) {
    if (!input) return;
    const index = Number(input.dataset.layerIndex);
    const object = getLayerByIndex(index);
    renamingLayerIndex = null;
    if (!object) {
      renderLayers();
      return;
    }
    const nextName = String(input.value || '').trim();
    const normalizedName = nextName.slice(0, 80);
    if (normalizedName && object.name !== normalizedName) {
      object.set('name', normalizedName);
      recordHistory('图层已重命名');
      setStatus('图层已重命名，记得保存', '');
    }
    updateSelectionUi();
  }

  function startGroupRename(groupId) {
    const group = getGroupById(groupId);
    if (!group) return;
    renamingLayerIndex = null;
    renamingGroupId = group.id;
    renderLayers();
  }

  function commitGroupRename(input) {
    if (!input) return;
    const groupId = String(input.dataset.layerGroupId || '').trim();
    const group = getGroupById(groupId);
    renamingGroupId = '';
    if (!group) {
      renderLayers();
      return;
    }
    const nextName = String(input.value || '').trim();
    const normalizedName = nextName.slice(0, 80);
    if (normalizedName && group.name !== normalizedName) {
      flushPendingHistory();
      refreshCurrentHistorySnapshot();
      group.objects.forEach(object => object.set('layoutGroupName', normalizedName));
      recordHistory('组合已重命名');
      setStatus('组合已重命名，记得保存', '');
    }
    renderLayers();
    updateSelectionUi();
  }

  function moveLayer(fromIndex, toIndex) {
    if (!canvas) return;
    const from = Number(fromIndex);
    const to = Number(toIndex);
    if (!Number.isInteger(from) || !Number.isInteger(to) || from === to) return;
    const object = getLayerByIndex(from);
    if (!object) return;
    const targetObject = getLayerByIndex(to);
    if (isolatedGroupId && (!isObjectInIsolatedGroup(object) || !isObjectInIsolatedGroup(targetObject))) {
      warnIsolationLocked();
      return;
    }
    selectedLayerIndices = [];
    canvas.moveTo(object, Math.max(0, Math.min(canvas.getObjects().length - 1, to)));
    canvas.setActiveObject(object);
    canvas.requestRenderAll();
    updateSelectionUi();
    recordHistory('图层顺序已调整');
    setStatus('图层顺序已调整，记得保存', '');
  }

  function layerObjectData(object) {
    const data = object?.toObject ? object.toObject(canvasJsonProps()) : null;
    if (data && isImageObject(object)) {
      const element = object.getElement?.() || object._element || object._originalElement || null;
      const src = object.getSrc?.() || element?.currentSrc || element?.src || data.src || '';
      if (src) data.src = src;
    }
    return data;
  }

  function enlivenLayerObjects(items = []) {
    return new Promise(resolve => {
      if (!window.fabric?.util?.enlivenObjects || !items.length) {
        resolve([]);
        return;
      }
      fabric.util.enlivenObjects(items, objects => resolve(objects || []));
    });
  }

  function copyLayerName(name, fallback = '图层') {
    const base = String(name || fallback || '图层').trim().slice(0, 70) || '图层';
    return /副本(?:\s\d+)?$/.test(base) ? `${base} 2` : `${base} 副本`;
  }

  function preparePastedObject(object, source = {}, offset = 24, index = 0, groupMap = new Map()) {
    if (!object) return null;
    const nextLeft = Number(source.left ?? object.left ?? 0) + offset;
    const nextTop = Number(source.top ?? object.top ?? 0) + offset;
    const sourceGroupId = String(source.layoutGroupId || '').trim();
    const mappedGroup = sourceGroupId ? groupMap.get(sourceGroupId) : null;
    object.set({
      left: nextLeft,
      top: nextTop,
      name: copyLayerName(source.name, objectLabel(object, index)),
      layoutLocked: false,
      layoutGroupId: mappedGroup?.id || '',
      layoutGroupName: mappedGroup?.name || ''
    });
    if (Number.isFinite(Number(source.layoutFrameLeft))) {
      object.set('layoutFrameLeft', Number(source.layoutFrameLeft) + offset);
    }
    if (Number.isFinite(Number(source.layoutFrameTop))) {
      object.set('layoutFrameTop', Number(source.layoutFrameTop) + offset);
    }
    applyLayerLock(object, false);
    if (isImageObject(object)) {
      object.__layoutFitFrame = null;
      rememberImageFrame(object);
    }
    if (isTextObject(object)) refreshTextObjectMetrics(object);
    object.setCoords?.();
    return object;
  }

  function copyActiveLayers(options = {}) {
    const objects = getLayerObjectsInStackOrder(getActiveLayerObjects());
    if (!objects.length) {
      if (!options.silent) setStatus('请先选中要复制的图层', 'error');
      return false;
    }
    layoutClipboard = {
      objects: objects.map(layerObjectData).filter(Boolean),
      pasteCount: 1
    };
    updateSelectionUi();
    if (!options.silent) {
      setStatus(objects.length > 1 ? `已复制 ${objects.length} 个图层` : '图层已复制', 'saved');
    }
    return true;
  }

  async function pasteLayerClipboard(options = {}) {
    if (!canvas || !layoutClipboard?.objects?.length) {
      if (!options.silent) setStatus('暂无可粘贴图层', 'error');
      return [];
    }
    flushPendingHistory();
    refreshCurrentHistorySnapshot();
    const pasteCount = Math.max(1, Number(layoutClipboard.pasteCount || 1));
    const baseOffset = Math.max(0, Number(options.offset ?? layerPasteOffset));
    const offsetSteps = options.accumulateOffset === false ? 1 : Math.min(pasteCount, maxPasteOffsetSteps);
    const offset = baseOffset * offsetSteps;
    const sourceObjects = clonePlain(layoutClipboard.objects) || [];
    const groupMap = new Map();
    [...new Set(sourceObjects.map(object => String(object.layoutGroupId || '').trim()).filter(Boolean))]
      .forEach((groupId, index) => {
        const groupName = sourceObjects.find(object => String(object.layoutGroupId || '').trim() === groupId)?.layoutGroupName || `组合 ${collectLayerGroups().size + index + 1}`;
        groupMap.set(groupId, {
          id: createLayerGroupId(),
          name: copyLayerName(groupName, '组合图层')
        });
      });
    const objects = await enlivenLayerObjects(sourceObjects);
    const pastedObjects = objects
      .map((object, index) => preparePastedObject(object, sourceObjects[index], offset, index, groupMap))
      .filter(Boolean);
    pastedObjects.forEach(assignObjectToIsolatedGroup);
    pastedObjects.forEach(object => canvas.add(object));
    layoutClipboard.pasteCount = pasteCount + 1;
    setActiveLayerObjects(pastedObjects);
    pastedObjects.forEach(object => {
      object.dirty = true;
      object.setCoords?.();
    });
    await renderCanvasImmediately();
    renderLayers();
    persistActivePage({ thumbnail: false });
    recordHistory(options.label || (pastedObjects.length > 1 ? `${pastedObjects.length} 个图层已粘贴` : '图层已粘贴'));
    setStatus(pastedObjects.length > 1 ? `已粘贴 ${pastedObjects.length} 个图层，记得保存` : '图层已粘贴，记得保存', '');
    return pastedObjects;
  }

  async function duplicateActiveLayers() {
    if (!copyActiveLayers({ silent: true })) return [];
    return pasteLayerClipboard({
      label: '图层已创建副本',
      offset: layerDuplicateOffset,
      accumulateOffset: false
    });
  }

  function deleteActiveLayers() {
    if (!canvas) return false;
    const objects = getLayerObjectsInStackOrder(getActiveLayerObjects());
    if (!objects.length) return false;
    flushPendingHistory();
    refreshCurrentHistorySnapshot();
    if (isolatedGroupId && objects.some(isObjectInIsolatedGroup)) {
      exitGroupIsolation({ silent: true, skipUi: true, keepSelection: true });
    }
    objects.forEach(object => canvas.remove(object));
    selectedLayerIndices = [];
    if (objects.includes(getGroupImageEditTarget())) clearGroupImageEditTarget();
    canvas.discardActiveObject();
    canvas.requestRenderAll();
    updateSelectionUi();
    const label = objects.length > 1 ? `${objects.length} 个图层已删除` : '图层已删除';
    recordHistory(label);
    setStatus(`${label}，记得保存`, '');
    return true;
  }

  function groupActiveLayers() {
    if (!canvas) return false;
    const objects = getLayerObjectsInStackOrder(getActiveLayerObjects());
    if (objects.length < 2) {
      setStatus('至少选择 2 个图层才能组合', 'error');
      return false;
    }
    flushPendingHistory();
    refreshCurrentHistorySnapshot();
    const groupId = createLayerGroupId();
    const groupName = `组合 ${collectLayerGroups().size + 1}`;
    objects.forEach(object => object.set({
      layoutGroupId: groupId,
      layoutGroupName: groupName
    }));
    clearGroupImageEditTarget();
    collapsedGroupIds.delete(groupId);
    setActiveLayerObjects(objects);
    renderLayers();
    recordHistory('图层已组合');
    setStatus(`${objects.length} 个图层已组合，记得保存`, '');
    return true;
  }

  function getUngroupTargets() {
    const activeObjects = getActiveLayerObjects();
    const groupId = getSelectedGroupId(activeObjects) || getLayerGroupId(activeObjects[0]);
    const group = getGroupById(groupId);
    return group?.objects || [];
  }

  function ungroupActiveLayers() {
    if (!canvas) return false;
    const objects = getUngroupTargets();
    if (!objects.length) {
      setStatus('请先选中一个组合', 'error');
      return false;
    }
    const groupId = getLayerGroupId(objects[0]);
    flushPendingHistory();
    refreshCurrentHistorySnapshot();
    objects.forEach(object => object.set({
      layoutGroupId: '',
      layoutGroupName: ''
    }));
    if (objects.includes(getGroupImageEditTarget())) clearGroupImageEditTarget();
    if (isolatedGroupId && groupId === isolatedGroupId) {
      exitGroupIsolation({ silent: true, skipUi: true, keepSelection: true });
    }
    if (groupId) collapsedGroupIds.delete(groupId);
    setActiveLayerObjects(objects);
    renderLayers();
    recordHistory('组合已取消');
    setStatus('组合已取消，记得保存', '');
    return true;
  }

  function clearLayerDropTargets() {
    els.deskLayoutLayerList?.querySelectorAll('.desk-layout-layer.is-drop-target, .desk-layout-layer.is-dragging').forEach(row => {
      row.classList.remove('is-drop-target', 'is-dragging');
    });
  }

  function handleLayerDragStart(event) {
    const row = event.target.closest('.desk-layout-layer[data-layer-index]');
    if (!row || event.target.closest('.desk-layout-layer__actions, [data-layer-name-input]')) {
      event.preventDefault();
      return;
    }
    draggingLayerIndex = Number(row.dataset.layerIndex);
    if (!Number.isInteger(draggingLayerIndex)) {
      event.preventDefault();
      return;
    }
    if (isolatedGroupId && !isObjectInIsolatedGroup(getLayerByIndex(draggingLayerIndex))) {
      event.preventDefault();
      draggingLayerIndex = null;
      warnIsolationLocked();
      return;
    }
    row.classList.add('is-dragging');
    event.dataTransfer?.setData('text/plain', String(draggingLayerIndex));
    if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
  }

  function handleLayerDragOver(event) {
    const row = event.target.closest('.desk-layout-layer[data-layer-index]');
    if (!row || draggingLayerIndex === null) return;
    if (isolatedGroupId && !isObjectInIsolatedGroup(getLayerByIndex(Number(row.dataset.layerIndex)))) return;
    event.preventDefault();
    clearLayerDropTargets();
    if (Number(row.dataset.layerIndex) !== draggingLayerIndex) {
      row.classList.add('is-drop-target');
    }
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
  }

  function handleLayerDrop(event) {
    const row = event.target.closest('.desk-layout-layer[data-layer-index]');
    if (!row) return;
    event.preventDefault();
    const from = Number(event.dataTransfer?.getData('text/plain') || draggingLayerIndex);
    const to = Number(row.dataset.layerIndex);
    if (isolatedGroupId && (!isObjectInIsolatedGroup(getLayerByIndex(from)) || !isObjectInIsolatedGroup(getLayerByIndex(to)))) {
      clearLayerDropTargets();
      draggingLayerIndex = null;
      warnIsolationLocked();
      return;
    }
    clearLayerDropTargets();
    draggingLayerIndex = null;
    moveLayer(from, to);
  }

  function handleLayerDragEnd() {
    clearLayerDropTargets();
    draggingLayerIndex = null;
  }

  function getObjectMetrics(object) {
    if (!object) {
      return { left: 0, top: 0, width: 0, height: 0, angle: 0, opacity: 100 };
    }
    const width = typeof object.getScaledWidth === 'function'
      ? object.getScaledWidth()
      : Number(object.width || 0) * Number(object.scaleX || 1);
    const height = typeof object.getScaledHeight === 'function'
      ? object.getScaledHeight()
      : Number(object.height || 0) * Number(object.scaleY || 1);
    return {
      left: Number(object.left || 0),
      top: Number(object.top || 0),
      width,
      height,
      angle: Number(object.angle || 0),
      opacity: Math.round(clampNumber(Number(object.opacity ?? 1) * 100, 0, 100, 100))
    };
  }

  function isImageObject(object) {
    return Boolean(object && object.type === 'image');
  }

  function canEditImageObject(object) {
    if (!isImageObject(object)) return false;
    const groupId = getLayerGroupId(object);
    const group = groupId ? getGroupById(groupId) : null;
    if (group?.locked || isLayerLocked(object)) {
      setStatus(group ? '组合已锁定，先解锁后再编辑图片' : '图层已锁定，先解锁后再编辑图片', 'error');
      updateSelectionUi();
      return false;
    }
    return true;
  }

  function getImageNaturalSize(image) {
    const element = image?.getElement?.() || image?._element || image?._originalElement || null;
    return {
      width: Math.max(1, Number(element?.naturalWidth || element?.videoWidth || element?.width || image?.width || 1)),
      height: Math.max(1, Number(element?.naturalHeight || element?.videoHeight || element?.height || image?.height || 1))
    };
  }

  function getImageFrame(image) {
    if (image?.__layoutFitFrame) {
      return { ...image.__layoutFitFrame };
    }
    const metrics = getObjectMetrics(image);
    return {
      left: Number(image?.layoutFrameLeft ?? image?.left ?? 0),
      top: Number(image?.layoutFrameTop ?? image?.top ?? 0),
      width: Math.max(1, Number(image?.layoutFrameWidth || metrics.width || 1)),
      height: Math.max(1, Number(image?.layoutFrameHeight || metrics.height || 1)),
      angle: Number(image?.angle || 0)
    };
  }

  function getImageCropSettings(image) {
    return {
      focalX: clampNumber(image?.layoutFocalX, 0, 1, 0.5),
      focalY: clampNumber(image?.layoutFocalY, 0, 1, 0.5),
      zoom: clampNumber(image?.layoutCropZoom, 1, 4, 1)
    };
  }

  function setImageCropSettings(image, patch = {}) {
    if (!isImageObject(image)) return getImageCropSettings(image);
    const current = getImageCropSettings(image);
    const next = {
      focalX: 'focalX' in patch ? clampNumber(patch.focalX, 0, 1, current.focalX) : current.focalX,
      focalY: 'focalY' in patch ? clampNumber(patch.focalY, 0, 1, current.focalY) : current.focalY,
      zoom: 'zoom' in patch ? clampNumber(patch.zoom, 1, 4, current.zoom) : current.zoom
    };
    image.set({
      layoutFocalX: next.focalX,
      layoutFocalY: next.focalY,
      layoutCropZoom: next.zoom
    });
    return next;
  }

  function rememberImageFrame(image, frame = null) {
    if (!isImageObject(image)) return null;
    const metrics = getObjectMetrics(image);
    const nextFrame = frame || {
      left: Number(image.left || 0),
      top: Number(image.top || 0),
      width: Math.max(1, Number(metrics.width || image.layoutFrameWidth || 1)),
      height: Math.max(1, Number(metrics.height || image.layoutFrameHeight || 1)),
      angle: Number(image.angle || 0)
    };
    image.__layoutFitFrame = { ...nextFrame };
    image.set({
      layoutFrameLeft: nextFrame.left,
      layoutFrameTop: nextFrame.top,
      layoutFrameWidth: nextFrame.width,
      layoutFrameHeight: nextFrame.height
    });
    return nextFrame;
  }

  function applyImageFit(image, mode = 'cover', frame = null) {
    if (!isImageObject(image)) return;
    const fit = ['cover', 'contain', 'stretch', 'original'].includes(mode) ? mode : 'cover';
    const nextFrame = frame || getImageFrame(image);
    rememberImageFrame(image, nextFrame);
    const crop = setImageCropSettings(image);
    const natural = getImageNaturalSize(image);
    const updates = {
      cropX: 0,
      cropY: 0,
      width: natural.width,
      height: natural.height,
      left: nextFrame.left,
      top: nextFrame.top,
      angle: nextFrame.angle || 0,
      objectFit: fit,
      layoutFrameLeft: nextFrame.left,
      layoutFrameTop: nextFrame.top,
      layoutFrameWidth: nextFrame.width,
      layoutFrameHeight: nextFrame.height,
      layoutFocalX: crop.focalX,
      layoutFocalY: crop.focalY,
      layoutCropZoom: crop.zoom
    };

    if (fit === 'cover') {
      const scale = Math.max(nextFrame.width / natural.width, nextFrame.height / natural.height) * crop.zoom;
      updates.width = Math.min(natural.width, nextFrame.width / scale);
      updates.height = Math.min(natural.height, nextFrame.height / scale);
      updates.cropX = Math.max(0, (natural.width - updates.width) * crop.focalX);
      updates.cropY = Math.max(0, (natural.height - updates.height) * crop.focalY);
      updates.scaleX = scale;
      updates.scaleY = scale;
    } else if (fit === 'contain') {
      const scale = Math.min(nextFrame.width / natural.width, nextFrame.height / natural.height);
      const displayWidth = natural.width * scale;
      const displayHeight = natural.height * scale;
      updates.left = nextFrame.left + (nextFrame.width - displayWidth) / 2;
      updates.top = nextFrame.top + (nextFrame.height - displayHeight) / 2;
      updates.scaleX = scale;
      updates.scaleY = scale;
    } else if (fit === 'stretch') {
      updates.scaleX = nextFrame.width / natural.width;
      updates.scaleY = nextFrame.height / natural.height;
    } else {
      updates.left = nextFrame.left + (nextFrame.width - natural.width) / 2;
      updates.top = nextFrame.top + (nextFrame.height - natural.height) / 2;
      updates.scaleX = 1;
      updates.scaleY = 1;
    }

    image.set(updates);
    image.setCoords?.();
  }

  function updateObjectMetricInputs(object = canvas?.getActiveObject(), options = {}) {
    const selectedObjects = options.forceSingle ? [] : getCustomSelectedLayerObjects();
    const isMulti = selectedObjects.length > 1;
    const hasObject = Boolean(object) || isMulti;
    const bounds = isMulti ? combinedObjectBounds(selectedObjects) : null;
    const metrics = isMulti && bounds
      ? { left: bounds.left, top: bounds.top, width: bounds.width, height: bounds.height, angle: 0, opacity: 100 }
      : getObjectMetrics(object);
    const fields = [
      [els.deskLayoutObjectXInput, metrics.left],
      [els.deskLayoutObjectYInput, metrics.top],
      [els.deskLayoutObjectWInput, metrics.width],
      [els.deskLayoutObjectHInput, metrics.height],
      [els.deskLayoutObjectAngleInput, metrics.angle],
      [els.deskLayoutObjectOpacityInput, metrics.opacity]
    ];
    fields.forEach(([input, value]) => {
      if (!input) return;
      input.value = formatInspectorNumber(value);
      input.disabled = !hasObject || isMulti;
    });
  }

  function updateImageCropInputs(object = canvas?.getActiveObject()) {
    const isImage = isImageObject(object);
    const crop = getImageCropSettings(object);
    [
      [els.deskLayoutImageFocalXInput, Math.round(crop.focalX * 100)],
      [els.deskLayoutImageFocalYInput, Math.round(crop.focalY * 100)],
      [els.deskLayoutImageCropZoomInput, Math.round(crop.zoom * 100)]
    ].forEach(([input, value]) => {
      if (!input) return;
      input.value = String(value);
      input.disabled = !isImage;
    });
    if (els.deskLayoutImageCropResetBtn) {
      els.deskLayoutImageCropResetBtn.disabled = !isImage;
    }
  }

  function getActiveArrangeObjects() {
    const selectedObjects = getCustomSelectedLayerObjects();
    const active = canvas?.getActiveObject();
    if (isGroupImageEditObject(active, selectedObjects)) return [active];
    if (selectedObjects.length > 1) return selectedObjects;
    if (!active) return [];
    if (active.type === 'activeSelection' && typeof active.getObjects === 'function') {
      return active.getObjects().filter(object => object && object.visible !== false);
    }
    return active.visible === false ? [] : [active];
  }

  function updateArrangeControls(object = canvas?.getActiveObject()) {
    const count = getActiveArrangeObjects().length;
    const hasObject = Boolean(object) || count > 0;
    document.querySelectorAll('[data-layout-object-align]').forEach(button => {
      button.disabled = !hasObject;
    });
    document.querySelectorAll('[data-layout-object-distribute]').forEach(button => {
      button.disabled = count < 3;
    });
    if (els.deskLayoutAlignScopeSelect) {
      els.deskLayoutAlignScopeSelect.disabled = !hasObject;
    }
  }

  function updateLayerActionControls() {
    const count = getActiveLayerObjects().length;
    const hasObject = count > 0;
    [
      els.deskLayoutCopyBtn,
      els.deskLayoutDuplicateBtn,
      els.deskLayoutDeleteBtn
    ].forEach(button => {
      if (button) button.disabled = !hasObject;
    });
    if (els.deskLayoutPasteBtn) {
      els.deskLayoutPasteBtn.disabled = !layoutClipboard?.objects?.length;
    }
    if (els.deskLayoutGroupBtn) {
      els.deskLayoutGroupBtn.disabled = count < 2;
    }
    if (els.deskLayoutUngroupBtn) {
      els.deskLayoutUngroupBtn.disabled = !getUngroupTargets().length;
    }
    [
      els.deskLayoutForwardBtn,
      els.deskLayoutBackwardBtn
    ].forEach(button => {
      if (button) button.disabled = count !== 1;
    });
  }

  function updateSelectionMeta(options = {}) {
    const root = els.deskLayoutSelectionMeta;
    const textEl = els.deskLayoutSelectionMetaText || root;
    const returnButton = els.deskLayoutReturnGroupBtn;
    if (!root || !textEl) return;
    const visible = Boolean(options.visible);
    const showButton = Boolean(options.canReturn || options.canExitIsolation);
    root.hidden = !visible;
    root.classList.toggle('is-deep-edit', Boolean(options.canReturn));
    root.classList.toggle('is-isolated', Boolean(options.isolationActive));
    if (!visible) {
      textEl.textContent = '';
      if (returnButton) returnButton.hidden = true;
      return;
    }
    if (options.canReturn && options.groupName && options.objectName) {
      textEl.innerHTML = `
        <strong>${escapeHtml(options.groupName)}</strong>
        <i>/</i>
        <b>${escapeHtml(options.objectName)}</b>
        <em>${escapeHtml(options.modeLabel || '编辑')}</em>
      `;
    } else {
      textEl.textContent = options.text || '';
    }
    if (returnButton) {
      returnButton.hidden = !showButton;
      returnButton.disabled = !showButton;
      returnButton.textContent = options.canReturn ? '返回组合' : '退出隔离';
    }
  }

  function returnToActiveGroupSelection() {
    if (!canvas) return;
    const active = canvas.getActiveObject();
    const selectedObjects = getCustomSelectedLayerObjects();
    const editTarget = getGroupImageEditTarget() || active || selectedObjects[0];
    const groupId = getSelectedGroupId(selectedObjects) || getLayerGroupId(editTarget);
    const group = groupId ? getGroupById(groupId) : null;
    const wasDeepEdit = Boolean(active?.isEditing || getGroupImageEditTarget());
    if (active?.isEditing && typeof active.exitEditing === 'function') {
      active.exitEditing();
    }
    clearGroupImageEditTarget();
    if (isolatedGroupId && !wasDeepEdit) {
      exitGroupIsolation();
      return;
    }
    if (group) {
      selectLayerGroup(group.id);
      setStatus(`已返回组合：${group.name || '组合图层'}`, '');
      return;
    }
    updateSelectionUi();
  }

  function updateSelectionUi() {
    if (!canvas || syncingSelection) return;
    let object = canvas.getActiveObject();
    const customSelectedObjects = getCustomSelectedLayerObjects();
    const selectedGroupId = customSelectedObjects.length > 1 ? getSelectedGroupId(customSelectedObjects) : '';
    const isolatedGroup = getIsolatedGroup();
    const selectedGroup = selectedGroupId ? getGroupById(selectedGroupId) : null;
    const objectGroup = isolatedGroup && object && getLayerGroupId(object) === isolatedGroup.id ? isolatedGroup : null;
    const metaGroup = selectedGroup || objectGroup;
    const imageEditTarget = getGroupImageEditTarget();
    const editingGroupObject = Boolean(
      metaGroup &&
      object &&
      (customSelectedObjects.includes(object) || isObjectInIsolatedGroup(object)) &&
      isTextObject(object) &&
      object.isEditing
    );
    let editingGroupImage = Boolean(
      metaGroup &&
      imageEditTarget &&
      (customSelectedObjects.includes(imageEditTarget) || isObjectInIsolatedGroup(imageEditTarget)) &&
      isImageObject(imageEditTarget) &&
      !metaGroup.locked &&
      !isLayerLocked(imageEditTarget)
    );
    if (editingGroupImage && object !== imageEditTarget) {
      syncingLayerSelection = true;
      try {
        canvas.setActiveObject(imageEditTarget);
      } finally {
        syncingLayerSelection = false;
      }
      object = imageEditTarget;
    }
    if (imageEditTarget && !editingGroupImage) {
      clearGroupImageEditTarget();
      editingGroupImage = false;
    }
    const isMulti = customSelectedObjects.length > 1 && !editingGroupObject && !editingGroupImage;
    const inspectedObject = (editingGroupObject || editingGroupImage) ? object : (isMulti ? null : object);
    const hasObject = Boolean(inspectedObject) || isMulti;
    const isText = isTextObject(inspectedObject);
    const isImage = isImageObject(inspectedObject);
    const templateFieldCount = renderTemplateControls();
    if (els.deskLayoutInspectorEmpty) {
      els.deskLayoutInspectorEmpty.hidden = hasObject || templateFieldCount > 0;
    }
    updateGroupSelectionBox(customSelectedObjects);
    const objectName = objectLabel(object, canvas.getObjects().indexOf(object));
    updateSelectionMeta({
      visible: hasObject,
      canReturn: editingGroupObject || editingGroupImage,
      canExitIsolation: Boolean(isolatedGroupId && !editingGroupObject && !editingGroupImage),
      isolationActive: Boolean(isolatedGroupId),
      groupName: metaGroup?.name || '',
      objectName,
      modeLabel: editingGroupImage ? '图片编辑' : (editingGroupObject ? '文字编辑' : ''),
      text: hasObject
        ? (isMulti
          ? (selectedGroup
            ? `${isGroupIsolated(selectedGroup.id) ? '隔离编辑' : '组合图层'} · ${selectedGroup.name}${selectedGroup.locked ? ' · 已锁定' : ''}`
            : `多选图层 · 已选 ${customSelectedObjects.length} 个图层`)
          : (isolatedGroup ? `隔离编辑 · ${isolatedGroup.name || '组合图层'} / ${objectName}` : `${objectKindLabel(object)} · ${objectName}`))
        : ''
    });
    if (els.deskLayoutTextControls) {
      els.deskLayoutTextControls.hidden = !isText;
    }
    if (els.deskLayoutImageControls) {
      els.deskLayoutImageControls.hidden = !isImage;
    }
    if (els.deskLayoutObjectControls) {
      els.deskLayoutObjectControls.hidden = !hasObject;
    }
    updateObjectMetricInputs(inspectedObject, { forceSingle: editingGroupObject || editingGroupImage });
    if (els.deskLayoutObjectToolbar) {
      els.deskLayoutObjectToolbar.hidden = !isText;
    }
    if (els.deskLayoutToolbarMeta) {
      els.deskLayoutToolbarMeta.textContent = isText ? objectLabel(object, canvas.getObjects().indexOf(object)) : '未选中';
    }
    if (els.deskLayoutBoldBtn) {
      const current = String(object?.fontWeight || '').toLowerCase();
      els.deskLayoutBoldBtn.classList.toggle('is-active', isText && (current === 'bold' || Number(current) >= 700));
    }
    if (els.deskLayoutTextInput) {
      els.deskLayoutTextInput.value = isText ? object.text || '' : '';
      els.deskLayoutTextInput.disabled = !isText;
    }
    if (els.deskLayoutFontFamilySelect) {
      const family = isText ? String(object.fontFamily || getDefaultTextFont()) : getDefaultTextFont();
      renderFontFamilyOptions(family);
      els.deskLayoutFontFamilySelect.value = family;
      els.deskLayoutFontFamilySelect.disabled = !isText;
      els.deskLayoutFontFamilySelect.style.fontFamily = fontCssStack(family);
    }
    if (els.deskLayoutFontWeightSelect) {
      renderFontWeightOptions(isText ? object.fontWeight : 400);
      els.deskLayoutFontWeightSelect.disabled = !isText;
    }
    if (els.deskLayoutFontSizeInput) {
      els.deskLayoutFontSizeInput.value = isText ? Math.round(object.fontSize || 48) : 48;
      els.deskLayoutFontSizeInput.disabled = !isText;
    }
    if (els.deskLayoutLineHeightInput) {
      els.deskLayoutLineHeightInput.value = isText ? formatCompactNumber(object.lineHeight || 1.16, 1.16) : '1.16';
      els.deskLayoutLineHeightInput.disabled = !isText;
    }
    if (els.deskLayoutCharSpacingInput) {
      els.deskLayoutCharSpacingInput.value = isText ? Math.round(Number(object.charSpacing || 0)) : 0;
      els.deskLayoutCharSpacingInput.disabled = !isText;
    }
    if (els.deskLayoutColorInput) {
      els.deskLayoutColorInput.value = isText && /^#[0-9a-f]{6}$/i.test(object.fill) ? object.fill : '#111827';
      els.deskLayoutColorInput.disabled = !isText;
    }
    if (els.deskLayoutImageFitSelect) {
      els.deskLayoutImageFitSelect.value = isImage ? (object.objectFit || 'cover') : 'cover';
      els.deskLayoutImageFitSelect.disabled = !isImage;
    }
    updateImageCropInputs(inspectedObject);
    updateArrangeControls(inspectedObject);
    updateLayerActionControls();
    if (els.deskLayoutReplaceImageBtn) {
      els.deskLayoutReplaceImageBtn.disabled = !isImage;
    }
    renderLayers();
  }

  function updateActiveText(patch) {
    if (!canvas) return;
    const object = canvas.getActiveObject();
    if (!object || !['i-text', 'text', 'textbox'].includes(object.type)) return;
    syncingSelection = true;
    Object.entries(patch).forEach(([key, value]) => object.set(key, value));
    if (Object.keys(patch).some(key => ['text', 'fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'charSpacing'].includes(key))) {
      refreshTextObjectMetrics(object);
    }
    syncingSelection = false;
    canvas.requestRenderAll();
    renderLayers();
    scheduleHistoryRecord('文本已修改');
  }

  function updateActiveObjectGeometry(patch) {
    if (!canvas) return;
    const object = canvas.getActiveObject();
    if (!object) return;
    const updates = {};
    const minSize = 1;

    if ('left' in patch) updates.left = Math.round(Number(patch.left) || 0);
    if ('top' in patch) updates.top = Math.round(Number(patch.top) || 0);
    if ('angle' in patch) updates.angle = clampNumber(patch.angle, -360, 360, 0);
    if ('opacity' in patch) updates.opacity = clampNumber(patch.opacity, 0, 100, 100) / 100;

    if ('width' in patch) {
      const targetWidth = Math.max(minSize, Number(patch.width) || minSize);
      const baseWidth = Math.max(minSize, Number(object.width || 0) || minSize);
      updates.scaleX = targetWidth / baseWidth;
    }
    if ('height' in patch) {
      const targetHeight = Math.max(minSize, Number(patch.height) || minSize);
      const baseHeight = Math.max(minSize, Number(object.height || 0) || minSize);
      updates.scaleY = targetHeight / baseHeight;
    }

    syncingSelection = true;
    object.set(updates);
    if (isImageObject(object) && ['left', 'top', 'width', 'height', 'angle'].some(key => key in patch)) {
      const nextFrame = rememberImageFrame(object);
      if ('width' in patch || 'height' in patch) {
        applyImageFit(object, object.objectFit || 'cover', nextFrame);
      }
    }
    refreshTextObjectMetrics(object);
    object.setCoords?.();
    syncingSelection = false;
    canvas.requestRenderAll();
    updateObjectMetricInputs(object);
    renderLayers();
    scheduleHistoryRecord('图层属性已修改');
  }

  function getArrangeScopeBounds() {
    const width = canvas?.getWidth?.() || activeProjectMeta?.width || 1080;
    const height = canvas?.getHeight?.() || activeProjectMeta?.height || 1440;
    const scope = els.deskLayoutAlignScopeSelect?.value || 'canvas';
    const margin = scope === 'safe' ? getSafeMargin() : 0;
    return {
      left: margin,
      top: margin,
      right: width - margin,
      bottom: height - margin,
      centerX: width / 2,
      centerY: height / 2,
      width: width - margin * 2,
      height: height - margin * 2
    };
  }

  function combinedObjectBounds(objects) {
    const bounds = (objects || []).map(objectBounds).filter(Boolean);
    if (!bounds.length) return null;
    const left = Math.min(...bounds.map(item => item.left));
    const top = Math.min(...bounds.map(item => item.top));
    const right = Math.max(...bounds.map(item => item.right));
    const bottom = Math.max(...bounds.map(item => item.bottom));
    return {
      left,
      top,
      right,
      bottom,
      centerX: left + (right - left) / 2,
      centerY: top + (bottom - top) / 2,
      width: right - left,
      height: bottom - top
    };
  }

  function beginArrangeMutation() {
    const selectedObjects = getCustomSelectedLayerObjects();
    const active = canvas?.getActiveObject();
    if (isGroupImageEditObject(active, selectedObjects)) {
      return { objects: [active], isSelection: false };
    }
    if (selectedObjects.length > 1) {
      return { objects: selectedObjects, isSelection: true };
    }
    const isSelection = active?.type === 'activeSelection' && typeof active.getObjects === 'function';
    const objects = isSelection ? active.getObjects().filter(Boolean) : (active ? [active] : []);
    if (isSelection) canvas.discardActiveObject();
    return { objects, isSelection };
  }

  function finishArrangeMutation(objects, preferSelection = false) {
    (objects || []).forEach(object => {
      if (isImageObject(object)) rememberImageFrame(object);
      if (isTextObject(object)) refreshTextObjectMetrics(object);
      object.setCoords?.();
    });
    const canvasObjects = canvas?.getObjects?.() || [];
    const groupImageEditObject = objects.length === 1 && getGroupImageEditTarget() === objects[0] ? objects[0] : null;
    const groupImageEditGroup = groupImageEditObject ? getGroupById(getLayerGroupId(groupImageEditObject)) : null;
    if (preferSelection && objects.length > 1) {
      selectedLayerIndices = objects
        .map(object => canvasObjects.indexOf(object))
        .filter(index => index >= 0);
      syncingLayerSelection = true;
      try {
        canvas.discardActiveObject();
        canvas.setActiveObject(objects[0]);
      } finally {
        syncingLayerSelection = false;
      }
    } else if (groupImageEditGroup) {
      selectedLayerIndices = groupImageEditGroup.indices.slice();
      syncingLayerSelection = true;
      try {
        canvas.discardActiveObject();
        canvas.setActiveObject(groupImageEditObject);
      } finally {
        syncingLayerSelection = false;
      }
    } else if (objects.length === 1) {
      selectedLayerIndices = [];
      canvas.setActiveObject(objects[0]);
    }
    canvas.requestRenderAll();
    updateObjectMetricInputs(canvas.getActiveObject(), { forceSingle: Boolean(groupImageEditGroup) });
    updateSelectionUi();
  }

  function moveArrangedObject(object, dx, dy) {
    object.set({
      left: Number(object.left || 0) + dx,
      top: Number(object.top || 0) + dy
    });
  }

  function nudgeActiveObjects(dx, dy) {
    if (!canvas || (!dx && !dy)) return false;
    if (historyTimer && pendingHistoryLabel !== '图层已微调') flushPendingHistory();
    const { objects, isSelection } = beginArrangeMutation();
    const movableObjects = objects.filter(object => object && object.visible !== false && !isLayerLocked(object));
    if (!movableObjects.length) {
      finishArrangeMutation(objects, isSelection);
      if (objects.length) {
        setStatus(objects.length > 1 ? '组合已锁定，先解锁后再移动' : '图层已锁定，先解锁后再移动', '');
      }
      return false;
    }
    if (!historyTimer) refreshCurrentHistorySnapshot();
    movableObjects.forEach(object => moveArrangedObject(object, dx, dy));
    finishArrangeMutation(objects, isSelection);
    scheduleHistoryRecord('图层已微调');
    setStatus(`图层已微调 ${Math.abs(dx || dy)}px，记得保存`, '');
    return true;
  }

  function alignActiveObjects(mode) {
    if (!canvas) return;
    flushPendingHistory();
    const { objects, isSelection } = beginArrangeMutation();
    if (!objects.length) {
      updateArrangeControls();
      return;
    }
    const bounds = combinedObjectBounds(objects);
    const scope = getArrangeScopeBounds();
    if (!bounds) return;
    refreshCurrentHistorySnapshot();
    let dx = 0;
    let dy = 0;
    if (mode === 'left') dx = scope.left - bounds.left;
    if (mode === 'hcenter') dx = scope.centerX - bounds.centerX;
    if (mode === 'right') dx = scope.right - bounds.right;
    if (mode === 'top') dy = scope.top - bounds.top;
    if (mode === 'vcenter') dy = scope.centerY - bounds.centerY;
    if (mode === 'bottom') dy = scope.bottom - bounds.bottom;
    if (!dx && !dy) {
      finishArrangeMutation(objects, isSelection);
      return;
    }
    objects.forEach(object => moveArrangedObject(object, dx, dy));
    finishArrangeMutation(objects, isSelection);
    recordHistory('图层已对齐');
  }

  function distributeActiveObjects(axis) {
    if (!canvas) return;
    flushPendingHistory();
    const { objects, isSelection } = beginArrangeMutation();
    if (objects.length < 3) {
      finishArrangeMutation(objects, isSelection);
      setStatus('至少选择 3 个图层才能等距分布', 'error');
      return;
    }
    const items = objects
      .map(object => ({ object, bounds: objectBounds(object) }))
      .filter(item => item.bounds);
    if (items.length < 3) return;
    refreshCurrentHistorySnapshot();
    const keyStart = axis === 'vertical' ? 'top' : 'left';
    const keySize = axis === 'vertical' ? 'height' : 'width';
    items.sort((a, b) => a.bounds[keyStart] - b.bounds[keyStart]);
    const first = items[0].bounds[keyStart];
    const lastItem = items[items.length - 1];
    const lastEnd = lastItem.bounds[keyStart] + lastItem.bounds[keySize];
    const totalSize = items.reduce((sum, item) => sum + item.bounds[keySize], 0);
    const gap = (lastEnd - first - totalSize) / (items.length - 1);
    let cursor = first;
    items.forEach((item, index) => {
      const target = index === 0 ? item.bounds[keyStart] : cursor;
      const delta = target - item.bounds[keyStart];
      if (axis === 'vertical') moveArrangedObject(item.object, 0, delta);
      else moveArrangedObject(item.object, delta, 0);
      cursor = target + item.bounds[keySize] + gap;
    });
    finishArrangeMutation(objects, isSelection);
    recordHistory(axis === 'vertical' ? '图层已纵向等距' : '图层已横向等距');
  }

  async function updateActiveTextFont(family) {
    const object = canvas?.getActiveObject();
    if (!object || !isTextObject(object)) return;
    const nextFamily = String(family || getDefaultTextFont()).trim();
    const weight = normalizeFontWeight(object.fontWeight);
    if (els.deskLayoutFontFamilySelect) {
      els.deskLayoutFontFamilySelect.style.fontFamily = fontCssStack(nextFamily);
    }
    await loadFontFamily(nextFamily, weight, object.text || '排版字体Aa123');
    updateActiveText({ fontFamily: nextFamily });
    refreshTextObjectMetrics(object);
    canvas?.renderAll();
  }

  async function updateActiveTextWeight(weight) {
    const object = canvas?.getActiveObject();
    if (!object || !isTextObject(object)) return;
    const nextWeight = normalizeFontWeight(weight);
    const family = String(object.fontFamily || getDefaultTextFont()).trim();
    await loadFontFamily(family, nextWeight, object.text || '排版字体Aa123');
    updateActiveText({ fontWeight: nextWeight });
    updateSelectionUi();
  }

  function addText() {
    const width = canvas?.getWidth?.() || 1080;
    const height = canvas?.getHeight?.() || 1440;
    const object = new fabric.IText('新文本', {
      left: Math.round(width * 0.08),
      top: Math.round(height * 0.12),
      fontFamily: els.deskLayoutFontFamilySelect?.value || getDefaultTextFont(),
      fontSize: Math.max(28, Math.round(width * 0.052)),
      fill: '#111827',
      name: '新文本'
    });
    assignObjectToIsolatedGroup(object);
    canvas.add(object);
    canvas.setActiveObject(object);
    loadFontFamily(object.fontFamily, object.fontWeight || 400, object.text).then(() => {
      refreshTextObjectMetrics(object);
      canvas?.requestRenderAll();
    });
    canvas.requestRenderAll();
    updateSelectionUi();
    recordHistory('已添加文本');
  }

  function getSourceKey(source) {
    return source?.id || source?.sourceNodeId || source?.imageUrl || source?.url || source?.name || source?.asset_url || '';
  }

  async function resolveImageSrc(src) {
    const raw = String(src || '');
    if (!raw || raw.startsWith('data:')) return raw;
    if (window.DesktopApi?.imageUrlToDataUri) {
      try {
        const dataUrl = await DesktopApi.imageUrlToDataUri(raw);
        if (dataUrl) return dataUrl;
      } catch (error) {
        console.warn('[LayoutEditor] image auth fetch failed, falling back to direct URL:', error.message);
      }
    }
    return raw;
  }

  async function imageFromSourceUrl(src) {
    const resolvedSrc = await resolveImageSrc(src);
    if (!resolvedSrc) return null;
    return new Promise(resolve => {
      const element = new Image();
      element.onload = async () => {
        try {
          await element.decode?.();
        } catch (error) {
          // Some browsers resolve onload after decode enough for drawing.
        }
        resolve(new fabric.Image(element));
      };
      element.onerror = () => resolve(null);
      element.src = resolvedSrc;
    });
  }

  function renderCanvasImmediately() {
    if (!canvas) return Promise.resolve();
    canvas.calcOffset?.();
    canvas.renderAll();
    return new Promise(resolve => {
      requestAnimationFrame(() => {
        canvas?.renderAll();
        resolve();
      });
    });
  }

  async function commitImageLayerRender(image) {
    if (image) {
      image.dirty = true;
      image.setCoords?.();
    }
    await renderCanvasImmediately();
  }

  async function updateActiveImageFit(mode) {
    const image = canvas?.getActiveObject();
    if (!isImageObject(image)) return;
    if (!canEditImageObject(image)) return;
    const currentFrame = getImageFrame(image);
    const nextMode = ['cover', 'contain', 'stretch', 'original'].includes(mode) ? mode : 'cover';
    const frame = image.__layoutFitFrame || currentFrame;
    if (nextMode === 'original') {
      image.__layoutFitFrame = { ...currentFrame };
    }
    applyImageFit(image, nextMode, frame);
    await commitImageLayerRender(image);
    updateObjectMetricInputs(image);
    renderLayers();
    updateSelectionUi();
    recordHistory('图片适配已更新');
    setStatus('图片适配已更新，记得保存', '');
  }

  async function updateActiveImageCrop(patch = {}) {
    const image = canvas?.getActiveObject();
    if (!isImageObject(image)) return;
    if (!canEditImageObject(image)) return;
    const frame = image.__layoutFitFrame || getImageFrame(image);
    setImageCropSettings(image, patch);
    applyImageFit(image, 'cover', frame);
    await commitImageLayerRender(image);
    updateImageCropInputs(image);
    updateObjectMetricInputs(image);
    if (els.deskLayoutImageFitSelect) els.deskLayoutImageFitSelect.value = 'cover';
    renderLayers();
    updateSelectionUi();
    scheduleHistoryRecord('图片裁剪已更新');
    setStatus('图片裁剪已更新，记得保存', '');
  }

  async function resetActiveImageCrop() {
    const image = canvas?.getActiveObject();
    if (!isImageObject(image)) return;
    if (!canEditImageObject(image)) return;
    const frame = image.__layoutFitFrame || getImageFrame(image);
    setImageCropSettings(image, { focalX: 0.5, focalY: 0.5, zoom: 1 });
    applyImageFit(image, 'cover', frame);
    await commitImageLayerRender(image);
    updateImageCropInputs(image);
    updateObjectMetricInputs(image);
    if (els.deskLayoutImageFitSelect) els.deskLayoutImageFitSelect.value = 'cover';
    renderLayers();
    updateSelectionUi();
    recordHistory('图片裁剪已重置');
    setStatus('图片裁剪已重置，记得保存', '');
  }

  async function replaceImageObject(target, source) {
    if (!isImageObject(target) || !canvas) return false;
    const src = source?.imageData || source?.base64 || source?.imageUrl || source?.url || '';
    if (!src) return false;
    const image = await imageFromSourceUrl(src);
    if (!image || !image.width || !image.height) return false;

    const layerIndex = canvas.getObjects().indexOf(target);
    const fit = target.objectFit || 'cover';
    const frame = getImageFrame(target);
    const wasEditingGroupImage = getGroupImageEditTarget() === target;
    const wasLocked = isLayerLocked(target);
    image.set({
      opacity: target.opacity ?? 1,
      name: source.name || target.name || '图片',
      layoutRole: target.layoutRole || 'freeImage',
      layoutVariable: target.layoutVariable || '',
      layoutSourceId: getSourceKey(source) || target.layoutSourceId || '',
      sourceNodeId: source.sourceNodeId || target.sourceNodeId || '',
      sourceImageUrl: source.imageUrl || source.url || target.sourceImageUrl || '',
      layoutGroupId: target.layoutGroupId || '',
      layoutGroupName: target.layoutGroupName || '',
      layoutLocked: wasLocked
    });
    applyImageFit(image, fit, frame);
    applyLayerLock(image, wasLocked);
    canvas.remove(target);
    canvas.add(image);
    if (layerIndex >= 0) canvas.moveTo(image, layerIndex);
    if (wasEditingGroupImage) setGroupImageEditTarget(image);
    canvas.setActiveObject(image);
    await commitImageLayerRender(image);
    renderLayers();
    renderTemplateControls();
    updateSelectionUi();
    return image;
  }

  function getAvailableImagePlaceholders() {
    if (!canvas) return [];
    return canvas.getObjects().filter(object => (
      object?.isTemplatePlaceholder === true
      && String(object.layoutRole || '').startsWith('heroImage')
      && !object.layoutSourceId
    ));
  }

  function removeHeroPlaceholderLabels() {
    canvas.getObjects()
      .filter(object => object.layoutRole === 'placeholderLabel')
      .forEach(object => canvas.remove(object));
  }

  async function fillImagePlaceholder(source, placeholder) {
    const src = source?.imageData || source?.base64 || source?.imageUrl || source?.url || '';
    if (!src || !placeholder) return false;
    const image = await imageFromSourceUrl(src);
    if (!image || !image.width || !image.height) return false;

    const targetWidth = Math.max(1, placeholder.getScaledWidth ? placeholder.getScaledWidth() : placeholder.width || 1);
    const targetHeight = Math.max(1, placeholder.getScaledHeight ? placeholder.getScaledHeight() : placeholder.height || 1);
    const placeholderIndex = canvas.getObjects().indexOf(placeholder);
    const sourceKey = getSourceKey(source);

    image.set({
      left: placeholder.left,
      top: placeholder.top,
      angle: placeholder.angle || 0,
      name: source.name || placeholder.name?.replace('占位', '图片') || '模板图片',
      layoutRole: placeholder.layoutRole || 'heroImage',
      layoutVariable: placeholder.layoutVariable || '',
      layoutSourceId: sourceKey,
      sourceNodeId: source.sourceNodeId || '',
      sourceImageUrl: source.imageUrl || source.url || '',
      opacity: placeholder.opacity ?? 1
    });
    applyImageFit(image, placeholder.objectFit || 'cover', {
      left: Number(placeholder.left || 0),
      top: Number(placeholder.top || 0),
      width: targetWidth,
      height: targetHeight,
      angle: Number(placeholder.angle || 0)
    });

    canvas.remove(placeholder);
    canvas.add(image);
    if (placeholderIndex >= 0) canvas.moveTo(image, placeholderIndex);
    if (String(image.layoutRole || '').startsWith('heroImage')) {
      removeHeroPlaceholderLabels();
    }
    canvas.setActiveObject(image);
    await commitImageLayerRender(image);
    renderLayers();
    updateSelectionUi();
    return true;
  }

  async function replaceTemplateImageFile(variable, file) {
    if (!file || !file.type.startsWith('image/')) return false;
    const target = findTemplateImageTarget(variable);
    if (!target) {
      setStatus('当前模板没有这个图片字段', 'error');
      return false;
    }
    const draftId = await ensureDraftForActiveNode();
    const uploaded = await DesktopApi.uploadLayoutAsset(draftId, file);
    const imageUrl = DesktopApi.addCacheBuster(uploaded.asset_url, Date.now());
    const ok = await fillImagePlaceholder({
      id: uploaded.asset_id || uploaded.filename || file.name,
      url: imageUrl,
      imageUrl,
      name: file.name || uploaded.filename || templateFieldLabel(variable)
    }, target);
    if (ok) {
      persistActivePage({ thumbnail: true });
      renderPages(activeProjectMeta);
      renderTemplateControls();
      recordHistory(`${templateFieldLabel(variable)}已替换`);
      setStatus(`${templateFieldLabel(variable)}已替换，记得保存`, 'saved');
    }
    return ok;
  }

  async function replaceActiveImageFile(file) {
    if (!file || !file.type.startsWith('image/')) return false;
    const target = canvas?.getActiveObject();
    if (!isImageObject(target)) {
      setStatus('请先选中一个图片图层', 'error');
      return false;
    }
    if (!canEditImageObject(target)) return false;
    const draftId = await ensureDraftForActiveNode();
    const uploaded = await DesktopApi.uploadLayoutAsset(draftId, file);
    const imageUrl = DesktopApi.addCacheBuster(uploaded.asset_url, Date.now());
    const ok = await replaceImageObject(target, {
      id: uploaded.asset_id || uploaded.filename || file.name,
      url: imageUrl,
      imageUrl,
      name: file.name || uploaded.filename || target.name || '图片'
    });
    if (ok) {
      persistActivePage({ thumbnail: true });
      renderPages(activeProjectMeta);
      recordHistory('当前图片已替换');
      setStatus('当前图片已替换，记得保存', 'saved');
    }
    return ok;
  }

  async function addFabricImageFromSource(source, index = 0) {
    const placeholder = getAvailableImagePlaceholders()[index] || getAvailableImagePlaceholders()[0];
    if (placeholder && await fillImagePlaceholder(source, placeholder)) return true;

    const src = source?.imageData || source?.base64 || source?.imageUrl || source?.url || '';
    if (!src) return false;
    const image = await imageFromSourceUrl(src);
    if (!image || !image.width || !image.height) return false;
    const maxWidth = canvas.getWidth() * 0.74;
    const maxHeight = canvas.getHeight() * 0.62;
    const scale = Math.min(maxWidth / image.width, maxHeight / image.height, 1);
    const offset = Math.min(index, 5) * 18;
    const frame = {
      left: Math.max(20, (canvas.getWidth() - image.width * scale) / 2 + offset),
      top: Math.max(72, 112 + offset),
      width: image.width * scale,
      height: image.height * scale,
      angle: 0
    };
    image.set({
      name: source.name || `输入图片 ${index + 1}`,
      layoutRole: 'freeImage',
      layoutSourceId: getSourceKey(source),
      sourceNodeId: source.sourceNodeId || '',
      sourceImageUrl: source.imageUrl || source.url || ''
    });
    assignObjectToIsolatedGroup(image);
    applyImageFit(image, 'contain', frame);
    canvas.add(image);
    canvas.setActiveObject(image);
    await commitImageLayerRender(image);
    renderLayers();
    updateSelectionUi();
    return true;
  }

  async function importConnectedImages(node) {
    if (!node || !canvas || !window.DesktopCanvas?.getLayoutInputImages) return 0;
    migrateTemplateObjects();
    const sources = DesktopCanvas.getLayoutInputImages(node.id) || [];
    if (!sources.length) return 0;
    const existing = new Set(canvas.getObjects()
      .map(object => object.layoutSourceId)
      .filter(Boolean));
    let imported = 0;
    for (const source of sources) {
      const key = source.id || source.sourceNodeId || source.imageUrl || source.url || source.name;
      if (!key) continue;
      if (existing.has(key)) {
        const placeholders = getAvailableImagePlaceholders();
        if (!placeholders.length) continue;
        canvas.getObjects()
          .filter(object => object.layoutSourceId === key && object.type === 'image' && !String(object.layoutRole || '').startsWith('heroImage'))
          .forEach(object => canvas.remove(object));
      }
      const ok = await addFabricImageFromSource({ ...source, id: key }, imported);
      if (ok) {
        existing.add(key);
        imported += 1;
      }
    }
    if (imported) {
      await renderCanvasImmediately();
      persistActivePage({ thumbnail: true });
      renderPages(activeProjectMeta);
      renderLayers();
      updateSelectionUi();
    }
    return imported;
  }

  async function addImageFile(file) {
    if (!file || !file.type.startsWith('image/')) return;
    const draftId = await ensureDraftForActiveNode();
    const uploaded = await DesktopApi.uploadLayoutAsset(draftId, file);
    const imageUrl = DesktopApi.addCacheBuster(uploaded.asset_url, Date.now());
    await addFabricImageFromSource({
      id: uploaded.asset_id || uploaded.filename || file.name,
      url: imageUrl,
      imageUrl,
      name: file.name || uploaded.filename || '图片'
    });
    recordHistory('已添加图片');
  }

  async function createLayoutFromSelection() {
    const node = getActiveNode();
    if (!node) return;
    const preset = getPreset(selectedPresetId);
    const template = getTemplate(selectedTemplateId);
    const project = createProject(preset.id, template.id);
    node.layoutProject = project;
    node.layoutPresetId = preset.id;
    node.layoutTemplateId = template.id;
    node.layoutPresetLabel = preset.name;
    node.layoutTitle = `${preset.name} · ${template.name}`;
    delete node.layoutDraftId;
    DesktopState.saveSettings();
    DesktopCanvas.refreshLayoutNode?.(node.id);
    hideCreatePanel();
    if (els.deskLayoutTitle) els.deskLayoutTitle.textContent = node.layoutTitle;
    await loadProject(node);
    const imported = await importConnectedImages(node);
    resetHistory();
    setStatus(imported ? `已创建画布，并导入 ${imported} 张连接图片` : '画布已创建，记得保存', imported ? 'saved' : '');
  }

  async function syncConnectedImages(nodeId) {
    if (!nodeId || nodeId !== activeNodeId || !canvas) return 0;
    const node = getActiveNode();
    const imported = await importConnectedImages(node);
    if (imported) {
      recordHistory('已导入连接图片');
      setStatus(`已导入 ${imported} 张连接图片，记得保存`, 'saved');
    }
    return imported;
  }

  async function open(nodeId, options = {}) {
    activeNodeId = nodeId;
    const node = getActiveNode();
    if (!node || node.type !== 'layout') {
      DesktopResults.showTransientMessage('请先选择排版节点。');
      return;
    }
    await ensureLayoutFonts();
    els.deskLayoutEditor?.classList.add('is-open');
    els.deskLayoutEditor?.setAttribute('aria-hidden', 'false');
    if (els.deskLayoutTitle) els.deskLayoutTitle.textContent = node.layoutTitle || '排版工作区';
    setStatus(node.layoutDraftId ? '正在加载草稿...' : '未保存', node.layoutDraftId ? 'saving' : '');
    await refreshDraftList(node.layoutDraftId || '');
    if (!hasEditableProject(node)) {
      if (isLegacyTestProject(node.layoutProject)) delete node.layoutProject;
      activeProjectMeta = null;
      if (canvas) {
        canvas.clear();
        canvas.discardActiveObject();
        canvas.requestRenderAll();
      }
      renderPages(defaultProject());
      renderLayers();
      updateSelectionUi();
      resetHistory();
      showCreatePanel();
      return;
    }
    hideCreatePanel();
    await loadProject(node);
    const imported = await importConnectedImages(node);
    resetHistory();
    if (imported) {
      setStatus(`已导入 ${imported} 张连接图片，记得保存`, 'saved');
    } else {
      setStatus(node.layoutDraftId ? '草稿已加载' : '未保存', node.layoutDraftId ? 'saved' : '');
    }
    if (options.exportOnOpen) {
      requestAnimationFrame(() => {
        saveToNode().catch(error => DesktopResults.showError(error));
      });
    }
  }

  function close() {
    flushPendingHistory();
    exitGroupIsolation({ silent: true, skipUi: true, keepSelection: true });
    els.deskLayoutEditor?.classList.remove('is-open');
    els.deskLayoutEditor?.setAttribute('aria-hidden', 'true');
    activeNodeId = '';
    resetHistory({ empty: true });
  }

  async function loadSelectedDraft() {
    const node = getActiveNode();
    const draftId = els.deskLayoutDraftSelect?.value || '';
    if (!node || !draftId) {
      setStatus('请选择一个草稿', 'error');
      return;
    }
    setStatus('加载草稿中...', 'saving');
    node.layoutDraftId = draftId;
    delete node.layoutProject;
    hideCreatePanel();
    await loadProject(node);
    const imported = await importConnectedImages(node);
    resetHistory();
    if (els.deskLayoutTitle) els.deskLayoutTitle.textContent = node.layoutTitle || '排版工作区';
    setStatus(imported ? `草稿已加载，并导入 ${imported} 张连接图片` : '草稿已加载', 'saved');
  }

  async function exportImage() {
    const node = getActiveNode();
    if (!node || !canvas) return;
    await saveToNode();
    if (!node.layoutDraftId) throw new Error('草稿保存失败，无法导出');
    setStatus('导出到最近记录...', 'saving');
    if (els.deskLayoutExportBtn) {
      els.deskLayoutExportBtn.disabled = true;
      els.deskLayoutExportBtn.textContent = '导出中';
    }
    try {
      await ensureCanvasFontsLoaded(canvas);
      const dataUrl = withIsolationVisualsSuspended(() => canvas.toDataURL({
        format: 'png',
        multiplier: 1,
        enableRetinaScaling: true
      }));
      const item = await DesktopApi.publishLayoutDraft({
        draftId: node.layoutDraftId,
        title: node.layoutTitle || '排版导出',
        prompt: node.layoutTitle || '排版导出',
        nodeId: node.id,
        dataUrl
      });
      node.layoutExport = item.primary_image_path || item.image_paths?.[0] || node.layoutExport;
      node.layoutPreview = node.layoutExport || node.layoutPreview;
      DesktopState.saveSettings();
      DesktopCanvas.refreshLayoutNode?.(node.id);
      await window.DesktopHistory?.loadHistory?.();
      setStatus('已导出到最近记录', 'saved');
    } catch (error) {
      setStatus(`导出失败：${error.message}`, 'error');
      throw error;
    } finally {
      if (els.deskLayoutExportBtn) {
        els.deskLayoutExportBtn.disabled = false;
        els.deskLayoutExportBtn.textContent = '导出到历史';
      }
    }
  }

  function bindEvents() {
    els.deskLayoutCloseBtn?.addEventListener('click', close);
    els.deskLayoutLayersCollapseBtn?.addEventListener('click', toggleLayersPanel);
    els.deskLayoutPageList?.addEventListener('click', event => {
      if (event.target.closest('[data-page-name-input]')) return;
      const action = event.target.closest('[data-page-action]');
      if (action) {
        const type = action.dataset.pageAction;
        if (type === 'add') addPage().catch(error => DesktopResults.showError(error));
        if (type === 'duplicate') duplicatePage().catch(error => DesktopResults.showError(error));
        if (type === 'rename') startPageRename(activePageId);
        if (type === 'delete') deletePage().catch(error => DesktopResults.showError(error));
        return;
      }
      const button = event.target.closest('[data-page-id]');
      if (!button) return;
      switchPage(button.dataset.pageId).catch(error => DesktopResults.showError(error));
    });
    els.deskLayoutPageList?.addEventListener('dblclick', event => {
      const button = event.target.closest('[data-page-id]');
      if (!button || event.target.closest('[data-page-name-input]')) return;
      startPageRename(button.dataset.pageId);
    });
    els.deskLayoutPageList?.addEventListener('keydown', event => {
      const input = event.target.closest('[data-page-name-input]');
      if (!input) return;
      if (event.key === 'Enter') {
        event.preventDefault();
        commitPageRename(input);
      } else if (event.key === 'Escape') {
        renamingPageId = null;
        renderPages(activeProjectMeta);
      }
    });
    els.deskLayoutPageList?.addEventListener('focusout', event => {
      const input = event.target.closest('[data-page-name-input]');
      if (input) commitPageRename(input);
    });
    els.deskLayoutTemplateBtn?.addEventListener('click', showCreatePanel);
    els.deskLayoutFitBtn?.addEventListener('click', fitStageToView);
    els.deskLayoutSafeAreaBtn?.addEventListener('click', () => {
      const settings = getAssistSettings();
      settings.showSafeArea = !settings.showSafeArea;
      updateAssistUi();
      recordHistory(settings.showSafeArea ? '安全边距已显示' : '安全边距已隐藏');
      setStatus(settings.showSafeArea ? '安全边距已显示，记得保存' : '安全边距已隐藏，记得保存', '');
    });
    els.deskLayoutSnapBtn?.addEventListener('click', () => {
      const settings = getAssistSettings();
      settings.snapEnabled = !settings.snapEnabled;
      if (!settings.snapEnabled) hideLayoutGuides();
      updateAssistUi();
      recordHistory(settings.snapEnabled ? '吸附参考线已开启' : '吸附参考线已关闭');
      setStatus(settings.snapEnabled ? '吸附参考线已开启，记得保存' : '吸附参考线已关闭，记得保存', '');
    });
    els.deskLayoutUndoBtn?.addEventListener('click', () => {
      undoLayoutEdit().catch(error => DesktopResults.showError(error));
    });
    els.deskLayoutRedoBtn?.addEventListener('click', () => {
      redoLayoutEdit().catch(error => DesktopResults.showError(error));
    });
    els.deskLayoutZoomSelect?.addEventListener('change', event => {
      const value = event.target.value;
      if (value === 'fit') fitStageToView();
      else applyStageZoom(Number(value), value);
    });
    els.deskLayoutPresetList?.addEventListener('click', event => {
      const button = event.target.closest('[data-preset-id]');
      if (!button) return;
      selectedPresetId = button.dataset.presetId;
      const templates = getTemplatesForPreset(selectedPresetId);
      selectedTemplateId = templates[0]?.id || 'blank';
      renderCreateOptions();
    });
    els.deskLayoutTemplateList?.addEventListener('click', event => {
      const button = event.target.closest('[data-template-id]');
      if (!button) return;
      selectedTemplateId = button.dataset.templateId;
      renderCreateOptions();
    });
    els.deskLayoutCreateBtn?.addEventListener('click', () => {
      createLayoutFromSelection().catch(error => DesktopResults.showError(error));
    });
    els.deskLayoutSaveBtn?.addEventListener('click', () => {
      saveToNode()
        .then(() => DesktopResults.showTransientMessage('排版已保存到后端草稿。'))
        .catch(error => DesktopResults.showError(error));
    });
    els.deskLayoutExportBtn?.addEventListener('click', () => exportImage().catch(error => DesktopResults.showError(error)));
    els.deskLayoutLoadBtn?.addEventListener('click', () => loadSelectedDraft().catch(error => {
      setStatus(`加载失败：${error.message}`, 'error');
      DesktopResults.showError(error);
    }));
    els.deskLayoutDraftSelect?.addEventListener('change', () => {
      if (els.deskLayoutDraftSelect.value) setStatus('选择后点击加载', '');
    });
    els.deskLayoutAddTextBtn?.addEventListener('click', addText);
    els.deskLayoutAddImageBtn?.addEventListener('click', () => {
      pendingTemplateImageVariable = '';
      pendingImageReplacement = false;
      els.deskLayoutImageInput?.click();
    });
    els.deskLayoutImageInput?.addEventListener('change', event => {
      const file = event.target.files?.[0];
      const templateVariable = pendingTemplateImageVariable;
      const replaceActiveImage = pendingImageReplacement;
      pendingTemplateImageVariable = '';
      pendingImageReplacement = false;
      if (templateVariable) {
        replaceTemplateImageFile(templateVariable, file).catch(error => DesktopResults.showError(error));
      } else if (replaceActiveImage) {
        replaceActiveImageFile(file).catch(error => DesktopResults.showError(error));
      } else {
        addImageFile(file).catch(error => DesktopResults.showError(error));
      }
      event.target.value = '';
    });
    els.deskLayoutTemplateFields?.addEventListener('input', event => {
      const input = event.target.closest('[data-template-text-var]');
      if (!input) return;
      updateTemplateTextVariable(input.dataset.templateTextVar, input.value);
    });
    els.deskLayoutTemplateFields?.addEventListener('focusin', event => {
      const input = event.target.closest('[data-template-text-var]');
      if (input) focusTemplateObject(input.dataset.templateTextVar);
    });
    els.deskLayoutTemplateFields?.addEventListener('click', event => {
      const button = event.target.closest('[data-template-image-var]');
      if (!button) return;
      pendingTemplateImageVariable = button.dataset.templateImageVar || '';
      pendingImageReplacement = false;
      els.deskLayoutImageInput?.click();
    });
    els.deskLayoutLayerList?.addEventListener('click', event => {
      if (!canvas || event.target.closest('[data-layer-name-input], [data-layer-group-name-input]')) return;
      const groupRow = event.target.closest('.desk-layout-layer[data-layer-group-id]');
      if (groupRow) {
        const groupId = groupRow.dataset.layerGroupId || '';
        if (isolatedGroupId && groupId !== isolatedGroupId) {
          warnIsolationLocked();
          return;
        }
        if (event.target.closest('[data-layer-group-toggle]')) {
          toggleLayerGroupCollapsed(groupId);
          return;
        }
        if (event.target.closest('[data-layer-group-visibility]')) {
          toggleLayerGroupVisibility(groupId);
          return;
        }
        if (event.target.closest('[data-layer-group-lock]')) {
          toggleLayerGroupLock(groupId);
          return;
        }
        if (event.target.closest('[data-layer-group-rename]')) {
          startGroupRename(groupId);
          return;
        }
        selectLayerGroup(groupId);
        return;
      }
      const row = event.target.closest('.desk-layout-layer[data-layer-index]');
      if (!row) return;
      const index = Number(row.dataset.layerIndex);
      const rowObject = getLayerByIndex(index);
      if (isolatedGroupId && !isObjectInIsolatedGroup(rowObject)) {
        warnIsolationLocked();
        return;
      }
      if (event.target.closest('[data-layer-visibility]')) {
        toggleLayerVisibility(index);
        return;
      }
      if (event.target.closest('[data-layer-lock]')) {
        toggleLayerLock(index);
        return;
      }
      if (event.target.closest('[data-layer-rename]')) {
        startLayerRename(index);
        return;
      }
      if (event.shiftKey || event.metaKey || event.ctrlKey) {
        const indices = new Set(getSelectedLayerIndices());
        if (indices.has(index) && indices.size > 1) indices.delete(index);
        else indices.add(index);
        selectLayerSet([...indices]);
        return;
      }
      selectLayer(index);
    });
    els.deskLayoutLayerList?.addEventListener('dblclick', event => {
      const groupRow = event.target.closest('.desk-layout-layer[data-layer-group-id]');
      if (groupRow && !event.target.closest('.desk-layout-layer__actions')) {
        if (isolatedGroupId && groupRow.dataset.layerGroupId !== isolatedGroupId) {
          warnIsolationLocked();
          return;
        }
        startGroupRename(groupRow.dataset.layerGroupId || '');
        return;
      }
      const row = event.target.closest('.desk-layout-layer[data-layer-index]');
      if (!row || event.target.closest('.desk-layout-layer__actions')) return;
      const object = getLayerByIndex(Number(row.dataset.layerIndex));
      if (isolatedGroupId && !isObjectInIsolatedGroup(object)) {
        warnIsolationLocked();
        return;
      }
      startLayerRename(Number(row.dataset.layerIndex));
    });
    els.deskLayoutLayerList?.addEventListener('keydown', event => {
      const input = event.target.closest('[data-layer-name-input], [data-layer-group-name-input]');
      if (!input) return;
      if (event.key === 'Enter') {
        event.preventDefault();
        if (input.hasAttribute('data-layer-group-name-input')) commitGroupRename(input);
        else commitLayerRename(input);
      } else if (event.key === 'Escape') {
        renamingLayerIndex = null;
        renamingGroupId = '';
        renderLayers();
      }
    });
    els.deskLayoutLayerList?.addEventListener('focusout', event => {
      const input = event.target.closest('[data-layer-name-input], [data-layer-group-name-input]');
      if (!input) return;
      if (input.hasAttribute('data-layer-group-name-input')) commitGroupRename(input);
      else commitLayerRename(input);
    });
    els.deskLayoutLayerList?.addEventListener('dragstart', handleLayerDragStart);
    els.deskLayoutLayerList?.addEventListener('dragover', handleLayerDragOver);
    els.deskLayoutLayerList?.addEventListener('drop', handleLayerDrop);
    els.deskLayoutLayerList?.addEventListener('dragend', handleLayerDragEnd);
    els.deskLayoutTextInput?.addEventListener('input', event => updateActiveText({ text: event.target.value }));
    els.deskLayoutFontFamilySelect?.addEventListener('change', event => {
      updateActiveTextFont(event.target.value).catch(error => setStatus(`字体加载失败：${error.message}`, 'error'));
    });
    els.deskLayoutFontWeightSelect?.addEventListener('change', event => {
      updateActiveTextWeight(event.target.value).catch(error => setStatus(`字重加载失败：${error.message}`, 'error'));
    });
    els.deskLayoutFontSizeInput?.addEventListener('input', event => updateActiveText({ fontSize: Number(event.target.value) || 32 }));
    els.deskLayoutLineHeightInput?.addEventListener('input', event => {
      updateActiveText({ lineHeight: clampNumber(event.target.value, 0.6, 3, 1.16) });
    });
    els.deskLayoutCharSpacingInput?.addEventListener('input', event => {
      updateActiveText({ charSpacing: Math.round(clampNumber(event.target.value, -200, 800, 0)) });
    });
    els.deskLayoutColorInput?.addEventListener('input', event => updateActiveText({ fill: event.target.value }));
    els.deskLayoutImageFitSelect?.addEventListener('change', event => {
      updateActiveImageFit(event.target.value).catch(error => setStatus(`图片适配失败：${error.message}`, 'error'));
    });
    els.deskLayoutImageFocalXInput?.addEventListener('input', event => {
      updateActiveImageCrop({ focalX: clampNumber(event.target.value, 0, 100, 50) / 100 })
        .catch(error => setStatus(`图片裁剪失败：${error.message}`, 'error'));
    });
    els.deskLayoutImageFocalYInput?.addEventListener('input', event => {
      updateActiveImageCrop({ focalY: clampNumber(event.target.value, 0, 100, 50) / 100 })
        .catch(error => setStatus(`图片裁剪失败：${error.message}`, 'error'));
    });
    els.deskLayoutImageCropZoomInput?.addEventListener('input', event => {
      updateActiveImageCrop({ zoom: clampNumber(event.target.value, 100, 400, 100) / 100 })
        .catch(error => setStatus(`图片裁剪失败：${error.message}`, 'error'));
    });
    els.deskLayoutImageCropResetBtn?.addEventListener('click', () => {
      resetActiveImageCrop().catch(error => setStatus(`图片裁剪失败：${error.message}`, 'error'));
    });
    els.deskLayoutReturnGroupBtn?.addEventListener('click', returnToActiveGroupSelection);
    els.deskLayoutIsolationExitBtn?.addEventListener('click', () => exitGroupIsolation());
    els.deskLayoutReplaceImageBtn?.addEventListener('click', () => {
      const object = canvas?.getActiveObject();
      if (!isImageObject(object)) {
        setStatus('请先选中一个图片图层', 'error');
        return;
      }
      if (!canEditImageObject(object)) return;
      pendingTemplateImageVariable = '';
      pendingImageReplacement = true;
      els.deskLayoutImageInput?.click();
    });
    [
      [els.deskLayoutObjectXInput, 'left'],
      [els.deskLayoutObjectYInput, 'top'],
      [els.deskLayoutObjectWInput, 'width'],
      [els.deskLayoutObjectHInput, 'height'],
      [els.deskLayoutObjectAngleInput, 'angle'],
      [els.deskLayoutObjectOpacityInput, 'opacity']
    ].forEach(([input, key]) => {
      input?.addEventListener('input', event => updateActiveObjectGeometry({ [key]: event.target.value }));
    });
    document.querySelectorAll('[data-layout-object-align]').forEach(button => {
      button.addEventListener('click', () => alignActiveObjects(button.dataset.layoutObjectAlign));
    });
    document.querySelectorAll('[data-layout-object-distribute]').forEach(button => {
      button.addEventListener('click', () => distributeActiveObjects(button.dataset.layoutObjectDistribute));
    });
    document.querySelectorAll('[data-layout-align]').forEach(button => {
      button.addEventListener('click', () => updateActiveText({ textAlign: button.dataset.layoutAlign }));
    });
    document.querySelectorAll('[data-layout-font-step]').forEach(button => {
      button.addEventListener('click', () => {
        const object = canvas?.getActiveObject();
        if (!object || !['i-text', 'text', 'textbox'].includes(object.type)) return;
        const nextSize = Math.max(8, Math.min(220, Number(object.fontSize || 32) + Number(button.dataset.layoutFontStep || 0)));
        updateActiveText({ fontSize: nextSize });
        updateSelectionUi();
      });
    });
    els.deskLayoutBoldBtn?.addEventListener('click', () => {
      const object = canvas?.getActiveObject();
      if (!object || !['i-text', 'text', 'textbox'].includes(object.type)) return;
      const current = normalizeFontWeight(object.fontWeight);
      updateActiveTextWeight(current >= 700 ? 500 : 800).catch(error => setStatus(`字重加载失败：${error.message}`, 'error'));
    });
    els.deskLayoutForwardBtn?.addEventListener('click', () => {
      const object = canvas?.getActiveObject();
      if (!object || getActiveLayerObjects().length !== 1) return;
      canvas.bringForward(object);
      canvas.requestRenderAll();
      renderLayers();
      recordHistory('图层已上移');
    });
    els.deskLayoutBackwardBtn?.addEventListener('click', () => {
      const object = canvas?.getActiveObject();
      if (!object || getActiveLayerObjects().length !== 1) return;
      canvas.sendBackwards(object);
      canvas.requestRenderAll();
      renderLayers();
      recordHistory('图层已下移');
    });
    els.deskLayoutCopyBtn?.addEventListener('click', () => copyActiveLayers());
    els.deskLayoutPasteBtn?.addEventListener('click', () => {
      pasteLayerClipboard().catch(error => DesktopResults.showError(error));
    });
    els.deskLayoutDuplicateBtn?.addEventListener('click', () => {
      duplicateActiveLayers().catch(error => DesktopResults.showError(error));
    });
    els.deskLayoutGroupBtn?.addEventListener('click', () => groupActiveLayers());
    els.deskLayoutUngroupBtn?.addEventListener('click', () => ungroupActiveLayers());
    els.deskLayoutDeleteBtn?.addEventListener('click', () => {
      deleteActiveLayers();
    });
    document.addEventListener('keydown', event => {
      if (!els.deskLayoutEditor?.classList.contains('is-open')) return;
      const key = String(event.key || '').toLowerCase();
      const isCommand = event.metaKey || event.ctrlKey;
      if (isCommand && key === 'z') {
        event.preventDefault();
        const action = event.shiftKey ? redoLayoutEdit : undoLayoutEdit;
        action().catch(error => DesktopResults.showError(error));
        return;
      }
      if (isCommand && key === 'y') {
        event.preventDefault();
        redoLayoutEdit().catch(error => DesktopResults.showError(error));
        return;
      }
      const editing = event.target.closest('input, textarea, [contenteditable="true"]');
      if (isCommand && key === 'c' && !editing) {
        event.preventDefault();
        copyActiveLayers();
        return;
      }
      if (isCommand && key === 'v' && !editing) {
        event.preventDefault();
        pasteLayerClipboard().catch(error => DesktopResults.showError(error));
        return;
      }
      if (isCommand && key === 'd' && !editing) {
        event.preventDefault();
        duplicateActiveLayers().catch(error => DesktopResults.showError(error));
        return;
      }
      if (isCommand && key === 'g' && !editing) {
        event.preventDefault();
        if (event.shiftKey) ungroupActiveLayers();
        else groupActiveLayers();
        return;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        close();
        return;
      }
      const nudgeByKey = {
        arrowleft: [-1, 0],
        arrowright: [1, 0],
        arrowup: [0, -1],
        arrowdown: [0, 1]
      }[key];
      if (nudgeByKey && !editing && !isCommand) {
        const step = event.shiftKey ? 10 : 1;
        event.preventDefault();
        nudgeActiveObjects(nudgeByKey[0] * step, nudgeByKey[1] * step);
        return;
      }
      if ((event.key === 'Delete' || event.key === 'Backspace') && !editing) {
        event.preventDefault();
        deleteActiveLayers();
      }
    });
    window.addEventListener('resize', () => {
      if (!els.deskLayoutEditor?.classList.contains('is-open') || stageZoomMode !== 'fit') return;
      fitStageToView();
    });
  }

  function init() {
    collectElements();
    renderFontFamilyOptions(getDefaultTextFont());
    renderFontWeightOptions(400);
    bindEvents();
    applyLayersPanelState();
    updateHistoryButtons();
  }

  init();

  window.DesktopLayoutEditor = {
    open,
    close,
    saveToNode,
    exportImage,
    syncConnectedImages
  };
})();

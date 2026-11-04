// ComfyUI input slots for title-tagged workflows: maps connected image/video sources onto the
// workflow's ordered `[参考图N]` / `[视频]` slots. Assignments live on the Comfy node per workflow
// (`comfyInputSlots[workflowId][slotKey]`): a source key, 'none' for a slot left to the workflow's
// own value, or absent for auto-fill in connection order. Stale sources fall back to auto-fill.
(function () {
  const NONE = 'none';

  function sourceKey(reference, kind) {
    if (kind === 'video') return `node:${reference.nodeId}`;
    return reference.imageGroupId
      ? `group:${reference.imageGroupId}:${reference.imageGroupItemId}`
      : `node:${reference.sourceNodeId || reference.id}`;
  }

  function sourceLabel(reference, kind) {
    if (kind === 'video') return String(reference.name || '视频');
    if (reference.imageGroupId) return `图片组 · 图${reference.imageNumber || 1}`;
    return String(reference.title || reference.name || '图片').slice(0, 40);
  }

  function create({getNodeState, getConnectedImageReferences, getConnectedVideoReferences, escapeHtml}) {
    function candidates(nodeId, kind) {
      const references = kind === 'video' ? getConnectedVideoReferences(nodeId) : getConnectedImageReferences(nodeId);
      const seen = new Set();
      return references.map(reference => ({key: sourceKey(reference, kind), label: sourceLabel(reference, kind), reference}))
        .filter(item => !seen.has(item.key) && seen.add(item.key));
    }

    function assignments(node, workflowId) {
      const bucket = node?.comfyInputSlots?.[workflowId];
      return bucket && typeof bucket === 'object' && !Array.isArray(bucket) ? bucket : {};
    }

    // [{key, kind, label, source: candidate|null, auto, options}] for every slot of the workflow.
    function resolve(nodeId, meta) {
      const node = getNodeState(nodeId);
      const slots = Array.isArray(meta?.input_slots) ? meta.input_slots : [];
      const saved = assignments(node, meta?.id || '');
      const byKind = {image: candidates(nodeId, 'image'), video: candidates(nodeId, 'video')};
      const resolved = slots.map(slot => {
        const options = byKind[slot.kind] || [];
        const value = saved[slot.key];
        const source = value === NONE ? null : (options.find(item => item.key === value) || undefined);
        return {...slot, options, source, auto: source === undefined};
      });
      ['image', 'video'].forEach(kind => {
        const used = new Set(resolved.filter(slot => slot.kind === kind && slot.source).map(slot => slot.source.key));
        const free = byKind[kind].filter(item => !used.has(item.key));
        resolved.filter(slot => slot.kind === kind && slot.auto).forEach(slot => { slot.source = free.shift() || null; });
      });
      return resolved;
    }

    function assign(nodeId, workflowId, slotKey, value) {
      const node = getNodeState(nodeId);
      if (!node || !workflowId || !slotKey) return;
      if (!node.comfyInputSlots || typeof node.comfyInputSlots !== 'object' || Array.isArray(node.comfyInputSlots)) node.comfyInputSlots = {};
      const bucket = {...assignments(node, workflowId)};
      if (value) bucket[slotKey] = value; else delete bucket[slotKey];
      if (Object.keys(bucket).length) node.comfyInputSlots[workflowId] = bucket;
      else delete node.comfyInputSlots[workflowId];
    }

    // Positional references for submission: compact lists plus per-slot indexes (-1 = keep workflow value).
    function readConfig(nodeId, meta) {
      const result = {referenceImages: [], imageSlotOrder: [], referenceVideos: [], videoSlotOrder: []};
      resolve(nodeId, meta).forEach(slot => {
        const list = slot.kind === 'video' ? result.referenceVideos : result.referenceImages;
        const order = slot.kind === 'video' ? result.videoSlotOrder : result.imageSlotOrder;
        if (!slot.source) { order.push(-1); return; }
        order.push(list.length);
        list.push(slot.source.reference);
      });
      return result;
    }

    function html(nodeId, meta) {
      const slots = resolve(nodeId, meta);
      if (!slots.length) return '';
      return `<div class="desk-comfy-input-slots">${slots.map(slot => {
        const selected = slot.auto ? '' : (slot.source?.key || NONE);
        const options = [
          `<option value=""${selected === '' ? ' selected' : ''}>自动${slot.auto && slot.source ? `（${escapeHtml(slot.source.label)}）` : '（未接入）'}</option>`,
          ...slot.options.map(item => `<option value="${escapeHtml(item.key)}"${selected === item.key ? ' selected' : ''}>${escapeHtml(item.label)}</option>`),
          `<option value="${NONE}"${selected === NONE ? ' selected' : ''}>不传入，沿用工作流原值</option>`,
        ].join('');
        return `<label class="desk-comfy-parameter-field"><span>${escapeHtml(slot.label)}</span><select class="desk-select" data-comfy-input-slot="${escapeHtml(slot.key)}">${options}</select></label>`;
      }).join('')}</div>`;
    }

    return Object.freeze({resolve, assign, readConfig, html});
  }

  window.DesktopCanvasComfyInputs = Object.freeze({create, NONE});
})();

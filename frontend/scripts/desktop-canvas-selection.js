// Canvas selection, node groups, alignment and snap-guide controller.
// The host owns event binding, selection notifications, persistence and node DOM.
// Dependencies stay explicit; getCanvas() must resolve the live canvas, not a snapshot.
(function () {
  function create({
    getCanvas, els, getNodeElement, getBoundsFromRects, rectsIntersect,
    applyNodeLayout, setSelectedNodes, updateLinkPath, saveSettings,
    showTransientMessage, imageNodeSource, IS_MAC_PLATFORM,
    IMAGE_GROUP_MAX_ITEMS, SNAP_THRESHOLD_PX
  }) {
    let nodeGroupSequence = 0;

    function normalizeNodeGroupId(value) {
      const normalized = String(value || '').trim();
      return /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(normalized) ? normalized : '';
    }

    function normalizeNodeGroups(nodes = getCanvas().nodes) {
      const groups = new Map();
      let changed = false;
      Object.values(nodes || {}).forEach(node => {
        if (!node || typeof node !== 'object') return;
        const groupId = normalizeNodeGroupId(node.groupId);
        if (!groupId) {
          if (Object.prototype.hasOwnProperty.call(node, 'groupId')) {
            delete node.groupId;
            changed = true;
          }
          return;
        }
        if (node.groupId !== groupId) {
          node.groupId = groupId;
          changed = true;
        }
        groups.set(groupId, (groups.get(groupId) || 0) + 1);
      });
      Object.values(nodes || {}).forEach(node => {
        const groupId = normalizeNodeGroupId(node?.groupId);
        if (!groupId || (groups.get(groupId) || 0) >= 2) return;
        delete node.groupId;
        changed = true;
      });
      return changed;
    }

    function getNodeIdsInGroup(groupId, nodes = getCanvas().nodes) {
      const normalized = normalizeNodeGroupId(groupId);
      if (!normalized) return [];
      return Object.keys(nodes || {}).filter(nodeId => normalizeNodeGroupId(nodes[nodeId]?.groupId) === normalized);
    }

    function expandNodeIdsToGroups(nodeIds, nodes = getCanvas().nodes) {
      const expanded = [];
      const seen = new Set();
      const append = nodeId => {
        if (!nodes?.[nodeId] || seen.has(nodeId)) return;
        seen.add(nodeId);
        expanded.push(nodeId);
      };
      (nodeIds || []).forEach(nodeId => {
        if (!nodes?.[nodeId]) return;
        append(nodeId);
        getNodeIdsInGroup(nodes[nodeId]?.groupId, nodes).forEach(append);
      });
      return expanded;
    }

    function normalizeCanvasGroupsAndSelection() {
      const canvas = getCanvas();
      const groupsChanged = normalizeNodeGroups(canvas.nodes);
      const selected = Array.isArray(canvas.selectedNodeIds)
        ? canvas.selectedNodeIds
        : (canvas.selectedNodeId ? [canvas.selectedNodeId] : []);
      const expanded = expandNodeIdsToGroups(selected, canvas.nodes);
      const selectionChanged = expanded.length !== selected.length
        || expanded.some((nodeId, index) => nodeId !== selected[index]);
      canvas.selectedNodeIds = expanded;
      canvas.selectedNodeId = expanded[0] || '';
      return groupsChanged || selectionChanged;
    }

    function createNodeGroupId() {
      let groupId = '';
      do {
        nodeGroupSequence += 1;
        groupId = `group_${Date.now().toString(36)}_${nodeGroupSequence.toString(36)}`;
      } while (getNodeIdsInGroup(groupId).length);
      return groupId;
    }

    function getSelectionGroupState(nodeIds = getSelectedNodeIds()) {
      const selectedIds = [...new Set((nodeIds || []).filter(nodeId => getCanvas().nodes[nodeId]))];
      if (selectedIds.length < 2) return { grouped: false, groupId: '', memberIds: selectedIds };
      const groupId = normalizeNodeGroupId(getCanvas().nodes[selectedIds[0]]?.groupId);
      if (!groupId || selectedIds.some(nodeId => normalizeNodeGroupId(getCanvas().nodes[nodeId]?.groupId) !== groupId)) {
        return { grouped: false, groupId: '', memberIds: selectedIds };
      }
      const memberIds = getNodeIdsInGroup(groupId);
      const selected = new Set(selectedIds);
      const grouped = memberIds.length === selectedIds.length && memberIds.every(nodeId => selected.has(nodeId));
      return { grouped, groupId: grouped ? groupId : '', memberIds: selectedIds };
    }

    function getSelectedNodeIds() {
      const canvas = getCanvas();
      const selected = Array.isArray(canvas.selectedNodeIds) ? canvas.selectedNodeIds : (canvas.selectedNodeId ? [canvas.selectedNodeId] : []);
      return selected.filter(nodeId => !!getCanvas().nodes[nodeId]);
    }

    function getNodeBounds(nodeState) {
      const el = getNodeElement(nodeState.id);
      return {
        x: nodeState.x,
        y: nodeState.y,
        width: el?.offsetWidth || nodeState.width,
        height: el?.offsetHeight || nodeState.height
      };
    }

    function getNodeBoundsById(nodeId) {
      const node = getCanvas().nodes[nodeId];
      return node ? getNodeBounds(node) : null;
    }

    function getBoundsForNodeIds(nodeIds) {
      return getBoundsFromRects((nodeIds || []).map(getNodeBoundsById).filter(Boolean));
    }

    function getSelectionUnits(nodeIds = getSelectedNodeIds()) {
      const units = [];
      const byKey = new Map();
      (nodeIds || []).forEach(nodeId => {
        const node = getCanvas().nodes[nodeId];
        if (!node) return;
        const groupId = normalizeNodeGroupId(node.groupId);
        const key = groupId ? `group:${groupId}` : `node:${nodeId}`;
        let unit = byKey.get(key);
        if (!unit) {
          unit = { key, groupId, nodeIds: [] };
          byKey.set(key, unit);
          units.push(unit);
        }
        unit.nodeIds.push(nodeId);
      });
      return units.map(unit => ({
        ...unit,
        bounds: getBoundsForNodeIds(unit.nodeIds)
      })).filter(unit => unit.bounds);
    }

    function moveSelectionUnit(unit, dx, dy) {
      unit.nodeIds.forEach(nodeId => {
        const node = getCanvas().nodes[nodeId];
        if (!node) return;
        node.x += dx;
        node.y += dy;
        applyNodeLayout(nodeId);
      });
      unit.bounds = {
        ...unit.bounds,
        x: unit.bounds.x + dx,
        y: unit.bounds.y + dy,
        right: unit.bounds.right + dx,
        bottom: unit.bounds.bottom + dy,
        centerX: unit.bounds.centerX + dx,
        centerY: unit.bounds.centerY + dy
      };
    }

    function selectionGroupShortcutLabel() {
      return IS_MAC_PLATFORM ? 'Command+G' : 'Ctrl+G';
    }

    function worldRectToCanvasRect(rect) {
      const canvas = getCanvas();
      return {
        left: canvas.x + rect.x * canvas.scale,
        top: canvas.y + rect.y * canvas.scale,
        width: rect.width * canvas.scale,
        height: rect.height * canvas.scale
      };
    }

    function updateSelectionToolbar() {
      if (!els.deskSelectionToolbar) return;
      const selectedIds = getSelectedNodeIds();
      if (selectedIds.length < 2) {
        els.deskSelectionToolbar.classList.remove('is-active');
        els.deskSelectionBounds?.classList.remove('is-active', 'is-grouped');
        return;
      }
      const bounds = getBoundsForNodeIds(selectedIds);
      if (!bounds) return;
      const groupState = getSelectionGroupState(selectedIds);
      const units = getSelectionUnits(selectedIds);
      const imageGroupButton = els.deskSelectionToolbar.querySelector('[data-create-image-group]');
      const imageGroupDivider = els.deskSelectionToolbar.querySelector('[data-image-group-divider]');
      const canCreateImageGroup = selectedIds.length <= IMAGE_GROUP_MAX_ITEMS && selectedIds.every(nodeId => {
        const node = getCanvas().nodes[nodeId];
        return node?.type === 'image' && Boolean(imageNodeSource(node));
      });
      if (imageGroupButton) imageGroupButton.hidden = !canCreateImageGroup;
      if (imageGroupDivider) imageGroupDivider.hidden = !canCreateImageGroup;
      const rect = worldRectToCanvasRect(bounds);
      if (els.deskSelectionBounds) {
        els.deskSelectionBounds.style.left = `${rect.left}px`;
        els.deskSelectionBounds.style.top = `${rect.top}px`;
        els.deskSelectionBounds.style.width = `${rect.width}px`;
        els.deskSelectionBounds.style.height = `${rect.height}px`;
        els.deskSelectionBounds.classList.add('is-active');
        els.deskSelectionBounds.classList.toggle('is-grouped', groupState.grouped);
      }
      if (els.deskSelectionCount) {
        els.deskSelectionCount.textContent = `${selectedIds.length} 个节点`;
      }
      if (els.deskSelectionGroupBtn) {
        const label = groupState.grouped ? '解除群组' : '群组';
        const title = groupState.grouped
          ? `解除选中节点的群组 (${selectionGroupShortcutLabel()})`
          : `将选中的节点设为群组 (${selectionGroupShortcutLabel()})`;
        els.deskSelectionGroupBtn.textContent = label;
        els.deskSelectionGroupBtn.dataset.mode = groupState.grouped ? 'ungroup' : 'group';
        els.deskSelectionGroupBtn.setAttribute('aria-label', title);
        els.deskSelectionGroupBtn.title = title;
      }
      els.deskSelectionToolbar.querySelectorAll('[data-align]').forEach(button => {
        const minimumUnits = String(button.dataset.align || '').startsWith('distribute-') ? 3 : 2;
        button.disabled = units.length < minimumUnits;
      });
      els.deskSelectionToolbar.style.left = `${Math.max(8, rect.left)}px`;
      els.deskSelectionToolbar.style.top = `${Math.max(8, rect.top - 42)}px`;
      els.deskSelectionToolbar.classList.add('is-active');
    }

    function renderMarquee(worldRect) {
      if (!els.deskSelectionMarquee) return;
      const rect = worldRectToCanvasRect(worldRect);
      els.deskSelectionMarquee.style.left = `${rect.left}px`;
      els.deskSelectionMarquee.style.top = `${rect.top}px`;
      els.deskSelectionMarquee.style.width = `${rect.width}px`;
      els.deskSelectionMarquee.style.height = `${rect.height}px`;
      els.deskSelectionMarquee.classList.add('is-active');
    }

    function hideMarquee() {
      els.deskSelectionMarquee?.classList.remove('is-active');
    }

    function hideSmartGuides() {
      els.deskSmartGuideX?.classList.remove('is-active');
      els.deskSmartGuideY?.classList.remove('is-active');
    }

    function applySelectionLayout() {
      getSelectedNodeIds().forEach(applyNodeLayout);
      updateLinkPath();
      updateSelectionToolbar();
      saveSettings();
    }

    function toggleSelectionGroup() {
      const selectedIds = getSelectedNodeIds();
      if (selectedIds.length < 2) return false;
      const groupState = getSelectionGroupState(selectedIds);
      if (groupState.grouped) {
        selectedIds.forEach(nodeId => {
          delete getCanvas().nodes[nodeId].groupId;
        });
        setSelectedNodes(selectedIds, false);
        saveSettings();
        showTransientMessage('已解除节点群组。');
        return true;
      }

      const groupId = createNodeGroupId();
      selectedIds.forEach(nodeId => {
        getCanvas().nodes[nodeId].groupId = groupId;
      });
      setSelectedNodes(selectedIds, false);
      saveSettings();
      showTransientMessage(`已将 ${selectedIds.length} 个节点设为群组。`);
      return true;
    }

    function alignSelection(action) {
      const selectedIds = getSelectedNodeIds();
      if (selectedIds.length < 2) return;
      const bounds = getBoundsForNodeIds(selectedIds);
      if (!bounds) return;
      const units = getSelectionUnits(selectedIds);
      if (units.length < 2) return;

      if (action === 'left') units.forEach(unit => moveSelectionUnit(unit, bounds.x - unit.bounds.x, 0));
      if (action === 'hcenter') units.forEach(unit => moveSelectionUnit(unit, bounds.centerX - unit.bounds.centerX, 0));
      if (action === 'right') units.forEach(unit => moveSelectionUnit(unit, bounds.right - unit.bounds.right, 0));
      if (action === 'top') units.forEach(unit => moveSelectionUnit(unit, 0, bounds.y - unit.bounds.y));
      if (action === 'vcenter') units.forEach(unit => moveSelectionUnit(unit, 0, bounds.centerY - unit.bounds.centerY));
      if (action === 'bottom') units.forEach(unit => moveSelectionUnit(unit, 0, bounds.bottom - unit.bounds.bottom));

      if (action === 'distribute-x' && units.length >= 3) {
        const ordered = [...units].sort((a, b) => a.bounds.x - b.bounds.x);
        const totalWidth = ordered.reduce((sum, unit) => sum + unit.bounds.width, 0);
        const gap = (bounds.width - totalWidth) / Math.max(1, ordered.length - 1);
        let x = bounds.x;
        ordered.forEach(unit => {
          moveSelectionUnit(unit, x - unit.bounds.x, 0);
          x += unit.bounds.width + gap;
        });
      }

      if (action === 'distribute-y' && units.length >= 3) {
        const ordered = [...units].sort((a, b) => a.bounds.y - b.bounds.y);
        const totalHeight = ordered.reduce((sum, unit) => sum + unit.bounds.height, 0);
        const gap = (bounds.height - totalHeight) / Math.max(1, ordered.length - 1);
        let y = bounds.y;
        ordered.forEach(unit => {
          moveSelectionUnit(unit, 0, y - unit.bounds.y);
          y += unit.bounds.height + gap;
        });
      }

      applySelectionLayout();
    }

    function showSmartGuides(guides) {
      const canvas = getCanvas();
      if (els.deskSmartGuideX) {
        if (Number.isFinite(guides?.x)) {
          els.deskSmartGuideX.style.left = `${canvas.x + guides.x * canvas.scale}px`;
          els.deskSmartGuideX.classList.add('is-active');
        } else {
          els.deskSmartGuideX.classList.remove('is-active');
        }
      }
      if (els.deskSmartGuideY) {
        if (Number.isFinite(guides?.y)) {
          els.deskSmartGuideY.style.top = `${canvas.y + guides.y * canvas.scale}px`;
          els.deskSmartGuideY.classList.add('is-active');
        } else {
          els.deskSmartGuideY.classList.remove('is-active');
        }
      }
    }

    function selectNodesInRect(rect, save = false) {
      const selected = Object.keys(getCanvas().nodes).filter(nodeId => {
        const bounds = getNodeBoundsById(nodeId);
        return bounds && rectsIntersect(rect, bounds);
      });
      setSelectedNodes(selected, save);
    }

    // Marquee session. Nodes neither move nor resize while the box is drawn, so their bounds
    // are measured once when it starts (no layout reads per pointer move); moves are folded
    // into one update per frame, and the selection is re-applied only when the set of nodes
    // inside the box changes — each apply restyles nodes, rebuilds the edge layer and
    // notifies the panels listening for selection changes.
    let marquee = null;

    function beginMarquee() {
      if (marquee?.frame) cancelAnimationFrame(marquee.frame);
      marquee = {
        bounds: Object.keys(getCanvas().nodes).map(nodeId => [nodeId, getNodeBoundsById(nodeId)]).filter(([, bounds]) => bounds),
        rect: null,
        frame: 0,
        key: getSelectedNodeIds().join('\n'),
      };
    }

    function flushMarquee() {
      if (!marquee) return;
      marquee.frame = 0;
      if (!marquee.rect) return;
      renderMarquee(marquee.rect);
      const ids = marquee.bounds.filter(([, bounds]) => rectsIntersect(marquee.rect, bounds)).map(([nodeId]) => nodeId);
      const key = ids.join('\n');
      if (key === marquee.key) return;
      marquee.key = key;
      setSelectedNodes(ids, false);
    }

    function moveMarquee(rect) {
      if (!marquee) beginMarquee();
      marquee.rect = rect;
      if (!marquee.frame) marquee.frame = requestAnimationFrame(flushMarquee);
    }

    function endMarquee() {
      if (marquee?.frame) cancelAnimationFrame(marquee.frame);
      marquee = null;
    }

    function getMovedBounds(groupIds, positions, dx, dy) {
      return getBoundsFromRects(groupIds.map(nodeId => {
        const node = getCanvas().nodes[nodeId];
        const base = positions[nodeId];
        if (!node || !base) return null;
        return {
          x: base.x + dx,
          y: base.y + dy,
          width: getNodeElement(nodeId)?.offsetWidth || node.width,
          height: getNodeElement(nodeId)?.offsetHeight || node.height
        };
      }).filter(Boolean));
    }

    function resolveSnap(groupIds, positions, dx, dy, options = {}) {
      const movingBounds = getMovedBounds(groupIds, positions, dx, dy);
      if (!movingBounds) return { dx, dy, guides: {} };
      const threshold = SNAP_THRESHOLD_PX / getCanvas().scale;
      const excludedIds = new Set(options.excludeNodeIds || []);
      const others = Object.keys(getCanvas().nodes)
        .filter(nodeId => !groupIds.includes(nodeId) && !excludedIds.has(nodeId))
        .map(getNodeBoundsById)
        .filter(Boolean);
      const movingX = [
        { value: movingBounds.x, kind: 'left' },
        { value: movingBounds.centerX, kind: 'center' },
        { value: movingBounds.right, kind: 'right' }
      ];
      const movingY = [
        { value: movingBounds.y, kind: 'top' },
        { value: movingBounds.centerY, kind: 'center' },
        { value: movingBounds.bottom, kind: 'bottom' }
      ];
      const targetX = others.flatMap(rect => [rect.x, rect.x + rect.width / 2, rect.x + rect.width]);
      const targetY = others.flatMap(rect => [rect.y, rect.y + rect.height / 2, rect.y + rect.height]);
      let snapX = null;
      let snapY = null;
      movingX.forEach(anchor => {
        targetX.forEach(target => {
          const diff = target - anchor.value;
          if (Math.abs(diff) <= threshold && (!snapX || Math.abs(diff) < Math.abs(snapX.diff))) {
            snapX = { diff, target };
          }
        });
      });
      movingY.forEach(anchor => {
        targetY.forEach(target => {
          const diff = target - anchor.value;
          if (Math.abs(diff) <= threshold && (!snapY || Math.abs(diff) < Math.abs(snapY.diff))) {
            snapY = { diff, target };
          }
        });
      });
      return {
        dx: dx + (snapX?.diff || 0),
        dy: dy + (snapY?.diff || 0),
        guides: {
          x: snapX?.target,
          y: snapY?.target
        }
      };
    }

    return Object.freeze({
      normalizeNodeGroupId,
      normalizeNodeGroups,
      getNodeIdsInGroup,
      expandNodeIdsToGroups,
      normalizeCanvasGroupsAndSelection,
      createNodeGroupId,
      getSelectionGroupState,
      getSelectedNodeIds,
      getNodeBounds,
      getNodeBoundsById,
      getBoundsForNodeIds,
      getSelectionUnits,
      moveSelectionUnit,
      selectionGroupShortcutLabel,
      worldRectToCanvasRect,
      updateSelectionToolbar,
      renderMarquee,
      hideMarquee,
      hideSmartGuides,
      applySelectionLayout,
      toggleSelectionGroup,
      alignSelection,
      showSmartGuides,
      selectNodesInRect,
      beginMarquee,
      moveMarquee,
      endMarquee,
      getMovedBounds,
      resolveSnap
    });
  }

  window.DesktopCanvasSelection = Object.freeze({ create });
})();

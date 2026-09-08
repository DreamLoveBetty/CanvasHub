(function () {
  function escapeAttr(value) {
    return String(value || '').replace(/[&<>"']/g, char => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[char]));
  }

  function imageSource(item = {}) {
    return item.dataUrl || item.imageData || item.imageUrl || item.url || '';
  }

  function cssEscape(value) {
    if (window.CSS?.escape) return window.CSS.escape(String(value || ''));
    return String(value || '').replace(/["\\]/g, '\\$&');
  }

  function isInside(root, node) {
    return !!(root && node && (node === root || root.contains(node)));
  }

  function create(options = {}) {
    const root = options.root;
    if (!root) return null;
    const attachments = new Map();
    let mentionRange = null;
    let mentionQuery = '';

    function resetMentionMenuPosition() {
      const menu = options.menu;
      if (!menu) return;
      ['left', 'top', 'right', 'bottom'].forEach(property => menu.style.removeProperty(property));
      delete menu.dataset.mentionAnchored;
    }

    function dispatchInput() {
      root.dispatchEvent(new CustomEvent('prompt-editor:change', { bubbles: true }));
      options.onChange?.(getText());
    }

    function clearMention() {
      mentionRange = null;
      mentionQuery = '';
      resetMentionMenuPosition();
    }

    function closeMention() {
      clearMention();
      options.onMentionClose?.();
    }

    function selectionRange(options = {}) {
      const selection = window.getSelection?.();
      if (!selection || !selection.rangeCount) return null;
      const range = selection.getRangeAt(0);
      if ((!options.allowExpanded && !range.collapsed)
        || !isInside(root, range.startContainer)
        || !isInside(root, range.endContainer)) return null;
      return range;
    }

    function mentionAnchorRect() {
      if (!mentionRange) return null;
      const anchorRange = mentionRange.cloneRange();
      const container = anchorRange.startContainer;
      if (container?.nodeType === Node.TEXT_NODE && anchorRange.startOffset < (container.nodeValue || '').length) {
        anchorRange.setEnd(container, anchorRange.startOffset + 1);
      }
      try {
        const rect = anchorRange.getBoundingClientRect();
        if (rect && (rect.width || rect.height)) return rect;
      } catch (error) {}
      try {
        return mentionRange.getBoundingClientRect();
      } catch (error) {
        return null;
      }
    }

    function positionMentionMenu() {
      const menu = options.menu;
      if (!menu || menu.hidden || !mentionRange) return;
      const anchorRect = mentionAnchorRect();
      const offsetParent = menu.offsetParent || menu.parentElement;
      if (!anchorRect || !offsetParent) return;

      const parentRect = offsetParent.getBoundingClientRect();
      const editorRect = root.getBoundingClientRect();
      const menuRect = menu.getBoundingClientRect();
      const menuWidth = menuRect.width || menu.offsetWidth || 0;
      const menuHeight = menuRect.height || menu.offsetHeight || 0;
      const gap = 6;
      const inset = 4;
      const minLeft = editorRect.left - parentRect.left + inset;
      const maxLeft = Math.max(minLeft, editorRect.right - parentRect.left - menuWidth - inset);
      const left = Math.max(minLeft, Math.min(maxLeft, anchorRect.left - parentRect.left));
      const below = anchorRect.bottom - parentRect.top + gap;
      const above = anchorRect.top - parentRect.top - menuHeight - gap;
      const editorBottom = editorRect.bottom - parentRect.top - inset;
      const top = below + menuHeight <= editorBottom ? below : above;

      menu.style.left = `${Math.round(left)}px`;
      menu.style.top = `${Math.round(top)}px`;
      menu.style.right = 'auto';
      menu.style.bottom = 'auto';
      menu.dataset.mentionAnchored = 'true';
    }

    function clipboardPlainText(clipboardData) {
      if (!clipboardData) return null;
      const types = Array.from(clipboardData.types || []);
      const plainText = clipboardData.getData('text/plain');
      if (plainText || types.includes('text/plain')) return plainText;
      const html = clipboardData.getData('text/html');
      if (!html && !types.includes('text/html')) return null;
      const parsed = new DOMParser().parseFromString(html, 'text/html');
      return serialize(parsed.body)
        .replace(/\u00a0/g, ' ')
        .replace(/[ \t]+\n/g, '\n')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
    }

    function insertPlainText(text = '') {
      const cleanText = String(text || '')
        .replace(/\r\n?/g, '\n')
        .replace(/\u0000/g, '');
      root.focus({ preventScroll: true });
      const range = selectionRange({ allowExpanded: true });
      const textNode = document.createTextNode(cleanText);
      if (range) {
        range.deleteContents();
        range.insertNode(textNode);
      } else {
        root.append(textNode);
      }
      placeCaretAfter(textNode);
      clearMention();
      detectMention();
      dispatchInput();
    }

    function detectMention() {
      const range = selectionRange();
      if (!range) {
        closeMention();
        return;
      }
      if (range.startContainer.nodeType !== Node.TEXT_NODE) {
        closeMention();
        return;
      }
      const text = range.startContainer.nodeValue || '';
      const before = text.slice(0, range.startOffset);
      const match = before.match(/(^|\s)@([^\s@]*)$/);
      if (!match) {
        closeMention();
        return;
      }
      const startOffset = range.startOffset - (match[2] || '').length - 1;
      const nextRange = document.createRange();
      nextRange.setStart(range.startContainer, Math.max(0, startOffset));
      nextRange.setEnd(range.startContainer, range.startOffset);
      mentionRange = nextRange;
      mentionQuery = match[2] || '';
      options.onMention?.({ query: mentionQuery, editor: api });
      positionMentionMenu();
    }

    function chipHtml(item = {}) {
      const id = String(item.id || '').trim();
      const src = imageSource(item);
      const sourceNodeId = String(item.sourceNodeId || item.nodeId || item.source_node_id || '').trim();
      const mimeType = String(item.mimeType || item.type || 'image/png').trim();
      return `
        <span class="desk-prompt-editor__image" contenteditable="false" data-prompt-image-id="${escapeAttr(id)}" data-source-node-id="${escapeAttr(sourceNodeId)}" data-image-src="${escapeAttr(src)}" data-mime-type="${escapeAttr(mimeType)}" title="${escapeAttr(id)}">
          <img src="${escapeAttr(src)}" alt="">
          <span class="desk-prompt-editor__label">${escapeAttr(id)}</span>
          <span class="desk-prompt-editor__remove" role="button" aria-label="移除 ${escapeAttr(id)}" data-prompt-editor-remove-image="${escapeAttr(id)}">×</span>
        </span>
      `;
    }

    function buildChip(item = {}) {
      const template = document.createElement('template');
      template.innerHTML = chipHtml(item).trim();
      return template.content.firstElementChild;
    }

    function placeCaretAfter(node) {
      const range = document.createRange();
      range.setStartAfter(node);
      range.collapse(true);
      const selection = window.getSelection?.();
      if (!selection) return;
      selection.removeAllRanges();
      selection.addRange(range);
    }

    function insertAttachment(item = {}, insertOptions = {}) {
      const id = String(item.id || '').trim();
      if (!id) return;
      attachments.set(id, item);
      root.focus({ preventScroll: true });
      const range = insertOptions.replaceMention !== false && mentionRange ? mentionRange.cloneRange() : selectionRange();
      const chip = buildChip(item);
      const spacer = document.createTextNode(' ');
      if (range && isInside(root, range.startContainer)) {
        range.deleteContents();
        range.insertNode(spacer);
        range.insertNode(chip);
      } else {
        root.append(chip, spacer);
      }
      clearMention();
      placeCaretAfter(spacer);
      dispatchInput();
    }

    function removeAttachment(id, removeOptions = {}) {
      const cleanId = String(id || '').trim();
      if (!cleanId) return;
      attachments.delete(cleanId);
      root.querySelectorAll(`[data-prompt-image-id="${cssEscape(cleanId)}"]`).forEach(node => {
        const next = node.nextSibling;
        node.remove();
        if (next?.nodeType === Node.TEXT_NODE && !next.nodeValue.trim()) next.remove();
      });
      if (!removeOptions.silent) dispatchInput();
    }

    function setAttachments(items = []) {
      const nextIds = new Set();
      items.forEach(item => {
        const id = String(item.id || '').trim();
        if (!id) return;
        nextIds.add(id);
        attachments.set(id, item);
        root.querySelectorAll(`[data-prompt-image-id="${cssEscape(id)}"]`).forEach(node => {
          const img = node.querySelector('img');
          if (img) img.src = imageSource(item);
          node.dataset.sourceNodeId = String(item.sourceNodeId || item.nodeId || item.source_node_id || '');
          node.dataset.imageSrc = imageSource(item);
          node.dataset.mimeType = String(item.mimeType || item.type || 'image/png');
          node.title = id;
        });
      });
      Array.from(attachments.keys()).forEach(id => {
        if (!nextIds.has(id)) removeAttachment(id, { silent: true });
      });
    }

    function serialize(node) {
      let output = '';
      node.childNodes.forEach(child => {
        if (child.nodeType === Node.TEXT_NODE) {
          output += child.nodeValue || '';
          return;
        }
        if (child.nodeType !== Node.ELEMENT_NODE) return;
        if (/^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE)$/.test(child.tagName)) return;
        if (child.matches?.('.desk-prompt-editor__image')) {
          const id = child.dataset.promptImageId || '';
          output += id ? `${id} ` : '';
          return;
        }
        if (child.tagName === 'BR') {
          output += '\n';
          return;
        }
        output += serialize(child);
        if (/^(ADDRESS|ARTICLE|BLOCKQUOTE|DD|DIV|DL|DT|FIGCAPTION|FIGURE|FOOTER|H[1-6]|HEADER|LI|MAIN|NAV|OL|P|PRE|SECTION|TABLE|TR|UL)$/.test(child.tagName)
          && !output.endsWith('\n')) output += '\n';
      });
      return output;
    }

    function getText() {
      return serialize(root)
        .replace(/\u00a0/g, ' ')
        .replace(/[ \t]+\n/g, '\n')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
    }

    function getAttachments() {
      return Array.from(root.querySelectorAll('.desk-prompt-editor__image'))
        .map(node => ({
          id: String(node.dataset.promptImageId || '').trim(),
          sourceNodeId: String(node.dataset.sourceNodeId || '').trim(),
          imageSrc: String(node.dataset.imageSrc || node.querySelector('img')?.getAttribute('src') || '').trim(),
          mimeType: String(node.dataset.mimeType || 'image/png').trim()
        }))
        .filter(item => item.id);
    }

    function setText(text = '') {
      root.textContent = String(text || '');
      clearMention();
      dispatchInput();
    }

    function setDocument(text = '', items = []) {
      const source = String(text || '');
      const byId = new Map(
        (Array.isArray(items) ? items : [])
          .map(item => [String(item?.id || '').trim(), item])
          .filter(([id]) => id)
      );
      const ids = Array.from(byId.keys()).sort((a, b) => b.length - a.length);
      attachments.clear();
      root.innerHTML = '';
      ids.forEach(id => attachments.set(id, byId.get(id)));

      if (!ids.length) {
        root.textContent = source;
      } else {
        const escapedIds = ids.map(id => id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
        const tokenPattern = new RegExp(`(^|\\s)(${escapedIds.join('|')})(?=\\s|$)`, 'g');
        let cursor = 0;
        let matched = false;
        let match;
        while ((match = tokenPattern.exec(source))) {
          matched = true;
          const prefixEnd = match.index + match[1].length;
          if (prefixEnd > cursor) root.append(document.createTextNode(source.slice(cursor, prefixEnd)));
          root.append(buildChip(byId.get(match[2])), document.createTextNode(' '));
          cursor = match.index + match[0].length;
        }
        if (cursor < source.length) root.append(document.createTextNode(source.slice(cursor)));
        if (!matched) {
          const original = root.textContent;
          root.innerHTML = '';
          ids.forEach(id => root.append(buildChip(byId.get(id)), document.createTextNode(' ')));
          if (original) root.append(document.createTextNode(original));
        }
      }
      clearMention();
      dispatchInput();
    }

    function clear() {
      root.innerHTML = '';
      clearMention();
      dispatchInput();
    }

    function clearText(options = {}) {
      if (!options.keepAttachments) {
        clear();
        return;
      }
      const chips = Array.from(root.querySelectorAll('.desk-prompt-editor__image'));
      root.innerHTML = '';
      chips.forEach(chip => {
        root.append(chip, document.createTextNode(' '));
      });
      clearMention();
      dispatchInput();
    }

    function focus() {
      root.focus({ preventScroll: true });
    }

    root.addEventListener('input', () => {
      detectMention();
      dispatchInput();
    });
    root.addEventListener('paste', event => {
      const text = clipboardPlainText(event.clipboardData);
      event.preventDefault();
      if (text === null) return;
      insertPlainText(text);
    });
    root.addEventListener('keyup', detectMention);
    root.addEventListener('mouseup', detectMention);
    root.addEventListener('scroll', positionMentionMenu, { passive: true });
    window.addEventListener('resize', positionMentionMenu, { passive: true });
    root.addEventListener('keydown', event => {
      if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
        event.preventDefault();
        options.onSubmit?.();
        return;
      }
      if (event.key === 'Escape') {
        closeMention();
      }
    });
    root.addEventListener('click', event => {
      const remove = event.target.closest('[data-prompt-editor-remove-image]');
      if (!remove) return;
      const id = remove.dataset.promptEditorRemoveImage || '';
      removeAttachment(id);
      options.onRemoveAttachment?.(id);
      event.preventDefault();
      event.stopPropagation();
    });

    const api = {
      clear,
      clearMention,
      clearText,
      closeMention,
      focus,
      getMentionQuery: () => mentionQuery,
      getAttachments,
      getText,
      hasMention: () => !!mentionRange,
      insertAttachment,
      insertPlainText,
      positionMentionMenu,
      removeAttachment,
      setAttachments,
      setDocument,
      setText
    };
    return api;
  }

  window.DesktopPromptEditor = { create };
})();

// Compose subtitles in the workbench (phase 3b): the 「字幕」 side panel (style, font, add, SRT
// import, clear), the selected cue's editor bar, and the draft caption overlay drawn over both the
// card and workbench previews. Cue/style rules live in desktop-video-compose-subtitles.js; markup in
// desktop-video-compose-view.js; the timeline lane in desktop-video-compose-timeline.js. Edits mutate
// the node's `subtitles` and are reported through onEdit; the controller saves and repaints.
(function () {
  const MAX_IMPORT_BYTES = 1024 * 1024;

  // Caption overlay + project font faces for the preview (the render draws the same font with Pillow).
  function createCaptions({subtitles, loadFonts}) {
    let catalog = null, loading = null;
    const faces = new Map(); // file -> family name once loaded, or a pending Promise
    const listeners = new Set();
    const fonts = () => {
      if (!loading) {
        loading = loadFonts().then(data => { catalog = data; listeners.forEach(fn => fn()); return data; })
          .catch(() => { loading = null; return {fonts: [], defaultFile: ''}; });
      }
      return loading;
    };
    const fileFor = name => name || catalog?.defaultFile || '';

    // CSS font-family for a style's font, registering its face on first use; '' until it has loaded.
    function family(name) {
      const file = fileFor(name), entry = faces.get(file);
      if (typeof entry === 'string') return entry;
      if (!entry && catalog && window.FontFace && document.fonts) {
        const font = catalog.fonts.find(item => item.file === file);
        if (font) {
          const familyName = `DeskComposeSubtitle${faces.size + 1}`;
          const face = new FontFace(familyName, `url("${font.url.replace(/"/g, '%22')}")`);
          faces.set(file, face.load().then(loaded => {
            document.fonts.add(loaded);
            faces.set(file, familyName);
            listeners.forEach(fn => fn());
          }).catch(() => faces.set(file, '')));
        }
      }
      return '';
    }

    // el: the frame's [data-compose-caption]; visible=false for the rendered result (already burned in).
    function paint(el, sub, time, visible = true) {
      if (!el) return;
      const k = visible && sub?.cues.length ? subtitles.cueAt(sub.cues, time) : -1;
      const text = k >= 0 ? subtitles.cleanText(sub.cues[k].text) : '';
      el.hidden = !text;
      if (!text) return;
      if (!catalog) fonts();
      if (el.textContent !== text) el.textContent = text;
      el.dataset.look = sub.style.look;
      el.dataset.position = sub.style.position;
      el.style.setProperty('--desk-video-subtitle-ratio', String(subtitles.RATIOS[sub.style.size]));
      const name = family(sub.style.font);
      el.style.fontFamily = name ? `"${name}", var(--desk-font-family-sans)` : '';
    }

    return Object.freeze({paint, fonts, family, onFonts: fn => listeners.add(fn), catalog: () => catalog});
  }

  // root: the workbench element. onEdit({final}) after any change; onSelect(k) selects a cue (-1: none).
  function create({root, subtitles, captions, escapeHtml, showMessage, confirm = message => window.confirm(message),
    onEdit, onSelect, clock, getTime}) {
    const q = selector => root.querySelector(selector);
    const panel = q('[data-cb-subtitles]'), bar = q('[data-cb-cue]'), text = q('[data-cb-cue-text]');
    const fontSelect = q('[data-cb-sub-font]'), fileInput = q('[data-cb-sub-file]');
    let state = null; // {node, total, cue}
    let fontMarkup = '';

    function paintFonts(selected) {
      const catalog = captions.catalog();
      const fonts = catalog?.fonts || [];
      const fallback = fonts.find(font => font.file === catalog?.defaultFile);
      const markup = `<option value="">默认${fallback ? `（${escapeHtml(fallback.label)}）` : ''}</option>`
        + fonts.map(font => `<option value="${escapeHtml(font.file)}">${escapeHtml(font.label)}</option>`).join('')
        + (selected && !fonts.some(font => font.file === selected) ? `<option value="${escapeHtml(selected)}">${escapeHtml(selected)}（不可用）</option>` : '');
      if (markup !== fontMarkup) { fontSelect.innerHTML = markup; fontMarkup = markup; }
      fontSelect.value = selected;
      fontSelect.disabled = !catalog;
    }

    function paint(next) {
      state = next;
      const sub = state.node.subtitles, count = sub.cues.length;
      q('[data-cb-sub-count]').textContent = count ? `${count} 条` : '未添加';
      panel.querySelectorAll('[data-cb-sub-seg]').forEach(group => group.querySelectorAll('button').forEach(button => {
        button.setAttribute('aria-pressed', String(button.dataset.value === sub.style[group.dataset.cbSubSeg]));
      }));
      if (!captions.catalog()) captions.fonts();
      paintFonts(sub.style.font);
      q('[data-cb-sub="clear"]').disabled = !count;
      q('[data-cb-sub="add"]').disabled = count >= subtitles.MAX_CUES;
      const cue = sub.cues[state.cue];
      bar.hidden = !cue;
      if (!cue) return;
      q('[data-cb-cue-name]').textContent = `字幕 ${state.cue + 1}`;
      if (document.activeElement !== text) text.value = cue.text;
      q('[data-cb-cue-time]').textContent = `${clock(cue.start)} – ${clock(cue.end)} · ${(cue.end - cue.start).toFixed(2)} 秒`;
      const late = cue.start >= state.total - subtitles.MIN_SECONDS + 1e-6;
      q('[data-cb-cue-note]').textContent = !subtitles.cleanText(cue.text) ? '请输入字幕文字'
        : late ? '在成片结束之后，合成前请移到成片范围内' : cue.end > state.total ? '超出成片的部分会被截掉' : '';
    }

    const sub = () => state?.node.subtitles;

    function addAt(time) {
      const current = sub();
      if (!current) return;
      const k = subtitles.add(current, time, state.total);
      if (k < 0) { showMessage(current.cues.length >= subtitles.MAX_CUES ? `最多 ${subtitles.MAX_CUES} 条字幕` : '播放头位置已有字幕，或剩余时间不足 0.3 秒'); return; }
      onEdit({final: true});
      onSelect(k);
      text.focus();
    }

    async function importFile(file) {
      if (!file || !sub()) return;
      if (file.size > MAX_IMPORT_BYTES) { showMessage('字幕文件超过 1 MB'); return; }
      const parsed = subtitles.parseSrt(await file.text());
      if (!parsed.cues.length) { showMessage('没有读到有效的字幕（支持 SRT／VTT）'); return; }
      const current = sub();
      if (current.cues.length && !confirm(`用导入的 ${parsed.cues.length} 条字幕替换现有 ${current.cues.length} 条？`)) return;
      current.cues = parsed.cues;
      onEdit({final: true});
      onSelect(-1);
      showMessage(`已导入 ${parsed.cues.length} 条字幕${parsed.skipped ? `，跳过 ${parsed.skipped} 条无效或重叠的` : ''}`);
    }

    function remove(k) {
      const current = sub();
      if (!current?.cues[k]) return;
      current.cues.splice(k, 1);
      onEdit({final: true});
      onSelect(-1);
    }

    function click(event) {
      const option = event.target.closest('[data-cb-sub-seg] button');
      if (option && !option.disabled) {
        sub().style[option.closest('[data-cb-sub-seg]').dataset.cbSubSeg] = option.dataset.value;
        onEdit({final: true});
        return true;
      }
      const action = event.target.closest('[data-cb-sub]')?.dataset.cbSub;
      if (action === 'add') { addAt(getTime()); return true; }
      if (action === 'import') { fileInput.value = ''; fileInput.click(); return true; }
      if (action === 'clear') {
        if (sub().cues.length && confirm(`清空全部 ${sub().cues.length} 条字幕？`)) { sub().cues = []; onEdit({final: true}); onSelect(-1); }
        return true;
      }
      if (event.target.closest('[data-cb-cue="delete"]')) { remove(state.cue); return true; }
      return Boolean(event.target.closest('[data-cb-subtitles], [data-cb-cue]'));
    }

    function input(event) {
      if (event.target !== text) return false;
      const cue = sub()?.cues[state.cue];
      if (cue) { cue.text = text.value.slice(0, subtitles.MAX_CHARS); onEdit({final: false}); }
      return true;
    }

    function change(event) {
      if (event.target === fontSelect) { sub().style.font = fontSelect.value; onEdit({final: true}); return true; }
      if (event.target === fileInput) { importFile(fileInput.files?.[0]).catch(error => showMessage(error.message || '导入失败')); return true; }
      if (event.target === text) { onEdit({final: true}); return true; }
      return false;
    }

    // Delete removes the selected cue when focus is not in a text field.
    function key(event) {
      if (!state || state.cue < 0 || !['Delete', 'Backspace'].includes(event.key)) return false;
      if (event.target.closest('input, textarea, select')) return false;
      event.preventDefault();
      remove(state.cue);
      return true;
    }

    captions.onFonts(() => { if (state && !root.hidden) paintFonts(state.node.subtitles.style.font); });

    return Object.freeze({paint, click, input, change, key, addAt});
  }

  window.DesktopVideoComposeSubtitlePanel = Object.freeze({create, createCaptions});
})();

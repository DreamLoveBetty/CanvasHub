// Lazy, local-only ABC renderer/exporter. Never changes source ABC while previewing.
(function () {
  let loading;
  function library() {
    if (window.ABCJS) return Promise.resolve(window.ABCJS);
    if (!loading) loading = new Promise((resolve, reject) => {
      const script = document.createElement('script'); script.src = 'vendor/abcjs/abcjs-basic-6.7.0.min.js';
      script.onload = () => resolve(window.ABCJS);
      script.onerror = () => { script.remove(); loading = null; reject(new Error('本地乐谱渲染器加载失败')); };
      document.head.appendChild(script);
    });
    return loading;
  }
  function selectVoice(abc, voice) {
    if (voice === 'all' || !voice) return abc;
    let selected = true;
    return abc.split('\n').filter(line => {
      const match = /^V:\s*(\S+)/.exec(line);
      if (match) selected = match[1] === voice;
      if (/^[XTM LQK]:/.test(line)) return true;
      return selected;
    }).join('\n');
  }
  async function render(element, abc, options = {}) {
    if (!abc.trim()) { element.textContent = '连接或导入 ABC 乐谱后预览'; return []; }
    const lib = await library();
    if (!element.isConnected) return [];
    // ABCJS responsive mode owns its target's padding/overflow. Keep that target
    // inside the flex/scroll viewport so titles and long scores cannot stretch it.
    const notation = document.createElement('div'); element.replaceChildren(notation);
    return lib.renderAbc(notation, selectVoice(abc, options.voice), {
      staffwidth: 570, responsive: 'resize', scale: options.scale || 1, paddingtop: 20, paddingbottom: 20,
      add_classes: true, foregroundColor: '#18273c',
    });
  }
  function download(blob, name) {
    const url = URL.createObjectURL(blob); const a = document.createElement('a');
    a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1500);
  }
  function svgDocument(element) {
    const sources = [...element.querySelectorAll('svg')];
    if (!sources.length) throw new Error('请先预览有效乐谱');
    const ns = 'http://www.w3.org/2000/svg', root = document.createElementNS(ns, 'svg');
    let height = 0, width = 0;
    sources.forEach(source => {
      const copy = source.cloneNode(true), box = source.viewBox.baseVal;
      const w = box.width || source.getBoundingClientRect().width, h = box.height || source.getBoundingClientRect().height;
      copy.setAttribute('x', '0'); copy.setAttribute('y', String(height)); copy.setAttribute('width', String(w)); copy.setAttribute('height', String(h));
      copy.style.removeProperty('position'); root.appendChild(copy); height += h; width = Math.max(width, w);
    });
    root.setAttribute('xmlns', ns); root.setAttribute('width', String(width)); root.setAttribute('height', String(height));
    root.setAttribute('viewBox', `0 0 ${width} ${height}`); root.style.background = '#fff';
    return { text: new XMLSerializer().serializeToString(root), width, height };
  }
  async function exportFile(kind, element, abc) {
    if (kind === 'abc') return download(new Blob([abc], { type: 'text/plain;charset=utf-8' }), 'score.abc');
    if (kind === 'midi') {
      const lib = await library(), data = lib.synth.getMidiFile(abc, { midiOutputType: 'binary' });
      if (!data?.[0]) throw new Error('没有可导出的 MIDI');
      return download(new Blob([data[0]], { type: 'audio/midi' }), 'score.mid');
    }
    const svg = svgDocument(element);
    if (kind === 'svg') return download(new Blob([svg.text], { type: 'image/svg+xml' }), 'score.svg');
    if (kind === 'png') {
      const scale = Math.min(2, 12000 / Math.max(svg.width, svg.height));
      const canvas = document.createElement('canvas'); canvas.width = Math.ceil(svg.width * scale); canvas.height = Math.ceil(svg.height * scale);
      const ctx = canvas.getContext('2d'), image = new Image(), url = URL.createObjectURL(new Blob([svg.text], { type: 'image/svg+xml' }));
      try {
        await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = () => reject(new Error('乐谱图片导出失败')); image.src = url; });
        ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height); ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
        const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
        if (!blob) throw new Error('乐谱尺寸过大'); download(blob, 'score.png');
      } finally { URL.revokeObjectURL(url); }
    } else if (kind === 'pdf') {
      // The native print dialog owns PDF destination; no silent filesystem writes.
      const frame = document.createElement('iframe'); frame.hidden = true; document.body.appendChild(frame);
      const doc = frame.contentDocument;
      doc.title = '乐谱'; const parsed = new DOMParser().parseFromString(svg.text, 'image/svg+xml');
      doc.body.appendChild(doc.importNode(parsed.documentElement, true));
      const style = doc.createElement('style'); style.textContent = '@page{size:A4;margin:12mm}svg{width:100%;height:auto}'; doc.head.appendChild(style);
      frame.contentWindow.addEventListener('afterprint', () => frame.remove(), { once: true });
      frame.contentWindow.focus(); frame.contentWindow.print(); setTimeout(() => frame.remove(), 60000);
    }
  }
  window.DesktopMusicScore = Object.freeze({ library, render, exportFile, download, selectVoice });
})();

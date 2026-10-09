// 本地文件 MIME/内容识别与读取、外部地址/HTML/拖放/剪贴板输入、图片节点插入替换回流及历史/视频资产导入；保持现有 API 适配、失败回退和返回值。
// Explicit host callbacks preserve ordering; shared state ports always resolve the live value.
// No API/schema changes. Load before desktop-canvas.js; create() has no I/O or event binding.
(function () {
  function create({
    DEFAULT_IMAGE_LONGEST_SIDE,
    LOCAL_IMAGE_EXTENSION_MIME,
    LOCAL_IMAGE_MIME_EXTENSION,
    MAX_EXTERNAL_IMAGE_IMPORTS,
    MAX_IMAGE_NODE_WIDTH,
    MIN_IMAGE_NODE_WIDTH,
    SUPPORTED_LOCAL_IMAGE_TEXT,
    addNode,
    applyNodeLayout,
    connectNodes,
    els,
    ensureGraphDom,
    findDefaultInputNodeId,
    fitVideoNodeToMedia,
    getNodeBoundsById,
    getNodeElement,
    getNodeReferenceImages,
    getViewportCenterWorldPoint,
    lastCanvasPointerRef,
    nextNodeId,
    openImageEditor,
    refreshImageNodeContent,
    refreshVideoNode,
    renderNodeReferenceThumbs,
    renderReferenceThumbs,
    screenToWorld,
    selectNode,
    updateLinkPath,
  }) {


    function fileToDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(new Error('图片读取失败'));
      reader.readAsDataURL(file);
    });
  }

    function readImageMeta(dataUrl) {
    return new Promise(resolve => {
      const img = new Image();
      img.onload = () => resolve({
        width: img.naturalWidth || 1,
        height: img.naturalHeight || 1
      });
      img.onerror = () => resolve({ width: 1, height: 1 });
      img.src = dataUrl;
    });
  }

    function readImageMetaStrict(dataUrl, filename = '') {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        const width = Number(img.naturalWidth || 0);
        const height = Number(img.naturalHeight || 0);
        if (width > 0 && height > 0) {
          resolve({ width, height });
          return;
        }
        reject(new Error(`无法读取“${filename || '图片'}”，请使用 ${SUPPORTED_LOCAL_IMAGE_TEXT}。`));
      };
      img.onerror = () => reject(new Error(`无法读取“${filename || '图片'}”，请使用 ${SUPPORTED_LOCAL_IMAGE_TEXT}。`));
      img.src = dataUrl;
    });
  }

    function localImageExtension(filename = '') {
    const match = String(filename || '').trim().toLowerCase().match(/\.([a-z0-9]+)$/);
    return match ? match[1] : '';
  }

    function localImageMimeFromName(filename = '') {
    return LOCAL_IMAGE_EXTENSION_MIME[localImageExtension(filename)] || '';
  }

    function localImageFilename(file, mimeType, fallbackPrefix = '图片') {
    const originalName = String(file?.name || '')
      .replace(/[\x00-\x1f<>:"/\\|?*]+/g, '_')
      .trim()
      .slice(0, 180);
    const originalExtension = localImageExtension(originalName);
    const normalizedMime = String(mimeType || '').toLowerCase() === 'image/jpg' ? 'image/jpeg' : String(mimeType || '').toLowerCase();
    if (originalName && LOCAL_IMAGE_EXTENSION_MIME[originalExtension] === normalizedMime) return originalName;
    const extension = LOCAL_IMAGE_MIME_EXTENSION[String(mimeType || '').toLowerCase()] || 'png';
    const stem = originalName
      ? originalName.replace(/\.[^.]+$/, '').trim()
      : `${fallbackPrefix}-${new Date().toISOString().replace(/[:.]/g, '-').replace('T', '-').replace('Z', '')}`;
    return `${stem || fallbackPrefix}.${extension}`;
  }

    async function sniffLocalImageMime(blob) {
    if (!blob || typeof blob.slice !== 'function') return '';
    let head;
    try {
      head = new Uint8Array(await blob.slice(0, 4096).arrayBuffer());
    } catch (error) {
      return '';
    }
    const hasBytes = (...bytes) => bytes.every((value, index) => head[index] === value);
    if (head.length >= 8 && hasBytes(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)) return 'image/png';
    if (head.length >= 3 && hasBytes(0xff, 0xd8, 0xff)) return 'image/jpeg';
    if (head.length >= 6) {
      const signature = String.fromCharCode(...head.slice(0, 6));
      if (signature === 'GIF87a' || signature === 'GIF89a') return 'image/gif';
    }
    if (head.length >= 12) {
      const riff = String.fromCharCode(...head.slice(0, 4));
      const webp = String.fromCharCode(...head.slice(8, 12));
      if (riff === 'RIFF' && webp === 'WEBP') return 'image/webp';
    }
    if (head.length >= 2 && hasBytes(0x42, 0x4d)) return 'image/bmp';
    if (head.length >= 4 && hasBytes(0x00, 0x00, 0x01, 0x00)) return 'image/x-icon';
    if (head.length >= 16) {
      const box = String.fromCharCode(...head.slice(4, 8));
      const brands = String.fromCharCode(...head.slice(8, 32));
      if (box === 'ftyp' && /avif|avis/.test(brands)) return 'image/avif';
    }
    try {
      const text = new TextDecoder('utf-8').decode(head).replace(/^\uFEFF/, '').trimStart().toLowerCase();
      if (text.startsWith('<svg') || (text.startsWith('<?xml') && text.slice(0, 2048).includes('<svg'))) {
        return 'image/svg+xml';
      }
    } catch (error) {}
    return '';
  }

    async function prepareLocalImageFile(file, fallbackPrefix = '图片') {
    if (!file || typeof file.slice !== 'function') {
      throw new Error(`请选择 ${SUPPORTED_LOCAL_IMAGE_TEXT} 文件。`);
    }
    const declaredMime = String(file.type || '').trim().toLowerCase();
    const namedMime = localImageMimeFromName(file.name);
    const sniffedMime = await sniffLocalImageMime(file);
    const mimeType = sniffedMime || (declaredMime.startsWith('image/') ? declaredMime : namedMime);
    if (!mimeType || !mimeType.startsWith('image/')) {
      throw new Error(`“${file.name || '拖入的内容'}”不是支持的图片文件。`);
    }
    const filename = localImageFilename(file, mimeType, fallbackPrefix);
    const typedBlob = declaredMime === mimeType ? file : file.slice(0, file.size, mimeType);
    const imageData = await fileToDataUrl(typedBlob);
    const meta = await readImageMetaStrict(imageData, filename);
    return {
      file,
      filename,
      mimeType,
      imageData,
      meta
    };
  }

    async function imageUrlToDataUrl(url) {
    const response = await fetch(url, { credentials: 'same-origin' });
    if (!response.ok) throw new Error('历史图片读取失败');
    const blob = await response.blob();
    return fileToDataUrl(blob);
  }

    function getImageNodeSize(meta) {
    const aspectRatio = Math.max(0.08, (meta?.width || 1) / Math.max(1, meta?.height || 1));
    const longestSide = DEFAULT_IMAGE_LONGEST_SIDE;
    let width = aspectRatio >= 1 ? longestSide : longestSide * aspectRatio;
    let height = aspectRatio >= 1 ? longestSide / aspectRatio : longestSide;
    if (width < MIN_IMAGE_NODE_WIDTH) {
      width = MIN_IMAGE_NODE_WIDTH;
      height = width / aspectRatio;
    }
    if (height > MAX_IMAGE_NODE_WIDTH) {
      height = MAX_IMAGE_NODE_WIDTH;
      width = height * aspectRatio;
    }
    return { width, height, aspectRatio };
  }

    function getImageNodeCenter(clientX, clientY) {
    if (Number.isFinite(clientX) && Number.isFinite(clientY)) {
      return screenToWorld(clientX, clientY);
    }
    const rect = els.deskCanvasViewport?.getBoundingClientRect();
    return rect
      ? screenToWorld(rect.left + rect.width / 2, rect.top + rect.height / 2)
      : { x: 260, y: 220 };
  }

    function triggerImageNodePopIn(nodeId, index = 0, options = {}) {
    const node = getNodeElement(nodeId);
    if (!node) return;
    const bounds = getNodeBoundsById(nodeId);
    const origin = options.popOrigin || null;
    const hasOrigin = bounds
      && Number.isFinite(Number(origin?.x))
      && Number.isFinite(Number(origin?.y));
    const dx = hasOrigin
      ? Number(origin.x) - (bounds.x + bounds.width / 2)
      : -42 - Math.min(140, Math.max(0, index) * 8);
    const dy = hasOrigin
      ? Number(origin.y) - (bounds.y + bounds.height / 2)
      : -72 - (Math.max(0, index) % 4) * 12;
    const rot = ((Math.max(0, index) % 5) - 2) * 3;
    node.style.setProperty('--desk-pop-x', `${dx}px`);
    node.style.setProperty('--desk-pop-y', `${dy}px`);
    node.style.setProperty('--desk-pop-rot', `${rot}deg`);
    node.style.setProperty('--desk-pop-delay', `${Math.min(280, Math.max(0, index) * 60)}ms`);
    node.classList.remove('is-pop-enter');
    void node.offsetWidth;
    node.classList.add('is-pop-enter');
    const cleanup = () => {
      node.classList.remove('is-pop-enter');
      node.style.removeProperty('--desk-pop-x');
      node.style.removeProperty('--desk-pop-y');
      node.style.removeProperty('--desk-pop-rot');
      node.style.removeProperty('--desk-pop-delay');
      node.removeEventListener('animationend', cleanup);
    };
    node.addEventListener('animationend', cleanup);
  }

    function insertImageNode(source, center, options = {}) {
    const size = getImageNodeSize(source.meta);
    const count = Object.keys(DesktopState.state.canvas.nodes).length;
    const placementIndex = options.exactCenter ? 0 : count;
    const id = nextNodeId('image');
    const node = {
      id,
      type: 'image',
      x: center.x - size.width / 2 + placementIndex * 14,
      y: center.y - size.height / 2 + placementIndex * 10,
      width: size.width,
      height: size.height,
      aspectRatio: size.aspectRatio,
      imageData: source.imageData || '',
      imageUrl: source.imageUrl || '',
      imageName: source.imageName || '图片节点',
      mimeType: source.mimeType || 'image/png',
      sourceTaskId: source.taskId || '',
      sourceAssetId: source.assetId || source.asset_id || '',
      sourcePrompt: source.prompt || '',
      sourceTitle: source.title || source.imageName || '',
      sourceFile: source.file || '',
      sourceProvider: source.provider || '',
      sourceKind: source.source || ''
    };
    DesktopState.state.canvas.nodes[id] = node;
    ensureGraphDom();
    applyNodeLayout(id);
    selectNode(id);
    triggerImageNodePopIn(id, options.popIndex || 0, options);
    updateLinkPath();
    DesktopState.saveSettings();
    return id;
  }

    async function createImageNodeFromFiles(files, center = null, options = {}) {
    const candidates = Array.from(files || []);
    if (!candidates.length) return '';
    let lastError = null;
    for (const file of candidates) {
      try {
        const prepared = await prepareLocalImageFile(file, options.fallbackPrefix || '本地图片');
        return insertImageNode({
          imageData: prepared.imageData,
          imageName: prepared.filename,
          mimeType: prepared.mimeType,
          title: prepared.filename,
          file: prepared.filename,
          source: options.source || 'upload',
          imageUrl: options.imageUrl || '',
          meta: prepared.meta
        }, center || getImageNodeCenter(), options);
      } catch (error) {
        lastError = error;
      }
    }
    if (lastError) throw lastError;
    return '';
  }

    async function createImageNodesFromFiles(files, clientX, clientY, options = {}) {
    const allFiles = Array.from(files || []);
    if (!allFiles.length) return [];
    const origin = getImageNodeCenter(clientX, clientY);
    const hasScreenPoint = Number.isFinite(clientX) && Number.isFinite(clientY);
    const createdNodeIds = [];
    const errors = [];
    for (let index = 0; index < allFiles.length; index += 1) {
      const center = hasScreenPoint
        ? getImageNodeCenter(clientX + createdNodeIds.length * 28, clientY + createdNodeIds.length * 24)
        : { x: origin.x + createdNodeIds.length * 36, y: origin.y + createdNodeIds.length * 30 };
      try {
        const nodeId = await createImageNodeFromFiles([allFiles[index]], center, {
          ...options,
          exactCenter: true,
          popIndex: createdNodeIds.length
        });
        if (nodeId) createdNodeIds.push(nodeId);
      } catch (error) {
        errors.push(error);
      }
    }
    if (createdNodeIds.length && !options.silent) {
      const ignoredCount = errors.length;
      const successLabel = options.successLabel || '本地图片';
      const createdText = createdNodeIds.length === 1
        ? `${successLabel}已创建为图片节点。`
        : `${createdNodeIds.length} 张${successLabel}已创建为图片节点。`;
      DesktopResults.showTransientMessage(ignoredCount ? `${createdText} 其他文件未导入。` : createdText);
    }
    if (!createdNodeIds.length && errors.length && !options.suppressErrors) throw errors[0];
    return createdNodeIds;
  }

    function externalImageNameFromUrl(source) {
    if (/^(?:data|blob):/i.test(String(source || '').trim())) return '';
    try {
      const parsed = new URL(String(source || ''), window.location.href);
      const name = decodeURIComponent(parsed.pathname.split('/').pop() || '').trim();
      return name.slice(0, 180) || '';
    } catch (error) {
      return '';
    }
  }

    async function prepareExternalImageSource(source, fallbackPrefix = '拖入图片') {
    const normalizedSource = normalizeExternalImageUrl(source);
    if (!normalizedSource) throw new Error('拖入内容中没有可读取的图片地址。');
    let blob = null;
    let filename = externalImageNameFromUrl(normalizedSource);
    if (/^data:image\//i.test(normalizedSource) || /^blob:/i.test(normalizedSource)) {
      try {
        const response = await fetch(normalizedSource);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        blob = await response.blob();
      } catch (error) {
        throw new Error('这个虚拟图片地址无法直接读取，请复制图片后在画布按 Ctrl+V。');
      }
    } else {
      const parsed = new URL(normalizedSource);
      if (parsed.origin === window.location.origin) {
        const dataUrl = await DesktopApi.imageUrlToDataUri(`${parsed.pathname}${parsed.search}${parsed.hash}`);
        blob = await (await fetch(dataUrl)).blob();
      } else {
        if (typeof DesktopApi.importImageUrl !== 'function') throw new Error('当前版本不支持远程图片拖入。');
        const imported = await DesktopApi.importImageUrl(normalizedSource);
        blob = imported.blob;
        filename = imported.filename || filename;
      }
    }
    const file = new File([blob], filename || fallbackPrefix, {
      type: blob.type || '',
      lastModified: Date.now()
    });
    const prepared = await prepareLocalImageFile(file, fallbackPrefix);
    return {
      ...prepared,
      sourceUrl: /^https?:\/\//i.test(normalizedSource) ? normalizedSource : ''
    };
  }

    async function createImageNodesFromExternalSources(sources, clientX, clientY, options = {}) {
    const candidates = Array.from(sources || []).slice(0, MAX_EXTERNAL_IMAGE_IMPORTS);
    const createdNodeIds = [];
    const errors = [];
    const origin = getImageNodeCenter(clientX, clientY);
    const hasScreenPoint = Number.isFinite(clientX) && Number.isFinite(clientY);
    for (const source of candidates) {
      try {
        const prepared = await prepareExternalImageSource(source, options.fallbackPrefix || '拖入图片');
        const center = hasScreenPoint
          ? getImageNodeCenter(clientX + createdNodeIds.length * 28, clientY + createdNodeIds.length * 24)
          : { x: origin.x + createdNodeIds.length * 36, y: origin.y + createdNodeIds.length * 30 };
        const nodeId = insertImageNode({
          imageData: prepared.imageData,
          imageUrl: prepared.sourceUrl,
          imageName: prepared.filename,
          mimeType: prepared.mimeType,
          title: prepared.filename,
          file: prepared.filename,
          source: options.source || 'external-drop',
          meta: prepared.meta
        }, center, {
          exactCenter: true,
          popIndex: createdNodeIds.length
        });
        createdNodeIds.push(nodeId);
      } catch (error) {
        errors.push(error);
      }
    }
    if (!createdNodeIds.length && errors.length) throw errors[0];
    if (createdNodeIds.length && !options.silent) {
      const label = options.successLabel || '拖入图片';
      const text = createdNodeIds.length === 1
        ? `${label}已创建为图片节点。`
        : `${createdNodeIds.length} 张${label}已创建为图片节点。`;
      DesktopResults.showTransientMessage(errors.length ? `${text} 其他内容未导入。` : text);
    }
    return createdNodeIds;
  }

    async function addExternalImageSourcesToNode(nodeId, sources, options = {}) {
    const refs = getNodeReferenceImages(nodeId);
    const remaining = Math.max(0, 8 - refs.length);
    if (!remaining) {
      DesktopResults.showTransientMessage('最多支持 8 张参考图。');
      return 0;
    }
    const preparedImages = [];
    const errors = [];
    for (const source of Array.from(sources || []).slice(0, remaining)) {
      try {
        preparedImages.push(await prepareExternalImageSource(source, options.fallbackPrefix || '拖入参考图'));
      } catch (error) {
        errors.push(error);
      }
    }
    preparedImages.forEach((prepared, index) => {
      refs.push({
        id: `external:${prepared.sourceUrl || prepared.filename}:${Date.now()}:${index}`,
        name: prepared.filename,
        title: prepared.filename,
        type: prepared.mimeType,
        url: prepared.imageData,
        base64: prepared.imageData,
        imageData: prepared.imageData,
        imageUrl: prepared.sourceUrl,
        source: options.source || 'external-drop',
        file: prepared.filename
      });
    });
    if (!preparedImages.length && errors.length) throw errors[0];
    if (preparedImages.length) {
      renderNodeReferenceThumbs(nodeId);
      DesktopState.saveSettings();
    }
    return preparedImages.length;
  }

    async function replaceImageNodeFromFiles(nodeId, files) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    const file = Array.from(files || [])[0];
    if (!node || node.type !== 'image' || !file) return '';
    const prepared = await prepareLocalImageFile(file, '替换图片');
    node.imageData = prepared.imageData;
    node.imageUrl = '';
    node.imageName = prepared.filename || '图片节点';
    node.mimeType = prepared.mimeType;
    node.aspectRatio = Math.max(0.08, (prepared.meta.width || 1) / Math.max(1, prepared.meta.height || 1));
    if (!node.width || !node.height) {
      const size = getImageNodeSize(prepared.meta);
      node.width = size.width;
      node.height = size.height;
    } else {
      node.height = node.width / node.aspectRatio;
    }
    node.sourceKind = 'upload';
    node.sourceTaskId = '';
    node.sourceAssetId = '';
    node.sourcePrompt = '';
    node.sourceTitle = prepared.filename || '';
    node.sourceFile = prepared.filename || '';
    node.sourceProvider = '';
    node.editState = {};
    refreshImageNodeContent(nodeId);
    DesktopState.saveSettings();
    return nodeId;
  }

    async function setImageNodeFromResult(nodeId, resultNodeId, output, index = 0) {
    const node = DesktopState.state.canvas.nodes[nodeId];
    if (!node || node.type !== 'image' || !output?.imagePaths?.length) return false;
    const safeIndex = Math.max(0, Number(index) || 0);
    const imageUrl = output.imagePaths[safeIndex] || output.imagePaths[0];
    const primaryFile = output.files?.[safeIndex] || output.primaryFile || imageUrl.split('/').pop() || '';
    node.imageData = '';
    node.imageUrl = imageUrl;
    node.imageName = primaryFile || '生成结果';
    node.mimeType = 'image/png';
    node.sourceKind = 'result-node';
    node.sourceTaskId = output.taskId || '';
    node.sourceAssetId = '';
    node.sourcePrompt = output.prompt || '';
    node.sourceTitle = primaryFile || '生成结果';
    node.sourceFile = primaryFile || '';
    node.sourceProvider = output.type || '';
    node.editState = {};
    try {
      const meta = await readImageMeta(imageUrl);
      node.aspectRatio = Math.max(0.08, (meta.width || 1) / Math.max(1, meta.height || 1));
      if (!node.width || !node.height) {
        const size = getImageNodeSize(meta);
        node.width = size.width;
        node.height = size.height;
      } else {
        node.height = node.width / node.aspectRatio;
      }
    } catch (e) {}
    refreshImageNodeContent(nodeId);
    updateLinkPath();
    DesktopState.saveSettings();
    return true;
  }

    async function createImageNodeFromResult(resultNodeId = 'output', index = 0) {
    const output = DesktopState.state.outputs?.[resultNodeId] || (resultNodeId === 'output' ? DesktopState.state.output : null);
    const safeIndex = Math.max(0, Number(index) || 0);
    const imageUrl = output?.imagePaths?.[safeIndex] || output?.primaryImagePath || output?.imagePaths?.[0] || '';
    if (!imageUrl) throw new Error('结果节点没有可回流的图片');
    const meta = await readImageMeta(imageUrl);
    const sourceBounds = getNodeBoundsById(resultNodeId);
    const center = sourceBounds
      ? {
          x: sourceBounds.x + sourceBounds.width + 210,
          y: sourceBounds.y + Math.min(sourceBounds.height * 0.5, 280)
        }
      : getViewportCenterWorldPoint(360, 0);
    const file = output?.files?.[safeIndex] || output?.primaryFile || imageUrl.split('/').pop() || '';
    const nodeId = insertImageNode({
      imageUrl,
      imageName: file || '生成结果',
      mimeType: 'image/png',
      taskId: output?.taskId || '',
      prompt: output?.prompt || '',
      title: file || '生成结果',
      file,
      provider: output?.type || '',
      source: 'result-node',
      meta
    }, center);
    DesktopResults.showTransientMessage('结果图已回流到画布。');
    return nodeId;
  }

    async function createImageNodeFromHistoryItem(item, clientX, clientY) {
    const imageUrl = String(item?.imageUrl || item?.imagePath || '').trim();
    if (!imageUrl) throw new Error('这条历史记录没有可拖入画布的图片');
    let imageData = '';
    try {
      imageData = await imageUrlToDataUrl(imageUrl);
    } catch (error) {
      imageData = '';
      DesktopResults.showTransientMessage('已创建图片节点；该历史图暂不能作为参考图提交。');
    }
    const displayUrl = imageData || imageUrl;
    const meta = await readImageMeta(displayUrl);
    return insertImageNode({
      imageData,
      imageUrl,
      imageName: item?.title || item?.prompt || item?.taskId || '历史图片',
      mimeType: imageData.startsWith('data:') ? imageData.slice(5, imageData.indexOf(';')) : 'image/png',
      taskId: item?.taskId || '',
      assetId: item?.assetId || item?.asset_id || item?.id || '',
      prompt: item?.prompt || '',
      title: item?.title || '',
      file: item?.file || '',
      provider: item?.provider || '',
      source: item?.source || 'gallery',
      meta
    }, getImageNodeCenter(clientX, clientY));
  }

    async function continueEditFromHistoryItem(item, clientX, clientY) {
    const imageNodeId = await createImageNodeFromHistoryItem(item, clientX, clientY);
    const inputNodeId = findDefaultInputNodeId();
    connectNodes(imageNodeId, inputNodeId);
    await openImageEditor(imageNodeId);
    DesktopResults.showTransientMessage('已创建继续编辑流程。');
    return { imageNodeId, inputNodeId };
  }

    async function addFiles(files) {
    const nextFiles = Array.from(files || []).filter(file => file.type.startsWith('image/'));
    if (!nextFiles.length) return;
    const remaining = Math.max(0, 8 - DesktopState.state.referenceImages.length);
    const selected = nextFiles.slice(0, remaining);
    const images = await Promise.all(selected.map(async file => ({
      id: `upload:${file.name}:${file.size}:${file.lastModified || Date.now()}`,
      name: file.name,
      type: file.type,
      url: URL.createObjectURL(file),
      base64: await fileToDataUrl(file),
      imageData: '',
      imageUrl: '',
      source: 'upload'
    })));
    DesktopState.state.referenceImages.push(...images);
    renderReferenceThumbs();
    DesktopState.saveSettings();
  }

    async function addFilesToNode(nodeId, files) {
    const nextFiles = Array.from(files || []);
    if (!nextFiles.length) return 0;
    const refs = getNodeReferenceImages(nodeId);
    const remaining = Math.max(0, 8 - refs.length);
    if (!remaining) {
      DesktopResults.showTransientMessage('最多支持 8 张参考图。');
      return 0;
    }
    const images = [];
    const errors = [];
    for (const file of nextFiles) {
      if (images.length >= remaining) break;
      try {
        const prepared = await prepareLocalImageFile(file, '参考图');
        images.push({
          id: `upload:${prepared.filename}:${file.size}:${file.lastModified || Date.now()}`,
          name: prepared.filename,
          title: prepared.filename,
          type: prepared.mimeType,
          url: prepared.imageData,
          base64: prepared.imageData,
          imageData: prepared.imageData,
          imageUrl: '',
          source: 'upload',
          file: prepared.filename
        });
      } catch (error) {
        errors.push(error);
      }
    }
    if (!images.length && errors.length) throw errors[0];
    refs.push(...images);
    renderNodeReferenceThumbs(nodeId);
    DesktopState.saveSettings();
    return images.length;
  }

    function isLocalImageFile(file) {
    const type = String(file?.type || '').toLowerCase();
    return type.startsWith('image/') || !!localImageMimeFromName(file?.name);
  }

    function hasLocalFileDragPayload(dataTransfer) {
    const types = Array.from(dataTransfer?.types || []);
    if (types.includes('Files')) return true;
    return Array.from(dataTransfer?.items || []).some(item => item?.kind === 'file');
  }

    function hasLocalImageDragPayload(dataTransfer) {
    return hasLocalFileDragPayload(dataTransfer);
  }

    function getLocalDragFiles(dataTransfer) {
    const files = Array.from(dataTransfer?.files || []);
    Array.from(dataTransfer?.items || []).forEach(item => {
      if (item?.kind !== 'file' || typeof item.getAsFile !== 'function') return;
      const file = item.getAsFile();
      if (file) files.push(file);
    });
    const seen = new Set();
    return files.filter(file => {
      const key = [file?.name || '', file?.size || 0, file?.lastModified || 0, file?.type || ''].join(':');
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

    function hasExternalImageTextDragPayload(dataTransfer) {
    const types = Array.from(dataTransfer?.types || []).map(type => String(type || '').toLowerCase());
    return types.includes('text/uri-list') || types.includes('text/html') || types.includes('text/plain');
  }

    function hasExternalImageDragPayload(dataTransfer) {
    return hasLocalFileDragPayload(dataTransfer) || hasExternalImageTextDragPayload(dataTransfer);
  }

    function readDroppedString(dataTransfer, mimeType) {
    const direct = String(dataTransfer?.getData?.(mimeType) || '').trim();
    if (direct) return Promise.resolve(direct);
    const item = Array.from(dataTransfer?.items || []).find(candidate => (
      candidate?.kind === 'string' && String(candidate?.type || '').toLowerCase() === mimeType
    ));
    if (!item || typeof item.getAsString !== 'function') return Promise.resolve('');
    return new Promise(resolve => item.getAsString(value => resolve(String(value || '').trim())));
  }

    function normalizeExternalImageUrl(value, allowRelative = false) {
    const raw = String(value || '').trim().replace(/^['"]|['"]$/g, '');
    if (!raw) return '';
    if (/^data:image\//i.test(raw) || /^blob:/i.test(raw)) return raw;
    if (!/^https?:\/\//i.test(raw) && !allowRelative) return '';
    try {
      const resolved = new URL(raw, window.location.href);
      return /^https?:$/i.test(resolved.protocol) ? resolved.href : '';
    } catch (error) {
      return '';
    }
  }

    function imageSourcesFromHtml(html) {
    if (!html) return [];
    try {
      const documentFragment = new DOMParser().parseFromString(html, 'text/html');
      const sources = [];
      documentFragment.querySelectorAll('img').forEach(image => {
        const source = image.getAttribute('src') || image.getAttribute('data-src') || '';
        if (source) sources.push(source);
        const srcset = String(image.getAttribute('srcset') || '').trim();
        if (srcset && !source) sources.push(srcset.split(',')[0].trim().split(/\s+/)[0]);
      });
      return sources;
    } catch (error) {
      return [];
    }
  }

    async function getExternalImageSources(dataTransfer) {
    const [html, uriList, plainText] = await Promise.all([
      readDroppedString(dataTransfer, 'text/html'),
      readDroppedString(dataTransfer, 'text/uri-list'),
      readDroppedString(dataTransfer, 'text/plain')
    ]);
    const candidates = [
      ...imageSourcesFromHtml(html).map(value => ({ value, allowRelative: true })),
      ...String(uriList || '').split(/\r?\n/).map(line => line.trim()).filter(line => line && !line.startsWith('#')).map(value => ({ value, allowRelative: false })),
      { value: String(plainText || '').trim(), allowRelative: false }
    ];
    const seen = new Set();
    const sources = [];
    candidates.forEach(candidate => {
      const source = normalizeExternalImageUrl(candidate.value, candidate.allowRelative);
      if (!source || seen.has(source) || sources.length >= MAX_EXTERNAL_IMAGE_IMPORTS) return;
      seen.add(source);
      sources.push(source);
    });
    return sources;
  }

    function captureExternalImageTransfer(dataTransfer) {
    return {
      files: getLocalDragFiles(dataTransfer),
      sourcesPromise: getExternalImageSources(dataTransfer)
    };
  }

    async function importCapturedImages(captured, options = {}) {
    const files = Array.from(captured?.files || []);
    const sourcesPromise = captured?.sourcesPromise || Promise.resolve([]);
    let fileError = null;
    if (options.referenceNodeId) {
      if (files.length) {
        try {
          const added = await addFilesToNode(options.referenceNodeId, files);
          if (added) {
            DesktopResults.showTransientMessage(added > 1 ? `${added} 张图片已添加为参考图。` : '图片已添加为参考图。');
            return added;
          }
        } catch (error) {
          fileError = error;
        }
      }
      const sources = await sourcesPromise;
      if (sources.length) {
        const added = await addExternalImageSourcesToNode(options.referenceNodeId, sources, {
          source: options.source || 'external-upload',
          fallbackPrefix: options.fallbackPrefix || '拖入参考图'
        });
        if (added) {
          DesktopResults.showTransientMessage(added > 1 ? `${added} 张图片已添加为参考图。` : '图片已添加为参考图。');
          return added;
        }
      }
      if (fileError) throw fileError;
      throw new Error(`没有找到可读取的图片，请使用 ${SUPPORTED_LOCAL_IMAGE_TEXT}，或复制图片后按 Ctrl+V。`);
    }

    if (files.length) {
      try {
        const nodeIds = await createImageNodesFromFiles(files, options.clientX, options.clientY, {
          source: options.fileSource || 'upload',
          suppressErrors: true,
          fallbackPrefix: options.fallbackPrefix,
          successLabel: options.successLabel
        });
        if (nodeIds.length) return nodeIds;
      } catch (error) {
        fileError = error;
      }
    }
    const sources = await sourcesPromise;
    if (sources.length) {
      return createImageNodesFromExternalSources(sources, options.clientX, options.clientY, {
        source: options.source || 'external-drop',
        fallbackPrefix: options.fallbackPrefix || '拖入图片',
        successLabel: options.successLabel || '拖入图片'
      });
    }
    if (fileError) throw fileError;
    throw new Error(`没有找到可读取的图片，请使用 ${SUPPORTED_LOCAL_IMAGE_TEXT}，或复制图片后按 Ctrl+V。`);
  }

    function hasClipboardImagePayload(dataTransfer) {
    if (!dataTransfer) return false;
    const files = getLocalDragFiles(dataTransfer);
    if (files.some(isLocalImageFile)) return true;
    const fileItems = Array.from(dataTransfer.items || []).filter(item => item?.kind === 'file');
    if (fileItems.some(item => !item.type || String(item.type).toLowerCase().startsWith('image/'))) return true;
    const html = String(dataTransfer.getData?.('text/html') || '');
    if (/<img\b/i.test(html)) return true;
    const uriList = String(dataTransfer.getData?.('text/uri-list') || '').split(/\r?\n/).find(line => line && !line.startsWith('#')) || '';
    if (normalizeExternalImageUrl(uriList)) return true;
    return !!normalizeExternalImageUrl(dataTransfer.getData?.('text/plain') || '');
  }

    function isEditablePasteTarget(target) {
    return !!target?.closest?.('input, textarea, select, [contenteditable="true"], [contenteditable="plaintext-only"]');
  }

    function handleCanvasImagePaste(event) {
    if (isEditablePasteTarget(event.target) || !hasClipboardImagePayload(event.clipboardData)) return;
    const viewport = els.deskCanvasViewport;
    const targetIsCanvas = !!viewport?.contains(event.target);
    if (!targetIsCanvas && !lastCanvasPointerRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    const captured = captureExternalImageTransfer(event.clipboardData);
    const rect = viewport?.getBoundingClientRect();
    const clientX = Number.isFinite(lastCanvasPointerRef.current?.x) ? lastCanvasPointerRef.current.x : (rect ? rect.left + rect.width / 2 : undefined);
    const clientY = Number.isFinite(lastCanvasPointerRef.current?.y) ? lastCanvasPointerRef.current.y : (rect ? rect.top + rect.height / 2 : undefined);
    importCapturedImages(captured, {
      clientX,
      clientY,
      source: 'clipboard',
      fileSource: 'clipboard',
      fallbackPrefix: '粘贴图片',
      successLabel: '粘贴图片'
    }).catch(error => DesktopResults.showError(error));
  }

    function hasHistoryDragPayload(dataTransfer) {
    const types = Array.from(dataTransfer?.types || []);
    return types.includes('application/x-desktop-history-image');
  }

    function hasGalleryDragPayload(dataTransfer) {
    const types = Array.from(dataTransfer?.types || []);
    return types.includes('application/x-desktop-gallery-images');
  }

    function getHistoryDragPayload(dataTransfer) {
    if (!hasHistoryDragPayload(dataTransfer)) return null;
    try {
      return JSON.parse(dataTransfer.getData('application/x-desktop-history-image') || '{}');
    } catch (e) {
      return null;
    }
  }

    function getGalleryDragPayload(dataTransfer) {
    if (!hasGalleryDragPayload(dataTransfer)) return [];
    try {
      const parsed = JSON.parse(dataTransfer.getData('application/x-desktop-gallery-images') || '[]');
      return Array.isArray(parsed) ? parsed.filter(item => item?.imageUrl || item?.imagePath) : [];
    } catch (e) {
      return [];
    }
  }

    async function createImageNodesFromHistoryItems(items, clientX, clientY) {
    const payloads = (Array.isArray(items) ? items : [items]).filter(item => item?.imageUrl || item?.imagePath);
    let created = 0;
    for (let index = 0; index < payloads.length; index += 1) {
      const x = Number.isFinite(clientX) ? clientX + index * 28 : undefined;
      const y = Number.isFinite(clientY) ? clientY + index * 24 : undefined;
      await createImageNodeFromHistoryItem(payloads[index], x, y);
      created += 1;
    }
    return created;
  }

    function createVideoNodeFromAsset(item, clientX, clientY) {
    const mediaUrl = String(item?.mediaUrl || item?.videoUrl || item?.url || '').trim();
    if (!mediaUrl) throw new Error('视频资产没有可播放地址');
    const worldPoint = Number.isFinite(clientX) && Number.isFinite(clientY)
      ? screenToWorld(clientX, clientY)
      : getViewportCenterWorldPoint();
    const nodeId = addNode('video', worldPoint);
    const node = DesktopState.state.canvas.nodes[nodeId];
    if (!node) throw new Error('视频节点创建失败');
    node.mediaUrl = mediaUrl;
    node.posterUrl = String(item?.posterUrl || item?.poster_url || '').trim();
    node.mediaName = String(item?.mediaName || item?.name || item?.filename || '视频资产');
    node.mimeType = String(item?.mimeType || item?.mime_type || 'video/mp4');
    node.sourceTaskId = String(item?.sourceTaskId || item?.source_task_id || item?.taskId || item?.task_id || '');
    node.durationSeconds = Math.max(0, Number(item?.durationSeconds || item?.duration_seconds || 0));
    node.mediaWidth = Math.max(0, Number(item?.mediaWidth || item?.media_width || item?.width || 0));
    node.mediaHeight = Math.max(0, Number(item?.mediaHeight || item?.media_height || item?.height || 0));
    node.fps = Math.max(1, Number(item?.fps || 24));
    node.fileSize = Math.max(0, Number(item?.fileSize || item?.file_size || item?.size_bytes || 0));
    node.status = 'succeeded';
    fitVideoNodeToMedia(node);
    refreshVideoNode(nodeId);
    selectNode(nodeId);
    DesktopState.saveSettings();
    return nodeId;
  }

    return Object.freeze({
      fileToDataUrl,
      readImageMeta,
      readImageMetaStrict,
      localImageExtension,
      localImageMimeFromName,
      localImageFilename,
      sniffLocalImageMime,
      prepareLocalImageFile,
      imageUrlToDataUrl,
      getImageNodeSize,
      getImageNodeCenter,
      triggerImageNodePopIn,
      insertImageNode,
      createImageNodeFromFiles,
      createImageNodesFromFiles,
      externalImageNameFromUrl,
      prepareExternalImageSource,
      createImageNodesFromExternalSources,
      addExternalImageSourcesToNode,
      replaceImageNodeFromFiles,
      setImageNodeFromResult,
      createImageNodeFromResult,
      createImageNodeFromHistoryItem,
      continueEditFromHistoryItem,
      addFiles,
      addFilesToNode,
      isLocalImageFile,
      hasLocalFileDragPayload,
      hasLocalImageDragPayload,
      getLocalDragFiles,
      hasExternalImageTextDragPayload,
      hasExternalImageDragPayload,
      readDroppedString,
      normalizeExternalImageUrl,
      imageSourcesFromHtml,
      getExternalImageSources,
      captureExternalImageTransfer,
      importCapturedImages,
      hasClipboardImagePayload,
      isEditablePasteTarget,
      handleCanvasImagePaste,
      hasHistoryDragPayload,
      hasGalleryDragPayload,
      getHistoryDragPayload,
      getGalleryDragPayload,
      createImageNodesFromHistoryItems,
      createVideoNodeFromAsset,
    });
  }

  window.DesktopCanvasMediaImport = Object.freeze({ create });
})();

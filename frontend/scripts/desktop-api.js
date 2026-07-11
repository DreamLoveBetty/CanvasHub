(function () {
  function requireApi() {
    if (typeof api === 'undefined' || !api.json) {
      throw new Error('API helper 未加载');
    }
    return api;
  }

  function blobToDataUrl(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(new Error('图片读取失败'));
      reader.readAsDataURL(blob);
    });
  }

  function fileToDataUrl(file) {
    return blobToDataUrl(file);
  }

  async function imageUrlToDataUri(url) {
    if (!url) return '';
    if (String(url).startsWith('data:')) return String(url);
    const blob = await requireApi().blob(url);
    return blobToDataUrl(blob);
  }

  async function normalizeImages(images) {
    const converted = await Promise.all((images || []).map(async item => {
      const raw = item?.base64 || item?.url || '';
      return imageUrlToDataUri(raw);
    }));
    return converted.filter(Boolean);
  }

  function stableReferenceUrl(item) {
    const url = String(item?.imageUrl || item?.url || '').trim();
    if (!url || url.startsWith('blob:') || url.startsWith('data:')) return '';
    return url;
  }

  function normalizeLineageReferences(images) {
    const refs = [];
    const seen = new Set();
    (Array.isArray(images) ? images : []).forEach((item, index) => {
      const assetId = String(item?.assetId || item?.asset_id || '').trim();
      const taskId = String(item?.taskId || item?.task_id || '').trim();
      const imageUrl = stableReferenceUrl(item);
      const sourceNodeId = String(item?.sourceNodeId || '').trim();
      if (!assetId && !taskId && !imageUrl && !sourceNodeId) return;
      const key = assetId || ((taskId || imageUrl) ? `${taskId}:${imageUrl}` : '') || sourceNodeId;
      if (seen.has(key)) return;
      seen.add(key);
      refs.push({
        asset_id: assetId,
        task_id: taskId,
        image_url: imageUrl,
        title: String(item?.title || item?.name || item?.file || `参考图 ${index + 1}`).slice(0, 160),
        prompt: String(item?.prompt || '').slice(0, 500),
        file: String(item?.file || '').slice(0, 160),
        source: String(item?.source || '').slice(0, 48),
        source_node_id: sourceNodeId,
        index
      });
    });
    return refs.slice(0, 16);
  }

  function buildLineage(referenceImages) {
    const refs = normalizeLineageReferences(referenceImages);
    if (!refs.length) return null;
    return {
      reference_assets: refs,
      reference_asset_ids: [...new Set(refs.map(item => item.asset_id).filter(Boolean))],
      source_task_ids: [...new Set(refs.map(item => item.task_id).filter(Boolean))]
    };
  }

  async function submitTaskConfig(config = {}) {
    const provider = config.provider || 'gpt';
    const prompt = String(config.prompt || (provider === 'upscale' ? '高清放大' : '')).trim();
    if (!prompt) {
      throw new Error('请输入提示词');
    }

    const client = requireApi();
    const params = config.params || {};
    const outputControls = DesktopState.state.output || {};
    const archiveEnabled = params.archiveEnabled ?? params.archive_enabled ?? (outputControls.archiveEnabled !== false);
    const telegramEnabled = params.telegramEnabled ?? params.telegram_enabled ?? (outputControls.telegramEnabled !== false);
    const lineage = buildLineage(config.referenceImages || []);
    const images = await normalizeImages(config.referenceImages || []);

    if (provider === 'gpt') {
      const taskType = DesktopState.normalizeGptTaskType(params.gptTaskType, 'image');
      const body = {
        prompt,
        ratio: DesktopState.normalizeRatio(params.ratio, '9:16'),
        resolution: DesktopState.normalizeResolution(params.resolution, '2k'),
        quality: DesktopState.normalizeGptQuality(params.quality, 'auto'),
        image_count: DesktopState.clamp(params.imageCount, 1, 8, 1),
        moderation: DesktopState.normalizeModeration(params.moderation, 'auto'),
        task_type: taskType,
        prompt_mode: DesktopState.normalizePromptMode(params.promptMode, 'smart'),
        gpt_provider_route: taskType === 'image'
          ? DesktopState.normalizeGptProviderRoute(params.gptProviderRoute, DesktopState.state.params.gptProviderRoute || 'codex')
          : 'chatgpt_pool',
        use_third_party_api: taskType === 'image'
          ? DesktopState.normalizeGptProviderRoute(params.gptProviderRoute, DesktopState.state.params.gptProviderRoute || 'codex') === 'third_party_image_api'
          : false,
        main_model: DesktopState.normalizeGptMainModel(params.gptMainModel, DesktopState.state.params.gptMainModel || 'gpt-5.5'),
        reasoning_effort: DesktopState.normalizeReasoningEffort(params.reasoningEffort, DesktopState.state.params.reasoningEffort || 'medium'),
        archive_enabled: archiveEnabled,
        telegram_enabled: telegramEnabled
      };
      const endpoint = taskType === 'image' && images.length ? '/api/gpt/edit' : '/api/gpt/generate';
      if (images.length) {
        body.images = images;
        if (config.mask) body.mask = config.mask;
      }
      if (lineage) body.lineage = lineage;
      return client.json(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
    }

    if (provider === 'google') {
      const googleModel = typeof DesktopState.normalizeGoogleModel === 'function'
        ? DesktopState.normalizeGoogleModel(params.model)
        : (params.model || 'gemini-3.1-flash-image');
      const body = {
        prompt,
        ratio: DesktopState.normalizeRatio(params.ratio, '1:1'),
        quality: DesktopState.normalizeResolution(params.resolution, '2k'),
        model: googleModel,
        params: {
          archive_enabled: archiveEnabled,
          telegram_enabled: telegramEnabled
        }
      };
      if (images.length) {
        body.images = images;
        body.feature = 'edit';
      }
      if (lineage) body.lineage = lineage;
      return client.json(images.length ? '/edit' : '/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
    }

    if (provider === 'upscale') {
      if (!images.length) {
        throw new Error('请先连接或上传一张图片');
      }
      const body = {
        prompt,
        images: [images[0]],
        model: params.model || '4x-UltraSharp',
        tile_size: DesktopState.clamp(params.tileSize ?? params.tile_size, 64, 2048, 256),
        tile_overlap: DesktopState.clamp(params.tileOverlap ?? params.tile_overlap, 0, 256, 32),
        device: params.device || 'auto',
        archive_enabled: true,
        telegram_enabled: telegramEnabled
      };
      if (lineage) body.lineage = lineage;
      return client.json('/api/upscale/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
    }

    if (provider === 'comfy') {
      return client.json('/api/comfy/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt,
          ratio: DesktopState.normalizeRatio(params.ratio, '1:1'),
          workflow: params.workflow || ''
        })
      });
    }

    throw new Error(`暂不支持的模型：${provider}`);
  }

  async function submitCurrentTask() {
    const { state } = DesktopState;
    return submitTaskConfig({
      prompt: state.prompt,
      provider: state.provider,
      params: state.params,
      referenceImages: state.referenceImages
    });
  }

  function splitBatchPrompts(prompt) {
    return String(prompt || '')
      .split(/\n\s*\n|\r?\n/)
      .map(item => item.trim())
      .filter(Boolean);
  }

  function getBatchPrompts(config = {}) {
    const explicit = Array.isArray(config.batchPrompts)
      ? config.batchPrompts.map(item => String(item || '').trim()).filter(Boolean)
      : [];
    return explicit.length ? explicit : splitBatchPrompts(config.prompt);
  }

  async function submitBatchConfig(config = {}) {
    const prompts = getBatchPrompts(config);
    if (prompts.length < 2) throw new Error('批量模式至少需要 2 条提示词');
    if ((config.referenceImages || []).length) {
      throw new Error('批量第一版暂不支持带参考图的编辑任务');
    }
    const provider = config.provider || 'gpt';
    if (!['gpt', 'google'].includes(provider)) {
      throw new Error('批量第一版只支持 GPT 和 Google 纯生成任务');
    }
    const outputControls = DesktopState.state.output || {};
    const batchParams = { ...(config.params || {}) };
    if (batchParams.archiveEnabled == null && batchParams.archive_enabled == null) {
      batchParams.archive_enabled = outputControls.archiveEnabled !== false;
    }
    if (batchParams.telegramEnabled == null && batchParams.telegram_enabled == null) {
      batchParams.telegram_enabled = outputControls.telegramEnabled !== false;
    }
    return requireApi().json('/api/tasks/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider,
        prompts,
        params: batchParams
      })
    });
  }

  function getStatus(taskId) {
    if (!taskId) return Promise.reject(new Error('缺少 task_id'));
    return requireApi().json(`/api/status/${encodeURIComponent(taskId)}`);
  }

  function getUpscaleModels() {
    return requireApi().json('/api/upscale/models');
  }

  function getBatch(batchId) {
    if (!batchId) return Promise.reject(new Error('缺少 batch_id'));
    return requireApi().json(`/api/batches/${encodeURIComponent(batchId)}`);
  }

  function controlBatch(batchId, action) {
    if (!batchId) return Promise.reject(new Error('缺少 batch_id'));
    if (!['pause', 'resume', 'cancel'].includes(action)) return Promise.reject(new Error('无效的批量操作'));
    return requireApi().json(`/api/batches/${encodeURIComponent(batchId)}/${action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
  }

  function cancelTask(taskId) {
    if (!taskId) return Promise.reject(new Error('缺少 task_id'));
    return requireApi().json(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
  }

  function retryTask(taskId) {
    if (!taskId) return Promise.reject(new Error('缺少 task_id'));
    return requireApi().json(`/api/tasks/${encodeURIComponent(taskId)}/retry`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
  }

  function getHistory(limit = 24, offset = 0) {
    return requireApi().json(`/api/history?limit=${limit}&offset=${offset}`);
  }

  function getAssets(options = {}) {
    const params = new URLSearchParams();
    params.set('limit', options.limit || 200);
    params.set('offset', options.offset || 0);
    if (options.query) params.set('query', options.query);
    if (options.filter) params.set('filter', options.filter);
    if (options.tag) params.set('tag', options.tag);
    if (options.ratio) params.set('ratio', options.ratio);
    if (options.orientation) params.set('orientation', options.orientation);
    if (options.format) params.set('format', options.format);
    if (options.resolution) params.set('resolution', options.resolution);
    if (options.includeHidden) params.set('include_hidden', '1');
    return requireApi().json(`/api/assets?${params.toString()}`);
  }

  function updateAssetMeta(assetId, patch = {}) {
    if (!assetId) return Promise.reject(new Error('缺少资产 ID'));
    return requireApi().json('/api/assets/meta', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        asset_id: assetId,
        ...patch
      })
    });
  }

  function listAssetSets(options = {}) {
    const params = new URLSearchParams();
    params.set('limit', options.limit || 80);
    params.set('offset', options.offset || 0);
    if (options.query) params.set('query', options.query);
    if (options.tag) params.set('tag', options.tag);
    return requireApi().json(`/api/assets/sets?${params.toString()}`);
  }

  function saveAssetSet(payload = {}) {
    return requireApi().json('/api/assets/sets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function deleteAssetSet(setId) {
    if (!setId) return Promise.reject(new Error('缺少候选集 ID'));
    return requireApi().json(`/api/assets/sets/${encodeURIComponent(setId)}`, {
      method: 'DELETE'
    });
  }

  function deleteAsset(assetId) {
    if (!assetId) return Promise.reject(new Error('缺少资产 ID'));
    return requireApi().json(`/api/assets/${encodeURIComponent(assetId)}`, {
      method: 'DELETE'
    });
  }

  function deleteAssets(assetIds) {
    const ids = (Array.isArray(assetIds) ? assetIds : [assetIds])
      .map(value => String(value || '').trim())
      .filter(Boolean);
    if (!ids.length) return Promise.reject(new Error('缺少资产 ID'));
    return requireApi().json('/api/assets/delete-batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ asset_ids: ids })
    });
  }

  function getAssetHealth() {
    return requireApi().json('/api/assets/health');
  }

  function listEditableFiles(options = {}) {
    const params = new URLSearchParams();
    params.set('limit', options.limit || 200);
    if (options.query) params.set('query', options.query);
    if (options.kind) params.set('kind', options.kind);
    if (options.includeLocal === false) params.set('include_local', '0');
    return requireApi().json(`/api/editable-files?${params.toString()}`);
  }

  function sendEditableFile(payload = {}) {
    return requireApi().json('/api/editable-files/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function deleteEditableFile(payload = {}) {
    return requireApi().json('/api/editable-files/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function getSystemDiagnostics() {
    return requireApi().json('/api/system/diagnostics');
  }

  function getSystemSettings() {
    return requireApi().json('/api/system/settings');
  }

  function saveSystemSettings(config = {}) {
    return requireApi().json('/api/system/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    });
  }

  function getGptConfig() {
    return requireApi().json('/api/gpt/config');
  }

  function getGptModels(refresh = false) {
    return requireApi().json(`/api/gpt/models${refresh ? '?refresh=1' : ''}`);
  }

  function saveGptConfig(config = {}) {
    return requireApi().json('/api/gpt/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    });
  }

  function getChatgptPoolStatus() {
    return requireApi().json('/api/gpt-pool/status');
  }

  function getChatgptPoolAccounts() {
    return requireApi().json('/api/gpt-pool/accounts');
  }

  function startChatgptPoolOAuth(payload = {}) {
    return requireApi().json('/api/gpt-pool/oauth/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function finishChatgptPoolOAuth(payload = {}) {
    return requireApi().json('/api/gpt-pool/oauth/finish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function openChatgptPoolOAuthClean(payload = {}) {
    return requireApi().json('/api/gpt-pool/oauth/open-clean', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function importChatgptPoolAccounts(payload = {}) {
    return requireApi().json('/api/gpt-pool/accounts/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function importLocalChatgptPoolAuth(payload = {}) {
    return requireApi().json('/api/gpt-pool/accounts/import-local-auth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function refreshChatgptPoolAccounts(payload = {}) {
    return requireApi().json('/api/gpt-pool/accounts/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function updateChatgptPoolAccount(payload = {}) {
    return requireApi().json('/api/gpt-pool/accounts/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function startChatgptPoolAccountVerification(payload = {}) {
    return requireApi().json('/api/gpt-pool/accounts/verify/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function completeChatgptPoolAccountVerification(payload = {}) {
    return requireApi().json('/api/gpt-pool/accounts/verify/complete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function deleteChatgptPoolAccounts(payload = {}) {
    return requireApi().json('/api/gpt-pool/accounts/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function getManagedCodexOAuthStatus() {
    return requireApi().json('/api/managed-codex-oauth/status');
  }

  function startManagedCodexOAuth(payload = {}) {
    return requireApi().json('/api/managed-codex-oauth/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function finishManagedCodexOAuth(payload = {}) {
    return requireApi().json('/api/managed-codex-oauth/finish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function refreshManagedCodexOAuth(payload = {}) {
    return requireApi().json('/api/managed-codex-oauth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function importManagedCodexOAuth(payload = {}) {
    return requireApi().json('/api/managed-codex-oauth/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function updateManagedCodexOAuthAccount(payload = {}) {
    return requireApi().json('/api/managed-codex-oauth/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function selectManagedCodexOAuthAccount(payload = {}) {
    return requireApi().json('/api/managed-codex-oauth/select', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function deleteManagedCodexOAuthAccount(payload = {}) {
    return requireApi().json('/api/managed-codex-oauth/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function logoutManagedCodexOAuth(payload = {}) {
    return requireApi().json('/api/managed-codex-oauth/logout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function getPromptConfig(provider = '') {
    const suffix = provider ? `?provider=${encodeURIComponent(provider)}` : '';
    return requireApi().json(`/api/prompt/config${suffix}`);
  }

  function getPromptModels(provider = '') {
    const suffix = provider ? `?provider=${encodeURIComponent(provider)}` : '';
    return requireApi().json(`/api/prompt/models${suffix}`);
  }

  function savePromptConfig(config = {}) {
    return requireApi().json('/api/prompt/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    });
  }

  function polishPromptText(payload = {}) {
    return requireApi().json('/api/prompt/polish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function promptChat(payload = {}) {
    return requireApi().json('/api/prompt/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function promptAssistantChat(payload = {}) {
    return requireApi().json('/api/prompt/assistant-chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  async function promptAssistantChatStream(payload = {}, handlers = {}) {
    const resp = await requireApi().request('/api/prompt/assistant-chat/stream', {
      method: 'POST',
      headers: {
        'Accept': 'application/x-ndjson',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });
    if (!resp.ok) {
      let detail = '';
      try {
        const data = await resp.json();
        detail = data?.error || data?.message || '';
      } catch (e) {
        try { detail = await resp.text(); } catch (_) {}
      }
      throw new Error(detail || `HTTP ${resp.status}`);
    }
    if (!resp.body || !resp.body.getReader) {
      throw new Error('当前浏览器不支持流式响应');
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let finalEvent = null;

    const handleLine = line => {
      const raw = String(line || '').trim();
      if (!raw) return null;
      let event = null;
      try {
        event = JSON.parse(raw);
      } catch (error) {
        throw new Error(`流式响应解析失败：${error.message}`);
      }
      const type = String(event?.type || '');
      if (type === 'meta') {
        handlers.onMeta?.(event);
      } else if (type === 'delta') {
        handlers.onDelta?.(String(event.text || ''), event);
      } else if (type === 'done') {
        finalEvent = event;
        handlers.onDone?.(event);
      } else if (type === 'error') {
        throw new Error(event.error || '流式响应失败');
      }
      return event;
    };

    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() || '';
      for (const line of lines) {
        const event = handleLine(line);
        if (event?.type === 'done') {
          try { await reader.cancel(); } catch (e) {}
          return finalEvent || event;
        }
      }
      if (done) break;
    }
    if (buffer.trim()) {
      const event = handleLine(buffer);
      if (event?.type === 'done') return finalEvent || event;
    }
    if (finalEvent) return finalEvent;
    throw new Error('流式响应提前结束');
  }

  function safeRewritePrompt(payload = {}) {
    return requireApi().json('/api/prompt/safe-rewrite', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function analyzePromptImage(payload = {}) {
    return requireApi().json('/api/prompt/image-analysis', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function generatePromptVersions(payload = {}) {
    return requireApi().json('/api/prompt/versions/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function getStylePresets() {
    return requireApi().json('/api/prompt/style-presets');
  }

  function saveStylePreset(payload = {}) {
    return requireApi().json('/api/prompt/style-presets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function extractStylePreset(payload = {}) {
    return requireApi().json('/api/prompt/style-presets/extract', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function savePromptVersion(payload = {}) {
    return requireApi().json('/api/prompt/versions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  function getPromptSources() {
    return requireApi().json('/api/prompt-sources');
  }

  function getPromptSourceItems(options = {}) {
    const params = new URLSearchParams();
    params.set('limit', options.limit || 300);
    params.set('offset', options.offset || 0);
    if (options.source) params.set('source', options.source);
    if (options.query) params.set('query', options.query);
    if (options.tag) params.set('tag', options.tag);
    if (options.style) params.set('style', options.style);
    if (options.subject) params.set('subject', options.subject);
    if (options.type) params.set('type', options.type);
    return requireApi().json(`/api/prompt-source-items?${params.toString()}`);
  }

  function syncPromptSource(source = 'all') {
    return requireApi().json('/api/prompt-sources/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source })
    });
  }

  function stopPromptSourceSync(runId) {
    return requireApi().json('/api/prompt-sources/stop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_id: runId })
    });
  }

  function getPromptSourceRun(runId) {
    if (!runId) return Promise.reject(new Error('缺少同步任务 ID'));
    return requireApi().json(`/api/prompt-sources/runs/${encodeURIComponent(runId)}`);
  }

  function cleanupAssetHealth() {
    return requireApi().json('/api/assets/health/cleanup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
  }

  function undoAssetDelete(batchIds) {
    const ids = Array.isArray(batchIds) ? batchIds : [batchIds];
    const cleanIds = ids.map(value => String(value || '').trim()).filter(Boolean);
    if (!cleanIds.length) return Promise.reject(new Error('没有可撤销的删除'));
    return requireApi().json('/api/assets/undo-delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch_ids: cleanIds })
    });
  }

  function exportTelegram(item) {
    const filename = item?.primaryFile || item?.result_file || item?.output_file || item?.filename || '';
    if (!filename) return Promise.reject(new Error('没有可发送的原图'));
    return requireApi().json('/api/history/export_tg', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        task_id: item.task_id || item.taskId || '',
        output_file: filename,
        type: item.type || 'gpt',
        prompt: item.prompt || DesktopState.state.prompt || ''
      })
    });
  }

  function exportTelegramImageData(item) {
    const imageData = String(item?.imageData || item?.image_data || item?.base64 || '').trim();
    if (!imageData) return Promise.reject(new Error('没有可发送的原图'));
    return requireApi().json('/api/history/export_tg', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_data: imageData,
        filename: item.filename || item.name || 'source.png',
        type: item.type || 'source',
        prompt: item.prompt || ''
      })
    });
  }

  function getImagePath(item) {
    const paths = item?.image_paths || item?.imagePaths || [];
    if (Array.isArray(paths) && paths.length) return paths[0];
    const filename = item?.result_file || item?.output_file || item?.primaryFile || '';
    if (!filename) return '';
    if ((item?.type || '').startsWith('gpt')) return `/gpt_outputs/${filename}`;
    return `/image/${filename}`;
  }

  function addCacheBuster(url, value) {
    if (!url) return '';
    const separator = String(url).includes('?') ? '&' : '?';
    return `${url}${separator}v=${encodeURIComponent(value || Date.now())}`;
  }

  async function saveLayoutDraft(payload = {}) {
    const draftId = String(payload.draftId || payload.draft_id || '').trim();
    const endpoint = draftId ? `/api/layout/drafts/${encodeURIComponent(draftId)}` : '/api/layout/drafts';
    const body = {
      title: payload.title || '排版工作区',
      node_id: payload.nodeId || payload.node_id || '',
      project: payload.project || {},
      preview_data_url: payload.previewDataUrl || payload.preview_data_url || '',
      export_data_url: payload.exportDataUrl || payload.export_data_url || ''
    };
    return requireApi().json(endpoint, {
      method: draftId ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
  }

  function loadLayoutDraft(draftId) {
    if (!draftId) return Promise.reject(new Error('缺少排版草稿 ID'));
    return requireApi().json(`/api/layout/drafts/${encodeURIComponent(draftId)}`);
  }

  function listLayoutDrafts(limit = 50, offset = 0) {
    return requireApi().json(`/api/layout/drafts?limit=${limit}&offset=${offset}`);
  }

  function listLayoutFonts() {
    return requireApi().json('/api/layout/fonts');
  }

  async function uploadLayoutAsset(draftId, file) {
    if (!draftId) throw new Error('缺少排版草稿 ID');
    if (!file) throw new Error('缺少图片文件');
    const dataUrl = await fileToDataUrl(file);
    return requireApi().json(`/api/layout/drafts/${encodeURIComponent(draftId)}/asset`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filename: file.name || 'image.png',
        data_url: dataUrl
      })
    });
  }

  function publishLayoutDraft(payload = {}) {
    const draftId = String(payload.draftId || payload.draft_id || '').trim();
    if (!draftId) return Promise.reject(new Error('缺少排版草稿 ID'));
    return requireApi().json(`/api/layout/drafts/${encodeURIComponent(draftId)}/publish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: payload.title || '排版导出',
        prompt: payload.prompt || payload.title || '排版导出',
        node_id: payload.nodeId || payload.node_id || '',
        data_url: payload.dataUrl || payload.data_url || ''
      })
    });
  }

  function getPoseAssetsStatus() {
    return requireApi().json('/api/pose/assets/status');
  }

  function saveWorkflowFileToPath(payload = {}) {
    return requireApi().json('/api/desktop/workflow/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  window.DesktopApi = {
    submitTaskConfig,
    submitBatchConfig,
    submitCurrentTask,
    getStatus,
    getUpscaleModels,
    getBatch,
    controlBatch,
    cancelTask,
    retryTask,
    getHistory,
    getAssets,
    updateAssetMeta,
    deleteAsset,
    deleteAssets,
    getAssetHealth,
    listEditableFiles,
    sendEditableFile,
    deleteEditableFile,
    getSystemDiagnostics,
    getSystemSettings,
    saveSystemSettings,
    getGptConfig,
    getGptModels,
    saveGptConfig,
    getChatgptPoolStatus,
    getChatgptPoolAccounts,
    startChatgptPoolOAuth,
    finishChatgptPoolOAuth,
    openChatgptPoolOAuthClean,
    importChatgptPoolAccounts,
    importLocalChatgptPoolAuth,
    refreshChatgptPoolAccounts,
    updateChatgptPoolAccount,
    startChatgptPoolAccountVerification,
    completeChatgptPoolAccountVerification,
    deleteChatgptPoolAccounts,
    getManagedCodexOAuthStatus,
    startManagedCodexOAuth,
    finishManagedCodexOAuth,
    refreshManagedCodexOAuth,
    importManagedCodexOAuth,
    updateManagedCodexOAuthAccount,
    selectManagedCodexOAuthAccount,
    deleteManagedCodexOAuthAccount,
    logoutManagedCodexOAuth,
    getPromptConfig,
    getPromptModels,
    savePromptConfig,
    polishPromptText,
    promptChat,
    promptAssistantChat,
    promptAssistantChatStream,
    safeRewritePrompt,
    analyzePromptImage,
    generatePromptVersions,
    getStylePresets,
    saveStylePreset,
    extractStylePreset,
    savePromptVersion,
    getPromptSources,
    getPromptSourceItems,
    syncPromptSource,
    stopPromptSourceSync,
    getPromptSourceRun,
    cleanupAssetHealth,
    undoAssetDelete,
    listAssetSets,
    saveAssetSet,
    deleteAssetSet,
    exportTelegram,
    exportTelegramImageData,
    getImagePath,
    addCacheBuster,
    saveLayoutDraft,
    loadLayoutDraft,
    listLayoutDrafts,
    listLayoutFonts,
    uploadLayoutAsset,
    publishLayoutDraft,
    getPoseAssetsStatus,
    saveWorkflowFileToPath,
    imageUrlToDataUri
  };
})();

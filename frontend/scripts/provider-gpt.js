// GPT provider flow
  function pickRatioGpt(val) {
    gptState.ratio = val;
    document.querySelectorAll('#gptRatioSection .r-btn').forEach(b => {
      b.classList.remove('selected');
      if ((b.dataset.ratioValue || b.textContent || '').trim() === val) b.classList.add('selected');
    });
    saveUiSettings();
  }

  function pickResolutionGpt(val) {
    gptState.resolution = val;
    document.querySelectorAll('#gptResolutionGroup .q-btn').forEach(b => {
      b.classList.remove('selected');
      if ((b.textContent || '').trim().toLowerCase() === val) b.classList.add('selected');
    });
    saveUiSettings();
  }

  function pickQualityGpt(val) {
    gptState.quality = val;
    document.querySelectorAll('#gptQualityGroup .q-btn, #cinematicGptQualityMenu .cinematic-pop-option').forEach(b => {
      b.classList.remove('selected', 'is-active');
      if ((b.dataset.gptQuality || '').trim().toLowerCase() === val) b.classList.add('selected', 'is-active');
    });
    saveUiSettings();
  }

  function pickModerationGpt(val) {
    const moderation = String(val || 'auto').trim().toLowerCase() === 'low' ? 'low' : 'auto';
    gptState.moderation = moderation;
    document.querySelectorAll('#gptModerationGroup .q-btn, #cinematicGptModerationMenu .cinematic-pop-option').forEach(b => {
      b.classList.remove('selected', 'is-active');
      if ((b.dataset.gptModeration || '').trim().toLowerCase() === moderation) b.classList.add('selected', 'is-active');
    });
    saveUiSettings();
  }

  function pickImageCountGpt(val) {
    const parsed = parseInt(val, 10);
    const count = Number.isFinite(parsed) ? Math.max(1, Math.min(8, parsed)) : 1;
    gptState.imageCount = count;
    document.querySelectorAll('#gptImageCountGroup .q-btn, #cinematicGptCountMenu .cinematic-pop-option').forEach(b => {
      b.classList.remove('selected', 'is-active');
      if (parseInt(b.dataset.gptCount || '0', 10) === count) b.classList.add('selected', 'is-active');
    });
    saveUiSettings();
  }

  function normalizeGptProviderRouteForUi(value) {
    const route = String(value || '').trim().toLowerCase();
    if (['managed_codex_oauth', 'managed_codex', 'managed_oauth', 'codex_oauth', 'oauth_codex'].includes(route)) return 'codex';
    if (['chatgpt_pool', 'pool', 'sidecar', 'web_api', 'account_pool'].includes(route)) return 'chatgpt_pool';
    if (['third_party_image_api', 'third_party_api', 'third_party', 'external_api', 'yunwu'].includes(route)) return 'third_party_image_api';
    return 'codex';
  }

  function pickProviderRouteGpt(value) {
    const route = normalizeGptProviderRouteForUi(value || (gptState.useThirdPartyApi ? 'third_party_image_api' : gptState.gptProviderRoute));
    gptState.gptProviderRoute = route;
    delete gptState.useThirdPartyApi;
    const select = document.getElementById('gptProviderRouteSelect');
    if (select) select.value = route;
    saveUiSettings();
  }

  function submitGpt() {
    let prompt = document.getElementById('gptPrompt').value.trim();
    if (!prompt) {
      alert('请输入 Prompt');
      return;
    }
    
    // 自动解码 URL 编码的提示词（将%20 等转换为原始字符）
    try {
      // 检测是否包含 URL 编码字符（%20, %E7 等）
      if (/%[0-9A-Fa-f]{2}/i.test(prompt)) {
        prompt = decodeURIComponent(prompt);
        console.log('🔓 已自动解码 URL 编码的提示词');
      }
    } catch (e) {
      console.warn('⚠️ URL 解码失败，使用原始提示词:', e);
    }

    const btn = setSubmitButtonState('btnGpt', { busy: true, label: '提交中...' });
    setStageStatusText('gpt', '正在提交后台任务...', 'busy');
    setStageState('gpt', { busy: true, statusVisible: true, state: 'busy' });
    const requestParams = {
      ratio: normalizeImageRatio(gptState.ratio, '9:16'),
      resolution: normalizeGptResolution(gptState.resolution, '1k'),
      quality: normalizeGptQuality(gptState.quality, 'auto'),
      image_count: normalizeGptImageCount(gptState.imageCount, 1),
      moderation: normalizeGptModeration(gptState.moderation, 'auto'),
      gpt_provider_route: normalizeGptProviderRouteForUi(gptState.gptProviderRoute),
      use_third_party_api: normalizeGptProviderRouteForUi(gptState.gptProviderRoute) === 'third_party_image_api'
    };

    // Call /api/gpt/generate endpoint (ChatGPT/Codex browser automation)
    api.json('/api/gpt/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt: prompt,
        ...requestParams
      })
    })
      .then((data) => {
        rememberStageTask('gpt', data?.task_id);
        addPendingHistoryRecord({
          taskId: data?.task_id,
          type: 'gpt',
          prompt,
          params: requestParams,
          statusText: 'GPT 生成任务已提交'
        });
        resetGptComposer();
        setStageStatusText('gpt', '后台任务提交成功，完成后会自动发送到 Telegram。', 'success');
        setStageState('gpt', { busy: false, statusVisible: true, state: 'success' });
        setSubmitButtonState(btn, { busy: false, label: '✅ 已提交' });
        alert('✅ GPT 任务已提交，生成完成后会自动无损发送到 Telegram');
      })
      .catch((e) => {
        if (e.isProxyError) {
          alert('🔴 网络连接问题\n\n' + e.message);
        } else {
          alert('提交失败：' + e.message);
        }
        setStageStatusText('gpt', e.message || '提交失败，请稍后重试。', 'error');
        setStageState('gpt', { busy: false, statusVisible: true, state: 'error' });
        setSubmitButtonState(btn, { busy: false });
      });
  }

  function submitGptEdit() {
    let prompt = document.getElementById('gptPrompt')?.value.trim() || document.getElementById('cinematicPrompt')?.value.trim() || '';
    if (!prompt) {
      alert('请输入编辑 Prompt');
      return;
    }

    try {
      if (/%[0-9A-Fa-f]{2}/i.test(prompt)) {
        prompt = decodeURIComponent(prompt);
        console.log('🔓 已自动解码 URL 编码的提示词');
      }
    } catch (e) {
      console.warn('⚠️ URL 解码失败，使用原始提示词:', e);
    }

    if (!uploadedImages.length) {
      alert('请先上传至少一张参考图');
      return;
    }

    const btn = setSubmitButtonState('btnGpt', { busy: true, label: '提交中...' });
    setStageStatusText('gpt', '正在提交 GPT 编辑任务...', 'busy');
    setStageState('gpt', { busy: true, statusVisible: true, state: 'busy' });
    const requestParams = {
      ratio: normalizeImageRatio(gptState.ratio, '9:16'),
      resolution: normalizeGptResolution(gptState.resolution, '1k'),
      quality: normalizeGptQuality(gptState.quality, 'auto'),
      moderation: normalizeGptModeration(gptState.moderation, 'auto'),
      gpt_provider_route: normalizeGptProviderRouteForUi(gptState.gptProviderRoute),
      use_third_party_api: normalizeGptProviderRouteForUi(gptState.gptProviderRoute) === 'third_party_image_api'
    };

    api.json('/api/gpt/edit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        images: uploadedImages.map(i => i.base64),
        ...requestParams
      })
    })
      .then((data) => {
        rememberStageTask('gpt', data?.task_id);
        addPendingHistoryRecord({
          taskId: data?.task_id,
          type: 'gpt-edit',
          prompt,
          params: requestParams,
          statusText: 'GPT 编辑任务已提交'
        });
        resetGptComposer();
        setStageStatusText('gpt', 'GPT 编辑任务提交成功，完成后会自动发送到 Telegram。', 'success');
        setStageState('gpt', { busy: false, statusVisible: true, state: 'success' });
        setSubmitButtonState(btn, { busy: false, label: '✅ 已提交' });
        alert('✅ GPT 编辑任务已提交，完成后会自动无损发送到 Telegram');
      })
      .catch((e) => {
        if (e.isProxyError) {
          alert('🔴 网络连接问题\n\n' + e.message);
        } else {
          alert('提交失败：' + e.message);
        }
        setStageStatusText('gpt', e.message || '提交失败，请稍后重试。', 'error');
        setStageState('gpt', { busy: false, statusVisible: true, state: 'error' });
        setSubmitButtonState(btn, { busy: false });
      });
  }

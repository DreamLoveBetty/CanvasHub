// Google Edit submission flow
  function submitEdit() {
    const promptEl = document.getElementById('editPrompt');
    let prompt = (promptEl && promptEl.value ? promptEl.value : '').trim();
    if (!prompt) {
      if (promptEl) {
        promptEl.focus();
        promptEl.placeholder = '请先输入编辑提示词';
      }
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

    if (uploadedImages.length === 0) {
      alert('请上传至少一张图片');
      return;
    }

    const btn = setSubmitButtonState('btnEdit', { busy: true, label: '提交中...' });
    setStageStatusText('edit', '正在提交编辑任务...', 'busy');
    setStageState('edit', { busy: true, statusVisible: true, state: 'busy' });

    api.request('/edit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        images: uploadedImages.map(i => i.base64),
        ratio: editState.ratio === 'auto' ? '1:1' : normalizeImageRatio(editState.ratio, '1:1'),
        quality: editState.quality === 'standard' ? 'standard' : 'hd',
        feature: editState.feature || 'edit',
        model: typeof normalizeGoogleModel === 'function'
          ? normalizeGoogleModel(editState.model)
          : (editState.model || 'gemini-3.1-flash-image'),
        style: 'raw'
      })
    })
      .then(async (r) => {
        let data = {};
        try { data = await r.json(); } catch (_) {}
        if (r.ok) {
          rememberStageTask('edit', data?.task_id);
          addPendingHistoryRecord({
            taskId: data?.task_id,
            type: 'google-edit',
            prompt,
            params: {
              ratio: editState.ratio === 'auto' ? '1:1' : normalizeImageRatio(editState.ratio, '1:1'),
              quality: editState.quality === 'standard' ? 'standard' : 'hd',
              feature: editState.feature || 'edit',
              model: typeof normalizeGoogleModel === 'function'
                ? normalizeGoogleModel(editState.model)
                : (editState.model || 'gemini-3.1-flash-image'),
              style: 'raw'
            },
            statusText: 'Google 编辑任务已提交'
          });
          resetGoogleEditComposer();
          setStageStatusText('edit', '编辑任务已提交，接下来会继续处理。', 'success');
          setStageState('edit', { busy: false, statusVisible: true, state: 'success' });
          setSubmitButtonState(btn, { busy: false, label: '✅ 已提交' });
          return;
        }
        alert((data && data.error) ? ('Error: ' + data.error) : ('Error ' + r.status));
        setStageStatusText('edit', (data && data.error) ? data.error : ('提交失败，错误码 ' + r.status), 'error');
        setStageState('edit', { busy: false, statusVisible: true, state: 'error' });
        setSubmitButtonState(btn, { busy: false });
      })
      .catch((e) => {
        if (e && e.isProxyError) {
          alert('🔴 网络连接问题\n\n' + e.message);
        } else {
          alert('提交失败：' + ((e && e.message) ? e.message : e));
        }
        setStageStatusText('edit', ((e && e.message) ? e.message : '提交失败，请稍后重试。'), 'error');
        setStageState('edit', { busy: false, statusVisible: true, state: 'error' });
        setSubmitButtonState(btn, { busy: false });
      });
  }

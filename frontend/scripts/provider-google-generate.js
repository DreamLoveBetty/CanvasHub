// Google Generate submission flow
  function submitGen() {
    const promptEl = document.getElementById('genPrompt');
    let prompt = (promptEl && promptEl.value ? promptEl.value : '').trim();
    if (!prompt) {
      if (promptEl) {
        promptEl.focus();
        promptEl.placeholder = '请先输入提示词再点生成';
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

    const btn = setSubmitButtonState('btnGen', { busy: true, label: '提交中...' });
    setStageStatusText('gen', '正在提交生成任务...', 'busy');
    setStageState('gen', { busy: true, statusVisible: true, state: 'busy' });

    const payload = {
      prompt,
      params: {
        ratio: normalizeImageRatio(genState.ratio, '1:1'),
        style: genState.style || 'raw',
        quality: normalizeGoogleQuality(genState.quality, '2k'),
        model: typeof normalizeGoogleModel === 'function'
          ? normalizeGoogleModel(genState.model)
          : (genState.model || 'gemini-3.1-flash-image')
      },
      idempotencyKey: buildGenIdempotencyKey({ prompt, ...genState })
    };

    api.request('/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(async (r) => {
        let data = {};
        try { data = await r.json(); } catch (_) {}

        if (r.ok) {
          if (data && data.task_id) {
            rememberStageTask('gen', data.task_id);
            addPendingHistoryRecord({
              taskId: data.task_id,
              type: 'google-gen',
              prompt,
              params: payload.params,
              statusText: 'Google 生成任务已提交'
            });
            resetGoogleGenerateComposer();
            pollTaskStatus(data.task_id, btn, 'gen');
            return;
          }
        }

        alert((data && data.error) ? ('Error: ' + data.error) : ('Error ' + r.status));
        setStageStatusText('gen', (data && data.error) ? data.error : ('提交失败，错误码 ' + r.status), 'error');
        setStageState('gen', { busy: false, statusVisible: true, state: 'error' });
        setSubmitButtonState(btn, { busy: false });
      })
      .catch((e) => {
        if (e && e.isProxyError) {
          alert('🔴 网络连接问题\n\n' + e.message);
        } else {
          alert('提交失败：' + ((e && e.message) ? e.message : e));
        }
        setStageStatusText('gen', ((e && e.message) ? e.message : '提交失败，请稍后重试。'), 'error');
        setStageState('gen', { busy: false, statusVisible: true, state: 'error' });
        setSubmitButtonState(btn, { busy: false });
      });
  }

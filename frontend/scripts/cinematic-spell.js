// Cinematic spell page: structured prompt generation and result actions
  let cinematicSpellResult = null;

  function getCinematicSpellPlaceholder(kind) {
    const placeholders = {
      positive: '尚未生成提示词',
      negative: '尚未生成提示词',
      json: '尚未生成提示词'
    };
    return placeholders[kind] || '尚未生成提示词';
  }

  function setCinematicSpellOutput(id, value, fallbackKind) {
    const el = document.getElementById(id);
    if (!el) return;
    const text = String(value || '').trim();
    el.textContent = text || getCinematicSpellPlaceholder(fallbackKind);
  }

  function renderCinematicSpellResult(payload) {
    cinematicSpellResult = payload && typeof payload === 'object' ? payload : null;

    const positive = cinematicSpellResult?.positive_prompt || '';
    const negative = cinematicSpellResult?.negative_prompt || '';
    const jsonText = cinematicSpellResult?.json_text
      || (cinematicSpellResult?.result ? JSON.stringify(cinematicSpellResult.result, null, 2) : '');

    setCinematicSpellOutput('cinematicSpellPositiveOutput', positive, 'positive');
    setCinematicSpellOutput('cinematicSpellNegativeOutput', negative, 'negative');
    setCinematicSpellOutput('cinematicSpellJsonOutput', jsonText, 'json');
  }

  function clearCinematicSpellWorkspace() {
    const seed = document.getElementById('cinematicSpellSeed');
    if (seed) {
      seed.value = '';
      seed.focus();
    }
    renderCinematicSpellResult(null);
  }

  function copyCinematicSpellJson() {
    const text = cinematicSpellResult?.json_text
      || (cinematicSpellResult?.result ? JSON.stringify(cinematicSpellResult.result, null, 2) : '');
    copyTextToClipboard(text, '结构化 JSON 已复制。');
  }

  function copyCinematicSpellPositivePrompt() {
    copyTextToClipboard(cinematicSpellResult?.positive_prompt || '', '正向提示已复制。');
  }

  function copyCinematicSpellNegativePrompt() {
    copyTextToClipboard(cinematicSpellResult?.negative_prompt || '', '负向约束已复制。');
  }

  async function generateCinematicSpellPrompt() {
    const seedEl = document.getElementById('cinematicSpellSeed');
    const btn = document.getElementById('cinematicSpellGenerateBtn');
    const topic = String(seedEl?.value || '').trim();

    if (!topic) {
      seedEl?.focus();
      showStatusMessage('先输入主题、关键词或画面想法，再生成提示词。', 'info');
      return;
    }

    const previousLabel = btn?.textContent || '生成结构化提示词';
    if (btn) {
      btn.disabled = true;
      btn.textContent = '生成中...';
    }

    try {
      const payload = await api.json('/api/spell/generate-prompt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic
        })
      });
      renderCinematicSpellResult(payload);
      showStatusMessage('结构化提示词已生成。', 'success');
    } catch (error) {
      renderCinematicSpellResult(null);
      showStatusMessage(error.message || '提示词生成失败，请稍后再试。', 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = previousLabel;
      }
    }
  }

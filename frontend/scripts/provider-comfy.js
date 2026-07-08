// ComfyUI provider flow
  // --- COMFY LOGIC ---
  function loadComfyWorkflows() {
    const sel = document.getElementById('comfyWorkflow');
    if(sel.options.length > 1) return Promise.resolve(); // Already loaded

    return api.json('/api/comfy/workflows')
      .then(data => {
        sel.innerHTML = '<option value="" disabled selected>-- 请选择 --</option>';
        data.workflows.forEach(wf => {
          const opt = document.createElement('option');
          opt.value = wf;
          opt.textContent = wf.replace('.json', '');
          sel.appendChild(opt);
        });
        if (comfyState.workflow && data.workflows.includes(comfyState.workflow)) {
          sel.value = comfyState.workflow;
        }
      })
      .catch(e => {
        sel.innerHTML = '<option disabled>加载失败</option>';
        console.error(e);
      });
  }

  let comfyTimer = null;
  let comfyImageData = null; // Store base64
  let comfyImageObjectUrl = null;

  function pickComfyWorkflow(val) {
    comfyState.workflow = val || '';
    saveUiSettings();
  }

  function pickRatioComfy(val) {
    comfyState.ratio = val;
    document.querySelectorAll('#comfyRatioSection .r-btn').forEach(b => {
      b.classList.remove('selected');
      if ((b.dataset.ratioValue || '').trim() === val) b.classList.add('selected');
    });
    saveUiSettings();
  }

  function handleComfyUpload(input) {
    if(!input.files || !input.files[0]) return;
    const file = input.files[0];
    const reader = new FileReader();
    reader.onload = (e) => {
      comfyImageData = e.target.result;
      document.getElementById('comfyPreview').src = comfyImageData;
      document.getElementById('comfyPreview').style.display = 'block';
      document.getElementById('comfyUploadPlaceholder').style.display = 'none';
      document.getElementById('comfyRemoveImg').style.display = 'block';
    };
    reader.readAsDataURL(file);
  }

  function clearComfyImage(e) {
    if(e) e.stopPropagation();
    comfyImageData = null;
    document.getElementById('comfyInput').value = '';
    document.getElementById('comfyPreview').src = '';
    document.getElementById('comfyPreview').style.display = 'none';
    document.getElementById('comfyUploadPlaceholder').style.display = 'block';
    document.getElementById('comfyRemoveImg').style.display = 'none';
  }

  function runComfy() {
    const wf = document.getElementById('comfyWorkflow').value;
    const prompt = document.getElementById('comfyPrompt').value.trim();
    if(!wf) { alert('请选择工作流'); return; }
    // Prompt is optional if image is provided (e.g. style transfer)
    // if(!prompt && !comfyImageData) { alert('请输入 Prompt 或上传图片'); return; }

    const btn = document.getElementById('btnComfy');
    const status = document.getElementById('comfyStatus');
    const img = document.getElementById('comfyImage');
    
    setSubmitButtonState(btn, { busy: true, label: '提交中...' });
    status.style.display = 'block';
    setComfyStatusText('提交任务中...', 'busy');
    img.style.display = 'none';
    setComfyStageState({ busy: true, statusVisible: true, imageVisible: false, state: 'busy' });

    const payload = { 
      workflow: wf, 
      prompt: prompt,
      ratio: comfyState.ratio 
    };
    if(comfyImageData) {
      // Send base64 (with or without header? server expects full data uri usually or raw base64)
      // Server logic splits by ',' if present, so full data URI is fine.
      payload.image = comfyImageData;
    }

    api.json('/api/comfy/run', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    })
    .then(data => {
      if(data.status === 'queued') {
        rememberStageTask('comfy', data.task_id || data.prompt_id);
        addPendingHistoryRecord({
          taskId: data.task_id || data.prompt_id,
          type: 'comfy',
          prompt,
          params: {
            workflow: wf,
            ratio: comfyState.ratio
          },
          statusText: 'ComfyUI 任务已进入队列'
        });
        setComfyStatusText('生成中... (ID: ' + data.prompt_id + ')', 'busy');
        setSubmitButtonState(btn, { busy: true, label: '⏳ 生成中...' });
        setComfyStageState({ busy: true, statusVisible: true, imageVisible: false, state: 'busy' });
        pollComfy(data.prompt_id, { workflow: wf, prompt: prompt, ratio: comfyState.ratio, pendingTaskId: data.task_id || data.prompt_id });
      } else {
        alert('提交失败: ' + JSON.stringify(data));
        resetComfyBtn();
      }
    })
    .catch(e => {
      if (e.isProxyError) {
        alert('🔴 网络连接问题\n\n' + e.message);
      } else {
        alert('Error: ' + e);
      }
      resetComfyBtn();
    });
  }

  function pollComfy(pid, meta = {}) {
    if(comfyTimer) clearTimeout(comfyTimer);
    
    api.json('/api/comfy/history?prompt_id=' + pid)
      .then(data => {
        // Comfy returns { prompt_id: { status: { completed: true }, outputs: { ... } } }
        const entry = data[pid];
        if(entry && entry.status && entry.status.completed) {
          // Done!
          const outputs = entry.outputs;
          // Find the best image (prefer 'output' over 'temp')
          let finalImg = null;
          let tempImg = null;
          
          for(let k in outputs) {
            if(outputs[k].images && outputs[k].images.length > 0) {
              for(let img of outputs[k].images) {
                if(img.type === 'output') finalImg = img;
                else tempImg = img;
              }
            }
          }
          let imgData = finalImg || tempImg;
          
          if(imgData) {
            const url = `/api/comfy/image?filename=${imgData.filename}&subfolder=${imgData.subfolder}&type=${imgData.type}`;
            const img = document.getElementById('comfyImage');

            api.blob(url)
              .then(blob => {
                if (comfyImageObjectUrl) {
                  URL.revokeObjectURL(comfyImageObjectUrl);
                }
                comfyImageObjectUrl = URL.createObjectURL(blob);
                img.onload = () => {
                  img.style.display = 'block';
                  document.getElementById('comfyStatus').style.display = 'none';
                  setComfyStageState({ busy: false, statusVisible: false, imageVisible: true, state: 'success' });
                  loadHistory({ force: true }).catch(() => {});
                  resetComfyBtn();
                };
                img.src = comfyImageObjectUrl;
              })
              .catch(e => {
                console.error('Image fetch error', e);
                setComfyStatusText('图片暂时没加载出来。', 'error');
                setComfyStageState({ busy: false, statusVisible: true, imageVisible: false, state: 'error' });
                clearPendingHistoryRecord(meta.pendingTaskId || pid);
                resetComfyBtn();
              });
          } else {
            setComfyStatusText('生成完成，但未找到图片输出', 'error');
            setComfyStageState({ busy: false, statusVisible: true, imageVisible: false, state: 'error' });
            clearPendingHistoryRecord(meta.pendingTaskId || pid);
            resetComfyBtn();
          }
        } else {
          // Not done yet
          setComfyStageState({ busy: true, statusVisible: true, imageVisible: false, state: 'busy' });
          comfyTimer = setTimeout(() => pollComfy(pid, meta), 1000);
        }
      })
      .catch(e => {
        console.error('Poll error', e);
        setComfyStatusText('生成中... 正在等待工作流返回', 'busy');
        setComfyStageState({ busy: true, statusVisible: true, imageVisible: false, state: 'busy' });
        comfyTimer = setTimeout(() => pollComfy(pid, meta), 2000);
      });
  }

  function resetComfyBtn() {
    const btn = document.getElementById('btnComfy');
    setSubmitButtonState(btn, { busy: false });
    const status = document.getElementById('comfyStatus');
    const image = document.getElementById('comfyImage');
    setComfyStageState({
      busy: false,
      statusVisible: !!(status && status.style.display !== 'none'),
      imageVisible: !!(image && image.style.display !== 'none'),
      state: image && image.style.display !== 'none' ? 'success' : (status && status.style.display !== 'none' && status.dataset.tone === 'error' ? 'error' : 'idle')
    });
  }

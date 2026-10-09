// Krea 2 native Canvas controller. Server owns models, LoRAs, jobs and archives.
(function () {
  function create({model:M,api,loraLibrary,loraView,getCanvas,getNodeState,getNodeElement,getImageReferences,getTextNodes,
    materializeText,addNode,connectNodes,setImageFromResult,saveState,reportStatus,progressView}={}){
    const sessions=new Map();let catalog=null,status=null,loras=[],loading=null,loraLoading=null,statusTimer=0;
    const controllerAbort=new AbortController();
    const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    const terminal=value=>['succeeded','succeeded_no_telegram','telegram_failed','failed','canceled'].includes(value);
    const live=s=>sessions.get(s.id)===s&&getNodeState?.(s.id)===s.node&&getNodeElement?.(s.id)===s.el;
    const loraMeta=id=>loraLibrary?.peek(id)||loras.find(item=>item.asset_id===id)||{};
    const modelItems=()=>status?.models||catalog?.models||[];
    const modelMeta=id=>modelItems().find(item=>item.id===id)||{};
    const regularLoraLimit=node=>node.mode==='edit'?3:4;
    const looksLikeEditAdapter=item=>/(?:krea\s*2.*edit|identity.*edit|edit.*identity)/i.test(String(item?.name||item?.filename||''));
    function chooseEditAdapter(node){
      if(node.mode!=='edit'||node.editAdapterId)return false;
      const preferred=loras.find(looksLikeEditAdapter);if(!preferred)return false;
      node.editAdapterId=preferred.asset_id;return true;
    }
    const modeLabel=node=>node.mode==='edit'?'图像编辑 · Identity Edit':'标准生成 · 文生图';
    function syncMode(node){
      const mode=M.resolveMode(node,getCanvas?.()),changed=node.mode!==mode;
      node.mode=mode;M.normalize(node);return chooseEditAdapter(node)||changed;
    }
    const readyFor=node=>Boolean(status?.environment_ready&&status?.source_ready&&status?.base_ready&&(!node.safetyEnabled||status?.safety_ready)&&modelMeta(node.baseModelId).ready);
    const preparationCovers=(preparation,node)=>Boolean(preparation?.base_model_id===node.baseModelId&&(!node.safetyEnabled||preparation?.safety_enabled===true));
    const bytes=value=>{const n=Number(value)||0;return n>=1024**3?`${(n/1024**3).toFixed(1)} GB`:n>=1024**2?`${Math.round(n/1024**2)} MB`:`${n} B`;};
    function dimensionOptions(selected){
      const values=[512,672,720,768,832,864,896,1024,1120,1152,1248,1280,1536,1568,2048,Number(selected)].filter(value=>Number.isFinite(value));
      return [...new Set(values)].sort((a,b)=>a-b).map(value=>`<option value="${value}"${value===selected?' selected':''}>${value}</option>`).join('');
    }
    function ratioOptions(selected){
      return M.ASPECT_RATIOS.map(value=>`<option value="${value}"${value===selected?' selected':''}>${value}</option>`).join('')+
        `<option value="custom"${selected==='custom'?' selected':''}>自定义</option>`;
    }
    function loraRows(node){
      if(!M.regularLoras(node).length)return `<div class="desk-krea2__empty">未加载普通 LoRA，可从本地库添加，最多 ${regularLoraLimit(node)} 个</div>`;
      return node.loras.map((item,index)=>({item,index})).filter(({item})=>node.mode!=='edit'||item.assetId!==node.editAdapterId).map(({item,index})=>{
        const meta=loraMeta(item.assetId),name=meta.name||item.assetId;return `<div class="desk-krea2__lora" data-krea2-lora-row="${index}">
          <strong title="${esc(name)}">${loraView?`<button type="button" class="desk-lora-row-detail" data-krea2-lora-detail="${esc(item.assetId)}" title="查看效果与触发词">${esc(meta.name||item.assetId.slice(0,12))} ⓘ</button>`:esc(meta.name||item.assetId.slice(0,12))}</strong>
          <label aria-label="${esc(name)} LoRA 强度"><input class="desk-number" type="number" min="0" max="2" step="0.05" value="${esc(item.scale)}" title="LoRA 强度" data-krea2-lora-scale="${index}"></label>
          <button type="button" class="desk-button desk-button--danger" data-krea2-lora-remove="${index}" aria-label="从节点移除 ${esc(name)}" title="移除">×</button></div>`;
      }).join('');
    }
    function loraOptions(node){
      const limit=regularLoraLimit(node);
      if(M.regularLoras(node).length>=limit)return `<option value="">已达到 ${limit} 个普通 LoRA 上限</option>`;
      const selected=new Set(node.loras.map(item=>item.assetId));
      const available=loras.filter(item=>!selected.has(item.asset_id)&&(node.mode!=='edit'||item.asset_id!==node.editAdapterId));
      return `<option value="">${available.length?'＋ 添加普通 LoRA…':'LoRA 目录暂无可用模型'}</option>`+
        available.map(item=>`<option value="${esc(item.asset_id)}">${esc(item.name)} · ${bytes(item.file_size)}</option>`).join('');
    }
    function editAdapterOptions(node){
      const current=loraMeta(node.editAdapterId);
      const available=[...loras].sort((a,b)=>Number(looksLikeEditAdapter(b))-Number(looksLikeEditAdapter(a)));
      const missing=node.editAdapterId&&!current.asset_id
        ?`<option value="${esc(node.editAdapterId)}" selected>编辑 LoRA 已不存在 · ${esc(node.editAdapterId.slice(0,12))}…</option>`:'';
      return missing+`<option value="">${available.length?'选择 Krea 2 编辑 LoRA…':'请先把编辑 LoRA 放入本地 LoRA 目录'}</option>`+
        available.map(item=>`<option value="${esc(item.asset_id)}"${item.asset_id===node.editAdapterId?' selected':''}>${looksLikeEditAdapter(item)?'推荐 · ':''}${esc(item.name)} · ${bytes(item.file_size)}</option>`).join('');
    }
    function modelOptions(node){
      const fallback=[
        {id:M.BUILTIN_MODEL_IDS['8bit'],label:'Krea 2 Turbo · Alis MLX（8-bit）',precision:'8bit'}
      ];
      const items=modelItems().length?modelItems():fallback;
      const missing=node.baseModelId&&!items.some(item=>item.id===node.baseModelId)
        ?`<option value="${esc(node.baseModelId)}" selected>模型已不存在 · ${esc(node.baseModelId)}</option>`:'';
      return missing+items.map(item=>`<option value="${esc(item.id)}"${item.id===node.baseModelId?' selected':''}>${esc(item.label||item.name||item.id)}${item.ready===false?' · 未准备':''}</option>`).join('');
    }
    function nodeHtml(node){
      syncMode(node);
      return `<section class="desk-node desk-node--krea2 desk-glass" data-node-id="${esc(node.id)}" aria-label="Krea 2 节点">
        <header class="desk-node__header desk-krea2__header" data-node-drag-handle>
          <div><p class="desk-node__eyebrow">本地图像生成</p><h2>Krea 2 · MLX</h2></div>
          <div class="desk-node-tools"><span class="desk-status-pill" data-krea2-status>检查环境</span><button type="button" class="desk-node-delete" data-node-delete aria-label="删除 Krea 2 节点">删</button></div>
        </header>
        <button class="desk-port desk-port--in" data-port="in" data-node-id="${esc(node.id)}" aria-label="连接提示词或参考图"></button>
        <button class="desk-port desk-port--out" data-port="out" data-node-id="${esc(node.id)}" aria-label="连接生成图片"></button>
        <div class="desk-krea2__body" data-node-drag-ignore>
          <div class="desk-param-grid desk-krea2__grid desk-krea2__grid--model">
            <label><span>工作模式 · 自动识别</span><input class="desk-select desk-krea2__mode" type="text" data-krea2-mode readonly value="${modeLabel(node)}" title="由画布连线自动识别：仅文本为标准文生图，接入图像为 Identity Edit 图像编辑。"></label>
            <label><span>Base 权重模型</span><select class="desk-select" data-desk-select-width="content" data-krea2-field="baseModelId">${modelOptions(node)}</select></label>
          </div>
          <div class="desk-param-grid desk-krea2__grid desk-krea2__grid--params">
            <label><span>画幅比例</span><select class="desk-select" data-krea2-field="ratio">${ratioOptions(node.ratio)}</select></label>
            <label><span>宽度</span><select class="desk-select" data-krea2-field="imageWidth">${dimensionOptions(node.imageWidth)}</select></label>
            <label><span>高度</span><select class="desk-select" data-krea2-field="imageHeight">${dimensionOptions(node.imageHeight)}</select></label>
            <label><span>步数</span><input class="desk-number" type="number" min="1" max="50" step="1" value="${node.steps}" data-krea2-field="steps"></label>
            <label><span>张数</span><input class="desk-number" type="number" min="1" max="4" step="1" value="${node.imageCount}" data-krea2-field="imageCount"></label>
            <label><span>Seed</span><input class="desk-number" type="text" inputmode="numeric" placeholder="随机" value="${esc(node.seed)}" data-krea2-field="seed"></label>
            <label data-krea2-edit-control${node.mode==='edit'?'':' hidden'}><span>语义识图</span><select class="desk-select" data-krea2-field="groundingPx"><option value="512"${node.groundingPx===512?' selected':''}>512 · 更服从指令</option><option value="768"${node.groundingPx===768?' selected':''}>768 · 推荐</option><option value="1024"${node.groundingPx===1024?' selected':''}>1024 · 更保身份</option><option value="0"${node.groundingPx===0?' selected':''}>原图分辨率</option></select></label>
          </div>
          <div class="desk-krea2__edit" data-krea2-edit-panel${node.mode==='edit'?'':' hidden'}>
            <label class="desk-krea2__edit-adapter"><span>编辑适配器 · 必需</span><select class="desk-select" data-krea2-edit-adapter>${editAdapterOptions(node)}</select></label>
            <label><span>适配器强度</span><input class="desk-number" type="number" min="0.01" max="2" step="0.05" value="${node.editAdapterScale}" data-krea2-edit-adapter-scale></label>
            <label><span>参考图保真</span><input class="desk-number" type="number" min="0.01" max="20" step="0.25" value="${node.referenceStrength}" data-krea2-field="referenceStrength"></label>
            <label><span>参考图适配</span><select class="desk-select" data-krea2-field="fitMode"><option value="fit"${node.fitMode==='fit'?' selected':''}>Fit · v1.2 推荐</option><option value="crop"${node.fitMode==='crop'?' selected':''}>Crop · 旧版</option></select></label>
          </div>
          <section class="desk-krea2__loras" aria-label="普通 LoRA"><header><div class="desk-krea2__lora-heading"><div><strong>普通 LoRA</strong><span class="desk-krea2__lora-count" data-krea2-lora-count>${M.regularLoras(node).length} / ${regularLoraLimit(node)}</span></div><small data-krea2-lora-limit>可选 · 按顺序叠加${node.mode==='edit'?' · 不含编辑适配器':''}</small></div><div class="desk-krea2__lora-add">${loraView?`<button type="button" class="desk-button desk-lora-picker-button" data-krea2-lora-picker aria-label="看图选择 LoRA">＋ 看图选择 LoRA <span>⌄</span></button>`:''}<select ${loraView?'hidden':''} class="desk-select" data-krea2-lora-add aria-label="添加普通 LoRA">${loraOptions(node)}</select></div></header>
            <div data-krea2-lora-list>${loraRows(node)}</div></section>
          <footer class="desk-input-footer desk-krea2__footer">
            <div class="desk-pill-row desk-krea2__meta"><span data-krea2-inputs>画布连线 · 文本 0 · 编辑源图 0</span><span data-krea2-runtime>正在检查共享环境与模型…</span></div>
            <div class="desk-output-controls desk-output-controls--input"><label class="desk-switch"><input type="checkbox" data-krea2-safety ${node.safetyEnabled?'checked':''}><span></span><em>NSFW 安全检查</em></label><label class="desk-switch"><input type="checkbox" data-krea2-telegram ${node.telegramEnabled?'checked':''}><span></span><em>发送到 Telegram</em></label></div>
            <div class="desk-action-row"><button type="button" class="desk-generation-action desk-krea2__run" data-krea2-run title="开始生成" aria-label="开始生成"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m13.5 2-9 12h6l-1 8 10-13h-7z"></path></svg><span class="desk-generation-action__label">开始生成</span></button></div>
          </footer>
        </div><div class="desk-progress-float desk-krea2__progress" data-krea2-progress hidden role="status"><div class="desk-progress-float__panel"><div class="desk-progress-float__bar"><span data-progress-bar data-krea2-bar></span><strong class="desk-progress-float__percent" data-krea2-percent>处理中</strong></div><span class="desk-progress-float__stage" data-krea2-stage>Krea 2 任务进行中</span></div></div>
      </section>`;
    }
    function paint(s){
      if(!live(s))return;if(syncMode(s.node)){renderLoraControls(s);renderMode(s);}
      const node=s.node,busy=Boolean(s.pending||s.starting)||M.active(node.status),ready=readyFor(node),serverPreparing=status?.preparation?.status==='running',preparing=Boolean(s.preparing)||serverPreparing;
      const label={idle:'就绪',submitting:'提交中',queued:'排队中',processing:'生成中',running:'生成中',succeeded:'已完成',succeeded_no_telegram:'已归档',telegram_failed:'已归档',failed:'失败',canceled:'已停止'};
      const badge=s.el.querySelector('[data-krea2-status]');badge.textContent=s.starting&&!s.pending?'准备中':busy?(label[node.status]||'处理中'):preparing?'准备中':ready?(label[node.status]||'就绪'):node.status==='failed'?'失败':'待首次生成';
      badge.classList.toggle('is-success',ready&&!busy&&!['failed','canceled'].includes(node.status));
      badge.classList.toggle('is-busy',busy||preparing);
      badge.classList.toggle('is-error',node.status==='failed');
      badge.classList.toggle('is-canceled',node.status==='canceled');
      const run=s.el.querySelector('[data-krea2-run]');run.disabled=Boolean(s.pending||s.starting)||(!busy&&preparing);run.querySelector('span').textContent=s.starting&&!s.pending?'准备中':busy?'停止生成':preparing?'准备中':node.status==='failed'?'重试生成':'开始生成';
      const images=getImageReferences?.(s.id)||[],texts=getTextNodes?.(s.id)||[];
      const sourceLabel='编辑源图';
      s.el.querySelector('[data-krea2-inputs]').textContent=`画布连线 · 文本 ${texts.length} · ${sourceLabel} ${images.length}${images.length>1?'（仅允许 1 张）':''}`;
      const prep=status?.preparation||{};let runtime='';
      if(preparing)runtime=`${prep.message||'正在准备模型'}${prep.total&&prep.downloaded?` · ${bytes(prep.downloaded)} / ${bytes(prep.total)}`:''}`;
      else if(ready)runtime=`共享环境已就绪 · ${modelMeta(node.baseModelId).name||node.baseModelId} · 安全检查${node.safetyEnabled?'开启':'关闭'}${status?.warm?' · 模型已热载入':''}`;
      else if(prep.status==='failed')runtime=prep.message||'Krea 2 模型准备失败';
      else if(status?.environment_ready&&status?.source_ready&&status?.base_ready&&node.safetyEnabled&&!status?.safety_ready)runtime='NSFW 安全分类模型尚未准备';
      else if(status?.environment_ready&&status?.source_ready&&status?.base_ready&&!modelMeta(node.baseModelId).ready)runtime='所选 Base 权重模型尚未准备或已不存在';
      else runtime=(status?.reasons?.length?status.reasons:[`首次生成时自动准备 ${modelMeta(node.baseModelId).name||'所选'} 模型`]).join(' · ');
      const runtimeEl=s.el.querySelector('[data-krea2-runtime]');runtimeEl.textContent=runtime;
      runtimeEl.classList.toggle('is-success',ready&&!busy);
      runtimeEl.classList.toggle('is-busy',busy||preparing);
      runtimeEl.classList.toggle('is-error',node.status==='failed'||prep.status==='failed');
      runtimeEl.classList.toggle('is-warning',!ready&&!busy&&!preparing&&node.status!=='failed'&&prep.status!=='failed');
      const progress=s.el.querySelector('[data-krea2-progress]'),showProgress=busy||preparing;progress.hidden=!showProgress;
      progress.classList.toggle('is-visible',showProgress);
      if(showProgress){const total=Number(prep.total)||0,downloaded=Number(prep.downloaded)||0;const amount=preparing&&!busy?(total&&downloaded?Math.max(2,Math.min(98,Math.round(downloaded/total*100))):3):Math.max(2,Math.min(98,Number(s.job?.progress||8)));progress.style.setProperty('--progress-percent',amount+'%');s.el.querySelector('[data-krea2-bar]').style.width=amount+'%';s.el.querySelector('[data-krea2-percent]').textContent=preparing&&!busy&&!(total&&downloaded)?'准备中':`${amount}%`;s.el.querySelector('[data-krea2-stage]').textContent=preparing&&!busy?(prep.message||'首次使用，正在自动准备 Krea 2 模型'):(s.job?.progress_text||'Krea 2 本地推理中');}
      const preparingModel=preparing&&(!busy||s.starting||!node.jobId),task=preparingModel?prep:s.starting?null:s.job;
      progressView?.update(progress,{visible:showProgress,running:showProgress,taskId:preparingModel?'prepare:'+node.baseModelId:node.jobId,
        percent:preparingModel?(Number(prep.total)>0?Number(prep.downloaded||0)/prep.total*100:null):(task?.progress??null),
        title:preparingModel?(prep.message||'正在准备模型'):(task?.progress_text||'Krea 2 本地推理中'),detail:'Krea 2 · MLX',
        startedAt:task?.started_at||task?.created_at||s.progressStartedAt,finishedAt:task?.finished_at},s.el);
      s.el.querySelectorAll('.desk-krea2__body :is(input,select,[data-krea2-lora-picker])').forEach(input=>{input.disabled=busy||preparing;});
    }
    function renderMode(s){
      if(!live(s))return;
      const editing=s.node.mode==='edit';
      s.el.querySelectorAll('[data-krea2-edit-control]').forEach(el=>{el.hidden=!editing;});
      const panel=s.el.querySelector('[data-krea2-edit-panel]');if(panel)panel.hidden=!editing;
      const adapter=s.el.querySelector('[data-krea2-edit-adapter]');if(adapter)adapter.innerHTML=editAdapterOptions(s.node);
      const mode=s.el.querySelector('[data-krea2-mode]');if(mode)mode.value=modeLabel(s.node);
      const section=s.el.querySelector('.desk-krea2__loras');if(section)section.classList.toggle('is-editing',editing);
      const total=M.regularLoras(s.node).length,max=regularLoraLimit(s.node);
      const limit=s.el.querySelector('[data-krea2-lora-limit]');if(limit)limit.textContent=total>max?`编辑模式最多 ${max} 个普通 LoRA，请移除 ${total-max} 个`:`可选 · 按顺序叠加${editing?' · 不含编辑适配器':''}`;
      const count=s.el.querySelector('[data-krea2-lora-count]');if(count)count.textContent=`${total} / ${max}`;
      window.DesktopSelect?.refreshAll?.();
    }
    function renderLoras(s){
      if(!live(s))return;const changed=syncMode(s.node);renderLoraControls(s);renderMode(s);window.DesktopSelect?.refreshAll?.();paint(s);if(changed)saveState?.();
    }
    function renderLoraControls(s){s.el.querySelector('[data-krea2-lora-list]').innerHTML=loraRows(s.node);s.el.querySelector('[data-krea2-lora-add]').innerHTML=loraOptions(s.node);}
    function renderModels(s){
      if(!live(s))return;const select=s.el.querySelector('[data-krea2-field="baseModelId"]');if(select)select.innerHTML=modelOptions(s.node);window.DesktopSelect?.refreshAll?.();paint(s);
    }
    function syncSizeControls(s){
      for(const key of ['ratio','imageWidth','imageHeight']){const input=s.el.querySelector(`[data-krea2-field="${key}"]`);if(input)input.value=String(s.node[key]);}
      window.DesktopSelect?.refreshAll?.();
    }
    async function loadResources(force=false){
      if(loraLibrary)loraLibrary.list({engine:'krea2',limit:200}).then(()=>sessions.forEach(renderLoras)).catch(()=>{});
      if(loading&&!force)return loading;
      loading=Promise.all([api.catalog(),api.status(),api.listLoras()]).then(([c,st,ls])=>{catalog=c;status=st;loras=ls.loras||[];sessions.forEach(s=>{renderModels(s);renderLoras(s);});scheduleStatus();return st;})
        .catch(error=>{status={reasons:[error.message||'Krea 2 状态读取失败'],models:[]};sessions.forEach(paint);throw error;}).finally(()=>{loading=null;});
      return loading;
    }
    async function refreshLoras(s){
      if(loraLoading)return loraLoading;
      loraLoading=api.listLoras().then(result=>{loras=result.loras||[];sessions.forEach(renderLoras);return result;})
        .catch(error=>{if(live(s)){s.notice=error.message;feedback(s,error.message,'error');}throw error;}).finally(()=>{loraLoading=null;});
      return loraLoading;
    }
    function scheduleStatus(){clearTimeout(statusTimer);if(status?.preparation?.status==='running')statusTimer=setTimeout(()=>loadResources(true).catch(()=>{}),2000);}
    function wait(ms,signal){return new Promise(resolve=>{let done=false,timer=0;const finish=()=>{if(done)return;done=true;clearTimeout(timer);signal?.removeEventListener('abort',finish);resolve();};timer=setTimeout(finish,ms);signal?.addEventListener('abort',finish,{once:true});});}
    function feedback(s,message='',tone='info'){
      if(!live(s)||!reportStatus)return;const task=s.job||{},stage=message||task.progress_text||task.error||'Krea 2 任务';
      reportStatus({message:`Krea 2 · ${stage}`,tone,task:{...task,task_id:s.node.jobId||'',node_id:s.id,node_title:`Krea 2 · ${s.id.slice(-6)}`,operation_label:'Krea 2 本地生成',provider_route:'krea2-alis-mlx',status:s.node.status,status_label:stage,detail_title:'Krea 2 任务状态',progress_text:stage,raw_detail:task.error||message||stage}});
    }
    async function publish(s,task,onlyTarget=''){
      if(!live(s)||!task?.image_paths?.length||s.publishing)return;s.publishing=true;
      try{const edges=(getCanvas().edges||[]).filter(edge=>edge.from===s.id&&getNodeState(edge.to)?.type==='image');
        if(onlyTarget&&!edges.some(edge=>edge.to===onlyTarget))return;
        if(!onlyTarget)for(let index=edges.length;index<task.image_paths.length;index++){
          const id=addNode('image',{x:s.node.x+s.node.width+260,y:s.node.y+110+index*215});connectNodes(s.id,id,{quiet:true,outputSlot:index});edges.push((getCanvas().edges||[]).find(edge=>edge.from===s.id&&edge.to===id));}
        const targets=onlyTarget?edges.filter(edge=>edge.to===onlyTarget):edges;
        for(const edge of targets){const slot=Number.isInteger(Number(edge?.outputSlot))?Number(edge.outputSlot):edges.indexOf(edge);if(!getNodeState(edge?.to))continue;
          await setImageFromResult(edge.to,s.id,{imagePaths:task.image_paths,files:task.result_files,primaryFile:task.result_file,taskId:task.task_id,prompt:task.prompt,type:'krea2'},slot);}
        s.node.resultJobId=task.task_id;saveState();
      }finally{s.publishing=false;}
    }
    async function poll(s){
      clearTimeout(s.timer);const id=s.node.jobId,epoch=s.epoch||0;if(!id||!live(s))return;
      try{const task=await api.job(id);if(!live(s)||s.node.jobId!==id||(s.epoch||0)!==epoch)return;s.job=task;s.node.status=task.status;
        if(task.result_files?.length&&['succeeded','succeeded_no_telegram','telegram_failed'].includes(task.status))await publish(s,task);
        paint(s);feedback(s,'',task.error?'error':task.status==='succeeded'?'success':'info');saveState();if(!terminal(task.status))s.timer=setTimeout(()=>poll(s),1500);
      }catch(error){if(!live(s)||s.node.jobId!==id)return;s.notice=error.message;paint(s);feedback(s,error.message,'error');if(!terminal(s.node.status))s.timer=setTimeout(()=>poll(s),3000);}
    }
    async function ensureReady(s){
      if(readyFor(s.node))return true;clearTimeout(statusTimer);s.preparing=true;s.notice='';paint(s);feedback(s,'首次使用，正在自动准备模型');let requested=false;
      try{while(live(s)){
          const next=await api.status();if(!live(s))return false;status=next;sessions.forEach(paint);if(readyFor(s.node)){feedback(s,'模型准备完成','success');return true;}
          const prep=next.preparation||{};if(prep.status==='running'){requested=requested||preparationCovers(prep,s.node);await wait(2000,s.abort.signal);continue;}
          if(requested)throw new Error(prep.status==='failed'?(prep.message||'Krea 2 模型准备失败'):(next.reasons||[]).join(' · ')||'Krea 2 模型准备后仍未就绪');
          const reply=await api.prepare(s.node.baseModelId,s.node.safetyEnabled);if(!live(s))return false;requested=reply.already_running!==true||preparationCovers(reply.preparation,s.node);if(reply.preparation)status={...status,preparation:reply.preparation};sessions.forEach(paint);await wait(700,s.abort.signal);
        }return false;
      }finally{s.preparing=false;if(live(s))paint(s);scheduleStatus();}
    }
    async function run(s){
      if(s.pending||s.preparing||s.starting)return;if(M.active(s.node.status)){if(s.node.jobId){s.pending=true;try{await api.cancel(s.node.jobId);}finally{s.pending=false;poll(s);}}return;}
      s.progressStartedAt=Date.now();s.starting=true;paint(s);
      try{if(!status)await loadResources();if(!live(s))return;paint(s);
        const prompt=(getTextNodes(s.id)||[]).map(node=>materializeText(node)).map(value=>String(value||'').trim()).filter(Boolean).join('\n\n');if(!prompt)throw new Error('请连接含有提示词的文本节点');
        const refs=getImageReferences(s.id)||[];if(refs.length>1)throw new Error('Krea 2 一次仅支持 1 张输入图');
        if(M.imageInputIds(s.node,getCanvas()).some(id=>!refs.some(ref=>ref.sourceNodeId===id)))throw new Error('连接的编辑源图尚无可读取内容，请先加载图片');
        if(s.node.mode==='edit'&&refs.length!==1)throw new Error('Krea 2 指令编辑必须连接 1 张编辑源图');
        if(s.node.mode==='edit'&&!s.node.editAdapterId)throw new Error('请选择 Krea 2 Identity Edit LoRA');
        if(M.regularLoras(s.node).length>regularLoraLimit(s.node))throw new Error('编辑模式最多 3 个普通 LoRA，请移除多余 LoRA 后再生成');
        // Snapshot mode, all parameters and source before preparation/upload can
        // yield. Graph changes update the next run, never this request's contract.
        const mode=s.node.mode,source=refs[0]?(refs[0].base64||refs[0].imageData||refs[0].imageUrl||refs[0].url):'',name=refs[0]?.name||'reference.png';
        const request={prompt,mode,base_model_id:s.node.baseModelId,aspect_ratio:s.node.ratio,width:s.node.imageWidth,height:s.node.imageHeight,steps:s.node.steps,
          seed:s.node.seed||'random',image_count:s.node.imageCount,strength:s.node.strength,
          edit_adapter_asset_id:mode==='edit'?s.node.editAdapterId:'',edit_adapter_scale:s.node.editAdapterScale,
          reference_strength:s.node.referenceStrength,grounding_px:s.node.groundingPx,fit_mode:s.node.fitMode,
          loras:M.regularLoras(s.node).map(item=>({asset_id:item.assetId,scale:item.scale})),safety_enabled:s.node.safetyEnabled,telegram_enabled:s.node.telegramEnabled};
        if(!readyFor(s.node)&&!await ensureReady(s))return;if(!live(s))return;
        s.pending=true;s.epoch=(s.epoch||0)+1;clearTimeout(s.timer);s.node.jobId='';s.job=null;s.node.status='submitting';s.notice='';paint(s);feedback(s,'准备本地任务');let token='';
        if(mode==='edit'){if(!source)throw new Error('连接的编辑源图尚无可读取内容');const blob=await api.sourceBlob(source);if(!live(s))return;token=(await api.uploadImage(blob,name)).upload_token;if(!live(s))return;}
        const reply=await api.submit({...request,init_image_upload_token:'',edit_image_upload_token:mode==='edit'?token:''});
        if(!live(s))return;s.node.jobId=reply.task_id;s.node.resultJobId='';s.node.status=reply.status||'queued';saveState();
      }catch(error){if(live(s)){s.node.status='failed';s.notice=error.message;feedback(s,error.message,'error');}}
      finally{s.starting=false;if(live(s)){s.pending=false;paint(s);saveState();if(s.node.jobId&&M.active(s.node.status))poll(s);}}
    }
    function change(s,input){
      if(s.pending||s.preparing||s.starting||M.active(s.node.status))return;
      const node=s.node;if(input.matches('[data-krea2-safety]'))node.safetyEnabled=input.checked;
      else if(input.matches('[data-krea2-telegram]'))node.telegramEnabled=input.checked;
      else if(input.matches('[data-krea2-edit-adapter]')){node.editAdapterId=input.value;renderLoras(s);}
      else if(input.matches('[data-krea2-edit-adapter-scale]'))node.editAdapterScale=Math.max(.01,Math.min(2,Number(input.value)||1));
      else if(input.matches('[data-krea2-lora-add]')){if(input.value&&M.regularLoras(node).length<regularLoraLimit(node)&&node.loras.length<4&&(node.mode!=='edit'||input.value!==node.editAdapterId)&&!node.loras.some(item=>item.assetId===input.value))node.loras.push({assetId:input.value,scale:1});renderLoras(s);}
      else if(input.dataset.krea2LoraScale!==undefined){const index=Number(input.dataset.krea2LoraScale);if(node.loras[index])node.loras[index].scale=Math.max(0,Math.min(2,Number(input.value)||0));}
      else if(input.dataset.krea2Field){const key=input.dataset.krea2Field;
        if(key==='mode')return;
        if(key==='ratio'){node.ratio=input.value;const dimensions=M.dimensionsForRatio(node.ratio);if(dimensions){node.imageWidth=dimensions.width;node.imageHeight=dimensions.height;}}
        else node[key]=['imageWidth','imageHeight','steps','imageCount','groundingPx'].includes(key)?Number(input.value):['strength','referenceStrength'].includes(key)?Number(input.value):input.value;
        M.normalize(node);if(key==='imageWidth'||key==='imageHeight')node.ratio=M.ratioFromDimensions(node.imageWidth,node.imageHeight);if(key==='baseModelId'){const selected=modelMeta(node.baseModelId);if(selected.precision)node.precision=selected.precision;}if(['ratio','imageWidth','imageHeight'].includes(key))syncSizeControls(s);if(key==='baseModelId')paint(s);}
      else return;saveState();paint(s);
    }
    function mount(node){
      const el=getNodeElement(node.id);if(!el||sessions.has(node.id))return;M.normalize(node);const s={id:node.id,node,el,abort:new AbortController()};sessions.set(node.id,s);
      el.addEventListener('click',event=>{if(event.target.closest('[data-krea2-lora-picker]')){if(canEdit(node.id))loraView?.openPicker(node.id,'krea2');return;}const detail=event.target.closest('[data-krea2-lora-detail]');if(detail){loraView?.openDetailForNode(detail.dataset.krea2LoraDetail,node.id,'krea2').catch(error=>feedback(s,error.message,'error'));return;}const remove=event.target.closest('[data-krea2-lora-remove]');if(remove){if(!canEdit(node.id))return;node.loras.splice(Number(remove.dataset.krea2LoraRemove),1);renderLoras(s);saveState();return;}if(event.target.closest('[data-krea2-run]'))run(s);},{signal:s.abort.signal});
      el.addEventListener('pointerdown',event=>{if(event.target.closest('.desk-krea2__lora-add .desk-select-trigger, .desk-krea2__edit-adapter .desk-select-trigger'))refreshLoras(s).catch(()=>{});},{signal:s.abort.signal});
      el.addEventListener('change',event=>change(s,event.target),{signal:s.abort.signal});
      if(node.status==='submitting'&&!node.jobId)node.status='failed';renderMode(s);renderLoras(s);if(node.jobId)poll(s);if(!status)loadResources().catch(()=>{});
    }
    function canEdit(id){const s=sessions.get(id);return Boolean(s&&live(s)&&!(Boolean(s.pending||s.preparing||s.starting)||M.active(s.node.status)));}
    async function addLoRA(id,identity){
      const s=sessions.get(id);if(!canEdit(id))throw new Error('节点正在运行或已不存在');
      await refreshLoras(s);
      if(!live(s)||!canEdit(id))throw new Error('节点状态已变化，请重新选择');
      if(!loras.some(item=>item.asset_id===identity))throw new Error('LoRA 文件已不存在或不适用于此节点');
      if(s.node.mode==='edit'&&s.node.editAdapterId===identity)throw new Error('该 LoRA 已作为编辑适配器加载');
      if(s.node.loras.some(item=>item.assetId===identity))throw new Error('该 LoRA 已加载');
      if(M.regularLoras(s.node).length>=regularLoraLimit(s.node)||s.node.loras.length>=4)throw new Error('已达到普通 LoRA 数量上限');
      s.node.loras.push({assetId:identity,scale:1});M.normalize(s.node);renderLoras(s);saveState();
    }
    // This controller survives workflow replacement; its shared-data listener does too.
    loraLibrary?.subscribe(()=>{sessions.forEach(renderLoras);});
    function dispose(id){const s=sessions.get(id);if(!s)return;progressView?.releaseWithin(s.el);sessions.delete(id);s.abort.abort();clearTimeout(s.timer);}
    function disposeAll(){[...sessions.keys()].forEach(dispose);clearTimeout(statusTimer);controllerAbort.abort();}
    function reconcile(){[...sessions.values()].forEach(s=>{if(!live(s))dispose(s.id);});Object.values(getCanvas?.().nodes||{}).filter(node=>node.type===M.TYPE).forEach(mount);sessions.forEach(paint);}
    function graphChanged(){sessions.forEach(paint);}
    function connected(from,to){const s=sessions.get(from);if(s?.job?.result_files?.length&&!s.publishing)publish(s,s.job,to).catch(error=>feedback(s,error.message,'error'));graphChanged();}
    window.addEventListener('krea2-models-changed',()=>loadResources(true).catch(()=>{}),{signal:controllerAbort.signal});
    return Object.freeze({nodeHtml,reconcile,dispose,disposeAll,run,graphChanged,addLoRA,canEdit,
      getCancelableTasks:()=>[...sessions.values()].filter(s=>s.node.jobId&&M.active(s.node.status)).map(s=>({key:s.node.jobId,cancel:()=>api.cancel(s.node.jobId)})),
      showStatus:id=>{const s=sessions.get(id);if(s&&(s.job||s.notice))feedback(s,s.notice||'');},
      connections:{targets:M.targets,policy:M.policy,changed:connected,removed:graphChanged}});
  }
  window.DesktopCanvasKrea2=Object.freeze({create});
})();

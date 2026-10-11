// Qwen node controller. Explicit canvas ports; jobs/models/archives belong to the backend.
(function () {
  function create({model:M,api,loraLibrary,loraView,getCanvas,getNodeState,getNodeElement,getImageReferences,getTextNodes,
    materializeText,addNode,connectNodes,setImageFromResult,applyNodeLayout,updateLinkPath,saveState,reportStatus,progressView}={}){
    const sessions=new Map();let status=null,loras=[],loading=null,statusTimer=0;
    const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    const terminal=value=>['succeeded','succeeded_no_telegram','telegram_failed','failed','canceled','cancelled'].includes(value);
    const live=s=>sessions.get(s.id)===s&&getNodeState(s.id)===s.node&&getNodeElement(s.id)===s.el;
    const modelItems=()=>status?.models||[{id:M.DEFAULT_MODEL_ID,name:'Qwen-Image-2.1-Heretic-mlx-8bit'}];
    const meta=node=>modelItems().find(item=>item.id===node.baseModelId)||{};
    const ready=node=>Boolean(status?.environment_ready&&status?.source_ready&&meta(node).ready&&(!M.PRESETS[node.preset]?.adapter||(status?.turbo_adapters?.[node.preset]??status?.turbo_ready)));
    const busy=s=>Boolean(s.pending||s.starting)||M.active(s.node.status);
    const modeLabel=node=>node.mode==='edit'?'图像编辑 · 参考图编辑':'标准生成 · 文生图';
    function syncMode(node){node.mode=M.resolveMode(node,getCanvas?.());M.normalize(node);}
    const keyOf=(ref,index)=>String(ref.id||ref.sourceNodeId||`reference-${index}`);
    function refsFor(s){
      const refs=getImageReferences(s.id)||[],keyed=refs.map((ref,index)=>({ref,key:keyOf(ref,index)}));
      const order=s.node.referenceOrder||[];return [...keyed].sort((a,b)=>{
        const ai=order.indexOf(a.key),bi=order.indexOf(b.key);return(ai<0?order.length+keyed.indexOf(a):ai)-(bi<0?order.length+keyed.indexOf(b):bi);
      });
    }
    const options=(items,selected)=>items.map(([id,name])=>`<option value="${esc(id)}"${String(selected)===String(id)?' selected':''}>${esc(name)}</option>`).join('');
    const sizeOptions=selected=>options([...new Set([512,672,768,832,896,928,1024,1120,1152,1184,1248,1376,1536,1568,2048,selected])].sort((a,b)=>a-b).map(x=>[x,x]),selected);
    function modelOptions(node){
      const items=modelItems(),missing=items.some(item=>item.id===node.baseModelId)?'':`<option value="${esc(node.baseModelId)}" selected>模型已不存在 · ${esc(node.baseModelId)}</option>`;
      return missing+options(items.map(item=>[item.id,(item.label||item.name||item.id)+(item.ready===false?' · 未准备':'')]),node.baseModelId);
    }
    // Options incompatible with the selected Base (Turbo vs non-Turbo) stay visible but disabled.
    const presetOptions=node=>Object.entries(M.PRESETS).map(([id,item])=>`<option value="${esc(id)}"${id===node.preset?' selected':''}${M.presetAllowed(id,meta(node))?'':' disabled'}>${esc(item.label)}</option>`).join('');
    function syncPreset(s,allowStarting=false){
      if(!live(s)||s.pending||(s.starting&&!allowStarting)||(!s.starting&&M.active(s.node.status))||s.preparing)return;
      const changed=M.applyModelPreset(s.node,meta(s.node)),select=s.el.querySelector('[data-qwen21-field="preset"]');
      if(select)select.innerHTML=presetOptions(s.node);
      if(changed){saveState();syncControls(s);}else window.DesktopSelect?.refreshAll?.();
    }
    function syncBase(s,allowStarting=false){
      if(!live(s)||s.pending||(s.starting&&!allowStarting)||s.preparing||status?.preparation?.status==='running')return;
      if(M.selectAvailableBase(s.node,status)){
        const select=s.el.querySelector('[data-qwen21-field="baseModelId"]');if(select)select.innerHTML=modelOptions(s.node);
        window.DesktopSelect?.refreshAll?.();saveState();
      }
      syncPreset(s,allowStarting);
    }
    function loraOptions(node){const available=loras.filter(item=>!node.loras.some(x=>x.assetId===item.asset_id));return`<option value="">${node.loras.length>=4?'已达到 4 个上限':available.length?'＋ 添加普通 LoRA…':'LoRA 目录暂无可用模型'}</option>`+options(available.map(item=>[item.asset_id,item.name]),'');}
    function loraRows(node){if(!node.loras.length)return'<div class="desk-qwen21__empty">未加载普通 LoRA · Viggle 加速适配器由预设自动加载</div>';return node.loras.map((item,index)=>{
      const name=(loraLibrary?.peek(item.assetId)||loras.find(x=>x.asset_id===item.assetId))?.name||item.assetId.slice(0,12);return`<div class="desk-qwen21__lora"><strong title="${esc(name)}">${loraView?`<button type="button" class="desk-lora-row-detail" data-qwen21-lora-detail="${esc(item.assetId)}" title="查看效果与触发词">${esc(name)} ⓘ</button>`:esc(name)}</strong><input class="desk-number" type="number" min="0" max="2" step="0.05" value="${item.scale}" data-qwen21-lora-scale="${index}" aria-label="${esc(name)} LoRA 强度"><button class="desk-button desk-button--danger" data-qwen21-lora-remove="${index}" aria-label="移除 ${esc(name)}">×</button></div>`;
    }).join('');}
    function nodeHtml(node){syncMode(node);return`<section class="desk-node desk-node--qwen21 desk-glass" data-node-id="${esc(node.id)}" aria-label="Qwen 2.1 节点">
      <header class="desk-node__header desk-qwen21__header" data-node-drag-handle><div><p class="desk-node__eyebrow">本地图像生成 / 参考图编辑</p><h2>Qwen 2.1 · MLX</h2></div><div class="desk-node-tools"><span class="desk-status-pill" data-qwen21-status>检查环境</span><button type="button" class="desk-node-delete" data-node-delete aria-label="删除 Qwen 节点">删</button></div></header>
      <button class="desk-port desk-port--in" data-port="in" data-node-id="${esc(node.id)}" aria-label="连接提示词或参考图"></button><button class="desk-port desk-port--out" data-port="out" data-node-id="${esc(node.id)}" aria-label="连接生成图片"></button>
      <div class="desk-qwen21__body" data-node-drag-ignore>
        <div class="desk-param-grid desk-qwen21__grid desk-qwen21__grid--model"><label><span>工作模式 · 自动识别</span><input class="desk-select desk-qwen21__mode" type="text" data-qwen21-mode readonly value="${modeLabel(node)}" title="由画布连线自动识别：仅文本为文生图，接入图像、图片组或导出参考图为图像编辑。"></label><label><span>推理 / 加速 LoRA</span><select class="desk-select" data-qwen21-field="preset">${presetOptions(node)}</select></label>
          <label><span>Base 权重模型</span><select class="desk-select" data-qwen21-field="baseModelId">${modelOptions(node)}</select></label><label><span>LoRA 模型</span>${loraView?`<button type="button" class="desk-button desk-lora-picker-button" data-qwen21-lora-picker aria-label="看图选择 LoRA">＋ 看图选择 LoRA <span>⌄</span></button>`:''}<select ${loraView?'hidden':''} class="desk-select" data-qwen21-lora-add>${loraOptions(node)}</select></label></div>
        <div class="desk-param-grid desk-qwen21__grid desk-qwen21__grid--params"><label><span>画幅比例</span><select class="desk-select" data-qwen21-field="ratio">${options([...M.ASPECT_RATIOS.map(x=>[x,x]),['custom','自定义']],node.ratio)}</select></label><label><span>宽度</span><select class="desk-select" data-qwen21-field="imageWidth">${sizeOptions(node.imageWidth)}</select></label><label><span>高度</span><select class="desk-select" data-qwen21-field="imageHeight">${sizeOptions(node.imageHeight)}</select></label><label><span>步数</span><input class="desk-number" type="number" min="${M.PRESETS[node.preset].minSteps}" max="60" value="${node.steps}" data-qwen21-field="steps" title="标准步数 2–60；Viggle 推荐 6 步，可调 5–60（9 步不等同于官方混合尾段模式）；Turbo 蒸馏模型固定 8 步。"></label><label><span>张数</span><input class="desk-number" type="number" min="1" max="4" value="${node.imageCount}" data-qwen21-field="imageCount"></label><label class="desk-qwen21__seed"><span>Seed</span><input class="desk-number" type="text" inputmode="numeric" placeholder="随机" value="${esc(node.seed)}" data-qwen21-field="seed"></label><label><span>CFG</span><input class="desk-number" type="number" min="1" max="10" step="0.1" value="${node.guidance}" data-qwen21-field="guidance"></label></div>
        <section class="desk-qwen21__loras"><header><strong>已加载 LoRA</strong><small data-qwen21-lora-count>${node.loras.length} / 4 · 按顺序叠加</small></header><div data-qwen21-lora-list>${loraRows(node)}</div></section>
        <section class="desk-qwen21__references" data-qwen21-references${node.mode==='edit'?'':' hidden'} aria-label="参考图顺序"></section>
        <footer class="desk-input-footer desk-qwen21__footer"><div class="desk-pill-row desk-qwen21__meta"><span data-qwen21-inputs>画布连线 · 文本 0 · 参考图 0</span><span data-qwen21-runtime>正在检查共享环境…</span></div><div class="desk-output-controls desk-output-controls--input"><label class="desk-switch"><input type="checkbox" data-qwen21-telegram ${node.telegramEnabled?'checked':''}><span></span><em>发送到 Telegram</em></label></div><div class="desk-action-row"><button type="button" class="desk-generation-action" data-qwen21-run><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m13.5 2-9 12h6l-1 8 10-13h-7z"></path></svg><span class="desk-generation-action__label">开始生成</span></button></div></footer>
      </div><div class="desk-progress-float desk-qwen21__progress" data-qwen21-progress hidden role="status"><div class="desk-progress-float__panel"><div class="desk-progress-float__bar"><span data-progress-bar data-qwen21-bar></span><strong class="desk-progress-float__percent" data-qwen21-percent>处理中</strong></div><span class="desk-progress-float__stage" data-qwen21-stage>Qwen 任务进行中</span></div></div></section>`;}
    function referenceHtml(s){const refs=refsFor(s);return refs.length?refs.map(({ref,key},index)=>`<div class="desk-qwen21__reference"><span title="${esc(ref.name||ref.title||key)}">Image ${index+1} · ${esc(ref.name||ref.title||'参考图')}</span><button class="desk-button" data-qwen21-ref-up="${index}" ${index===0?'disabled':''} aria-label="将参考图 ${index+1} 前移">←</button><button class="desk-button" data-qwen21-ref-down="${index}" ${index===refs.length-1?'disabled':''} aria-label="将参考图 ${index+1} 后移">→</button></div>`).join(''):'<span>请连接参考图，Image 1 / Image 2 按此处顺序对应提示词。</span>';}
    function feedback(s,message='',tone='info'){if(!live(s))return;const task=s.job||{},stage=message||task.progress_text||task.error||'Qwen 2.1 任务';reportStatus?.({message:`Qwen 2.1 · ${stage}`,tone,task:{...task,task_id:s.node.jobId||'',node_id:s.id,node_title:`Qwen 2.1 · ${s.id.slice(-6)}`,operation_label:'Qwen 2.1 本地生成',provider_route:'qwen-image-2.1-mlx',status:s.node.status,status_label:stage,detail_title:'Qwen 2.1 任务状态',progress_text:stage,raw_detail:task.error||message||stage}});}
    function paint(s){
      if(!live(s))return;syncMode(s.node);syncBase(s);const node=s.node,isBusy=busy(s),preparing=s.preparing||status?.preparation?.status==='running',isReady=ready(node);
      const mode=s.el.querySelector('[data-qwen21-mode]');if(mode)mode.value=modeLabel(node);
      const badge=s.el.querySelector('[data-qwen21-status]'),labels={queued:'排队中',processing:'生成中',submitting:'提交中',succeeded:'已完成',succeeded_no_telegram:'已归档',telegram_failed:'已归档',failed:'失败',canceled:'已停止',idle:'就绪'};
      badge.textContent=s.starting&&!s.pending?'准备中':isBusy?(labels[node.status]||'处理中'):preparing?'准备中':isReady?(labels[node.status]||'就绪'):node.status==='failed'?'失败':'待首次生成';
      badge.classList.toggle('is-success',isReady&&!isBusy&&!['failed','canceled'].includes(node.status));badge.classList.toggle('is-busy',isBusy||preparing);badge.classList.toggle('is-error',node.status==='failed');badge.classList.toggle('is-canceled',node.status==='canceled');
      const run=s.el.querySelector('[data-qwen21-run]');run.disabled=Boolean(s.pending||s.starting)||(!isBusy&&preparing);run.querySelector('span').textContent=s.starting&&!s.pending?'准备中':isBusy?'停止生成':preparing?'准备中':node.status==='failed'?'重试生成':'开始生成';
      const refs=refsFor(s);s.el.querySelector('[data-qwen21-inputs]').textContent=`画布连线 · 文本 ${(getTextNodes(s.id)||[]).length} · 参考图 ${refs.length}`;
      const runtime=s.el.querySelector('[data-qwen21-runtime]'),prep=status?.preparation||{};
      runtime.textContent=preparing?(prep.message||'正在准备模型'):isReady?`共享环境已就绪 · ${node.preset==='standard'?'标准':M.PRESETS[node.preset].label}${status?.warm?' · 已热载入':''}`:(status?.reasons?.join(' · ')||'首次生成时自动准备所选模型');
      runtime.classList.toggle('is-success',isReady&&!isBusy);runtime.classList.toggle('is-busy',isBusy||preparing);runtime.classList.toggle('is-error',node.status==='failed'||prep.status==='failed');
      const progress=s.el.querySelector('[data-qwen21-progress]'),show=isBusy||preparing;progress.hidden=!show;progress.classList.toggle('is-visible',show);
      if(show){const amount=preparing&&!isBusy?(prep.total?Math.min(98,Math.max(2,Math.round((prep.downloaded||0)/prep.total*100))):3):Math.min(98,Math.max(2,Number(s.job?.progress||5)));progress.style.setProperty('--progress-percent',amount+'%');s.el.querySelector('[data-qwen21-bar]').style.width=amount+'%';s.el.querySelector('[data-qwen21-percent]').textContent=`${amount}%`;s.el.querySelector('[data-qwen21-stage]').textContent=preparing&&!isBusy?(prep.message||'正在自动准备 Qwen 模型'):(s.job?.progress_text||'Qwen 本地推理中');}
      const preparingModel=preparing&&(!isBusy||s.starting||!node.jobId),task=preparingModel?prep:s.starting?null:s.job;
      progressView?.update(progress,{visible:show,running:show,taskId:preparingModel?'prepare:'+node.baseModelId:node.jobId,
        percent:preparingModel?(Number(prep.total)>0?Number(prep.downloaded||0)/prep.total*100:null):(task?.progress??null),
        title:preparingModel?(prep.message||'正在准备模型'):(task?.progress_text||'Qwen 本地推理中'),detail:'Qwen 2.1 · MLX',
        startedAt:task?.started_at||task?.created_at||s.progressStartedAt,finishedAt:task?.finished_at},s.el);
      const referenceEl=s.el.querySelector('[data-qwen21-references]');referenceEl.hidden=node.mode!=='edit';referenceEl.innerHTML=referenceHtml(s);
      s.el.querySelectorAll('.desk-qwen21__body :is(input,select,[data-qwen21-lora-picker])').forEach(input=>{input.disabled=isBusy||preparing||(node.preset!=='standard'&&input.dataset.qwen21Field==='guidance')||(input.dataset.qwen21Field==='steps'&&M.PRESETS[node.preset].minSteps===M.PRESETS[node.preset].maxSteps);});
      // LoRA rows survive polling: restore their buttons on every idle/terminal paint.
      s.el.querySelectorAll('[data-qwen21-lora-remove]').forEach(button=>{button.disabled=Boolean(isBusy||preparing);});
      // Reference rows were rebuilt above with their first/last boundary locks.
      s.el.querySelectorAll('[data-qwen21-ref-up],[data-qwen21-ref-down]').forEach(button=>{if(isBusy||preparing)button.disabled=true;});
    }
    function renderLoras(s){if(!live(s))return;s.el.querySelector('[data-qwen21-lora-list]').innerHTML=loraRows(s.node);s.el.querySelector('[data-qwen21-lora-add]').innerHTML=loraOptions(s.node);s.el.querySelector('[data-qwen21-lora-count]').textContent=`${s.node.loras.length} / 4 · 按顺序叠加`;window.DesktopSelect?.refreshAll?.();paint(s);}
    function syncControls(s){for(const key of ['ratio','imageWidth','imageHeight','steps','guidance']){const input=s.el.querySelector(`[data-qwen21-field="${key}"]`);if(input){if(['imageWidth','imageHeight'].includes(key))input.innerHTML=sizeOptions(s.node[key]);input.value=String(s.node[key]);if(key==='steps'){input.min=String(M.PRESETS[s.node.preset].minSteps);input.max=String(M.PRESETS[s.node.preset].maxSteps);}}}window.DesktopSelect?.refreshAll?.();paint(s);}
    async function loadResources(force=false){
      if(loraLibrary)loraLibrary.list({engine:'qwen21',limit:200}).then(()=>sessions.forEach(renderLoras)).catch(()=>{});if(loading&&!force)return loading;loading=Promise.all([api.status(),api.listLoras()]).then(([st,ls])=>{status=st;loras=ls.loras||[];sessions.forEach(s=>{const select=s.el.querySelector('[data-qwen21-field="baseModelId"]');if(live(s)&&select)select.innerHTML=modelOptions(s.node);syncPreset(s);renderLoras(s);});scheduleStatus();return st;}).catch(error=>{sessions.forEach(s=>feedback(s,error.message,'error'));throw error;}).finally(()=>{loading=null;});return loading;}
    function scheduleStatus(){clearTimeout(statusTimer);if(status?.preparation?.status==='running'&&sessions.size)statusTimer=setTimeout(()=>loadResources(true).catch(()=>{}),2000);}
    function wait(ms,signal){return new Promise(resolve=>{let done=false,timer;const finish=()=>{if(done)return;done=true;clearTimeout(timer);signal?.removeEventListener('abort',finish);resolve();};timer=setTimeout(finish,ms);signal?.addEventListener('abort',finish,{once:true});});}
    async function ensureReady(s){if(ready(s.node))return true;s.preparing=true;paint(s);let requested=false;
      try{while(live(s)){status=await api.status();if(!live(s))return false;paint(s);if(ready(s.node))return true;const prep=status.preparation||{};
        if(prep.status==='running'){requested=requested||(prep.base_model_id===s.node.baseModelId&&(s.node.preset==='standard'||prep.preset===s.node.preset));await wait(2000,s.abort.signal);continue;}
        if(requested)throw new Error(prep.message||status.reasons?.join(' · ')||'模型准备后仍未就绪');
        const reply=await api.prepare(s.node.baseModelId,s.node.preset);if(!live(s))return false;requested=!reply.already_running;status={...status,preparation:reply.preparation};await wait(800,s.abort.signal);
      }return false;}finally{s.preparing=false;if(live(s))paint(s);scheduleStatus();}}
    async function publish(s,task,onlyTarget=''){if(!live(s)||!task.image_paths?.length||s.publishing)return;s.publishing=true;
      try{const edges=(getCanvas().edges||[]).filter(edge=>edge.from===s.id&&getNodeState(edge.to)?.type==='image');if(onlyTarget&&!edges.some(edge=>edge.to===onlyTarget))return;
        const created=new Set();let previous=edges.length?getNodeState(edges.at(-1).to):null;
        if(!onlyTarget)for(let index=edges.length;index<task.image_paths.length;index++){
          const id=addNode('image'),image=getNodeState(id);if(!image)continue;
          Object.assign(image,M.outputPosition(s.node,previous));applyNodeLayout(id);
          connectNodes(s.id,id,{quiet:true,outputSlot:index});created.add(id);
          edges.push((getCanvas().edges||[]).find(edge=>edge.from===s.id&&edge.to===id));
        }
        for(const edge of onlyTarget?edges.filter(edge=>edge.to===onlyTarget):edges){
          if(!live(s))return;const image=getNodeState(edge?.to);if(!image)continue;
          const slot=Number.isInteger(Number(edge.outputSlot))?Number(edge.outputSlot):edges.indexOf(edge);
          await setImageFromResult(edge.to,s.id,{imagePaths:task.image_paths,files:task.result_files,primaryFile:task.result_file,taskId:task.task_id,prompt:task.prompt,type:'qwen21'},slot);
          if(!live(s))return;
          // Only position newly created outputs; never move user-arranged image nodes.
          if(created.has(edge.to)&&getNodeState(edge.to)===image){Object.assign(image,M.outputPosition(s.node,previous));applyNodeLayout(edge.to);previous=image;}
        }
        if(created.size&&live(s))updateLinkPath();
        if(live(s)){s.node.resultJobId=task.task_id;saveState();}
      }finally{s.publishing=false;}}
    async function poll(s){clearTimeout(s.timer);const id=s.node.jobId,epoch=s.epoch||0;if(!id||!live(s))return;
      try{const task=await api.job(id);if(!live(s)||s.node.jobId!==id||(s.epoch||0)!==epoch)return;s.job=task;s.node.status=task.status;
        if(task.result_files?.length&&['succeeded','succeeded_no_telegram','telegram_failed'].includes(task.status))await publish(s,task);
        paint(s);feedback(s,'',task.error?'error':'info');saveState();if(!terminal(task.status))s.timer=setTimeout(()=>poll(s),1500);
      }catch(error){if(live(s)&&s.node.jobId===id){feedback(s,error.message,'error');if(!terminal(s.node.status))s.timer=setTimeout(()=>poll(s),3000);}}}
    async function run(s){if(s.pending||s.preparing||s.starting)return;if(M.active(s.node.status)){if(s.node.jobId){s.pending=true;try{await api.cancel(s.node.jobId);}catch(error){feedback(s,error.message,'error');}finally{s.pending=false;poll(s);}}return;}
      s.progressStartedAt=Date.now();s.starting=true;paint(s);
      try{if(!status)await loadResources();if(!live(s))return;syncBase(s,true);paint(s);const prompt=(getTextNodes(s.id)||[]).map(node=>materializeText(node)).map(x=>String(x||'').trim()).filter(Boolean).join('\n\n');if(!prompt)throw new Error('请连接含有提示词的文本节点');
        const refs=refsFor(s),limit=M.PRESETS[s.node.preset].references;
        if(M.imageInputIds(s.node,getCanvas()).some(id=>!refs.some(({ref})=>ref.sourceNodeId===id)))throw new Error('连接的参考图节点尚无可读取内容，请先加载图片或完成导出');
        if(s.node.mode==='edit'&&(!refs.length||refs.length>limit))throw new Error(`该编辑预设需要 1–${limit} 张参考图`);
        const mode=s.node.mode,sources=refs.map(({ref})=>({source:ref.base64||ref.imageData||ref.imageUrl||ref.url,name:ref.name||'reference.png'}));
        // This immutable request is paired with the same ordered source snapshot.
        // Subsequent connect/disconnect operations only affect the next task.
        const request={prompt,mode,preset:s.node.preset,base_model_id:s.node.baseModelId,aspect_ratio:s.node.ratio,width:s.node.imageWidth,height:s.node.imageHeight,steps:s.node.steps,image_count:s.node.imageCount,seed:s.node.seed||'random',guidance:s.node.guidance,loras:s.node.loras.map(x=>({asset_id:x.assetId,scale:x.scale})),telegram_enabled:s.node.telegramEnabled};
        if(!ready(s.node)&&!await ensureReady(s))return;if(!live(s))return;s.pending=true;s.epoch=(s.epoch||0)+1;clearTimeout(s.timer);s.node.jobId='';s.node.status='submitting';s.job=null;paint(s);const tokens=[];
        for(const {source,name} of mode==='edit'?sources:[]){if(!source)throw new Error('连接的参考图尚无可读取内容');const blob=await api.sourceBlob(source);if(!live(s))return;const reply=await api.uploadImage(blob,name);if(!live(s))return;tokens.push(reply.upload_token);}
        const reply=await api.submit({...request,reference_upload_tokens:tokens});
        if(!live(s))return;s.node.jobId=reply.task_id;s.node.resultJobId='';s.node.status=reply.status||'queued';saveState();
      }catch(error){if(live(s)){s.node.status='failed';s.notice=error.message;feedback(s,error.message,'error');}}
      finally{s.starting=false;if(live(s)){s.pending=false;paint(s);saveState();if(s.node.jobId&&M.active(s.node.status))poll(s);}}}
    function change(s,input){if(busy(s)||s.preparing)return;const node=s.node;
      if(input.matches('[data-qwen21-telegram]'))node.telegramEnabled=input.checked;
      else if(input.matches('[data-qwen21-lora-add]')){if(input.value&&node.loras.length<4&&!node.loras.some(x=>x.assetId===input.value))node.loras.push({assetId:input.value,scale:1});renderLoras(s);}
      else if(input.dataset.qwen21LoraScale!==undefined){const item=node.loras[Number(input.dataset.qwen21LoraScale)];if(item)item.scale=Math.max(0,Math.min(2,Number(input.value)||0));}
      else if(input.dataset.qwen21Field){const key=input.dataset.qwen21Field;if(key==='ratio'){const dims=M.dimensionsForRatio(input.value);if(dims){node.imageWidth=dims.width;node.imageHeight=dims.height;}}
        else if(key==='mode')return;
        else if(key==='preset'){if(!M.presetAllowed(input.value,meta(node))){input.value=node.preset;return;}if(M.PRESETS[node.preset]?.steps!==M.PRESETS[input.value]?.steps)node.steps=M.PRESETS[input.value]?.steps||40;node.preset=input.value;node.guidance=1;}
        else node[key]=['imageWidth','imageHeight','steps','imageCount','guidance'].includes(key)?Number(input.value):input.value;
        M.normalize(node);if(key==='baseModelId')syncPreset(s);if(['ratio','imageWidth','imageHeight','preset','steps','guidance'].includes(key))syncControls(s);
      }else return;M.normalize(node);saveState();paint(s);}
    function mount(node){const el=getNodeElement(node.id);if(!el||sessions.has(node.id))return;M.normalize(node);const s={id:node.id,node,el,abort:new AbortController()};sessions.set(node.id,s);
      el.addEventListener('click',event=>{if(event.target.closest('[data-qwen21-lora-picker]')){if(canEdit(node.id))loraView?.openPicker(node.id,'qwen21');return;}const detail=event.target.closest('[data-qwen21-lora-detail]');if(detail){loraView?.openDetailForNode(detail.dataset.qwen21LoraDetail,node.id,'qwen21').catch(error=>feedback(s,error.message,'error'));return;}const remove=event.target.closest('[data-qwen21-lora-remove]');if(remove){if(busy(s)||s.preparing)return;node.loras.splice(Number(remove.dataset.qwen21LoraRemove),1);renderLoras(s);saveState();return;}
        const move=event.target.closest('[data-qwen21-ref-up],[data-qwen21-ref-down]');if(move){if(busy(s)||s.preparing)return;const order=refsFor(s).map(x=>x.key),index=Number(move.dataset.qwen21RefUp??move.dataset.qwen21RefDown),to=index+(move.dataset.qwen21RefUp!==undefined?-1:1);if(to>=0&&to<order.length){[order[index],order[to]]=[order[to],order[index]];node.referenceOrder=order;saveState();paint(s);}return;}
        if(event.target.closest('[data-qwen21-run]'))run(s);
      },{signal:s.abort.signal});el.addEventListener('change',event=>change(s,event.target),{signal:s.abort.signal});
      el.addEventListener('pointerdown',event=>{if(event.target.closest('[data-qwen21-lora-add], .desk-qwen21__grid--model .desk-select-trigger'))loadResources().catch(()=>{});},{signal:s.abort.signal});
      if(node.status==='submitting'&&!node.jobId)node.status='failed';paint(s);if(node.jobId)poll(s);if(!status)loadResources().catch(()=>{});
    }
    function canEdit(id){const s=sessions.get(id);return Boolean(s&&live(s)&&!(busy(s)||s.preparing));}
    async function addLoRA(id,identity){
      const s=sessions.get(id);if(!canEdit(id))throw new Error('节点正在运行或已不存在');
      const result=await api.listLoras();loras=result.loras||[];
      if(!live(s)||!canEdit(id))throw new Error('节点状态已变化，请重新选择');
      if(!loras.some(item=>item.asset_id===identity))throw new Error('LoRA 文件已不存在或不适用于此节点');
      if(s.node.loras.some(item=>item.assetId===identity))throw new Error('该 LoRA 已加载');
      if(s.node.loras.length>=4)throw new Error('已达到普通 LoRA 数量上限');
      s.node.loras.push({assetId:identity,scale:1});M.normalize(s.node);renderLoras(s);saveState();
    }
    // This controller survives workflow replacement; its shared-data listener does too.
    loraLibrary?.subscribe(()=>{sessions.forEach(renderLoras);});
    function dispose(id){const s=sessions.get(id);if(!s)return;progressView?.releaseWithin(s.el);sessions.delete(id);s.abort.abort();clearTimeout(s.timer);}
    function disposeAll(){[...sessions.keys()].forEach(dispose);clearTimeout(statusTimer);}
    function reconcile(){[...sessions.values()].forEach(s=>{if(!live(s))dispose(s.id);});Object.values(getCanvas().nodes||{}).filter(node=>node.type===M.TYPE).forEach(mount);sessions.forEach(paint);}
    function graphChanged(){sessions.forEach(paint);}
    function connected(from,to){const s=sessions.get(from);if(s?.job?.result_files?.length&&!s.publishing)publish(s,s.job,to).catch(error=>feedback(s,error.message,'error'));graphChanged();}
    window.addEventListener('qwen21-models-changed',()=>{if(sessions.size)loadResources(true).catch(()=>{});});
    return Object.freeze({nodeHtml,reconcile,dispose,disposeAll,run,graphChanged,addLoRA,canEdit,
      getCancelableTasks:()=>[...sessions.values()].filter(s=>s.node.jobId&&M.active(s.node.status)).map(s=>({key:s.node.jobId,cancel:()=>api.cancel(s.node.jobId)})),
      showStatus:id=>{const s=sessions.get(id);if(s&&(s.job||s.notice))feedback(s,s.notice||'');},
      connections:{targets:M.targets,policy:M.policy,changed:connected,removed:graphChanged}});
  }
  window.DesktopCanvasQwen21=Object.freeze({create});
})();

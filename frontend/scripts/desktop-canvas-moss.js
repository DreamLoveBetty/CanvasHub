// MOSS node controller. Field references own text bindings; dependency edges are their projection.
(function () {
  function create({model:M,api,loraLibrary,loraView,getCanvas,getNodeState,getNodeElement,materializeText,addNode,connectNodes,removeEdges,setImageFromResult,
    applyNodeLayout,updateLinkPath,saveState,reportStatus,progressView,confirmAction,notify,focusTextNode,selectNode,openModelTools,createImage,groupImages,getNegativeTextNodes=()=>[],layoutFactory=null,gridFactory=null,layoutModes=[]}={}){
    const NODE_CHROME=32,REEXPAND_OFFSET=200,sessions=new Map();
    // Negative text nodes reach MOSS by plain edges, never as field bindings; a bound source stays positive.
    const negativeNodes=node=>getNegativeTextNodes(node.id).filter(item=>!M.textDependencies(node).includes(item.id));
    const textPorts={getNodeState,materializeText,getNegativePrompt:node=>negativeNodes(node).map(item=>String(materializeText(item)||'').trim()).filter(Boolean).join('\n\n')};let status=null,loras=[],loading=null,statusTimer=0;
    const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    const terminal=value=>['succeeded','succeeded_no_telegram','telegram_failed','failed','canceled','cancelled'].includes(value);
    const live=s=>sessions.get(s.id)===s&&getNodeState(s.id)===s.node&&getNodeElement(s.id)===s.el;
    const busy=s=>Boolean(s.pending||s.starting)||M.active(s.node.status);
    const preparing=()=>status?.preparation?.status==='running';
    const environmentReady=()=>status?.ready===true&&!preparing();
    const modeAvailable=node=>node.mode==='text'||layoutModes.includes(node.mode);
    const modeLabel=(mode,name)=>[mode,name+(layoutModes.includes(mode)?'':' · 尚未开放'),!layoutModes.includes(mode)];
    const options=(items,selected)=>items.map(([id,name,disabled])=>`<option value="${esc(id)}"${String(selected)===String(id)?' selected':''}${disabled?' disabled':''}>${esc(name)}</option>`).join('');
    const sizeOptions=selected=>options([...new Set([512,640,768,832,896,1024,1152,1216,1344,1536,1792,2048,selected])].sort((a,b)=>a-b).map(x=>[x,x]),selected);
    const modeOptions=node=>options([['text','普通文生图'],modeLabel('layout','自由 Layout'),modeLabel('storyboard','分镜网格')],node.mode);
    const presetOptions=node=>options(Object.entries(M.PRESETS).map(([id,item])=>[id,item.label]),node.preset);
    const modelState=node=>status?.models?.find(item=>item.model_id===node.baseModelId)||(node.baseModelId===M.DEFAULT_MODEL_ID?status?.model:null);
    function modelOptions(node){
      const known=status?.models?.length?status.models:[{model_id:M.DEFAULT_MODEL_ID,label:'MOSS Image SFT · BF16',ready:!status||status.model?.ready}];
      const items=known.some(item=>item.model_id===node.baseModelId)?known:[...known,{model_id:node.baseModelId,label:node.baseModelId,ready:false}];
      return options(items.map(item=>[item.model_id,item.label+(item.ready?'':' · 未绑定')]),node.baseModelId);
    }
    const ratioOptions=node=>options([...M.ASPECT_RATIOS.map(x=>[x,x]),['custom','自定义']],M.ratioFromDimensions(node.imageWidth,node.imageHeight));
    function loraRows(node){if(!node.loras.length)return'<div class="desk-moss__empty">未加载普通 LoRA · 受管适配器由预设自动加载</div>';return node.loras.map((item,index)=>{
      const name=(loraLibrary?.peek(item.assetId)||loras.find(x=>x.asset_id===item.assetId))?.name||item.assetId.slice(0,12);return`<div class="desk-moss__lora"><strong title="${esc(name)}">${loraView?`<button type="button" class="desk-lora-row-detail" data-moss-lora-detail="${esc(item.assetId)}" title="查看效果与触发词">${esc(name)} ⓘ</button>`:esc(name)}</strong><input class="desk-number" type="number" min="${M.LORA_SCALE_MIN}" max="${M.LORA_SCALE_MAX}" step="0.05" value="${item.scale}" data-stepper="off" data-moss-lora-scale="${index}" aria-label="${esc(name)} LoRA 强度"><button class="desk-button desk-button--danger" data-moss-lora-remove="${index}" aria-label="移除 ${esc(name)}">×</button></div>`;}).join('');}
    function nodeHtml(node){return`<section class="desk-node desk-node--moss desk-glass" data-node-id="${esc(node.id)}" aria-label="MOSS 节点">
      <header class="desk-node__header desk-moss__header" data-node-drag-handle><div><p class="desk-node__eyebrow">本地图像生成 / Layout</p><h2>MOSS · MLX</h2></div><div class="desk-node-tools"><span class="desk-status-pill" data-moss-status>检查环境</span><button type="button" class="desk-node-delete" data-node-delete aria-label="删除 MOSS 节点" title="删除 MOSS 节点"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M9 7V4h6v3"></path><path d="m7 7 1 13h8l1-13"></path><path d="M10 11v5M14 11v5"></path></svg></button></div></header>
      <button class="desk-port desk-port--in" data-port="in" data-node-id="${esc(node.id)}" aria-label="连接文本节点"></button><button class="desk-port desk-port--out" data-port="out" data-node-id="${esc(node.id)}" aria-label="连接生成图片"></button>
      <div class="desk-moss__body" data-moss-body data-node-drag-ignore>
        <div class="desk-param-grid desk-moss__grid"><label><span>工作模式</span><select class="desk-select" data-moss-field="mode">${modeOptions(node)}</select></label><label><span>推理预设</span><select class="desk-select" data-moss-field="preset">${presetOptions(node)}</select></label><label><span>Base 权重模型</span><select class="desk-select" data-desk-select-width="content" data-moss-field="baseModelId">${modelOptions(node)}</select></label><label><span>LoRA 模型</span>${loraView?'<button type="button" class="desk-button desk-lora-picker-button" data-moss-lora-picker aria-label="看图选择 LoRA">＋ 看图选择 LoRA <span>⌄</span></button>':'<span class="desk-moss__empty">LoRA 目录不可用</span>'}</label></div>
        <div class="desk-param-grid desk-moss__grid"><label><span>画幅比例</span><select class="desk-select" data-moss-field="ratio">${ratioOptions(node)}</select></label><label><span>宽度</span><select class="desk-select" data-moss-field="imageWidth">${sizeOptions(node.imageWidth)}</select></label><label><span>高度</span><select class="desk-select" data-moss-field="imageHeight">${sizeOptions(node.imageHeight)}</select></label><label><span>Seed</span><input class="desk-number" type="text" inputmode="numeric" placeholder="随机" value="${esc(node.seed)}" data-moss-field="seed"></label></div>
        <section class="desk-moss__prompt"><header><strong>全局描述</strong><span data-moss-source></span></header><textarea rows="3" placeholder="写下画面描述，或连接一个文本节点" data-moss-prompt aria-label="全局描述">${esc(node.prompt)}</textarea></section>
        <section class="desk-moss__loras"><header><strong>已加载 LoRA</strong><small data-moss-lora-count>${node.loras.length} / ${M.MAX_LORAS}</small></header><div class="desk-moss__lora-list" data-moss-lora-list>${loraRows(node)}</div></section>
        <section class="desk-moss-layout" data-moss-layout hidden aria-label="布局画板"></section><section class="desk-moss-layout" data-moss-grid hidden aria-label="分镜画板"></section><button type="button" class="desk-button desk-moss__expand" data-moss-expand hidden>展开设置</button>
        <footer class="desk-input-footer desk-moss__footer"><div class="desk-pill-row desk-moss__meta"><span data-moss-sampling></span><span data-moss-budget></span><span data-moss-runtime>正在检查环境…</span></div><div class="desk-output-controls desk-output-controls--input"><label class="desk-switch"><input type="checkbox" data-moss-telegram ${node.telegramEnabled?'checked':''}><span></span><em>发送到 Telegram</em></label></div><div class="desk-action-row"><button type="button" class="desk-generation-action" data-moss-run><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m13.5 2-9 12h6l-1 8 10-13h-7z"></path></svg><span class="desk-generation-action__label">开始生成</span></button></div></footer>
      </div><div class="desk-progress-float desk-moss__progress" data-moss-progress hidden role="status"><div class="desk-progress-float__panel"><div class="desk-progress-float__bar"><span data-progress-bar data-moss-bar></span><strong class="desk-progress-float__percent" data-moss-percent>处理中</strong></div><span class="desk-progress-float__stage" data-moss-stage>MOSS 任务进行中</span></div></div></section>`;}
    const resolved=s=>M.resolveTextSources(s.node,textPorts);
    const issueText=issue=>({missing:'来源文本节点已删除',incompatible:'来源不是兼容的文本节点',image_reference:'来源文本含图片引用',empty:'来源文本为空',schema:'节点版本过新，无法执行'}[issue.reason]||'来源无效');
    function blockReason(s,input=resolved(s)){
      if(input.issues.length)return issueText(input.issues[0]);
      if(M.textDependencies(s.node).some(id=>getNodeState(id)?.promptRole==='negative'))return'负面文本节点不能绑定为描述，请解除绑定或改回正向';
      if(status&&!modelState(s.node)?.ready)return modelState(s.node)?.reason||'所选 Base 尚未绑定';
      if(!modeAvailable(s.node))return'该工作模式尚未开放';
      if(s.node.mode==='layout'&&!s.node.freeDraft.items.length)return'请在画板里添加区域';
      if(s.node.mode==='text'&&!input.prompt.trim())return'请填写全局描述';
      if(s.node.mode==='storyboard'){const index=input.layoutDraft.panels.findIndex(panel=>!panel.caption.trim());if(index>=0)return`第 ${index+1} 格须填写描述`;}
      return'';
    }
    // A receipt counts only for this exact input, draft revision and bound model; the session object scopes it to the workflow.
    const validReceipt=(s,input)=>s.receipt&&s.receipt.inputFingerprint===input.inputFingerprint&&s.receiptRevision===s.node.draftRevision&&s.receipt.modelFingerprint===modelState(s.node)?.fingerprint?s.receipt:null;
    async function compileNow(s){
      const token=++s.compileToken,input=resolved(s),revision=s.node.draftRevision,receipt=await api.compile(s.node,input);
      if(!live(s)||token!==s.compileToken||revision!==s.node.draftRevision||resolved(s).inputFingerprint!==receipt.inputFingerprint)return null;
      s.receipt=receipt;s.receiptRevision=revision;s.compileError='';paint(s);return validReceipt(s,input);
    }
    function requestCompile(s){
      clearTimeout(s.compileTimer);s.compileToken++;s.compileError='';
      if(!live(s)||!environmentReady()||busy(s)||blockReason(s))return;
      s.compileTimer=setTimeout(()=>compileNow(s).catch(error=>{if(live(s)){s.compileError=error.message;paint(s);}}),800);
    }
    function feedback(s,message='',tone='info'){if(!live(s))return;const task=s.job||{},stage=message||task.progress_text||task.error||'MOSS 任务';reportStatus?.({message:stage.startsWith('MOSS')?stage:`MOSS · ${stage}`,tone,task:{...task,task_id:s.node.jobId||'',node_id:s.id,node_title:`MOSS · ${s.id.slice(-6)}`,operation_label:'MOSS 本地生成',provider_route:'moss-image-mlx',status:s.node.status,status_label:stage,detail_title:'MOSS 任务状态',progress_text:stage,raw_detail:task.error||message||stage}});}
    function paintSource(s,input,locked){
      const node=s.node,tag=s.el.querySelector('[data-moss-source]'),area=s.el.querySelector('[data-moss-prompt]'),isBound=M.bound(node.promptSource),state=isBound?getNodeState(node.promptSource.nodeId):null;
      const failure=input.issues.find(issue=>issue.targetId===M.GLOBAL);
      tag.innerHTML=isBound?`<em class="${failure?'is-error':''}">${esc(failure?issueText(failure):`来源 · ${state?.alias||state?.id||''}`)}</em>${state?'<button type="button" class="desk-button" data-moss-source-focus>跳转</button>':''}<button type="button" class="desk-button" data-moss-source-unbind>解除</button>`:'';
      area.readOnly=isBound;area.disabled=locked;
      if(isBound)area.value=failure?'':input.prompt;
    }
    function paint(s){
      if(!live(s))return;const node=s.node,isBusy=busy(s),prep=status?.preparation||{},isPreparing=preparing(),isReady=environmentReady(),input=resolved(s),reason=blockReason(s,input),receipt=validReceipt(s,input),locked=isBusy||isPreparing||M.unsupported(node);
      const badge=s.el.querySelector('[data-moss-status]'),labels={queued:'排队中',processing:'生成中',submitting:'提交中',succeeded:'已完成',succeeded_no_telegram:'已归档',telegram_failed:'已归档',failed:'失败',canceled:'已停止',idle:'就绪'};
      badge.textContent=isBusy?(labels[node.status]||'处理中'):isPreparing?'准备中':isReady?(labels[node.status]||'就绪'):status?'未就绪':'检查环境';
      badge.classList.toggle('is-success',isReady&&!isBusy&&!['failed','canceled'].includes(node.status));badge.classList.toggle('is-busy',isBusy||isPreparing);badge.classList.toggle('is-error',node.status==='failed');badge.classList.toggle('is-canceled',node.status==='canceled');
      const run=s.el.querySelector('[data-moss-run]');run.disabled=Boolean(s.pending||s.starting)||(!isBusy&&(isPreparing||(isReady&&Boolean(reason))));run.querySelector('span').textContent=isBusy?'停止生成':isPreparing?'准备中':!status?'检查环境':!isReady?'前往模型工具':node.status==='failed'?'重试生成':'开始生成';
      s.el.querySelector('[data-moss-sampling]').textContent=(node.preset==='turbo'?'Turbo · 10 更新 / 15 前向 · CFG 3 → 1':'标准 · Euler 50 步 · CFG 3')+(input.negativePrompt?' · 负面':'');
      const budget=s.el.querySelector('[data-moss-budget]');budget.textContent=reason||s.compileError||(receipt?.tokenBudget.checked?`提示词 ${receipt.tokenBudget.promptTokens}${input.negativePrompt?` · 负面 ${receipt.tokenBudget.negativeTokens}`:''} / ${receipt.tokenBudget.maxTokens}`:'');budget.classList.toggle('is-error',Boolean(input.issues.length||s.compileError)||receipt?.tokenBudget.valid===false);
      const runtime=s.el.querySelector('[data-moss-runtime]');runtime.textContent=isPreparing?(prep.message||'正在准备'):isReady?(status.warm?'已热载入':'环境已就绪'):(status?.reasons?.[0]||'正在检查环境…');runtime.classList.toggle('is-success',isReady&&!isBusy);runtime.classList.toggle('is-busy',isBusy||isPreparing);runtime.classList.toggle('is-error',node.status==='failed'||prep.status==='failed');
      const progress=s.el.querySelector('[data-moss-progress]');progress.hidden=!isBusy;progress.classList.toggle('is-visible',isBusy);
      if(isBusy){const amount=Math.min(98,Math.max(2,Number(s.job?.progress||5)));progress.style.setProperty('--progress-percent',amount+'%');s.el.querySelector('[data-moss-bar]').style.width=amount+'%';s.el.querySelector('[data-moss-percent]').textContent=`${amount}%`;s.el.querySelector('[data-moss-stage]').textContent=s.job?.progress_text||'MOSS 本地推理中';}
      progressView?.update(progress,{visible:isBusy,running:isBusy,taskId:node.jobId,percent:s.job?.progress??null,title:s.job?.progress_text||'MOSS 本地推理中',detail:'MOSS · MLX',startedAt:s.job?.started_at||s.job?.created_at||s.progressStartedAt,finishedAt:s.job?.finished_at},s.el);
      paintSource(s,input,locked);
      s.el.querySelectorAll('.desk-moss__body :is(select,input,[data-moss-lora-picker],[data-moss-lora-remove])').forEach(control=>{if(!control.closest('[data-moss-layout]'))control.disabled=locked;});
      paintLayout(s);syncHeight(s);
    }
    function paintLayout(s){
      const expand=s.el.querySelector('[data-moss-expand]'),editors=[['[data-moss-layout]','layout',s.layout],['[data-moss-grid]','storyboard',s.grid]],active=editors.some(([,mode,editor])=>editor&&s.node.mode===mode);
      s.el.classList.toggle('is-layout',s.node.mode!=='text');
      expand.hidden=!active||s.node.settingsExpanded;
      editors.forEach(([selector,mode,editor])=>{const host=s.el.querySelector(selector);host.hidden=!editor||s.node.mode!==mode||!s.node.settingsExpanded;if(!host.hidden)editor.render();});
    }
    // Measured here, never in the model. Text mode is the fixed compact size; only the bottom edge moves.
    function syncHeight(s){const height=s.node.mode==='text'?M.HEIGHT:Math.max(M.HEIGHT,Math.ceil(s.el.querySelector('[data-moss-body]').scrollHeight+s.el.querySelector('.desk-moss__header').offsetHeight+NODE_CHROME));if(height!==s.node.height){s.node.height=height;applyNodeLayout(s.id);updateLinkPath();}}
    function renderLoras(s){if(!live(s))return;s.el.querySelector('[data-moss-lora-list]').innerHTML=loraRows(s.node);s.el.querySelector('[data-moss-lora-count]').textContent=`${s.node.loras.length} / ${M.MAX_LORAS}`;paint(s);}
    function syncControls(s){const node=s.node;for(const [key,html] of [['imageWidth',sizeOptions(node.imageWidth)],['imageHeight',sizeOptions(node.imageHeight)],['ratio',ratioOptions(node)]]){const select=s.el.querySelector(`[data-moss-field="${key}"]`);if(select)select.innerHTML=html;}window.DesktopSelect?.refreshAll?.();paint(s);}
    function refreshModelSelect(s){const select=s.el.querySelector('[data-moss-field="baseModelId"]');if(select)select.innerHTML=modelOptions(s.node);window.DesktopSelect?.refreshAll?.();}
    function loadResources(force=false){
      if(loraLibrary)loraLibrary.list({engine:'moss',limit:200}).then(()=>sessions.forEach(renderLoras)).catch(()=>{});
      if(loading&&!force)return loading;
      loading=Promise.all([api.status(),api.listLoras()]).then(([st,ls])=>{status=st;loras=ls.loras||[];sessions.forEach(s=>{if(live(s)){refreshModelSelect(s);renderLoras(s);requestCompile(s);}});scheduleStatus();return st;}).catch(error=>{sessions.forEach(s=>feedback(s,error.message,'error'));throw error;}).finally(()=>{loading=null;});
      return loading;
    }
    function scheduleStatus(){clearTimeout(statusTimer);if(preparing()&&sessions.size)statusTimer=setTimeout(()=>loadResources(true).catch(()=>{}),2000);}
    const hasEdge=(from,to)=>(getCanvas().edges||[]).some(edge=>edge.from===from&&edge.to===to);
    // Internal edge changes must not re-enter the user-facing connection rules below.
    function quietly(s,action){s.internalEdges=true;try{return action();}finally{s.internalEdges=false;}}
    const dropEdge=(s,from)=>quietly(s,()=>removeEdges((getCanvas().edges||[]).filter(edge=>edge.from===from&&edge.to===s.id).map(edge=>edge.id),{quiet:true}));
    function afterBinding(s){s.node.draftRevision+=1;s.receipt=null;saveState();paint(s);requestCompile(s);}
    function listTextSources(){return Object.values(getCanvas().nodes||{}).filter(node=>node.type==='text').map(node=>({id:node.id,alias:node.alias||`文本 ${node.id.slice(-6)}`,preview:String(materializeText(node)||'').slice(0,120)}));}
    // Unbinding freezes what the source says now; a source that cannot be read leaves the old inline value untouched.
    function freezeField(s,slot){
      const source=slot.holder[slot.sourceKey],state=getNodeState(source.nodeId);
      if(state?.type==='text'){const value=materializeText(state);if(typeof value==='string'&&value.trim())slot.holder[slot.valueKey]=value;}
      slot.holder[slot.sourceKey]={kind:'inline'};
    }
    function bindTextSource(id,targetId,field,sourceNodeId){
      const s=sessions.get(id);if(!canEdit(id))throw new Error('节点正在运行或已不存在');
      const slot=M.bindingSlot(s.node,targetId,field);if(!slot)throw new Error('绑定目标不存在');
      const previous=slot.holder[slot.sourceKey];
      if(sourceNodeId){
        if(getNodeState(sourceNodeId)?.type!=='text')throw new Error('只能绑定文本节点');
        if(!hasEdge(sourceNodeId,id))quietly(s,()=>connectNodes(sourceNodeId,id,{quiet:true}));
        if(!hasEdge(sourceNodeId,id))throw new Error('文本节点连接失败');
        slot.holder[slot.sourceKey]={kind:'text_node',nodeId:sourceNodeId};
      }else if(M.bound(previous))freezeField(s,slot);
      if(M.bound(previous)&&previous.nodeId!==sourceNodeId&&!M.textDependencies(s.node).includes(previous.nodeId))dropEdge(s,previous.nodeId);
      afterBinding(s);
    }
    function updateDraft(id,mode,draft,expectedRevision){
      const s=sessions.get(id);if(!canEdit(id))throw new Error('节点正在运行或已不存在');
      if(s.node.draftRevision!==expectedRevision)throw new Error('草稿已变化，请重试');
      const key=mode==='storyboard'?'gridDraft':'freeDraft',previous=s.node[key],before=M.textDependencies(s.node);
      s.node[key]=draft;M.normalize(s.node);
      if(!syncEdges(s,before)){s.node[key]=previous;throw new Error('文本节点连接失败');}
      afterBinding(s);
    }
    // Undo and import can bring references back, so projection runs both ways. Live sources only: a dead reference has no edge.
    function syncEdges(s,before){
      const after=M.textDependencies(s.node);
      for(const nodeId of after){if(getNodeState(nodeId)?.type==='text'&&!hasEdge(nodeId,s.id)){quietly(s,()=>connectNodes(nodeId,s.id,{quiet:true}));if(!hasEdge(nodeId,s.id))return false;}}
      before.filter(nodeId=>!after.includes(nodeId)).forEach(nodeId=>dropEdge(s,nodeId));
      return true;
    }
    async function importDraft(id,raw){
      const s=sessions.get(id);if(!canEdit(id))throw new Error('节点正在运行或已不存在');
      const receipt=await api.importDraft(raw);
      if(!live(s)||!canEdit(id))throw new Error('节点状态已变化，请重新导入');
      if(!confirmAction?.('导入会替换当前草稿、全局描述和输出尺寸，确定继续？'))return false;
      const before=M.textDependencies(s.node);M.applyImport(s.node,receipt.draft);syncEdges(s,before);
      s.el.querySelector('[data-moss-prompt]').value=s.node.prompt;syncControls(s);afterBinding(s);return true;
    }
    // A local preview of the bound text; nothing here is written back to the node.
    function fieldPreview(s,item){
      const field=item.label==='text'?'text':'caption',source=item[field+'Source'];
      if(!M.bound(source))return{bound:false,text:item[field]||''};
      const state=getNodeState(source.nodeId);
      if(state?.type!=='text')return{bound:true,nodeId:source.nodeId,issue:'来源已删除'};
      return{bound:true,nodeId:source.nodeId,alias:state.alias||'',text:String(materializeText(state)||'')};
    }
    function textConnected(s,from){
      if(M.textDependencies(s.node).includes(from))return;
      if(canEdit(s.id)&&!M.bound(s.node.promptSource)){s.node.promptSource={kind:'text_node',nodeId:from};afterBinding(s);return;}
      dropEdge(s,from);notify?.(busy(s)?'节点运行中，暂不能修改文本来源。':'全局描述已有文本来源。要绑定到区域，请选中区域后在工具条里选择。');
    }
    // Deleting a node keeps its references so the user can see what broke; only a removed edge means unbind.
    function textDisconnected(s,from){
      if(!getNodeState(from)||!M.textDependencies(s.node).includes(from))return;
      const affected=M.allBindings(s.node).filter(item=>item.source?.nodeId===from);
      if(!canEdit(s.id)||!confirmAction?.(`断开后这 ${affected.length} 处内容将解除绑定，保留当前文字为内联内容。确定断开？`)){quietly(s,()=>connectNodes(from,s.id,{quiet:true}));return;}
      affected.forEach(item=>freezeField(s,M.bindingSlot(s.node,item.targetId,item.field)));afterBinding(s);
    }
    // Files and image_paths share one order; an overlay is in neither.
    const panelFiles=task=>(task?.params?.artifacts||[]).filter(item=>item.role!=='grid_overlay').map((item,index)=>({...item,imageUrl:task.image_paths?.[index]})).filter(item=>item.role==='panel'&&item.imageUrl).sort((a,b)=>a.panel_index-b.panel_index);
    // Panels are plain image nodes with no edge back here, so a rerun can never write over them.
    async function expand(s,task,offset=0){
      const panels=panelFiles(task);if(!panels.length)return false;
      s.node.panelJobId=task.task_id;saveState();
      const page=(getCanvas().edges||[]).map(edge=>edge.from===s.id?getNodeState(edge.to):null).find(node=>node?.type==='image'),x=page?.x??s.node.x+s.node.width+100,y=(page?page.y+page.height+80:s.node.y)+offset,ids=[];
      for(const [index,panel] of panels.entries()){
        const id=await createImage({imageUrl:panel.imageUrl,file:panel.file,taskId:task.task_id,prompt:panel.caption||task.prompt,title:`切 ${index+1}`,provider:M.TYPE,source:'result-node'});
        if(!live(s))return false;const image=getNodeState(id);if(!image)continue;
        Object.assign(image,{x:x+index*40,y:y+index*40});applyNodeLayout(id);ids.push(id);
      }
      if(ids.length>1)groupImages(ids);
      updateLinkPath();saveState();return true;
    }
    async function expandPanels(id,taskId){
      const s=sessions.get(id);if(!s||!live(s))return false;
      const task=s.job?.task_id===taskId?s.job:await api.job(taskId);
      if(!live(s)||!panelFiles(task).length)return false;
      if(s.node.panelJobId===taskId&&!confirmAction?.('这次结果已展开过分格，再次展开会新建一组图片，确定继续？'))return false;
      return expand(s,task,s.node.panelJobId===taskId?REEXPAND_OFFSET:0);
    }
    // Only the whole page goes to the image node; panels become their own nodes once per task.
    async function publish(s,task,onlyTarget=''){
      if(!live(s)||!task.image_paths?.length||s.publishing||(!onlyTarget&&s.node.resultJobId===task.task_id))return;s.publishing=true;
      try{
        const edges=(getCanvas().edges||[]).filter(edge=>edge.from===s.id&&getNodeState(edge.to)?.type==='image');
        if(onlyTarget&&!edges.some(edge=>edge.to===onlyTarget))return;
        let created=false;
        if(!onlyTarget&&!edges.length){const id=addNode('image'),image=getNodeState(id);if(!image)return;Object.assign(image,{x:s.node.x+s.node.width+100,y:s.node.y});applyNodeLayout(id);connectNodes(s.id,id,{quiet:true,outputSlot:0});created=true;edges.push((getCanvas().edges||[]).find(edge=>edge.from===s.id&&edge.to===id));}
        const output={imagePaths:task.image_paths.slice(0,1),files:(task.result_files||[]).slice(0,1),primaryFile:task.result_file,taskId:task.task_id,prompt:task.prompt,type:M.TYPE};
        for(const edge of onlyTarget?edges.filter(edge=>edge.to===onlyTarget):edges){
          if(!live(s))return;const image=getNodeState(edge?.to);if(!image)continue;
          await setImageFromResult(edge.to,s.id,output,0);
          if(!live(s))return;
          if(created&&getNodeState(edge.to)===image){Object.assign(image,{x:s.node.x+s.node.width+100,y:s.node.y});applyNodeLayout(edge.to);}
        }
        if(created)updateLinkPath();
        s.node.resultJobId=task.task_id;saveState();
        if(!onlyTarget&&s.node.panelJobId!==task.task_id)await expand(s,task).catch(error=>feedback(s,`分格展开失败：${error.message}`,'error'));
      }finally{s.publishing=false;}
    }
    async function poll(s){clearTimeout(s.timer);const id=s.node.jobId;if(!id||!live(s))return;
      try{const task=await api.job(id);if(!live(s)||s.node.jobId!==id)return;s.job=task;s.node.status=task.status;
        if(task.result_files?.length&&['succeeded','succeeded_no_telegram','telegram_failed'].includes(task.status))await publish(s,task);
        if(!live(s)||s.node.jobId!==id)return;
        paint(s);feedback(s,'',task.error?'error':'info');saveState();if(!terminal(task.status))s.timer=setTimeout(()=>poll(s),1500);else requestCompile(s);
      }catch(error){if(live(s)&&s.node.jobId===id){feedback(s,error.message,'error');if(!terminal(s.node.status))s.timer=setTimeout(()=>poll(s),3000);}}}
    async function run(s){
      if(s.pending||s.starting)return;
      if(M.active(s.node.status)){if(s.node.jobId){s.pending=true;try{await api.cancel(s.node.jobId);}catch(error){feedback(s,error.message,'error');}finally{s.pending=false;poll(s);}}return;}
      if(preparing())return;
      if(status&&!environmentReady()){openModelTools?.();return;}
      s.progressStartedAt=Date.now();s.starting=true;clearTimeout(s.compileTimer);paint(s);
      try{
        if(!status)await loadResources();if(!live(s))return;
        if(!environmentReady())throw new Error(status.reasons?.[0]||'MOSS 环境尚未就绪');
        const input=resolved(s),reason=blockReason(s,input);if(reason)throw new Error(reason);
        // The server recompiles this frozen input; source edits after this point only affect the next task.
        const receipt=validReceipt(s,input)||await compileNow(s);if(!live(s))return;
        if(!receipt)throw new Error('输入已变化，请重新生成');
        if(!receipt.tokenBudget.checked||!receipt.tokenBudget.valid)throw new Error(receipt.tokenBudget.reason||'提示词未通过 token 预算检查');
        s.pending=true;clearTimeout(s.timer);s.node.jobId='';s.node.status='submitting';s.job=null;paint(s);
        const reply=await api.submit(s.node,input);if(!live(s))return;
        s.node.jobId=reply.task_id;s.node.resultJobId='';s.node.status=reply.status||'queued';saveState();
      }catch(error){if(live(s)){s.node.status='failed';s.notice=error.message;feedback(s,error.message,'error');}}
      finally{s.starting=false;if(live(s)){s.pending=false;paint(s);saveState();if(s.node.jobId&&M.active(s.node.status))poll(s);}}
    }
    function resize(s,next){
      const node=s.node,{imageWidth:width,imageHeight:height}=node;
      if(node.freeDraft.items.length&&!confirmAction?.('输出尺寸变化会同比缩放全部布局区域，确定继续？'))return false;
      Object.assign(node,next);M.scaleFreeDraft(node,width,height);node.draftRevision+=1;return true;
    }
    function change(s,input){if(busy(s)||preparing())return;const node=s.node;
      if(input.matches('[data-moss-telegram]'))node.telegramEnabled=input.checked;
      else if(input.dataset.mossLoraScale!==undefined){const item=node.loras[Number(input.dataset.mossLoraScale)];if(item){item.scale=M.normalizeLoraScale(input.value);input.value=String(item.scale);}}
      else if(input.dataset.mossField){const key=input.dataset.mossField;
        if(key==='ratio'){const size=M.dimensionsForRatio(input.value);if(size&&!resize(s,{imageWidth:size.width,imageHeight:size.height})){syncControls(s);return;}}
        else if(key==='imageWidth'||key==='imageHeight'){const next={imageWidth:node.imageWidth,imageHeight:node.imageHeight,[key]:Number(input.value)};if(!M.withinPixels(next.imageWidth,next.imageHeight)){notify?.('总像素不能超过 2,097,152。');input.value=String(node[key]);return;}if(!resize(s,next)){input.value=String(node[key]);return;}}
        else if(key==='mode'&&!M.MODES.includes(input.value))return;
        else node[key]=input.value;
        M.normalize(node);if(key==='seed')input.value=node.seed;if(['ratio','imageWidth','imageHeight','mode'].includes(key))syncControls(s);
      }else return;
      saveState();paint(s);requestCompile(s);}
    function mount(node){const el=getNodeElement(node.id);if(!el||sessions.has(node.id))return;M.normalize(node);const s={id:node.id,node,el,abort:new AbortController(),compileToken:0,receipt:null,compileError:''};sessions.set(node.id,s);
      const editorPorts=(host,mode)=>({host:el.querySelector(host),resized:()=>syncHeight(s),getNode:()=>s.node,canEdit:()=>canEdit(node.id),updateDraft:draft=>updateDraft(node.id,mode,draft,s.node.draftRevision),
        listTextSources,bindTextSource:(targetId,field,sourceId)=>bindTextSource(node.id,targetId,field,sourceId),focusTextNode:id=>focusTextNode?.(id),fieldPreview:item=>fieldPreview(s,item),
        compile:()=>compileNow(s),importDraft:raw=>importDraft(node.id,raw),collapse:()=>{node.settingsExpanded=false;paint(s);saveState();},select:()=>selectNode?.(node.id),notify:message=>notify?.(message)});
      s.layout=layoutFactory?.(editorPorts('[data-moss-layout]','layout'))||null;
      s.grid=gridFactory?.({...editorPorts('[data-moss-grid]','storyboard'),setOption:(key,value)=>{if(canEdit(node.id)){node[key]=value===true;saveState();}},
        warnings:()=>{const receipt=validReceipt(s,resolved(s));return receipt?.compiled.warnings||[];},hasPanels:()=>panelFiles(s.job).length>0,
        expandPanels:()=>expandPanels(node.id,s.job.task_id).catch(error=>feedback(s,error.message,'error'))})||null;
      el.addEventListener('click',event=>{
        if(event.target.closest('[data-moss-lora-picker]')){if(canEdit(node.id))loraView?.openPicker(node.id,M.TYPE);return;}
        const detail=event.target.closest('[data-moss-lora-detail]');if(detail){loraView?.openDetailForNode(detail.dataset.mossLoraDetail,node.id,M.TYPE).catch(error=>feedback(s,error.message,'error'));return;}
        const remove=event.target.closest('[data-moss-lora-remove]');if(remove){if(!canEdit(node.id))return;node.loras.splice(Number(remove.dataset.mossLoraRemove),1);renderLoras(s);saveState();return;}
        if(event.target.closest('[data-moss-source-focus]')){focusTextNode?.(node.promptSource.nodeId);return;}
        if(event.target.closest('[data-moss-source-unbind]')){try{bindTextSource(node.id,M.GLOBAL,'prompt',null);s.el.querySelector('[data-moss-prompt]').value=node.prompt;}catch(error){feedback(s,error.message,'error');}return;}
        if(event.target.closest('[data-moss-expand]')){node.settingsExpanded=true;paint(s);saveState();return;}
        if(event.target.closest('[data-moss-run]')){s.layout?.close();s.grid?.close();run(s);}
      },{signal:s.abort.signal});
      el.addEventListener('change',event=>{if(event.target.matches('[data-moss-prompt]')){if(!M.bound(node.promptSource))saveState();return;}change(s,event.target);},{signal:s.abort.signal});
      el.addEventListener('input',event=>{if(event.target.matches('[data-moss-prompt]')&&!M.bound(node.promptSource)&&canEdit(node.id)){node.prompt=event.target.value;paint(s);requestCompile(s);}},{signal:s.abort.signal});
      if(node.status==='submitting'&&!node.jobId)node.status='failed';paint(s);if(node.jobId)poll(s);if(!status)loadResources().catch(()=>{});else requestCompile(s);
    }
    function canEdit(id){const s=sessions.get(id);return Boolean(s&&live(s)&&!busy(s)&&!preparing()&&!M.unsupported(s.node));}
    async function addLoRA(id,identity){
      const s=sessions.get(id);if(!canEdit(id))throw new Error('节点正在运行或已不存在');
      const result=await api.listLoras();loras=result.loras||[];
      if(!live(s)||!canEdit(id))throw new Error('节点状态已变化，请重新选择');
      if(!loras.some(item=>item.asset_id===identity))throw new Error('LoRA 文件已不存在或不适用于此节点');
      if(s.node.loras.some(item=>item.assetId===identity))throw new Error('该 LoRA 已加载');
      if(s.node.loras.length>=M.MAX_LORAS)throw new Error('已达到普通 LoRA 数量上限');
      s.node.loras.push({assetId:identity,scale:1});M.normalize(s.node);renderLoras(s);saveState();
    }
    loraLibrary?.subscribe(()=>{sessions.forEach(renderLoras);});
    function dispose(id){const s=sessions.get(id);if(!s)return;progressView?.releaseWithin(s.el);s.layout?.dispose();s.grid?.dispose();sessions.delete(id);s.abort.abort();clearTimeout(s.timer);clearTimeout(s.compileTimer);s.compileToken++;}
    function disposeAll(){[...sessions.keys()].forEach(dispose);clearTimeout(statusTimer);}
    function reconcile(){[...sessions.values()].forEach(s=>{if(!live(s))dispose(s.id);});Object.values(getCanvas().nodes||{}).filter(node=>node.type===M.TYPE).forEach(mount);sessions.forEach(paint);}
    function graphChanged(){sessions.forEach(s=>{paint(s);requestCompile(s);});}
    function connected(from,to){
      const output=sessions.get(from);if(output?.job?.result_files?.length&&!output.publishing)publish(output,output.job,to).catch(error=>feedback(output,error.message,'error'));
      const input=sessions.get(to);if(input&&!input.internalEdges&&getNodeState(from)?.type==='text'&&getNodeState(from).promptRole!=='negative')textConnected(input,from);
      graphChanged();
    }
    function removed(edges=[]){edges.forEach(edge=>{const s=sessions.get(edge.to);if(s&&!s.internalEdges)textDisconnected(s,edge.from);});graphChanged();}
    window.addEventListener('moss-models-changed',()=>{if(sessions.size)loadResources(true).catch(()=>{});});
    return Object.freeze({nodeHtml,reconcile,dispose,disposeAll,run:id=>{const s=sessions.get(id);return s?run(s):undefined;},graphChanged,addLoRA,expandPanels,canEdit,listTextSources,bindTextSource,updateDraft,
      getCancelableTasks:()=>[...sessions.values()].filter(s=>s.node.jobId&&M.active(s.node.status)).map(s=>({key:s.node.jobId,cancel:()=>api.cancel(s.node.jobId)})),
      showStatus:id=>{const s=sessions.get(id);if(s&&(s.job||s.notice))feedback(s,s.notice||'');},
      connections:{targets:M.targets,policy:M.policy,changed:connected,removed}});
  }
  window.DesktopCanvasMoss=Object.freeze({create});
})();

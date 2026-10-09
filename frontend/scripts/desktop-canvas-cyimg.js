// 绘栾 Canvas controller. Catalog and jobs live on the server; only node UI state lives here.
(function () {
  function create({model:M,api, getCanvas,getNodeState,getNodeElement,getImageReferences,getTextNodes,
    materializeText, audioAssets,addNode,connectNodes,setImageFromResult,refreshVideoNode,saveState,reportStatus,progressView}) {
    const sessions=new Map();
    let catalog=null, catalogError='', catalogPromise=null;
    const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const kind=node=>node.type==='cyimg_video'?'video':'image';
    const choices=node=>catalog?.models?.[kind(node)] || [];
    const selected=node=>choices(node).find(item=>item.id===node.modelId);
    const live=s=>sessions.get(s.id)===s && getNodeState(s.id)===s.node && getNodeElement(s.id)===s.el;
    const terminal=status=>['succeeded','succeeded_no_telegram','telegram_failed','failed','canceled'].includes(status);
    function valueFor(node,field) {
      const value=node.parameters[field.name], fallback=field.default;
      if(field.type==='custom_radio') return field.options.some(option=>String(option.value)===String(value)) ? value
        : field.options.some(option=>String(option.value)===String(fallback)) ? fallback : field.options[0]?.value ?? '';
      return value===undefined || value===null || value==='' ? fallback : value;
    }
    function fields(node) {
      const item=selected(node);
      return (item?.fields || []).filter(field=>field.visible && !['image','video','audio'].includes(field.type)).map(field=>{
        const value=valueFor(node,field), label=esc(field.label);
        if(field.type==='custom_radio') return `<label><span>${label}</span><select class="desk-select" data-cyimg-field="${esc(field.name)}">${field.options.map(option=>`<option value="${esc(option.value)}"${String(value)===String(option.value)?' selected':''}>${esc(option.label)}${option.extra_credit?' · '+(String(option.extra_credit).includes('%')?'费率 '+esc(option.extra_credit):'+'+esc(option.extra_credit)+' 积分'):''}</option>`).join('')}</select></label>`;
        if(field.type==='boolean') return `<label class="desk-cyimg__check"><input type="checkbox" data-cyimg-field="${esc(field.name)}" ${value===true?'checked':''}><span>${label}</span></label>`;
        if(field.type==='number') return `<label><span>${label}</span><input type="number" min="0" max="300" step="1" data-cyimg-field="${esc(field.name)}" value="${esc(value ?? '')}"></label>`;
        return `<label><span>${label}</span><input type="text" maxlength="10000" data-cyimg-field="${esc(field.name)}" value="${esc(value ?? '')}"></label>`;
      }).join('');
    }
    function modelOptions(node) {
      const list=choices(node), counts=new Map();
      list.forEach(item=>counts.set(item.label,(counts.get(item.label)||0)+1));
      return list.length ? list.map(item=>`<option value="${esc(item.id)}"${item.id===node.modelId?' selected':''}>${esc(item.label)}${counts.get(item.label)>1?' · '+esc(item.channel.split(':').pop().slice(-7)):''}</option>`).join('')
        : '<option value="">正在加载模型目录…</option>';
    }
    function nodeHtml(node) {
      M.normalize(node);
      const video=kind(node)==='video', title=video?'绘栾视频':'绘栾图像';
      return `<section class="desk-node desk-node--cyimg desk-node--${esc(node.type)} desk-glass" data-node-id="${esc(node.id)}" aria-label="${title}节点">
        <header class="desk-cyimg__header" data-node-drag-handle><span class="desk-cyimg__icon">${video?M.ICON_VIDEO:M.ICON_IMAGE}</span><div><strong>${title}</strong><small>${video?'VIDEO':'IMAGE'} GENERATION · CYIMG API</small></div><span class="desk-status-pill" data-cyimg-status>目录加载中</span><button class="desk-node-delete" data-node-delete aria-label="删除${title}节点">删</button></header>
        <button class="desk-port desk-port--in" data-port="in" data-node-id="${esc(node.id)}" aria-label="连接提示词与素材"></button>
        <button class="desk-port desk-port--out" data-port="out" data-node-id="${esc(node.id)}" aria-label="连接生成结果"></button>
        <div class="desk-cyimg__body" data-node-drag-ignore>
          <label class="desk-cyimg__model"><span>在线模型</span><select class="desk-select" data-cyimg-model>${modelOptions(node)}</select></label>
          <div class="desk-cyimg__fields" data-cyimg-fields>${fields(node)}</div>
          <div class="desk-cyimg__inputs" data-cyimg-source-hint>连接文本节点作为提示词，连接素材节点作为参考</div>
          <footer class="desk-cyimg__footer"><div><small data-cyimg-credit>模型积分以绘栾结算为准</small><label class="desk-cyimg__telegram"><input type="checkbox" data-cyimg-telegram ${node.telegramEnabled?'checked':''}>发送到 Telegram</label></div><button type="button" class="desk-generation-action desk-cyimg__run" data-cyimg-run title="开始生成" aria-label="开始生成"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m13.5 2-9 12h6l-1 8 10-13h-7z"></path></svg><span class="desk-generation-action__label">开始生成</span></button></footer>
        </div><div class="desk-progress-float desk-cyimg__progress" data-cyimg-progress hidden role="status"><div class="desk-progress-float__panel"><div class="desk-progress-float__bar"><span data-cyimg-bar></span><strong class="desk-progress-float__percent" data-cyimg-percent>处理中</strong></div><span data-cyimg-stage>绘栾任务进行中</span></div></div>
      </section>`;
    }
    function incoming(s,type) {
      return (getCanvas().edges||[]).filter(edge=>edge.to===s.id).map(edge=>getNodeState(edge.from)).filter(node=>node?.type===type);
    }
    function paint(s) {
      if(!live(s)) return;
      const node=s.node, busy=Boolean(s.pending)||M.active(node.status), item=selected(node), badge=s.el.querySelector('[data-cyimg-status]');
      const statusText={idle:'就绪',submitting:'提交中',queued:'处理中',processing:'处理中',running:'处理中',succeeded:'已完成',succeeded_no_telegram:'已归档',telegram_failed:'已归档',failed:'失败',canceled:'已停止'};
      badge.textContent=busy?statusText[node.status]||'处理中':catalogError?'目录错误':!catalog?'目录加载中':!item?'选择模型':!catalog.api_key_configured?'待配置':statusText[node.status]||'就绪';
      badge.classList.toggle('is-success',!busy && ['idle','succeeded','succeeded_no_telegram'].includes(node.status) && !!item && !!catalog?.api_key_configured);
      const button=s.el.querySelector('[data-cyimg-run]');button.disabled=busy||!item;
      button.setAttribute('aria-busy',String(busy));button.querySelector('span').textContent=busy?'生成中':node.status==='failed'?'重试生成':'开始生成';
      const hint=s.el.querySelector('[data-cyimg-source-hint]');
      const textCount=getTextNodes(s.id).length,imageCount=getImageReferences(s.id).length;
      const videoCount=incoming(s,'video').filter(n=>n.mediaUrl).length,audioCount=incoming(s,'audio').length;
      hint.textContent=catalogError||(!catalog?.api_key_configured?'请先在设置中填写绘栾 API Key':`画布连线 · 文本 ${textCount} · 图片 ${imageCount}${kind(node)==='video'?` · 视频 ${videoCount} · 音频 ${audioCount}`:''}`);
      const credit=s.el.querySelector('[data-cyimg-credit]');
      if(item){let amount=item.credit_estimate;for(const field of item.fields||[]){const option=field.options?.find(v=>String(v.value)===String(valueFor(node,field)));if(amount!==null&&amount!==undefined){const extra=Number(option?.extra_credit||0);amount=Number.isFinite(extra)?amount+extra:null;}}credit.textContent=amount===null||amount===undefined?'积分按绘栾实时结算':`参考积分约 ${amount} · 实际以绘栾结算为准`;}
      const progress=s.el.querySelector('[data-cyimg-progress]');progress.hidden=!busy;
      if(busy){s.el.querySelector('[data-cyimg-bar]').style.width=`${Math.max(10,Math.min(95,Number(s.job?.progress||35)))}%`;s.el.querySelector('[data-cyimg-stage]').textContent=s.job?.progress_text||'绘栾任务进行中';s.el.querySelector('[data-cyimg-percent]').textContent=s.job?.progress ? `${s.job.progress}%` : '处理中';}
      const task=s.pending?null:s.job;
      progressView?.update(progress,{visible:busy,running:busy,taskId:node.jobId,percent:task?.progress??null,
        title:task?.progress_text||(s.pending?'正在提交素材':'绘栾任务进行中'),detail:item?.label||(kind(node)==='video'?'绘栾视频':'绘栾图像'),
        startedAt:task?.started_at||task?.created_at||s.progressStartedAt,finishedAt:task?.finished_at},s.el);
      s.el.querySelectorAll('.desk-cyimg__body :is(input,select)').forEach(input=>input.disabled=busy);
    }
    function renderCatalog(s) {
      if(!live(s))return;
      const list=choices(s.node);
      if(list.length && !list.some(item=>item.id===s.node.modelId)) s.node.modelId=list[0].id;
      s.el.querySelector('[data-cyimg-model]').innerHTML=modelOptions(s.node);
      s.el.querySelector('[data-cyimg-fields]').innerHTML=fields(s.node);
      window.DesktopSelect?.refreshAll?.();paint(s);
    }
    function loadCatalog() {
      if(catalogPromise)return catalogPromise;
      catalogPromise=api.catalog().then(value=>{catalog=value;catalogError='';sessions.forEach(renderCatalog);return value;})
        .catch(error=>{catalogError=error.message||'目录加载失败';sessions.forEach(paint);throw error;})
        .finally(()=>{catalogPromise=null;});
      return catalogPromise;
    }
    function feedback(s,message='',tone='info') {
      if(!live(s))return;
      const task=s.job||{},stage=message||task.progress_text||task.error||'绘栾任务';
      reportStatus({message:`绘栾${kind(s.node)==='video'?'视频':'图像'} · ${stage}`,tone,task:{
        ...task,task_id:s.node.jobId||'',node_id:s.id,node_title:`绘栾${kind(s.node)==='video'?'视频':'图像'} · ${s.id.slice(-6)}`,
        operation_label:'绘栾生成',provider_route:'cyimg',status:s.node.status,status_label:stage,
        detail_title:'绘栾任务状态',progress_text:stage,raw_detail:task.error||message||stage}});
    }
    async function publish(s,task,onlyTarget='') {
      if(!live(s)||!task?.result_files?.length||s.publishing)return;
      const paths=kind(s.node)==='video'?task.video_paths:task.image_paths;
      if(!paths?.length)return;
      s.publishing=true;
      try {
        const targetType=kind(s.node), edges=(getCanvas().edges||[]).filter(e=>e.from===s.id&&getNodeState(e.to)?.type===targetType);
        if(onlyTarget && !edges.some(e=>e.to===onlyTarget))return;
        if(!onlyTarget)for(let i=edges.length;i<paths.length;i++){
          const source=s.node, id=addNode(targetType,{x:source.x+source.width+260,y:source.y+110+i*215});
          connectNodes(s.id,id,{quiet:true,outputSlot:i});
          edges.push((getCanvas().edges||[]).find(e=>e.from===s.id&&e.to===id));
        }
        const targets=onlyTarget?edges.filter(e=>e.to===onlyTarget):edges;
        for(let index=0;index<targets.length;index++){
          const edge=targets[index], target=getNodeState(edge?.to);
          const slot=Number.isInteger(Number(edge?.outputSlot)) ? Number(edge.outputSlot) : edges.indexOf(edge);
          const path=paths[slot]||paths[0];
          if(!target||!path)continue;
          if(targetType==='image')await setImageFromResult(target.id,s.id,{imagePaths:paths,files:task.result_files,primaryFile:task.result_file,taskId:task.task_id,prompt:task.prompt,type:'cyimg'},slot);
          else {const ext=path.split(/[?#]/,1)[0].split('.').pop().toLowerCase();const mimeType={mov:'video/quicktime',webm:'video/webm'}[ext]||'video/mp4';Object.assign(target,{mediaUrl:path,mediaName:task.result_files[slot]||task.result_file||'绘栾视频',mimeType,status:'succeeded',sourceTaskId:task.task_id});refreshVideoNode(target.id);}
        }
        s.node.resultJobId=task.task_id;saveState();
      } finally {s.publishing=false;}
    }
    async function poll(s) {
      clearTimeout(s.timer);
      const id=s.node.jobId, epoch=s.epoch||0;
      if(!id||!live(s))return;
      try {
        const task=await api.job(id);
        if(!live(s)||s.node.jobId!==id||(s.epoch||0)!==epoch)return;
        s.job=task;s.node.status=task.status;
        if(task.result_files?.length && ['succeeded','succeeded_no_telegram','telegram_failed'].includes(task.status))await publish(s,task);
        paint(s);feedback(s,'',task.error?'error':task.status==='succeeded'?'success':'info');saveState();
        if(!terminal(task.status))s.timer=setTimeout(()=>poll(s),3000);
      } catch(error){
        if(!live(s)||s.node.jobId!==id||(s.epoch||0)!==epoch)return;
        s.notice=error.message;paint(s);feedback(s,error.message,'error');
        if(!terminal(s.node.status))s.timer=setTimeout(()=>poll(s),5000);
      }
    }
    async function uploadSources(s,item) {
      const result={image:[],video:[],audio:[]};
      const fields=item.fields.filter(field=>['image','video','audio'].includes(field.type));
      for(const field of fields){
        const type=field.type, blobs=[];
        if(type==='image')for(const ref of getImageReferences(s.id)){
          const source=ref.base64||ref.imageData||ref.imageUrl||ref.url;
          if(source)blobs.push({blob:await api.sourceBlob(source,'image'),name:ref.name||'reference.png'});
        }
        if(type==='video')for(const node of incoming(s,'video'))if(node.mediaUrl)blobs.push({blob:await api.sourceBlob(node.mediaUrl,'video'),name:node.mediaName||'reference.mp4'});
        if(type==='audio')for(const node of incoming(s,'audio')){
          const blob=await audioAssets.get(node.audioAssetId);
          if(blob)blobs.push({blob,name:node.mediaName||'reference.mp3'});
          else if(node.mediaUrl)blobs.push({blob:await api.sourceBlob(node.mediaUrl,'audio'),name:node.mediaName||'reference.mp3'});
        }
        if(blobs.length>field.resource_count)throw new Error(`${field.label}最多 ${field.resource_count} 个`);
        for(const entry of blobs)result[type].push(await api.upload(entry.blob,entry.name));
        if(field.required&&!result[type].length)throw new Error(`当前模型需要${field.label}`);
      }
      return result;
    }
    async function run(id) {
      const s=sessions.get(id);if(!s||s.pending||M.active(s.node.status))return;
      s.progressStartedAt=Date.now();
      try {
        if(!catalog)await loadCatalog();
        if(!catalog.api_key_configured)throw new Error('请先在设置中填写绘栾 API Key');
        const item=selected(s.node);if(!item)throw new Error('请先选择模型');
        const texts=getTextNodes(s.id).map(node=>materializeText(node)).filter(Boolean);
        const prompt=texts.map(v=>String(v||'').trim()).filter(Boolean).join('\n\n');
        if(!prompt)throw new Error('请连接含有提示词的文本节点');
        s.pending=true;s.node.status='submitting';s.notice='';paint(s);feedback(s,'上传素材并提交任务');
        const tokens=await uploadSources(s,item);
        if(!live(s))return;
        const parameters={};for(const field of item.fields)if(!['image','video','audio'].includes(field.type))parameters[field.name]=valueFor(s.node,field);
        const reply=await api.submit({kind:kind(s.node),model_id:item.id,prompt,parameters,
          image_upload_tokens:tokens.image,video_upload_tokens:tokens.video,audio_upload_tokens:tokens.audio,
          telegram_enabled:s.node.telegramEnabled});
        if(!live(s))return;
        s.node.jobId=reply.task_id;s.node.resultJobId='';s.node.status=reply.status||'queued';saveState();
      } catch(error){if(live(s)){s.node.status='failed';s.notice=error.message;feedback(s,error.message,'error');}}
      finally {if(live(s)){s.pending=false;paint(s);saveState();if(s.node.jobId && M.active(s.node.status))poll(s);}}
    }
    function mount(node) {
      const el=getNodeElement(node.id);if(!el||sessions.has(node.id))return;
      M.normalize(node);const s={id:node.id,node,el,abort:new AbortController()};sessions.set(node.id,s);
      el.addEventListener('click',event=>{if(event.target.closest('[data-cyimg-run]'))run(s.id);},{signal:s.abort.signal});
      el.addEventListener('change',event=>{
        const input=event.target;
        if(input.matches('[data-cyimg-model]')){node.modelId=input.value;renderCatalog(s);saveState();return;}
        if(input.matches('[data-cyimg-telegram]'))node.telegramEnabled=input.checked;
        else if(input.dataset.cyimgField){node.parameters[input.dataset.cyimgField]=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value;}
        else return;saveState();paint(s);
      },{signal:s.abort.signal});
      if(node.status==='submitting'&&!node.jobId)node.status='failed';
      renderCatalog(s);if(node.jobId)poll(s);
      if(!catalog)loadCatalog().catch(()=>{});
    }
    function dispose(id) {const s=sessions.get(id);if(!s)return;progressView?.releaseWithin(s.el);sessions.delete(id);s.abort.abort();clearTimeout(s.timer);}
    function disposeAll(){[...sessions.keys()].forEach(dispose);}
    function reconcile(){[...sessions.values()].forEach(s=>{if(!live(s))dispose(s.id);});Object.values(getCanvas().nodes).filter(n=>M.TYPES.includes(n.type)).forEach(mount);}
    function graphChanged(){sessions.forEach(paint);}
    function connected(from,to){const s=sessions.get(from);if(s?.job?.result_files?.length&&!s.publishing)publish(s,s.job,to).catch(error=>feedback(s,error.message,'error'));graphChanged();}
    window.addEventListener('desktop:cyimg-settings-updated',()=>{
      Promise.resolve(catalogPromise).catch(()=>{}).then(loadCatalog).catch(()=>{});
    });
    return Object.freeze({nodeHtml,reconcile,dispose,disposeAll,run,graphChanged,
      showStatus:id=>{const s=sessions.get(id);if(s&&(s.job||s.notice))feedback(s,s.notice||'');},
      connections:{targets:M.targets,policy:M.policy,changed:connected,removed:graphChanged}});
  }
  window.DesktopCanvasCyimg=Object.freeze({create});
})();

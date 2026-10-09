// Topaz form/controller. Live outputs remain owned by DesktopResults/Tasks.
(function () {
  function create({model:M,stateIcon,loadCatalog,getState,getNodeElement,getReferences,outputReference,save,setImageFromResult,ensureOutputs,submit,showError}) {
    const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const options=(items,current)=>items.map(item=>{const [value,label]=Array.isArray(item)?item:[item,item];return `<option value="${esc(value)}"${String(value)===String(current)?' selected':''}>${esc(label)}</option>`;}).join('');
    let catalog=null, catalogRequested=false;
    function modelOptions(current) {
      return M.MODELS.map(m=>{
        const remote=catalog?.find(x=>x.id===m.value), unavailable=remote?.available===false||!m.verified;
        return `<option value="${esc(m.value)}"${m.value===current?' selected':''}${unavailable?' disabled':''}>${esc(m.label)}${unavailable?' · 暂不可用':''}</option>`;
      }).join('');
    }
    function fields(node) {
      const p=node.topaz, meta=M.MODELS.find(m=>m.value===node.model)||M.MODELS[0], profile=meta.profile;
      const classic=profile==='classic', legacy=profile==='legacy', strength=profile==='strength';
      const faces=meta.protocol==='native' && (classic||strength);
      const gamma=classic||legacy||strength;
      const creative=profile==='redefine_creative', realistic=profile==='redefine_realistic';
      const select=(key,label,items,disabled=false)=>`<label><span>${label}</span><select class="desk-select" data-topaz-field="${key}" ${disabled?'disabled':''}>${options(items,p[key])}</select></label>`;
      const number=(key,label,disabled=false,step=1,min=M.ranges[key][0])=>`<label><span>${label}</span><input data-topaz-field="${key}" aria-label="${label}" type="number" required min="${min}" max="${M.ranges[key][1]}" step="${step}" value="${p[key]}" ${disabled?'disabled':''}></label>`;
      const toggle=(key,label)=>`<label class="desk-topaz__toggle"><input type="checkbox" data-topaz-field="${key}" ${p[key]?'checked':''}><span>${label}</span></label>`;
      return `<div class="desk-topaz__grid">
        <label><span>模型</span><select class="desk-select" data-topaz-model>${modelOptions(node.model)}</select></label>
        ${select('resize_mode','尺寸方式',[['scale','倍数'],['width','指定宽度'],['height','指定高度'],['longest','最长边']])}
        <label><span>倍数预设</span><select class="desk-select" data-topaz-preset ${p.resize_mode!=='scale'?'disabled':''}>${options([[1,'1× · 原尺寸增强'],[2,'2×'],[4,'4×'],[6,'6×'],['custom','自定义']], [1,2,4,6].includes(p.scale)?p.scale:'custom')}</select></label>
        ${number('scale','自定义倍数',p.resize_mode!=='scale',.01,M.minScale(node.model))}
        ${number('dimension','目标尺寸',p.resize_mode==='scale',.01)}
        ${select('unit','尺寸单位',[['px','像素 px'],['in','英寸 in'],['cm','厘米 cm']],p.resize_mode==='scale')}
        ${number('ppi','像素密度 PPI')}
        ${select('output_format','生成格式',[['png','PNG · 无损 / 透明'],['jpg','JPEG · 8 bit'],['tiff','TIFF · 无损 / 8 bit']])}
      </div>
      <div class="desk-topaz__section"><strong>模型调节</strong>${classic?toggle('auto','自动参数'):''}${gamma?toggle('gamma_correction','伽马校正'):''}</div>
      <div class="desk-topaz__grid">
        ${classic||legacy?number('sharpen','锐化',classic&&p.auto)+number('denoise','降噪',classic&&p.auto)+number('fix_compression','压缩修复',classic&&p.auto):''}
        ${strength?number('strength','增强强度'):''}
        ${['wonder','recover3','natural'].includes(profile)?select('enhancement_strength','增强档位',[[.7,'低 · Low'],[1,'中 · Medium'],[1.3,'高 · High']]):''}
        ${['recover1','recover2'].includes(profile)?number('detail','细节恢复'):''}
        ${realistic?select('realistic_detail','创意程度',[[0,'无 · None'],[1,'轻微 · Subtle']]):''}
        ${creative?select('creativity','创意程度',[[2,'低 · Low'],[3,'中 · Medium'],[4,'高 · High'],[5,'最大 · Max']])+number('texture','纹理'):''}
        ${creative||realistic||profile==='natural'?number('seed','随机种子'):''}
        ${number('jpeg_quality','JPEG 质量',p.output_format!=='jpg')}
      </div>
      ${creative?`<label class="desk-topaz__description"><span>图像描述（可选）</span><input data-topaz-field="description" aria-label="图像描述" maxlength="2000" value="${esc(p.description)}" placeholder="描述希望保留或增强的内容"></label>`:''}
      <div class="desk-topaz__section">${faces?toggle('face_enhancement','人脸恢复 V2'):''}${toggle('grain','添加颗粒')}</div>
      <div class="desk-topaz__grid ${faces?'desk-topaz__grid--five':''}">
        ${faces?number('face_strength','人脸强度',!p.face_enhancement)+select('face_creativity','人脸模式',[[0,'写实 · Realistic'],[1,'创意 · Creative']],!p.face_enhancement):''}
        ${number('grain_strength','颗粒强度',!p.grain)}${number('grain_intensity','颗粒浓度',!p.grain)}${number('grain_size','颗粒大小',!p.grain,.1)}
      </div>`;
    }
    function nodeHtml(node) {
      M.normalize(node);
      return `<section class="desk-node desk-node--topaz desk-glass" data-node-id="${esc(node.id)}" aria-label="Topaz Gigapixel 节点">
        <header class="desk-topaz__header" data-node-drag-handle><span class="desk-topaz__icon">${M.ICON}</span><div><strong>Topaz Gigapixel</strong><small>IMAGE ENHANCEMENT · LOCAL</small></div><span class="desk-status-pill" data-output-status>就绪</span><button class="desk-node-delete" data-node-delete aria-label="删除节点">删</button></header>
        <button class="desk-port desk-port--in" data-port="in" data-node-id="${esc(node.id)}" aria-label="连接图片输入"></button>
        <button class="desk-port desk-port--out" data-port="out" data-node-id="${esc(node.id)}" aria-label="连接增强结果"></button>
        <div class="desk-topaz__fields">${fields(node)}</div><small class="desk-topaz__availability" data-topaz-availability></small>
        <footer class="desk-topaz__footer"><div><span data-topaz-source>连接图片节点作为输入</span><small>保持原图比例 · 本地原生推理 · 自动归档</small><label class="desk-topaz__toggle"><input type="checkbox" data-topaz-telegram ${node.output.telegramEnabled?'checked':''}><span>发送到 Telegram</span></label></div>
          <button class="desk-generation-action" data-result-run aria-label="开始增强">${stateIcon.html(icons)}<span class="desk-generation-action__label">开始增强</span></button></footer>
        <div class="desk-progress-float desk-topaz__progress" aria-label="Topaz 放大进度" aria-hidden="true"><div class="desk-progress-float__panel"><div class="desk-progress-float__bar"><span data-progress-bar></span><strong class="desk-progress-float__percent" data-progress-percent><span data-progress-percent-value>0%</span><span class="desk-progress-float__timer" data-progress-timer>00:00</span></strong></div><span data-progress-stage class="desk-progress-float__stage">等待任务</span></div></div>
      </section>`;
    }
    function references(id) {
      const refs=getReferences(id); if(refs.length)return refs;
      const state=getState(), edge=state.canvas.edges.find(e=>e.to===id);
      const source=edge && state.outputs?.[edge.from];
      const ref=source && outputReference(source,0,edge.from);
      return ref?[ref]:[];
    }
    function readConfig(id, explicitRef) {
      const node=getState().canvas.nodes[id], el=getNodeElement(id);
      if(!node||node.type!==M.TYPE)throw new Error('Topaz 节点不存在');
      for(const input of el?.querySelectorAll('input[type=number]:not(:disabled)')||[]) {
        if(!input.checkValidity()) {input.reportValidity();throw new Error('请检查 Topaz 参数范围');}
      }
      if(node.topaz.resize_mode==='scale' && node.topaz.scale<M.minScale(node.model))
        throw new Error('所选 Wonder 模型的生成倍数不能低于 1×');
      const availability=catalog?.find(m=>m.id===node.model);
      if(availability?.available===false)throw new Error(availability.error||'所选 Topaz 模型不可用');
      const ref=explicitRef||references(id)[0];
      if(!ref)throw new Error('请先连接一张图片到 Topaz 节点');
      return {nodeId:id,provider:'topaz',prompt:`Topaz：${ref.title||ref.name||node.model}`,batchMode:false,expectedImageOutputCount:1,
        params:{model:node.model,topaz:{...node.topaz},archiveEnabled:true,telegramEnabled:node.output.telegramEnabled},referenceImages:[ref]};
    }
    const icons={idle:'<path d="M13 3 5 14h6l-1 7 8-11h-6l1-7Z"/>',busy:'<path fill="none" stroke="currentColor" stroke-width="2" d="M20 12a8 8 0 1 1-8-8"/>',success:'<path fill="none" stroke="currentColor" stroke-width="2.5" d="m5 12 4 4L20 5"/>',error:'<path fill="none" stroke="currentColor" stroke-width="2" d="m6 6 12 12M6 18 18 6"/>'};
    function paint(id) {
      const state=getState(), node=state.canvas.nodes[id], el=getNodeElement(id);if(node?.type!==M.TYPE||!el)return;
      const output=state.outputs?.[id]||{}, status=output.status, busy=DesktopState.isInFlight(status);
      const icon=busy?'busy':DesktopState.isSuccess(status)?'success':DesktopState.isFailure(status)?'error':'idle';
      const button=el.querySelector('[data-result-run]');
      if(button.dataset.topazIcon!==icon){stateIcon.paint(button.querySelector('svg'),icon);button.dataset.topazIcon=icon;}
      const availability=catalog?.find(m=>m.id===node.model);
      const unavailable=availability?.available===false||M.MODELS.find(m=>m.value===node.model)?.verified===false;
      const hint=el.querySelector('[data-topaz-availability]');
      if(hint)hint.textContent=unavailable?(availability?.error||'该模型暂未通过本机验证'):'';
      button.disabled=busy||unavailable;button.setAttribute('aria-busy',String(busy));
      const label=busy?(status==='queued'?'排队中':'处理中'):icon==='success'?'已完成':icon==='error'?'重试增强':status==='canceled'?'已停止':'开始增强';
      button.querySelector('span').textContent=label;button.setAttribute('aria-label',label);
      el.querySelector('[data-topaz-source]').textContent=references(id)[0]?.title||'连接图片节点作为输入';
      // Only dynamic disabling; values and in-progress edits remain intact.
      el.querySelectorAll('.desk-topaz__fields input,.desk-topaz__fields select,[data-topaz-telegram]').forEach(input=>{
        if(busy){if(!input.disabled)input.dataset.topazBusy='1'; input.disabled=true;}
        else if(input.dataset.topazBusy){input.disabled=false;delete input.dataset.topazBusy;}
      });
    }
    function reconcile() {
      if(loadCatalog && !catalogRequested && Object.values(getState().canvas.nodes).some(n=>n.type===M.TYPE)) {
        catalogRequested=true;
        loadCatalog().then(data=>{
          catalog=Array.isArray(data.models)?data.models:[];
          for(const n of Object.values(getState().canvas.nodes)) {
            if(n.type!==M.TYPE)continue;
            const select=getNodeElement(n.id)?.querySelector('[data-topaz-model]');
            if(select)select.innerHTML=modelOptions(n.model);
            paint(n.id);
          }
        }).catch(()=>{ /* Submission still uses the backend installation/version gate. */ });
      }
      for(const node of Object.values(getState().canvas.nodes)) {
        if(node.type!==M.TYPE)continue;
        const el=getNodeElement(node.id);if(!el)continue;
        if(!el.dataset.topazBound) {
          el.dataset.topazBound='1';
          const handleChange=event=>{
            const target=event.target, live=getState().canvas.nodes[node.id];if(live!==node)return;
            const key=target.dataset.topazField;
            if(key){
              if(target.type==='number'&&!target.checkValidity()){
                if(event.type==='change' && key==='scale' && target.value!=='' && Number(target.value)<M.minScale(node.model))
                  target.value=String(M.minScale(node.model));
                else return;
              }
              node.topaz[key]=target.type==='checkbox'?target.checked:(target.type==='number'||['face_creativity','creativity','realistic_detail','enhancement_strength'].includes(key))?Number(target.value):target.value;
            }
            else if(target.hasAttribute('data-topaz-model')){node.model=target.value;M.normalize(node);}
            else if(target.hasAttribute('data-topaz-preset')) {if(target.value==='custom'){el.querySelector('[data-topaz-field="scale"]').focus();return;} node.topaz.scale=Number(target.value);}
            else if(target.hasAttribute('data-topaz-telegram'))node.output.telegramEnabled=target.checked;
            else return;
            // Restore form only when its structure/dependencies change; never on progress polls.
            if(target.tagName==='SELECT'||target.type==='checkbox')el.querySelector('.desk-topaz__fields').innerHTML=fields(node);
            if(key==='scale')el.querySelector('[data-topaz-preset]').value=[1,2,4,6].includes(node.topaz.scale)?String(node.topaz.scale):'custom';
            save();paint(node.id);
          };
          el.addEventListener('change',handleChange);
          el.addEventListener('input',event=>{if(event.target.type==='number'||event.target.dataset.topazField==='description')handleChange(event);});
        }
        paint(node.id);
      }
    }
    function changed(from,to) {
      reconcile();const state=getState();
      if(state.canvas.nodes[from]?.type===M.TYPE && state.canvas.nodes[to]?.type==='image' && state.outputs[from]?.imagePaths?.length)
        setImageFromResult(to,from,state.outputs[from],0).catch(()=>{});
    }
    async function runChains(id, output) {
      const state=getState(), graph=state.canvas; if(!['input','comfy'].includes(state.canvas.nodes[id]?.type))return 0;
      const ref=outputReference(output,0,id), key=output.taskId||output.primaryImagePath;if(!ref||!key)return 0;
      let count=0;
      for(const edge of state.canvas.edges.filter(e=>e.from===id&&state.canvas.nodes[e.to]?.type===M.TYPE)) {
        if(getState().canvas!==graph)break;
        const node=graph.nodes[edge.to];
        if(!node||node.type!==M.TYPE||!graph.edges.includes(edge))continue;
        if(state.outputs[id]?.taskId && state.outputs[id].taskId!==key)break;
        if(node.topazSourceKey===key||DesktopState.isInFlight(state.outputs[edge.to]?.status))continue;
        node.topazSourceKey=key;count++;
        try{const config=readConfig(node.id,ref);ensureOutputs(node.id,config);await submit(config,node.id);}
        catch(error){if(getState().canvas.nodes[node.id]===node){node.topazSourceKey='';showError(error,node.id);}}
      }
      return count;
    }
    return Object.freeze({nodeHtml,reconcile,readConfig,paint,runChains,
      connections:{targets:M.targets,policy:M.policy,changed,removed:()=>reconcile()}});
  }
  window.DesktopCanvasTopaz=Object.freeze({create});
})();

// Settings-center controller for offline Qwen 2.1 checkpoint conversion.
(function () {
  function create({api,escapeHtml,rerender,notify}={}){
    const esc=escapeHtml||((value)=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])));
    const state={loaded:false,loading:false,busy:false,data:null,inspection:null,
      draft:{sourcePath:'',modelName:'',precision:'8bit',vaeSource:'',vaeId:''},vaeDirty:false,timer:0,active:false,lastStatus:''};
    const terminal=value=>['succeeded','failed','canceled','idle'].includes(String(value||'idle'));
    const bytes=value=>{const size=Number(value)||0;if(size>=1024**3)return`${(size/1024**3).toFixed(1)} GiB`;if(size>=1024**2)return`${(size/1024**2).toFixed(0)} MiB`;return`${size} B`;};
    const tell=(message,tone='info')=>notify?.(message,tone);
    function schedule(){clearTimeout(state.timer);const status=state.data?.conversion?.status;if(!terminal(status)||state.data?.preparation?.status==='running')state.timer=setTimeout(()=>refresh(true).catch(()=>{}),state.active?1500:3000);}
    async function refresh(quiet=false){
      if(state.loading)return;state.loading=true;if(!quiet)rerender?.();
      try{
        const previous=state.data?.conversion?.status||state.lastStatus;
        const hadState=state.loaded;
        state.data=await api.modelTools();state.loaded=true;
        if(!state.vaeDirty)state.draft.vaeId=state.data?.vae?.selected_id||'';
        const imports=Array.isArray(state.data?.import_models)?state.data.import_models:[];
        if(!state.draft.sourcePath&&imports.length===1)state.draft.sourcePath=String(imports[0]?.source_name||'');
        const current=state.data?.conversion?.status||'idle';
        if(hadState&&current==='succeeded'&&previous!==current){
          window.dispatchEvent(new CustomEvent('qwen21-models-changed'));
          tell('Qwen 2.1 Base 权重转换完成，节点模型列表已刷新。','success');
        }else if(hadState&&current==='failed'&&previous!==current)tell(state.data.conversion.error||'Qwen 2.1 模型转换失败','error');
        state.lastStatus=current;
      }finally{state.loading=false;rerender?.();schedule();}
    }
    function card(title,body,ok=true){return`<section class="desk-settings-card ${ok?'is-ok':'is-warn'} desk-qwen21-tools__card"><header><span class="desk-settings-dot" aria-hidden="true"></span><h3>${esc(title)}</h3></header><div class="desk-settings-card__body">${body}</div></section>`;}
    function inspectionHtml(){const item=state.inspection;if(!item)return'';
      return`<div class="desk-qwen21-tools__inspection ${item.compatible_candidate?'is-ok':'is-warn'}">
        <strong>${esc(item.message)}</strong><span>${esc(item.source_name)} · ${bytes(item.file_size)} · ${Number(item.tensor_count)||0} tensors</span>
        <span>数据类型：${esc((item.dtypes||[]).join(' / ')||'未知')}${item.source_format?` · 源格式：${esc(item.source_format)}`:''}</span>${item.estimated_outputs?.[state.draft.precision]?`<span>预计 Transformer：${bytes(item.estimated_outputs[state.draft.precision])} · 共享组件不变</span>`:''}</div>`;}
    function progressHtml(){const job=state.data?.conversion||{status:'idle'},active=!terminal(job.status),progress=Math.max(0,Math.min(100,Number(job.progress)||0));
      if(job.status==='idle'&&!job.message)return'';
      const labels={queued:'排队中',waiting:'等待资源',running:'转换中',succeeded:'已完成',failed:'失败',canceled:'已取消'};
      return`<div class="desk-qwen21-tools__progress ${job.status==='failed'?'is-error':job.status==='succeeded'?'is-success':''}">
        <div><strong>${esc(labels[job.status]||job.status)}</strong><span>${esc(job.message||'')}</span><em>${Math.round(progress)}%</em></div>
        <div class="desk-qwen21-tools__bar"><span style="width:${progress}%"></span></div>
        ${active?'<button type="button" class="is-danger" data-qwen21-convert-cancel>取消转换</button>':''}
        ${job.error?`<small>${esc(job.error)}</small>`:''}</div>`;}
    function formHtml(){const running=!terminal(state.data?.conversion?.status)||state.data?.preparation?.status==='running',invalid=Boolean(state.inspection&&!state.inspection.compatible_candidate),imports=Array.isArray(state.data?.import_models)?state.data.import_models:[],current=state.draft.sourcePath;
      const known=imports.some(item=>String(item?.source_name||'')===current),options=imports.map(item=>{const name=String(item?.source_name||'');return`<option value="${esc(name)}"${name===current?' selected':''}>${esc(name)} · ${bytes(item?.file_size)}</option>`;}).join('');
      return`<div class="desk-qwen21-tools__form">
      <label class="desk-qwen21-tools__wide"><span>源模型文件</span><select class="desk-select" data-qwen21-tool-field="sourcePath" ${running?'disabled':''}><option value="">${imports.length?'选择导入目录内的 .safetensors…':'导入目录内暂无 .safetensors 文件'}</option>${current&&!known?`<option value="${esc(current)}" selected>${esc(current)}</option>`:''}${options}</select></label>
      <label><span>转换后显示名称</span><input class="desk-input" type="text" maxlength="120" data-qwen21-tool-field="modelName" value="${esc(state.draft.modelName)}" placeholder="检查后自动读取，也可手动修改" ${running?'disabled':''}></label>
      <label><span>输出精度</span><select class="desk-select" data-qwen21-tool-field="precision" ${running?'disabled':''}><option value="8bit"${state.draft.precision==='8bit'?' selected':''}>MLX 8-bit · group_size 64</option><option value="bf16"${state.draft.precision==='bf16'?' selected':''}>MLX BF16 · 不量化</option></select></label>
      ${inspectionHtml()}
      <div class="desk-settings-form__actions desk-qwen21-tools__actions"><button type="button" data-qwen21-model-inspect ${running||state.busy?'disabled':''}>检查兼容性</button><button type="button" class="is-primary" data-qwen21-model-convert ${running||state.busy||invalid?'disabled':''}>开始转换</button></div>
    </div>${progressHtml()}`;}
    function modelsHtml(){const models=state.data?.models||[];if(!models.length)return'<div class="desk-settings-empty">暂无可用 Base 权重模型。</div>';
      return`<div class="desk-qwen21-tools__models">${models.map(model=>`<article class="desk-qwen21-tools__model ${model.ready?'is-ready':'is-missing'}">
        <div><strong>${esc(model.name||model.id)}</strong><span>${esc(model.quantization||model.precision)} · ${bytes(model.file_size)}${model.requantized?' · FP8 源重新量化':model.precision==='bf16'&&String(model.source_format||'').startsWith('comfy-scaled-fp8')?' · FP8 源解码':''}${model.ready?' · 可用':' · 未准备'}</span></div>
        ${model.builtin?'<em>内置</em>':`<button type="button" class="is-danger" data-qwen21-model-delete="${esc(model.id)}">删除</button>`}
      </article>`).join('')}</div>`;}
    function render(){
      if(!state.loaded)return card('Qwen 2.1 模型转换',`<div class="desk-settings-empty">${state.loading?'正在读取模型工具状态…':'打开页面后读取本地模型目录。'}</div>`,false);
      const paths=`<div class="desk-qwen21-tools__paths"><div><span>Base 权重目录</span><strong title="${esc(state.data?.base_model_directory||'')}">${esc(state.data?.base_model_directory||'')}</strong></div><div><span>模型导入目录</span><strong title="${esc(state.data?.import_directory||'')}">${esc(state.data?.import_directory||'')}</strong></div></div>`;
      return card('Qwen 2.1 模型转换',paths+prepareHtml()+formHtml(),state.data?.conversion?.status!=='failed')+vaeHtml()+card('Base 权重模型库',modelsHtml(),(state.data?.models||[]).some(item=>item.ready));
    }
    function vaeHtml(){
      const data=state.data?.vae;if(!data)return'';
      const selected=(data.models||[]).find(item=>item.id===data.selected_id);
      const options=(data.models||[]).map(item=>`<option value="${esc(item.id)}"${item.id===state.draft.vaeId?' selected':''}>${esc(item.name)} · ${item.format==='diffusers'?'自动布局适配':'MLX 原生'}</option>`).join('');
      const sources=(data.imports||[]).map(item=>`<option value="${esc(item.source_name)}"${item.source_name===state.draft.vaeSource?' selected':''}>${esc(item.source_name)} · ${bytes(item.file_size)}</option>`).join('');
      return card('Qwen 2.1 · VAE',`<div class="desk-qwen21-tools__paths"><div><span>VAE 导入目录</span><strong>${esc(data.import_directory||'')}</strong></div></div>
        <div class="desk-qwen21-tools__form">
          <label class="desk-qwen21-tools__wide"><span>生成使用的 VAE</span><select class="desk-select" data-qwen21-tool-field="vaeId" ${state.busy?'disabled':''}><option value="" disabled${!state.draft.vaeId?' selected':''}>请选择可用 VAE</option>${options}</select></label>
          <p class="desk-settings-form__hint desk-qwen21-tools__wide">当前：${esc(selected?.name||'所选 VAE 不可用')}。</p>
          <div class="desk-settings-form__actions desk-qwen21-tools__actions"><button type="button" data-qwen21-vae-select ${state.busy||!state.draft.vaeId?'disabled':''}>应用 VAE</button></div>
          <label class="desk-qwen21-tools__wide"><span>导入新的 VAE</span><select class="desk-select" data-qwen21-tool-field="vaeSource" ${state.busy?'disabled':''}><option value="">选择导入目录内的 .safetensors…</option>${sources}</select></label>
          <div class="desk-settings-form__actions desk-qwen21-tools__actions"><button type="button" data-qwen21-vae-refresh ${state.busy?'disabled':''}>刷新目录</button><button type="button" data-qwen21-vae-import ${state.busy?'disabled':''}>导入 VAE</button></div>
          ${(data.errors||[]).map(error=>`<p class="desk-settings-form__hint desk-qwen21-tools__wide">${esc(error)}</p>`).join('')}
        </div>`,!(data.errors||[]).length);
    }
    async function importVae(){if(!state.draft.vaeSource)throw new Error('请先选择 VAE 源文件');state.busy=true;rerender?.();try{const reply=await api.importVae(state.draft.vaeSource);state.draft.vaeId=reply.vae.id;state.vaeDirty=true;await refresh(true);tell('VAE 已独立导入；点击“应用 VAE”后用于后续生成。','success');}finally{state.busy=false;rerender?.();}}
    async function selectVae(){state.busy=true;rerender?.();try{await api.selectVae(state.draft.vaeId);state.vaeDirty=false;await refresh(true);tell('VAE 已应用，将在下一次生成时加载。','success');}finally{state.busy=false;rerender?.();}}
    function prepareHtml(){
      const prep=state.data?.preparation||{},ready=state.data?.runtime?.environment_ready&&state.data?.runtime?.source_ready&&(state.data?.models||[]).some(item=>item.ready);
      if(ready&&prep.status!=='running')return'';
      return `<div class="desk-qwen21-tools__inspection"><strong>${esc(prep.status==='running'?prep.message:'首次使用需要准备 Qwen 固定源码与共享模型')}</strong><button type="button" data-qwen21-tools-prepare ${prep.status==='running'?'disabled':''}>${prep.status==='running'?'准备中…':'准备共享模型'}</button></div>`;
    }
    async function prepare(){await api.prepare(state.data?.default_model_id,'standard');await refresh(true);schedule();}
    async function inspect(){if(!state.draft.sourcePath.trim())throw new Error('请填写本地 .safetensors 模型路径');state.busy=true;rerender?.();try{const reply=await api.inspectModel(state.draft.sourcePath.trim());state.inspection=reply.inspection;if(!state.draft.modelName.trim())state.draft.modelName=reply.inspection?.suggested_name||'';tell(reply.inspection?.message||'模型文件头检查完成',reply.inspection?.compatible_candidate?'success':'warning');}finally{state.busy=false;rerender?.();}}
    async function convert(){if(!state.draft.sourcePath.trim())throw new Error('请填写本地 .safetensors 模型路径');state.busy=true;rerender?.();try{const reply=await api.convertModel({source_path:state.draft.sourcePath.trim(),model_name:state.draft.modelName.trim(),precision:state.draft.precision});state.data={...(state.data||{}),conversion:reply.conversion};state.lastStatus=reply.conversion?.status||'';tell('模型转换已进入本地推理队列。','success');schedule();}finally{state.busy=false;rerender?.();}}
    async function cancel(){state.busy=true;rerender?.();try{const reply=await api.cancelModelConversion();state.data={...(state.data||{}),conversion:reply.conversion};tell('正在停止模型转换。','info');schedule();}finally{state.busy=false;rerender?.();}}
    async function remove(modelId){if(window.confirm&&!window.confirm('确定删除这个已转换的 Base 权重模型？'))return;state.busy=true;rerender?.();try{await api.deleteModel(modelId);window.dispatchEvent(new CustomEvent('qwen21-models-changed'));tell('Base 权重模型已删除。','success');await refresh(true);}finally{state.busy=false;rerender?.();}}
    function run(action){Promise.resolve().then(action).catch(error=>tell(error?.message||'Qwen 2.1 模型工具操作失败','error'));}
    function handleClick(event){let target=event.target.closest('[data-qwen21-model-inspect],[data-qwen21-model-convert],[data-qwen21-convert-cancel],[data-qwen21-model-delete],[data-qwen21-tools-prepare],[data-qwen21-vae-select],[data-qwen21-vae-import],[data-qwen21-vae-refresh]');if(!target)return false;event.preventDefault();
      if(state.busy)return true;
      if(target.matches('[data-qwen21-vae-select]'))run(selectVae);else if(target.matches('[data-qwen21-vae-import]'))run(importVae);else if(target.matches('[data-qwen21-vae-refresh]'))run(()=>refresh(true));else if(target.matches('[data-qwen21-tools-prepare]'))run(prepare);else if(target.matches('[data-qwen21-model-inspect]'))run(inspect);else if(target.matches('[data-qwen21-model-convert]'))run(convert);else if(target.matches('[data-qwen21-convert-cancel]'))run(cancel);else run(()=>remove(target.dataset.qwen21ModelDelete));return true;}
    function handleInput(event){const input=event.target.closest('[data-qwen21-tool-field]');if(!input)return false;const key=input.dataset.qwen21ToolField;state.draft[key]=input.value;if(key==='sourcePath')state.inspection=null;if(key==='precision')rerender?.();if(key==='vaeId')state.vaeDirty=true;return true;}
    async function activate(){state.active=true;await refresh(true);}
    function deactivate(){state.active=false;schedule();}
    return Object.freeze({render,activate,deactivate,refresh,handleClick,handleInput,state});
  }
  window.DesktopQwen21Tools=Object.freeze({create});
})();

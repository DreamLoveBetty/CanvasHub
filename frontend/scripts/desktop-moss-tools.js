// Settings-center controller for MOSS environment preparation, official weight binding and community Base conversion.
(function () {
  function create({api,escapeHtml,rerender,notify}={}){
    const esc=escapeHtml;
    const state={loaded:false,loading:false,busy:false,data:null,tools:null,inspection:null,draft:{sourceName:'',modelName:''},sourcePath:'',timer:0,active:false,lastOperation:'',lastConversion:''};
    const tell=(message,tone='info')=>notify?.(message,tone);
    const running=()=>state.data?.preparation?.status==='running';
    const converting=()=>['queued','waiting','running'].includes(state.tools?.conversion?.status);
    const bytes=value=>{const size=Number(value)||0;return size>=1024**3?`${(size/1024**3).toFixed(1)} GiB`:`${(size/1024**2).toFixed(0)} MiB`;};
    function schedule(){clearTimeout(state.timer);if(running()||converting())state.timer=setTimeout(()=>refresh().catch(()=>{}),state.active?1500:3000);}
    function settle(){
      const operation=state.data?.preparation||{},key=`${operation.operation_id}:${operation.status}`;
      if(state.lastOperation&&key!==state.lastOperation&&operation.status==='succeeded'){window.dispatchEvent(new CustomEvent('moss-models-changed'));tell('MOSS 操作已完成。','success');}
      else if(state.lastOperation&&key!==state.lastOperation&&operation.status==='failed')tell(operation.error||operation.message||'MOSS 操作失败','error');
      state.lastOperation=key;
    }
    async function refresh(){
      if(state.loading)return;state.loading=true;
      try{[state.data,state.tools]=await Promise.all([api.status(),api.modelTools()]);state.loaded=true;settle();settleConversion();}finally{state.loading=false;rerender?.();schedule();}
    }
    function settleConversion(){
      const job=state.tools?.conversion||{},key=`${job.job_id}:${job.status}`;
      if(state.lastConversion&&key!==state.lastConversion&&job.status==='succeeded'){state.draft={sourceName:'',modelName:''};state.inspection=null;window.dispatchEvent(new CustomEvent('moss-models-changed'));tell('MOSS Base 转换完成，节点模型列表已刷新。','success');}
      else if(state.lastConversion&&key!==state.lastConversion&&job.status==='failed')tell(job.error||'MOSS 模型转换失败','error');
      state.lastConversion=key;
    }
    const card=(title,body,ok)=>`<section class="desk-settings-card ${ok?'is-ok':'is-warn'} desk-moss-tools"><header><span class="desk-settings-dot" aria-hidden="true"></span><h3>${esc(title)}</h3></header><div class="desk-settings-card__body">${body}</div></section>`;
    const row=(label,value)=>`<div class="desk-moss-tools__row"><span>${esc(label)}</span><strong title="${esc(value)}">${esc(value)}</strong></div>`;
    function render(){
      if(!state.loaded)return card('MOSS 环境',`<div class="desk-settings-empty">${state.loading?'正在读取 MOSS 状态…':'打开页面后读取 MOSS 状态。'}</div>`,false);
      const data=state.data,model=data.model||{},operation=data.preparation||{},versions=data.versions||{},isRunning=running(),locked=isRunning||state.busy;
      return card('MOSS 环境',`<div class="desk-moss-tools__rows">${row('隔离环境',versions.mlx?`已准备 · mlx ${versions.mlx}`:'未准备')}${row('模型权重',model.ready?`已绑定 · ${String(model.fingerprint||'').slice(0,12)}`:(model.reason||'未绑定'))}${isRunning||operation.message?row('当前操作',operation.message||''):''}</div>
        ${(data.reasons||[]).map(reason=>`<p class="desk-settings-form__hint">${esc(reason)}</p>`).join('')}
        <div class="desk-moss-tools__form"><label><span>权重目录（绝对路径，只读绑定）</span><input class="desk-input" type="text" data-moss-tool-source value="${esc(state.sourcePath)}" placeholder="/path/to/moss-image-sft-mflux-bf16" ${locked?'disabled':''}></label>
        <div class="desk-settings-form__actions"><button type="button" data-moss-tool-prepare ${locked?'disabled':''}>准备环境</button><button type="button" class="is-primary" data-moss-tool-bind ${locked||!state.sourcePath.trim()?'disabled':''}>绑定权重</button></div>
        <p class="desk-settings-form__hint">准备环境会创建独立 venv 并下载配置文件；绑定权重会完整校验约 27 GB 文件，不修改源文件。两者都不会自动运行。</p></div>`,Boolean(data.ready));
    }
    function progressHtml(){
      const job=state.tools?.conversion||{status:'idle'},progress=Math.max(0,Math.min(100,Number(job.progress)||0));if(job.status==='idle'&&!job.message)return'';
      const labels={queued:'排队中',waiting:'等待资源',running:'转换中',succeeded:'已完成',failed:'失败',canceled:'已取消'};
      return`<div class="desk-qwen21-tools__progress ${job.status==='failed'?'is-error':job.status==='succeeded'?'is-success':''}"><div><strong>${esc(labels[job.status]||job.status)}</strong><span>${esc(job.message||'')}</span><em>${Math.round(progress)}%</em></div><div class="desk-qwen21-tools__bar"><span style="width:${progress}%"></span></div>${converting()?'<button type="button" class="is-danger" data-moss-convert-cancel>取消转换</button>':''}${job.error?`<small>${esc(job.error)}</small>`:''}</div>`;
    }
    function inspectionHtml(){const item=state.inspection;if(!item)return'';const formats={'comfy-int8-convrot':'ComfyUI INT8 ConvRot','bf16':'BF16','mlx-bf16':'已转换的 MLX BF16 目录'};
      return`<div class="desk-qwen21-tools__inspection ${item.compatible_candidate?'is-ok':'is-warn'}"><strong>${esc(item.message)}</strong>${item.source_format?`<span>${esc(item.source_name)} · ${esc(formats[item.source_format]||item.source_format)} · ${Number(item.tensor_count)||0} tensors</span>`:''}</div>`;}
    function modelsHtml(){return`<div class="desk-qwen21-tools__models">${(state.tools?.models||[]).map((model,index)=>`<article class="desk-qwen21-tools__model ${model.ready?'is-ready':'is-missing'}"><div><strong>${esc(model.label||model.model_id)}</strong><span>${!model.ready?esc(model.reason||'未绑定'):index?'BF16 · 复用官方文本编码器与 VAE':'BF16 · 完整权重'}</span></div>${index?`<button type="button" class="is-danger" data-moss-model-delete="${esc(model.model_id)}">删除</button>`:'<em>官方</em>'}</article>`).join('')}</div>`;}
    function renderBases(){
      const tools=state.tools||{},imports=tools.import_models||[],locked=converting()||state.busy,selected=state.draft.sourceName,invalid=state.inspection&&!state.inspection.compatible_candidate;
      const options=imports.map(item=>`<option value="${esc(item.source_name)}"${item.source_name===selected?' selected':''}>${esc(item.source_name)} · ${bytes(item.file_size)}</option>`).join('');
      return card('MOSS 模型转换',`<div class="desk-qwen21-tools__paths"><div><span>Base 权重目录</span><strong title="${esc(tools.base_model_directory||'')}">${esc(tools.base_model_directory||'')}</strong></div><div><span>模型导入目录</span><strong title="${esc(tools.import_directory||'')}">${esc(tools.import_directory||'')}</strong></div></div>
        <div class="desk-qwen21-tools__form"><label class="desk-qwen21-tools__wide"><span>源模型</span><select class="desk-select" data-moss-base-field="sourceName" ${locked?'disabled':''}><option value="">${imports.length?'选择导入目录内的模型…':'导入目录内暂无模型'}</option>${options}</select></label>
        <label class="desk-qwen21-tools__wide"><span>转换后显示名称</span><input class="desk-input" type="text" maxlength="120" data-moss-base-field="modelName" value="${esc(state.draft.modelName)}" placeholder="检查后自动读取，也可手动修改" ${locked?'disabled':''}></label>
        ${inspectionHtml()}<div class="desk-settings-form__actions desk-qwen21-tools__actions"><button type="button" data-moss-model-refresh ${locked?'disabled':''}>刷新目录</button><button type="button" data-moss-model-inspect ${locked||!selected?'disabled':''}>检查兼容性</button><button type="button" class="is-primary" data-moss-model-convert ${locked||!selected||invalid?'disabled':''}>开始转换</button></div></div>
        ${progressHtml()}${modelsHtml()}<p class="desk-settings-form__hint">支持 ComfyUI INT8 ConvRot、BF16 单文件，以及已转换的 MLX 目录。只转换 Transformer，文本编码器、VAE 与 Turbo 适配器复用官方权重；源文件不会被修改。</p>`,(tools.conversion?.status)!=='failed');
    }
    async function inspectBase(){state.busy=true;rerender?.();try{const reply=await api.inspectModel(state.draft.sourceName);state.inspection=reply.inspection;if(!state.draft.modelName.trim())state.draft.modelName=reply.inspection?.suggested_name||'';tell(reply.inspection?.message||'检查完成',reply.inspection?.compatible_candidate?'success':'error');}finally{state.busy=false;rerender?.();}}
    async function convertBase(){state.busy=true;rerender?.();try{const reply=await api.convertModel({source_path:state.draft.sourceName,model_name:state.draft.modelName.trim()});state.tools={...(state.tools||{}),conversion:reply.conversion};state.lastConversion=`${reply.conversion?.job_id}:${reply.conversion?.status}`;schedule();}finally{state.busy=false;rerender?.();}}
    async function cancelBase(){state.busy=true;rerender?.();try{const reply=await api.cancelModelConversion();state.tools={...(state.tools||{}),conversion:reply.conversion};schedule();}finally{state.busy=false;rerender?.();}}
    async function removeBase(modelId){if(window.confirm&&!window.confirm('确定删除这个已转换的 Base 权重模型？'))return;state.busy=true;rerender?.();try{await api.deleteModel(modelId);window.dispatchEvent(new CustomEvent('moss-models-changed'));tell('Base 权重模型已删除。','success');}finally{state.busy=false;await refresh();}}
    async function start(action){state.busy=true;rerender?.();try{const reply=await action();state.data={...(state.data||{}),preparation:reply.preparation};state.lastOperation=`${reply.preparation?.operation_id}:running`;schedule();}finally{state.busy=false;rerender?.();}}
    function run(action){Promise.resolve().then(action).catch(error=>tell(error?.message||'MOSS 操作失败','error'));}
    function handleClick(event){const base=event.target.closest('[data-moss-model-refresh],[data-moss-model-inspect],[data-moss-model-convert],[data-moss-convert-cancel],[data-moss-model-delete]');if(base){event.preventDefault();if(state.busy)return true;run(base.matches('[data-moss-model-refresh]')?refresh:base.matches('[data-moss-model-inspect]')?inspectBase:base.matches('[data-moss-model-convert]')?convertBase:base.matches('[data-moss-convert-cancel]')?cancelBase:()=>removeBase(base.dataset.mossModelDelete));return true;}const target=event.target.closest('[data-moss-tool-prepare],[data-moss-tool-bind]');if(!target)return false;event.preventDefault();if(state.busy)return true;const path=state.sourcePath.trim();run(()=>start(()=>target.matches('[data-moss-tool-bind]')?api.bindModel(path):api.prepare(path)));return true;}
    function handleInput(event){const field=event.target.closest('[data-moss-base-field]');if(field){const key=field.dataset.mossBaseField;state.draft[key]=field.value;if(key==='sourceName'){state.inspection=null;rerender?.();}return true;}const input=event.target.closest('[data-moss-tool-source]');if(!input)return false;state.sourcePath=input.value;const bind=input.closest('.desk-moss-tools')?.querySelector('[data-moss-tool-bind]');if(bind)bind.disabled=running()||state.busy||!state.sourcePath.trim();return true;}
    async function activate(){state.active=true;await refresh();}
    function deactivate(){state.active=false;schedule();}
    return Object.freeze({render:()=>render()+(state.loaded?renderBases():''),activate,deactivate,refresh,handleClick,handleInput,state});
  }
  window.DesktopMossTools=Object.freeze({create});
})();

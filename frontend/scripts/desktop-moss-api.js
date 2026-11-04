// MOSS authenticated transport and the camelCase/snake_case boundary; canvas state never leaves as-is.
(function () {
  const get=path=>api.json('/api/moss/'+path);
  const post=(path,body)=>api.json('/api/moss/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
  const wireTrace=item=>({source_node_id:item.sourceNodeId,target_id:item.targetId,field:item.field,content_hash:item.contentHash,...(item.sourceAlias?{source_alias:item.sourceAlias}:{})});
  function compileRequest(node,input){
    return{mode:node.mode,base_model_id:node.baseModelId,preset:node.preset,width:node.imageWidth,height:node.imageHeight,prompt:input.prompt,
      ...(input.negativePrompt?{negative_prompt:input.negativePrompt}:{}),...(input.layoutDraft?{layout_draft:input.layoutDraft}:{}),input_fingerprint:input.inputFingerprint};
  }
  function jobRequest(node,input){
    const storyboard=node.mode==='storyboard';
    return{...compileRequest(node,input),...(node.seed===''?{}:{seed:Number(node.seed)}),loras:node.loras.map(item=>({asset_id:item.assetId,scale:item.scale})),
      telegram_enabled:node.telegramEnabled,draw_grid:storyboard&&node.drawGrid,split_panels:storyboard&&node.splitPanels,text_sources:input.textSources.map(wireTrace)};
  }
  function compileReceipt(raw){
    if(raw.kind==='import_draft')return{kind:'import_draft',draft:raw.draft,requiresSourceResolution:raw.requires_source_resolution===true,inputFingerprint:raw.input_fingerprint??null};
    const budget=raw.token_budget||{},compiled=raw.compiled||{};
    return{kind:'compiled',compiled:{prompt:compiled.prompt,promptHash:compiled.prompt_hash,geometrySpec:compiled.geometry_spec??null,geometryHash:compiled.geometry_hash??null,warnings:compiled.warnings||[]},
      tokenBudget:{checked:budget.checked===true,valid:budget.valid??null,promptTokens:budget.prompt_tokens??null,negativeTokens:budget.negative_tokens??null,maxTokens:budget.max_tokens??null,reason:budget.reason||''},
      inputFingerprint:raw.input_fingerprint??null,modelFingerprint:raw.model_fingerprint??null};
  }
  async function importLora(file){
    if(!(file instanceof Blob)||!file.size||file.size>2*1024**3)throw new Error('LoRA 文件须小于 2 GiB');
    const response=await api.request('/api/moss/lora-import?name='+encodeURIComponent(file.name||'lora.safetensors'),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});
    const result=await response.json();if(!response.ok)throw new Error(result.error||`HTTP ${response.status}`);return result;
  }
  let client;
  const getClient=()=>client||=DesktopTasks.createClient({domain:'moss',submit:body=>post('generate',body),progress:id=>DesktopApi.getStatus(id),cancel:id=>post('cancel',{task_id:id})});
  const tasks=Object.freeze({submit:(...args)=>getClient().submit(...args),progress:(...args)=>getClient().progress(...args),cancel:(...args)=>getClient().cancel(...args),result:(...args)=>getClient().result(...args)});
  window.DesktopMossAPI=Object.freeze({
    status:()=>get('status'),catalog:()=>get('catalog'),listLoras:()=>get('lora-list'),
    prepare:sourcePath=>post('prepare',sourcePath?{source_path:sourcePath}:{}),bindModel:sourcePath=>post('model-bind',{source_path:sourcePath}),
    compile:async(node,input)=>compileReceipt(await post('layout-compile',compileRequest(node,input))),
    importDraft:async(draftJson,inputFingerprint)=>compileReceipt(await post('layout-compile',{draft_json:draftJson,...(inputFingerprint?{input_fingerprint:inputFingerprint}:{})})),
    modelTools:()=>get('model-tools'),inspectModel:name=>post('model-inspect',{source_path:name}),
    convertModel:body=>post('model-convert',body),cancelModelConversion:()=>post('model-convert-cancel',{}),deleteModel:modelId=>post('model-delete',{model_id:modelId}),
    importLora,deleteLora:assetId=>post('lora-delete',{asset_id:assetId}),
    submit:(node,input)=>post('generate',jobRequest(node,input)),cancel:taskId=>post('cancel',{task_id:taskId}),
    job:id=>DesktopApi.getStatus(id),compileRequest,jobRequest,compileReceipt,tasks
  });
})();

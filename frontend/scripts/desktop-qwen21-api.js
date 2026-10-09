// Qwen authenticated transport; server paths and credentials never enter canvas state.
(function () {
  const get=path=>api.json('/api/qwen21/'+path);
  const post=(path,body)=>api.json('/api/qwen21/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
  async function uploadImage(blob,filename){
    if(!(blob instanceof Blob)||!blob.size||blob.size>32*1024**2)throw new Error('参考图须小于 32 MB');
    const response=await api.request('/api/qwen21/upload?name='+encodeURIComponent(filename||'reference.png'),{method:'POST',headers:{'Content-Type':blob.type||'application/octet-stream'},body:blob});
    const result=await response.json();if(!response.ok)throw new Error(result.error||`HTTP ${response.status}`);return result;
  }
  async function sourceBlob(value){
    const raw=String(value||'').trim();if(!raw)throw new Error('参考图地址为空');
    if(raw.startsWith('data:')||raw.startsWith('blob:'))return api.blob(raw);
    const url=new URL(raw,location.href);return url.origin===location.origin?api.blob(url.pathname+url.search):(await DesktopApi.importImageUrl(url.href)).blob;
  }
  let client;
  const getClient=()=>client||=DesktopTasks.createClient({domain:'qwen21',submit:body=>post('generate',body),progress:id=>DesktopApi.getStatus(id),cancel:id=>post('cancel',{task_id:id})});
  const tasks=Object.freeze({submit:(...args)=>getClient().submit(...args),progress:(...args)=>getClient().progress(...args),cancel:(...args)=>getClient().cancel(...args),result:(...args)=>getClient().result(...args)});
  window.DesktopQwen21API=Object.freeze({
    status:()=>get('status'),catalog:()=>get('catalog'),listLoras:()=>get('lora-list'),
    prepare:(baseModelId,preset='viggle-v03-r256')=>post('prepare',{base_model_id:baseModelId,preset}),
    modelTools:()=>get('model-tools'),inspectModel:filename=>post('model-inspect',{source_path:filename}),
    convertModel:body=>post('model-convert',body),cancelModelConversion:()=>post('model-convert-cancel',{}),
    deleteModel:modelId=>post('model-delete',{model_id:modelId}),
    importVae:sourcePath=>post('vae-import',{source_path:sourcePath}),
    selectVae:vaeId=>post('vae-select',{vae_id:vaeId}),
    submit:body=>post('generate',body),cancel:taskId=>post('cancel',{task_id:taskId}),
    job:id=>DesktopApi.getStatus(id),uploadImage,sourceBlob,tasks
  });
})();

// Authenticated Krea 2 transport. Local paths, HF credentials and model files stay server-side.
(function () {
  const get=path=>api.json('/api/krea2/'+path);
  const post=(path,body)=>api.json('/api/krea2/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
  async function rawUpload(path,blob,filename,maximum){
    if(!(blob instanceof Blob)||!blob.size||blob.size>maximum)throw new Error(`文件须小于 ${Math.ceil(maximum/1024/1024)} MB`);
    const response=await api.request('/api/krea2/'+path+'?name='+encodeURIComponent(filename||'source'),{
      method:'POST',headers:{'Content-Type':blob.type||'application/octet-stream'},body:blob});
    let result={};try{result=await response.json();}catch(error){}
    if(!response.ok)throw new Error(result.error||`HTTP ${response.status}`);
    return result;
  }
  async function sourceBlob(value){
    const raw=String(value||'').trim();if(!raw)throw new Error('参考图地址为空');
    if(raw.startsWith('data:')||raw.startsWith('blob:'))return api.blob(raw);
    const url=new URL(raw,location.href);
    if(url.origin===location.origin)return api.blob(url.pathname+url.search);
    return (await DesktopApi.importImageUrl(url.href)).blob;
  }
  let client;
  const getClient=()=>client||=DesktopTasks.createClient({domain:'krea2',submit:body=>post('generate',body),
    progress:id=>DesktopApi.getStatus(id),cancel:id=>post('cancel',{task_id:id})});
  const tasks=Object.freeze({submit:(...args)=>getClient().submit(...args),progress:(...args)=>getClient().progress(...args),
    cancel:(...args)=>getClient().cancel(...args),result:(...args)=>getClient().result(...args)});
  window.DesktopKrea2API=Object.freeze({
    status:()=>get('status'),catalog:()=>get('catalog'),
    prepare:(baseModelId,safetyEnabled=false)=>post('prepare',{base_model_id:baseModelId,safety_enabled:safetyEnabled===true}),
    listLoras:()=>get('lora-list'),deleteLora:assetId=>post('lora-delete',{asset_id:assetId}),
    modelTools:()=>get('model-tools'),inspectModel:sourcePath=>post('model-inspect',{source_path:sourcePath}),
    convertModel:body=>post('model-convert',body),cancelModelConversion:()=>post('model-convert-cancel',{}),
    deleteModel:modelId=>post('model-delete',{model_id:modelId}),
    importLora:(blob,filename)=>rawUpload('lora-import',blob,filename,2*1024*1024*1024),
    uploadImage:(blob,filename)=>rawUpload('upload',blob,filename,32*1024*1024),
    submit:body=>post('generate',body),cancel:taskId=>post('cancel',{task_id:taskId}),
    job:id=>DesktopApi.getStatus(id),sourceBlob,tasks
  });
})();

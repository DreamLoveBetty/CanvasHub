const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ROOT = path.resolve(__dirname,'..');
function fixture() {
  const records=new Map();let sequence=0,abort=false;
  const db={createObjectStore(){},close(){},transaction(){
    const tx={objectStore:()=>({
      put(value){const request={result:value.id};queueMicrotask(()=>{if(abort)tx.onabort();else{records.set(value.id,value);tx.oncomplete();}});return request;},
      get(id){const request={};queueMicrotask(()=>{request.result=records.get(id);tx.oncomplete();});return request;},
      delete(id){const request={};queueMicrotask(()=>{records.delete(id);tx.oncomplete();});return request;}
    })};return tx;
  }};
  const context={window:{},Blob,Uint8Array,atob,crypto:{randomUUID:()=>String(++sequence)},
    indexedDB:{open(){const r={result:db};queueMicrotask(()=>{r.onupgradeneeded();r.onsuccess();});return r;}},
    FileReader:class {readAsDataURL(blob){blob.arrayBuffer().then(bytes=>{this.result=`data:${blob.type};base64,${Buffer.from(bytes).toString('base64')}`;this.onload();});}}
  };
  vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(ROOT,'frontend/scripts/desktop-audio-assets.js'),'utf8'),context);
  return {api:context.window.DesktopAudioAssets,records,abort:()=>{abort=true;}};
}
test('audio storage only publishes committed binary assets',async()=>{
  const h=fixture();const blob=new Blob(['audio-bytes'],{type:'audio/wav'});const id=await h.api.put(blob);
  assert.equal(id,'audio-1');assert.equal(await h.api.get(id),blob);await h.api.remove(id);assert.equal(await h.api.get(id),null);
});
test('quota/abort is reported instead of an apparent successful import',async()=>{
  const h=fixture();h.abort();await assert.rejects(h.api.put(new Blob(['a'],{type:'audio/wav'})),/保存失败/);assert.equal(h.records.size,0);
});
test('empty, oversized and malformed embedded audio is rejected',async()=>{
  const h=fixture();await assert.rejects(h.api.put(new Blob([])),/100 MB/);
  const oversized = new Blob(['audio'], {type:'audio/wav'});
  Object.defineProperty(oversized, 'size', {value: h.api.MAX_FILE_BYTES + 1});
  await assert.rejects(h.api.put(oversized),/100 MB/);
  await assert.rejects(h.api.put(new Blob(['<html>'], {type:'text/html'})),/MIME/);
  for(const value of ['data:text/html;base64,WA==','data:audio/wav;base64,','data:audio/wav;base64,!!','not-data'])assert.throws(()=>h.api.fromDataUrl(value));
  const blob=h.api.fromDataUrl('data:audio/wav;base64,UklGRg==');assert.equal(blob.type,'audio/wav');assert.equal(await blob.text(),'RIFF');
});
test('portable workflow export embeds binaries without blob URLs',async()=>{
  const h=fixture();const id=await h.api.put(new Blob(['RIFF'],{type:'audio/wav'}));
  const payload={state:{canvas:{nodes:{a:{type:'audio',audioAssetId:id},b:{type:'image',imageData:'untouched'}}}}};
  assert.equal(await h.api.embedWorkflowAssets(payload),payload);assert.equal(payload.state.canvas.nodes.a.audioAssetId,'');
  assert.equal(payload.state.canvas.nodes.a.audioData,'data:audio/wav;base64,UklGRg==');assert.equal(payload.state.canvas.nodes.b.imageData,'untouched');
});
test('missing local audio blocks portable export instead of silently losing media',async()=>{
  const h=fixture();await assert.rejects(h.api.embedWorkflowAssets({state:{canvas:{nodes:{a:{type:'audio',audioAssetId:'audio-missing',mediaName:'clip.wav'}}}}}),/重新导入/);
});

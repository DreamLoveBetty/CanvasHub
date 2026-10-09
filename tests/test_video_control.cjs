const {test}=require('node:test'); const assert=require('node:assert/strict');
const fs=require('node:fs'); const path=require('node:path'); const vm=require('node:vm');
const root=path.join(__dirname,'../frontend/scripts'); const sandbox={window:{}};
for(const file of ['desktop-state-icon.js', 'desktop-video-control-model.js','desktop-video-control-view.js','desktop-canvas-connections.js']) vm.runInNewContext(fs.readFileSync(path.join(root,file),'utf8'),sandbox);
const model=sandbox.window.DesktopVideoControlModel;
function transport(api={}) {
  const ctx={window:{location:{href:'http://localhost:18463/desktop.html',origin:'http://localhost:18463'}},URL,Blob,api};
  vm.runInNewContext(fs.readFileSync(path.join(root,'desktop-video-control-api.js'),'utf8'),ctx);
  return ctx.window.DesktopVideoControlAPI;
}
test('video transport accepts generated, nested archive and control-video sources',async()=> {
  const calls=[],api=transport({blob:async url=>{calls.push(url);return 'video bytes';}});
  for(const url of ['/video/generated.mp4','/video/archive/2026-09-20/clip.mp4',
    '/video/imported/folder/%E8%A7%86%E9%A2%91%20%E5%8F%82%E8%80%83.mov?download=1',
    '/api/video_control/source?id=synthetic','/api/video_control/artifact?id=synthetic&name=result%2Fcontrol.mp4',
    '/api/topaz_video/source?id=synthetic','/api/topaz_video/artifact?id=synthetic&name=result%2Fenhanced.mp4']) {
    assert.equal(api.sourceUrl(url),url);
    assert.equal(await api.blob('http://localhost:18463'+url+'#preview'),'video bytes');
    assert.equal(calls.at(-1),url);
  }
});
test('video transport still refuses external origins and unrelated local endpoints',()=> {
  const api=transport();
  for(const url of ['https://example.com/video/clip.mp4','//example.com/video/clip.mp4',
    'http://user:password@localhost:18463/video/clip.mp4','file:///tmp/clip.mp4',
    'blob:http://localhost:18463/synthetic','data:video/mp4;base64,AAAA','/api/settings',
    '/video/','/video-other/clip.mp4','/video/../../api/settings','/api/video_control/source/extra']) {
    assert.throws(()=>api.sourceUrl(url),/请导入本地视频/);
  }
});
test('video-only typed connections, no image/audio/generation control claim',()=> {
  assert.ok(model.policy({type:'video'},{type:'video_control'})); assert.ok(model.policy({type:'video_control'},{type:'video'}));
  for(const type of ['audio','image','video_inference','music_generate']) assert.equal(model.policy({type},{type:'video_control'}),null);
});
test('state normalisation and snake_case request',()=> {
  const node=model.normalize({type:'video_control',maxSeconds:Infinity,cannyLow:NaN,control:'invalid'});
  assert.equal(node.width,720);assert.equal(node.height,390);assert.equal(node.maxSeconds,15);
  const request=model.request(node,'a'.repeat(32));assert.equal(request.max_res,640);assert.equal(request.max_seconds,15);
  assert.equal(request.control,'depth'); assert.equal(request.asset_id,'a'.repeat(32));assert.equal(request.maxSeconds,undefined);
});
test('independent domains compose without losing policies',()=> {
  let changes=0;
  const composed=sandbox.window.DesktopCanvasConnections.combineDomains({targets:{audio:['music']},policy:()=>null,changed:()=>changes++,removed:()=>{}},
    {targets:model.targets,policy:model.policy,changed:()=>changes++,removed:()=>{}});
  assert.ok(composed.targets.video.includes('video_control')); assert.ok(composed.targets.audio.includes('music'));
  assert.ok(composed.policy({type:'video'},{type:'video_control'})); composed.changed(); assert.equal(changes,2);
});
test('view has shared action, suspended progress and no inline error/stop/history',()=> {
  const view=sandbox.window.DesktopVideoControlView.create({model,stateIcon:sandbox.window.DesktopStateIcon,escapeHtml:s=>s});
  const html=view.html(model.normalize({id:'synthetic',type:'video_control'}));
  assert.match(html,/desk-generation-action/); assert.match(html,/data-control-progress/);
  assert.doesNotMatch(html,/<details|开始转谱|data-control-error|data-control-stop/);
});

const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
function fixture() {
  const state={nodes:{},edges:[]}, elements=new Map(), reports=[], timers=new Map(), jobs=new Map(), cancelled=[];
  let seq=0,timer=0;
  const ctx={window:{},AbortController,setTimeout(fn){const id=++timer;timers.set(id,fn);return id;},clearTimeout(id){timers.delete(id);}};
  for(const file of ['desktop-video-control-model.js','desktop-canvas-video-control.js']) vm.runInNewContext(fs.readFileSync(path.join(root,file),'utf8'),ctx);
  const m=ctx.window.DesktopVideoControlModel;
  const api={sourceUrl:u=>u,blob:async()=>({}),upload:async()=>({asset_id:'a'.repeat(32)}),
    submit:async spec=>{const j={id:String(++seq).padStart(32,'0'),status:'queued',spec,artifacts:[]};jobs.set(j.id,j);return j;},
    job:async id=>jobs.get(id),cancel:async id=>{cancelled.push(id);const j=jobs.get(id);if(j)j.status='cancelled';return j;}};
  let controller;
  function element(){return{fields:new Map(),addEventListener(){},querySelector(k){if(!this.fields.has(k))this.fields.set(k,{textContent:''});return this.fields.get(k);}};}
  const addNode=(type)=>{const id='result'+(++seq);state.nodes[id]={id,type};elements.set(id,element());return id;};
  const connectNodes=(from,to)=>{state.edges.push({from,to});controller.connections.changed(from,to);};
  controller=ctx.window.DesktopCanvasVideoControl.create({model:m,api,view:{html:()=>'',paint(){}},
    getCanvas:()=>state,getNodeState:id=>state.nodes[id],getNodeElement:id=>elements.get(id),addNode,connectNodes,
    refreshVideoNode(){},saveState(){},reportStatus:x=>reports.push(x)});
  const node=m.normalize({id:'control',type:'video_control',x:0,y:0});state.nodes.control=node;elements.set(node.id,element());
  state.nodes.source={id:'source',type:'video',mediaUrl:'/video/synthetic.mp4',mediaName:'synthetic.mp4'};
  state.edges.push({from:'source',to:'control'});controller.reconcile();
  return {state,node,api,controller,jobs,reports,cancelled,async poll(){const callbacks=[...timers.values()];timers.clear();callbacks.forEach(fn=>fn());await flush();}};
}
test('controller publishes one result, preserves typed provenance and reuses completed output',async()=> {
 const h=fixture();await h.controller.run('control');await flush();
 const job=h.jobs.get(h.node.jobId);Object.assign(job,{status:'succeeded',engine:'synthetic',media:{width:320,height:192,fps:24},artifacts:[{name:'result/control.mp4',url:'/api/video_control/artifact?id=synthetic',file_size:20}]});
 await h.poll();const results=Object.values(h.state.nodes).filter(n=>n.controlMetadata);
 assert.equal(results.length,1);assert.equal(results[0].controlMetadata.kind,'depth');assert.equal(h.node.resultJobId,job.id);
 h.state.nodes.manual={id:'manual',type:'video'};h.state.edges.push({from:'control',to:'manual'});h.controller.connections.changed('control','manual');
 assert.equal(h.state.nodes.manual.sourceTaskId,job.id);h.controller.disposeAll();
});
test('pending submission cancellation cancels late accepted task instead of publishing',async()=> {
 const h=fixture(),gate=deferred();h.api.submit=()=>gate.promise;
 const running=h.controller.run('control');await flush();
 await h.controller.getCancelableTasks()[0].cancel();gate.resolve({id:'b'.repeat(32),status:'queued'});await running;await flush();
 assert.equal(h.cancelled[0],'b'.repeat(32));assert.equal(h.node.status,'cancelled');assert.equal(h.node.jobId,'');h.controller.disposeAll();
});
test('deleted node cancels known job, stale polling cannot change replacement workflow',async()=> {
 const h=fixture();await h.controller.run('control');await flush();const id=h.node.jobId;
 h.controller.dispose('control',true);assert.equal(h.cancelled[0],id);
 const count=h.reports.length;await h.poll();assert.equal(h.reports.length,count);h.controller.disposeAll();
});
test('source URL changes invalidate uploaded asset cache',async()=> {
 const h=fixture();h.state.nodes.source.videoControlAssetId='stale';h.state.nodes.source.videoControlAssetUrl='/video/old.mp4';
 let uploads=0;h.api.upload=async()=>{uploads++;return{asset_id:'c'.repeat(32)};};
 await h.controller.run('control');await flush();assert.equal(uploads,1);assert.equal(h.jobs.get(h.node.jobId).spec.asset_id,'c'.repeat(32));h.controller.disposeAll();
});
test('failed operation reports through status port, leaves old output intact',async()=> {
 const h=fixture();h.api.submit=async()=>{throw Error('synthetic failure');};await h.controller.run('control');await flush();
 assert.equal(h.reports.at(-1).tone,'error');assert.match(h.reports.at(-1).task.raw_detail,/synthetic failure/);assert.equal(h.node.status,'failed');h.controller.disposeAll();
});
test('source-read failure has a failed summary and can reopen details before any job exists',async()=> {
 const h=fixture();h.api.blob=async()=>{throw Error('synthetic source rejection');};
 await h.controller.run('control');await flush();
 const task=h.reports.at(-1).task;
 assert.equal(task.status,'failed');assert.equal(task.status_label,'失败');assert.equal(task.task_id,'');
 assert.equal(task.progress_text,'操作失败，点击查看详情');
 const detail=JSON.parse(task.raw_detail.split('\n\n')[0]);
 assert.equal(detail.message,'synthetic source rejection');assert.equal(detail.stage,task.stage);
 const count=h.reports.length;h.controller.showStatus('control');assert.equal(h.reports.length,count+1);
 assert.equal(h.reports.at(-1).task.progress_text,task.progress_text);h.controller.disposeAll();
});
test('H3 refuses control-video inputs until reference-video integration is verified',()=> {
 vm.runInNewContext(fs.readFileSync(path.join(root,'desktop-canvas-generation-config.js'),'utf8'),sandbox);
 const controller=sandbox.window.DesktopCanvasGenerationConfig.create({getNodeElement:()=>({}),
  syncVideoInferenceNodeStateFromDom:()=>({mode:'reference_to_video'}),getVisibleInputPrompt:()=> 'synthetic prompt',
  videoInferenceInputSummary:()=>({referenceVideo:{node:{controlMetadata:{kind:'depth'}}}})});
 assert.throws(()=>controller.readVideoInferenceNodeConfig('h3'),/尚未开放/);
});

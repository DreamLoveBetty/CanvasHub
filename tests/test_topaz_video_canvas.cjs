const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '../frontend/scripts');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const status = {models: [
  {id:'precise-26',label:'Starlight Precise 2.6',family:'starlight',available:true,verified:true,scales:[2],
    parameters:[{key:'softness',label:'柔化',type:'number',min:0,max:2,step:.1,default:1}]},
  {id:'mini',label:'Starlight Mini',family:'starlight',available:false,verified:false,reason:'macOS 27 首帧不兼容',scales:[2],parameters:[]},
  {id:'proteus-v4',label:'Proteus v4',family:'standard',available:true,verified:false,scales:[1,4],
    parameters:[{key:'details',label:'细节',type:'number',min:0,max:1,step:.05,default:0},
      {key:'gsize',label:'颗粒尺寸',type:'number',min:0,max:5,step:1,default:0}]},
]};
const ctx = {window:{}};
for (const file of ['desktop-state-icon.js', 'desktop-topaz-video-pipeline.js', 'desktop-topaz-video-model.js', 'desktop-topaz-video-view.js', 'desktop-canvas-topaz-video.js'])
  vm.runInNewContext(read(file), ctx);
const model = ctx.window.DesktopTopazVideoModel;
const flush = async () => {for (let i=0;i<20;i++) await Promise.resolve();};
function transport(fakeApi = {}) {
  const sandbox = {window:{location:{href:'http://localhost:18463/desktop.html',origin:'http://localhost:18463'},
    DesktopTasks:{createClient:({submit,progress,cancel}) => ({
      submit:async x=>({raw:await submit(x)}),progress:async x=>({raw:await progress(x)}),
      cancel:async x=>({raw:await cancel(x)}),result:async()=>({raw:{}}),
    })}},URL,Blob,api:fakeApi};
  vm.runInNewContext(read('desktop-topaz-video-api.js'),sandbox);
  return sandbox.window.DesktopTopazVideoAPI;
}
test('catalog availability, verified labels and model-specific snake_case request', () => {
  const catalog=model.catalogModels(status),node=model.normalize({type:'topaz_video'});
  model.syncForModel(node,catalog[0]);
  assert.equal(node.width,680);assert.equal(node.height,330);assert.equal(node.model,'precise-26');
  assert.equal(node.modelParams.softness,1);
  const request=model.request(node,'a'.repeat(32),catalog[0]);
  assert.equal(request.asset_id,'a'.repeat(32));assert.equal(request.max_seconds,0);
  assert.equal(request.task_kind,'export');assert.equal(request.start_seconds,0);
  assert.equal(request.softness,1);assert.equal(request.modelParams,undefined);
  node.model='mini';model.syncForModel(node,catalog[1]);
  assert.throws(()=>model.request(node,'a'.repeat(32),catalog[1]),/不兼容/);
  node.model='proteus-v4';model.syncForModel(node,catalog[2]);
  assert.equal(node.scale,1);assert.equal(node.modelParams.details,0);
  node.modelParams.gsize=.1;model.syncForModel(node,catalog[2]);assert.equal(node.modelParams.gsize,0);
  node.modelParams.gsize=.1;assert.throws(()=>model.request(node,'a'.repeat(32),catalog[2]),/有效步进/);
  node.modelParams.gsize=2;assert.equal(model.request(node,'a'.repeat(32),catalog[2]).gsize,2);
  assert.equal(catalog[2].verified,false);
});
test('only video inputs and outputs, not image Topaz or ReShot domains', () => {
  assert.ok(model.policy({type:'video'},{type:'topaz_video'}));
  assert.ok(model.policy({type:'topaz_video'},{type:'video'}));
  for (const type of ['audio','image','topaz','video_control','video_inference'])
    assert.equal(model.policy({type},{type:'topaz_video'}),null);
});
test('compact view shows presets and workbench entry but keeps detailed parameters out of the node', () => {
  const view=ctx.window.DesktopTopazVideoView.create({model,stateIcon:ctx.window.DesktopStateIcon,escapeHtml:s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;')});
  const node=model.normalize({id:'test',type:'topaz_video'});
  const html=view.html(node);
  assert.match(html,/data-topaz-video-run disabled/);
  assert.match(html,/data-topaz-video-progress hidden/);
  assert.match(html,/处理范围/);assert.match(html,/全片/);assert.match(html,/前 N 秒/);
  assert.match(html,/data-topaz-video-workbench/);assert.match(html,/data-topaz-video-preset/);
  assert.doesNotMatch(html,/data-topaz-video-stop|data-topaz-video-error|<details/);
  let rendered='';
  node.model='proteus-v4';model.syncForModel(node,model.catalogModels(status)[2]);
  const element={querySelector:()=>({set innerHTML(value){rendered=value;}})};
  view.renderFields(element,node,model.catalogModels(status));
  assert.match(rendered,/Proteus v4 · 待验证/);
  assert.match(rendered,/Starlight Mini · 不可用/);
  assert.doesNotMatch(rendered,/data-topaz-video-param="details"/);
});
test('transport only reads local assets, same-origin blob/video data and rejects remote URLs', async () => {
  const seen=[];const client=transport({json:async url=>{seen.push(url);return status;},blob:async url=>{seen.push(url);return new Blob(['video']);}});
  assert.equal((await client.status()).models.length,3);
  for (const url of ['/video/archive/clip.mp4','/api/topaz_video/source?id=one',
    '/api/topaz_video/artifact?id=one&name=result%2Fenhanced.mp4','/api/video_control/artifact?id=two']) {
    assert.equal(client.sourceUrl(url),url);
    await client.blob(url);assert.equal(seen.at(-1),url);
  }
  assert.equal(client.sourceUrl('blob:http://localhost:18463/uuid'),'blob:http://localhost:18463/uuid');
  assert.equal(client.sourceUrl('data:video/mp4;base64,AA=='),'data:video/mp4;base64,AA==');
  for (const url of ['https://example.com/video/x.mp4','blob:https://example.com/id','data:text/html;base64,AA==',
    '/api/settings','/video/../../api/settings','file:///tmp/a.mp4'])
    assert.throws(()=>client.sourceUrl(url),/请导入本地视频/);
});
function fixture({workbench, runtime = status} = {}) {
  const graph={nodes:{},edges:[]},elements=new Map(),jobs=new Map(),reports=[],cancelled=[],timers=new Map();
  let sequence=0,timer=0,uploads=0;
  const scope={window:{},AbortController,setTimeout(fn){const id=++timer;timers.set(id,fn);return id;},clearTimeout(id){timers.delete(id);}};
  vm.runInNewContext(read('desktop-topaz-video-pipeline.js'),scope);
  vm.runInNewContext(read('desktop-topaz-video-model.js'),scope);
  vm.runInNewContext(read('desktop-canvas-topaz-video.js'),scope);
  const m=scope.window.DesktopTopazVideoModel;
  const api={status:async()=>runtime,sourceUrl:u=>u,blob:async()=>new Blob(['source']),
    upload:async()=>{uploads++;return {asset_id:'a'.repeat(32)};},
    submit:async spec=>{const job={id:String(++sequence).padStart(32,'0'),status:'queued',spec,artifacts:[]};jobs.set(job.id,job);return job;},
    job:async id=>jobs.get(id),cancel:async id=>{cancelled.push(id);const j=jobs.get(id);if(j)j.status='cancelled';return j;}};
  const element=()=>({fields:new Map(),addEventListener(){},querySelector(key){if(!this.fields.has(key))this.fields.set(key,{textContent:''});return this.fields.get(key);}});
  const addNode=type=>{const id='result'+(++sequence);graph.nodes[id]={id,type};elements.set(id,element());return id;};
  let controller;
  const connectNodes=(from,to)=>{graph.edges.push({from,to});controller.connections.changed(from,to);};
  controller=scope.window.DesktopCanvasTopazVideo.create({model:m,api,pipeline:scope.window.DesktopTopazVideoPipeline,
    view:{html:()=>'',paint(){},renderFields(){}},workbench,
    getCanvas:()=>graph,getNodeState:id=>graph.nodes[id],getNodeElement:id=>elements.get(id),
    addNode,connectNodes,refreshVideoNode(){},saveState(){},reportStatus:x=>reports.push(x)});
  const node=m.normalize({id:'enhance',type:'topaz_video',x:0,y:0});
  graph.nodes.enhance=node;elements.set(node.id,element());
  graph.nodes.source={id:'source',type:'video',mediaUrl:'/video/source.mp4',mediaName:'source.mp4'};
  graph.edges.push({from:'source',to:'enhance'});
  controller.reconcile();
  return {node,graph,jobs,reports,cancelled,api,controller,uploads:()=>uploads,
    async poll(){const callbacks=[...timers.values()];timers.clear();callbacks.forEach(fn=>fn());await flush();}};
}
test('controller refuses Mini, publishes completed MP4 to video and reports unified status', async () => {
  const h=fixture();await flush();h.node.model='mini';
  await h.controller.run('enhance');assert.equal(h.uploads(),0);
  assert.match(h.reports.at(-1).task.raw_detail,/不兼容/);
  h.node.model='precise-26';await h.controller.run('enhance');await flush();
  assert.equal(h.uploads(),1);
  const job=h.jobs.get(h.node.jobId);assert.equal(job.spec.model,'precise-26');assert.equal(job.spec.softness,1);
  Object.assign(job,{status:'succeeded',artifacts:[{name:'result/enhanced.mp4',url:'/api/topaz_video/artifact?id=x&name=result%2Fenhanced.mp4',file_size:100}]});
  await h.poll();
  const results=Object.values(h.graph.nodes).filter(n=>n.topazVideoMetadata);
  assert.equal(results.length,1);assert.equal(results[0].sourceTaskId,job.id);
  assert.equal(h.node.resultJobId,job.id);
  assert.equal(h.reports.at(-1).task.task_domain,undefined); // Registry adds domain at the host boundary.
  h.controller.disposeAll();
});
test('selected-range preview uses the unified task API without publishing downstream video', async () => {
  const h=fixture();await flush();
  await h.controller.runPreview('enhance',{startSeconds:3.25,maxSeconds:2.5});await flush();
  const job=h.jobs.get(h.node.previewJobId);
  assert.equal(job.spec.task_kind,'preview');assert.equal(job.spec.start_seconds,3.25);assert.equal(job.spec.max_seconds,2.5);
  Object.assign(job,{status:'succeeded',media:{duration_seconds:2.5},artifacts:[{name:'result/enhanced.mp4',url:'/api/topaz_video/artifact?id=p&name=result%2Fenhanced.mp4'}]});
  await h.poll();
  assert.equal(h.node.previewStatus,'succeeded');assert.equal(h.node.previewStartSeconds,3.25);
  assert.equal(Object.values(h.graph.nodes).filter(n=>n.topazVideoMetadata).length,0);
  assert.match(h.reports.at(-1).task.operation_label,/预览/);
  h.controller.disposeAll();
});
test('filter-only previews preserve slow-motion metadata and mark changed processing drafts stale', async () => {
  const updates=[],runtime={...status,processing_ready:true,encoding:{codecs:['h264']},capabilities:{
    interpolation:{available:true,models:[{id:'chf-3',available:true}]}}};
  const h=fixture({runtime,workbench:{update(_id,next){updates.push(next);},dispose(){}}});await flush();
  h.node.enhancementEnabled=false;
  h.node.videoFilters.interpolation.enabled=true;h.node.videoFilters.interpolation.slowmo=2;
  await h.controller.runPreview('enhance',{startSeconds:.25,maxSeconds:.5});await flush();
  const job=h.jobs.get(h.node.previewJobId);
  assert.equal(job.spec.scale,1);assert.equal(job.spec.enhancement,false);assert.equal(job.spec.filters.interpolation.slowmo,2);
  Object.assign(job,{status:'succeeded',media:{duration_seconds:1,time_scale:2},artifacts:[{name:'result/enhanced.mp4',url:'/api/topaz_video/artifact?id=p&name=result%2Fenhanced.mp4'}]});
  await h.poll();assert.equal(updates.at(-1).result.timeScale,2);assert.equal(updates.at(-1).result.stale,false);
  h.node.encodingOptions.bitrateMbps=25;h.controller.graphChanged();
  assert.equal(updates.at(-1).result.stale,true);assert.equal(h.jobs.size,1);
  assert.equal(Object.values(h.graph.nodes).filter(n=>n.topazVideoMetadata).length,0);
  h.controller.disposeAll();
});
test('completed previews are bound to their input video and disappear when the source changes', async () => {
  const updates=[];
  const h=fixture({workbench:{update(_id,next){updates.push(next);},dispose(){}}});await flush();
  await h.controller.runPreview('enhance',{startSeconds:0,maxSeconds:2});await flush();
  const job=h.jobs.get(h.node.previewJobId);
  Object.assign(job,{status:'succeeded',artifacts:[{name:'result/enhanced.mp4',url:'/api/topaz_video/artifact?id=preview&name=result%2Fenhanced.mp4'}]});
  await h.poll();
  assert.ok(h.node.previewSourceKey.includes('/video/source.mp4'));
  assert.equal(updates.at(-1).result.sourceKey,h.node.previewSourceKey);
  Object.assign(h.graph.nodes.source,{mediaUrl:'/video/replacement.mp4',mediaName:'replacement.mp4',topazVideoAssetId:'',topazVideoAssetUrl:''});
  h.controller.graphChanged();
  assert.equal(updates.at(-1).source.name,'replacement.mp4');
  assert.equal(updates.at(-1).result,null);
  await h.controller.run('enhance');await flush();
  const replacementJob=h.jobs.get(h.node.jobId);
  Object.assign(replacementJob,{status:'succeeded',artifacts:[{name:'result/enhanced.mp4',url:'/api/topaz_video/artifact?id=replacement&name=result%2Fenhanced.mp4'}]});
  await h.poll();
  assert.ok(h.node.exportSourceKey.includes('/video/replacement.mp4'));
  assert.equal(updates.at(-1).result.sourceKey,h.node.exportSourceKey);
  h.controller.disposeAll();
});
test('desktop loads isolated scripts before canvas and wires the shared task domain', () => {
  const html=fs.readFileSync(path.join(root,'../desktop.html'),'utf8');
  const canvas=read('desktop-canvas.js'),nodes=read('desktop-canvas-nodes.js'),workflow=read('desktop-canvas-workflow.js');
  for (const file of ['desktop-topaz-video-model.js','desktop-topaz-video-api.js','desktop-topaz-video-view.js','desktop-topaz-video-workbench.js','desktop-canvas-topaz-video.js']) {
    assert.ok(html.includes(file+'?v='));
    assert.ok(html.indexOf(file+'?v=')<html.indexOf('scripts/desktop-canvas.js?v='));
  }
  assert.match(html,/desktop-topaz-video.css\?v=/);
  assert.match(html,/desktop-topaz-video-workbench.css\?v=/);
  assert.match(canvas,/DesktopTopazVideoWorkbench\.create/);
  assert.match(canvas,/taskRegistry.register\('topaz_video'/);
  assert.match(canvas,/canvasTopazVideo.connections/);
  assert.match(nodes,/topazVideoNode\.nodeHtml/);
  assert.match(workflow,/topazVideoDefinition\.normalize/);
});

test('workbench has direct compare, a real trim timeline, stable inspector controls and system styling', () => {
  const workbench=read('desktop-topaz-video-workbench.js');
  const controller=read('desktop-canvas-topaz-video.js');
  const css=fs.readFileSync(path.join(root,'../styles/desktop-topaz-video-workbench.css'),'utf8');
  const html=fs.readFileSync(path.join(root,'../desktop.html'),'utf8');

  assert.match(workbench,/role="separator"/);
  assert.match(workbench,/data-tvwb-divider[^\n]+tabindex="0"/);
  assert.match(workbench,/setPointerCapture\(event\.pointerId\)/);
  assert.match(workbench,/function mediaBand\(\)/);
  assert.match(css,/desk-topaz-video-workbench__divider[\s\S]*?pointer-events:auto/);
  assert.doesNotMatch(workbench,/data-tvwb-compare/);
  assert.match(workbench,/data-tvwb-zoom/);
  assert.match(workbench,/function toggleZoom\(\)/);
  assert.match(workbench,/drag\?\.kind !== 'pan'/);
  assert.match(css,/grid-template-rows:auto minmax\(160px,1fr\) 40px auto/);
  assert.match(css,/workbench__header\s*\{[^}]*min-height:40px/);
  assert.match(css,/workbench__heading\s*\{[^}]*align-items:baseline/);
  assert.match(css,/input\[type=range\]\s*\{[^}]*height:24px/);
  assert.match(css,/timeline-editor[\s\S]*?height:50px/);
  assert.match(workbench,/data-tvwb-mode="side"/);
  assert.match(css,/is-side-by-side/);
  assert.match(workbench,/data-tvwb-mute/);
  assert.match(workbench,/data-tvwb-timeline-zoom/);
  assert.match(workbench,/data-tvwb-mark="start"/);
  assert.match(workbench,/data-tvwb-mark="end"/);
  assert.match(workbench,/WORKFLOW_PRESETS/);
  assert.match(workbench,/内置预设/);
  assert.match(workbench,/inspector.filters/);
  assert.doesNotMatch(workbench,/运行时未接入/);
  assert.match(read('desktop-topaz-video-inspector.js'),/帧插值/);
  assert.match(workbench,/编码设置/);
  assert.match(workbench,/data-tvwb-sidebar-toggle/);

  assert.match(workbench,/data-tvwb-timeline/);
  assert.match(workbench,/data-tvwb-trim="start"/);
  assert.match(workbench,/data-tvwb-trim="end"/);
  assert.match(workbench,/data-tvwb-playhead-marker/);
  assert.doesNotMatch(workbench,/<input type="range"[^>]+data-tvwb-(?:start|end|playhead)>/);
  assert.match(workbench,/savedDuration > 0 \? savedDuration : Math\.min\(5,/);
  assert.match(controller,/fps: Number\(source\.fps \|\| 0\)/);

  assert.match(workbench,/next\.catalog && next\.catalog !== previousCatalog/);
  assert.doesNotMatch(workbench,/next\.catalog \|\| next\.node/);
  assert.match(workbench,/if \(parameterKey\(input\)\) commitParameter\(input\)/);
  const selects=read('desktop-select.js');
  assert.match(selects,/closest\('\.desk-topaz-video-workbench'\).*topaz-video-workbench/);
  assert.match(css,/desk-select-menu\[data-select-variant="topaz-video-workbench"\][^{]*\{z-index:2602;/);
  assert.match(controller,/previewSourceKey = inputSourceKey/);
  assert.match(controller,/matchedSourceKey !== source\.key/);
  assert.match(css,/--desk-node-glass-background/);
  assert.match(css,/--desk-settings-field-background/);
  assert.match(css,/--desk-action-primary-gloss/);
  assert.doesNotMatch(css,/--desk-layout-/);
  assert.match(css,/--desk-font-size-caption/);
  assert.match(css,/--desk-font-size-micro/);
  assert.doesNotMatch(css,/font-size:\s*[0-9](?:\.\d+)?px/);
  assert.doesNotMatch(css,/backdrop-filter|color-mix\(|radial-gradient\(|linear-gradient\(/);
  assert.match(html,/desktop-topaz-video-workbench\.js\?v=20261005-topaz-pipeline1/);
  assert.match(html,/desktop-topaz-video-workbench\.css\?v=20261006-topaz-panel-polish2/);
  // Shared select changes may bump independently of the Topaz workbench.
  assert.match(html,/desktop-select\.js\?v=\d{8}-[a-z0-9-]+/);
});

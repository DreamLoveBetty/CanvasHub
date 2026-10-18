const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const scripts=path.join(__dirname,'../frontend/scripts');
function load(){
  const context={window:{}};
  for(const name of ['desktop-krea2-control.js','desktop-krea2-model.js']){
    assert.ok(fs.existsSync(path.join(scripts,name)),`${name} must implement the control domain`);
    vm.runInNewContext(fs.readFileSync(path.join(scripts,name),'utf8'),context);
  }
  return context.window;
}
test('control schema persists normalized geometry, not a bitmap or guide pixels',()=>{
  const {DesktopKrea2Control:C}=load();
  const node=C.normalize({type:C.TYPE,id:'c'});
  assert.equal(node.circles.length,2);
  C.applyPreset(node,'large');
  const area=node.circles.reduce((n,c)=>n+Math.PI*c.rx*c.ry,0);
  assert.ok(Math.abs(area-.0718)<1e-8);
  const snapshot=C.request(node);
  assert.equal(snapshot.profile,'editutils-area-v1');
  assert.equal(snapshot.circles.length,2);
  assert.equal('guide' in snapshot,false);
  node.circles[0].cx=.9;
  assert.notEqual(snapshot.circles[0].cx,node.circles[0].cx);
});
test('typed control does not masquerade as an Identity Edit photograph',()=>{
  const {DesktopKrea2Model:M}=load();
  const c={id:'c',type:'krea2_control'}, k=M.normalize({id:'k',type:'krea2'}), i={id:'i',type:'image'};
  const canvas={nodes:{c,k,i},edges:[{from:'c',to:'k',inputRole:'area_control'}]};
  assert.equal(M.policy(c,k).inputRole,'area_control');
  assert.equal(M.resolveMode(k,canvas),'control');
  assert.equal(M.imageInputIds(k,canvas).length,0);
  assert.deepEqual(Array.from(M.controlInputIds(k,canvas)),['c']);
  canvas.edges.push({from:'i',to:'k'});
  assert.equal(M.imageInputIds(k,canvas).length,1);
  assert.equal(M.resolveMode(k,canvas),'control');
});
test('control mode has a dedicated adapter panel, not Identity Edit settings',()=>{
  const window=load();window.addEventListener=()=>{};
  vm.runInNewContext(fs.readFileSync(path.join(scripts,'desktop-canvas-krea2.js'),'utf8'),{window,AbortController});
  const k={id:'k',type:'krea2'},c={id:'c',type:'krea2_control'};
  const controller=window.DesktopCanvasKrea2.create({model:window.DesktopKrea2Model,
    controlModel:window.DesktopKrea2Control,getCanvas:()=>({nodes:{k,c},edges:[{from:'c',to:'k'}]})});
  const html=controller.nodeHtml(k);
  assert.match(html,/区域控制生成/);
  assert.match(html,/data-krea2-control-panel>/);
  assert.match(html,/data-krea2-edit-panel hidden/);
  assert.match(html,/data-krea2-lora-count>0 \/ 3/);
  assert.match(html,/data-krea2-field="controlReferenceSize"/);
  assert.match(html,/<option value="1024" selected>1024/);
});

test('control reference size defaults safely and survives workflow serialization',()=>{
  const {DesktopKrea2Model:M}=load();
  assert.equal(M.normalize({type:'krea2'}).controlReferenceSize,1024);
  for(const size of [512,768,1024]){
    const node=M.normalize({type:'krea2',controlReferenceSize:size});
    assert.equal(M.normalize(JSON.parse(JSON.stringify(node))).controlReferenceSize,size);
    assert.equal(node.imageWidth,1024);
  }
  for(const size of [false,0,256,768.5,'768'])assert.equal(M.normalize({type:'krea2',controlReferenceSize:size}).controlReferenceSize,1024);
});

test('workflow normalization restores control geometry and adapter without aliasing',()=>{
  const window=load();
  vm.runInNewContext(fs.readFileSync(path.join(scripts,'desktop-canvas-workflow.js'),'utf8'),{window});
  const workflow=window.DesktopCanvasWorkflow.create({
    jsonClone:value=>JSON.parse(JSON.stringify(value)),normalizeNodeMenuType:type=>type,
    normalizeNodeGroupId:()=>'',krea2ControlDefinition:window.DesktopKrea2Control,
    krea2Definition:window.DesktopKrea2Model
  });
  const original=window.DesktopKrea2Control.normalize({id:'c',type:'krea2_control'});
  original.circles[0].angle=35;
  const restored=workflow.normalizeWorkflowNode(original,'c');
  assert.equal(restored.type,'krea2_control');assert.equal(restored.circles[0].angle,35);
  restored.circles[0].cx=.9;assert.notEqual(original.circles[0].cx,.9);
  const k=workflow.normalizeWorkflowNode({id:'k',type:'krea2',mode:'control',controlAdapterId:'a'.repeat(64),controlAdapterScale:.8},'k');
  assert.equal(k.controlAdapterId,'a'.repeat(64));assert.equal(k.controlAdapterScale,.8);
});

test('control module is loaded and wired through node, workflow and connection domains',()=>{
  const {hasCacheKey}=require('./asset_keys.cjs');
  const html=fs.readFileSync(path.join(scripts,'../desktop.html'),'utf8');
  for(const file of ['scripts/desktop-krea2-control.js','styles/desktop-krea2-control.css','styles/desktop-krea2-control-geometry.css'])assert.ok(hasCacheKey(html,file));
  assert.ok(html.indexOf('scripts/desktop-krea2-control.js')<html.indexOf('scripts/desktop-canvas.js'));
  const host=fs.readFileSync(path.join(scripts,'desktop-canvas.js'),'utf8');
  assert.match(host,/krea2ControlNode: canvasKrea2Control/);
  assert.match(host,/krea2ControlDefinition: window.DesktopKrea2Control/);
  assert.match(host,/canvasKrea2Control.connections/);
  const nodeHost=fs.readFileSync(path.join(scripts,'desktop-canvas-nodes.js'),'utf8');
  for(const name of ['normalize','nodeHtml','reconcile','disposeAll','dispose'])assert.ok(nodeHost.includes(`krea2Control${name==='normalize'?'Definition':'Node'}${name==='reconcile'||name==='disposeAll'?'?.':'.'}${name}`));
});


test('approximate reference KV is opt-in, persisted, and only submitted for control',()=>{
  const window=load(),M=window.DesktopKrea2Model;
  assert.equal(M.normalize({type:'krea2'}).controlReferenceKvCache,false);
  assert.equal(M.normalize({type:'krea2',controlReferenceKvCache:true}).controlReferenceKvCache,true);
  window.addEventListener=()=>{};
  vm.runInNewContext(fs.readFileSync(path.join(scripts,'desktop-canvas-krea2.js'),'utf8'),{window,AbortController});
  const k={id:'k',type:'krea2',controlReferenceKvCache:true},c={id:'c',type:'krea2_control'};
  const controller=window.DesktopCanvasKrea2.create({model:M,controlModel:window.DesktopKrea2Control,
    getCanvas:()=>({nodes:{k,c},edges:[{from:'c',to:'k'}]})});
  const html=controller.nodeHtml(k);
  assert.match(html,/data-krea2-reference-kv checked/);
  assert.match(html,/参考 KV 加速/);assert.match(html,/近似/);
  const source=fs.readFileSync(path.join(scripts,'desktop-canvas-krea2.js'),'utf8');
  assert.match(source,/control_reference_kv_cache:mode==='control'&&s.node.controlReferenceKvCache/);
});

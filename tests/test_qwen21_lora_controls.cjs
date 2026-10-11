// Controller lifecycle regression: synthetic DOM/API ports, no weights or service access.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const read=name=>fs.readFileSync(path.join(__dirname,'../frontend/scripts',name),'utf8');
const plain=value=>JSON.parse(JSON.stringify(value));
const flush=async()=>{for(let i=0;i<4;i++)await new Promise(resolve=>setImmediate(resolve));};
const identities=['a'.repeat(64),'b'.repeat(64)];

class Element {
  constructor(key=''){
    this.key=key;this.parts=new Map();this.controls=[];this.listeners=new Map();this.dataset={};this.disabled=false;
    this.style={setProperty(){}};this.classList={toggle(){}};
  }
  querySelector(key){if(!this.parts.has(key))this.parts.set(key,new Element(key));return this.parts.get(key);}
  set innerHTML(value){
    this.html=value;
    // Replacing list/reference HTML creates new controls, while ordinary paint must
    // keep the existing LoRA buttons (and therefore their disabled state).
    if(!['[data-qwen21-lora-list]','[data-qwen21-references]'].includes(this.key))return;
    this.controls=[...value.matchAll(/<(button|input)\b([^>]*)>/g)].map(([,tag,attrs])=>{
      const el=new Element();el.tag=tag;el.disabled=/\bdisabled\b/.test(attrs);
      for(const [,name,value] of attrs.matchAll(/data-([\w-]+)="([^"]*)"/g))el.dataset[name.replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=value;
      return el;
    });
  }
  get innerHTML(){return this.html||'';}
  matches(selector){return selector.split(',').some(part=>{
    const attr=part.trim().match(/^\[data-([\w-]+)\]$/);
    return attr&&Object.hasOwn(this.dataset,attr[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase()));
  });}
  querySelectorAll(selector){
    const controls=[...this.parts.values()].flatMap(el=>el.controls);
    if(selector.startsWith('.desk-qwen21__body'))return controls.filter(el=>el.tag==='input');
    return controls.filter(el=>el.matches(selector));
  }
  addEventListener(type,listener){this.listeners.set(type,listener);}
  click(target){if(!target.disabled)this.listeners.get('click')?.({target:{closest:selector=>target.matches(selector)?target:null}});}
}

function fixture({ready=true,prompt='Synthetic landscape',refs=2,models=null,nodeFields={},turboReady=true}={}){
  let nextTimer=0;const timers=new Map(),submitted=[],saved=[],reports=[];
  const sandbox={window:{addEventListener(){},DesktopSelect:{refreshAll(){}}},AbortController,
    setTimeout:(fn,ms)=>{timers.set(++nextTimer,{fn,ms});return nextTimer;},clearTimeout:id=>timers.delete(id)};
  vm.createContext(sandbox);
  for(const name of ['desktop-qwen21-model.js','desktop-canvas-qwen21.js'])vm.runInContext(read(name),sandbox);
  const model=sandbox.window.DesktopQwen21Model;
  const node={id:'q',type:'qwen21',status:'idle',loras:identities.map((assetId,i)=>({assetId,scale:i?.7:1})),...nodeFields};
  const references=Array.from({length:refs},(_,i)=>({id:`image-${i}`,sourceNodeId:`image-${i}`,name:`Reference ${i+1}`,imageData:'synthetic'}));
  const canvas={nodes:{q:node,...Object.fromEntries(references.map(ref=>[ref.id,{id:ref.id,type:'image'}]))},edges:references.map(ref=>({from:ref.id,to:'q'}))};
  const element=new Element();
  const runtime={environment_ready:true,source_ready:true,turbo_ready:turboReady,turbo_adapters:{},preparation:{status:'idle'},models:models||[{id:model.DEFAULT_MODEL_ID,ready}]};
  let job={status:'processing',result_files:[]};
  const api={status:async()=>runtime,listLoras:async()=>({loras:identities.map((asset_id,i)=>({asset_id,name:`Synthetic LoRA ${i+1}`}))}),
    submit:async request=>{submitted.push(plain(request));job={status:'processing',result_files:[]};return{task_id:'qwen21_'+'c'.repeat(32),status:'queued'};},
    job:async()=>job,cancel:async()=>{job={status:'canceled'};return{ok:true};},
    sourceBlob:async()=>({}),uploadImage:async()=>({upload_token:'synthetic-upload'}),
    prepare:async()=>{throw new Error('Synthetic preparation failure');}};
  const controller=sandbox.window.DesktopCanvasQwen21.create({model,api,getCanvas:()=>canvas,getNodeState:id=>canvas.nodes[id],
    getNodeElement:id=>id==='q'?element:null,getImageReferences:()=>references,getTextNodes:()=>prompt?[{text:prompt}]:[],materializeText:item=>item.text,
    saveState:()=>saved.push(plain(node)),reportStatus:report=>reports.push(report),
    addNode(){throw new Error('Unexpected output publication');},connectNodes(){},setImageFromResult(){},applyNodeLayout(){},updateLinkPath(){}});
  controller.nodeHtml(node);controller.reconcile();
  return{node,element,api,runtime,controller,submitted,saved,reports,
    buttons:()=>element.querySelectorAll('[data-qwen21-lora-remove]'),
    refs:()=>element.querySelectorAll('[data-qwen21-ref-up],[data-qwen21-ref-down]'),
    run:()=>element.click({disabled:false,matches:selector=>selector==='[data-qwen21-run]'}),
    async finish(status){job={status,result_files:[]};const timer=[...timers].find(([,item])=>item.ms===1500);assert.ok(timer,'poll scheduled');timers.delete(timer[0]);await timer[1].fn();await flush();},
    dispose:()=>controller.disposeAll()};
}

for(const status of ['succeeded','succeeded_no_telegram','telegram_failed','failed','canceled','cancelled']){
  test(`Qwen LoRA removal unlocks the same buttons after ${status} and saves only the remaining stack`,async t=>{
    const f=fixture();t.after(f.dispose);await flush();
    const buttons=f.buttons(),preset=f.node.preset;
    assert.equal(buttons.length,2);assert.ok(buttons.every(button=>!button.disabled));
    f.run();assert.ok(buttons.every(button=>button.disabled),'lock immediately during submission');await flush();
    assert.equal(f.node.status,'processing');f.element.click(buttons[1]);assert.equal(f.node.loras.length,2,'busy click cannot remove');
    assert.ok(f.refs().every(button=>button.disabled),'reference ordering remains locked while running');
    await f.finish(status);
    assert.strictEqual(f.buttons()[1],buttons[1],'poll completion must not need a list rebuild');
    assert.ok(buttons.every(button=>!button.disabled),'terminal state restores removal');
    assert.deepEqual(f.refs().map(button=>button.disabled),[true,false,false,true],'preserve first/last reference boundaries');
    const saves=f.saved.length;f.element.click(buttons[0]);
    assert.deepEqual(plain(f.node.loras),[{assetId:identities[1],scale:.7}]);
    assert.equal(f.saved.length,saves+1);assert.deepEqual(f.saved.at(-1).loras,plain(f.node.loras));
    assert.equal(f.node.preset,preset,'ordinary LoRA removal does not remove the acceleration preset');
    assert.match(f.element.querySelector('[data-qwen21-lora-count]').textContent,/1 \/ 4/);
    assert.equal(f.buttons()[0].dataset.qwen21LoraRemove,'0','remaining row is reindexed');
    f.run();await flush();assert.deepEqual(f.submitted.at(-1).loras,[{asset_id:identities[1],scale:.7}]);
    await f.finish('succeeded_no_telegram');f.element.click(f.buttons()[0]);
    assert.equal(f.node.loras.length,0);assert.equal(f.buttons().length,0);
    assert.match(f.element.querySelector('[data-qwen21-lora-list]').innerHTML,/未加载普通 LoRA/);
  });
}

test('Qwen validation failure restores removal without submitting or rebuilding the list',async t=>{
  const f=fixture({prompt:''});t.after(f.dispose);await flush();const button=f.buttons()[0];
  f.run();await flush();assert.equal(f.node.status,'failed');assert.equal(f.submitted.length,0);
  assert.strictEqual(f.buttons()[0],button);assert.equal(button.disabled,false);
  f.element.click(button);assert.equal(f.node.loras.length,1);
});

test('Qwen failed model preparation restores removal, while pending preparation keeps it locked',async t=>{
  const f=fixture({ready:false});t.after(f.dispose);await flush();const button=f.buttons()[0];
  let fail;f.api.prepare=()=>new Promise((_,reject)=>{fail=reject;});
  f.run();await flush();assert.equal(button.disabled,true);assert.equal(f.controller.canEdit('q'),false);
  fail(new Error('Synthetic preparation failure'));await flush();
  assert.equal(f.node.status,'failed');assert.equal(button.disabled,false);assert.equal(f.controller.canEdit('q'),true);
  assert.equal(f.submitted.length,0);f.element.click(button);assert.equal(f.node.loras.length,1);
});

test('Qwen stop-generation action unlocks LoRA removal after the cancellation receipt',async t=>{
  const f=fixture();t.after(f.dispose);await flush();f.run();await flush();const button=f.buttons()[0];
  assert.equal(button.disabled,true);f.run();await flush();assert.equal(f.node.status,'canceled');
  assert.equal(button.disabled,false);f.element.click(button);assert.equal(f.node.loras.length,1);
});

test('Qwen Turbo Base selects Turbo · 8 步 and submits without a Viggle adapter',async t=>{
  const models=[{id:'turbo-bf16',ready:true,sampling:'turbo-8'},{id:'qwen-image-2.1-heretic-mlx-8bit',ready:true}];
  const f=fixture({models,turboReady:false,nodeFields:{baseModelId:'turbo-bf16',preset:'viggle-v03-r256',steps:30}});t.after(f.dispose);await flush();
  assert.equal(f.node.preset,'turbo-8');assert.equal(f.node.steps,8);
  const options=f.element.querySelector('[data-qwen21-field="preset"]').innerHTML;
  assert.match(options,/value="turbo-8" selected>Turbo · 8 步/);assert.match(options,/value="viggle-v03-r256" disabled/);
  f.run();await flush();
  assert.equal(f.submitted.length,1,'no adapter preparation is required');
  assert.equal(f.submitted[0].preset,'turbo-8');assert.equal(f.submitted[0].steps,8);assert.equal(f.submitted[0].guidance,1);
  await f.finish('succeeded_no_telegram');
  const change=target=>f.element.listeners.get('change')({target}),input=(key,value)=>({dataset:{qwen21Field:key},value,matches:()=>false});
  change(input('baseModelId','qwen-image-2.1-heretic-mlx-8bit'));
  assert.equal(f.node.preset,'viggle-v03-r256');assert.equal(f.node.steps,6);
  assert.match(f.element.querySelector('[data-qwen21-field="preset"]').innerHTML,/value="turbo-8" disabled/);
  const rejected=input('preset','turbo-8');change(rejected);
  assert.equal(f.node.preset,'viggle-v03-r256');assert.equal(rejected.value,'viggle-v03-r256');
});

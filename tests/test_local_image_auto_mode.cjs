// Portable canvas/controller regression: synthetic graph, DOM and authenticated API ports only.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const read=name=>fs.readFileSync(path.join(__dirname,'../frontend/scripts',name),'utf8');
const plain=value=>JSON.parse(JSON.stringify(value));
const adapterId='e'.repeat(64);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};};

class Element {
  constructor(){this.parts=new Map();this.listeners=new Map();this.dataset={};this.style={setProperty(){}};this.hidden=false;
    const values=new Set();this.classList={toggle:(name,on)=>on?values.add(name):values.delete(name),contains:name=>values.has(name)};}
  querySelector(key){if(!this.parts.has(key))this.parts.set(key,new Element());return this.parts.get(key);}
  querySelectorAll(key){return [this.querySelector(key)];}
  addEventListener(type,listener){this.listeners.set(type,listener);}
  click(attribute,dataset={}){this.listeners.get('click')?.({target:{closest:selector=>selector===`[${attribute}]`?{dataset}:null}});}
}

function fixture(engine,options={}){
  const modelName=engine==='krea2'?'DesktopKrea2Model':'DesktopQwen21Model';
  const controllerName=engine==='krea2'?'DesktopCanvasKrea2':'DesktopCanvasQwen21';
  const context={window:{addEventListener(){},DesktopSelect:{refreshAll(){}}},AbortController,setTimeout,clearTimeout};
  vm.createContext(context);
  vm.runInContext(read(`desktop-${engine}-model.js`),context);
  vm.runInContext(read(`desktop-canvas-${engine}.js`),context);
  const model=context.window[modelName];
  let canvas={nodes:{n:{id:'n',type:engine,...options.node},t:{id:'t',type:'text',text:'a synthetic prompt'}},edges:[{from:'t',to:'n'}]};
  let element=new Element(),saves=0;
  const submitted=[],uploads=[],sources=[],feedback=[];
  const api={catalog:async()=>({models:[]}),status:async()=>{
    await options.statusGate?.promise;
    return{environment_ready:true,source_ready:true,base_ready:true,safety_ready:true,turbo_ready:true,
      models:[{id:model.DEFAULT_MODEL_ID,name:'Synthetic Base',ready:true}],preparation:{status:'idle'}};
  },listLoras:async()=>({loras:options.noAdapter?[]:[{asset_id:adapterId,name:'Krea 2 Identity Edit',file_size:100}]}),
  sourceBlob:async source=>{sources.push(source);await options.sourceGate?.promise;return{source};},
  uploadImage:async(blob,name)=>{uploads.push({source:blob.source,name});await options.uploadGate?.promise;return{upload_token:`token-${uploads.length}`};},
  submit:async request=>{submitted.push(plain(request));return{task_id:engine+'_'+'a'.repeat(32),status:'queued'};},
  job:async()=>({status:'succeeded_no_telegram',result_files:[]}),
  prepare:async()=>{throw new Error('Test must not prepare real resources');},cancel:async()=>({ok:true})};
  function references(){return canvas.edges.filter(edge=>edge.to==='n').flatMap(edge=>{
    const node=canvas.nodes[edge.from];if(!node)return[];
    const items=node.type==='image_group'?node.items||[]:[node];
    if(!['image','image_group','layout','pose'].includes(node.type))return[];
    return items.filter(item=>item.imageData||item.imageUrl||item.layoutExport||item.exportImage).map((item,index)=>({
      id:item.id||`${node.id}-${index}`,sourceNodeId:node.id,name:item.name||node.id,
      imageData:item.imageData||item.layoutExport||item.exportImage,imageUrl:item.imageUrl}));
  });}
  const controller=context.window[controllerName].create({model,api,getCanvas:()=>canvas,
    getNodeState:id=>canvas.nodes[id],getNodeElement:id=>id==='n'?element:null,getImageReferences:references,
    getTextNodes:id=>canvas.edges.filter(edge=>edge.to===id).map(edge=>canvas.nodes[edge.from]).filter(node=>node?.type==='text'),
    materializeText:node=>node.text,saveState:()=>saves++,reportStatus:value=>feedback.push(value),
    addNode(){throw new Error('Unexpected output publication');},connectNodes(){},setImageFromResult(){},applyNodeLayout(){},updateLinkPath(){}});
  const html=controller.nodeHtml(canvas.nodes.n);controller.reconcile();
  return{model,controller,html,submitted,uploads,sources,feedback,
    get canvas(){return canvas;},get node(){return canvas.nodes.n;},get element(){return element;},get saves(){return saves;},
    async loaded(){for(let i=0;i<4;i++)await tick();},
    connect(type='image',id='i',data={imageData:'data:image/png;base64,c3ludGhldGlj'}){
      canvas.nodes[id]={id,type,...data};canvas.edges.push({from:id,to:'n'});controller.graphChanged();
    },disconnect(id='i'){canvas.edges=canvas.edges.filter(edge=>edge.from!==id);controller.connections.removed();},
    replace(next){canvas=next;element=new Element();controller.nodeHtml(canvas.nodes.n);controller.reconcile();},
    click(){element.click(`data-${engine}-run`);},
    async run(){this.click();await this.loaded();},
    dispose(){controller.disposeAll();}};
}

for(const engine of ['krea2','qwen21']){
  const textMode=engine==='krea2'?'standard':'text';
  test(`${engine}: 模式由真实输入边识别，忽略旧模式、输出边和无效边`,async t=>{
    const f=fixture(engine,{node:{mode:'edit'}});t.after(()=>f.dispose());await f.loaded();
    assert.equal(f.model.resolveMode(f.node,f.canvas),textMode);
    const allowed=engine==='krea2'?['image']:['image','image_group','layout','pose'];
    for(const type of allowed){f.connect(type,'empty',{});assert.equal(f.model.resolveMode(f.node,f.canvas),'edit');f.disconnect('empty');}
    f.canvas.nodes.out={id:'out',type:'image'};f.canvas.edges.push({from:'n',to:'out'},{from:'missing',to:'n'});
    f.connect('video','invalid',{});assert.equal(f.model.resolveMode(f.node,f.canvas),textMode);
  });
  test(`${engine}: 工作模式是统一控件的只读自动状态，不再手动选择`,t=>{
    const f=fixture(engine);t.after(()=>f.dispose());
    assert.match(f.html,/工作模式 · 自动识别/);
    assert.match(f.html,new RegExp(`<input[^>]+data-${engine}-mode[^>]+readonly`));
    assert.doesNotMatch(f.html,new RegExp(`data-${engine}-field="mode"`));
  });
  test(`${engine}: 接入/删除图片立即更新模式及编辑区域`,async t=>{
    const f=fixture(engine);t.after(()=>f.dispose());await f.loaded();
    const selector=engine==='krea2'?'[data-krea2-edit-panel]':'[data-qwen21-references]';
    assert.equal(f.node.mode,textMode);f.connect();assert.equal(f.node.mode,'edit');
    assert.equal(f.element.querySelector(selector).hidden,false);
    assert.match(f.element.querySelector(`[data-${engine}-mode]`).value,/图像编辑/);
    if(engine==='krea2')assert.equal(f.node.editAdapterId,adapterId);
    f.disconnect();assert.equal(f.node.mode,textMode);assert.equal(f.element.querySelector(selector).hidden,true);
    assert.match(f.element.querySelector(`[data-${engine}-mode]`).value,/文生图/);
  });
  test(`${engine}: 工作流重载从连线重新识别，不采用保存的手动模式`,async t=>{
    const f=fixture(engine);t.after(()=>f.dispose());await f.loaded();
    f.replace({nodes:{n:{id:'n',type:engine,mode:textMode},i:{id:'i',type:'image'}},edges:[{from:'i',to:'n'}]});
    assert.equal(f.node.mode,'edit');f.disconnect();assert.equal(f.node.mode,textMode);
    f.node.mode='edit';f.controller.reconcile();assert.equal(f.node.mode,textMode);
  });
  test(`${engine}: 文本连线自动提交文生图且不上传任何参考图`,async t=>{
    const f=fixture(engine,{node:{mode:'edit'}});t.after(()=>f.dispose());await f.loaded();await f.run();
    assert.equal(f.submitted.length,1);assert.equal(f.submitted[0].mode,textMode);
    assert.equal(f.submitted[0].prompt,'a synthetic prompt');assert.equal(f.uploads.length,0);
    if(engine==='krea2'){
      assert.equal(f.submitted[0].init_image_upload_token,'');assert.equal(f.submitted[0].edit_image_upload_token,'');
      assert.equal(f.submitted[0].edit_adapter_asset_id,'');
    }else{assert.deepEqual(f.submitted[0].reference_upload_tokens,[]);assert.equal(f.submitted[0].preset,'viggle-v03-r256');}
  });
  test(`${engine}: 图像连线自动提交编辑参数而不是文生图/重绘参数`,async t=>{
    const f=fixture(engine);t.after(()=>f.dispose());await f.loaded();f.connect();await f.run();
    assert.equal(f.submitted.length,1);assert.equal(f.submitted[0].mode,'edit');assert.equal(f.uploads.length,1);
    if(engine==='krea2'){
      assert.equal(f.submitted[0].init_image_upload_token,'');assert.equal(f.submitted[0].edit_image_upload_token,'token-1');
      assert.equal(f.submitted[0].edit_adapter_asset_id,adapterId);assert.equal(f.submitted[0].reference_strength,4);
    }else assert.deepEqual(f.submitted[0].reference_upload_tokens,['token-1']);
  });
  test(`${engine}: 空图片节点识别为编辑，禁止静默退回文生图`,async t=>{
    const f=fixture(engine);t.after(()=>f.dispose());await f.loaded();f.connect('image','i',{});await f.run();
    assert.equal(f.node.mode,'edit');assert.equal(f.submitted.length,0);assert.equal(f.uploads.length,0);
    assert.match(f.feedback.at(-1).message,/尚无可读取内容/);
  });
  test(`${engine}: 上传期间连线变化不改变已经快照的提交模式`,async t=>{
    const gate=deferred(),f=fixture(engine,{sourceGate:gate});t.after(()=>f.dispose());await f.loaded();f.connect();
    f.click();await f.loaded();assert.equal(f.sources.length,1);f.disconnect();assert.equal(f.node.mode,textMode);
    gate.resolve();await f.loaded();assert.equal(f.submitted.length,1);assert.equal(f.submitted[0].mode,'edit');
    if(engine==='krea2')assert.equal(f.submitted[0].edit_image_upload_token,'token-1');
    else assert.deepEqual(f.submitted[0].reference_upload_tokens,['token-1']);
  });
  test(`${engine}: 上传期间工作流替换后旧会话不能提交`,async t=>{
    const gate=deferred(),f=fixture(engine,{sourceGate:gate});t.after(()=>f.dispose());await f.loaded();f.connect();
    f.click();await f.loaded();f.replace({nodes:{n:{id:'n',type:engine}},edges:[]});gate.resolve();await f.loaded();
    assert.equal(f.submitted.length,0);assert.equal(f.node.mode,textMode);
  });
  test(`${engine}: 异步加载资源期间重复点击只创建一个任务`,async t=>{
    const gate=deferred(),f=fixture(engine,{statusGate:gate});t.after(()=>f.dispose());
    f.click();f.click();gate.resolve();await f.loaded();assert.equal(f.submitted.length,1);
  });
  test(`${engine}: 上传期间参数和 LoRA 强度也属于同一提交快照`,async t=>{
    const gate=deferred(),f=fixture(engine,{sourceGate:gate,node:{steps:12,seed:'123',loras:[{assetId:'a'.repeat(64),scale:.8}]}});
    t.after(()=>f.dispose());await f.loaded();f.connect();f.click();await f.loaded();
    f.node.steps=20;f.node.seed='456';f.node.loras[0].scale=1.4;f.disconnect();gate.resolve();await f.loaded();
    assert.equal(f.submitted[0].mode,'edit');assert.equal(f.submitted[0].steps,12);assert.equal(f.submitted[0].seed,'123');assert.equal(f.submitted[0].loras[0].scale,.8);
  });
}

test('Krea: 自动切换保留四个已选普通 LoRA，超出编辑上限明确提示而不删数据',async t=>{
  const loras=['a','b','c','d'].map(letter=>({assetId:letter.repeat(64),scale:.8}));
  const f=fixture('krea2',{node:{loras}});t.after(()=>f.dispose());await f.loaded();f.connect();
  assert.deepEqual(plain(f.node.loras),loras);await f.run();assert.equal(f.submitted.length,0);
  assert.match(f.feedback.at(-1).message,/最多 3 个普通 LoRA/);f.disconnect();assert.deepEqual(plain(f.node.loras),loras);
  await f.run();assert.equal(f.submitted[0].loras.length,4);
});
test('Krea: 编辑适配器不重复叠加，断开图片后原普通 LoRA 选择仍可恢复',async t=>{
  const f=fixture('krea2',{node:{loras:[{assetId:adapterId,scale:.8},{assetId:'a'.repeat(64),scale:1}]}});
  t.after(()=>f.dispose());await f.loaded();f.connect();await f.run();
  assert.equal(f.submitted[0].edit_adapter_asset_id,adapterId);assert.deepEqual(f.submitted[0].loras,[{asset_id:'a'.repeat(64),scale:1}]);
  assert.equal(f.node.loras.length,2);f.disconnect();await f.run();assert.equal(f.submitted[1].loras.length,2);
});
test('Krea: 自动编辑缺少适配器时给出明确提示，不准备/提交任务',async t=>{
  const f=fixture('krea2',{noAdapter:true});t.after(()=>f.dispose());await f.loaded();f.connect();await f.run();
  assert.equal(f.submitted.length,0);assert.match(f.feedback.at(-1).message,/Identity Edit LoRA/);
});
test('Krea: 隐去编辑适配器后，普通 LoRA 的移除/强度索引仍指向原始选择',async t=>{
  const f=fixture('krea2',{node:{loras:[{assetId:adapterId,scale:.8},{assetId:'a'.repeat(64),scale:1},{assetId:'b'.repeat(64),scale:.5}]}});
  t.after(()=>f.dispose());await f.loaded();f.connect();
  const rows=f.element.querySelector('[data-krea2-lora-list]').innerHTML;
  assert.doesNotMatch(rows,/data-krea2-lora-row="0"/);assert.match(rows,/data-krea2-lora-scale="1"/);
  f.element.click('data-krea2-lora-remove',{krea2LoraRemove:'1'});
  assert.deepEqual(f.node.loras.map(x=>x.assetId),[adapterId,'b'.repeat(64)]);
  f.disconnect();assert.match(f.element.querySelector('[data-krea2-lora-list]').innerHTML,/data-krea2-lora-row="0"/);
});
test('Qwen: 自动编辑保留用户参考图顺序和推理预设',async t=>{
  const f=fixture('qwen21',{node:{preset:'standard',referenceOrder:['b','a'],steps:30,guidance:4.5}});
  t.after(()=>f.dispose());await f.loaded();f.connect('image','a',{imageData:'image-a'});f.connect('image','b',{imageData:'image-b'});await f.run();
  assert.deepEqual(f.uploads.map(x=>x.source),['image-b','image-a']);assert.equal(f.submitted[0].mode,'edit');
  assert.equal(f.submitted[0].preset,'standard');assert.equal(f.submitted[0].steps,30);assert.equal(f.submitted[0].guidance,4.5);
  f.disconnect('a');f.disconnect('b');assert.deepEqual(plain(f.node.referenceOrder),['b','a']);
});
test('Qwen: 连上空图片和有效参考图时不得跳过空节点',async t=>{
  const f=fixture('qwen21');t.after(()=>f.dispose());await f.loaded();f.connect();f.connect('image','empty',{});await f.run();
  assert.equal(f.node.mode,'edit');assert.equal(f.submitted.length,0);assert.match(f.feedback.at(-1).message,/尚无可读取内容/);
});
test('Qwen: 自动编辑继续遵守标准 10 张/Viggle 3 张的参考上限',async t=>{
  for(const [preset,count] of [['standard',11],['viggle-v03-r256',4]]){
    const f=fixture('qwen21',{node:{preset}});t.after(()=>f.dispose());await f.loaded();
    for(let i=0;i<count;i++)f.connect('image',String(i),{imageData:'synthetic-'+i});await f.run();
    assert.equal(f.submitted.length,0);assert.match(f.feedback.at(-1).message,/张参考图/);
  }
});

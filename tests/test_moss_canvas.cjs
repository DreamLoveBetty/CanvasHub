const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {plain,textNode,setup,mount,receipt}=require('./moss_frontend_fixture.cjs');
const {hasCacheKey}=require('./asset_keys.cjs');
const frontend=path.join(__dirname,'../frontend');

test('文本节点首次连线默认指定全局，已有全局源时不静默覆盖',async()=>{
  const t=await mount(setup({text:[textNode('a','一'),textNode('b','二')]}));
  t.connectNodes('a','m');
  assert.deepEqual(plain(t.moss.promptSource),{kind:'text_node',nodeId:'a'});
  t.connectNodes('b','m');
  assert.equal(t.moss.promptSource.nodeId,'a');
  assert.deepEqual(plain(t.canvas.edges.map(edge=>edge.from)),['a']);assert.equal(t.log.notify.length,1);
});

test('内部区域绑定建边不触发全局默认赋值，解绑一处不删共享边',async()=>{
  const t=await mount(setup({node:{mode:'text',freeDraft:{items:[{id:'o',label:'object',caption:'',bbox:[0,0,9,9]},{id:'p',label:'object',caption:'',bbox:[0,0,9,9]}]}},text:[textNode('a','一')]}));
  t.controller.bindTextSource('m','o','caption','a');
  assert.equal(t.moss.promptSource.kind,'inline');assert.equal(t.canvas.edges.length,1);
  t.controller.bindTextSource('m','p','caption','a');assert.equal(t.canvas.edges.length,1);
  t.controller.bindTextSource('m','o','caption',null);
  assert.equal(t.moss.freeDraft.items[0].caption,'一');assert.equal(t.moss.freeDraft.items[0].captionSource.kind,'inline');
  assert.equal(t.canvas.edges.length,1);
  t.controller.bindTextSource('m','p','caption',null);assert.equal(t.canvas.edges.length,0);
  assert.equal(t.log.confirm.length,0);
});

test('建边失败回滚，不留假绑定',async()=>{
  const t=await mount(setup({text:[textNode('a','一')]}));t.setFail(true);
  assert.throws(()=>t.controller.bindTextSource('m','global','prompt','a'),/连接失败/);
  assert.equal(t.moss.promptSource.kind,'inline');
  assert.throws(()=>t.controller.bindTextSource('m','nope','caption','a'),/目标不存在/);
});

test('手动删边确认后解绑并冻结内容，取消则恢复边',async()=>{
  const t=await mount(setup({text:[textNode('a','一')]}));
  t.connectNodes('a','m');
  t.setConfirm(false);t.removeEdges(['e1']);
  assert.equal(t.moss.promptSource.nodeId,'a');assert.equal(t.canvas.edges.length,1);assert.equal(t.log.confirm.length,1);
  t.setConfirm(true);t.removeEdges([t.canvas.edges[0].id]);
  assert.equal(t.moss.promptSource.kind,'inline');assert.equal(t.moss.prompt,'一');assert.equal(t.canvas.edges.length,0);
});

test('删除源节点保留失效引用并阻止提交，不静默用旧词',async()=>{
  const t=await mount(setup({text:[textNode('a','一')]}));t.connectNodes('a','m');
  const edge=t.canvas.edges[0];delete t.canvas.nodes.a;t.canvas.edges=[];t.controller.connections.removed([edge]);
  assert.equal(t.moss.promptSource.nodeId,'a');assert.equal(t.log.confirm.length,0);
  await t.controller.run('m');await t.settle();
  assert.equal(t.log.submits.length,0);assert.equal(t.moss.status,'failed');
});

test('连续点击只提交一次，默认无 LoRA',async()=>{
  const t=await mount(setup());
  const first=t.controller.run('m'),second=t.controller.run('m');await Promise.all([first,second]);
  assert.equal(t.log.submits.length,1);assert.equal(t.moss.jobId,'moss_'+'a'.repeat(32));assert.deepEqual(plain(t.moss.loras),[]);
});

test('未就绪时进入模型工具，不隐式准备',async()=>{
  const t=await mount(setup({ready:false}));await t.controller.run('m');
  assert.equal(t.log.tools,true);assert.equal(t.log.submits.length,0);
});

test('预算未通过不提交',async()=>{
  const t=await mount(setup({api:{compile:async(_n,input)=>receipt(input.inputFingerprint,'fp',{valid:false,reason:'超过上限'})}}));
  await t.controller.run('m');assert.equal(t.log.submits.length,0);assert.equal(t.moss.status,'failed');
});

test('旧编译 receipt 不算数：输入中途改变则不提交',async()=>{
  const t=setup({api:{compile:async(_n,input)=>{t.moss.prompt='狗';return receipt(input.inputFingerprint);}}});await mount(t);
  await t.controller.run('m');
  assert.equal(t.log.submits.length,0);assert.equal(t.moss.status,'failed');
});

test('模型指纹不符的 receipt 不复用，提交前重新编译',async()=>{
  let model='old';
  const t=setup({api:{compile:async(_n,input)=>{t.log.compiles++;return receipt(input.inputFingerprint,model);}}});await mount(t);
  t.timers.splice(0).forEach(fn=>fn());await t.settle();assert.equal(t.log.compiles,1);
  model='fp';await t.controller.run('m');
  assert.equal(t.log.compiles,2);assert.equal(t.log.submits.length,1);
});

test('晚到结果不写入已删除节点，结果只发整图且不重复造图',async()=>{
  const task={task_id:'moss_'+'a'.repeat(32),status:'succeeded_no_telegram',image_paths:['/a.png','/a_p01.png'],result_files:['a.png','a_p01.png'],result_file:'a.png'};
  let answer;const t=setup({node:{jobId:task.task_id,status:'running'},api:{job:()=>new Promise(resolve=>{answer=resolve;})}});await mount(t);
  t.controller.dispose('m');answer(task);await t.settle();assert.equal(t.log.images.length,0);
  const u=setup({node:{jobId:task.task_id,status:'running'},api:{job:async()=>task}});await mount(u);
  assert.equal(u.log.images.length,1);assert.deepEqual(u.log.images[0][1].imagePaths,['/a.png']);assert.equal(u.moss.resultJobId,task.task_id);
  const images=Object.values(u.canvas.nodes).filter(node=>node.type==='image').length;
  u.controller.reconcile();await u.settle();
  assert.equal(Object.values(u.canvas.nodes).filter(node=>node.type==='image').length,images);
});

test('Base：选项来自已绑定列表，回执按所选 Base 的指纹校验，失效 Base 不能生成',async()=>{
  const models=[{model_id:'moss-image-sft-mflux-bf16',label:'官方',ready:true,fingerprint:'fp'},{model_id:'tune',label:'微调',ready:true,fingerprint:'tune-fp'},{model_id:'gone',label:'失效',ready:false,reason:'绑定文件丢失：x',fingerprint:'g'}];
  const status=async()=>({ready:true,reasons:[],model:models[0],models,preparation:{status:'idle'}});
  const t=await mount(setup({node:{baseModelId:'tune'},api:{status,compile:async(_n,input)=>receipt(input.inputFingerprint,'tune-fp')}}));
  const select=t.elements.m.querySelector('[data-moss-field="baseModelId"]');
  for(const label of ['官方','微调','失效 · 未绑定'])assert.ok(select.innerHTML.includes(label));
  assert.equal(t.elements.m.querySelector('[data-moss-budget]').textContent,'');
  t.moss.baseModelId='gone';t.controller.reconcile();await t.settle();
  assert.equal(t.elements.m.querySelector('[data-moss-budget]').textContent,'绑定文件丢失：x');
});

test('高度：普通固定 500，展开测量去重，只动底边',async()=>{
  const t=await mount(setup());assert.equal(t.moss.height,500);assert.equal(t.log.applied,0);
  t.moss.mode='layout';t.elements.m.querySelector('[data-moss-body]').scrollHeight=800;t.controller.reconcile();
  assert.equal(t.moss.height,882);assert.equal(t.log.applied,1);assert.equal(t.moss.y,0);
  t.controller.reconcile();assert.equal(t.log.applied,1);
  t.moss.mode='text';t.controller.reconcile();assert.equal(t.moss.height,500);assert.equal(t.log.applied,2,'collapsing must reach the DOM');
});

test('Layout 未开放时明确标记且不能提交',async()=>{
  const t=await mount(setup({node:{mode:'layout'}}));
  assert.match(t.controller.nodeHtml(t.moss),/自由 Layout · 尚未开放/);
  await t.controller.run('m');assert.equal(t.log.submits.length,0);
});

test('updateDraft 校验修订号并同步依赖边',async()=>{
  const t=await mount(setup({text:[textNode('a','一')],node:{freeDraft:{items:[{id:'o',label:'object',caption:'',bbox:[0,0,9,9]}]}}}));
  t.controller.bindTextSource('m','o','caption','a');const revision=t.moss.draftRevision;
  assert.throws(()=>t.controller.updateDraft('m','layout',{items:[]},revision-1),/草稿已变化/);
  t.controller.updateDraft('m','layout',{items:[]},revision);
  assert.equal(t.canvas.edges.length,0);assert.equal(t.moss.draftRevision,revision+1);
});

test('宿主装配：加载顺序、任务注册、LoRA 引擎与 CSS 隔离',()=>{
  const html=fs.readFileSync(path.join(frontend,'desktop.html'),'utf8');
  const order=['desktop-moss-model.js','desktop-moss-api.js','desktop-moss-tools.js','desktop-canvas-moss.js','desktop-canvas.js'].map(name=>html.indexOf('scripts/'+name));
  assert.ok(order.every(index=>index>0));assert.deepEqual([...order].sort((a,b)=>a-b),order);
  for(const name of ['scripts/desktop-canvas-moss.js','styles/desktop-moss.css','styles/desktop-moss-geometry.css'])assert.ok(hasCacheKey(html,name));
  const host=fs.readFileSync(path.join(frontend,'scripts/desktop-canvas.js'),'utf8');
  assert.match(host,/taskRegistry\.register\('moss'/);assert.match(host,/canvasMoss\.connections/);
  assert.match(fs.readFileSync(path.join(frontend,'scripts/desktop-canvas-lora.js'),'utf8'),/moss:'MOSS'/);
  for(const name of ['desktop-moss.css','desktop-moss-geometry.css'])for(const rule of fs.readFileSync(path.join(frontend,'styles',name),'utf8').split('\n').filter(line=>line.includes('{')))assert.match(rule,/^\.desk-app /);
});

const {test}=require('node:test');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const {load,plain}=require('./moss_frontend_fixture.cjs');
const M=load(['desktop-moss-model.js']).window.DesktopMossModel;
const asset=c=>c.repeat(64);

test('普通节点 720×500，UI 尺寸与输出尺寸分离',()=>{
  const node=M.normalize({type:'moss',imageWidth:1536,imageHeight:1024});
  assert.deepEqual([node.width,node.height,node.imageWidth,node.imageHeight],[720,500,1536,1024]);
  assert.equal(node.mode,'text');assert.equal(node.preset,'turbo');assert.equal(node.baseModelId,M.DEFAULT_MODEL_ID);
  assert.equal(node.schemaVersion,1);assert.deepEqual(plain(node.loras),[]);assert.equal(node.telegramEnabled,false);
});

test('布局模式保留测量高度，切回普通仍由控制器收回且两份草稿都在',()=>{
  const node=M.normalize({type:'moss',mode:'layout',height:900,freeDraft:{items:[{id:'a',label:'object',caption:'猫',bbox:[0,0,9,9]}]}});
  assert.equal(node.height,900);
  node.gridDraft.panels[0].caption='远山';node.mode='text';M.normalize(node);
  assert.equal(node.height,900,'height stays measured by the controller, which needs to see it change');assert.equal(node.freeDraft.items[0].caption,'猫');assert.equal(node.gridDraft.panels[0].caption,'远山');
});

test('输出尺寸按 16 对齐并受总像素限制',()=>{
  assert.equal(M.normalize({type:'moss',imageWidth:1000,imageHeight:1000}).imageWidth,1008);
  const over=M.normalize({type:'moss',imageWidth:2048,imageHeight:2048});
  assert.deepEqual([over.imageWidth,over.imageHeight],[1024,1024]);
});

test('Seed、LoRA 与任务 ID 归一',()=>{
  const node=M.normalize({type:'moss',seed:'99999999999',jobId:'qwen21_'+'a'.repeat(32),
    loras:[{assetId:asset('a'),scale:99},{assetId:asset('a'),scale:1},{assetId:'bad'},...['b','c','d','e'].map(c=>({assetId:asset(c),scale:1}))]});
  assert.equal(node.seed,'');assert.equal(node.jobId,'');assert.equal(node.loras.length,4);assert.equal(node.loras[0].scale,20);
  assert.equal(M.normalize({type:'moss',seed:4294967295}).seed,'4294967295');
  assert.equal(M.normalize({type:'moss',jobId:'moss_'+'a'.repeat(32)}).jobId,'moss_'+'a'.repeat(32));
});

test('未知 schema 原样保留并阻止执行',()=>{
  const raw={type:'moss',schemaVersion:2,mode:'hologram',prompt:7,futureField:{a:1}};
  const node=M.normalize({...raw});
  assert.equal(node.mode,'hologram');assert.equal(node.prompt,7);assert.deepEqual(plain(node.futureField),{a:1});
  assert.equal(M.unsupported(node),true);
  assert.deepEqual(plain(M.resolveTextSources(node,{}).issues.map(item=>item.reason)),['schema']);
});

test('连接只接受文本，输出只到图片节点',()=>{
  const moss={type:'moss'};
  assert.equal(M.policy({type:'text'},moss).inputRole,'prompt');
  for(const type of ['image','image_group','pose','layout','moss'])assert.equal(M.policy({type},moss),null);
  assert.equal(M.policy(moss,{type:'image'}).outputRole,'image');
  assert.equal(M.policy(moss,{type:'text'}),null);
});

test('sha256 与服务端一致（含中文与分块边界）',()=>{
  for(const value of ['','abc','清晨窗边🌅','x'.repeat(55),'x'.repeat(56),'y'.repeat(64),'中'.repeat(1000)])
    assert.equal(M.sha256(value),crypto.createHash('sha256').update(value,'utf8').digest('hex'));
});

test('菜单项',()=>{assert.equal(M.MENU_ITEM.title,'MOSS · 本地生成 / Layout');assert.equal(M.MENU_ITEM.type,'moss');});

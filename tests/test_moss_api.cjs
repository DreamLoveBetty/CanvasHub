const {test}=require('node:test');
const assert=require('node:assert/strict');
const {load,plain,textNode,ports}=require('./moss_frontend_fixture.cjs');
const calls=[];
const api={json:async(path,options={})=>{calls.push({path,method:options.method||'GET',body:options.body?JSON.parse(options.body):null});return api.reply||{ok:true};},
  request:async(path,options)=>{calls.push({path,options});return{ok:true,json:async()=>({ok:true})};}};
class Blob{constructor(size){this.size=size;}}
const context=load(['desktop-moss-model.js','desktop-moss-api.js'],{api,Blob,DesktopApi:{getStatus:async()=>({})},DesktopTasks:{}});
const M=context.window.DesktopMossModel,A=context.window.DesktopMossAPI;
const ref=nodeId=>({kind:'text_node',nodeId});

test('生成请求 snake_case，普通模式不带草稿',()=>{
  const node=M.normalize({type:'moss',prompt:'猫',imageWidth:768,imageHeight:512,seed:'5',telegramEnabled:true,loras:[{assetId:'a'.repeat(64),scale:.7}],drawGrid:true});
  const body=plain(A.jobRequest(node,M.resolveTextSources(node,ports())));
  assert.deepEqual(Object.keys(body).sort(),['base_model_id','draw_grid','height','input_fingerprint','loras','mode','preset','prompt','seed','split_panels','telegram_enabled','text_sources','width']);
  assert.equal(body.draw_grid,false);assert.equal(body.split_panels,false);assert.equal(body.seed,5);
  assert.deepEqual(body.loras,[{asset_id:'a'.repeat(64),scale:.7}]);
});

test('空 Seed 不发送，让服务端解析一次',()=>{
  const node=M.normalize({type:'moss',prompt:'猫'});
  assert.equal('seed' in A.jobRequest(node,M.resolveTextSources(node,ports())),false);
});

test('分镜请求带来源 trace 与草稿，不发 Source、别名外的画布信息',()=>{
  const node=M.normalize({type:'moss',mode:'storyboard',gridDraft:{rows:1,cols:3,margin:8,gutter:8,panels:[{id:'a',captionSource:ref('n')},{id:'b',caption:'二'},{id:'c',caption:'三'}]}});
  const body=plain(A.jobRequest(node,M.resolveTextSources(node,ports(textNode('n','一')))));
  assert.equal(body.split_panels,true);
  assert.deepEqual(body.text_sources,[{source_node_id:'n',target_id:'a',field:'caption',content_hash:M.sha256('一'),source_alias:'n'}]);
  assert.doesNotMatch(JSON.stringify(body),/captionSource|freeDraft|gridDraft|\/Users/);
});

test('编译走鉴权 API，receipt 转 camelCase',async()=>{
  api.reply={ok:true,kind:'compiled',compiled:{prompt:'p',prompt_hash:'h',geometry_spec:null,geometry_hash:null,warnings:[]},token_budget:{checked:true,valid:true,prompt_tokens:3,negative_tokens:1,max_tokens:4096,reason:null},input_fingerprint:'moss:x',model_fingerprint:'f'};
  const node=M.normalize({type:'moss',prompt:'猫'}),input=M.resolveTextSources(node,ports());
  const receipt=await A.compile(node,input);
  assert.equal(calls.at(-1).path,'/api/moss/layout-compile');assert.equal(calls.at(-1).body.input_fingerprint,input.inputFingerprint);
  assert.equal(receipt.tokenBudget.promptTokens,3);assert.equal(receipt.modelFingerprint,'f');assert.equal(receipt.compiled.promptHash,'h');
});

test('导入发原文字符串，receipt 不伪造预算',async()=>{
  api.reply={ok:true,kind:'import_draft',draft:{mode:'text'},requires_source_resolution:true,input_fingerprint:null};
  const raw='{"a":1,"a":2}';
  const receipt=await A.importDraft(raw);
  assert.deepEqual(plain(calls.at(-1).body),{draft_json:raw});
  assert.equal(receipt.kind,'import_draft');assert.equal(receipt.requiresSourceResolution,true);assert.equal(receipt.tokenBudget,undefined);
});

test('准备、绑定、取消、LoRA 路径与字段',async()=>{
  api.reply=null;
  await A.prepare();assert.deepEqual(plain(calls.at(-1).body),{});
  await A.bindModel('/m');assert.equal(calls.at(-1).path,'/api/moss/model-bind');assert.deepEqual(plain(calls.at(-1).body),{source_path:'/m'});
  await A.cancel('t');assert.deepEqual(plain(calls.at(-1).body),{task_id:'t'});
  await A.deleteLora('x');assert.deepEqual(plain(calls.at(-1).body),{asset_id:'x'});
  const file=new Blob(4);file.name='a b.safetensors';await A.importLora(file);
  assert.equal(calls.at(-1).path,'/api/moss/lora-import?name=a%20b.safetensors');assert.equal(calls.at(-1).options.body,file);
  await assert.rejects(()=>A.importLora(new Blob(0)),/2 GiB/);
});

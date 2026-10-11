const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');
const scripts=path.join(__dirname,'../frontend/scripts');
const frontend=path.join(__dirname,'../frontend');
const read=name=>fs.readFileSync(path.join(scripts,name),'utf8');
const context={window:{}};
vm.runInNewContext(read('desktop-cyimg-model.js'),context);
const model=context.window.DesktopCyimgModel;

test('绘栾图像和视频是独立 typed Canvas 节点',()=>{
  assert.deepEqual(Array.from(model.TYPES),['cyimg_image','cyimg_video']);
  assert.equal(model.MENU_ITEMS.length,2);
  for(const type of model.TYPES){
    const node=model.normalize({id:'test',type,modelId:'',parameters:null});
    assert.ok(node.width>=600);assert.ok(node.height>=400);
    assert.deepEqual(Object.keys(node.parameters),[]);
  }
});
test('绘栾节点仅展示模型参数，提示词与素材只从画布连接读取',()=>{
  const sandbox={window:{addEventListener(){}}};
  vm.runInNewContext(read('desktop-canvas-cyimg.js'),sandbox);
  const controller=sandbox.window.DesktopCanvasCyimg.create({model});
  for(const type of model.TYPES){
    const html=controller.nodeHtml({id:'cyimg-test',type,parameters:{}});
    assert.doesNotMatch(html,/<textarea|type="file"|data-cyimg-prompt|data-cyimg-file/);
    assert.match(html,/data-cyimg-source-hint/);
    assert.match(html,/class="desk-generation-action desk-cyimg__run"/);
  }
  const source=read('desktop-canvas-cyimg.js');
  assert.match(source,/getTextNodes\(s\.id\)\.map\(node=>materializeText\(node\)\)/);
  assert.doesNotMatch(source,/s\.node\.prompt|s\.files|data-cyimg-file/);
});
test('连线只允许正确的素材和结果类型',()=>{
  for(const source of ['text','image','image_group'])for(const target of model.TYPES)
    assert.ok(model.policy({type:source},{type:target}));
  assert.ok(model.policy({type:'video'},{type:'cyimg_video'}));
  assert.ok(model.policy({type:'audio'},{type:'cyimg_video'}));
  assert.ok(model.policy({type:'cyimg_image'},{type:'image'}));
  assert.ok(model.policy({type:'cyimg_video'},{type:'video'}));
  for(const [source,target] of [['video','cyimg_image'],['cyimg_image','video'],['cyimg_video','image'],['topaz','cyimg_video']])
    assert.equal(model.policy({type:source},{type:target}),null);
});
test('认证 API 适配不携带 Key；桌面资源顺序和缓存版本已更新',async()=>{
  const calls=[];
  const api={json:async (url,options)=>{calls.push([url,options]);return{ok:true}},
    request:async()=>({ok:true,json:async()=>({upload_token:'tok'})}),blob:async()=>new Blob(['test'])};
  const sandbox={window:{location:{href:'http://localhost:18463/desktop.html',origin:'http://localhost:18463'},
    DesktopTasks:{createClient:()=>({submit(){},progress(){},cancel(){},result(){}})}},
    location:{href:'http://localhost:18463/desktop.html',origin:'http://localhost:18463'},
    DesktopApi:{getStatus:async()=>({}),importImageUrl:async()=>({blob:new Blob(['test'])})},
    DesktopTasks:{createClient:()=>({submit(){},progress(){},cancel(){},result(){}})},api,URL,Blob};
  vm.runInNewContext(read('desktop-cyimg-api.js'),sandbox);
  await sandbox.window.DesktopCyimgAPI.catalog();
  await sandbox.window.DesktopCyimgAPI.submit({kind:'image',model_id:'synthetic',prompt:'test'});
  assert.equal(calls[0][0],'/api/cyimg/catalog');
  assert.equal(calls[1][0],'/api/cyimg/submit');
  assert.doesNotMatch(JSON.stringify(calls),/api_key|X-API-Key|secret/i);
  const html=fs.readFileSync(path.join(frontend,'desktop.html'),'utf8');
  const order=['desktop-api.js','desktop-cyimg-model.js','desktop-cyimg-api.js','desktop-canvas-cyimg.js','desktop-canvas.js'];
  for(let i=1;i<order.length;i++)assert.ok(html.indexOf(order[i-1])<html.indexOf(order[i]));
  for(const name of ['styles/desktop-cyimg.css','scripts/desktop-cyimg-model.js','scripts/desktop-canvas-cyimg.js','scripts/desktop-cyimg-api.js','scripts/desktop-settings.js','styles/desktop-controls.css'])
    assert.ok(hasCacheKey(html,name),name);
  const cyimgCss=fs.readFileSync(path.join(frontend,'styles/desktop-cyimg.css'),'utf8');
  assert.match(cyimgCss,/desk-cyimg__fields\{[^}]*overflow:visible/);
  assert.match(cyimgCss,/desk-node--cyimg:has\(\.desk-select-shell\.is-open\)/);
  assert.match(read('desktop-settings.js'),/desktop:cyimg-settings-updated/);
  assert.match(read('desktop-canvas-cyimg.js'),/addEventListener\('desktop:cyimg-settings-updated'/);
});

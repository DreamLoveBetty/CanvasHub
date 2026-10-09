const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const frontend=path.join(__dirname,'../frontend');
const read=name=>fs.readFileSync(path.join(frontend,'scripts',name),'utf8');
const context={window:{}};
vm.runInNewContext(read('desktop-qwen21-model.js'),context);
const M=context.window.DesktopQwen21Model;

test('独立 Qwen 2.1 节点持久化 Base、预设、多 LoRA 和参考图顺序',()=>{
  const node=M.normalize({id:'qwen21-test',type:'qwen21',preset:'viggle-8',steps:30,guidance:5,mode:'edit',
    baseModelId:'community-v1',referenceOrder:['image-b','image-a','image-b'],
    loras:['a','b','c','d','e'].map(x=>({assetId:x.repeat(64),scale:1}))});
  assert.equal(node.width,720);assert.equal(node.height,500);
  assert.equal(node.baseModelId,'community-v1');assert.equal(node.steps,30);assert.equal(node.guidance,1);
  assert.equal(node.preset,M.DEFAULT_PRESET);
  assert.equal(node.loras.length,4);assert.deepEqual(Array.from(node.referenceOrder),['image-b','image-a']);
  const standard=M.normalize({type:'qwen21',preset:'standard',steps:31,guidance:4.5});
  assert.equal(standard.steps,31);assert.equal(standard.guidance,4.5);
  assert.equal(M.normalize({type:'qwen21'}).baseModelId,M.DEFAULT_MODEL_ID);
});

test('加速 LoRA 选择与步数解耦，往返保存保留自定义步数',()=>{
  for(const preset of ['viggle-v021-r256','viggle-v03-r256','viggle-v021-r128']){
    for(const steps of [5,6,8,10,30,60]){
      const node=M.normalize({type:'qwen21',preset,steps});
      assert.equal(M.normalize(JSON.parse(JSON.stringify(node))).steps,steps);
      assert.equal(node.preset,preset);
    }
  }
  assert.equal(M.normalize({type:'qwen21',preset:'viggle-8'}).steps,8);
  assert.equal(M.normalize({type:'qwen21'}).preset,M.DEFAULT_PRESET);
  assert.equal(M.normalize({type:'qwen21',steps:3}).steps,5);
  const source=read('desktop-canvas-qwen21.js');
  assert.doesNotMatch(source,/\['steps','guidance'\]\.includes/);
  assert.match(source,/turbo_adapters\?\.\[node\.preset\]/);
});

test('画幅联动尺寸满足 Qwen 32 倍数且重载不会将舍入画幅变为自定义',()=>{
  for(const ratio of M.ASPECT_RATIOS){
    const dims=M.dimensionsForRatio(ratio);
    assert.equal(dims.width%32,0);assert.equal(dims.height%32,0);
    assert.equal(M.ratioFromDimensions(dims.width,dims.height),ratio);
    const node=M.normalize({type:'qwen21',ratio});assert.equal(node.ratio,ratio);
    assert.equal(node.imageWidth,dims.width);assert.equal(node.imageHeight,dims.height);
  }
  assert.equal(M.dimensionsForRatio('custom'),null);
  assert.equal(M.ratioFromDimensions(832,832),'1:1');
});

test('文本、多图、分组参考输入和图片输出的连接契约',()=>{
  for(const type of ['text','image','image_group','layout','pose']){
    assert.equal(M.policy({type},{type:'qwen21'}).single,false);
  }
  assert.ok(M.policy({type:'qwen21'},{type:'image'}));
  for(const type of ['audio','video','music','krea2'])assert.equal(M.policy({type},{type:'qwen21'}),null);
});

test('新建结果以实际外框定位到节点右方，按图片最终高度堆叠',()=>{
  const source={x:200,y:100,width:720,height:500};
  const first=M.outputPosition(source);
  assert.deepEqual({...first},{x:1020,y:100});
  const portrait={...first,width:640,height:960};
  const next=M.outputPosition(source,portrait);
  assert.deepEqual({...next},{x:1020,y:1100});
  assert.ok(first.x>source.x+source.width);
  assert.ok(next.y>portrait.y+portrait.height);
  const controller=read('desktop-canvas-qwen21.js');
  assert.match(controller,/created\.has\(edge\.to\)&&getNodeState\(edge\.to\)===image/);
  assert.match(controller,/applyNodeLayout\(edge\.to\);previous=image/);
});

test('节点使用标准控件、两行参数区，不暴露模型路径或另设准备按钮',()=>{
  const sandbox={window:{addEventListener(){}},AbortController};
  vm.runInNewContext(read('desktop-canvas-qwen21.js'),sandbox);
  const controller=sandbox.window.DesktopCanvasQwen21.create({model:M});
  const html=controller.nodeHtml({id:'qwen21-test',type:'qwen21'});
  for(const token of ['工作模式','推理 / 加速 LoRA','Base 权重模型','LoRA 模型','Qwen-Image-2.1-Heretic-mlx-8bit',
    'data-qwen21-field="ratio"','desk-number','desk-switch','desk-input-footer','data-qwen21-lora-add','data-qwen21-progress'])assert.ok(html.includes(token));
  assert.doesNotMatch(html,/<textarea|导入.safetensors|准备模型|data-qwen21-prepare|HF_TOKEN|api_key/);
  assert.ok(html.indexOf('data-qwen21-field="ratio"')<html.indexOf('data-qwen21-field="imageWidth"'));
  assert.match(html,/<\/footer>\s*<\/div><div class="desk-progress-float desk-qwen21__progress"/);
  const source=read('desktop-canvas-qwen21.js');
  assert.match(source,/map\(node=>materializeText\(node\)\)/);
  assert.match(source,/reference_upload_tokens:tokens/);
  assert.match(source,/referenceOrder=order/);
  assert.match(source,/s\.node\.jobId!==id\|\|\(s\.epoch\|\|0\)!==epoch/);
  assert.match(source,/if\(!live\(s\)\)return/);
});

test('节点尺寸和悬挂进度条遵循已有标准，不占用 LoRA 或生成按钮区域',()=>{
  const css=fs.readFileSync(path.join(frontend,'styles/desktop-qwen21.css'),'utf8');
  assert.match(css,/\.desk-node--qwen21\s*\{[^}]*width:720px;[^}]*height:500px;/);
  assert.match(css,/desk-qwen21__grid--params\s*\{[^}]*repeat\(4/);
  assert.match(css,/desk-qwen21__seed\s*\{[^}]*grid-column:span 2/);
  assert.match(css,/desk-qwen21__footer\s*\{[^}]*min-height:72px/);
  assert.match(css,/\.desk-node--qwen21 > \.desk-qwen21__progress\s*\{[^}]*top:calc\(100% \+ 2px\)/);
  assert.match(css,/desk-qwen21__references\[hidden\]\s*\{\s*display:none/);
  assert.doesNotMatch(css,/#7f7cff|#56c8d8/);
});

test('认证 API 与统一任务 client 保留 snake_case 和有序上传 tokens',async()=>{
  const calls=[];const api={json:async(url,options)=>{calls.push([url,options]);return{ok:true}},request(){},blob(){}};
  const DesktopTasks={createClient:options=>({submit:options.submit,progress:options.progress,cancel:options.cancel,result(){}})};
  const sandbox={window:{},api,DesktopTasks,DesktopApi:{getStatus:async id=>({task_id:id})},Blob,URL,location:{href:'http://localhost/desktop.html',origin:'http://localhost'}};
  vm.runInNewContext(read('desktop-qwen21-api.js'),sandbox);
  const A=sandbox.window.DesktopQwen21API;
  await A.prepare('community-v1','viggle-8');
  assert.equal(calls[0][0],'/api/qwen21/prepare');assert.match(calls[0][1].body,/"base_model_id":"community-v1"/);
  await A.tasks.submit({mode:'edit',preset:'viggle-6',reference_upload_tokens:['b','a'],loras:[{asset_id:'a'.repeat(64),scale:.8}]});
  assert.equal(calls[1][0],'/api/qwen21/generate');assert.match(calls[1][1].body,/"reference_upload_tokens":\["b","a"\]/);
  await A.convertModel({source_path:'Portrait.safetensors',model_name:'Portrait',precision:'8bit'});
  assert.equal(calls[2][0],'/api/qwen21/model-convert');assert.doesNotMatch(calls[2][1].body,/sourcePath|modelName/);
});

test('设置中心 Qwen 转换直接扫描目录，和 Krea 量化方案隔离',async()=>{
  const sandbox={window:{dispatchEvent(){}},CustomEvent:class{},setTimeout,clearTimeout};
  vm.runInNewContext(read('desktop-qwen21-tools.js'),sandbox);
  const tool=sandbox.window.DesktopQwen21Tools.create({api:{modelTools:async()=>({ok:true,base_model_directory:'/data/qwen21/base_models',
    import_directory:'/data/qwen21/imports',import_models:[{source_name:'PortraitFP8.safetensors',file_size:123}],
    runtime:{environment_ready:true,source_ready:true},conversion:{status:'idle'},models:[{id:'portrait',name:'Portrait',precision:'8bit',ready:true}]})}});
  await tool.activate();const html=tool.render();
  assert.match(html,/Qwen 2.1 模型转换/);assert.match(html,/PortraitFP8\.safetensors/);
  assert.equal(tool.state.draft.sourcePath,'PortraitFP8.safetensors');
  assert.doesNotMatch(html,/ComfyUI scaled-FP8/);assert.match(read('desktop-settings.js'),/ComfyUI scaled-FP8/);assert.match(html,/data-qwen21-model-convert/);
  assert.doesNotMatch(html,/mixed-4-8|Mixed 4\/8|data-krea2/);
  tool.deactivate();
});

test('脚本装配顺序、设置页、工作流和缓存版本完整',()=>{
  const html=fs.readFileSync(path.join(frontend,'desktop.html'),'utf8');
  const ordered=['desktop-tasks.js','desktop-qwen21-model.js','desktop-qwen21-api.js','desktop-qwen21-tools.js','desktop-canvas-qwen21.js','desktop-canvas-workflow.js','desktop-canvas-nodes.js','desktop-canvas.js','desktop-settings.js'];
  for(let i=1;i<ordered.length;i++)assert.ok(html.indexOf(ordered[i-1])<html.indexOf(ordered[i]));
  for(const name of ordered.filter(name=>name!=='desktop-tasks.js'))assert.ok(html.includes(name+'?v='+(name==='desktop-canvas-qwen21.js'?'20261009-generation-action-unify1':name==='desktop-settings.js'?'20261009-settings-drawer2':['desktop-canvas.js','desktop-canvas-nodes.js'].includes(name)?'20261007-node-progress4':['desktop-qwen21-model.js','desktop-qwen21-tools.js'].includes(name)?'20261006-qwen-base-retirement1':name==='desktop-qwen21-api.js'?'20261002-qwen21-vae1':'20261001-qwen21-adapters-1')));
  assert.match(read('desktop-canvas.js'),/qwen21Definition/);assert.match(read('desktop-canvas-nodes.js'),/qwen21Node/);
  assert.match(read('desktop-canvas-workflow.js'),/qwen21Definition/);assert.match(read('desktop-settings.js'),/qwen21Tools\?\.render/);
});

test('VAE 管理沿用认证适配，显式应用且不会隐式覆盖原版',async()=>{
  const calls=[];
  const api={json:async(url,options)=>{calls.push([url,options]);return{ok:true}}};
  const transport={window:{},api};vm.runInNewContext(read('desktop-qwen21-api.js'),transport);
  await transport.window.DesktopQwen21API.importVae('community.safetensors');
  await transport.window.DesktopQwen21API.selectVae('builtin');
  assert.equal(calls[0][0],'/api/qwen21/vae-import');assert.equal(JSON.parse(calls[0][1].body).source_path,'community.safetensors');
  assert.equal(calls[1][0],'/api/qwen21/vae-select');assert.equal(JSON.parse(calls[1][1].body).vae_id,'builtin');
  const imported='a'.repeat(64),feedback=[],operations=[];
  const data={runtime:{},conversion:{status:'idle'},models:[],vae:{selected_id:'builtin',import_directory:'/synthetic/vaes/imports',
    imports:[{source_name:'community.safetensors',file_size:256}],models:[{id:'builtin',name:'原版',format:'mflux'},{id:imported,name:'新 VAE <example>',format:'diffusers'}]}};
  const sandbox={window:{dispatchEvent(){}},CustomEvent:class{},setTimeout,clearTimeout};vm.runInNewContext(read('desktop-qwen21-tools.js'),sandbox);
  const tool=sandbox.window.DesktopQwen21Tools.create({api:{modelTools:async()=>data,
    importVae:async source=>{operations.push(['import',source]);return{vae:{id:imported}}},
    selectVae:async id=>{operations.push(['select',id]);data.vae.selected_id=id;return{ok:true}}},notify:(...x)=>feedback.push(x)});
  await tool.activate();assert.equal(tool.state.draft.vaeId,'builtin');
  let html=tool.render();assert.match(html,/Qwen 2.1 · VAE/);assert.match(html,/data-qwen21-vae-select/);assert.match(html,/新 VAE &lt;example&gt;/);
  const input=(key,value)=>({target:{closest:()=>({dataset:{qwen21ToolField:key},value})}});
  tool.handleInput(input('vaeSource','community.safetensors'));
  const click=attr=>({preventDefault(){},target:{closest:()=>({matches:selector=>selector===`[${attr}]`,dataset:{}})}});
  tool.handleClick(click('data-qwen21-vae-import'));await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(operations,[['import','community.safetensors']]);assert.equal(data.vae.selected_id,'builtin');assert.equal(tool.state.draft.vaeId,imported);
  await tool.refresh(true);assert.equal(tool.state.draft.vaeId,imported);
  tool.handleClick(click('data-qwen21-vae-select'));await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(operations[1],['select',imported]);assert.equal(tool.state.vaeDirty,false);
  tool.handleInput(input('vaeId','builtin'));tool.handleClick(click('data-qwen21-vae-select'));await new Promise(resolve=>setImmediate(resolve));
  assert.equal(data.vae.selected_id,'builtin');tool.deactivate();
});

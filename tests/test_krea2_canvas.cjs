const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const scripts=path.join(__dirname,'../frontend/scripts');
const frontend=path.join(__dirname,'../frontend');
const read=name=>fs.readFileSync(path.join(scripts,name),'utf8');
const context={window:{}};
vm.runInNewContext(read('desktop-krea2-model.js'),context);
const model=context.window.DesktopKrea2Model;

test('Krea 2 是独立 typed Canvas 节点并持久化多 LoRA 参数',()=>{
  const node=model.normalize({id:'krea2-test',type:'krea2',width:10,height:10,imageWidth:769,imageHeight:1024,
    loras:Array.from({length:6},(_,index)=>({assetId:String(index+1).repeat(64).slice(0,64),scale:1+index/10}))});
  assert.equal(model.TYPE,'krea2');
  assert.equal(node.width,720);assert.equal(node.height,480);
  assert.equal(node.imageWidth,768);assert.equal(node.loras.length,4);
  assert.equal(node.ratio,'3:4');
  assert.equal(model.ASPECT_RATIOS.length,11);
  const wide=model.dimensionsForRatio('16:9');
  assert.equal(wide.width,1280);assert.equal(wide.height,720);
  assert.equal(model.ratioFromDimensions(768,1280),'custom');
  const initialized=model.normalize({type:'krea2',ratio:'9:16'});
  assert.equal(initialized.imageWidth,720);assert.equal(initialized.imageHeight,1280);
  assert.equal(node.safetyEnabled,false);
  assert.equal(node.baseModelId,'krea-2-turbo-alis-mlx-8bit');
  assert.equal(model.normalize({type:'krea2',precision:'mixed-4-8'}).baseModelId,'krea-2-turbo-alis-mlx-mixed-4-8');
  assert.equal(model.normalize({type:'krea2',baseModelId:'portrait-v2'}).baseModelId,'portrait-v2');
  assert.equal(model.normalize({type:'krea2',safetyEnabled:true}).safetyEnabled,true);
  const edit=model.normalize({type:'krea2',mode:'edit',editAdapterId:'e'.repeat(64),editAdapterScale:.9,
    referenceStrength:5.5,groundingPx:1024,fitMode:'crop',loras:Array.from({length:4},(_,index)=>({assetId:String(index+1).repeat(64).slice(0,64),scale:1}))});
  assert.equal(edit.mode,'edit');assert.equal(edit.editAdapterId,'e'.repeat(64));
  assert.equal(edit.editAdapterScale,.9);assert.equal(edit.referenceStrength,5.5);
  assert.equal(edit.groundingPx,1024);assert.equal(edit.fitMode,'crop');assert.equal(edit.loras.length,4);
  const duplicate=model.normalize({type:'krea2',mode:'edit',editAdapterId:'a'.repeat(64),loras:[{assetId:'a'.repeat(64),scale:1}]});
  assert.equal(duplicate.loras.length,1);assert.equal(model.regularLoras(duplicate).length,0);
  assert.equal(model.MENU_ITEM.type,'krea2');
});

test('Krea 2 连线只接受文本和单图输入并输出图片',()=>{
  assert.ok(model.policy({type:'text'},{type:'krea2'}));
  assert.equal(model.policy({type:'text'},{type:'krea2'}).single,false);
  assert.equal(model.policy({type:'image'},{type:'krea2'}).single,true);
  assert.ok(model.policy({type:'krea2'},{type:'image'}));
  for(const [from,to] of [['video','krea2'],['image_group','krea2'],['krea2','video'],['audio','krea2']])
    assert.equal(model.policy({type:from},{type:to}),null);
});

test('节点只从画布连线取提示词和编辑图，参数面板支持 LoRA 栈',()=>{
  const sandbox={window:{addEventListener(){}},AbortController};vm.runInNewContext(read('desktop-canvas-krea2.js'),sandbox);
  const canvas={nodes:{i:{id:'i',type:'image'}},edges:[]};
  const controller=sandbox.window.DesktopCanvasKrea2.create({model,getCanvas:()=>canvas});
  const html=controller.nodeHtml({id:'krea2-test',type:'krea2'});
  assert.doesNotMatch(html,/<textarea|data-krea2-prompt/);
  assert.match(html,/data-krea2-lora-add/);
  assert.doesNotMatch(html,/data-krea2-lora-file|data-krea2-prepare/);
  assert.match(html,/Base 权重模型/);
  assert.match(html,/工作模式/);
  assert.match(html,/标准生成 · 文生图/);
  assert.match(html,/data-krea2-mode readonly/);
  assert.doesNotMatch(html,/data-krea2-field="mode"|data-krea2-field="strength"/);
  assert.doesNotMatch(html,/<span>LoRA 模型<\/span>/);
  assert.match(html,/普通 LoRA/);
  assert.match(html,/data-krea2-lora-count>0 \/ 4/);
  assert.match(html,/aria-label="添加普通 LoRA"/);
  assert.match(html,/data-krea2-field="baseModelId"/);
  assert.match(html,/Krea 2 Turbo · Alis MLX/);
  assert.match(html,/data-krea2-field="ratio"/);
  assert.ok(html.indexOf('data-krea2-lora-add')>html.indexOf('desk-krea2__loras'));
  assert.ok(html.indexOf('data-krea2-field="ratio"')<html.indexOf('data-krea2-field="imageWidth"'));
  assert.equal((html.match(/data-krea2-lora-add/g)||[]).length,1);
  assert.match(html,/desk-node__header desk-krea2__header/);
  assert.match(html,/desk-number/);
  assert.match(html,/desk-input-footer desk-krea2__footer/);
  assert.match(html,/desk-switch/);
  assert.match(html,/data-krea2-safety/);
  assert.doesNotMatch(html,/data-krea2-safety checked/);
  assert.match(controller.nodeHtml({id:'krea2-safe',type:'krea2',safetyEnabled:true}),/data-krea2-safety checked/);
  assert.match(html,/data-progress-bar data-krea2-bar/);
  assert.match(html,/data-krea2-edit-panel hidden/);
  canvas.edges.push({from:'i',to:'krea2-edit'});
  const editHtml=controller.nodeHtml({id:'krea2-edit',type:'krea2',mode:'standard',editAdapterId:'e'.repeat(64)});
  assert.match(editHtml,/图像编辑 · Identity Edit/);
  assert.match(editHtml,/data-krea2-edit-panel>/);
  assert.match(editHtml,/编辑适配器 · 必需/);assert.match(editHtml,/参考图保真/);
  assert.match(editHtml,/语义识图/);assert.match(editHtml,/Fit · v1\.2 推荐/);
  assert.match(editHtml,/data-krea2-lora-count>0 \/ 3/);
  assert.match(editHtml,/可选 · 按顺序叠加 · 不含编辑适配器/);
  const source=read('desktop-canvas-krea2.js');
  assert.match(source,/getTextNodes\(s\.id\)/);
  assert.match(source,/getImageReferences\(s\.id\)/);
  assert.match(source,/loras:M\.regularLoras\(s\.node\)\.map/);
  assert.match(source,/const mode=s\.node\.mode/);
  assert.match(source,/edit_image_upload_token:mode==='edit'\?token:''/);
  assert.match(source,/edit_adapter_asset_id:mode==='edit'\?s\.node\.editAdapterId:''/);
  assert.match(source,/reference_strength:s\.node\.referenceStrength/);
  assert.match(source,/grounding_px:s\.node\.groundingPx/);
  assert.match(source,/fit_mode:s\.node\.fitMode/);
  assert.match(source,/指令编辑必须连接 1 张编辑源图/);
  assert.match(source,/aspect_ratio:s\.node\.ratio/);
  assert.match(source,/M\.dimensionsForRatio\(node\.ratio\)/);
  assert.match(source,/M\.ratioFromDimensions\(node\.imageWidth,node\.imageHeight\)/);
  assert.match(source,/await api\.prepare\(s\.node\.baseModelId,s\.node\.safetyEnabled\)/);
  assert.match(source,/base_model_id:s\.node\.baseModelId/);
  assert.match(source,/safety_enabled:s\.node\.safetyEnabled/);
  assert.match(source,/!node\.safetyEnabled\|\|status\?\.safety_ready/);
  assert.match(source,/!readyFor\(s\.node\)&&!await ensureReady\(s\)/);
  assert.doesNotMatch(source,/function importLora|data-krea2-lora-file/);
  assert.doesNotMatch(source,/api[_-]?key|HF_TOKEN/);
  assert.match(source,/progress\.classList\.toggle\('is-visible',showProgress\)/);
});

test('Krea 2 复用标准模型节点控件并约束可变 LoRA 区域',()=>{
  const css=fs.readFileSync(path.join(frontend,'styles/desktop-krea2.css'),'utf8');
  assert.match(css,/\.desk-node--krea2\s*\{[\s\S]*?width:\s*720px;[\s\S]*?height:\s*480px;/);
  assert.match(css,/\.desk-krea2__loras\s*\{[\s\S]*?flex:\s*1 1 auto;[\s\S]*?overflow:\s*visible;/);
  assert.match(css,/\[data-krea2-lora-list\][\s\S]*?flex:\s*1 1 auto;[\s\S]*?overflow:\s*auto;/);
  assert.doesNotMatch(css,/\.desk-krea2__loras\s*\{[\s\S]*?max-height:/);
  assert.match(css,/\.desk-krea2__footer\s*\{[\s\S]*?min-height:\s*72px;/);
  assert.match(css,/\.desk-krea2__grid--model\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0, 0\.8fr\) minmax\(0, 1\.7fr\)/);
  assert.match(css,/\.desk-krea2__grid--params\s*\{[\s\S]*?grid-template-columns:\s*repeat\(4,/);
  assert.match(css,/\.desk-krea2__grid--params\s*>\s*label:nth-child\(6\)\s*\{[\s\S]*?grid-column:\s*span 2;/);
  assert.doesNotMatch(css,/desk-krea2__(?:prepare|import)/);
  assert.match(css,/\.desk-node--krea2\s*>\s*\.desk-krea2__progress\s*\{[\s\S]*?top:\s*calc\(100% \+ 2px\);[\s\S]*?left:\s*0;[\s\S]*?width:\s*100%;/);
  assert.doesNotMatch(css,/\.desk-node--krea2\s*>\s*\.desk-krea2__progress\s*\{[\s\S]*?bottom:\s*78px;/);
  assert.match(css,/\.desk-node--krea2\s*>\s*\.desk-krea2__progress\[hidden\]\s*\{\s*display:\s*none;/);
  assert.doesNotMatch(css,/--krea-accent|#7f7cff|#56c8d8|rgba\(6,8,17/);
  assert.match(css,/\.desk-krea2__edit\s*\{[\s\S]*?grid-template-columns:/);
  assert.match(css,/\.desk-krea2__edit\[hidden\][\s\S]*?display:\s*none !important;/);
  assert.match(css,/\.desk-krea2__lora-count\s*\{/);
  assert.match(css,/grid-template-columns:\s*repeat\(auto-fit, minmax\(190px, 1fr\)\)/);
  assert.match(css,/\.desk-krea2__lora\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\) 58px 26px;/);
});

test('Krea 2 API 使用认证适配器和 snake_case 请求',async()=>{
  const calls=[];
  const api={json:async(url,options)=>{calls.push([url,options]);return{ok:true,task_id:'krea2_'+ 'a'.repeat(32)}},
    request:async()=>({ok:true,json:async()=>({upload_token:'token'})}),blob:async()=>new Blob(['x'])};
  const createClient=()=>({submit(){},progress(){},cancel(){},result(){}});
  const sandbox={window:{DesktopTasks:{createClient},location:{href:'http://localhost/desktop.html',origin:'http://localhost'}},
    DesktopTasks:{createClient},DesktopApi:{getStatus:async()=>({})},api,Blob,URL,
    location:{href:'http://localhost/desktop.html',origin:'http://localhost'}};
  vm.runInNewContext(read('desktop-krea2-api.js'),sandbox);
  await sandbox.window.DesktopKrea2API.prepare('portrait-v2',true);
  assert.equal(calls[0][0],'/api/krea2/prepare');
  assert.match(calls[0][1].body,/"base_model_id":"portrait-v2"/);
  assert.match(calls[0][1].body,/"safety_enabled":true/);
  await sandbox.window.DesktopKrea2API.submit({mode:'edit',aspect_ratio:'16:9',image_count:2,edit_image_upload_token:'token',edit_adapter_asset_id:'e'.repeat(64),reference_strength:4,grounding_px:768,fit_mode:'fit',loras:[],safety_enabled:false});
  const [url,options]=calls[1];assert.equal(url,'/api/krea2/generate');
  assert.match(options.body,/"image_count":2/);assert.match(options.body,/"edit_image_upload_token"/);
  assert.match(options.body,/"edit_adapter_asset_id"/);assert.match(options.body,/"reference_strength":4/);
  assert.match(options.body,/"aspect_ratio":"16:9"/);
  assert.match(options.body,/"safety_enabled":false/);
  assert.doesNotMatch(options.body,/imageCount|api_key|token_secret/);
  await sandbox.window.DesktopKrea2API.convertModel({source_path:'/tmp/model.safetensors',model_name:'Portrait',precision:'8bit'});
  assert.equal(calls[2][0],'/api/krea2/model-convert');
  assert.match(calls[2][1].body,/"source_path":"\/tmp\/model\.safetensors"/);
});

test('设置中心模型工具管理检查、转换、取消和模型目录',async()=>{
  const sandbox={window:{dispatchEvent(){}},CustomEvent:class{constructor(type){this.type=type;}},setTimeout,clearTimeout};
  vm.runInNewContext(read('desktop-krea2-tools.js'),sandbox);
  const api={modelTools:async()=>({ok:true,base_model_directory:'/data/base_models',import_directory:'/data/imports',
    import_models:[{source_name:'Dark Beast FP8.safetensors',file_size:13*1024**3}],
    conversion:{status:'idle'},models:[{id:'portrait-v2',name:'Portrait v2',quantization:'8-bit',file_size:42,ready:true,builtin:false,requantized:true}]})};
  const tool=sandbox.window.DesktopKrea2Tools.create({api,escapeHtml:value=>String(value),rerender(){},notify(){}});
  await tool.activate();
  const html=tool.render();
  assert.match(html,/data-krea2-tool-field="sourcePath"/);
  assert.match(html,/Dark Beast FP8\.safetensors/);
  assert.equal(tool.state.draft.sourcePath,'Dark Beast FP8.safetensors');
  assert.match(html,/data-krea2-tool-field="modelName"/);
  assert.match(html,/转换后显示名称/);
  assert.match(html,/data-krea2-tool-field="precision"/);
  assert.match(html,/data-krea2-model-inspect/);
  assert.match(html,/data-krea2-model-convert/);
  assert.match(html,/Portrait v2/);
  assert.match(html,/FP8 源重新量化/);
  assert.doesNotMatch(html,/ComfyUI scaled-FP8 E4M3FN/);
  assert.match(read('desktop-settings.js'),/ComfyUI scaled-FP8 E4M3FN/);
  assert.match(html,/data-krea2-model-delete="portrait-v2"/);
  tool.state.inspection={compatible_candidate:false,message:'already quantized',source_name:'model.safetensors'};
  assert.match(tool.render(),/data-krea2-model-convert disabled/);
  tool.deactivate();
  const source=read('desktop-krea2-tools.js');
  assert.match(source,/api\.inspectModel/);
  assert.match(source,/api\.convertModel/);
  assert.match(source,/api\.cancelModelConversion/);
  assert.match(source,/krea2-models-changed/);
});

test('桌面资源顺序与 Krea 2 缓存版本已更新',()=>{
  const html=fs.readFileSync(path.join(frontend,'desktop.html'),'utf8');
  const order=['desktop-api.js','desktop-krea2-model.js','desktop-krea2-api.js','desktop-krea2-tools.js','desktop-canvas-krea2.js','desktop-canvas-workflow.js','desktop-canvas-nodes.js','desktop-canvas.js','desktop-settings.js'];
  for(let index=1;index<order.length;index++)assert.ok(html.indexOf(order[index-1])<html.indexOf(order[index]));
  for(const name of ['desktop-krea2-model.js','desktop-krea2-api.js','desktop-krea2-tools.js','desktop-canvas-krea2.js'])
    assert.match(html,new RegExp(name.replaceAll('.','\\.')+'\\?v='+ (['desktop-krea2-model.js','desktop-krea2-tools.js'].includes(name)?'20261006-bf16-transformer1':name==='desktop-canvas-krea2.js'?'20261009-generation-action-unify1':'20260929-krea2-layout-3')));
  for(const name of ['desktop-canvas-workflow.js','desktop-canvas-nodes.js','desktop-canvas.js','desktop-settings.js'])
    assert.match(html,new RegExp(name.replaceAll('.','\\.')+'\\?v='+ (name==='desktop-settings.js'?'20261010-segment-bank1':name==='desktop-canvas-nodes.js'?'20261010-node-keys1':name==='desktop-canvas.js'?'20261007-node-progress4':'20261001-qwen21-adapters-1')));
  assert.match(html,/desktop-krea2\.css\?v=20261003-auto-image-mode1/);
  assert.match(html,/data-settings-tab="model-tools"/);
});

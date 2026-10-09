const {test}=require('node:test'), assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const dir=path.join(__dirname,'../frontend/scripts');
function context(){
 const ctx={window:{},DesktopState:{state:{canvas:{nodes:{},edges:[]}},isInFlight:s=>['queued','processing'].includes(s),isSuccess:s=>s==='succeeded',isFailure:s=>s==='failed'}};
 for(const file of ['desktop-state-icon.js', 'desktop-topaz-model.js','desktop-topaz-api.js','desktop-canvas-topaz.js','desktop-canvas-generation.js'])vm.runInNewContext(fs.readFileSync(path.join(dir,file),'utf8'),ctx);
 return ctx;
}
test('legacy Topaz node migrates without changing identity, position or edges',()=>{
 const c=context(),m=c.window.DesktopTopazModel;
 const node={id:'old',type:'upscale',x:123,y:45,model:'topaz-high-fidelity-v3',autoUpscaleSourceKey:'old-output',output:{telegramEnabled:true}};
 const result=m.migrate(node);assert.equal(result,node);assert.equal(node.type,'topaz');assert.equal(node.model,'topaz-high-fidelity-v3');
 assert.equal(node.id,'old');assert.equal(node.x,123);assert.equal(node.topaz.scale,2);assert.equal(node.output.telegramEnabled,true);
 assert.equal(node.autoUpscaleSourceKey,undefined);
 const original={id:'esr',type:'upscale',model:'4x-UltraSharp'};m.migrate(original);assert.equal(original.type,'upscale');assert.equal(original.topaz,undefined);
});
test('Topaz supports own parameters and only compatible image connections',()=>{
 const c=context(),m=c.window.DesktopTopazModel, n=m.normalize({type:'topaz',topaz:{scale:6,grain:true,unit:'cm',face_creativity:1}});
 assert.equal(n.topaz.scale,6);assert.equal(n.topaz.grain,true);assert.equal(n.topaz.face_creativity,1);
 assert.equal(m.normalize({topaz:{scale:NaN,output_format:'exe'}}).topaz.scale,2);
 for(const t of ['image','input','comfy','pose','layout'])assert.equal(m.policy({type:t},{type:'topaz'}).single,true);
 assert.equal(m.policy({type:'audio'},{type:'topaz'}),null);assert.equal(m.policy({type:'topaz'},{type:'image'}).replaceAllInputs,true);
});
test('independent node form exposes sizes, formats and model-specific controls without folds',()=>{
 const c=context(),m=c.window.DesktopTopazModel,controller=c.window.DesktopCanvasTopaz.create({model:m,stateIcon:c.window.DesktopStateIcon});
 const std=controller.nodeHtml(m.normalize({id:'s',type:'topaz'}));
 for(const key of ['resize_mode','scale','dimension','unit','ppi','auto','denoise','sharpen','fix_compression','gamma_correction','grain','grain_strength','grain_intensity','grain_size','face_enhancement','face_strength','face_creativity','output_format','jpeg_quality'])assert.ok(std.includes(`data-topaz-field="${key}"`),key);
 for(const label of ['1×','2×','4×','6×','自定义','指定宽度','指定高度','最长边','PNG','JPEG','TIFF','Realistic','Creative'])assert.ok(std.includes(label),label);
 assert.ok(!std.includes('<details'));assert.ok(!std.includes('data-upscale-field'));
 const hf=controller.nodeHtml(m.normalize({id:'h',model:'topaz-high-fidelity-v3'}));
 assert.ok(hf.includes('data-topaz-field="strength"'));assert.ok(!hf.includes('data-topaz-field="sharpen"'));
 assert.ok(hf.includes('data-progress-bar'));assert.ok(hf.includes('data-result-run'));
});
test('own API uses authenticated client, snake_case options and the shared task receipt',async()=>{
 const c=context();let call;
 const receipt={task_id:'topaz_1'};
 const client={json:async(route,request)=>{call={route,body:JSON.parse(request.body)};return receipt;}};
 const returned=await c.window.DesktopTopazApi.submit(client,{config:{prompt:'test',params:{model:'topaz-standard-v2',topaz:{scale:4,output_format:'tiff'}}},images:['data:image/png;base64,AA=='],lineage:{source_node_id:'s'},telegramEnabled:false});
 assert.equal(returned,receipt);assert.equal(call.route,'/api/topaz/run');assert.equal(call.body.options.scale,4);assert.equal(call.body.telegram_enabled,false);assert.equal(call.body.lineage.source_node_id,'s');
});
test('Wonder submit rejects sub-1× scale and equivalent target dimensions before the API call',async()=>{
 const c=context();let calls=0;
 c.Image=class {set src(_) {this.naturalWidth=1000;this.naturalHeight=800;this.onload();}};
 const client={json:async()=>{calls++;return {task_id:'ok'};}};
 const submit=(model,topaz)=>c.window.DesktopTopazApi.submit(client,{config:{params:{model,topaz}},images:['data:image/png;base64,AA==']});
 for(const model of ['topaz-wonder-2','topaz-wonder-3','topaz-wonder-35']){
   await assert.rejects(submit(model,{resize_mode:'scale',scale:.5}),/不能低于 1×/);
   await assert.rejects(submit(model,{resize_mode:'width',dimension:500,unit:'px',ppi:300}),/不能小于原图/);
 }
 await assert.rejects(submit('topaz-wonder-3',{resize_mode:'height',dimension:7,unit:'in',ppi:100}),/不能小于原图/);
 await assert.rejects(submit('topaz-wonder-3',{resize_mode:'longest',dimension:9,unit:'cm',ppi:254}),/不能小于原图/);
 assert.equal(calls,0);
 await submit('topaz-wonder-3',{resize_mode:'longest',dimension:10,unit:'cm',ppi:254});
 await submit('topaz-standard-v2',{resize_mode:'scale',scale:.5});
 assert.equal(calls,2);
});
test('missing/migrated Topaz never triggers legacy component download',async()=>{
 const c=context();let installs=0;c.DesktopApi={getUpscaleModels:async()=>({models:[]}),installUpscaleComponent:()=>installs++};
 await assert.rejects(c.window.DesktopCanvasGeneration.create({}).ensureUpscaleComponent('topaz-standard-v2'),/独立节点/);assert.equal(installs,0);
});
test('chain stops scheduling when workflow is replaced during an awaited submission',async()=>{
 const c=context(),m=c.window.DesktopTopazModel;
 let state={canvas:{nodes:{source:{type:'input'},a:m.normalize({id:'a',type:'topaz'}),b:m.normalize({id:'b',type:'topaz'})},edges:[{from:'source',to:'a'},{from:'source',to:'b'}]},outputs:{}};
 let submissions=0;
 const controller=c.window.DesktopCanvasTopaz.create({model:m,stateIcon:c.window.DesktopStateIcon,getState:()=>state,getNodeElement:()=>null,getReferences:()=>[],outputReference:()=>({title:'synthetic'}),ensureOutputs:()=>{},showError:()=>{},submit:async()=>{submissions++;state={canvas:{nodes:{},edges:[]},outputs:{}};}});
 await controller.runChains('source',{taskId:'test'});assert.equal(submissions,1);
});
test('standalone assets load before canvas and no Topaz option remains in local upscale',()=>{
 const html=fs.readFileSync(path.join(dir,'../desktop.html'),'utf8'),canvas=fs.readFileSync(path.join(dir,'desktop-canvas.js'),'utf8');
 for(const file of ['desktop-topaz-model.js','desktop-topaz-api.js','desktop-canvas-topaz.js'])assert.ok(html.indexOf(file)<html.indexOf('scripts/desktop-canvas.js?'));
 assert.ok(html.includes('desktop-topaz.css?v='));
 const options=canvas.slice(canvas.indexOf('const UPSCALE_MODEL_OPTIONS'),canvas.indexOf('const UPSCALE_MODEL_OPTIONS')+650);
 assert.ok(!options.includes('topaz-standard-v2'));
});
test('number inputs persist before blur; dependency changes retain values and invalid numbers do not submit',()=>{
 const c=context(),m=c.window.DesktopTopazModel,n=m.normalize({id:'t',type:'topaz'}),events={};let saves=0;
 const button={dataset:{},querySelector:()=>({dataset:{stateIcon:'idle'},querySelectorAll:()=>[]}),setAttribute:()=>{}},preset={},fields={};
 const el={dataset:{},addEventListener:(name,fn)=>events[name]=fn,querySelector:s=>s==='[data-result-run]'?button:s==='.desk-topaz__fields'?fields:s==='[data-topaz-preset]'?preset:{},querySelectorAll:()=>[]};
 const state={canvas:{nodes:{t:n},edges:[]},outputs:{}};
 const control=c.window.DesktopCanvasTopaz.create({model:m,stateIcon:c.window.DesktopStateIcon,getState:()=>state,getNodeElement:()=>el,getReferences:()=>[],save:()=>saves++});
 control.reconcile();
 const target={dataset:{topazField:'scale'},type:'number',tagName:'INPUT',value:'1.5',checkValidity:()=>true};
 events.input({target});assert.equal(n.topaz.scale,1.5);assert.equal(preset.value,'custom');assert.equal(saves,1);
 events.change({target:{dataset:{topazField:'grain'},type:'checkbox',tagName:'INPUT',checked:true}});
 assert.equal(n.topaz.scale,1.5);assert.ok(fields.innerHTML.includes('value="1.5"'));
 target.value='-1';target.checkValidity=()=>false;events.input({target});assert.equal(n.topaz.scale,1.5);
});

test('Wonder 2/3/3.5 require at least 1× while other Topaz models retain downscale',()=>{
 const c=context(),m=c.window.DesktopTopazModel,controller=c.window.DesktopCanvasTopaz.create({model:m,stateIcon:c.window.DesktopStateIcon});
 for(const model of ['topaz-wonder-2','topaz-wonder-3','topaz-wonder-35']){
   assert.equal(m.minScale(model),1);
   const node=m.normalize({id:model,type:'topaz',model,topaz:{scale:.5}});
   assert.equal(node.topaz.scale,1);
   assert.match(controller.nodeHtml(node),/data-topaz-field="scale"[^>]*min="1"[^>]*value="1"/);
 }
 for(const model of ['topaz-wonder-1','topaz-standard-v2']){
   assert.equal(m.minScale(model),.2);
   const node=m.normalize({id:model,type:'topaz',model,topaz:{scale:.5}});
   assert.equal(node.topaz.scale,.5);
   assert.match(controller.nodeHtml(node),/data-topaz-field="scale"[^>]*min="0\.2"[^>]*value="0\.5"/);
 }
});

test('switching to Wonder corrects a saved 0.5× value and stale invalid scale cannot submit',()=>{
 const c=context(),m=c.window.DesktopTopazModel,n=m.normalize({id:'t',type:'topaz',model:'topaz-standard-v2',topaz:{scale:.5}}),events={};let saves=0;
 const button={dataset:{},querySelector:()=>({dataset:{stateIcon:'idle'},querySelectorAll:()=>[]}),setAttribute:()=>{}},fields={};
 const el={dataset:{},addEventListener:(name,fn)=>events[name]=fn,
   querySelector:s=>s==='[data-result-run]'?button:s==='.desk-topaz__fields'?fields:{},querySelectorAll:()=>[]};
 const state={canvas:{nodes:{t:n},edges:[]},outputs:{}};
 const control=c.window.DesktopCanvasTopaz.create({model:m,stateIcon:c.window.DesktopStateIcon,getState:()=>state,getNodeElement:()=>el,
   getReferences:()=>[{title:'test.png'}],save:()=>saves++});
 control.reconcile();
 events.change({target:{dataset:{},tagName:'SELECT',value:'topaz-wonder-3',hasAttribute:key=>key==='data-topaz-model'}});
 assert.equal(n.model,'topaz-wonder-3');assert.equal(n.topaz.scale,1);assert.equal(saves,1);
 assert.match(fields.innerHTML,/data-topaz-field="scale"[^>]*min="1"[^>]*value="1"/);
 const scale={dataset:{topazField:'scale'},type:'number',tagName:'INPUT',value:'0.5',checkValidity:()=>false};
 events.input({type:'input',target:scale});assert.equal(n.topaz.scale,1);assert.equal(scale.value,'0.5');
 events.change({type:'change',target:scale});assert.equal(scale.value,'1');assert.equal(n.topaz.scale,1);
 n.topaz.scale=.5;
 assert.throws(()=>control.readConfig('t'),/不能低于 1×/);
});

test('expanded models have distinct controls and unverified versions cannot masquerade as available',()=>{
 const c=context(),m=c.window.DesktopTopazModel,controller=c.window.DesktopCanvasTopaz.create({model:m,stateIcon:c.window.DesktopStateIcon});
 assert.equal(m.MODELS.length,19);
 const page=id=>controller.nodeHtml(m.normalize({id,type:'topaz',model:id}));
 for(const model of m.MODELS)assert.ok(page(model.value).includes(model.label.replaceAll('&','&amp;')));
 const wonder=page('topaz-wonder-35');
 assert.ok(wonder.includes('data-topaz-field="enhancement_strength"'));
 assert.ok(!wonder.includes('data-topaz-field="denoise"'));assert.ok(!wonder.includes('data-topaz-field="face_enhancement"'));
 assert.match(wonder,/<option value="topaz-wonder-1">/);
 const creative=page('topaz-redefine-creative');
 for(const field of ['creativity','texture','description','seed'])assert.ok(creative.includes(`data-topaz-field="${field}"`));
 assert.ok(!creative.includes('data-topaz-field="strength"'));
 const real=page('topaz-redefine-realistic');assert.ok(real.includes('Subtle'));assert.ok(!real.includes('data-topaz-field="description"'));
 const old=m.normalize({model:'topaz-redefine-creative',topaz:{description:'<script>test</script>',creativity:99,realistic_detail:1}});
 assert.equal(old.topaz.creativity,3);assert.equal(old.topaz.realistic_detail,1);assert.ok(controller.nodeHtml(old).includes('&lt;script&gt;test&lt;/script&gt;'));
});
test('capability API uses the authenticated adapter',async()=>{
 const c=context();let route;
 const result=await c.window.DesktopTopazApi.catalog({json:async path=>{route=path;return {models:[]};}});
 assert.equal(route,'/api/topaz/models');assert.equal(result.models.length,0);
});

test('Topaz floating progress has no inset-card class and shares result visibility wiring',()=>{
 const c=context(),m=c.window.DesktopTopazModel;
 const html=c.window.DesktopCanvasTopaz.create({model:m,stateIcon:c.window.DesktopStateIcon}).nodeHtml(m.normalize({id:'t'}));
 assert.match(html,/class="desk-progress-float desk-topaz__progress"/);assert.doesNotMatch(html,/desk-progress-wrap/);
 const css=fs.readFileSync(path.join(dir,'../styles/desktop-topaz.css'),'utf8');
 assert.match(css,/top:calc\(100% \+ 2px\)/);
 const results=fs.readFileSync(path.join(dir,'desktop-results.js'),'utf8');
 assert.ok(results.includes("node.querySelector('.desk-progress-wrap, .desk-progress-float')"));
});

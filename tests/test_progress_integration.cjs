const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {Element,read}=require('./helpers/progress-harness.cjs');
const file=name=>fs.readFileSync(path.join(__dirname,'../frontend',name),'utf8');

test('preference migration defaults to Liquid while preserving existing theme/connection settings and per-style colors',()=>{
 const storage=new Map([['desktop_ui_preferences_v1',JSON.stringify({theme:'dark',language:'zh',connectionLineStyle:'curve'})]]),events=[];
 const body=new Element(),html=new Element();
 const document={readyState:'loading',body,documentElement:html,getElementById:()=>null,addEventListener(){}};
 const window={dispatchEvent:e=>events.push(e)};
 const ctx=vm.createContext({window,document,localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},CustomEvent:class {constructor(type,opts){this.type=type;this.detail=opts.detail;}}});
 vm.runInContext(read('desktop-progress-model'),ctx);
 vm.runInContext(read('desktop-preferences').split('\n(function () {')[0],ctx);
 const prefs=window.DesktopPreferences;prefs.init();
 assert.equal(prefs.state.progress.style,'liquid');assert.equal(body.dataset.progressStyle,'liquid');
 assert.equal(prefs.state.theme,'dark');assert.equal(prefs.state.connectionLineStyle,'curve');
 prefs.setProgressPreferences({style:'slosh',height:48,colors:{slosh:'#abc'}});
 prefs.setProgressPreferences({style:'smoke'});prefs.setProgressPreferences({style:'slosh'});
 assert.equal(prefs.state.progress.colors.slosh,'#AABBCC');
 const saved=JSON.parse(storage.get('desktop_ui_preferences_v1'));assert.equal(saved.theme,'dark');assert.equal(saved.connectionLineStyle,'curve');assert.equal(saved.progress.height,48);
 prefs.init();assert.equal(prefs.state.progress.style,'slosh');assert.equal(prefs.state.progress.colors.slosh,'#AABBCC');
 prefs.setProgressPreferences({style:'classic',colors:{classic:'#35D1C4'}});assert.equal(body.dataset.progressClassicTint,'true');
 prefs.setProgressPreferences({colors:{}});assert.equal(body.dataset.progressClassicTint,undefined);
 assert.ok(events.every(e=>e.type==='desktop:progress-preferences-change'));
});

test('desktop load order, cache busting and boundaries cover every new dependency and changed consumer',()=>{
 const html=file('desktop.html'),order=['desktop-progress-model','desktop-progress-materials','desktop-progress-renderer','desktop-progress','desktop-preferences'];
 for(let i=1;i<order.length;i++)assert.ok(html.indexOf(`scripts/${order[i-1]}.js?`)<html.indexOf(`scripts/${order[i]}.js?`));
 const changed=[...order,'desktop-canvas','desktop-canvas-krea2','desktop-canvas-qwen21','desktop-canvas-cyimg','desktop-canvas-nodes','desktop-canvas-model-nodes','desktop-results','desktop-settings','desktop-music-view','desktop-topaz-video-view','desktop-video-control-view'];
 for(const name of changed)assert.ok(html.includes(`scripts/${name}.js?v=${['desktop-canvas-qwen21','desktop-canvas-krea2','desktop-canvas-cyimg','desktop-canvas-model-nodes'].includes(name)?'20261009-generation-action-unify1':name==='desktop-preferences'?'20261009-release-26-3-0':name==='desktop-settings'?'20261009-settings-drawer2':'20261007-node-progress4'}`),name);
 assert.ok(html.includes('styles/desktop-progress.css?v=20261007-node-progress4'));
 for(const name of ['desktop-progress-model','desktop-progress-materials','desktop-progress-renderer','desktop-progress']) {
  const source=read(name);assert.doesNotMatch(source,/\b(?:fetch|localStorage|DesktopState|DesktopResults)\b/);
 }
 assert.doesNotMatch(read('desktop-progress'),/new (?:window\.)?MutationObserver/);
 assert.match(read('desktop-canvas'),/progressView: canvasProgress/);
 assert.match(read('desktop-canvas'),/updateTaskProgress: canvasProgress\.update/);
 assert.match(read('desktop-canvas-nodes'),/progressView\?\.releaseWithin\(nodeEl\)/);
 assert.match(read('desktop-canvas'),/function applyWorkflowSnapshot[\s\S]*?canvasProgress\.clear\(\)/);
 assert.match(read('desktop-canvas'),/pagehide', event => \{ if \(!event\.persisted\) canvasProgress\.destroy\(\)/);
 const css=file('styles/desktop-progress.css');
 assert.match(css,/body\.desk-app \.desk-node \.desk-progress-material\s*\{/);
 assert.match(css,/body\.desk-app \.desk-progress-material > \.desk-progress-material__track\s*\{[^}]*height: 100%;\s*margin: 0;/);
});

function viewHarness(name, model) {
 const calls=[],elements=new Map();
 const el={querySelector(key){if(!elements.has(key)){
  const item=new Element();item.querySelector=child=>el.querySelector(key+' '+child);elements.set(key,item);
 }return elements.get(key);},querySelectorAll:()=>[]};
 const ctx=vm.createContext({window:{}});vm.runInContext(read(name),ctx);
 const namespace=Object.values(ctx.window)[0];
 const view=namespace.create({model,escapeHtml:String,stateIcon:{html:()=>'',paint(){}},progressView:{update:(...args)=>calls.push(args)}});
 return {view,el,calls};
}
test('Topaz Video adapter forwards exact observed counts/timestamps and hides terminal, not prior pending percentages',()=>{
 const h=viewHarness('desktop-topaz-video-view',{active:s=>s==='running',labels:{running:'运行中',succeeded:'已完成'}});
 const node={status:'running',model:'test',scale:2,maxSeconds:0},job={id:'test',progress_percent:34.9,started_at:1790910000,stage:'渲染帧'};
 const catalog=[{id:'test',available:true,verified:true,scales:[2]}];
 h.view.paint(h.el,node,job,false,catalog);assert.equal(h.calls.at(-1)[1].percent,34.9);assert.equal(h.calls.at(-1)[1].startedAt,job.started_at);
 h.view.paint(h.el,node,job,true,catalog);assert.equal(h.calls.at(-1)[1].percent,null);assert.equal(h.calls.at(-1)[1].startedAt,0);
 h.view.paint(h.el,{...node,status:'succeeded'},job,false,catalog);assert.equal(h.calls.at(-1)[1].visible,false);
});
test('ReShot retains unknown percent and music retains current-stage label and domain-owned elapsed',()=>{
 const v=viewHarness('desktop-video-control-view',{active:s=>s==='running',stageLabel:s=>s,labels:{running:'处理中'}});
 v.view.paint(v.el,{status:'running',control:'depth'},{id:'r',stage:'深度处理',created_at:1790910000});
 assert.equal(v.calls.at(-1)[1].percent,undefined);assert.equal(v.calls.at(-1)[1].detail,'ReShot · 视频控制');
 const m=viewHarness('desktop-music-view',{});
 m.view.paintProgress(m.el,{visible:true,percent:25,value:'阶段 25%',stage:'声学合成 · 2/8 步（当前阶段）',elapsed:'01:12'});
 assert.equal(m.calls.at(-1)[1].valueLabel,'阶段 25%');assert.equal(m.calls.at(-1)[1].elapsedText,'01:12');
 m.view.paintProgress(m.el,{visible:true,percent:null,value:'生成中',stage:'生成语义 · 512 tokens',elapsed:'01:13'});
 assert.equal(m.calls.at(-1)[1].percent,null);
});
test('common results and MLX/Cyimg adapters use task receipts, not the legacy estimated floor, and release on disposal',()=>{
 for(const name of ['desktop-canvas-qwen21','desktop-canvas-krea2','desktop-canvas-cyimg']) {
  const source=read(name);assert.match(source,/progressView\?\.update\(progress/);
  assert.match(source,/task\?\.progress\?\?null/);assert.match(source,/progressView\?\.releaseWithin\(s\.el\)/);
 }
 const results=read('desktop-results');assert.match(results,/percent: task\?\.progress \?\? task\?\.progress_percent \?\? task\?\.progressPercent \?\? null/);
 assert.match(results,/materialRoot = resultNode\.querySelector\('\[data-input-material-progress\]'\)/);
 assert.match(read('desktop-canvas-model-nodes'),/progressView\?\.replaceRoot/);
});

test('progress settings update only their controls and retain unsaved System fields',()=>{
 const controls=['style','height','color','hex'].map(field=>{
  const control=new Element('input');control.dataset.progressPreference=field;return control;
 });
 const card={querySelectorAll:()=>controls};
 for(const control of controls)control.closest=selector=>selector==='[data-progress-settings]'?card:control;
 const ctx=vm.createContext({window:{DesktopSelect:{refresh(){}}}});
 vm.runInContext(read('desktop-progress-model'),ctx);
 const model=ctx.window.DesktopProgressModel,preferences={state:{progress:model.normalizePreferences()},setProgressPreferences(patch){this.state.progress=model.normalizePreferences({...this.state.progress,...patch});}};
 ctx.window.DesktopPreferences=preferences;
 const source=read('desktop-settings');
 vm.runInContext(source.slice(source.indexOf('  function syncProgressSettings('),source.indexOf('  function pinterestAuthSourceLabel(')),ctx);
 controls[0].value='classic';ctx.event={target:controls[0],type:'change'};
 vm.runInContext('updateProgressPreference(event)',ctx);
 assert.equal(controls[1].disabled,true);assert.equal(preferences.state.progress.style,'classic');
 controls[0].value='slosh';vm.runInContext('updateProgressPreference(event)',ctx);
 assert.equal(controls[1].disabled,false);assert.equal(controls[2].value,model.PROGRESS_STYLES.slosh.color);
 // No host rendering function is provided: style/height/color must work without it.
 controls[1].value='56';ctx.event.target=controls[1];vm.runInContext('updateProgressPreference(event)',ctx);
 assert.equal(preferences.state.progress.height,56);
 controls[3].value='#35d1c4';ctx.event.target=controls[3];vm.runInContext('updateProgressPreference(event)',ctx);
 assert.equal(preferences.state.progress.colors.slosh,'#35D1C4');
 controls[3].value='invalid';vm.runInContext('updateProgressPreference(event)',ctx);
 assert.equal(controls[3].getAttribute('aria-invalid'),'true');assert.equal(preferences.state.progress.colors.slosh,'#35D1C4');
});

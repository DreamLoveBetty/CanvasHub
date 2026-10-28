const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
function fixture() {
  const calls = [], storage = new Map();
  const ctx = vm.createContext({console, URL, URLSearchParams, TextEncoder, structuredClone, setTimeout, clearTimeout,
    localStorage: {getItem: k => storage.get(k) || null, setItem: (k,v) => storage.set(k,v)},
    api: {json: async (url, options={}) => {calls.push({url, body: options.body ? JSON.parse(options.body) : null}); return {task_id:'fixture'};}}});
  ctx.window = ctx; ctx.sessionStorage = ctx.localStorage;
  for (const name of ['desktop-state', 'desktop-tasks', 'desktop-api']) vm.runInContext(fs.readFileSync(path.join(root, 'frontend/scripts/'+name+'.js'), 'utf8'), ctx);
  return {ctx, calls, storage};
}
test('Web generation is not silently converted to third party', async () => {
  const {ctx, calls} = fixture();
  const params={googleProviderRoute:'google_web', model:'gemini-3.1-flash-image', ratio:'9:16', resolution:'4k'};
  await ctx.DesktopApi.submitTaskConfig({provider:'google', prompt:'fixture', params});
  assert.equal(calls[0].url, '/generate');
  assert.equal(calls[0].body.params.google_provider_route, 'google_web');
  assert.equal(calls[0].body.quality, '2k');
  assert.equal(calls[0].body.ratio, '9:16');
  assert.equal(calls[0].body.prompt, 'fixture');
  assert.equal(params.resolution, '4k', 'Web defaults must not overwrite the saved OAuth choice');
});
test('Web edit and batch preserve explicit route and public model', async () => {
  const {ctx, calls} = fixture();
  await ctx.DesktopApi.submitTaskConfig({provider:'google', prompt:'fixture', params:{googleProviderRoute:'google_web',ratio:'16:9',resolution:'4k'}, referenceImages:[{base64:'data:image/png;base64,fixture'}]});
  await ctx.DesktopApi.submitBatchConfig({provider:'google', batchPrompts:['one','two'], params:{googleProviderRoute:'google_web',ratio:'4:3',resolution:'4k'}});
  assert.equal(calls[0].url, '/edit');
  assert.equal(calls[0].body.params.google_provider_route, 'google_web');
  assert.equal(calls[0].body.model, 'gemini-3-pro-image');
  assert.equal(calls[0].body.quality, '2k');
  assert.equal(calls[0].body.ratio, '16:9');
  assert.equal(calls[0].body.prompt, 'fixture');
  assert.deepEqual(calls[0].body.images, ['data:image/png;base64,fixture']);
  assert.equal(calls[1].url, '/api/tasks/batch');
  assert.equal(calls[1].body.params.google_provider_route, 'google_web');
  assert.equal(calls[1].body.params.googleProviderRoute, undefined);
  assert.equal(calls[1].body.params.resolution, '2k');
  assert.equal(calls[1].body.params.ratio, '4:3');
  assert.deepEqual(calls[1].body.prompts, ['one','two']);
});

test('Web controls display 2K without replacing the OAuth resolution or model selection', () => {
  const {ctx}=fixture();
  ctx.document={createElement:()=>({dataset:{},hidden:false,textContent:'',title:''})};
  vm.runInContext(fs.readFileSync(path.join(root,'frontend/scripts/desktop-google-web-controls.js'),'utf8'),ctx);
  const field=value=>{
    const label={view:null,querySelector(){return this.view;},appendChild(view){this.view=view;}};
    return {value,hidden:false,dataset:{},label,closest:()=>label};
  };
  const route=field('google_web'), model=field('gemini-3.1-flash-image'), resolution=field('4k');
  const node={querySelector:selector=>selector.includes('googleProviderRoute')?route:selector.includes('resolution')?resolution:model};
  const apply=()=>ctx.DesktopGoogleWebControls.apply(node,'google');
  apply();
  assert.equal(resolution.label.view.textContent,'2K');
  assert.equal(resolution.label.view.hidden,false);
  assert.equal(resolution.hidden,true);
  assert.equal(model.label.view.textContent,'Nano Banana Pro');
  assert.equal(resolution.value,'4k');
  assert.equal(model.value,'gemini-3.1-flash-image');
  for(const value of ['google_pool','third_party']){
    route.value=value;apply();
    assert.equal(resolution.label.view.hidden,true);
    assert.equal(model.label.view.hidden,true);
    assert.equal(resolution.hidden,false);
    assert.equal(model.hidden,false);
    assert.equal(resolution.value,'4k');
    assert.equal(model.value,'gemini-3.1-flash-image');
  }
  route.value='google_web';apply();
  assert.equal(resolution.label.view.textContent,'2K');
  assert.equal(resolution.label.view.hidden,false);
});
test('old default and OAuth and GPT payloads keep their route', async () => {
  const {ctx,calls} = fixture();
  for (const route of [undefined, 'google_pool']) await ctx.DesktopApi.submitTaskConfig({provider:'google',prompt:'fixture',params:{googleProviderRoute:route}});
  await ctx.DesktopApi.submitTaskConfig({provider:'gpt',prompt:'fixture',params:{googleProviderRoute:'google_web',gptProviderRoute:'codex'}});
  assert.equal(calls[0].body.params.google_provider_route,'third_party');
  assert.equal(calls[1].body.params.google_provider_route,'google_pool');
  assert.equal(calls[2].body.gpt_provider_route,'codex');
  assert.equal(calls[2].body.google_provider_route,undefined);
});
test('Web management stays behind authenticated API adapter', async () => {
  const {ctx,calls} = fixture();
  await ctx.DesktopApi.googleWeb('status');
  await ctx.DesktopApi.googleWeb('config',{enabled:true});
  assert.equal(calls[0].url,'/api/google-web/status');
  assert.deepEqual(calls[1].body,{enabled:true});
  assert.throws(()=>ctx.DesktopApi.googleWeb('../secret'));
});

test('same-session expansion uses the protected Web action with an explicit account ID', async () => {
  const {ctx,calls}=fixture();
  await ctx.DesktopApi.googleWeb('account-expand',{account_id:'synthetic-a'});
  assert.equal(calls[0].url,'/api/google-web/account-expand');
  assert.deepEqual(calls[0].body,{account_id:'synthetic-a'});
});

test('Web UI can expand the selected stored session without reading Chrome again', async () => {
  const {ctx}=fixture();
  vm.runInContext(fs.readFileSync(path.join(root,'frontend/scripts/desktop-google-web.js'),'utf8'),ctx);
  const calls=[];
  const state={enabled:true,items:[{id:'synthetic-a',label:'Chrome · Default',authuser:0,email:'a@example.test',enabled:true,state:'available'}],stats:{},capabilities:{}};
  const ui=ctx.DesktopGoogleWeb.create({escapeHtml:String,onRender(){},request:async(action,body)=>{
    calls.push({action,body});return action==='account-expand'?{...state,imported:4,items:[0,1,2,3].map(i=>({...state.items[0],id:'synthetic-'+i,authuser:i,email:i+'@example.test'}))}:state;
  }});
  await ui.refresh();
  assert.match(ui.render(),/data-google-web-action="account-expand"/);
  const control={dataset:{googleWebAction:'account-expand',googleWebId:'synthetic-a'},closest:()=>({})};
  ui.handleClick({preventDefault(){},target:{closest:()=>control}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(calls.map(c=>c.action),['status','account-expand']);
  assert.equal(calls[1].body.account_id,'synthetic-a');
  assert.match(ui.render(),/4 个/);
  assert.match(ui.render(),/3@example.test/);
});

test('Web account UI imports one browser cookie list without persisting credentials', async () => {
  const {ctx, storage} = fixture();
  const file = path.join(root,'frontend/scripts/desktop-google-web.js');
  assert.ok(fs.existsSync(file), 'Independent Web account controller is required');
  vm.runInContext(fs.readFileSync(file,'utf8'),ctx);
  const requests=[];
  const ui=ctx.DesktopGoogleWeb.create({escapeHtml:s=>String(s).replaceAll('<','&lt;'),onRender:()=>{},request:async(action,body)=>{
    requests.push({action,body}); return {enabled:false,items:[],stats:{},capabilities:{browser_import:false,backend_available:true}};
  }});
  await ui.refresh();
  const input={value:'[{"name":"__Secure-1PSID","value":"fixture-cookie-secret"}]'};
  const panel={querySelector:s=>s.includes('label')?{value:'Synthetic'}:input};
  const button={dataset:{googleWebAction:'accounts-import'},closest:()=>panel};
  ui.handleClick({preventDefault(){},target:{closest:s=>s==='[data-google-web-action]'?button:null}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(requests[1].body.accounts.length,1);
  assert.equal(requests[1].body.accounts[0].cookies[0].value,'fixture-cookie-secret');
  assert.equal(input.value,'');
  assert.equal(storage.size,0);
  assert.doesNotMatch(ui.render(),/fixture-cookie-secret|__Secure-1PSID/);
});

test('Web route remains explicit in saved settings and defaults stay third party', () => {
  const {ctx,storage}=fixture();
  assert.equal(ctx.DesktopState.normalizeGoogleProviderRoute(undefined),'third_party');
  ctx.DesktopState.state.params.googleProviderRoute='google_web';
  ctx.DesktopState.saveSettings();
  assert.equal(JSON.parse(storage.get('desktop_canvas_settings_v1')).params.googleProviderRoute,'google_web');
});

test('Chrome discovery shows progress then asks for a Profile without automatically importing', async () => {
  const {ctx,storage}=fixture();
  vm.runInContext(fs.readFileSync(path.join(root,'frontend/scripts/desktop-google-web.js'),'utf8'),ctx);
  const requests=[], initial={enabled:false,items:[],stats:{},capabilities:{browser_import:true,backend_available:true}};
  let finish;
  const ui=ctx.DesktopGoogleWeb.create({escapeHtml:String,onRender(){},request:async(action,body)=>{
    requests.push({action,body});
    if(action==='browser-profiles') return new Promise(resolve=>{finish=resolve;});
    return initial;
  }});
  await ui.refresh();
  const control={dataset:{googleWebAction:'browser-profiles'},closest:()=>({})};
  ui.handleClick({preventDefault(){},target:{closest:()=>control}});
  assert.match(ui.render(),/正在.*Chrome.*Profile/);
  finish({ok:true,items:[{id:'Default',label:'Default'},{id:'Profile 2',label:'Profile 2'}]});
  await new Promise(resolve=>setImmediate(resolve));
  const html=ui.render();
  assert.match(html,/找到 2 个/);
  assert.match(html,/选择.*Profile.*导入/);
  assert.match(html,/<option value="Profile 2">Profile 2<\/option>/);
  assert.match(html,/data-google-web-action="browser-import"/);
  assert.deepEqual(requests.map(r=>r.action),['status','browser-profiles']);
  assert.equal(storage.size,0);
});

test('Chrome permission failure is an alert and leaves existing Web accounts intact', async () => {
  const {ctx}=fixture();
  vm.runInContext(fs.readFileSync(path.join(root,'frontend/scripts/desktop-google-web.js'),'utf8'),ctx);
  const ui=ctx.DesktopGoogleWeb.create({escapeHtml:String,onRender(){},request:async action=>{
    if(action==='browser-profiles')throw Error('请为账号服务 Python 开启完全磁盘访问权限后重启账号服务。');
    return {enabled:false,items:[{id:'fixture-a',label:'Synthetic A',state:'unchecked',enabled:true}],stats:{},capabilities:{browser_import:true}};
  }});
  await ui.refresh();
  const control={dataset:{googleWebAction:'browser-profiles'},closest:()=>({})};
  ui.handleClick({preventDefault(){},target:{closest:()=>control}});
  await new Promise(resolve=>setImmediate(resolve));
  const html=ui.render();
  assert.match(html,/role="alert"/);
  assert.match(html,/完全磁盘访问权限/);
  assert.match(html,/Synthetic A/);
  assert.doesNotMatch(html,/data-google-web-action="browser-import"/);
});

test('Web panel prefers escaped session identity and keeps the import label as provenance', async () => {
  const {ctx, storage}=fixture();
  vm.runInContext(fs.readFileSync(path.join(root,'frontend/scripts/desktop-google-web.js'),'utf8'),ctx);
  const ui=ctx.DesktopGoogleWeb.create({escapeHtml:s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),onRender(){},request:async()=>({
    enabled:true,items:[{id:'fixture-a',label:'Chrome · Default',display_name:'Synthetic <Name>',email:'active@example.test',state:'available',enabled:true},
      {id:'fixture-b',label:'Chrome · Profile 2',email:'second@example.test',state:'unchecked',enabled:true},
      {id:'fixture-c',label:'Unrecognized account',state:'unchecked',enabled:true}],stats:{},capabilities:{}})});
  await ui.refresh();
  const html=ui.render();
  assert.match(html,/<strong>Synthetic &lt;Name&gt;<\/strong>/);
  assert.match(html,/active@example\.test/);
  assert.match(html,/Chrome · Default/);
  assert.match(html,/<strong>second@example\.test<\/strong>/);
  assert.match(html,/<strong>Unrecognized account<\/strong>/);
  assert.doesNotMatch(html,/<Name>/);
  assert.equal(storage.size,0);
});

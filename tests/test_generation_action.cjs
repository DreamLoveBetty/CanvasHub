const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const ctx = vm.createContext({window:{}});
for (const file of ['desktop-state-icon', 'desktop-music-model','desktop-music-view']) vm.runInContext(read(`frontend/scripts/${file}.js`),ctx);
const model = ctx.window.DesktopMusicModel;
const view = ctx.window.DesktopMusicView.create({model,stateIcon:ctx.window.DesktopStateIcon,escapeHtml:s=>String(s??'')});

for (const [status,label,icon,busy] of [
  ['idle','开始生成','idle',false],['queued','排队中','busy',true],['running','生成中','busy',true],
  ['cancelling','停止中','busy',true],['succeeded','已完成','success',false],['partial','结果截断','warning',false],
  ['failed','重试生成','error',false],['interrupted','重试生成','error',false],['cancelled','已停止','stopped',false],
]) test(`music button derives ${status} without mutating task state`,()=>{
  const node={status,jobId:'old-job'};
  const result=model.generationButtonState(node);
  assert.equal(result.label,label);assert.equal(result.icon,icon);assert.equal(result.busy,busy);
  assert.deepEqual(node,{status,jobId:'old-job'});
});
test('submission and cancellation take priority over a previous success',()=>{
  const node={status:'succeeded'};
  assert.equal(model.generationButtonState(node,{submitting:true}).state,'submitting');
  assert.equal(model.generationButtonState(node,{submitting:true,phase:'等待上游转谱'}).state,'waiting');
  assert.equal(model.generationButtonState(node,{submitting:true,cancelRequested:true}).state,'cancelling');
  assert.equal(model.generationButtonState(node,{outcome:'failed'}).state,'failed');
  assert.equal(model.generationButtonState(node,{outcome:'cancelled'}).state,'cancelled');
  assert.equal(model.generationButtonState({status:'running'},{outcome:'failed'}).state,'running');
  assert.equal(model.generationButtonState({status:'unknown'}).state,'idle');
  assert.equal(model.generationButtonState({status:'constructor'}).state,'idle');
});
test('view keeps spinner DOM stable across polls, announces state and unlocks retry',()=>{
  let changes=0;
  const layers=['idle','busy','success','error','warning','stopped'].map(key=>({dataset:{stateIconLayer:key},current:key==='idle'}));
  for(const layer of layers)layer.classList={toggle(_name,current){if(layer.current!==current){changes++;layer.current=current;}}};
  const icon={dataset:{stateIcon:'idle'},querySelectorAll:()=>layers,set innerHTML(_value){throw Error('state paint must retain glyph DOM');}},label={};
  const button={dataset:{},attrs:{},setAttribute(k,v){this.attrs[k]=v;},querySelector(s){return s==='svg'?icon:label;}};
  for(const status of ['queued','running','running','cancelling'])view.paintRunButton(button,model.generationButtonState({status}));
  assert.equal(changes,2);assert.equal(icon.dataset.stateIcon,'busy');assert.equal(button.disabled,true);assert.equal(button.attrs['aria-busy'],'true');assert.equal(label.textContent,'停止中');
  view.paintRunButton(button,model.generationButtonState({status:'succeeded'}));
  assert.equal(changes,4);assert.equal(icon.dataset.stateIcon,'success');assert.equal(button.disabled,false);assert.equal(button.attrs['aria-busy'],'false');assert.match(button.attrs['aria-label'],/重新生成/);
  view.paintRunButton(button,model.generationButtonState({status:'failed'}));
  assert.equal(label.textContent,'重试生成');assert.equal(button.dataset.generationIcon,'error');
});
test('generate actions use only the shared component class; event hooks stay on data attributes',()=>{
  const source=read('frontend/scripts/desktop-canvas-model-nodes.js');
  assert.match(source,/class="desk-generation-action" data-result-run/);
  // The default input node is static markup; it must match the template button.
  assert.match(read('frontend/desktop.html'),/class="desk-generation-action" data-result-run id="deskNodeGenerateBtn" title="开始生成"[\s\S]*?<span class="desk-generation-action__label">开始生成<\/span>/);
  assert.equal((source.match(/desk-generation-action"/g)||[]).length,1);
  assert.match(source,/<span class="desk-generation-action__label">开始生成<\/span>/);
  const html=view.nodeHtml(model.createState('g','music_generate',{}));
  assert.match(html,/desk-music__generate desk-generation-action/);
  assert.match(html,/data-music-action="run"/);assert.doesNotMatch(html,/data-result-run/);
});
test('motion is audio-scoped with reduced-motion support; touched assets cache-busted',()=>{
  const css=read('frontend/styles/desktop-music.css');
  assert.match(css,/@media \(prefers-reduced-motion:reduce\)/);
  assert.doesNotMatch(css,/desk-music__generate[^\n]+svg \{ animation:/);
  const motion=read('frontend/styles/desktop-motion.css');
  assert.match(motion,/data-state-icon-layer="busy"/);
  assert.match(motion,/animation-play-state: running/);
  assert.match(motion,/prefers-reduced-motion: reduce[\s\S]*desk-state-icon__glyph[\s\S]*animation: none/);
  const controls=read('frontend/styles/desktop-controls.css');
  assert.match(controls,/desk-generation-action:not\(:disabled\),/);
  // Busy keeps the primary finish for every generate action, not a per-domain list.
  assert.match(controls,/\.desk-node \.desk-generation-action\[aria-busy="true"\]/);
  assert.doesNotMatch(controls,/desk-music__generate\.desk-generation-action/);
  const html=read('frontend/desktop.html');
  // Shared controls/model assembly also evolve for other domains. Their latest
  // version is asserted by that domain's tests; do not freeze it to music's date.
  for(const file of ['styles/desktop-controls.css','scripts/desktop-canvas-model-nodes.js'])assert.match(html,new RegExp(file.replaceAll('.','\\.')+'\\?v=[A-Za-z0-9._-]+'));
  for(const file of ['styles/desktop-music.css','scripts/desktop-music-view.js'])assert.ok(html.includes(file+'?v='+(file.endsWith('.js')?'20261010-segment-bank1':'20261004-state-icons1')));
  for(const file of ['scripts/desktop-music-model.js','scripts/desktop-canvas-music.js'])assert.ok(html.includes(file+'?v=20260919-music-status2'));
});
test('every generate action is one component: no legacy button classes, no per-domain list, all states shared',()=>{
  const sources=fs.readdirSync(path.join(root,'frontend/scripts')).filter(f=>f.endsWith('.js')).map(f=>read(`frontend/scripts/${f}`)).join('\n')+read('frontend/desktop.html');
  const lists=[...sources.matchAll(/class="([^"]*\bdesk-generation-action\b[^"]*)"/g)].map(m=>m[1].split(/\s+/));
  assert.ok(lists.length>=8,'all canvas generate actions are found');
  for(const list of lists)assert.ok(!list.includes('desk-button')&&!list.includes('desk-button--generate'),list.join(' '));
  const controls=read('frontend/styles/desktop-controls.css');
  const block=controls.slice(controls.indexOf('/* Canvas generate action:'),controls.indexOf('/* Settings-only model tools'));
  assert.doesNotMatch(block,/desk-(music|video-control|topaz-video|cyimg)__/,'shared rules do not name domains');
  for(const state of [':not(:disabled)','[aria-busy="true"]',':disabled:not([aria-busy="true"])',':hover:not(:disabled)',':active:not(:disabled)'])
    assert.ok(block.includes(`.desk-node .desk-generation-action${state}`),state);
  // Footer placement belongs to each node, not to the component.
  assert.doesNotMatch(block,/margin-left/);
});

// Pure SVG presentation contracts: no browser, tasks, media or personal data.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname,'..');
const read = file => fs.readFileSync(path.join(root,file),'utf8');
function load(){
  const context={window:{}};
  vm.runInNewContext(read('frontend/scripts/desktop-state-icon.js'),context);
  return context.window.DesktopStateIcon;
}
const icons={idle:'<path d="M1 2"/>',busy:'<circle cx="12" cy="12" r="8"/>',success:'<path d="M3 4"/>'};
function svgFixture(initial='idle'){
  let changes=0;
  const layers=Object.keys(icons).map(key=>({dataset:{stateIconLayer:key},current:key===initial,classList:{toggle(name,on){if(on!==this.owner.current){this.owner.current=on;changes++;}}}}));
  layers.forEach(layer=>layer.classList.owner=layer);
  const svg={dataset:{stateIcon:initial},querySelectorAll:()=>layers};
  Object.defineProperty(svg,'innerHTML',{set(){throw Error('paint must not replace SVG DOM');}});
  return{svg,layers,changes:()=>changes};
}
test('markup keeps every glyph in one accessible, fixed-size SVG shell',()=>{
  const icon=load(),html=icon.html(icons,'idle');
  assert.equal((html.match(/<svg /g)||[]).length,1);
  assert.equal((html.match(/data-state-icon-layer=/g)||[]).length,3);
  assert.equal((html.match(/is-current/g)||[]).length,1);
  assert.match(html,/class="desk-state-icon".*aria-hidden="true"/);
  assert.match(html,/data-state-icon="idle"/);
  assert.ok(!html.includes(' hidden'));
});
test('a repeated busy poll leaves the DOM and rotation uninterrupted',()=>{
  const icon=load(),f=svgFixture();
  assert.equal(icon.paint(f.svg,'busy'),true);
  const count=f.changes();
  for(let i=0;i<20;i++)assert.equal(icon.paint(f.svg,'busy'),false);
  assert.equal(f.changes(),count);
  assert.deepEqual(f.layers.map(l=>l.current),[false,true,false]);
});
test('rapid reversal always picks one current glyph, without timers or stale completion',()=>{
  const icon=load(),f=svgFixture();
  for(const state of ['busy','success','busy','idle','success','idle']){
    icon.paint(f.svg,state);
    assert.equal(f.layers.filter(l=>l.current).length,1);
    assert.equal(f.layers.find(l=>l.current).dataset.stateIconLayer,state);
    assert.equal(f.svg.dataset.stateIcon,state);
  }
});
test('unknown/prototype state falls back to an actual glyph and absent element is a no-op',()=>{
  const icon=load(),f=svgFixture('busy');
  icon.paint(f.svg,'constructor');assert.equal(f.svg.dataset.stateIcon,'idle');
  assert.equal(icon.paint(null,'busy'),false);
  assert.match(icon.html(icons,'constructor'),/data-state-icon="idle"/);
  assert.throws(()=>icon.html({'bad"key':'<path/>'}),/Invalid/);
});
test('the helper owns presentation only and motion respects reduced-motion',()=>{
  const source=read('frontend/scripts/desktop-state-icon.js'),css=read('frontend/styles/desktop-motion.css');
  assert.doesNotMatch(source,/setTimeout|requestAnimationFrame|fetch\(|DesktopState\.|localStorage/);
  assert.match(css,/\.desk-state-icon__layer \{[\s\S]*?opacity: 0;[\s\S]*?filter: blur\(var\(--desk-motion-icon-blur\)\)/);
  assert.match(css,/\.desk-state-icon__layer\.is-current \{[\s\S]*?opacity: 1;[\s\S]*?filter: blur\(0\)/);
  assert.match(css,/animation-play-state: paused/);
  assert.match(css,/animation-play-state: running/);
  const reduced=css.slice(css.lastIndexOf('@media (prefers-reduced-motion: reduce)'));
  assert.match(reduced,/desk-state-icon__layer[\s\S]*?filter: none/);
  assert.match(reduced,/transition: none !important/);
  assert.match(reduced,/transform: none !important/);
  assert.match(reduced,/filter: none !important/);
  assert.match(reduced,/desk-state-icon__glyph[\s\S]*?animation: none/);
});
test('all consumers receive an explicit display-only dependency in loading order',()=>{
  const html=read('frontend/desktop.html'),host=read('frontend/scripts/desktop-canvas.js');
  const helper=html.indexOf('scripts/desktop-state-icon.js?');assert.ok(helper>=0);
  for(const name of ['desktop-canvas-audio','desktop-music-view','desktop-canvas-topaz','desktop-video-control-view','desktop-topaz-video-view','desktop-topaz-video-workbench']){
    assert.ok(helper<html.indexOf(`scripts/${name}.js?`),name);
    assert.match(read(`frontend/scripts/${name}.js`),/stateIcon/);
    assert.ok(html.includes(`scripts/${name}.js?v=${name.startsWith('desktop-topaz-video-workbench') ? '20261005-topaz-pipeline1' : name === 'desktop-canvas-topaz' ? '20261009-generation-action-unify1' : name === 'desktop-music-view' ? '20261010-segment-bank1' : '20261010-node-keys1'}`),name);
  }
  assert.match(host,/const stateIcon = window\.DesktopStateIcon;/);
  assert.match(host,/DesktopCanvasAudio\.create\(\{\s*stateIcon,/);
  assert.ok(html.includes('scripts/desktop-canvas.js?v=20261010-marquee-frame1'));
});
function displayFixture(keys){
  const layers=keys.map(key=>({dataset:{stateIconLayer:key},current:key==='idle'}));
  layers.forEach(layer=>layer.classList={toggle(_name,value){layer.current=value;}});
  const svg={dataset:{stateIcon:'idle'},querySelectorAll:()=>layers};
  Object.defineProperty(svg,'innerHTML',{set(){throw Error('must retain layers');}});
  const label={textContent:''},button={dataset:{},attrs:{},setAttribute(k,v){this.attrs[k]=v;},querySelector:s=>s==='svg'?svg:label};
  const fields=new Map();
  const q=selector=>{
    if(/\[data-(control|topaz-video|result)-run\]/.test(selector))return button;
    if(!fields.has(selector))fields.set(selector,{dataset:{},classList:{toggle(){}},style:{setProperty(){}},textContent:''});
    return fields.get(selector);
  };
  return{svg,layers,label,button,root:{querySelector:q,querySelectorAll:()=>[]}};
}
for(const [prefix,type] of [['VideoControl','video_control'],['TopazVideo','topaz_video']])test(`${type} painting preserves task state, availability and busy/accessibility contracts`,()=>{
  const context={window:{}};
  for(const name of ['desktop-topaz-video-pipeline','desktop-state-icon',prefix==='VideoControl'?'desktop-video-control-model':'desktop-topaz-video-model',prefix==='VideoControl'?'desktop-video-control-view':'desktop-topaz-video-view'])vm.runInNewContext(read(`frontend/scripts/${name}.js`),context);
  const model=context.window[`Desktop${prefix}Model`],view=context.window[`Desktop${prefix}View`].create({model,escapeHtml:String,stateIcon:context.window.DesktopStateIcon});
  const node=model.normalize({id:'synthetic',type}),f=displayFixture(['idle','busy','succeeded','failed']);
  const catalog=[{id:node.model,available:true,scales:[node.scale],verified:true}];
  for(const [status,icon,busy] of [['queued','busy',true],['running','busy',true],['succeeded','succeeded',false],['interrupted','failed',false],['cancelled','idle',false]]){
    node.status=status;const before=JSON.stringify(node);
    if(type==='video_control')view.paint(f.root,node,null,false);
    else view.paint(f.root,node,null,false,catalog);
    assert.equal(JSON.stringify(node),before);
    assert.equal(f.svg.dataset.stateIcon,icon);
    assert.equal(f.layers.filter(l=>l.current).length,1);
    assert.equal(f.button.attrs['aria-busy'],String(busy));
    assert.equal(f.button.disabled,busy);
    assert.equal(f.button.attrs['aria-label'],f.label.textContent);
  }
  if(type==='topaz_video'){
    node.status='idle';view.paint(f.root,node,null,false,[]);assert.equal(f.button.disabled,true,'unavailable model must remain disabled');
  }
});
test('Topaz image painting never changes generation state while updating retained glyphs',()=>{
  const context={window:{},DesktopState:{isInFlight:s=>['queued','processing'].includes(s),isSuccess:s=>s==='succeeded',isFailure:s=>s==='failed'}};
  for(const name of ['desktop-state-icon','desktop-topaz-model','desktop-canvas-topaz'])vm.runInNewContext(read(`frontend/scripts/${name}.js`),context);
  const model=context.window.DesktopTopazModel,node=model.normalize({id:'t',type:'topaz'}),f=displayFixture(['idle','busy','success','error']);
  const state={canvas:{nodes:{t:node},edges:[]},outputs:{t:{status:'idle'}}};
  const controller=context.window.DesktopCanvasTopaz.create({model,stateIcon:context.window.DesktopStateIcon,getState:()=>state,getNodeElement:()=>f.root,getReferences:()=>[]});
  for(const [status,icon,busy] of [['queued','busy',true],['processing','busy',true],['succeeded','success',false],['failed','error',false],['idle','idle',false]]){
    state.outputs.t.status=status;const before=JSON.stringify(state);controller.paint('t');
    assert.equal(JSON.stringify(state),before);assert.equal(f.svg.dataset.stateIcon,icon);assert.equal(f.button.disabled,busy);assert.equal(f.button.attrs['aria-busy'],String(busy));
  }
});

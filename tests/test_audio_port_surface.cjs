// Border-box contract for all node swell overlays; no DOM/network/storage required.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
function fixture({borderLeft=2, borderTop=2, imageGroup=false, swell='liquid'}={}) {
  const context={window:{DesktopPreferences:{state:{connectionSwellStyle:swell}}},getComputedStyle:el=>el.computedStyle,DesktopState:{state:{canvas:{scale:1}}}};
  vm.createContext(context);
  for(const file of ['desktop-canvas-port-geometry.js','desktop-canvas-port-interaction.js'])vm.runInContext(fs.readFileSync(path.join(root,'frontend/scripts',file),'utf8'),context);
  const shape=()=>({attributes:{},style:{setProperty(k,v){this[k]=v;}},dataset:{},setAttribute(k,v){this.attributes[k]=v;},getAttribute(k){return this.attributes[k];},classList:{toggle(){},contains(){return false;}}});
  const base=shape();Object.assign(base.attributes,{x:'8',y:'12',width:'600',height:'300',rx:'16'});
  const node=shape();Object.assign(node,{offsetWidth:800,offsetHeight:360,computedStyle:{borderTopLeftRadius:'26px',borderLeftWidth:`${borderLeft}px`,borderTopWidth:`${borderTop}px`},matches:()=>imageGroup,querySelector:()=>base});
  node.dataset.nodeId='fixture';
  const state={nodeElement:node,svg:shape(),paintRect:shape(),innerRect:shape(),maskPath:shape(),floatingPort:shape(),amplitude:{value:1,target:1,velocity:0},position:{value:NaN,target:NaN,velocity:0}};
  const api=context.window.DesktopCanvasPortInteraction.create({...context.window.DesktopCanvasPortGeometry,
    FLOATING_SWELL_BORDER_PADDING_PX:36,FLOATING_SWELL_VISIBLE_THRESHOLD_PX:0.25,
    FLOATING_SWELL_PEAK_PX:7,FLOATING_DROPLET_PEAK_PX:9,IMAGE_GROUP_LIQUID_VISIBLE_OUTSET_PX:2,FLOATING_SWELL_LINK_OVERLAP_SCREEN_PX:1.25,
    getNodeState:()=>({id:'fixture',x:20,y:30,width:800,height:360}),clamp:(n,min,max)=>Math.max(min,Math.min(max,n)),
    activeInteractionRef:{current:null},contextMenuConnectionSourceIdRef:{current:''},contextMenuElRef:{current:null},
    portOutwardVector:side=>({left:{x:-1,y:0},right:{x:1,y:0},top:{x:0,y:-1},bottom:{x:0,y:1}}[side])});
  return {api,state,node};
}
for (const border of [0,1,2,4,0.5]) test(`swell SVG uses border-box dimensions and origin for ${border}px border`,()=>{
 const {api,state}=fixture({borderLeft:border,borderTop:border});api.updateFloatingSwellGeometry(state);
 assert.equal(state.svg.attributes.viewBox,'-36 -36 872 432');
 assert.equal(state.svg.style.width,'872px');assert.equal(state.svg.style.height,'432px');
 assert.equal(parseFloat(state.svg.style.left)+border+36,0);assert.equal(parseFloat(state.svg.style.top)+border+36,0);
 assert.equal(state.innerRect.attributes.x,'0');assert.equal(state.innerRect.attributes.width,'800');
});
test('asymmetric border changes invalidate geometry cache even without resizing',()=>{
 const {api,state,node}=fixture();api.updateFloatingSwellGeometry(state);const old=state.geometry;
 api.updateFloatingSwellGeometry(state);assert.equal(state.geometry,old);
 Object.assign(node.computedStyle,{borderLeftWidth:'5px',borderTopWidth:'3px'});api.updateFloatingSwellGeometry(state);
 assert.notEqual(state.geometry,old);assert.equal(state.svg.style.left,'-41px');assert.equal(state.svg.style.top,'-39px');
 node.offsetWidth=900;api.updateFloatingSwellGeometry(state);assert.equal(state.svg.style.width,'972px');
});
test('resolved border-box sizes retain fractional image-group dimensions',()=>{
 const {api,state,node}=fixture();Object.assign(node.computedStyle,{width:'307.1875px',height:'201.59375px',boxSizing:'border-box'});
 api.updateFloatingSwellGeometry(state);assert.equal(state.width,307.1875);assert.equal(state.height,201.59375);
 assert.equal(state.svg.style.width,'379.1875px');assert.equal(state.svg.style.height,'273.59375px');
});
test('content-box styles include padding and each border exactly once',()=>{
 const {api,state,node}=fixture({borderLeft:2,borderTop:1});Object.assign(node.computedStyle,{width:'100.5px',height:'60.25px',boxSizing:'content-box',borderRightWidth:'4px',borderBottomWidth:'3px',paddingLeft:'5px',paddingRight:'7px',paddingTop:'6px',paddingBottom:'8px'});
 api.updateFloatingSwellGeometry(state);assert.equal(state.width,118.5);assert.equal(state.height,78.25);
});
for(const swell of ['liquid','droplet']) test(`${swell} hit target and public anchor retain the same border-box point`,()=>{
 const {api,state}=fixture({borderLeft:4,borderTop:3,swell});api.renderFloatingSwellState(state);
 const port=state.floatingPort;
 assert.equal(parseFloat(port.style['--desk-floating-x'])+4,Number(port.dataset.anchorX));
 assert.equal(parseFloat(port.style['--desk-floating-y'])+3,Number(port.dataset.anchorY));
 assert.equal(port.dataset.portSide,'right');assert.ok(Number(port.dataset.anchorX)>800);
 port.dataset.edgeHandle='true';const anchor=api.getConnectionPortAnchor('fixture',port,'right');
 assert.equal(anchor.x,20+Number(port.dataset.anchorX)-1.25);assert.equal(anchor.y,30+Number(port.dataset.anchorY));
 assert.ok(!/NaN|Infinity/.test(state.maskPath.attributes.d));
});
test('image-group inset/outset geometry remains independent of CSS border compensation',()=>{
 const {api,state}=fixture({imageGroup:true,borderLeft:1,borderTop:1});api.updateFloatingSwellGeometry(state);
 assert.equal(state.geometryX,6);assert.equal(state.geometryY,10);assert.equal(state.geometryWidth,604);assert.equal(state.geometryHeight,304);assert.equal(state.radius,18);
 assert.equal(state.innerRect.attributes.x,'6');assert.equal(state.svg.style.left,'-37px');
});
test('audio daylight consumes existing canvas palette and preserves its dark override',()=>{
 const css=fs.readFileSync(path.join(root,'frontend/styles/desktop-audio.css'),'utf8');
 const day=css.slice(0,css.indexOf('body.desk-app .desk-node--audio.is-selected'));
 for(const token of ['--desk-node-glass-background','--desk-node-ink','--desk-node-muted-ink','--desk-node-sheen-background','--desk-node-glass-shadow','--desk-blue-frost','--desk-blue-mist'])assert.ok(day.includes(`var(${token})`),token);
 assert.ok(!/#eceded|#343a3c/.test(day));assert.match(css,/--desk-audio-face: #323839/);
 const html=fs.readFileSync(path.join(root,'frontend/desktop.html'),'utf8');
 for(const name of ['styles/desktop-audio.css','scripts/desktop-canvas-port-interaction.js'])assert.match(html,new RegExp(name.replaceAll('.', '\\.')+'\\?v=[0-9a-z._-]+'));
});

// Synthetic DOM/RAF/clock; no real workflow, credentials, network or browser.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, 'frontend', file), 'utf8');
function fixture({ scale = 1 } = {}) {
  let now = 0, sequence = 0, reduced = false;
  const timers = new Map(), frames = new Map(), animations = [], refreshes = [];
  function events() {
    const listeners = new Map();
    return {
      addEventListener(type, fn) { if (!listeners.has(type)) listeners.set(type, new Set()); listeners.get(type).add(fn); },
      removeEventListener(type, fn) { listeners.get(type)?.delete(fn); },
      dispatch(type, event = {}) { [...(listeners.get(type) || [])].forEach(fn => fn(event)); },
      listenerCount() { return [...listeners.values()].reduce((n, set) => n + set.size, 0); }
    };
  }
  function element() {
    return { ...events(), style: { translate:'' }, dataset: {}, children: [], attributes: {}, isConnected: true,
      classList: { contains: () => true }, offsetWidth: 200, offsetHeight: 240, clientLeft: 1, clientTop: 1,
      setAttribute(name, value) { this.attributes[name] = String(value); }, getAttribute(name) { return this.attributes[name]; },
      appendChild(child) { this.children.push(child); child.parentNode = this; },
      remove() { this.isConnected = false; if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(el => el !== this); },
      animate(keyframes, options) {
        const animation = { keyframes, options, cancelled: false, cancel() { this.cancelled = true; } };
        animations.push(animation); return animation;
      }
    };
  }
  const document = { ...events(), hidden: false, createElementNS: element };
  const motionQuery = events(), window = { ...events(), matchMedia: () => motionQuery };
  const context = { window, document, performance: { now: () => now }, getComputedStyle: () => ({borderTopLeftRadius:'8px'}),
    requestAnimationFrame(fn) { const id=++sequence; frames.set(id,fn); return id; }, cancelAnimationFrame(id) { frames.delete(id); },
    setTimeout(fn, delay) { const id = ++sequence; timers.set(id, { fn, at: now + delay }); return id; }, clearTimeout(id) { timers.delete(id); }
  };
  vm.createContext(context); vm.runInContext(read('scripts/desktop-canvas-connection-feedback.js'), context);
  const activeInteractionRef = { current: { type: 'connect', fromNodeId: 'from' } };
  const nodes = { from: {x:100,y:0}, to: {x:500,y:200}, other: {} }, elements = {};
  const layer=element(), wire=element();wire.setAttribute('d','M 200 100 L 500 320');layer.appendChild(wire);
  const api = window.DesktopCanvasConnectionFeedback.create({ activeInteractionRef,
    getNodeState: id => nodes[id], getNodeElement: id=>elements[id], getEdgeVisualPath: ()=>wire,
    refreshNodeConnectionGeometry: id => refreshes.push({id, offset:{...api.getNodeVisualOffset(id)}}), prefersReducedMotion: () => reduced });
  function target(nodeId = 'to', phase='near') {
    const nodeElement = elements[nodeId] ||= element(), port = element();
    Object.assign(nodeElement, { dataset: { nodeId }, getBoundingClientRect: () => ({ left: 500, top: 200 }) });
    Object.assign(port, { offsetWidth: 9, getBoundingClientRect: () => ({
      left: 500 - 8 * scale, right: 500 + scale, top: 200 + 86 * scale, bottom: 200 + 114 * scale,
      width: 9 * scale, height: 28 * scale
    }) });
    return { nodeId, nodeElement, port, side: 'left', phase, strength: 1/3,
      pointer:{x:500-8*scale-12,y:200+100*scale}, get rect() { return port.getBoundingClientRect(); } };
  }
  const to = target();
  function tick(ms) {
    now+=ms;
    for(const [id,timer] of [...timers]) if(timer.at<=now) { timers.delete(id);timer.fn(); }
    const queued=[...frames.values()];frames.clear();queued.forEach(fn=>fn(now));
  }
  const commit=(approach)=>{activeInteractionRef.current=null;api.playCommit({edgeId:'edge',fromNodeId:'from',toNodeId:'to',approach});};
  return { api, to, target, nodes, elements, activeInteractionRef, document, window, motionQuery, timers, frames, animations, refreshes, layer, wire, tick, commit,
    setScale(value) { scale = value; }, reduce(value) { reduced = value; motionQuery.dispatch('change', { matches: value }); },
    get listeners() { return document.listenerCount() + window.listenerCount() + motionQuery.listenerCount(); },
    get overlay() { return to.nodeElement.children[0]; } };
}

test('one pinned layered arc near the input, no graph/edge updates or accumulating effects',()=>{
  const h=fixture(), before=JSON.stringify(h.nodes);h.api.updateProximity(h.to);
  const root=h.overlay,arc=root.children[0],wave=arc.children[1];
  assert.equal(root.attributes['aria-hidden'],'true');assert.equal(root.children.length,2);
  assert.equal(arc.children.length,3,'halo, color body and bright core share one local arc');
  assert.equal(arc.attributes.class,'desk-connection-proximity__arc');
  const initial=wave.getAttribute('d');for(let i=0;i<80;i++)h.api.updateProximity(h.to);
  assert.equal(h.overlay,root);assert.equal(h.frames.size,1);assert.equal(h.timers.size,0);
  h.tick(150);assert.notEqual(wave.getAttribute('d'),initial);assert.match(wave.getAttribute('d'),/^M -20\.000 100\.000/);
  assert.match(wave.getAttribute('d'),/L -8\.000 100\.000$/);assert.equal(h.refreshes.length,0);assert.equal(JSON.stringify(h.nodes),before);
  assert.ok(arc.children.every(layer=>layer.getAttribute('d')===wave.getAttribute('d')));
});
test('arc reshapes rapidly with bounded angular bends, smooth pose boundaries and steady light',()=>{
  const h=fixture();h.api.updateProximity(h.to);const arc=h.overlay.children[0],wave=arc.children[1];
  const points=()=>wave.getAttribute('d').match(/-?\d+\.\d+/g).map(Number);
  const frames=[points()];
  for(let i=0;i<20;i++){
    h.tick(16);const p=points();frames.push(p);
    assert.equal(p.length,18,'eight angular segments, not a slow dense sine wave');
    assert.deepEqual(p.slice(0,2),[-20,100]);assert.deepEqual(p.slice(-2),[-8,100]);
    assert.ok(p.every((v,i)=>i%2===0||Math.abs(v-100)<=3.534),'bounded local arc envelope');
    assert.equal(arc.style.opacity,'1','fast movement, not fast on/off flashing');
    assert.ok(arc.children.every(layer=>layer.getAttribute('d')===wave.getAttribute('d')));
  }
  const travel=(a,b)=>Math.max(...a.map((v,i)=>Math.abs(v-b[i])));
  assert.ok(travel(frames[0],frames[2])>.5,'noticeable change within 32ms');
  assert.ok(travel(frames[0],frames[5])>1,'new shape within 80ms');
  assert.ok(Math.max(...frames.flatMap(p=>p.filter((_,i)=>i%2).map(y=>Math.abs(y-100))))>1.8,'stronger than the old subtle ripple');
  const continuity=fixture();continuity.api.updateProximity(continuity.to);
  const shape=()=>continuity.overlay.children[0].children[1].getAttribute('d').match(/-?\d+\.\d+/g).map(Number);
  continuity.tick(79.99);const before=shape();continuity.tick(.02);
  assert.ok(travel(before,shape())<.01,'pose boundaries must not teleport');
});
for(const scale of [.1,.3,1,2])test(`visuals inherit node zoom ${scale}; hit bounds do not move`,()=>{
  const h=fixture({scale}),rect=h.to.rect;h.api.updateProximity(h.to);
  assert.equal(h.overlay.style.transform,undefined);assert.ok(Math.abs(Number(h.overlay.children[1].getAttribute('cx'))+8)<1e-8);
  assert.ok(Math.abs(Number(h.overlay.children[1].getAttribute('cy'))-100)<1e-8);assert.deepEqual(h.to.rect,rect);
  assert.equal(h.overlay.attributes.width,'200');assert.equal(h.overlay.style.left,'-1px');
});
test('snap settles wave once in 100ms; keeping the snapped ring never shakes/commits',()=>{
  const h=fixture();h.api.updateProximity(h.to);h.tick(40);
  const snapped={...h.to,phase:'snapped',strength:0};h.api.updateProximity(snapped);const root=h.overlay;
  h.tick(60);assert.ok(Number(root.children[0].style.opacity)>0);
  h.api.updateProximity(snapped);h.tick(50);assert.equal(root.children[0].style.opacity,'0');assert.equal(h.frames.size,0);
  assert.equal(h.refreshes.length,0);assert.equal(h.timers.size,0);assert.equal(h.to.nodeElement.style.translate,'');
});
test('switch target/leave cancels old root/RAF and re-entry does not multiply loops',()=>{
  const h=fixture();h.api.updateProximity(h.to);const old=h.overlay;h.api.updateProximity(h.target('other'));
  assert.equal(old.isConnected,false);assert.equal(h.frames.size,1);h.api.updateProximity(null);
  assert.equal(h.frames.size,0);assert.equal(h.listeners,0);h.api.updateProximity(h.to);assert.equal(h.frames.size,1);
});
test('commit responds without teleporting, peaks promptly and softly returns within 300ms',()=>{
  const h=fixture(),before=JSON.stringify(h.nodes);h.api.updateProximity(h.to);h.commit();
  assert.equal(h.overlay.attributes.class,'desk-connection-impact');
  assert.equal(h.layer.children.length,2);
  assert.equal(h.api.getNodeVisualOffset('to').x,0,'commit must preserve the pre-contact position');
  assert.equal(h.to.nodeElement.style.translate,'0px 0px');
  assert.equal(h.api.getNodeVisualOffset('from').x,0);assert.equal(h.refreshes.at(-1).id,'to');
  h.tick(1);assert.ok(h.api.getNodeVisualOffset('to').x>0 && h.api.getNodeVisualOffset('to').x<.3,'no trigger delay or step at t=0');
  h.tick(15);const first=h.api.getNodeVisualOffset('to').x;assert.ok(first>2 && first<4,'first visible frame already reacts');
  h.tick(34);const peak=h.api.getNodeVisualOffset('to').x;assert.ok(peak>5 && peak<6);
  h.tick(50);assert.ok(h.api.getNodeVisualOffset('to').x>0 && h.api.getNodeVisualOffset('to').x<peak);
  h.tick(90);const undershoot=h.api.getNodeVisualOffset('to').x;assert.ok(undershoot<-.4 && undershoot>-1);
  h.tick(109);assert.ok(Math.abs(h.api.getNodeVisualOffset('to').x)<.001,'smooth rest, not a hard end cutoff');h.tick(1);
  assert.equal(h.api.getNodeVisualOffset('to').x,0);assert.equal(h.to.nodeElement.style.translate,'');assert.equal(h.frames.size,0);
  h.tick(180);assert.equal(h.overlay,undefined);assert.equal(h.layer.children.length,1);assert.equal(h.timers.size,0);assert.equal(h.listeners,0);
  assert.equal(JSON.stringify(h.nodes),before);assert.ok(h.animations.every(a=>a.cancelled));
});
test('bounded two-dimensional recoil follows the approach, with safe inward fallback',()=>{
  for(const approach of [{x:20,y:-10},{x:20,y:10},{x:1,y:10000},{x:0,y:0},{x:-10,y:20},{x:NaN,y:1},undefined]) {
    const h=fixture();h.commit(approach);h.tick(50);const p=h.api.getNodeVisualOffset('to');
    assert.ok(Number.isFinite(p.x)&&Number.isFinite(p.y));assert.ok(p.x>4.5 && Math.hypot(p.x,p.y)<6);
    assert.ok(Math.abs(p.y)<2.3,'input normal remains dominant, even with grazing approach');
    if(approach?.x>0 && Number.isFinite(approach.y))assert.equal(Math.sign(p.y),Math.sign(approach.y));
    else assert.equal(p.y,0);
    assert.deepEqual(h.refreshes.at(-1).offset,{x:p.x,y:p.y},'both axes reach attached wire geometry');
    h.tick(250);assert.equal(h.api.getNodeVisualOffset('to').x,0);assert.equal(h.api.getNodeVisualOffset('to').y,0);
  }
});
test('contact bloom, tapered light layers and wire share the commit and stay locally bounded',()=>{
  const h=fixture();h.commit();
  const children=h.overlay.children;
  const waves=children.filter(el=>el.attributes.class?.includes('desk-connection-impact__wave'));
  assert.equal(waves.length,6,'two directions, each with halo/tail/core');
  assert.ok(children.some(el=>el.attributes.class==='desk-connection-impact__bloom'));
  assert.ok(waves.every(el=>el.attributes['stroke-dasharray'].endsWith(' 2')),'no repeated dash at the far end');
  assert.ok(h.animations.every(a=>!a.options.delay && a.options.duration<=480));
  assert.ok(waves.every(el=>!el.attributes.filter && !el.style.filter),'no node-sized blur surface');
});
test('repeated commits replace rather than stack; existing transforms are preserved',()=>{
  const h=fixture();h.to.nodeElement.style.transform='scale(1.1)';h.to.nodeElement.style.translate='';
  h.commit();h.tick(70);const old=h.overlay;h.commit();assert.equal(old.isConnected,false);assert.equal(h.frames.size,1);assert.equal(h.timers.size,1);
  h.api.clear();assert.equal(h.to.nodeElement.style.transform,'scale(1.1)');assert.equal(h.to.nodeElement.style.translate,'');assert.equal(h.frames.size,0);
});
for(const stage of ['near','impact'])for(const reason of ['blur','pagehide','hidden','reduced','escape','target-deleted','source-deleted'])test(`${stage}: ${reason} releases all resources and restores wires`,()=>{
  const h=fixture();if(stage==='near')h.api.updateProximity(h.to);else {h.commit();h.tick(60);}
  if(['blur','pagehide'].includes(reason))h.window.dispatch(reason);
  if(reason==='hidden'){h.document.hidden=true;h.document.dispatch('visibilitychange');}
  if(reason==='reduced')h.reduce(true);
  if(reason==='escape')h.window.dispatch('keydown',{key:'Escape'});
  if(reason==='target-deleted')h.api.discardNode(h.to.nodeElement);
  if(reason==='source-deleted')h.api.discardNode({dataset:{nodeId:'from'}});
  h.tick(16);assert.equal(h.overlay,undefined);assert.equal(h.listeners,0);assert.equal(h.timers.size,0);assert.equal(h.frames.size,0);
  assert.equal(h.to.nodeElement.style.translate,'');assert.equal(h.api.getNodeVisualOffset('to').x,0);
});
test('next manipulation cancels recoil before node drag/pan; detached DOM or replaced workflow also cancels',()=>{
  for(const reason of ['pointerdown','dom','overlay','workflow','source','edge']) {
    const h=fixture();h.commit();h.tick(60);
    if(reason==='pointerdown')h.window.dispatch('pointerdown');
    if(reason==='dom')h.to.nodeElement.isConnected=false;
    if(reason==='overlay')h.overlay.remove();
    if(reason==='workflow')h.nodes.to={...h.nodes.to};
    if(reason==='source')delete h.nodes.from;
    if(reason==='edge')h.wire.isConnected=false;
    h.tick(16);assert.equal(h.overlay,undefined,reason);assert.equal(h.frames.size,0);assert.equal(h.listeners,0);
  }
});
test('reduced motion uses only a static ring and no frame/geometry animation',()=>{
  const h=fixture();h.reduce(true);h.api.updateProximity(h.to);
  assert.equal(h.overlay.children[0].style.opacity,'0');assert.equal(h.frames.size,0);
  h.commit();assert.equal(h.overlay.children.length,1);assert.equal(h.frames.size,0);assert.equal(h.animations.length,0);
  assert.equal(h.refreshes.length,0);h.tick(220);assert.equal(h.overlay,undefined);assert.equal(h.listeners,0);
});
test('feedback module is loaded before host; old splash removed; overlays are hit-transparent and theme-local',()=>{
  const html=read('desktop.html'),name='scripts/desktop-canvas-connection-feedback.js';
  assert.ok(html.indexOf(name)<html.indexOf('scripts/desktop-canvas.js?'));
  for(const asset of [name,'scripts/desktop-canvas-connections.js','scripts/desktop-canvas-port-interaction.js',
    'scripts/desktop-canvas.js','styles/desktop-canvas-nodes.css','styles/desktop-tokens.css']) {
    const changed=[name,'styles/desktop-canvas-nodes.css'];
    const version=asset==='styles/desktop-tokens.css'?'20261009-settings-drawer2':asset==='scripts/desktop-canvas.js'?'20261007-node-progress4':changed.includes(asset)?'20261007-connection-arc1':asset==='scripts/desktop-canvas-connections.js'?'20261007-connection-feedback-natural1':'20261007-connection-feedback1';
    assert.ok(html.includes(`${asset}?v=${version}`));
  }
  const css=read('styles/desktop-canvas-nodes.css');assert.doesNotMatch(css,/desk-connection-splash/);
  assert.match(css,/\.desk-node > :is\(\.desk-connection-proximity, \.desk-connection-impact\) \{[^}]*pointer-events: none;/);
  assert.match(css,/color: var\(--desk-node-edge-stroke\)/);assert.match(css,/@media \(prefers-reduced-motion: reduce\)/);
  const host=read('scripts/desktop-canvas.js');assert.match(host,/discardConnectionFeedback: nodeElement => canvasConnectionFeedback.discardNode\(nodeElement\)/);
});

test('arc has theme-colored light layers and a white-hot core without blur or strobing',()=>{
  const css=read('styles/desktop-canvas-nodes.css');
  assert.match(css,/\.desk-node > \.desk-connection-proximity \{[^}]*color: var\(--desk-canvas-control-accent\)/);
  assert.match(css,/\.desk-connection-proximity__halo \{[^}]*stroke-width: 7px;[^}]*opacity: 0\.22;/);
  assert.match(css,/\.desk-connection-proximity__wave \{[^}]*stroke-width: 2\.4px;/);
  assert.match(css,/\.desk-connection-proximity__core \{[^}]*stroke: color-mix\(in srgb, currentColor 18%, white\);[^}]*stroke-width: 0\.85px;/);
  assert.match(css,/@media \(prefers-reduced-motion: reduce\) \{\s*body\.desk-app :is\(\.desk-connection-proximity__arc,/);
  const h=fixture();h.api.updateProximity(h.to);
  assert.equal(h.animations.length,0,'no independent flashing animations');
  assert.ok(h.overlay.children[0].children.every(el=>!el.attributes.filter&&!el.style.filter));
});


test('unsupported Web Animations falls back to static confirmation and hidden page does nothing',()=>{
  const h=fixture();h.document.hidden=true;h.commit();assert.equal(h.overlay,undefined);assert.equal(h.listeners,0);
  h.document.hidden=false;const create=h.document.createElementNS;
  h.document.createElementNS=(...args)=>{const el=create(...args);el.animate=undefined;return el;};
  h.commit();assert.equal(h.overlay.children.length,1);assert.equal(h.frames.size,0);assert.equal(h.animations.length,0);
  h.tick(220);assert.equal(h.overlay,undefined);assert.equal(h.listeners,0);
});
test('boundary re-entry and live zoom reuse one proximity root without moving the semantic port',()=>{
  const h=fixture();h.api.updateProximity(h.to);const overlay=h.overlay,rect=h.to.rect;
  h.api.updateProximity({...h.to,phase:'snapped',strength:0});h.tick(45);h.api.updateProximity(h.to);
  assert.equal(h.overlay,overlay);assert.equal(overlay.dataset.phase,'near');assert.equal(h.frames.size,1);
  assert.deepEqual(h.to.rect,rect);h.setScale(2);h.to.pointer={x:472,y:400};h.api.updateProximity(h.to);
  assert.equal(h.overlay,overlay);assert.equal(h.overlay.style.transform,undefined);assert.equal(h.frames.size,1);
});

// Portable controller tests: synthetic DOM, deterministic RAF, no browser/API I/O.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');

function fixture({fromType = 'text', toType = 'input', scale = 1, secondTarget = false} = {}) {
  const frames = new Map(), messages = [], commits = [], offsets = new Map();
  let minimaps = 0, svgRebuilds = 0;
  let sequence = 0, saves = 0, lastRoute = null, covered = false, proximity = null, proximityClears = 0;
  const canvas = {scale, nodes: {
    from: {type: fromType, x: 100, y: 80, width: 100, height: 160},
    to: {type: toType, x: 500, y: 160, width: 200, height: 240}
  }, edges: []};
  if (secondTarget) canvas.nodes.other = {...canvas.nodes.to, y:188};
  const state = {canvas, preferences: {}};
  function element(classes = '', dataset = {}) {
    const names = new Set(classes.split(' ').filter(Boolean));
    const el = {dataset, isConnected: true, children: [], attributes: {}, style: {setProperty() {}},
      classList: {
        add: (...xs) => xs.forEach(x => names.add(x)), remove: (...xs) => xs.forEach(x => names.delete(x)),
        contains: x => names.has(x), toggle(x, on) {if (on) names.add(x); else names.delete(x);}
      }, setAttribute(k,v) {this.attributes[k] = v;}, getAttribute(k) {return this.attributes[k];}, addEventListener() {},
      appendChild(child) {child.parent = this; this.children.push(child);},
      remove() {this.parent.children = this.parent.children.filter(x => x !== this);},
      closest(selector) {return matches(this, selector) ? this : this.parent?.closest(selector) || null;},
      querySelectorAll(selector) {return descendants(this).filter(e => matches(e, selector));},
      querySelector(selector) {return this.querySelectorAll(selector)[0] || null;},
      getBoundingClientRect: () => ({left: 0, top: 0, right: 1600, bottom: 1000, width: 1600, height: 1000}),
      set innerHTML(value) {
        this.markup = value; this.children.forEach(child => child.isConnected = false); this.children = []; svgRebuilds++;
        for(const match of value.matchAll(/<path class="([^"]+)" data-edge-id="([^"]+)"[^>]* d="([^"]*)"/g)) {
          const child = element(match[1], {edgeId:match[2]}); child.setAttribute('d',match[3]); this.appendChild(child);
        }
      }, get innerHTML() {return this.markup || '';}
    };
    return el;
  }
  const descendants = el => el.children.flatMap(c => [c, ...descendants(c)]);
  function matches(el, selector) {
    return selector.split(',').some(raw => {
      const s = raw.trim();
      if (s.includes(' ')) return false;
      const classes = [...s.matchAll(/\.([\w-]+)/g)].map(m => m[1]);
      const attrs = [...s.matchAll(/\[data-([\w-]+)(?:="([^"]*)")?\]/g)];
      return classes.every(c => el.classList.contains(c)) && attrs.every(([, name, value]) => {
        const key = name.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
        return key in el.dataset && (value === undefined || el.dataset[key] === value);
      });
    });
  }
  const body = element(), viewport = element(), svg = element('desk-link-layer'), menu = element('desk-node-palette');
  body.appendChild(svg); body.appendChild(viewport); body.appendChild(menu);
  const nodes = {};
  for (const id of Object.keys(canvas.nodes)) {
    const node = element('desk-node desk-node--edge-handles', {nodeId: id});
    node.getBoundingClientRect = () => {
      const n = state.canvas.nodes[id], s = state.canvas.scale;
      return {left:n.x*s, top:n.y*s, right:(n.x+n.width)*s, bottom:(n.y+n.height)*s, width:n.width*s, height:n.height*s};
    };
    for (const direction of ['in', 'out']) {
      const port = element('desk-port', {nodeId:id, port:direction, semanticPort:'true', portSide:direction === 'in' ? 'left' : 'right'});
      port.getBoundingClientRect = () => {
        const n = state.canvas.nodes[id], s = state.canvas.scale, x = direction === 'in' ? n.x : n.x+n.width;
        return {left:(x-4.5)*s, right:(x+4.5)*s, top:(n.y+n.height/2-14)*s, bottom:(n.y+n.height/2+14)*s, width:9*s, height:28*s};
      };
      node.appendChild(port);
    }
    viewport.appendChild(node); nodes[id] = node;
  }
  const overlay = element('desk-settings'), blank = element();
  const within = (r,x,y) => x>=r.left && x<=r.right && y>=r.top && y<=r.bottom;
  const document = {
    body, createElement: () => element(), createElementNS: () => element(),
    querySelectorAll: selector => descendants(body).filter(e => matches(e, selector)),
    querySelector: selector => selector.includes('[data-live-connection-preview]') ? svg.querySelector('[data-live-connection-preview]') : descendants(body).find(e => matches(e, selector)),
    elementFromPoint(x,y) {
      if (covered) return overlay;
      for (const node of Object.values(nodes).reverse()) {
        if (!state.canvas.nodes[node.dataset.nodeId]) continue;
        for (const port of node.children) if (within(port.getBoundingClientRect(),x,y)) return port;
        if (within(node.getBoundingClientRect(),x,y)) return node;
      }
      return blank;
    }
  };
  const context = {document,console,innerWidth:1600,innerHeight:1000,
    DesktopState:{state,saveSettings(){saves++;}}, DesktopResults:{showTransientMessage:m=>messages.push(m)},
    requestAnimationFrame(fn){frames.set(++sequence,fn);return sequence;},cancelAnimationFrame:id=>frames.delete(id),
    setTimeout:()=>1,clearTimeout(){},DesktopLayoutEditor:{}};
  context.window=context;vm.createContext(context);
  for (const file of ['desktop-canvas-geometry.js','desktop-canvas-connections.js']) {
    vm.runInContext(fs.readFileSync(path.join(root,'frontend/scripts',file),'utf8'),context);
  }
  const geometry=context.DesktopCanvasGeometry;
  const noop=()=>{};
  const args={
    ...geometry, LINK_VIEWBOX:'0 0 1600 1000', NODE_MENU_ITEMS:['input','comfy','image','file_output','upscale','video_inference','video','text'].map(type=>({type})),
    activeInteractionRef:{current:null},pendingConnectionDropPointRef:{current:null},
    contextMenuConnectionSourceAnchorRef:{current:null},contextMenuConnectionSourceIdRef:{current:''},
    contextMenuConnectionSourceSideRef:{current:'right'},contextMenuElRef:{current:menu},
    edgeMenuElRef:{current:null},hoveredEdgeIdRef:{current:''},selectedEdgeIdRef:{current:''},
    els:{deskCanvasViewport:viewport},escapeHtml:String,nodeMenuButtonHtml:()=>'',
    getNodeState:id=>state.canvas.nodes[id],getNodeElement:id=>nodes[id],
    getNodeVisualOffset:id=>offsets.get(id),playConnectionCommit:receipt=>commits.push(receipt),
    screenToWorld:(x,y)=>({x:x/state.canvas.scale,y:y/state.canvas.scale}),
    getConnectionPortAnchor:(id,port)=>{const r=port.getBoundingClientRect();return args.screenToWorld((r.left+r.right)/2,(r.top+r.bottom)/2);},
    makeSmoothStepPath:(from,to,fromSide,toSide,route)=>{lastRoute={from,to,fromSide,toSide,route};return geometry.makeSmoothStepPath(from,to,fromSide,toSide,route);},
    makeClassicCurvePath:(...xs)=>geometry.makeClassicCurvePath(...xs),
    syncNodeEdgeStroke:noop,clearFloatingConnectionPort:noop,holdFloatingSwell:noop,releaseFloatingSwell:noop,
    updateConnectionProximity:target=>{proximity=target;},
    clearConnectionProximity:()=>{proximity=null;proximityClears++;},
    renderMiniMap:()=>{minimaps++;},refreshImageReferenceTokens:noop,ensureTextNodeImageReferenceConnections:noop,
    assignImageOutputSlots:noop,refreshComfyNode:noop,refreshPoseNode:noop,refreshUpscaleNodeMode:noop,
    refreshVideoInferenceNode:noop,refreshVideoNode:noop,updateLayoutInputCount:noop,updateUpscaleInputCount:noop,
    videoInputRoleForSource:type=>type==='text'?'prompt':type==='video'?'reference_video':'first_frame'
  };
  const api=context.DesktopCanvasConnections.create(args);
  const input=nodes.to.children[0];
  function begin() {
    api.startConnectionDrag({button:0,clientX:200*scale,clientY:160*scale,preventDefault:noop,stopPropagation:noop},nodes.from.children[1]);
  }
  function flush() { for(let n=0;frames.size && n<10;n++){const f=[...frames.values()];frames.clear();f.forEach(fn=>fn());}assert.equal(frames.size,0); }
  function pointer(x,y) {
    args.activeInteractionRef.current.pointer=args.screenToWorld(x,y);
    api.renderConnectionPreview('from',args.activeInteractionRef.current.pointer,'right');
    args.pendingConnectionDropPointRef.current={x,y};
  }
  function near(distance=8) {const r=input.getBoundingClientRect();return {x:r.left-distance,y:(r.top+r.bottom)/2};}
  return {api,state,canvas,nodes,input,args,begin,flush,pointer,near,svg,frames,messages,commits,offsets,
    setLineStyle(style){context.DesktopPreferences={state:{connectionLineStyle:style}};},
    get minimaps(){return minimaps;},get svgRebuilds(){return svgRebuilds;},
    cover(value){covered=value;},get lastRoute(){return lastRoute;},get saves(){return saves;},
    get proximity(){return proximity;},get proximityClears(){return proximityClears;}};
}

for (const scale of [0.1,0.5,1,2]) test(`near wave and snapped ring respect the CSS-pixel annulus at zoom ${scale}`,()=>{
  const h=fixture({scale});h.begin();
  for(const distance of [20.01,20,19.99,12,8.01,8,7.99,0,12,30]) {
    const p=h.near(distance);h.pointer(p.x,p.y);h.flush();
    assert.equal(h.proximity?.nodeId || null,distance<20?'to':null,`distance ${distance}`);
    assert.equal(h.proximity?.phase || null,distance<=8?'snapped':distance<20?'near':null);
    assert.equal(Boolean(h.lastRoute.route.toGeometry),distance<=8);
    assert.equal(h.canvas.edges.length,0,'proximity must not create a connection');
  }
});
test('proximity honors live compatibility, visibility, occlusion and viewport rejection',()=>{
  const h=fixture();h.begin();const p=h.near(12);
  const update=()=>{h.pointer(p.x,p.y);h.flush();};
  update();assert.equal(h.proximity.nodeId,'to');
  for(const key of ['hidden','disabled']){h.input[key]=true;update();assert.equal(h.proximity,null);h.input[key]=false;}
  h.cover(true);update();assert.equal(h.proximity,null);h.cover(false);
  h.canvas.nodes.to.type='image';update();assert.equal(h.proximity,null);
  h.canvas.nodes.to.type='input';update();assert.equal(h.proximity.nodeId,'to');
  h.pointer(-1,p.y);h.flush();assert.equal(h.proximity,null);
});
test('proximity corners use radial distance and only the nearest valid target is selected',()=>{
  const h=fixture();h.begin();const r=h.input.getBoundingClientRect();
  h.pointer(r.left-12,r.top-12);h.flush();assert.equal(h.proximity.nodeId,'to');
  h.pointer(r.left-15,r.top-15);h.flush();assert.equal(h.proximity,null);
  // Move the source's synthetic input near the target; self is never a candidate.
  h.canvas.nodes.from.x=h.canvas.nodes.to.x-1;
  h.nodes.from.classList.add('is-compatible-target');
  const p=h.near(12);h.pointer(p.x,p.y);h.flush();assert.equal(h.proximity.nodeId,'to');
});
test('only the closest of two compatible input ports gets feedback, and snap takes priority',()=>{
  const h=fixture({secondTarget:true});
  // Real input caps protrude from the node; keep each center outside the
  // overlapping shells so this case tests distance rather than occlusion.
  for(const id of ['to','other']) {
    const port=h.nodes[id].children[0],rect=port.getBoundingClientRect;
    port.getBoundingClientRect=()=>{const r=rect();return {...r,left:r.left-4,right:r.right-4};};
  }
  h.begin();const p=h.near(12);
  h.pointer(p.x,290);h.flush();assert.equal(h.proximity.nodeId,'to');
  h.pointer(p.x,296);h.flush();assert.equal(h.proximity.nodeId,'other');
  h.canvas.nodes.other.type='image';h.pointer(p.x,296);h.flush();assert.equal(h.proximity.nodeId,'to');
  const snap=h.near(8);h.pointer(snap.x,snap.y);h.flush();assert.equal(h.proximity.phase,'snapped');assert.ok(h.lastRoute.route.toGeometry);
});
for(const cancelled of [false,true]) test(`ending ${cancelled?'cancelled':'committed'} drag clears proximity`,()=>{
  const h=fixture();h.begin();const p=h.near(12);h.pointer(p.x,p.y);h.flush();
  assert.equal(h.proximity.nodeId,'to');const clears=h.proximityClears;
  const end=h.near(8);h.api.finishConnectionDrag({type:cancelled?'pointercancel':'pointerup',clientX:end.x,clientY:end.y});h.flush();
  assert.equal(h.proximity,null);assert.ok(h.proximityClears>clears);
  assert.equal(h.canvas.edges.length,cancelled?0:1);
});

for (const scale of [0.5,1,2]) test(`8 CSS-pixel capture is zoom invariant at ${scale}`,()=>{
  const h=fixture({scale});h.begin();
  for(const distance of [0,7.99,8]){const p=h.near(distance);assert.equal(h.api.findConnectionSnapTarget('from',p.x,p.y)?.nodeId,'to');}
  const p=h.near(8.01);assert.equal(h.api.findConnectionSnapTarget('from',p.x,p.y),null);
});
test('corners use radial distance, not a square 8px expansion',()=>{
  const h=fixture();h.begin();const r=h.input.getBoundingClientRect();
  assert.equal(h.api.findConnectionSnapTarget('from',r.left-6,r.top-6),null);
  assert.equal(h.api.findConnectionSnapTarget('from',r.left-4.8,r.top-6.4)?.nodeId,'to');
});
test('preview ends at the input anchor on the first RAF and releases beyond 8px',()=>{
  const h=fixture();h.begin();let p=h.near(8);h.pointer(p.x,p.y);h.flush();
  assert.equal(h.lastRoute.to.x,500);assert.equal(h.lastRoute.to.y,280);assert.equal(h.lastRoute.toSide,'left');
  assert.ok(h.lastRoute.route.toGeometry);assert.ok(h.input.classList.contains('is-drop-target'));
  assert.equal(h.canvas.edges.length,0,'magnetic preview alone must not create an edge');
  p=h.near(9);h.pointer(p.x,p.y);h.flush();assert.equal(h.lastRoute.to.x,p.x);
  assert.equal(h.input.classList.contains('is-drop-target'),false);
});
for(const flushed of [false,true]) test(`release at 8px commits once and clears ${flushed?'painted':'queued'} preview`,()=>{
  const h=fixture();h.begin();const p=h.near(8);h.pointer(p.x,p.y);if(flushed)h.flush();
  h.api.finishConnectionDrag({type:'pointerup',clientX:p.x,clientY:p.y});h.flush();
  assert.equal(h.canvas.edges.length,1);assert.equal(h.canvas.edges[0].to,'to');assert.equal(h.saves,1);
  assert.equal(h.svg.querySelector('[data-live-connection-preview]'),null);assert.equal(h.args.activeInteractionRef.current,null);
  assert.equal(h.input.classList.contains('is-drop-target'),false);
});
test('release recomputes the target rather than using stale magnet state',()=>{
  const h=fixture();h.begin();const p=h.near(7);h.pointer(p.x,p.y);h.flush();h.cover(true);
  h.api.finishConnectionDrag({type:'pointerup',clientX:p.x,clientY:p.y});h.flush();assert.equal(h.canvas.edges.length,0);
});
test('pointercancel discards a snapped or queued connection',()=>{
  const h=fixture();h.begin();const p=h.near(7);h.pointer(p.x,p.y);
  h.api.finishConnectionDrag({type:'pointercancel',clientX:p.x,clientY:p.y});h.flush();
  assert.equal(h.canvas.edges.length,0);assert.equal(h.saves,0);assert.equal(h.svg.querySelector('[data-live-connection-preview]'),null);
});
test('disabled, hidden, covered and outside-viewport targets do not attract',()=>{
  const h=fixture();h.begin();const p=h.near(7);
  for(const key of ['disabled','hidden']){h.input[key]=true;assert.equal(h.api.findConnectionSnapTarget('from',p.x,p.y),null);h.input[key]=false;}
  h.cover(true);assert.equal(h.api.findConnectionSnapTarget('from',p.x,p.y),null);h.cover(false);
  assert.equal(h.api.findConnectionSnapTarget('from',-1,280),null);
  assert.equal(h.api.findConnectionSnapTarget('from',NaN,280),null);
});
test('compatibility is checked against live nodes, not a stale DOM class',()=>{
  const h=fixture();h.begin();const p=h.near(7);h.canvas.nodes.to.type='image';
  assert.equal(h.api.findConnectionSnapTarget('from',p.x,p.y),null);
  assert.equal(h.api.connectNodes('from','to',{quiet:true}),'');assert.equal(h.canvas.edges.length,0);
  delete h.canvas.nodes.to;assert.equal(h.api.canConnectNodes('from','to'),false);
});
test('workflow state replacement is respected by compatibility and capture',()=>{
  const h=fixture();h.begin();const p=h.near(7);
  h.state.canvas={...h.canvas,nodes:{...h.canvas.nodes,to:{...h.canvas.nodes.to,type:'image'}}};
  assert.equal(h.api.canConnectNodes('from','to'),false);assert.equal(h.api.findConnectionSnapTarget('from',p.x,p.y),null);
});
test('self, missing and unknown source types are rejected',()=>{
  const h=fixture();assert.equal(h.api.canConnectNodes('from','from'),false);assert.equal(h.api.canConnectNodes('missing','to'),false);
  for(const type of ['unknown','toString','constructor']){h.canvas.nodes.from.type=type;assert.equal(h.api.canConnectNodes('from','to'),false);assert.equal(h.api.getConnectableNodeMenuItems('from').length,0);}
});
const contracts={
  input:['image','file_output','upscale','output'],comfy:['image','upscale'],video_inference:['video'],video:['video_inference'],
  image_group:['input','comfy'],output:['image'],image:['input','comfy','video_inference','layout','pose','upscale'],
  upscale:['image'],layout:['input','comfy','video_inference','upscale'],pose:['input','comfy','video_inference','upscale'],text:['input','comfy','video_inference'],file_output:[]
};
test('all source/target type pairs share one policy with highlight and magnetic capture',()=>{
  for(const [fromType,targets] of Object.entries(contracts)) for(const toType of Object.keys(contracts)) {
    const h=fixture({fromType,toType});h.begin();const p=h.near(8),valid=targets.includes(toType);
    assert.equal(h.api.canConnectNodes('from','to'),valid,`${fromType} -> ${toType}`);
    assert.equal(h.nodes.to.classList.contains('is-compatible-target'),valid);
    assert.equal(Boolean(h.api.findConnectionSnapTarget('from',p.x,p.y)),valid);
  }
});
test('video prompt role still replaces only the same role on commit',()=>{
  const h=fixture({fromType:'text',toType:'video_inference'});h.canvas.edges=[{id:'old',from:'from',to:'to',inputRole:'prompt'},{id:'frame',from:'source-image',to:'to',inputRole:'first_frame'}];
  h.begin();const p=h.near(8);h.api.finishConnectionDrag({type:'pointerup',clientX:p.x,clientY:p.y});
  assert.equal(h.canvas.edges.length,2);assert.equal(h.canvas.edges.filter(e=>e.inputRole==='prompt').length,1);
  assert.ok(h.canvas.edges.some(e=>e.id==='frame'));
});


test('only successful manual release emits a commit receipt; restore, cancel and rejected drops never do',()=>{
  const h=fixture();h.api.connectNodes('from','to');assert.equal(h.commits.length,0);
  h.begin();const p=h.near(7);h.pointer(p.x,p.y);h.flush();assert.equal(h.commits.length,0);
  h.api.finishConnectionDrag({type:'pointerup',clientX:p.x,clientY:p.y});h.flush();
  assert.equal(h.commits.length,1);assert.equal(h.commits[0].edgeId,h.canvas.edges[0].id);
  h.begin();h.api.finishConnectionDrag({type:'pointercancel',clientX:p.x,clientY:p.y});h.flush();assert.equal(h.commits.length,1);
  h.begin();h.canvas.nodes.to.type='image';h.api.finishConnectionDrag({type:'pointerup',clientX:p.x,clientY:p.y});h.flush();assert.equal(h.commits.length,1);
});

for(const line of ['curve','straight']) test(`temporary offset updates only adjacent ${line} wires and hit paths, not graph/minimap/SVG identity`,()=>{
  const h=fixture({secondTarget:true});h.setLineStyle(line);
  // Incoming, outgoing and unrelated edge are deliberately different records.
  h.canvas.edges=[{id:'in',from:'from',to:'to'},{id:'out',from:'to',to:'other'},{id:'unrelated',from:'from',to:'other'}];
  h.api.updateLinkPath();
  const paths=[...h.svg.children],before=paths.map(p=>p.getAttribute('d')),graph=JSON.stringify(h.canvas);
  const saves=h.saves, minimaps=h.minimaps, rebuilds=h.svgRebuilds;
  h.offsets.set('to',{x:3,y:-2});h.api.refreshNodeConnectionGeometry('to');
  assert.equal(h.api.getNodeGeometry('to').x,503);assert.equal(h.api.getAnchor('to','left').x,503);
  assert.equal(h.api.getNodeGeometry('to').y,158);assert.equal(h.api.getAnchor('to','left').y,278);
  assert.equal(h.api.getEdgeVisualPath('in'),paths[0]);
  for(let i=0;i<4;i++)assert.notEqual(paths[i].getAttribute('d'),before[i]);
  for(let i=4;i<6;i++)assert.equal(paths[i].getAttribute('d'),before[i]);
  assert.equal(paths[0].getAttribute('d'),paths[1].getAttribute('d'),'visual and hit endpoints agree');
  assert.equal(JSON.stringify(h.canvas),graph);assert.equal(h.saves,saves);assert.equal(h.minimaps,minimaps);assert.equal(h.svgRebuilds,rebuilds);
  h.offsets.delete('to');h.api.refreshNodeConnectionGeometry('to');assert.deepEqual(paths.map(p=>p.getAttribute('d')),before);
});

test('commit receives the free approach vector even after snapping and drag cleanup',()=>{
  const h=fixture();h.begin();const p=h.near(12);h.pointer(p.x,p.y+9);h.flush();
  const r=h.input.getBoundingClientRect();
  h.pointer((r.left+r.right)/2,(r.top+r.bottom)/2);h.flush();
  h.api.finishConnectionDrag({type:'pointerup',clientX:(r.left+r.right)/2,clientY:(r.top+r.bottom)/2});
  assert.equal(h.commits.length,1);assert.equal(h.commits[0].approach.x,16.5);assert.equal(h.commits[0].approach.y,-9);
});
for(const scale of [.1,1,2])test(`release without a preview frame provides a world-space approach at zoom ${scale}`,()=>{
  const h=fixture({scale});h.begin();const p=h.near(7);
  h.api.finishConnectionDrag({type:'pointerup',clientX:p.x,clientY:p.y+3*scale});
  assert.equal(h.commits.length,1);assert.ok(Math.abs(h.commits[0].approach.x-(4.5+7/scale))<1e-8);
  assert.equal(h.commits[0].approach.y,-3);
});
test('approach metadata cannot leak from another target or previous drag',()=>{
  const h=fixture({secondTarget:true});h.begin();const p=h.near(12);h.pointer(p.x,p.y-9);h.flush();
  const r=h.nodes.other.children[0].getBoundingClientRect();
  h.api.finishConnectionDrag({type:'pointerup',clientX:r.left-7,clientY:(r.top+r.bottom)/2});
  assert.equal(h.commits[0].toNodeId,'other');assert.equal(h.commits[0].approach.y,0);
  h.canvas.nodes.other.y=500; // The second node must not occlude the next input.
  h.begin();const q=h.near(7);h.api.finishConnectionDrag({type:'pointerup',clientX:q.x,clientY:q.y});
  assert.equal(h.commits[1].toNodeId,'to');assert.equal(h.commits[1].approach.y,0);
});

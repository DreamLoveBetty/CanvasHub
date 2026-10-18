const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');
const root=path.join(__dirname,'..');
const meltSource=fs.readFileSync(path.join(root,'frontend/scripts/desktop-canvas-image-group-melt.js'),'utf8');
const source=fs.readFileSync(path.join(root,'frontend/scripts/desktop-canvas-image-group-interaction.js'),'utf8');

class Element {
  constructor(name='div'){
    this.name=name;this.attrs={};this.parts=new Map();this.children=[];this.writes=0;this.dataset={};
    this.style={cssText:'',setProperty(key,value){this[key]=value;},removeProperty(key){delete this[key];}};
    this.classList={add(){},remove(){},toggle(){}};
  }
  setAttribute(key,value){this.attrs[key]=String(value);this.writes++;}
  getAttribute(key){return Object.prototype.hasOwnProperty.call(this.attrs,key)?this.attrs[key]:null;}
  removeAttribute(key){delete this.attrs[key];}
  querySelector(selector){if(!this.parts.has(selector))this.parts.set(selector,new Element());return this.parts.get(selector);}
  appendChild(child){this.children.push(child);child.parent=this;return child;}
  append(...nodes){nodes.forEach(node=>this.appendChild(node));}
  remove(){this.removed=true;}
  all(){return [this,...this.children.flatMap(child=>child.all())];}
}
const writes=root=>root.all().reduce((sum,node)=>sum+node.writes,0);
const find=(root,predicate)=>root.all().find(predicate);

function fixture(){
  const frames=new Map(),timers=new Map();let nextId=1,now=0;
  const frame=fn=>{const id=nextId++;frames.set(id,fn);return id;};
  const sandbox={window:{setTimeout:(fn,delay)=>{const id=nextId++;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id)},
    DesktopState:{state:{canvas:{nodes:{}}}},document:{createElementNS:(ns,name)=>new Element(name)},
    performance:{now:()=>now},requestAnimationFrame:frame,cancelAnimationFrame:id=>frames.delete(id)};
  vm.createContext(sandbox);vm.runInContext(meltSource,sandbox);vm.runInContext(source,sandbox);
  const Melt=sandbox.window.DesktopCanvasImageGroupMelt;
  const deps={
    clamp:(x,a,b)=>Math.min(b,Math.max(a,x)),imageGroupUiSize:x=>x,
    IMAGE_GROUP_BASE_THUMB_PX:168,IMAGE_GROUP_THUMB_PX:100,IMAGE_GROUP_THUMB_RADIUS_PX:19,IMAGE_GROUP_MAX_COLUMNS:4,
    IMAGE_GROUP_PROXIMITY_CONTACT_PX:52,IMAGE_GROUP_PROXIMITY_DROP_PX:28,
    IMAGE_GROUP_PROXIMITY_DROP_MS:400,IMAGE_GROUP_PROXIMITY_RELEASE_MS:380,
    imageGroupMelt:Melt,getNodeElement:()=>new Element(),activeInteractionRef:{current:null}
  };
  const api=sandbox.window.DesktopCanvasImageGroupInteraction.create(deps);
  const layer=new Element();
  const chip=src=>{const image=new Element('img');image.src=src;return {chip:new Element(),image,badge:new Element(),startSide:100};};
  const preview={
    active:true,raf:0,overlay:new Element(),
    melt:api.createLiveImageGroupMelt(layer),meltProx:0,meltClock:null,meltSettling:false,meltPartner:null,
    incoming:chip('incoming.webp'),targetItems:[chip('a.webp'),chip('b.webp')],introStartedAt:0,introDuration:250,introStartSide:100,
    pointerX:250,pointerY:90,baseLeft:0,baseTop:0,baseWidth:300,baseHeight:180,currentWidth:300,currentHeight:180,
    targetWidth:300,targetHeight:180,finalWidth:380,finalHeight:180,motherRadius:20,incomingRadius:54,
    thumbSize:100,thumbStart:120,step:80,rowStep:140,rowInset:40,
    currentStrength:1,targetStrength:1,releaseStrength:1,releaseStartedAt:0,reducedMotion:false,releasing:false,
    incomingCenter:{x:250,y:90},incomingSize:100,dropActive:true
  };
  const step=time=>{now=time;const [id,fn]=frames.entries().next().value||[];assert.ok(fn,'A frame must be scheduled');frames.delete(id);fn(now);};
  const svg=()=>layer.children[0];
  return {api,Melt,layer,svg,preview,frames,timers,deps,step,Element,setNow:t=>{now=t;}};
}
const card=(x,y,w=100,src='a.webp')=>({x,y,w,h:w,r:w*32/168,src});

// ---- the module -------------------------------------------------------------------------
test('接近程度：分开为 0、接触或重叠为 1，中间平滑单调，触发距离随尺寸缩放',()=>{
  const {Melt}=fixture();
  assert.equal(Melt.proximity(card(0,0),card(200,0)),0);
  assert.equal(Melt.proximity(card(0,0),card(100,0)),1);
  assert.equal(Melt.proximity(card(0,0),card(70,0)),1);
  let previous=-1;
  for(let gap=40;gap>=0;gap-=0.5){const value=Melt.proximity(card(0,0),card(100+gap,0));assert.ok(value>=previous);previous=value;}
  const small=Melt.proximity(card(0,0,50),card(60,0,50)),large=Melt.proximity(card(0,0,100),card(120,0,100));
  assert.ok(Math.abs(small-large)<1e-9,'the same relative gap gives the same proximity');
});

test('SVG 只覆盖两张图的外接框加滤镜外溢，而不是整个视口',()=>{
  const {api,Element}=fixture(),layer=new Element(),svg=()=>layer.children[0],melt=api.createLiveImageGroupMelt(layer);
  const box=melt.update({a:card(1000,600),b:card(1080,600,100,'b.webp'),prox:1});
  assert.ok(box.x<1000&&box.y<600);
  assert.ok(box.width<180+2*60&&box.height<100+2*60,`box ${box.width}x${box.height}`);
  assert.ok(box.x+box.width>1180&&box.y+box.height>700);
  assert.equal(svg().attrs.viewBox,`0 0 ${box.width} ${box.height}`);
  assert.equal(svg().style.transform,`translate(${box.x}px, ${box.y}px)`);
});

test('分开时清晰卡片原样不动；接触后接缝擦除椭圆和大理石纹才出现',()=>{
  const {api,Element}=fixture(),layer=new Element(),melt=api.createLiveImageGroupMelt(layer),root=layer.children[0];
  const ellipses=()=>root.all().filter(node=>node.name==='ellipse'&&node.attrs.fill==='#000');
  const marble=()=>find(root,node=>node.attrs.mask&&/marblemask/.test(node.attrs.mask));
  melt.update({a:card(0,0),b:card(140,0,100,'b.webp'),prox:0});
  assert.ok(ellipses().every(node=>Number(node.attrs.rx)===0&&Number(node.attrs.ry)===0));
  assert.equal(marble().style.display,'none');
  melt.update({a:card(0,0),b:card(90,0,100,'b.webp'),prox:1});
  assert.ok(ellipses().every(node=>Number(node.attrs.rx)>0&&Number(node.attrs.ry)>0));
  assert.equal(marble().style.display,'');
  const [first]=ellipses();assert.equal(Number(first.attrs.cx),Number(find(root,n=>n.name==='ellipse'&&n.attrs.fill==='#fff').attrs.cx));
});

test('像素参数随卡片尺寸缩放（上游按 84px 调校）',()=>{
  const {api,Element}=fixture(),layer=new Element();
  const blurOf=size=>{const melt=api.createLiveImageGroupMelt(layer);melt.update({a:card(0,0,size),b:card(size*0.9,0,size,'b.webp'),prox:1});
    return Number(find(layer.children.at(-1),node=>node.name==='feGaussianBlur'&&node.attrs.result==='b').attrs.stdDeviation);};
  assert.equal(blurOf(84),7);assert.equal(blurOf(168),14);
});

test('静止时不重复写入属性，图片地址只在来源变化时更新',()=>{
  const {api,Element}=fixture(),layer=new Element(),melt=api.createLiveImageGroupMelt(layer),root=layer.children[0];
  const args={a:card(0,0),b:card(90,0,100,'b.webp'),prox:.6};
  melt.update(args);const before=writes(root);melt.update(args);
  assert.equal(writes(root),before);
  const hrefs=()=>root.all().filter(node=>node.name==='image').map(node=>node.attrs.href);
  assert.deepEqual(hrefs(),['a.webp','b.webp']);
  melt.update({...args,a:card(0,0,100,'c.webp')});assert.deepEqual(hrefs(),['c.webp','b.webp']);
});

test('绘制模块无图状态、计时器或独立循环，只由交互模块显式注入',()=>{
  assert.ok(!/DesktopState|requestAnimationFrame|setTimeout|setInterval|fetch\(|querySelector|getComputedStyle|getBoundingClientRect/.test(meltSource));
  const {Melt}=fixture();assert.ok(Object.isFrozen(Melt));assert.ok(Object.isFrozen(Melt.DEFAULTS));
  assert.match(source,/imageGroupMelt\.create\(container\)/);
  assert.match(source,/imageGroupMelt\.proximity\(incomingBox, partner\.box\)/);
  const host=fs.readFileSync(path.join(root,'frontend/scripts/desktop-canvas.js'),'utf8');
  assert.match(host,/imageGroupMelt: window\.DesktopCanvasImageGroupMelt/);
  assert.ok(!fs.existsSync(path.join(root,'frontend/scripts/desktop-canvas-image-group-liquid-field.js')));
  assert.match(meltSource,/liquid-gooey/);assert.ok(fs.existsSync(path.join(root,'frontend/vendor/liquid-gooey/LICENSE')));
});

// ---- the interaction controller -----------------------------------------------------------
test('熔化对象是离拖入图片最近的缩略图；熔化中的两张原图隐藏，其余保持清晰',()=>{
  const {api,preview,setNow}=fixture();preview.introStartedAt=-10000;
  preview.pointerX=preview.incomingCenter.x=236; // off the exact midpoint between the two slots
  api.renderLiveImageGroupPreview(preview,0);
  for(let t=16;t<=1000;t+=16){setNow(t);api.renderLiveImageGroupPreview(preview,t);}
  const [a,b]=preview.targetItems;
  assert.ok(preview.meltProx>0.99,`prox ${preview.meltProx}`);
  const nearest=Math.hypot(a.box.x+a.box.w/2-236,a.box.y+a.box.h/2-90)<Math.hypot(b.box.x+b.box.w/2-236,b.box.y+b.box.h/2-90)?a:b;
  assert.equal(preview.meltPartner,nearest);
  assert.equal(preview.incoming.image.style.opacity,'0');assert.equal(nearest.image.style.opacity,'0');
  assert.equal((nearest===a?b:a).image.style.opacity||'','');
  preview.pointerX=preview.incomingCenter.x=900;preview.incoming.image.style.opacity='0';
  for(let t=1016;t<=3000;t+=16)api.renderLiveImageGroupPreview(preview,t);
  assert.equal(preview.meltProx,0);assert.equal(preview.incoming.image.style.opacity,'');assert.equal(nearest.image.style.opacity,'');
});

test('接近程度按经过时间指数追赶，与帧率无关',()=>{
  const sample=times=>{const {api,preview}=fixture();preview.introStartedAt=-10000;api.renderLiveImageGroupPreview(preview,0);for(const t of times)api.renderLiveImageGroupPreview(preview,t);return preview.meltProx;};
  const one=sample([48,96,144]),many=sample([16,32,48,64,80,96,112,128,144]);
  assert.ok(Math.abs(one-many)<1e-9,`${one} vs ${many}`);assert.ok(one>0&&one<1);
});

test('减少动态效果不熔化，原图可见，且不新建动画循环',()=>{
  const {api,preview,frames}=fixture();preview.reducedMotion=true;
  api.startLiveImageGroupPreviewFrame(preview);
  assert.equal(frames.size,0);assert.equal(preview.meltProx,0);
  assert.equal(preview.incoming.image.style.opacity,'');assert.equal(preview.dropActive,true);
});

test('熔化尚在收敛时保持唯一 RAF，收敛且无其他动画后停止',()=>{
  const {api,preview,frames,step}=fixture();preview.introStartedAt=-10000;
  api.startLiveImageGroupPreviewFrame(preview);step(16);
  assert.equal(preview.meltSettling,true);assert.equal(frames.size,1);
  for(let t=32;t<=3000&&frames.size;t+=16)step(t);
  assert.equal(preview.meltSettling,false);assert.equal(frames.size,0);
});

test('拖入预览不再画母卡底板；也没有连接桥、接触点或拖入轮廓',()=>{
  const {api,preview}=fixture();api.renderLiveImageGroupPreview(preview,300);
  assert.ok(!/__bridge|__contact|__incoming-shape|liquify|Liquify/.test(source));
  assert.ok(!/mother-shape|liveImageGroupMotherPath|liquid-svg|liquid-surface/.test(source));
  assert.equal(api.liveImageGroupMotherPath,undefined);
});

// ---- lifecycle contracts unchanged by the melt -------------------------------------------
test('离开时不重新计算成接触状态，不重新放大容器或激活投放',()=>{
  const {api,preview}=fixture();preview.releasing=true;
  api.renderLiveImageGroupPreview(preview,300);
  assert.equal(preview.targetStrength,0);assert.equal(preview.dropActive,false);
  assert.equal(preview.targetWidth,preview.baseWidth);assert.equal(preview.targetHeight,preview.baseHeight);
});

test('离开时从当前强度连续回收，不跳回之前最大强度',()=>{
  const {api,preview,step}=fixture();preview.currentStrength=.35;preview.releaseStrength=1;preview.releasing=true;preview.targetStrength=0;
  api.startLiveImageGroupPreviewFrame(preview);step(16);
  assert.equal(preview.currentStrength,.35);
  step(100);assert.ok(preview.currentStrength<.35&&preview.currentStrength>0);
  step(410);assert.equal(preview.currentStrength,0);
});

test('松手回收由经过时间决定，同一时刻不会因帧率不同产生不同强度',()=>{
  const sample=times=>{
    const {api,preview,step}=fixture();preview.currentStrength=.8;
    api.animateImageGroupProximityDrop({nodeId:'source',imageGroupProximity:{ready:true,preview}});
    for(const time of times)step(time);
    return preview.currentStrength;
  };
  const one=sample([200]),many=sample([16,32,48,64,80,96,112,128,144,160,176,192,200]);
  assert.equal(one,many);assert.equal(one,.4);
});

test('进入和落位曲线连续单调',()=>{
  const {api}=fixture();let previous=0;
  for(let i=0;i<=10000;i++){
    const value=api.liveImageGroupEase(i/10000);
    assert.ok(value>=previous&&value<=1);assert.ok(value-previous<=.000301);previous=value;
  }
  assert.equal(api.liveImageGroupEase(0),0);assert.equal(api.liveImageGroupEase(1),1);
});

test('清理取消准确的 RAF/定时器并移除包含熔化层的同一 overlay',()=>{
  const {api,preview,frames,timers}=fixture();api.startLiveImageGroupPreviewFrame(preview);
  timers.set(91,{});timers.set(92,{});
  const interaction={nodeId:'source',imageGroupProximity:{targetNodeId:'target',timer:91,releaseTimer:92,preview}};
  api.clearImageGroupProximity(interaction);
  assert.equal(frames.size,0);assert.equal(timers.size,0);assert.equal(preview.active,false);
  assert.equal(preview.overlay.removed,true);assert.equal(interaction.imageGroupProximity,null);
});

test('按顺序加载熔化模块并带缓存版本',()=>{
  const html=fs.readFileSync(path.join(root,'frontend/desktop.html'),'utf8');
  for(const asset of ['scripts/desktop-canvas-image-group-interaction.js','scripts/desktop-canvas-image-group-melt.js','scripts/desktop-canvas.js','styles/desktop-image-group.css'])assert.ok(hasCacheKey(html,asset),asset);
  assert.ok(html.indexOf('scripts/desktop-canvas-image-group-melt.js')<html.indexOf('scripts/desktop-canvas-image-group-interaction.js'));
  assert.ok(!html.includes('desktop-canvas-image-group-liquid-field.js'));
});

test('组内拖动排序时，拖动的缩略图与最近的缩略图熔化；结束时图层与原图恢复',()=>{
  // Painted inside the group's mother, under the items, with the same pairwise melt module.
  assert.match(source,/function renderImageGroupSortMelt\(sortState, now\)/);
  assert.match(source,/layer\.className = 'desk-image-group__sort-melt';\n\s*sortState\.mother\.appendChild\(layer\);\n\s*sortState\.meltLayer = layer;\n\s*sortState\.melt = imageGroupMelt\.create\(layer\);/);
  assert.match(source,/const target = partner \? imageGroupMelt\.proximity\(draggedBox, partner\.box\) : 0;/);
  assert.match(source,/sortState\.meltProx \+= \(target - sortState\.meltProx\) \* \(1 - Math\.exp\(-14 \* dt\)\);/);
  assert.match(source,/if \(sortState\.reducedMotion \|\| !sortState\.mother\) return;/);
  // Every sort ending (commit or return) clears the melt and restores both photos.
  assert.match(source,/function clearImageGroupItemSortState\(sortState, delay = 0\) \{\n\s*clearImageGroupSortMelt\(sortState\);/);
  assert.match(source,/sortState\.itemEntries\.forEach\(entry => entry\.element\.classList\.remove\('is-melting'\)\);/);
  assert.match(source,/dragged\.element\.classList\.toggle\('is-melting', visible\);/);
  // A melting thumbnail paints nothing of its own: no photo, no tint, no drag shadow,
  // so no hard-edged rectangle sits on top of the melt.
  const paint=fs.readFileSync(path.join(root,'frontend/styles/desktop-image-group.css'),'utf8');
  const after=paint.slice(paint.indexOf('.desk-image-group__item.is-dragging {'));
  assert.match(after,/\.desk-image-group__item\.is-melting \{\n  filter: none;\n\}/,'beats the drag shadow (declared after it)');
  assert.match(paint,/\.desk-image-group__item\.is-melting \.desk-image-group__thumb \{\n  background: transparent;\n\}/);
  assert.match(paint,/\.desk-image-group__item\.is-melting \.desk-image-group__thumb img \{\n  opacity: 0;\n\}/);
  const sortMelt=source.slice(source.indexOf('function renderImageGroupSortMelt'),source.indexOf('function clearImageGroupSortMelt'));
  assert.doesNotMatch(sortMelt,/image\.style\.opacity/,'hiding only the photo left the tint on top');
  const css=fs.readFileSync(path.join(root,'frontend/styles/desktop-image-group-geometry.css'),'utf8');
  const layer=css.slice(css.indexOf('.desk-image-group__sort-melt {'));
  assert.match(layer,/z-index: 3;/,'under the items (z-index 4)');
  assert.match(css,/\.desk-image-group__items \{[\s\S]*?z-index: 4;/);
});

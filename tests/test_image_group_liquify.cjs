const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.join(__dirname,'..');
const fieldSource=fs.readFileSync(path.join(root,'frontend/scripts/desktop-canvas-image-group-liquid-field.js'),'utf8');
const source=fs.readFileSync(path.join(root,'frontend/scripts/desktop-canvas-image-group-interaction.js'),'utf8');

function fixture(){
  const frames=new Map(),timers=new Map();let nextId=1,now=0;
  class Element {
    constructor(){
      this.attrs={};this.parts=new Map();this.children=[];this.writes=0;this.dataset={};
      this.style={setProperty(key,value){this[key]=value;},removeProperty(key){delete this[key];}};
      this.classList={add(){},remove(){},toggle(){}};
    }
    setAttribute(key,value){this.attrs[key]=String(value);this.writes++;}
    removeAttribute(key){delete this.attrs[key];}
    querySelector(selector){if(!this.parts.has(selector))this.parts.set(selector,new Element());return this.parts.get(selector);}
    appendChild(child){this.children.push(child);return child;}
    remove(){this.removed=true;}
  }
  const frame=fn=>{const id=nextId++;frames.set(id,fn);return id;};
  const sandbox={window:{setTimeout:(fn,delay)=>{const id=nextId++;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id)},
    DesktopState:{state:{canvas:{nodes:{}}}},document:{createElementNS:()=>new Element()},
    performance:{now:()=>now},requestAnimationFrame:frame,cancelAnimationFrame:id=>frames.delete(id)};
  vm.createContext(sandbox);vm.runInContext(fieldSource,sandbox);vm.runInContext(source,sandbox);
  const deps={
    clamp:(x,a,b)=>Math.min(b,Math.max(a,x)),imageGroupUiSize:x=>x,
    IMAGE_GROUP_BASE_THUMB_PX:168,IMAGE_GROUP_MAX_COLUMNS:4,
    IMAGE_GROUP_PROXIMITY_CONTACT_PX:52,IMAGE_GROUP_PROXIMITY_DROP_PX:28,
    IMAGE_GROUP_PROXIMITY_DROP_MS:400,IMAGE_GROUP_PROXIMITY_RELEASE_MS:380,
    imageGroupLiquidField:sandbox.window.DesktopCanvasImageGroupLiquidField,
    getNodeElement:()=>new Element(),activeInteractionRef:{current:null}
  };
  const api=sandbox.window.DesktopCanvasImageGroupInteraction.create(deps);
  const defs=new Element(),image=new Element(),outline=new Element();
  const effect=api.createLiveImageGroupLiquify(defs,'test-texture',image,outline);
  const chip=()=>({chip:new Element(),image:new Element(),badge:new Element(),startSide:100});
  const preview={
    active:true,raf:0,overlay:new Element(),base:new Element(),bridge:new Element(),bridgeHalo:new Element(),contactBlob:new Element(),incomingShape:outline,identity:new Element(),
    liquify:effect,incoming:chip(),targetItems:[chip()],introStartedAt:0,introDuration:250,introStartSide:100,
    pointerX:350,pointerY:90,baseLeft:0,baseTop:0,baseWidth:300,baseHeight:180,currentWidth:300,currentHeight:180,
    targetWidth:300,targetHeight:180,finalWidth:380,finalHeight:180,motherRadius:20,incomingRadius:54,
    thumbSize:100,thumbStart:120,step:80,rowStep:140,rowInset:40,identityInset:12,identityTop:12,
    currentStrength:1,targetStrength:1,releaseStrength:1,releaseStartedAt:0,reducedMotion:false,releasing:false,
    incomingCenter:{x:350,y:90},incomingSize:100,dropActive:true
  };
  preview.incoming.image=image;
  const step=time=>{now=time;const [id,fn]=frames.entries().next().value||[];assert.ok(fn,'A frame must be scheduled');frames.delete(id);fn(now);};
  return {api,effect,defs,image,outline,preview,frames,timers,deps,step,Element};
}

test('单一图片共用合成位移场，接触噪声先衰减再形变而不是透明副本',()=>{
  const {effect,defs}=fixture();
  assert.equal(defs.children.length,1);
  assert.match(effect.filter.innerHTML,/<feDisplacementMap in="SourceGraphic" in2="pullMap"/);
  assert.match(effect.filter.innerHTML,/<feDisplacementMap in="contactWarped" in2="contactNoise"[^>]+result="edgeWarped"/);
  assert.match(effect.filter.innerHTML,/<feComposite in="smear" in2="smearField" operator="in"/);
  assert.match(effect.filter.innerHTML,/<feComposite in="warped" in2="smearField" operator="out"/);
  assert.match(effect.filter.innerHTML,/operator="arithmetic" k2="1" k3="1"/);
  assert.equal((effect.filter.innerHTML.match(/<feImage /g)||[]).length,3);
  for(const field of effect.fields)assert.ok(field.attrs.href.startsWith('data:image/svg+xml,'));
  assert.match(effect.filter.innerHTML,/in="movingNoise" in2="flowEnvelope"[^>]+k1="1" k3="-.5" k4=".5"/);
  assert.match(effect.filter.innerHTML,/result="opaqueNoise"><feFuncA[^>]+slope="0" intercept="1"/);
  assert.equal(effect.filter.attrs.filterUnits,'objectBoundingBox');
  assert.equal(effect.filter.attrs.width,'230%');
});

test('接触期使用固定种子的低频局部形变，尺寸缩放一致',()=>{
  const {api,effect}=fixture();
  assert.match(effect.filter.innerHTML,/<feTurbulence type="fractalNoise"[^>]+numOctaves="2" seed="11"/);
  for(const size of [30,100,250])for(const strength of [.2,.8,1]){
    api.renderLiveImageGroupLiquify(effect,{x:1,y:0},strength,size);
    const frequencies=effect.noise.attrs.baseFrequency.split(' ').map(Number);
    assert.equal(frequencies[0],1.8/size);assert.equal(frequencies[1],2.2/size);
    assert.equal(Number(effect.edgeWarp.attrs.scale),size*.48*strength);
  }
  const writes=effect.edgeWarp.writes;
  api.renderLiveImageGroupLiquify(effect,{x:1,y:0},1,250);
  assert.equal(effect.edgeWarp.writes,writes);
});

test('完整涂抹与完全退出遮罩端点精确，覆盖连续扩展',()=>{
  const {api,effect}=fixture();
  for(const coverage of [.99999,1,.00001,0]){
    api.renderLiveImageGroupLiquify(effect,{x:1,y:0},1,100,coverage);
    const t=Math.min(1,Math.max(0,(coverage-.45)/.55)),mix=t*t*(3-2*t);
    assert.equal(Number(effect.maskAlpha.attrs.slope),1-mix);
    assert.equal(Number(effect.maskAlpha.attrs.intercept),mix);
  }
});

test('进入程度由完整缩略图与圆角母板计算，不以鼠标中心越界冒充整图进入',()=>{
  const {api}=fixture(),rect={left:0,top:0,width:300,height:180};
  for(const [x,expected] of [[350,0],[300,0],[275,.5],[250,1],[150,1]]){
    assert.equal(api.liveImageGroupLiquidCoverage({x,y:90},rect,50,20),expected);
  }
  assert.equal(api.liveImageGroupLiquidCoverage({x:10,y:10},rect,50,40),0);
});

test('完全进入且鼠标未放开时，整图涂抹遮罩为 1，没有清晰半边或提前还原',()=>{
  const {api,preview,effect}=fixture();
  api.renderLiveImageGroupPreview(preview,300);
  const entryNormal={...preview.lastContact.normal};
  preview.pointerX=230;preview.pointerY=90;
  for(const now of [400,1600,3600]){
    api.renderLiveImageGroupPreview(preview,now);
    assert.equal(preview.liquidCoverage,1);assert.equal(preview.liquidStrength,1);
    assert.equal(effect.maskAlpha.attrs.slope,'0');assert.equal(effect.maskAlpha.attrs.intercept,'1');
    assert.ok(Number(effect.edgeWarp.attrs.scale)>0);assert.equal(effect.enabled,true);
    assert.deepEqual({...preview.lastContact.normal},entryNormal);
  }
  assert.equal(preview.committing,undefined);
});

test('部分进入平滑扩大涂抹区域，退出完整区域时不会跳成全图清晰',()=>{
  const {api,preview,effect}=fixture();
  preview.pointerX=275;api.renderLiveImageGroupPreview(preview,300);
  assert.equal(preview.liquidCoverage,.5);assert.ok(Number(effect.maskAlpha.attrs.slope)>.97);
  assert.ok(Number(effect.maskAlpha.attrs.intercept)<.03);
  preview.pointerX=230;api.renderLiveImageGroupPreview(preview,400);
  preview.pointerX=275;api.renderLiveImageGroupPreview(preview,500);
  assert.equal(preview.liquidCoverage,.5);assert.equal(effect.enabled,true);
});

test('快速整图拖入不等待接触动画强度爬升，撤离仍可平滑恢复',()=>{
  const {api,preview,effect}=fixture();preview.pointerX=230;preview.currentStrength=0;
  api.renderLiveImageGroupPreview(preview,300);
  assert.equal(preview.liquidCoverage,1);assert.equal(preview.liquidStrength,1);assert.equal(effect.enabled,true);
  preview.releasing=true;preview.currentStrength=.35;api.renderLiveImageGroupPreview(preview,400);
  assert.equal(preview.liquidStrength,.35);
  preview.currentStrength=0;api.renderLiveImageGroupPreview(preview,500);
  assert.equal(preview.liquidStrength,0);assert.equal(effect.enabled,false);
});

test('SVG 轮廓在与 HTML 图片一致的本地坐标中采样，移动时不留下错位圆环',()=>{
  const {api,preview}=fixture();api.renderLiveImageGroupPreview(preview,300);
  assert.equal(preview.incomingShape.attrs.cx,'50');assert.equal(preview.incomingShape.attrs.cy,'50');
  assert.equal(preview.incomingShape.attrs.transform,'translate(300 40)');
  preview.pointerX=230;preview.pointerY=100;api.renderLiveImageGroupPreview(preview,400);
  assert.equal(preview.incomingShape.attrs.cx,'50');assert.equal(preview.incomingShape.attrs.cy,'50');
  assert.equal(preview.incomingShape.attrs.transform,'translate(180 50)');
});

test('松手后的母板可以回收，但每个融合中间帧仍保持整图液化直到完成',()=>{
  const {api,preview,effect,step}=fixture();preview.pointerX=230;
  api.renderLiveImageGroupPreview(preview,300);
  api.animateImageGroupProximityDrop({nodeId:'source',imageGroupProximity:{ready:true,preview}});
  for(const time of [16,100,200,300,399]){
    step(time);
    assert.equal(preview.liquidCoverage,1);assert.equal(preview.liquidStrength,1);
    assert.equal(effect.maskAlpha.attrs.slope,'0');assert.equal(effect.maskAlpha.attrs.intercept,'1');
    assert.equal(Number(effect.edgeWarp.attrs.scale),60);assert.equal(effect.enabled,true);
  }
  assert.ok(preview.currentStrength<.001);
});

test('接触位移与图片尺寸和强度成比例，四方向及斜角的拉伸法向正确',()=>{
  const {api,effect}=fixture();
  for(const n of [{x:1,y:0},{x:-1,y:0},{x:0,y:1},{x:0,y:-1},{x:3,y:4}]){
    for(const size of [30,100,250])for(const strength of [.1,.5,1]){
      api.renderLiveImageGroupLiquify(effect,n,strength,size);
      const len=Math.hypot(n.x,n.y),matrix=effect.direction.attrs.values.trim().split(/\s+/).map(Number);
      assert.ok(Math.abs(Number(effect.offset.attrs.dx)+n.x/len*size*.52)<1e-9);
      assert.ok(Math.abs(Number(effect.offset.attrs.dy)+n.y/len*size*.52)<1e-9);
      assert.equal(Number(effect.warp.attrs.scale),size*.62*strength);
      assert.equal(matrix[3],n.x/len*.5);assert.equal(matrix[8],n.y/len*.5);
      assert.equal(matrix[4],.5);assert.equal(matrix[9],.5);
      assert.ok(effect.smear.attrs.stdDeviation.split(' ').every(x=>Number.isFinite(Number(x))));
    }
  }
});

test('静止不重复写滤镜参数，强度归零恢复原图，重新接触重新启用',()=>{
  const {api,effect,image}=fixture();
  api.renderLiveImageGroupLiquify(effect,{x:1,y:0},1,100);
  const writes=effect.warp.writes;
  api.renderLiveImageGroupLiquify(effect,{x:1,y:0},1,100);
  assert.equal(effect.warp.writes,writes);
  api.renderLiveImageGroupLiquify(effect,{x:1,y:0},0,100);
  assert.equal(image.style.filter,undefined);assert.equal(effect.enabled,false);
  api.renderLiveImageGroupLiquify(effect,{x:1,y:0},1,100);
  assert.equal(image.style.filter,'url(#test-texture)');assert.equal(effect.warp.writes,writes);
});

test('真实预览渲染使用位移而不是 opacity 副本和径向渐隐，序号不被滤镜扭曲',()=>{
  const {api,preview,effect}=fixture();api.renderLiveImageGroupPreview(preview,300);
  assert.equal(effect.enabled,true);assert.ok(Number(effect.warp.attrs.scale)>0);
  assert.equal(preview.incoming.image.style.maskImage,undefined);
  assert.equal(preview.incoming.chip.style.filter,undefined);
  assert.equal(preview.incoming.badge.style.filter,undefined);
  assert.ok(!source.includes('meltImages'));assert.ok(!source.includes('liveImageGroupMask'));
});

test('图片与背板圆形轮廓使用同一位移场，离开后一起还原而不是留下硬圆环',()=>{
  const {api,effect,image,outline}=fixture();
  for(const strength of [.2,.75,1,0,.5]){
    api.renderLiveImageGroupLiquify(effect,{x:1,y:1},strength,100);
    assert.equal(outline.style.filter,image.style.filter);
    assert.equal(outline.style.filter,strength?'url(#test-texture)':undefined);
  }
});

test('渲染轮廓与图片边框盒等大，母板输出拉伸路径，不再保留刚性圆和矩形边界',()=>{
  const {api,preview}=fixture();api.renderLiveImageGroupPreview(preview,300);
  assert.equal(Number(preview.incomingShape.attrs.r),preview.incomingSize/2);
  assert.equal(preview.incomingShape.style.filter,preview.incoming.image.style.filter);
  assert.match(preview.base.attrs.d,/^M .* L .* Z$/);
  assert.equal(preview.base.attrs.width,undefined);
  assert.match(source,/createLiveImageGroupLiquify\([^\n]+incoming\.image, incomingShape\)/);
});

const pathPoints=d=>[...d.matchAll(/[ML]\s+(-?[\d.]+)\s+(-?[\d.]+)/g)].map(m=>({x:Number(m[1]),y:Number(m[2])}));

test('母板只有接触邻域被拉伸，四边及斜角沿接触法向而不是整体缩放',()=>{
  const {api}=fixture(),rect={left:20,top:30,width:300,height:180};
  const samples=[{x:360,y:120,nx:1,ny:0},{x:-20,y:120,nx:-1,ny:0},
    {x:170,y:0,nx:0,ny:-1},{x:170,y:240,nx:0,ny:1},{x:340,y:230,nx:Math.SQRT1_2,ny:Math.SQRT1_2}];
  for(const sample of samples){
    const contact=api.liveImageGroupRoundedRectContact(sample,rect,20);
    const small=pathPoints(api.liveImageGroupMotherPath(rect,20,contact,.25,100));
    const large=pathPoints(api.liveImageGroupMotherPath(rect,20,contact,1,100));
    assert.equal(small.length,large.length);
    let maxPull=0;
    large.forEach((p,i)=>{
      const dx=p.x-small[i].x,dy=p.y-small[i].y;
      const normal=dx*sample.nx+dy*sample.ny;
      assert.ok(normal>=-.002);assert.ok(Math.abs(-dx*sample.ny+dy*sample.nx)<.002);
      maxPull=Math.max(maxPull,normal);
      if(Math.hypot(p.x-contact.surface.x,p.y-contact.surface.y)>200)assert.ok(Math.hypot(dx,dy)<.002);
    });
    assert.ok(maxPull>15&&maxPull<=16.502);
  }
});

test('轮廓按缩放比例变化，强度归零精确恢复圆角矩形，采样数量始终有界',()=>{
  const {api}=fixture();let reference;
  for(const scale of [.3,1,1.25,3]){
    const rect={left:0,top:0,width:300*scale,height:180*scale};
    const contact={surface:{x:rect.width,y:rect.height/2},normal:{x:1,y:0}};
    const points=pathPoints(api.liveImageGroupMotherPath(rect,20*scale,contact,1,100*scale));
    const pull=(Math.max(...points.map(p=>p.x))-rect.width)/scale;
    assert.ok(pull>21.9&&pull<=22.01);
    reference=api.liveImageGroupMotherPath(rect,20*scale,contact,0,100*scale);
    assert.match(reference,/ H .* A .* V .* Z$/);assert.ok(!reference.includes(' L '));
  }
  for(const radius of [0,20,500]){
    const d=api.liveImageGroupMotherPath({left:-100,top:10,width:10000,height:1000},radius,{surface:{x:9900,y:500},normal:{x:1,y:0}},1,30);
    assert.ok(pathPoints(d).length<=304);assert.ok(!/NaN|Infinity/.test(d));
  }
});

test('减少动态效果同时恢复图片与轮廓，母板没有残留拉伸',()=>{
  const {api,preview,outline,image}=fixture();api.renderLiveImageGroupPreview(preview,300);
  preview.reducedMotion=true;api.renderLiveImageGroupPreview(preview,400);
  assert.equal(outline.style.filter,undefined);assert.equal(image.style.filter,undefined);
  assert.ok(!preview.base.attrs.d.includes(' L '));
});

test('仅临时 incoming 去除独立环形阴影，透明图片有不透底的同色 alpha',()=>{
  const css=fs.readFileSync(path.join(root,'frontend/styles/desktop-image-group.css'),'utf8');
  const rule=css.match(/body\.desk-app\[data-theme\] \.desk-image-group-transition--proximity \.desk-image-group-transition__chip\.is-incoming img\s*\{([^}]+)\}/);
  assert.ok(rule);assert.match(rule[1],/background: var\(--desk-image-group-transition-chip-border\)/);
  assert.match(rule[1],/box-shadow: none/);
  assert.match(css,/\.desk-image-group-transition__incoming-shape\s*\{\s*fill: var\(--desk-image-group-transition-chip-border\)/);
  assert.ok(!rule[1].includes('filter:'));
});

test('减少动态效果保留清晰单图，无位移、无新增动画循环',()=>{
  const {api,preview,effect,frames}=fixture();preview.reducedMotion=true;
  api.startLiveImageGroupPreviewFrame(preview);
  assert.equal(effect.enabled,false);assert.equal(frames.size,0);assert.equal(preview.dropActive,true);
});

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
  step(410);assert.equal(preview.currentStrength,0);assert.equal(preview.liquify.enabled,false);
});

test('松手回收由经过时间决定，同一时刻不会因帧率不同产生不同形变',()=>{
  const sample=times=>{
    const {api,preview,step}=fixture();preview.currentStrength=.8;
    api.animateImageGroupProximityDrop({nodeId:'source',imageGroupProximity:{ready:true,preview}});
    for(const time of times)step(time);
    return preview.currentStrength;
  };
  const one=sample([200]),many=sample([16,32,48,64,80,96,112,128,144,160,176,192,200]);
  assert.equal(one,many);assert.equal(one,.4);
});

test('进入和落位曲线连续单调，没有旧 0.82 分段回跳',()=>{
  const {api}=fixture();let previous=0;
  for(let i=0;i<=10000;i++){
    const value=api.liveImageGroupEase(i/10000);
    assert.ok(value>=previous&&value<=1);assert.ok(value-previous<=.000301);previous=value;
  }
  assert.equal(api.liveImageGroupEase(0),0);assert.equal(api.liveImageGroupEase(1),1);
});

test('清理取消准确的 RAF/定时器并移除包含滤镜的同一 overlay',()=>{
  const {api,preview,frames,timers}=fixture();api.startLiveImageGroupPreviewFrame(preview);
  timers.set(91,{});timers.set(92,{});
  const interaction={nodeId:'source',imageGroupProximity:{targetNodeId:'target',timer:91,releaseTimer:92,preview}};
  api.clearImageGroupProximity(interaction);
  assert.equal(frames.size,0);assert.equal(timers.size,0);assert.equal(preview.active,false);
  assert.equal(preview.overlay.removed,true);assert.equal(interaction.imageGroupProximity,null);
});

test('接触到整图液化连续过渡，早期不把远侧放大全局噪声',()=>{
  const {api,effect}=fixture();let last=0;
  for(let i=0;i<=1000;i++){
    const coverage=i/1000;
    api.renderLiveImageGroupLiquify(effect,{x:1,y:0},1,100,coverage,600);
    const mix=effect.radialMix;
    assert.ok(mix>=last&&mix-last<.00273);last=mix;
    if(coverage<=.45){assert.equal(mix,0);assert.equal(effect.radialWarp.attrs.scale,'0');assert.equal(effect.maskAlpha.attrs.intercept,'0');}
    assert.equal(Number(effect.warp.attrs.scale),62*(1-mix));
    assert.equal(Number(effect.radialWarp.attrs.scale),50*mix);
    assert.equal(Number(effect.maskAlpha.attrs.slope)+Number(effect.maskAlpha.attrs.intercept),1);
  }
  assert.equal(last,1);assert.equal(effect.warp.attrs.scale,'0');
});

test('同一径向波峰按经过时间从中心向外传播，不是随机噪声或整体偏移',()=>{
  const {api,effect}=fixture(),peaks=[];
  for(const elapsed of [0,300,600]){
    api.renderLiveImageGroupLiquify(effect,{x:1,y:0},1,100,1,elapsed);
    const svg=decodeURIComponent(effect.wave.attrs.href.split(',').slice(1).join(','));
    const samples=[...svg.matchAll(/<stop offset="([^"]+)" stop-color="rgb\((\d+),/g)]
      .map(m=>({radius:Number(m[1])*Math.SQRT2*115,level:Number(m[2])})).filter(v=>v.radius<46);
    peaks.push(samples.reduce((a,b)=>a.level>b.level?a:b).radius);
    assert.match(svg,/cx="115" cy="115"/);assert.ok(!/animate|script|href=|<image/.test(svg));
  }
  assert.ok(peaks[1]>peaks[0]+8&&peaks[2]>peaks[1]+8);
  assert.ok(peaks[2]-peaks[0]<27);
  assert.match(decodeURIComponent(effect.fields[0].attrs.href),/stop-color="#ff0000".*stop-color="#000"/);
  assert.match(decodeURIComponent(effect.fields[1].attrs.href),/y2="1".*stop-color="#00ff00".*stop-color="#000"/);
});

test('动态位移相位与帧率无关，同帧尺寸或覆盖变化不复用错误字段',()=>{
  const sample=times=>{const {api,effect}=fixture();for(const time of times)api.renderLiveImageGroupLiquify(effect,{x:1,y:0},1,100,1,time);return {url:effect.wave.attrs.href,dx:effect.noiseShift.attrs.dx,dy:effect.noiseShift.attrs.dy};};
  assert.deepEqual(sample([1600]),sample([16,32,80,180,500,800,1200,1600]));
  const {api,effect}=fixture();
  api.renderLiveImageGroupLiquify(effect,{x:1,y:0},1,100,0,400);
  const initial=effect.wave.attrs.href;
  api.renderLiveImageGroupLiquify(effect,{x:1,y:0},1,100,1,400);
  assert.notEqual(effect.wave.attrs.href,initial);
  const dx=Number(effect.noiseShift.attrs.dx);
  api.renderLiveImageGroupLiquify(effect,{x:1,y:0},1,250,1,400);
  assert.ok(Math.abs(Number(effect.noiseShift.attrs.dx)-dx*2.5)<1e-12);
  assert.equal(effect.fields[2].attrs.width,'575');
});

test('完整进入后鼠标静止仍有唯一 RAF，未完成不清晰；退出/清理停止循环',()=>{
  const {api,preview,effect,frames,step}=fixture();
  preview.finalWidth=300;preview.pointerX=230;preview.introStartedAt=-1000;
  api.renderLiveImageGroupPreview(preview,0);api.startLiveImageGroupPreviewFrame(preview);
  const phases=new Set();
  for(const time of [16,50,100,300,600,950]){
    step(time);phases.add(effect.wave.attrs.href);
    assert.equal(frames.size,1);assert.equal(preview.liquidCoverage,1);assert.equal(effect.enabled,true);assert.equal(effect.animated,true);
  }
  assert.ok(phases.size>4);
  api.clearImageGroupProximity({nodeId:'source',imageGroupProximity:{targetNodeId:'target',preview}});
  assert.equal(frames.size,0);assert.equal(preview.active,false);
});

test('接触期稳定后不保留动画循环，减少动态效果不会生成新径向帧',()=>{
  const {api,preview,effect,frames,step}=fixture();
  preview.finalWidth=300;preview.introStartedAt=-1000;
  api.renderLiveImageGroupPreview(preview,0);api.startLiveImageGroupPreviewFrame(preview);step(16);
  assert.equal(effect.radialMix,0);assert.equal(effect.animated,false);assert.equal(frames.size,0);
  preview.pointerX=230;preview.reducedMotion=true;
  const writes=effect.wave.writes;
  api.startLiveImageGroupPreviewFrame(preview);
  assert.equal(effect.enabled,false);assert.equal(effect.animated,false);assert.equal(frames.size,0);assert.equal(effect.wave.writes,writes);
});

test('字段更新最高 30Hz，完整周期最多 36 个合成 SVG，重复周期复用资源',()=>{
  const {api,effect}=fixture();
  api.renderLiveImageGroupLiquify(effect,{x:1,y:0},1,100,1,0);
  const waveWrites=effect.wave.writes,noiseWrites=effect.noiseShift.writes;
  for(let time=1;time<2400;time++)api.renderLiveImageGroupLiquify(effect,{x:1,y:0},1,100,1,time);
  assert.equal(effect.waves.filter(Boolean).length,36);assert.equal(effect.waves.length,36);
  assert.ok(effect.wave.writes-waveWrites<=72);assert.ok(effect.noiseShift.writes-noiseWrites<=144);
  const url=effect.wave.attrs.href,writes=effect.wave.writes;
  api.renderLiveImageGroupLiquify(effect,{x:1,y:0},1,100,1,2399);
  assert.equal(effect.wave.attrs.href,url);assert.equal(effect.wave.writes,writes);
});

test('绘制模块无图状态或独立循环，只生成合成字段并由交互模块显式注入',()=>{
  assert.ok(!/DesktopState|requestAnimationFrame|setInterval|fetch\(|getImageData|drawImage/.test(fieldSource));
  assert.match(source,/imageGroupLiquidField\.create\(defs, id, image, outline\)/);
  assert.match(source,/imageGroupLiquidField\.render\(effect, normal, strength, size, coverage, elapsedMs\)/);
  const host=fs.readFileSync(path.join(root,'frontend/scripts/desktop-canvas.js'),'utf8');
  assert.match(host,/imageGroupLiquidField: window\.DesktopCanvasImageGroupLiquidField/);
});

test('不同预览使用独立滤镜标识，按顺序加载绘制模块并更新缓存',()=>{
  const {api,Element}=fixture(),defs=new Element();
  const a=api.createLiveImageGroupLiquify(defs,'a-texture',new Element()),b=api.createLiveImageGroupLiquify(defs,'b-texture',new Element());
  api.renderLiveImageGroupLiquify(a,{x:1,y:0},1,100);api.renderLiveImageGroupLiquify(b,{x:0,y:1},.5,80);
  assert.notEqual(a.image.style.filter,b.image.style.filter);
  const html=fs.readFileSync(path.join(root,'frontend/desktop.html'),'utf8');
  assert.ok(html.includes('desktop-canvas-image-group-interaction.js?v=20261005-minimap-navigation2'));
  assert.ok(html.includes('desktop-canvas-image-group-liquid-field.js?v=20261003-image-group-radial1'));
  assert.ok(html.includes('desktop-canvas.js?v=20261007-node-progress4'));
  assert.ok(html.indexOf('scripts/desktop-canvas-image-group-liquid-field.js')<html.indexOf('scripts/desktop-canvas-image-group-interaction.js'));
  assert.ok(html.includes('desktop-image-group.css?v=20261004-node-selection-frames1'));
});

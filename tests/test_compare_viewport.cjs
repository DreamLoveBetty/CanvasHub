const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const read=p=>fs.readFileSync(path.join(__dirname,'..',p),'utf8');
function setup(){
 let queue=new Map(),next=0,observer;const window={requestAnimationFrame:f=>{queue.set(++next,f);return next;},cancelAnimationFrame:id=>queue.delete(id),ResizeObserver:class{constructor(fn){observer=this;this.fn=fn;}observe(){}disconnect(){this.disconnected=true;}}};
 vm.runInNewContext(read('frontend/scripts/desktop-compare-viewport.js'),{window});
 class Element {
  constructor(){this.style={};this.listeners={};this.attrs={};this.dataset={};this.classes=new Set();this.classList={toggle:(k,v)=>v?this.classes.add(k):this.classes.delete(k),remove:k=>this.classes.delete(k)};}
  addEventListener(t,fn){(this.listeners[t]??=[]).push(fn);}removeEventListener(t,fn){this.listeners[t]=this.listeners[t]?.filter(f=>f!==fn);}setAttribute(k,v){this.attrs[k]=v;}
  emit(t,e={}){for(const fn of this.listeners[t]??[])fn({target:this,preventDefault(){},...e});}querySelector(){return null;}querySelectorAll(){return [];}contains(target){return target===this;}focus(){}setPointerCapture(id){this.capture=id;}releasePointerCapture(){this.capture=null;}
 }
 const stage=new Element(),base=new Element(),top=new Element(),overlay=new Element(),divider=new Element(),range=new Element(),toolbar=new Element(),readout=new Element();
 const buttons=['in','out','fit','pixel'].map(action=>Object.assign(new Element(),{dataset:{compareZoom:action},closest(){return this;}}));
 toolbar.querySelectorAll=()=>buttons;toolbar.contains=target=>target===toolbar||buttons.includes(target);
 stage.querySelector=q=>q==='[data-compare-tools]'?toolbar:q==='[data-compare-zoom-value]'?readout:null;
 let rect={width:1000,height:800,left:10,top:20};stage.getBoundingClientRect=()=>rect;
 Object.assign(top,{naturalWidth:2000,naturalHeight:4000});Object.assign(base,{naturalWidth:1000,naturalHeight:2000});
 const api=window.DesktopCompareViewport,control=api.create({stage,base,top,overlay,divider,range});
 const flush=()=>{const pending=[...queue.values()];queue.clear();pending.forEach(f=>f());};
 const click=action=>{toolbar.emit('click',{target:buttons.find(b=>b.dataset.compareZoom===action)});flush();};
 return {api,control,stage,base,top,overlay,divider,range,toolbar,readout,buttons,flush,click,queue,observer,resize:r=>{rect={...rect,...r};observer.fn();flush();}};
}
test('unequal resolution originals share fitted geometry; zero-size and pixel scale are bounded',()=>{
 const {api}=setup(),imgs=[{naturalWidth:2000,naturalHeight:4000},{naturalWidth:1000,naturalHeight:2000}];
 const g=api.geometry({width:1000,height:800},imgs);assert.equal(g.band.left,300);assert.equal(g.band.width,400);assert.equal(g.pixelZoom,5);
 assert.equal(api.geometry({width:0,height:1},imgs),null);
 const clamped=api.geometry({width:1000,height:800},imgs,{zoom:2,x:999,y:-999});assert.equal(clamped.x,0);assert.equal(clamped.y,-400);
 const small=api.geometry({width:1000,height:800},[{naturalWidth:40,naturalHeight:80}],{zoom:.1});assert.equal(small.pixelZoom,.1);
});
test('cursor-anchored zoom preserves the image coordinate beneath the cursor',()=>{
 const {api}=setup(),v={zoom:2,x:17,y:-80},p={x:360,y:290},size={width:1000,height:800};const n=api.zoomAt(v,3,p,size);
 assert.equal((p.x-500-v.x)/v.zoom,(p.x-500-n.x)/n.zoom);assert.equal((p.y-400-v.y)/v.zoom,(p.y-400-n.y)/n.zoom);
});
test('zoom is synchronized, reveal remains separate, original pixels and fit work',()=>{
 const s=setup();s.control.open();s.flush();assert.equal(s.readout.textContent,'1×');assert.match(s.base.style.transform,/scale\(1\)/);
 s.click('in');assert.equal(s.readout.textContent,'1.25×');assert.match(s.top.style.transform,/scale\(1.25\)/);assert.equal(s.overlay.style.transform,'translateX(-500px)');
 s.click('pixel');assert.equal(s.readout.textContent,'5×');assert.match(s.base.style.transform,/scale\(5\)/);
 s.range.value='25';s.range.emit('input');s.flush();assert.equal(s.overlay.style.transform,'translateX(-750px)');assert.match(s.top.style.transform,/translate\(750px, 0px\)/);assert.match(s.range.attrs['aria-valuetext'],/A 25%/);
 s.click('fit');assert.equal(s.readout.textContent,'1×');assert.equal(s.overlay.style.transform,'translateX(-600px)');
});
test('zoomed image drag pans both originals; seam dragging only reveals, with pointer capture cleanup',()=>{
 const s=setup();s.control.open();s.flush();s.click('pixel');
 s.stage.emit('pointerdown',{button:0,pointerId:1,clientX:750,clientY:400});s.stage.emit('pointermove',{pointerId:1,clientX:830,clientY:430});s.flush();
 assert.equal(s.base.style.transform,'translate(80px, 30px) scale(5)');assert.equal(s.top.style.transform,'translate(580px, 30px) scale(5)');
 s.stage.emit('pointercancel',{pointerId:1});assert.equal(s.stage.capture,null);assert.equal(s.stage.classes.has('is-panning'),false);
 s.stage.emit('pointerdown',{button:0,pointerId:2,clientX:510,clientY:400});s.stage.emit('pointermove',{pointerId:2,clientX:210,clientY:400});s.flush();assert.equal(s.range.value,'20');assert.equal(s.base.style.transform,'translate(80px, 30px) scale(5)');
 s.stage.emit('lostpointercapture',{pointerId:2});assert.equal(s.stage.capture,null);
});
test('RAF coalesces wheel events, resize keeps 1:1 mode, swap preserves view; reopen resets',()=>{
 const s=setup();s.control.open();s.flush();s.click('pixel');s.resize({width:500,height:400});assert.equal(s.readout.textContent,'10×');
 s.control.open({preserve:true});s.flush();assert.equal(s.readout.textContent,'10×');
 let prevented=0;for(let i=0;i<5;i++)s.stage.emit('wheel',{deltaY:-10,deltaMode:0,clientX:250,clientY:200,preventDefault(){prevented++;}});
 assert.equal(prevented,5);assert.equal(s.queue.size,1);s.flush();assert.ok(parseFloat(s.readout.textContent)>10);
 s.control.close();assert.equal(s.queue.size,0);s.control.open();s.flush();assert.equal(s.readout.textContent,'1×');assert.equal(s.range.value,'50');
 s.control.destroy();assert.equal(s.observer.disconnected,true);assert.equal(s.stage.listeners.wheel.length,0);
});
test('toolbar does not pan or move the seam; native range keyboard remains accessible',()=>{
 const s=setup();s.control.open();s.flush();s.click('pixel');s.stage.emit('pointerdown',{button:0,pointerId:1,target:s.buttons[0],clientX:900,clientY:400});assert.equal(s.stage.capture,undefined);
 s.stage.emit('keydown',{key:'0',target:s.range});s.flush();assert.equal(s.readout.textContent,'5×');
 s.stage.emit('keydown',{key:'0'});s.flush();assert.equal(s.readout.textContent,'1×');
});
test('new viewport is explicitly assembled before history, no second compare drag implementation',()=>{
 const html=read('frontend/desktop.html'),history=read('frontend/scripts/desktop-history.js');
 assert.ok(html.indexOf('scripts/desktop-compare-viewport.js')<html.indexOf('scripts/desktop-history.js'));assert.match(html,/desktop-compare.css\?v=/);
 assert.match(history,/DesktopCompareViewport.create/);assert.match(history,/compareViewport\?\.close/);assert.doesNotMatch(history,/function compareImageBand|compareDragPointerId|comparePositionRaf/);
 for(const action of ['in','out','pixel','fit'])assert.ok(html.includes(`data-compare-zoom="${action}"`));
});

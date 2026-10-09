const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const read = name => fs.readFileSync(path.join(__dirname, '../../frontend/scripts', name + '.js'), 'utf8');

class Element {
  constructor(tag = 'div') {
    this.tagName=tag.toUpperCase(); this.className=''; this.children=[]; this.parentElement=null;
    this.dataset={};this.attributes={};this.textContent='';this.clientWidth=720;this.connected=true;
    this.style={background:'',setProperty(k,v){this[k]=v;},removeProperty(k){delete this[k];}};
    this.classList={contains:name=>this.className.split(/\s+/).includes(name),
      add:(...names)=>{this.className=[...new Set([...this.className.split(/\s+/),...names])].filter(Boolean).join(' ');},
      remove:(...names)=>{this.className=this.className.split(/\s+/).filter(n=>!names.includes(n)).join(' ');},
      toggle:(name,on)=>{on??=!this.classList.contains(name);this.classList[on?'add':'remove'](name);return on;}};
  }
  get isConnected(){return this.parentElement?this.parentElement.isConnected:this.connected;}
  appendChild(el){el.parentElement?.children.splice(el.parentElement.children.indexOf(el),1);el.parentElement=this;this.children.push(el);return el;}
  remove(){this.parentElement?.children.splice(this.parentElement.children.indexOf(this),1);this.parentElement=null;this.connected=false;}
  contains(el){return this===el||this.children.some(c=>c.contains(el));}
  setAttribute(k,v){this.attributes[k]=String(v);if(k.startsWith('data-'))this.dataset[k.slice(5).replace(/-([a-z])/g,(_,a)=>a.toUpperCase())]=String(v);}
  removeAttribute(k){delete this.attributes[k];if(k.startsWith('data-'))delete this.dataset[k.slice(5).replace(/-([a-z])/g,(_,a)=>a.toUpperCase())];}
  getAttribute(k){return this.attributes[k]??null;}
  matches(selector){return selector.split(',').some(s=>{s=s.trim();return s.startsWith('.')?this.classList.contains(s.slice(1)):s.startsWith('[')?Object.hasOwn(this.attributes,s.slice(1,-1)):s.toUpperCase()===this.tagName;});}
  querySelector(selector){for(const c of this.children){if(c.matches(selector))return c;const found=c.querySelector(selector);if(found)return found;}return null;}
}
function harness({style='liquid',height=36,drawCost=0,failCanvas=false}={}) {
  let now=0,wall=1790910750000,next=1;
  const frames=new Map(),timers=new Map(),listeners=new Map(),docListeners=new Map(),observers=[],resizeObservers=[],renderers=[];
  const media={matches:false,addEventListener(_,f){this.listener=f;},removeEventListener(){this.listener=null;}};
  const document={hidden:false,createElement:tag=>new Element(tag),
    addEventListener:(n,f)=>docListeners.set(n,f),removeEventListener:n=>docListeners.delete(n)};
  class Observer {
    constructor(callback){this.callback=callback;this.targets=new Set();observers.push(this);}
    observe(t){this.targets.add(t);}unobserve(t){this.targets.delete(t);}disconnect(){this.targets.clear();}
  }
  class ResizeObserver extends Observer {constructor(cb){super(cb);observers.pop();resizeObservers.push(this);}}
  class Renderer {
    constructor(canvas){if(failCanvas)throw Error('unavailable');this.canvas=canvas;this.draws=[];this.sizes=[];this.destroyed=false;renderers.push(this);}
    resize(w,h){this.sizes.push([w,h]);this.canvas.width=w*2;this.canvas.height=h*2;}
    draw(m,amount,style,color,flow){this.draws.push({...m,style,color,flowPhase:flow.phase});now+=drawCost;}
    destroy(){this.destroyed=true;this.canvas.width=this.canvas.height=1;}
  }
  const window={IntersectionObserver:Observer,ResizeObserver,matchMedia:()=>media,
    requestAnimationFrame:cb=>{const id=next++;frames.set(id,cb);return id;},cancelAnimationFrame:id=>frames.delete(id),
    setTimeout:(cb,delay)=>{const id=next++;timers.set(id,{cb,delay});return id;},clearTimeout:id=>timers.delete(id),
    addEventListener:(n,f)=>listeners.set(n,f),removeEventListener:n=>listeners.delete(n),DesktopProgressRenderer:{ProgressRenderer:Renderer}};
  const context=vm.createContext({window,document,performance:{now:()=>now},Date:class extends Date{static now(){return wall;}}});
  vm.runInContext(read('desktop-progress-model'),context);vm.runInContext(read('desktop-progress'),context);
  let preferences={style,height,colors:{}};
  const controller=window.DesktopProgress.create({getPreferences:()=>preferences});
  return {controller,window,document,context,frames,timers,observers,resizeObservers,renderers,listeners,docListeners,
    root(){const root=new Element();const panel=root.appendChild(new Element());panel.className='desk-progress-float__panel';const bar=panel.appendChild(new Element('span'));bar.setAttribute('data-progress-bar','');return root;},
    intersect(root,inView=true){for(const o of observers)if(o.targets.has(root))o.callback([{target:root,isIntersecting:inView}]);},
    resize(root,width){for(const o of resizeObservers)if(o.targets.has(root))o.callback([{target:root,contentRect:{width}}]);},
    step(ms=17){now+=ms;wall+=ms;const callbacks=[...frames.values()];frames.clear();callbacks.forEach(cb=>cb(now));},
    seconds(n=1){wall+=n*1000;const callbacks=[...timers.values()];timers.clear();callbacks.forEach(v=>v.cb());},
    hidden(value){document.hidden=value;docListeners.get('visibilitychange')?.();},
    reduce(value){media.matches=value;media.listener?.();},
    preferences(value){preferences={...preferences,...value};controller.refreshPreferences();},
    get now(){return now;},get wall(){return wall;},
  };
}
module.exports={harness,Element,read};

const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
const source = name => fs.readFileSync(path.join(root, 'frontend', name), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
const identity = 'a'.repeat(64);

// Small DOM ports, no browser dependency or production API calls. Real geometry
// and pointer interactions are also checked against the served desktop page.
function fixture({targets, add, available = true} = {}) {
  const dialogs = [], calls = [], details = [], messages = [], writes = [];
  let choices = targets || [{id:'k',engine:'krea2',label:'Krea 2'}, {id:'q',engine:'qwen21',label:'Qwen 2.1'}];
  class Element {
    constructor() {
      this.innerHTML='';this.dataset={};this.value='';this.disabled=false;
      this.isConnected=true;this.parts=new Map();this.handlers=new Map();
      this.classList={add(){},remove(){}};
    }
    setAttribute(key,value){this[key]=value;}
    querySelector(selector){if(!this.parts.has(selector))this.parts.set(selector,new Element());return this.parts.get(selector);}
    querySelectorAll(selector){return selector==='[data-lora-action="add-card"]'?[this.addButton]:[];}
    addEventListener(type,fn,{signal}={}){if(!this.handlers.has(type))this.handlers.set(type,[]);this.handlers.get(type).push({fn,signal});}
    emit(type,event={}){for(const {fn,signal} of this.handlers.get(type)||[])if(!signal?.aborted)fn(event);}
    showModal(){this.open=true;}
    close(){this.open=false;queueMicrotask(()=>this.emit('close'));}
    remove(){this.isConnected=false;}
    get addButton(){const control=this.querySelector('add-button');control.dataset={loraAction:'add-card',id:identity};return control;}
  }
  const document={
    createElement:()=>new Element(),
    querySelector:()=>({append:element=>dialogs.push(element)}),
    querySelectorAll:()=>dialogs.filter(el=>el.open&&el.isConnected),
  };
  const item={asset_id:identity,name:'Synthetic Style',version:'v1',available,engines:['krea2','qwen21'],members:[],previews:[],tags:[],manual_fields:[],trigger_words:[],trigger_status:'unknown'};
  const sandbox={window:{DesktopSelect:{refreshAll(){}},confirm:()=>true},document,URLSearchParams,URL,Blob,AbortController,setTimeout,clearTimeout};
  vm.createContext(sandbox);
  vm.runInContext(source('scripts/desktop-lora-data.js'),sandbox);
  vm.runInContext(source('scripts/desktop-lora-view.js'),sandbox);
  const view=sandbox.window.DesktopLoRAView.create({
    library:{list:async()=>({items:[item],total:1}),detail:async id=>{details.push(id);return item;},
      subscribe:()=>()=>{},syncState:async()=>({items:[],active:false}),changed(){},mediaUrl:value=>value,
      update:async(...args)=>writes.push(args)},
    listTargets:()=>choices,
    addToNode:async(...args)=>{calls.push(args);await add?.(...args);},
    notify:message=>messages.push(message),
  });
  function click(container,action='add-card') {
    const target=action==='add-card'?container.addButton:{dataset:{loraId:identity}};
    container.emit('click',{target:{closest:selector=>selector===(action==='add-card'?'[data-lora-action]':'[data-lora-id]')?target:null}});
  }
  return {view,item,dialogs,calls,details,messages,writes,click,setTargets:value=>choices=value,
    get openDialogs(){return dialogs.filter(el=>el.open&&el.isConnected);},
    async picker(id='k',engine='krea2'){view.openPicker(id,engine);await tick();return dialogs.at(-1).querySelector('.desk-lora-dialog__body');},
    async gallery(){const container=new Element();view.mount(container);await tick();return container;},
  };
}

test('节点选择器添加按钮直接添加到固定节点，不读详情、不写资料且不关选择器',async()=>{
  const f=fixture(),container=await f.picker('q','qwen21');
  f.click(container);await tick();
  assert.deepEqual(f.calls,[['q',identity]]);
  assert.deepEqual(f.details,[]);assert.deepEqual(f.writes,[]);
  assert.equal(f.openDialogs.length,1);
  assert.match(f.messages.at(-1),/已添加 LoRA/);
  assert.equal(container.addButton.disabled,false);
});

test('单击卡片仍打开资料编辑，绝不添加到节点',async()=>{
  const f=fixture(),container=await f.picker();f.click(container,'card');await tick();
  assert.deepEqual(f.details,[identity]);assert.deepEqual(f.calls,[]);
  assert.equal(f.openDialogs.length,2);
  assert.match(f.openDialogs.at(-1).querySelector('.desk-lora-dialog__footer').innerHTML,/保存资料/);
});

test('添加中防重复点击，列表刷新仍显示添加中；完成后恢复按钮',async()=>{
  let finish;const waiting=new Promise(resolve=>finish=resolve);
  const f=fixture({add:()=>waiting}),container=await f.picker();
  f.click(container);f.click(container);await tick();
  assert.equal(f.calls.length,1);assert.equal(container.addButton.disabled,true);
  await f.view.refresh();
  assert.match(container.querySelector('.desk-lora-grid').innerHTML,/添加中…/);
  finish();await tick();assert.equal(container.addButton.disabled,false);
  assert.equal(container.addButton.textContent,'添加');
});

test('节点控制器的重复/数量上限/运行中/节点过期错误原样反馈，恢复按钮且不打开详情',async()=>{
  for(const message of ['该 LoRA 已加载','已达到普通 LoRA 数量上限','节点正在运行或已不存在','节点状态已变化，请重新选择']){
    const f=fixture({add:()=>{throw new Error(message);}}),container=await f.picker();
    f.click(container);await tick();
    assert.equal(f.messages.at(-1),message);assert.equal(container.addButton.disabled,false);
    assert.equal(f.openDialogs.length,1);assert.deepEqual(f.details,[]);assert.deepEqual(f.writes,[]);
  }
});

test('固定目标被删除时不回退到另一个兼容节点',async()=>{
  const f=fixture(),container=await f.picker();f.setTargets([{id:'q',engine:'qwen21',label:'Other'}]);
  f.click(container);await tick();assert.deepEqual(f.calls,[]);assert.match(f.messages.at(-1),/不存在或不兼容/);
});

test('切换选择器不改变正在提交的目标，旧关闭事件不拆除新面板',async()=>{
  let finish;const f=fixture({add:()=>new Promise(resolve=>finish=resolve)}),container=await f.picker();
  f.click(container);await tick();await f.picker('q','qwen21');finish();await tick();
  assert.deepEqual(f.calls,[['k',identity]]);assert.equal(f.openDialogs.length,1);
});

test('资产库只有一个兼容节点时直接添加，缺少节点或权重时仅提示',async()=>{
  const f=fixture({targets:[{id:'q',engine:'qwen21',label:'Qwen'}]}),container=await f.gallery();
  f.click(container);await tick();assert.deepEqual(f.calls,[['q',identity]]);assert.equal(f.openDialogs.length,0);
  for(const options of [{targets:[]},{available:false}]){
    const invalid=fixture(options),list=await invalid.gallery();invalid.click(list);await tick();
    assert.deepEqual(invalid.calls,[]);assert.deepEqual(invalid.details,[]);assert.equal(invalid.messages.length,1);
  }
});

test('资产库多节点只显示目标选择，确认前不添加也不打开资料',async()=>{
  const f=fixture(),container=await f.gallery();f.click(container);await tick();
  const modal=f.openDialogs[0];assert.equal(modal['aria-label'],'添加 LoRA 到节点');
  assert.deepEqual(f.calls,[]);assert.deepEqual(f.details,[]);
  assert.ok(!modal.querySelector('.desk-lora-dialog__body').innerHTML.includes('data-lora-edit'));
  modal.querySelector('[data-lora-add-target]').value='q';
  await modal.querySelector('[data-lora-action="confirm-add"]').onclick();await tick();
  assert.deepEqual(f.calls,[['q',identity]]);assert.equal(f.openDialogs.length,0);
});

test('目标选择期间节点删除不会误添加；退出列表清理选择面板',async()=>{
  const f=fixture(),container=await f.gallery();f.click(container);await tick();
  const modal=f.openDialogs[0];modal.querySelector('[data-lora-add-target]').value='k';f.setTargets([]);
  await modal.querySelector('[data-lora-action="confirm-add"]').onclick();
  assert.deepEqual(f.calls,[]);assert.match(f.messages.at(-1),/不存在或不兼容/);
  f.view.unmount();await tick();assert.equal(f.openDialogs.length,0);
});

test('卡片使用纵向 flex 与自动底边距对齐底栏，不用绝对定位覆盖内容',()=>{
  const css=source('styles/desktop-lora.css');
  const card=css.match(/\.desk-app \.desk-lora-card \{([^}]+)\}/)[1];
  const footer=css.match(/\.desk-app \.desk-lora-card footer \{([^}]+)\}/)[1];
  assert.match(card,/display: flex/);assert.match(card,/flex-direction: column/);
  assert.match(footer,/margin-top: auto/);assert.match(footer,/flex: 0 0 auto/);
  assert.ok(!footer.includes('position: absolute'));
});

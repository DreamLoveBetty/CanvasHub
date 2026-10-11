const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');
const root = path.join(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, 'frontend', file), 'utf8');

// Minimal DOM ports: exercise the actual view lifecycle without browser/network
// dependencies. Geometry, pointer hit testing and theme colors are checked on
// the served page with synthetic API fixtures.
function viewFixture(overrides = {}) {
  const dialogs = [], updates = [];
  let item = {asset_id:'a'.repeat(64),name:'Style',version:'v1',engines:['krea2'],members:[],previews:[],trigger_words:['style word'],trigger_status:'provided',tags:[],manual_fields:[],favorite:false,hidden:false,...overrides};
  const element = () => ({innerHTML:'',dataset:{},value:'',classList:{add(){}},setAttribute(){},addEventListener(){}});
  const doc = {
    querySelector:()=>({append:node=>dialogs.push(node)}),
    querySelectorAll:()=>dialogs,
    createElement:()=>{
      const parts=new Map();
      return {...element(),showModal(){},close(){},remove(){},
        querySelector(selector){if(!parts.has(selector))parts.set(selector,element());return parts.get(selector);},
        querySelectorAll:()=>[],
      };
    },
  };
  const sandbox={window:{DesktopSelect:{refreshAll(){}},confirm:()=>true},document:doc,URLSearchParams,URL,Blob};
  vm.createContext(sandbox);
  vm.runInContext(read('scripts/desktop-lora-data.js'),sandbox);
  vm.runInContext(read('scripts/desktop-lora-view.js'),sandbox);
  const view=sandbox.window.DesktopLoRAView.create({
    library:{detail:async()=>item,mediaUrl:x=>x,update:async(_,patch)=>{updates.push(JSON.parse(JSON.stringify(patch)));item={...item,...patch};}},
    listTargets:()=>[{id:'node',engine:'krea2',label:'Krea 2'}],
  });
  return {view,dialogs,updates};
}

test('LoRA 详情保留全部编辑字段，低频资料折叠且保存栏独立于滚动区',async()=>{
  const f=viewFixture();await f.view.openDetail('a'.repeat(64));
  const modal=f.dialogs[0],body=modal.querySelector('.desk-lora-dialog__body'),footer=modal.querySelector('.desk-lora-dialog__footer');
  assert.equal(footer.hidden,false);
  assert.ok(!body.innerHTML.includes('data-lora-action="save"'));
  assert.ok(footer.innerHTML.includes('data-lora-action="save"'));
  const fields=[...(body.innerHTML+footer.innerHTML).matchAll(/data-lora-edit="([^"]+)"/g)].map(m=>m[1]);
  assert.deepEqual(fields.sort(),['name','version','trigger_status','trigger_words','description','tags','recommended_scale','source_name','source_url','favorite','hidden'].sort());
  assert.match(body.innerHTML,/<details class="desk-lora-disclosure desk-lora-source"><summary>Civitai 资料/);
  assert.match(body.innerHTML,/<details class="desk-lora-disclosure"><summary>文件信息与权重操作/);
  assert.match(body.innerHTML,/<details class="desk-lora-disclosure desk-lora-trigger-editor">/);
  assert.ok(!body.innerHTML.includes('data-desk-select-ignore'));
});

test('未填写触发词时直接展开编辑，保持手动添加入口',async()=>{
  const f=viewFixture({trigger_words:[],trigger_status:'unknown'});await f.view.openDetail('id');
  assert.match(f.dialogs[0].querySelector('.desk-lora-dialog__body').innerHTML,/<details class="desk-lora-disclosure desk-lora-trigger-editor" open>/);
});

test('单行字段同排，状态放标题行，多行编辑不与短控件拼列',async()=>{
  const f=viewFixture();await f.view.openDetail('id');
  const html=f.dialogs[0].querySelector('.desk-lora-dialog__body').innerHTML;
  const identity=html.match(/<div class="desk-lora-fields desk-lora-fields--identity">([\s\S]*?)<\/div>/)[1];
  assert.deepEqual([...identity.matchAll(/data-lora-edit="([^"]+)"/g)].map(m=>m[1]),['name','version','recommended_scale']);
  for(const [,fields] of html.matchAll(/<div class="desk-lora-fields[^">]*">([\s\S]*?)<\/div>/g))assert.ok(!fields.includes('<textarea'));
  const heading=html.match(/<section class="desk-lora-triggers"><div class="desk-lora-section-head">([\s\S]*?)<\/div>/)[1];
  assert.ok(heading.includes('data-lora-edit="trigger_status"'));
  const editor=html.match(/<details class="desk-lora-disclosure desk-lora-trigger-editor">([\s\S]*?)<\/details>/)[1];
  assert.ok(editor.includes('data-lora-edit="trigger_words"'));
  assert.ok(!editor.includes('<select'));
  assert.match(html,/<\/label>\s*<label><span>标签 · 每行一个<\/span><textarea/);
});

test('固定保存栏的收藏操作参与脏状态及原有更新接口',async()=>{
  const f=viewFixture();await f.view.openDetail('id');
  const modal=f.dialogs[0],footer=modal.querySelector('.desk-lora-dialog__footer');
  footer.onchange({target:{matches:selector=>selector==='[data-lora-edit]'}});
  assert.equal(modal.dataset.dirty,'true');
  modal.querySelectorAll=()=>[{dataset:{loraEdit:'favorite'},type:'checkbox',checked:true}];
  footer.onclick({target:{closest:()=>({dataset:{loraAction:'save'}})}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(f.updates,[{favorite:true}]);
  assert.equal(modal.dataset.dirty,'false');
});

function selectPorts() {
  const body={},sandbox={window:{addEventListener(){}},document:{body,readyState:'loading',addEventListener(){}}};
  vm.createContext(sandbox);
  vm.runInContext(read('scripts/desktop-select.js').replace('  window.DesktopSelect = {','  window.__layoutPorts = {menuContainer, usesAnchoredMenu, inferVariant};\n  window.DesktopSelect = {'),sandbox);
  return {body,...sandbox.window.__layoutPorts};
}

test('统一下拉菜单留在当前原生模态层，不改变普通页面和画布的挂载契约',()=>{
  const ports=selectPorts(),dialog={},nested={};
  assert.equal(ports.menuContainer({closest:()=>null}),ports.body);
  assert.equal(ports.menuContainer({closest:selector=>selector==='dialog'?dialog:null}),dialog);
  assert.equal(ports.menuContainer({closest:selector=>selector==='dialog'?nested:null}),nested);
  assert.equal(ports.usesAnchoredMenu({closest:selector=>selector==='.desk-canvas-world .desk-node'?{}:null}),true);
  const regular={id:'',closest:()=>null,classList:{contains:()=>false}};
  assert.equal(ports.inferVariant(regular),'default');
  assert.equal(ports.inferVariant({...regular,closest:selector=>selector==='.desk-lora-library, .desk-lora-dialog'?{}:null}),'gallery');
});

test('LoRA 控件复用已有字号/尺寸 token，没有引入未定义的主题变量',()=>{
  const css=read('styles/desktop-lora.css');
  assert.match(css,/height: var\(--desk-control-height-sm\)/);
  assert.match(css,/font-size: var\(--desk-font-size-caption\)/);
  const definitions=fs.readdirSync(path.join(root,'frontend/styles')).filter(x=>x.endsWith('.css')).map(x=>read('styles/'+x)).join('\n');
  for(const [,name] of css.matchAll(/var\((--[\w-]+)/g))assert.match(definitions,new RegExp(name+'\\s*:'),name);
  assert.ok(!read('scripts/desktop-lora-view.js').includes('data-desk-select-ignore'));
  const html=read('desktop.html');
  for(const asset of ['styles/desktop-lora.css','scripts/desktop-lora-view.js','scripts/desktop-select.js'])assert.ok(hasCacheKey(html,asset),asset);
});

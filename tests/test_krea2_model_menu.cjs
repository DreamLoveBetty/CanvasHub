const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const read=name=>fs.readFileSync(path.join(__dirname,'../frontend',name),'utf8');
const sandbox={window:{addEventListener(){}},document:{readyState:'loading',addEventListener(){}},Math};
vm.runInNewContext(read('scripts/desktop-select.js').replace('  window.DesktopSelect = {',
  '  window.__geometry = {placeAnchoredMenu, placeMenu};\n  window.DesktopSelect = {'),sandbox);
const G=sandbox.window.__geometry;

function state({wide=true,scale=1,x=300,shellWidth=460,naturalWidth=650,viewport=1440,fixed=false}={}){
  sandbox.window.innerWidth=viewport;sandbox.window.innerHeight=900;
  const rect={left:x,right:x+shellWidth*scale,top:180,bottom:212,width:shellWidth*scale,height:32*scale};
  return {open:true,variant:'default',menuMode:fixed?'fixed':'anchored',select:{},
    trigger:{offsetWidth:shellWidth,offsetHeight:32,getBoundingClientRect:()=>rect},
    shell:{offsetWidth:shellWidth,getBoundingClientRect:()=>rect},
    menu:{dataset:{selectWidth:wide?'content':''},style:{},offsetWidth:naturalWidth,scrollHeight:140,classList:{toggle(){}}}};
}

test('模型菜单至少与控件等宽并按长名称扩宽，不再限于 320px',()=>{
  for(const width of [460,650]){
    const s=state({naturalWidth:width});G.placeAnchoredMenu(s);
    assert.equal(s.menu.style.width,width+'px');
  }
});

test('模型菜单在画布缩放和左右屏幕边界下保持可见',()=>{
  for(const scale of [.1,.75,1,1.8])for(const x of [-150,300,1050]){
    const s=state({scale,x,viewport:1180,naturalWidth:1800});G.placeAnchoredMenu(s);
    const width=parseFloat(s.menu.style.width)*scale,left=x+parseFloat(s.menu.style.left)*scale;
    assert.ok(left>=7.9,{scale,x,left});
    assert.ok(left+width<=1172.1,{scale,x,left,width});
  }
});

test('不选择扩宽模式的下拉仍保留原来的宽度限制',()=>{
  const s=state({wide:false});G.placeAnchoredMenu(s);
  assert.equal(s.menu.style.width,'320px');assert.equal(s.menu.style.left,'0px');
});

test('非画布扩宽菜单也受视口约束',()=>{
  const s=state({fixed:true,x:1050,viewport:1180,naturalWidth:1300});G.placeMenu(s);
  assert.equal(s.menu.style.width,'1164px');assert.equal(s.menu.style.left,'8px');
});

test('只有 Krea Base 选择器启用扩宽，加载前不制造未安装 Mixed 占位项',()=>{
  const ctx={window:{addEventListener(){}},AbortController};
  vm.runInNewContext(read('scripts/desktop-krea2-model.js'),ctx);
  vm.runInNewContext(read('scripts/desktop-canvas-krea2.js'),ctx);
  const controller=ctx.window.DesktopCanvasKrea2.create({model:ctx.window.DesktopKrea2Model});
  const html=controller.nodeHtml({id:'synthetic',type:'krea2'});
  assert.match(html,/data-desk-select-width="content" data-krea2-field="baseModelId"/);
  assert.doesNotMatch(html,/Mixed 4\/8-bit|krea-2-turbo-alis-mlx-mixed-4-8/);
  assert.equal((html.match(/data-desk-select-width="content"/g)||[]).length,1);
  assert.doesNotMatch(read('scripts/desktop-canvas-qwen21.js'),/data-desk-select-width="content"/);
  assert.match(read('styles/desktop-liquid.css'),/body\.desk-app \.desk-select-menu\[data-select-width="content"\] \.desk-select-option\s*\{[^}]*white-space: nowrap;[^}]*text-overflow: ellipsis;/);
  assert.match(read('scripts/desktop-select.js'),/title="\$\{escapeHtml\(item.label\)\}"/);
});

const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const read=name=>fs.readFileSync(path.join(__dirname,'../frontend',name),'utf8');

const css=read('styles/desktop-liquid.css');
const rule=selector=>{
  const start=css.indexOf(`\n${selector} {`);
  assert.ok(start>=0,selector);
  return css.slice(start,css.indexOf('}',start));
};

test('打开下拉时把菜单字号同步为触发器实际字号',()=>{
  const properties={};
  const sandbox={Math,Number,setTimeout,clearTimeout,
    window:{addEventListener(){},getComputedStyle:element=>({fontSize:element.fontSize}),requestAnimationFrame(){},innerWidth:1200,innerHeight:800},
    document:{readyState:'loading',addEventListener(){}},
    requestAnimationFrame(){}};
  vm.runInNewContext(read('scripts/desktop-select.js').replace('  window.DesktopSelect = {',
    '  window.__open = open;\n  window.DesktopSelect = {'),sandbox);
  const classList={add(){},remove(){},toggle(){}};
  const rect={left:0,right:100,top:0,bottom:30,width:100,height:30};
  const state={select:{selectedIndex:-1,children:[],options:[],getAttribute(){return ''}},variant:'default',menuMode:'fixed',
    shell:{classList,offsetWidth:100,getBoundingClientRect:()=>rect},
    trigger:{setAttribute(){},removeAttribute(){},getAttribute(){return ''},getBoundingClientRect:()=>rect},
    valueEl:{fontSize:'10.5px'},
    menu:{dataset:{},style:{setProperty(name,value){properties[name]=value}},classList,setAttribute(){},querySelectorAll:()=>[],scrollHeight:100,offsetWidth:100}};
  sandbox.window.__open(state);
  assert.equal(properties['--desk-select-menu-font-size'],'10.5px');
});

test('菜单以同步字号为准，并为逐字段继承保留 token 兜底',()=>{
  assert.match(rule('.desk-select-menu'),/font-size: var\(--desk-select-menu-font-size, var\(--desk-font-size-caption\)\);/);
  assert.match(rule('.desk-select-option'),/min-height: 24px;[\s\S]*line-height: 14px;/);
});

test('参数网格的说明文字规则不再影响下拉取值',()=>{
  assert.match(css,/\.desk-param-grid span:not\(\.desk-select-value\),/);
  assert.match(css,/\.desk-prompt-mode span:not\(\.desk-select-value\) \{/);
});

test('节点分段按钮声明字号，不继承 16px',()=>{
  assert.match(rule('.desk-segment button'),/font-size: var\(--desk-font-size-label\);/);
});

test('音乐节点的按钮样式不套到下拉选项上',()=>{
  assert.match(read('styles/desktop-music.css'),/\.desk-music__body button:not\(\.desk-select-option\) \{/);
});

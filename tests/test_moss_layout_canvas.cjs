const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {load,plain,textNode,setup,mount}=require('./moss_frontend_fixture.cjs');
const L=load(['desktop-moss-layout.js'],{AbortController,document:{}}).window.DesktopMossLayout;
const size={width:1024,height:512};
const box=(id,label='object',extra={})=>({id,label,caption:'猫',bbox:[0,0,100,100],...extra});

// Captures the ports each session hands its editor; the real DOM editor is driven by the browser probe.
function withEditor(options={}){
  const editors={};
  const t=setup({layoutModes:['layout'],layoutFactory:ports=>{editors.ports=ports;return{render(){},close(){},dispose(){editors.disposed=true;}};},...options});
  return{t,editors};
}

test('坐标映射已含外层缩放：同一点在不同 zoom 得到同一画幅坐标',()=>{
  for(const zoom of [.25,.75,1,2])assert.deepEqual(plain(L.toImage({x:10+250*zoom,y:20+50*zoom},{left:10,top:20,width:500*zoom,height:250*zoom},size)),{x:512,y:102});
  assert.deepEqual(plain(L.toImage({x:-99,y:9999},{left:0,top:0,width:100,height:100},size)),{x:0,y:512});
});

test('建框：反向拖动归一，单击给默认尺寸且不越界',()=>{
  assert.deepEqual(plain(L.boxFromPoints({x:200,y:300},{x:100,y:100},size)),[100,100,200,300]);
  const click=L.boxFromPoints({x:1020,y:510},{x:1020,y:510},size);
  assert.ok(click[2]<=1024&&click[3]<=512&&click[2]-click[0]===240);
});

test('移动不出界、边角缩放保最小边、对齐',()=>{
  assert.deepEqual(plain(L.moveBox([10,10,110,110],-99,9999,size)),[0,412,100,512]);
  assert.deepEqual(plain(L.resizeBox([100,100,200,200],'nw',-20,-30,size)),[80,70,200,200]);
  assert.deepEqual(plain(L.resizeBox([100,100,200,200],'se',-999,-999,size)),[100,100,116,116]);
  assert.deepEqual(plain(L.resizeBox([100,100,200,200],'ne',9999,0,size)),[100,100,1024,200]);
  assert.deepEqual(plain(L.alignBox([10,10,110,110],'right',size)),[924,10,1024,110]);
  assert.deepEqual(plain(L.alignBox([10,10,110,110],'middle',size)),[10,206,110,306]);
});

test('新区域、复制与类型切换带上内容和绑定',()=>{
  const text=L.createItem([],'text',[0,0,9,9]);assert.equal(text.text,'');assert.equal(text.textSource.kind,'inline');
  const object=L.createItem([{id:'region-2'},{id:'x'}],'object',[0,0,9,9]);assert.equal(object.id,'region-3');assert.equal(object.text,undefined);
  const copy=L.duplicateItem([box('a')],box('a'),size);assert.notEqual(copy.id,'a');assert.deepEqual(plain(copy.bbox),[24,24,124,124]);
  const bound=L.changeLabel(box('a','object',{captionSource:{kind:'text_node',nodeId:'n'}}),'text');
  assert.equal(bound.text,'猫');assert.equal(bound.textSource.nodeId,'n');assert.equal(bound.captionSource,undefined);
  assert.equal(L.changeLabel(box('a','object'),'character').label,'character');
});

test('点选画板后放开鼠标，焦点回到按键接收框，避免 Delete 落到画布删掉节点',()=>{
  const listeners={};let focused=0,resized=0,selected=0;
  const keys={focus(){focused++;}},board={getBoundingClientRect:()=>({left:0,top:0,width:100,height:100})};
  const host={hidden:false,innerHTML:'',addEventListener:(type,handler)=>{listeners[type]=handler;},querySelector:selector=>selector==='[data-moss-keys]'?keys:selector==='[data-moss-board]'?board:null,querySelectorAll:()=>[]};
  const node={imageWidth:1024,imageHeight:1024,freeDraft:{items:[]}};
  const editor=L.create({host,getNode:()=>node,canEdit:()=>true,listTextSources:()=>[],fieldPreview:()=>({}),select:()=>{selected++;},resized:()=>{resized++;}});
  editor.open();assert.ok(resized>0);
  const target={closest:selector=>selector==='[data-moss-board]'?board:null};
  listeners.pointerdown({target,clientX:5,clientY:5,stopPropagation(){}});
  focused=0;listeners.pointerup({});
  assert.equal(selected,1);assert.equal(focused,1);
  listeners.pointerup({});assert.equal(focused,1);
});

test('编辑器由控制器按节点各建一份，销毁时释放',async()=>{
  const {t,editors}=withEditor({node:{mode:'layout',freeDraft:{items:[box('a')]}}});await mount(t);
  assert.equal(editors.ports.getNode(),t.moss);
  t.controller.dispose('m');assert.equal(editors.disposed,true);
});

test('撤销可恢复绑定：依赖边随草稿重建，失败回滚',async()=>{
  const {t,editors}=withEditor({node:{mode:'layout',freeDraft:{items:[box('a')]}},text:[textNode('n','一')]});await mount(t);
  editors.ports.bindTextSource('a','caption','n');
  const withBinding=plain(t.moss.freeDraft);
  editors.ports.updateDraft({...plain(t.moss.freeDraft),items:[]});assert.equal(t.canvas.edges.length,0);
  editors.ports.updateDraft(withBinding);
  assert.equal(t.canvas.edges.length,1);assert.equal(t.moss.freeDraft.items[0].captionSource.nodeId,'n');
  const empty={...withBinding,items:[]};editors.ports.updateDraft(empty);t.setFail(true);
  assert.throws(()=>editors.ports.updateDraft(withBinding),/连接失败/);
  assert.equal(t.moss.freeDraft.items.length,0);
});

test('失效来源预览标错，解绑保留可读内容，绑定预览不写回节点',async()=>{
  const {t,editors}=withEditor({node:{mode:'layout',freeDraft:{items:[box('a',undefined,{caption:'旧'})]}},text:[textNode('n','新')]});await mount(t);
  editors.ports.bindTextSource('a','caption','n');
  const item=t.moss.freeDraft.items[0];
  assert.equal(editors.ports.fieldPreview(item).text,'新');assert.equal(item.caption,'旧');
  delete t.canvas.nodes.n;assert.equal(editors.ports.fieldPreview(item).issue,'来源已删除');
  t.canvas.nodes.n=textNode('n','再改');editors.ports.bindTextSource('a','caption',null);
  assert.equal(t.moss.freeDraft.items[0].caption,'再改');
});

test('运行中只读：不能改草稿；收起不改内容指纹',async()=>{
  const {t,editors}=withEditor({node:{mode:'layout',prompt:'全局',freeDraft:{items:[box('a')]},jobId:'moss_'+'a'.repeat(32),status:'running'}});await mount(t);
  assert.equal(editors.ports.canEdit(),false);
  assert.throws(()=>editors.ports.updateDraft({items:[]}),/运行/);
  const before=t.M.resolveTextSources(t.moss,{getNodeState:()=>null,materializeText:()=>''}).inputFingerprint;
  editors.ports.collapse();assert.equal(t.moss.settingsExpanded,false);
  assert.equal(t.M.resolveTextSources(t.moss,{getNodeState:()=>null,materializeText:()=>''}).inputFingerprint,before);
});

test('导入须确认，取消不改节点；确认后替换并递增修订',async()=>{
  const draft={schema:'canvashub.moss.layout',schema_version:1,mode:'layout',width:768,height:512,prompt:'新',prompt_source:{kind:'inline'},free_draft:{summary:{},items:[box('z')]}};
  const {t,editors}=withEditor({node:{mode:'layout',freeDraft:{items:[box('a')]}},api:{importDraft:async()=>({kind:'import_draft',draft})}});await mount(t);
  t.setConfirm(false);assert.equal(await editors.ports.importDraft('{}'),false);assert.equal(t.moss.freeDraft.items[0].id,'a');
  t.setConfirm(true);const revision=t.moss.draftRevision;assert.equal(await editors.ports.importDraft('{}'),true);
  assert.equal(t.moss.freeDraft.items[0].id,'z');assert.equal(t.moss.imageWidth,768);assert.ok(t.moss.draftRevision>revision);
});

test('画幅变化同比缩放区域',()=>{
  const {M}=setup();
  const node=M.normalize({type:'moss',imageWidth:2048,imageHeight:512,freeDraft:{items:[box('a',undefined,{bbox:[256,128,512,256]})]}});
  node.imageWidth=1024;node.imageHeight=1024;M.scaleFreeDraft(node,2048,512);
  assert.deepEqual(plain(node.freeDraft.items[0].bbox),[128,256,256,512]);
});

test('自由 Layout 空画板不可提交；分镜仍标未开放',async()=>{
  const {t}=withEditor({node:{mode:'layout',prompt:'全局'}});await mount(t);await t.controller.run('m');
  assert.equal(t.log.submits.length,0);
  assert.match(t.controller.nodeHtml(t.moss),/分镜网格 · 尚未开放/);assert.doesNotMatch(t.controller.nodeHtml(t.moss),/自由 Layout · 尚未开放/);
});

test('无常驻属性表单：节点不含 XYWH 输入，草稿字段不暴露为侧栏',()=>{
  const source=fs.readFileSync(path.join(__dirname,'../frontend/scripts/desktop-moss-layout.js'),'utf8');
  assert.doesNotMatch(source,/XYWH|type="number"|desk-moss-layout__side/);
  assert.match(source,/isComposing/);
});

const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.join(__dirname,'..');
const read=name=>fs.readFileSync(path.join(root,'frontend/scripts',name),'utf8');
function environment(){const sandbox={window:{},URLSearchParams,URL,Blob,location:{href:'http://localhost/desktop.html',origin:'http://localhost'}};vm.createContext(sandbox);vm.runInContext(read('desktop-lora-data.js'),sandbox);vm.runInContext(read('desktop-canvas-lora.js'),sandbox);return sandbox;}
const plain=value=>JSON.parse(JSON.stringify(value));

test('触发词保留词组和大小写，只按换行拆分',()=>{
 const {window:w}=environment();assert.deepEqual(plain(w.DesktopLoRAData.parseWords('My Phrase\nMy Phrase\nmy phrase\nword, detail')),['My Phrase','my phrase','word, detail']);
});
test('触发词插入去重使用完整词边界，不误认子串',()=>{
 const {window:w}=environment();const fn=w.DesktopLoRAData.appendWords;
 assert.deepEqual(plain(fn('a cat, My Phrase',['cat','My Phrase','dog','dog'])),{added:['dog'],suffix:'\ndog'});
 assert.deepEqual(plain(fn('concatenate',['cat'])),{added:['cat'],suffix:'\ncat'});
 assert.deepEqual(plain(fn('', ['My Phrase'])),{added:['My Phrase'],suffix:'My Phrase'});
});
test('共享数据通过认证适配访问，读操作不会触发变更循环',async()=>{
 const {window:w}=environment(),requests=[];let notices=0;
 const item={asset_id:'a'.repeat(64),name:'Style',revision:0};
 const client={json:async(url,options)=>{requests.push({url,options});return url.includes('/list')?{items:[item]}:{item:{...item,name:'New'}};}};
 const lib=w.DesktopLoRAData.create({getClient:()=>client});const stop=lib.subscribe(()=>notices++);
 await lib.list({engine:'krea2'});assert.equal(notices,0);assert.equal(lib.peek(item.asset_id).name,'Style');
 await lib.update(item,{name:'New'});assert.equal(notices,1);assert.equal(lib.peek(item.asset_id).name,'New');
 const payload=JSON.parse(requests[1].options.body);assert.equal(payload.asset_id,item.asset_id);assert.equal(payload.revision,0);assert.deepEqual(payload.reset_fields,[]);
 stop();lib.changed();assert.equal(notices,1);
});
test('资料图复制只允许同源资产，不把凭证发往任意远端',async()=>{
 const {window:w}=environment();let called=false;
 const lib=w.DesktopLoRAData.create({getClient:()=>({blob:async()=>{called=true;return 'image';}})});
 await assert.rejects(lib.imageBlob('https://untrusted.test/image'),/本地/);assert.equal(called,false);
 assert.equal(await lib.imageBlob('/archive_image/a.png'),'image');
});
function graphFixture(){
 const {window:w}=environment();const canvas={nodes:{k:{id:'k',type:'krea2',x:400,y:50},q:{id:'q',type:'qwen21',x:900,y:50},t:{id:'t',type:'text',text:'original',promptDocument:{version:1,segments:[{type:'prompt_block',block_id:'block',content_snapshot:'original'},{type:'image_reference',source_node_id:'image',instance_id:'keep-image'}]}}},edges:[{from:'t',to:'k'}]};
 let writes=0,mutable=true;const added=[];
 const controller={canEdit:()=>mutable,addLoRA:async(...args)=>added.push(args)};
 const textNodes=id=>canvas.edges.filter(e=>e.to===id).map(e=>canvas.nodes[e.from]).filter(n=>n?.type==='text');
 const materialize=node=>node.promptDocument?.segments.map(x=>x.text||x.content_snapshot||'[image]').join('')||node.text||'';
 const bridge=w.DesktopCanvasLoRA.create({getCanvas:()=>canvas,getNodeState:id=>canvas.nodes[id],getNodeElement:()=>({}),getTextNodes:textNodes,materializeText:materialize,
 cloneDocument:(document,text)=>document?plain(document):{version:1,segments:[{type:'text',text}]},setDocument:(_,node,document)=>{node.promptDocument=document;node.text=materialize(node);writes++;},
 addNode:(type,position)=>{canvas.nodes.new={id:'new',type,...position,text:''};return 'new';},removeNode:id=>delete canvas.nodes[id],connectNodes:(from,to)=>canvas.edges.push({from,to}),getController:()=>controller,getSelectedIds:()=>['q']});
 return {bridge,canvas,added,writes:()=>writes,block:()=>mutable=false};
}
test('按当前选择排序兼容节点，普通 LoRA 走节点领域控制器',async()=>{
 const f=graphFixture();assert.equal(f.bridge.listTargets()[0].id,'q');await f.bridge.addToNode('k','a'.repeat(64));assert.deepEqual(f.added,[['k','a'.repeat(64)]]);
 await assert.rejects(f.bridge.addToNode('t','id'),/不兼容/);
});
test('插入触发词保留素材块与图片引用，不扁平化文档',()=>{
 const f=graphFixture(),before=plain(f.canvas.nodes.t.promptDocument.segments);
 f.bridge.insertTriggers('k','t',['My Phrase']);const segments=f.canvas.nodes.t.promptDocument.segments;
 assert.deepEqual(plain(segments.slice(0,2)),before);assert.equal(segments[2].text,'\nMy Phrase');assert.equal(f.writes(),1);
 f.bridge.insertTriggers('k','t',['My Phrase']);assert.equal(f.writes(),1);
});
test('文本断开、目标删除、运行中均拒绝过期插入',()=>{
 const f=graphFixture();assert.throws(()=>f.bridge.insertTriggers('q','t',['word']),/断开/);
 f.block();assert.throws(()=>f.bridge.insertTriggers('k','t',['word']),/运行/);assert.equal(f.writes(),0);
 delete f.canvas.nodes.k;assert.throws(()=>f.bridge.insertTriggers('k','t',['word']),/不存在/);
});
test('无文本时显式新建并连接，不向已有输入追加第二个节点',()=>{
 const f=graphFixture();assert.throws(()=>f.bridge.insertTriggers('k','',['word']),/已有文本/);
 f.bridge.insertTriggers('q','',['word']);assert.equal(f.canvas.nodes.new.text,'word');assert.ok(f.canvas.edges.some(e=>e.from==='new'&&e.to==='q'));
});
test('两个节点共用可视化选择器，不改变权重任务参数或外挂进度',()=>{
 for(const engine of ['krea2','qwen21']){
  const source=read(`desktop-canvas-${engine}.js`);assert.ok(source.includes('loraView?.openPicker'));assert.ok(source.includes('addLoRA,canEdit'));assert.ok(source.includes('asset_id:item.assetId')||source.includes('asset_id:x.assetId'));assert.ok(source.includes(`data-${engine}-progress`));
 }
 const html=fs.readFileSync(path.join(root,'frontend/desktop.html'),'utf8');
 assert.ok(html.indexOf('desktop-lora-data.js')<html.indexOf('desktop-api.js'));
 assert.ok(html.indexOf('desktop-canvas-lora.js')<html.indexOf('scripts/desktop-canvas.js'));
 assert.ok(html.includes('data-gallery-view="loras"'));assert.ok(html.includes('20261002-lora-library3'));
});

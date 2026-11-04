const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {load,plain,textNode,setup,mount}=require('./moss_frontend_fixture.cjs');
const G=load(['desktop-moss-grid.js'],{AbortController,document:{}}).window.DesktopMossGrid;
const size={width:1024,height:1024},panel=(id,caption='猫')=>({id,caption,captionSource:{kind:'inline'}});
const draft=(rows,cols,extra={})=>({summary:{},rows,cols,margin:8,gutter:8,panels:Array.from({length:rows*cols},(_,index)=>panel('p'+(index+1))),...extra});
const TASK='moss_'+'b'.repeat(32);
function finished({panels=4,overlay=false}={}){
  const files=['page.png',...Array.from({length:panels},(_,index)=>`panel${index+1}.png`)];
  return{task_id:TASK,status:'succeeded_no_telegram',prompt:'整页',result_file:files[0],result_files:files,image_paths:files.map(name=>'/img/'+name),
    params:{artifacts:[{role:'original',file:files[0]},...files.slice(1).map((file,index)=>({role:'panel',file,panel_id:'p'+(index+1),panel_index:index})),...(overlay?[{role:'grid_overlay',file:'_layout_drafts/o.png'}]:[])]}};
}
function withGrid(options={}){
  const editors={},job=options.task||finished();
  const t=setup({layoutModes:['layout','storyboard'],gridFactory:ports=>{editors.ports=ports;return{render(){},close(){},dispose(){}};},node:{mode:'storyboard',gridDraft:draft(2,2),...options.node},text:options.text,api:{job:async()=>job,...options.api}});
  return{t,editors,job};
}
const runToEnd=async t=>{await mount(t);await t.controller.run('m');await t.settle();await t.settle();};

test('全部格数与转置：几何与后端一致，每格正面积不重叠',()=>{
  assert.deepEqual(plain(G.cells(draft(2,2),size)),[[8,8,508,508],[516,8,1016,508],[8,516,508,1016],[516,516,1016,1016]]);
  for(const [rows,cols] of Object.values(G.SHAPES).flatMap(shape=>[shape,[shape[1],shape[0]]])){
    const boxes=G.cells(draft(rows,cols),{width:1000,height:601});
    assert.equal(boxes.length,rows*cols);
    boxes.forEach(box=>assert.ok(box[2]>box[0]&&box[3]>box[1]&&box[0]>=8&&box[2]<=992&&box[3]<=593));
  }
  assert.deepEqual(plain(G.partition(1000,3,8,8)),[[8,331],[339,662],[670,992]]);
  assert.equal(G.cells({...draft(2,2),margin:256,gutter:256},{width:512,height:512}),null);
});

test('换序与转置时描述和绑定跟随 panel_id，几何不变',()=>{
  const grid=draft(2,3);grid.panels[0]={id:'p1',caption:'甲',captionSource:{kind:'text_node',nodeId:'t'}};
  const moved=G.movePanel(grid,'p1',1);
  assert.deepEqual(plain(moved.panels.slice(0,2).map(item=>item.id)),['p2','p1']);assert.equal(moved.panels[1].caption,'甲');assert.equal(moved.panels[1].captionSource.nodeId,'t');
  assert.equal(G.movePanel(grid,'p1',-1),grid);
  const flipped=G.transpose(grid);assert.deepEqual([flipped.rows,flipped.cols],[3,2]);assert.equal(flipped.panels,grid.panels);
  assert.deepEqual(plain(G.cells({...grid,panels:moved.panels},size)),plain(G.cells(grid,size)));
});

test('改格数保留已有格，新格 id 不撞',()=>{
  const grown=G.resizeGrid({...draft(2,2),panels:['p1','p3','p4','p5'].map(id=>panel(id))},2,3);
  assert.equal(grown.panels.length,6);assert.equal(new Set(grown.panels.map(item=>item.id)).size,6);assert.equal(grown.panels[1].id,'p3');
  assert.deepEqual(plain(G.resizeGrid(grown,1,3).panels.map(item=>item.id)),['p1','p3','p4']);
});

test('任一格为空时阻止提交，绑定文本算有内容',async()=>{
  const blocked=withGrid({node:{gridDraft:draft(2,2,{panels:[panel('p1'),panel('p2',' '),panel('p3'),panel('p4')]})}});
  await runToEnd(blocked.t);assert.equal(blocked.t.log.submits.length,0);assert.equal(blocked.t.moss.status,'failed');
  const bound=withGrid({text:[textNode('t','来自节点')],node:{gridDraft:draft(2,2,{panels:[{id:'p1',caption:'',captionSource:{kind:'text_node',nodeId:'t'}},panel('p2'),panel('p3'),panel('p4')]})}});
  await runToEnd(bound.t);assert.equal(bound.t.log.submits.length,1);assert.equal(bound.t.log.submits[0].layoutDraft.panels[0].caption,'来自节点');
});

test('一次任务一次提交，整图进图片节点，切图各成普通节点并只归组一次',async()=>{
  const {t}=withGrid();await runToEnd(t);
  assert.equal(t.log.submits.length,1);
  assert.deepEqual(t.log.images.map(([,output])=>output.imagePaths),[['/img/page.png']]);
  assert.deepEqual(t.log.created.map(item=>item.imageUrl),[1,2,3,4].map(index=>`/img/panel${index}.png`));
  assert.deepEqual(t.log.created.map(item=>item.title),['切 1','切 2','切 3','切 4']);
  assert.equal(t.log.groups.length,1);assert.equal(t.log.groups[0].length,4);
  assert.equal(t.moss.panelJobId,TASK);
  assert.equal(t.canvas.edges.filter(edge=>edge.to.startsWith('panel')).length,0);
});

test('描线图不占切图序号；取消切图时只有整图',async()=>{
  const overlay=withGrid({task:finished({overlay:true})});await runToEnd(overlay.t);assert.equal(overlay.t.log.created.length,4);
  const single=withGrid({task:finished({panels:0})});await runToEnd(single.t);
  assert.equal(single.t.log.created.length,0);assert.equal(single.t.log.groups.length,0);assert.equal(single.t.moss.panelJobId,'');assert.equal(single.t.log.images.length,1);
});

test('用户删除切图后重载不复活，显式再展开需确认',async()=>{
  const {t,job}=withGrid();await runToEnd(t);
  const firstY=t.canvas.nodes.panel1.y;
  ['panel1','panel2','panel3','panel4'].forEach(id=>delete t.canvas.nodes[id]);
  t.controller.dispose('m');await mount(t);await t.settle();
  assert.equal(t.log.created.length,4);
  t.setConfirm(false);assert.equal(await t.controller.expandPanels('m',job.task_id),false);assert.equal(t.log.created.length,4);
  t.setConfirm(true);assert.equal(await t.controller.expandPanels('m',job.task_id),true);assert.equal(t.log.created.length,8);assert.equal(t.log.groups.length,2);
  assert.equal(t.log.confirm.length,2);
  assert.equal(t.canvas.nodes.panel5.y,firstY+200);
});

test('编辑器端口：选项持久、警告只取当前回执、切图可展开',async()=>{
  const {t,editors}=withGrid();await mount(t);
  editors.ports.setOption('splitPanels',false);assert.equal(t.moss.splitPanels,false);
  assert.equal(editors.ports.hasPanels(),false);
  t.controller.dispose('m');
});

test('复制节点不带走展开记录',()=>{
  const {t}=withGrid();t.moss.panelJobId=TASK;
  const copy=t.M.remapClone(plain(t.moss),new Map());assert.equal(copy.panelJobId,'');
});

test('桌面页按 model→layout→grid→controller 顺序加载',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../frontend/desktop.html'),'utf8');
  const at=name=>html.indexOf(`scripts/${name}?v=`);
  assert.ok(at('desktop-moss-model.js')>0&&at('desktop-moss-layout.js')<at('desktop-moss-grid.js')&&at('desktop-moss-grid.js')<at('desktop-canvas-moss.js'));
  const source=fs.readFileSync(path.join(__dirname,'../frontend/scripts/desktop-moss-grid.js'),'utf8');
  assert.ok(!/XYWH|desk-moss-grid__list/.test(source));
});

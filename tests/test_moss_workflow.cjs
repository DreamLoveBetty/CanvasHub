const {test}=require('node:test');
const assert=require('node:assert/strict');
const {load,plain,textNode,ports}=require('./moss_frontend_fixture.cjs');
const context=load(['desktop-moss-model.js','desktop-canvas-workflow.js'],{DesktopState:{state:{}}});
const M=context.window.DesktopMossModel;
const ref=nodeId=>({kind:'text_node',nodeId});
const full=()=>M.normalize({id:'m',type:'moss',mode:'layout',prompt:'全局',promptSource:ref('g'),imageWidth:1024,imageHeight:768,seed:'7',jobId:'moss_'+'a'.repeat(32),resultJobId:'r',status:'succeeded',
  freeDraft:{summary:{canvas:'single'},items:[{id:'t',label:'text',text:'内联',textSource:ref('a'),bbox:[0,0,9,9]},{id:'o',label:'object',caption:'猫',captionSource:{kind:'inline'},bbox:[1,1,9,9]}]},
  gridDraft:{rows:1,cols:3,margin:8,gutter:8,panels:[{id:'p1',captionSource:ref('b')},{id:'p2',caption:'二'},{id:'p3',caption:'三'}]}});

test('工作流归一化走 MOSS 定义并保留草稿与来源',()=>{
  const workflow=context.window.DesktopCanvasWorkflow.create({mossDefinition:M,jsonClone:(value,fallback)=>value===undefined?fallback:JSON.parse(JSON.stringify(value)),normalizeNodeMenuType:type=>type,normalizeNodeGroupId:()=>''});
  const restored=workflow.normalizeWorkflowNode(plain(full()),'m');
  assert.deepEqual(plain(restored.freeDraft.items[0].textSource),ref('a'));
  assert.equal(restored.gridDraft.panels[1].caption,'二');assert.equal(restored.width,720);
  assert.equal(M.normalize(plain(restored)).mode,'layout');
});

test('自有草稿包 snake 往返保留来源与内联值',()=>{
  const pack=M.exportDraft(full());
  assert.equal(pack.schema,'canvashub.moss.layout');assert.equal(pack.schema_version,1);
  assert.deepEqual(plain(pack.prompt_source),{kind:'text_node',node_id:'g'});
  assert.deepEqual(plain(pack.free_draft.items[0].text_source),{kind:'text_node',node_id:'a'});
  assert.deepEqual(plain(pack.grid_draft.panels[2]),{id:'p3',caption:'三',caption_source:{kind:'inline'}});
  assert.doesNotMatch(JSON.stringify(pack),/nodeId|jobId|textSource|captionSource|settingsExpanded|status/);
  const node=M.normalize({type:'moss'}),revision=node.draftRevision;
  M.applyImport(node,plain(pack));
  assert.equal(node.mode,'layout');assert.equal(node.imageHeight,768);assert.deepEqual(plain(node.promptSource),ref('g'));
  assert.deepEqual(plain(node.freeDraft.items[0].textSource),ref('a'));assert.equal(node.freeDraft.items[1].caption,'猫');
  assert.deepEqual(plain(node.gridDraft.panels[0].captionSource),ref('b'));assert.equal(node.draftRevision,revision+1);
  assert.equal(node.jobId,'');
});

test('官方导出解析引用并剥离全部自有字段',()=>{
  const node=full(),input=M.resolveTextSources(node,ports(textNode('g','风格'),textNode('a','文案')));
  const official=M.exportOfficial(node,input);
  assert.deepEqual(plain(official.items[0]),{label:'text',text:'文案',bbox:[0,0,9,9]});
  assert.equal(official.summary.caption,'风格');assert.equal(official.summary.canvas,'single');
  assert.equal(official.bbox_coord_space,'abs');assert.equal(official.bbox_format,'xyxy');
  assert.doesNotMatch(JSON.stringify(official),/[Ss]ource|"id"/);
  assert.throws(()=>M.exportOfficial(node,M.resolveTextSources(node,ports())),/失效/);
  node.mode='storyboard';assert.throws(()=>M.exportOfficial(node,M.resolveTextSources(node,ports(textNode('b','一'),textNode('g','风格')))),/官方/);
  node.mode='text';assert.deepEqual(plain(M.exportOfficial(node,M.resolveTextSources(node,ports(textNode('g','风格'))))),{caption:'风格'});
});

test('整组克隆映射来源，单节点克隆保留共享源，都清运行关联',()=>{
  const group=M.remapClone(full(),{a:'a2',g:'g2'});
  assert.equal(group.promptSource.nodeId,'g2');assert.equal(group.freeDraft.items[0].textSource.nodeId,'a2');
  assert.equal(group.gridDraft.panels[0].captionSource.nodeId,'b');
  assert.deepEqual([group.jobId,group.resultJobId,group.status],['','','idle']);
  const single=M.remapClone(full());
  assert.equal(single.promptSource.nodeId,'g');assert.equal(single.jobId,'');
  const source=full();M.remapClone(source,{a:'a2'});assert.equal(source.freeDraft.items[0].textSource.nodeId,'a');
});

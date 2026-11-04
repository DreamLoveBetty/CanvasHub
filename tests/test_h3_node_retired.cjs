const {test}=require('node:test');
const assert=require('node:assert/strict');
const {load,plain}=require('./moss_frontend_fixture.cjs');

// The canvas normalizer reaches many host helpers; none of them matter to the type check here.
const withPassthrough=target=>new Proxy(target,{get:(own,key)=>key in own?own[key]:(/Definition$/.test(String(key))?undefined:value=>value)});
function fixture(outputs={}){
  const DesktopState=withPassthrough({state:{outputs},isInFlight:status=>status==='processing'});
  const context=load(['desktop-canvas-workflow.js'],{DesktopState});
  const workflow=context.window.DesktopCanvasWorkflow.create(withPassthrough({
    jsonClone:(value,fallback)=>value===undefined?fallback:JSON.parse(JSON.stringify(value)),
    normalizeNodeGroups(){}
  }));
  return {workflow,state:DesktopState.state};
}
const legacyCanvas=()=>({
  nodes:{
    input:{id:'input',type:'input'},
    prompt:{id:'prompt',type:'text',text:'保留'},
    h3:{id:'h3',type:'video_inference',provider:'minimax_h3'},
    result:{id:'result',type:'video',status:'processing',progress:40,progressText:'H3',mediaUrl:'/video/old.mp4'}
  },
  edges:[{id:'in',from:'prompt',to:'h3'},{id:'out',from:'h3',to:'result'},{id:'keep',from:'prompt',to:'input'}],
  selectedNodeId:'h3',selectedNodeIds:['h3','prompt']
});

test('saved H3 nodes are purged while their video results stay and stop waiting',()=>{
  const h=fixture({h3:{taskId:'t'},prompt:{taskId:'p'}}),canvas=legacyCanvas();
  assert.equal(h.workflow.purgeRetiredVideoNodes(canvas),1);
  assert.deepEqual(Object.keys(canvas.nodes).sort(),['input','prompt','result']);
  assert.deepEqual(plain(canvas.edges.map(edge=>edge.id)),['keep']);
  assert.deepEqual(plain(canvas.selectedNodeIds),['prompt']);assert.equal(canvas.selectedNodeId,'');
  assert.deepEqual(Object.keys(h.state.outputs),['prompt']);
  const result=canvas.nodes.result;
  assert.deepEqual([result.status,result.progress,result.progressText],['idle',0,'']);
  assert.equal(result.mediaUrl,'/video/old.mp4');
});

test('a canvas without H3 nodes is left alone',()=>{
  const h=fixture(),canvas={nodes:{result:{id:'result',type:'video',status:'processing'}},edges:[{id:'x',from:'a',to:'result'}]};
  const before=JSON.stringify(canvas);
  assert.equal(h.workflow.purgeRetiredVideoNodes(canvas),0);assert.equal(JSON.stringify(canvas),before);
});

test('imported workflows drop the H3 node and its edges instead of turning it into an image node',()=>{
  const h=fixture();
  assert.equal(h.workflow.normalizeWorkflowNode({id:'h3',type:'video_inference'},'h3'),null);
  const canvas=h.workflow.normalizeWorkflowCanvas(legacyCanvas());
  assert.equal(canvas.nodes.h3,undefined);assert.equal(canvas.nodes.result.type,'video');assert.equal(canvas.nodes.result.status,'idle');
  assert.deepEqual(plain(canvas.edges.map(edge=>edge.id)),['keep']);
  assert.ok(!canvas.selectedNodeIds.includes('h3'));
});

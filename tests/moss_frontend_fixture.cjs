const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const scripts=path.join(__dirname,'../frontend/scripts');
// Load a browser script in a fresh context; `globals` stands in for what the page provides.
function load(names,globals={}){
  const context={window:{},TextEncoder,Uint8Array,Uint32Array,DataView,...globals};
  for(const name of names)vm.runInNewContext(fs.readFileSync(path.join(scripts,name),'utf8'),context);
  return context;
}
const plain=value=>JSON.parse(JSON.stringify(value));
const textNode=(id,text,extra={})=>({id,type:'text',alias:id,text,...extra});
function ports(...nodes){
  const byId=Object.fromEntries(nodes.map(node=>[node.id,node]));
  return{getNodeState:id=>byId[id],materializeText:node=>node.text,byId};
}
const frontend=path.join(__dirname,'../frontend');
function fakeElement(){
  const parts=new Map(),listeners={};
  const el={style:{setProperty(){}},dataset:{},classList:{toggle(){}},hidden:false,value:'',innerHTML:'',textContent:'',offsetHeight:50,scrollHeight:400,listeners,
    addEventListener:(type,fn)=>{listeners[type]=fn;},querySelectorAll:()=>[],matches:()=>false,
    querySelector:selector=>{if(!parts.has(selector))parts.set(selector,fakeElement());return parts.get(selector);}};
  return el;
}
const receipt=(fingerprint,model='fp',budget={})=>({kind:'compiled',compiled:{},tokenBudget:{checked:true,valid:true,promptTokens:3,maxTokens:4096,...budget},inputFingerprint:fingerprint,modelFingerprint:model});
function setup({ready=true,node={},text=[],api={},layoutFactory=null,gridFactory=null,layoutModes=[]}={}){
  const timers=[];
  const context=load(['desktop-moss-model.js'],{});
  const vmGlobals={window:context.window,setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout(){},AbortController};
  context.window.addEventListener=()=>{};
  require('node:vm').runInNewContext(fs.readFileSync(path.join(frontend,'scripts/desktop-canvas-moss.js'),'utf8'),vmGlobals);
  const M=context.window.DesktopMossModel;
  const moss=M.normalize({id:'m',type:'moss',x:0,y:0,prompt:'猫',...node});
  const canvas={nodes:{m:moss,...Object.fromEntries(text.map(item=>[item.id,item]))},edges:[]};
  const elements={m:fakeElement()},log={connect:[],remove:[],confirm:[],notify:[],applied:0,saved:0,submits:[],compiles:0,images:[],created:[],groups:[]};
  let edgeId=0,failConnect=false,confirmReply=true;
  const stub={status:async()=>({ready,reasons:ready?[]:['未准备'],model:{ready,fingerprint:'fp'},preparation:{status:'idle'}}),listLoras:async()=>({loras:[]}),
    compile:async(_node,input)=>{log.compiles++;return receipt(input.inputFingerprint);},submit:async(_node,input)=>{log.submits.push(input);return{task_id:'moss_'+'a'.repeat(32),status:'queued'};},
    job:async()=>({status:'running'}),cancel:async()=>({}),...api};
  let controller;
  const connectNodes=(from,to,options)=>{log.connect.push([from,to]);if(failConnect)return;canvas.edges.push({id:'e'+(++edgeId),from,to,...options});controller.connections.changed(from,to);};
  const removeEdges=(ids,options)=>{log.remove.push(ids);const gone=canvas.edges.filter(edge=>ids.includes(edge.id));canvas.edges=canvas.edges.filter(edge=>!ids.includes(edge.id));controller.connections.removed(gone);};
  controller=context.window.DesktopCanvasMoss.create({model:M,api:stub,getCanvas:()=>canvas,getNodeState:id=>canvas.nodes[id],getNodeElement:id=>elements[id],materializeText:item=>item.text,
    addNode:type=>{const id='i'+Object.keys(canvas.nodes).length;canvas.nodes[id]={id,type,height:100};elements[id]=fakeElement();return id;},connectNodes,removeEdges,
    setImageFromResult:async(id,from,output)=>{log.images.push([id,plain(output)]);},applyNodeLayout:()=>{log.applied++;},updateLinkPath(){},saveState:()=>{log.saved++;},
    confirmAction:message=>{log.confirm.push(message);return confirmReply;},
    getNegativeTextNodes:id=>canvas.edges.filter(edge=>edge.to===id&&canvas.nodes[edge.from]?.promptRole==='negative').map(edge=>canvas.nodes[edge.from]),notify:message=>log.notify.push(message),openModelTools:()=>{log.tools=true;},layoutFactory,gridFactory,layoutModes,
    createImage:async item=>{const id='panel'+(log.created.length+1);log.created.push(plain(item));canvas.nodes[id]={id,type:'image',x:0,y:0,height:100};return id;},groupImages:ids=>{log.groups.push(plain(ids));return'g';}});
  return{controller,M,moss,canvas,log,timers,elements,connectNodes,removeEdges,setFail:value=>{failConnect=value;},setConfirm:value=>{confirmReply=value;},
    settle:async()=>{for(let i=0;i<8;i++)await Promise.resolve();await new Promise(resolve=>setImmediate(resolve));}};
}
const mount=async t=>{t.controller.reconcile();await t.settle();return t;};

module.exports={load,plain,textNode,ports,setup,mount,receipt,fakeElement};


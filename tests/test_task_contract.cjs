const {test}=require('node:test'); const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.join(__dirname,'../frontend/scripts');
function load(ctx,files){for(const file of files)vm.runInNewContext(fs.readFileSync(path.join(root,file+'.js'),'utf8'),ctx);return ctx;}
function base(extra={}){return load({window:{},...extra},['desktop-tasks','desktop-task-output-adapter']);}
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
test('canonical receipt preserves raw contracts, partial, cancellation and unknown progress',async()=>{
 const ctx=base(),raw={id:'j',status:'processing',progress_message:'working',artifacts:[{url:'/local'}]};
 const client=ctx.window.DesktopTasks.createClient({domain:'sample',submit:async()=>raw,progress:async()=>raw,cancel:async()=>({...raw,status:'canceled'})});
 const receipt=await client.submit({});assert.equal(receipt.status,'running');assert.equal(receipt.progress,null);
 assert.equal(receipt.raw,raw);assert.equal((await client.cancel('j')).status,'cancelled');
 assert.equal((await client.result({...raw,status:'partial'})).status,'partial');
 assert.equal(client.inspect({status:'alien'}).status,'unknown');assert.equal(client.inspect({progress:120}).progress,100);
 receipt.artifacts[0].url='changed';assert.equal(raw.artifacts[0].url,'/local');
});
test('result reuses receipt without network and ID queries exactly once',async()=>{
 const ctx=base();let calls=0;const raw={id:'j',status:'succeeded'};
 const c=ctx.window.DesktopTasks.createClient({domain:'d',submit:async()=>raw,progress:async()=>{calls++;return raw;},cancel:async()=>raw});
 await c.result(await c.submit());assert.equal(calls,0);await c.result('j');assert.equal(calls,1);
});
test('new domain supports all commands/status/selection/stop without UI branches',async()=>{
 const ctx=base(),reports=[],calls=[];const hub=ctx.window.DesktopTasks.createRegistry({reportStatus:x=>reports.push(x)});
 const client=Object.fromEntries(['submit','progress','cancel','result'].map(k=>[k,async value=>{calls.push(k);return value;}]));
 hub.register('future-model',{client:()=>client,showStatus:id=>calls.push(id),listCancelable:()=>[{key:'1',cancel:async()=>calls.push('stop')}]});
 for(const k of ['submit','progress','cancel','result'])assert.equal(await hub[k]('future-model','value'),'value');
 hub.report('future-model',{task:{status:'failed',stage:'failure'},message:'failure'});
 assert.equal(reports[0].task.task_domain,'future-model');assert.equal(reports[0].task.progress_text,'failure');
 hub.showStatus('node');assert.equal((await hub.cancelAll()).total,1);assert.ok(calls.includes('stop'));assert.ok(calls.includes('node'));
 assert.throws(()=>hub.register('future-model',{client:()=>client}),/重复/);
});
test('cancel namespace, deduplication, concurrent calls and retry after rejection',async()=>{
 const ctx=base(),hub=ctx.window.DesktopTasks.createRegistry({reportStatus(){}});let calls=0,fail=true;const gate=deferred();
 const entry={key:'same',cancel:async()=>{calls++;await gate.promise;if(fail)throw Error('network');}};
 hub.register('a',{client:()=>({}),listCancelable:()=>[entry,entry]});
 hub.register('b',{client:()=>({}),listCancelable:()=>[{key:'same',cancel:async()=>{}}]});
 const one=hub.cancelAll(),two=hub.cancelAll();gate.resolve();assert.equal((await one).failed,1);assert.equal((await two).total,2);assert.equal(calls,1);
 fail=false;assert.equal((await hub.cancelAll()).failed,0);assert.equal(calls,2);
});
function outputFixture(){
 const ctx=base(),gate=deferred(),applied=[],stopped=[];let calls=0;
 let state={canvas:{nodes:{a:{type:'input'},b:{type:'input'}}},outputs:{a:{taskId:'same',status:'processing'},b:{taskId:'same',status:'processing'}}};
 const adapter=ctx.window.DesktopTaskOutputAdapter.create({getState:()=>state,isInFlight:s=>s==='processing',
 api:()=>({cancelTask:async()=>{calls++;return gate.promise;},controlBatch:async()=>gate.promise}),
 applyTask:(...args)=>applied.push(args),applyBatch:(...args)=>applied.push(args),stopTaskPolling:id=>stopped.push(id),stopBatchPolling:id=>stopped.push(id),cancelVideo:async()=>applied.push('video')});
 return {adapter,gate,applied,stopped,get calls(){return calls;},get state(){return state;},replace(){state={canvas:{nodes:{}},outputs:{}};}};
}
test('shared legacy task cancels once and applies receipt to each live result',async()=>{
 const h=outputFixture(),entries=h.adapter.listCancelable();assert.equal(entries.length,1);
 const p=entries[0].cancel();h.gate.resolve({status:'canceled'});await p;assert.equal(h.calls,1);assert.equal(h.applied.length,2);assert.equal(h.stopped.length,2);
});
test('workflow replacement or new task during cancellation cannot receive old receipt',async()=>{
 for(const replace of [h=>h.replace(),h=>{h.state.outputs.a.taskId='new';h.state.outputs.b.taskId='new';}]){
 const h=outputFixture(),p=h.adapter.listCancelable()[0].cancel();replace(h);h.gate.resolve({status:'canceled'});await p;assert.equal(h.applied.length,0);assert.equal(h.stopped.length,0);
 }
});
test('failed cancellation leaves pollers intact and task retryable',async()=>{
 const h=outputFixture(),p=h.adapter.listCancelable()[0].cancel();h.gate.reject(Error('network'));await assert.rejects(p,/network/);
 assert.equal(h.stopped.length,0);assert.equal(h.adapter.listCancelable().length,1);
});
test('H3 cancellation dispatches to owning controller; completed jobs excluded',async()=>{
 const h=outputFixture();h.state.canvas.nodes.a.type='video_inference';h.state.outputs.b.status='succeeded';
 await h.adapter.listCancelable()[0].cancel();assert.deepEqual(h.applied,['video']);assert.equal(h.calls,0);
});
test('legacy selected output uses the input result alias and ignores a replaced selection',async()=>{
 for(const replace of [false,true]){
  const h=outputFixture();delete h.state.outputs.a;delete h.state.outputs.b;
  h.state.selectedTaskId='legacy';h.state.output={status:'processing'};
  const entries=h.adapter.listCancelable();assert.equal(entries.length,1);
  const pending=entries[0].cancel();if(replace)h.state.selectedTaskId='new';
  h.gate.resolve({status:'canceled'});await pending;
  assert.equal(h.applied.length,replace?0:1);
  if(!replace){assert.equal(h.applied[0][1],'input');assert.deepEqual(h.stopped,['input']);}
 }
});
test('batch cancellation uses batch receipts and ignores completed batches',async()=>{
 const h=outputFixture();h.state.outputs.a={batchId:'batch',batchStatus:'running'};
 h.state.outputs.b={batchId:'done',batchStatus:'completed'};
 const entries=h.adapter.listCancelable();assert.equal(entries.length,1);assert.equal(entries[0].key,'batch:batch');
 const pending=entries[0].cancel();const receipt={batch_id:'batch',status:'completed'};
 h.gate.resolve(receipt);await pending;
 assert.equal(h.calls,0);assert.equal(h.applied[0][0],receipt);assert.deepEqual(h.stopped,['a']);
});
test('music and ReShot old methods are compatibility forwards to common transport',async()=>{
 for(const [file,namespace,domain] of [['desktop-music-api','DesktopMusicAPI','music'],['desktop-video-control-api','DesktopVideoControlAPI','video_control']]){
 const raw={id:'fixture',status:'running',artifacts:[{name:'result',url:'/local'}]},calls=[];
 const ctx=base({api:{json:async(...args)=>{calls.push(args);return raw;}}});load(ctx,[file]);const api=ctx.window[namespace];
 assert.equal(await api.submit({style:'test'}),raw);assert.equal(await api.job('fixture'),raw);assert.equal(await api.cancel('fixture'),raw);
 const receipt=await api.tasks.progress('fixture');assert.equal(receipt.domain,domain);assert.equal(receipt.raw,raw);
 assert.equal((await api.tasks.result(receipt)).artifacts.length,1);assert.equal(calls.length,4);
 }
});
test('legacy generation adapters preserve endpoints and original receipts',async()=>{
 const raw={task_id:'fixture',status:'succeeded_no_telegram',video_paths:['/video/fixture.mp4']},calls=[];
 const ctx=base({api:{json:async(...args)=>{calls.push(args);return raw;}}});load(ctx,['desktop-api']);const api=ctx.window.DesktopApi;
 assert.equal(await api.getStatus('fixture'),raw);assert.equal(calls.at(-1)[0],'/api/status/fixture');
 assert.equal(await api.cancelTask('fixture'),raw);assert.equal(calls.at(-1)[0],'/api/tasks/fixture/cancel');
 const receipt=await api.tasks.video.result(raw);assert.equal(receipt.status,'succeeded');assert.equal(receipt.artifacts[0].kind,'video');assert.equal(calls.length,2);
});
test('status UI is domain-agnostic and task scripts load before consumers',()=>{
 const source=fs.readFileSync(path.join(root,'desktop-results.js'),'utf8');
 assert.doesNotMatch(source,/getCancelableMusicTasks|getCancelableVideoControlTasks|entry\.kind/);
 assert.match(source,/getTaskRegistry\(\)\.cancelAll\(\)/);
 const html=fs.readFileSync(path.join(root,'../desktop.html'),'utf8');
 assert.ok(html.indexOf('scripts/desktop-tasks.js')<html.indexOf('scripts/desktop-api.js'));
});

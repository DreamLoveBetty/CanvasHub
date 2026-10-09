const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.join(__dirname,'..'),read=name=>fs.readFileSync(path.join(root,name),'utf8');
const ctx=vm.createContext({window:{}});
for(const name of ['desktop-state-icon', 'desktop-music-model','desktop-music-view'])vm.runInContext(read(`frontend/scripts/${name}.js`),ctx);
const model=ctx.window.DesktopMusicModel,view=ctx.window.DesktopMusicView.create({model,stateIcon:ctx.window.DesktopStateIcon,escapeHtml:s=>String(s??'')});
const node={jobId:'job',status:'running'};
const snapshot=(job,options={})=>model.generationProgress(node,{id:'job',stage:'Generating song',started_at:10,...job},model.generationButtonState(node),{now:30000,...options});
test('unknown token total animates without inventing percent or ETA',()=>{
 const p=snapshot({progress:{tokens:712}});
 assert.equal(p.percent,null);assert.equal(p.visible,true);assert.equal(p.elapsed,'00:20');assert.match(p.stage,/712 tokens/);
 assert.equal(snapshot({progress:{tokens:712}},{now:60000}).percent,null);
});
test('real counts are explicitly current-stage progress, not global progress',()=>{
 const p=snapshot({stage:'Synthesizing audio',progress:{completed:4,total:8,unit:'steps'}});
 assert.equal(p.percent,50);assert.equal(p.value,'阶段 50%');assert.match(p.stage,/声学合成 · 4\/8 步（当前阶段）/);
 for(const progress of [{completed:5,total:0},{completed:-1,total:8},{completed:9,total:8},{completed:1,total:Infinity},{completed:'4',total:8}])assert.equal(snapshot({progress}).percent,null);
});
test('phase and job replacement clear the previous stage percentage',()=>{
 assert.equal(snapshot({stage:'Loading MLX audio decoder',progress:{}}).percent,null);
 assert.equal(snapshot({id:'previous-job',progress:{completed:8,total:8}}).percent,null);
});
test('pending and cancelled states override previous completed-stage observations',()=>{
 const job={id:'job',started_at:10,progress:{completed:8,total:8}};
 for(const opts of [{submitting:true},{submitting:true,phase:'等待上游转谱'},{cancelRequested:true}]){
  const p=model.generationProgress(node,job,model.generationButtonState(node,opts),{now:30000,submittedAt:25000});
  assert.equal(p.percent,null);assert.equal(p.visible,true);
 }
 for(const status of ['idle','succeeded','failed','cancelled','partial','interrupted']){
  const n={...node,status};assert.equal(model.generationProgress(n,job,model.generationButtonState(n)).visible,false);
 }
});
test('only music inference gets a node-relative overlay, outside the body',()=>{
 const html=view.nodeHtml(model.createState('g','music_generate',{}));
 assert.equal(html.split('data-music-progress').length-1,1);assert.match(html,/<\/div><div class="desk-progress-float desk-music__progress"/);
 assert.match(html,/role="progressbar"/);assert.doesNotMatch(html,/deskProgressFloat|deskInputProgressBar/);
 for(const type of ['music_transcribe','music_abc','music_score','music_compare'])assert.doesNotMatch(view.nodeHtml(model.createState('n',type,{})),/data-music-progress/);
 const css=read('frontend/styles/desktop-music.css');assert.match(css,/desk-music__progress \{ position:absolute; top:calc\(100% \+ 2px\)/);assert.match(css,/is-visible\.is-indeterminate \[data-progress-bar\] \{ animation:none/);
});
test('view removes numeric ARIA value when total becomes unknown and stops at terminal state',()=>{
 const elements=new Map();const element=()=>({textContent:'',style:{setProperty(){}},attrs:{},classes:{},setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];},classList:{toggle(k,v){overlay.classes[k]=v;}}});
 const overlay=element();overlay.querySelector=k=>{if(!elements.has(k))elements.set(k,element());return elements.get(k);};
 const root={querySelector:k=>k==='[data-music-progress]'?overlay:element()};
 view.paintProgress(root,{visible:true,percent:50,value:'阶段 50%',stage:'声学合成',elapsed:'00:20'});assert.equal(overlay.attrs['aria-valuenow'],'50');
 view.paintProgress(root,{visible:true,percent:null,value:'生成中',stage:'解码音频',elapsed:'00:21'});assert.equal(overlay.attrs['aria-valuenow'],undefined);assert.equal(overlay.classes['is-indeterminate'],true);
 view.paintProgress(root,{visible:false,percent:null,value:'已完成',stage:'已完成',elapsed:'00:22'});assert.equal(overlay.classes['is-visible'],false);assert.equal(overlay.attrs['aria-hidden'],'true');
});

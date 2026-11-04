// MOSS canvas state, text-source references and workflow contract; no DOM or transport.
(function () {
  const TYPE='moss',WIDTH=720,HEIGHT=500,SCHEMA='canvashub.moss.layout',SCHEMA_VERSION=1;
  const DEFAULT_MODEL_ID='moss-image-sft-mflux-bf16',DEFAULT_PRESET='turbo';
  const MODES=Object.freeze(['text','layout','storyboard']);
  const PRESETS=Object.freeze({turbo:{label:'Turbo · 10 步'},standard:{label:'标准 · 50 步'}});
  const ASPECT_RATIOS=Object.freeze(['1:1','2:3','3:2','3:4','4:3','4:5','5:4','9:16','16:9']);
  const LORA_SCALE_MIN=-20,LORA_SCALE_MAX=20,MAX_LORAS=4,MAX_PIXELS=2097152,SEED_MAX=4294967295,GLOBAL='global';
  const ICON='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"/></svg>';
  const MENU_ITEM=Object.freeze({type:TYPE,title:'MOSS · 本地生成 / Layout',subtitle:'文生图 / 自由布局 / 分镜网格',icon:ICON});
  const K=Uint32Array.from('428a2f98 71374491 b5c0fbcf e9b5dba5 3956c25b 59f111f1 923f82a4 ab1c5ed5 d807aa98 12835b01 243185be 550c7dc3 72be5d74 80deb1fe 9bdc06a7 c19bf174 e49b69c1 efbe4786 0fc19dc6 240ca1cc 2de92c6f 4a7484aa 5cb0a9dc 76f988da 983e5152 a831c66d b00327c8 bf597fc7 c6e00bf3 d5a79147 06ca6351 14292967 27b70a85 2e1b2138 4d2c6dfc 53380d13 650a7354 766a0abb 81c2c92e 92722c85 a2bfe8a1 a81a664b c24b8b70 c76c51a3 d192e819 d6990624 f40e3585 106aa070 19a4c116 1e376c08 2748774c 34b0bcb5 391c0cb3 4ed8aa4a 5b9cca4f 682e6ff3 748f82ee 78a5636f 84c87814 8cc70208 90befffa a4506ceb bef9a3f7 c67178f2'.split(' '),hex=>parseInt(hex,16));
  // crypto.subtle is async and missing on plain-http LAN origins; source hashes are checked by the server byte for byte.
  function sha256(value){
    const bytes=new TextEncoder().encode(String(value)),padded=new Uint8Array(((bytes.length+9+63)>>>6)<<6);
    padded.set(bytes);padded[bytes.length]=128;
    const view=new DataView(padded.buffer);view.setUint32(padded.length-8,Math.floor(bytes.length/536870912));view.setUint32(padded.length-4,bytes.length<<3>>>0);
    const hash=Uint32Array.from([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]),w=new Uint32Array(64);
    const rotr=(x,n)=>(x>>>n)|(x<<(32-n));
    for(let offset=0;offset<padded.length;offset+=64){
      for(let i=0;i<16;i++)w[i]=view.getUint32(offset+i*4);
      for(let i=16;i<64;i++){const a=w[i-15],b=w[i-2];w[i]=w[i-16]+(rotr(a,7)^rotr(a,18)^(a>>>3))+w[i-7]+(rotr(b,17)^rotr(b,19)^(b>>>10));}
      let [a,b,c,d,e,f,g,h]=hash;
      for(let i=0;i<64;i++){
        const t1=(h+(rotr(e,6)^rotr(e,11)^rotr(e,25))+((e&f)^(~e&g))+K[i]+w[i])|0,t2=((rotr(a,2)^rotr(a,13)^rotr(a,22))+((a&b)^(a&c)^(b&c)))|0;
        h=g;g=f;f=e;e=(d+t1)|0;d=c;c=b;b=a;a=(t1+t2)|0;
      }
      [a,b,c,d,e,f,g,h].forEach((value,i)=>{hash[i]=hash[i]+value;});
    }
    return Array.from(hash,value=>value.toString(16).padStart(8,'0')).join('');
  }
  const isObject=value=>Boolean(value)&&typeof value==='object'&&!Array.isArray(value);
  const clone=value=>value===undefined?undefined:JSON.parse(JSON.stringify(value));
  const text=value=>typeof value==='string'?value:'';
  const clamp=(value,lo,hi,fallback)=>Number.isFinite(Number(value))?Math.max(lo,Math.min(hi,Number(value))):fallback;
  const active=status=>['submitting','queued','processing','running'].includes(String(status||''));
  const normalizeLoraScale=value=>clamp(value,LORA_SCALE_MIN,LORA_SCALE_MAX,1);
  const inline=()=>({kind:'inline'});
  // A field binding is a reference only: no live copy of the source text is ever stored.
  function normalizeSource(value){
    const nodeId=value?.kind==='text_node'?text(value.nodeId??value.node_id).trim():'';
    return nodeId?{kind:'text_node',nodeId}:inline();
  }
  const bound=source=>source?.kind==='text_node';
  function normalizeSize(node){
    const dimension=value=>Math.round(clamp(value,256,2048,1024)/16)*16;
    const width=dimension(node.imageWidth),height=dimension(node.imageHeight);
    [node.imageWidth,node.imageHeight]=width*height<=MAX_PIXELS?[width,height]:[1024,1024];
  }
  const normalizeSeed=value=>{const digits=value===null||value===undefined?'':String(value).replace(/[^0-9]/g,'');return digits&&Number(digits)<=SEED_MAX?digits:'';};
  const defaultGridDraft=()=>({summary:{},rows:2,cols:2,margin:8,gutter:8,panels:['p1','p2','p3','p4'].map(id=>({id,caption:'',captionSource:inline()}))});
  function normalizeFreeDraft(value){
    const source=isObject(value)?value:{};
    const items=(Array.isArray(source.items)?source.items:[]).filter(isObject).map(item=>{
      const next={...item,caption:text(item.caption)};
      if(next.label==='text'){next.text=text(item.text);next.textSource=normalizeSource(item.textSource);delete next.captionSource;}
      else{next.captionSource=normalizeSource(item.captionSource);delete next.text;delete next.textSource;}
      return next;
    });
    return{summary:isObject(source.summary)?source.summary:{},items};
  }
  function normalizeGridDraft(value){
    if(!isObject(value))return defaultGridDraft();
    const fallback=defaultGridDraft(),number=(key,lo,hi)=>Math.round(clamp(value[key],lo,hi,fallback[key]));
    const panels=(Array.isArray(value.panels)?value.panels:[]).filter(isObject).map(panel=>({id:text(panel.id),caption:text(panel.caption),captionSource:normalizeSource(panel.captionSource)}));
    return{summary:isObject(value.summary)?value.summary:{},rows:number('rows',1,4),cols:number('cols',1,4),margin:number('margin',0,256),gutter:number('gutter',0,256),panels:panels.length?panels:fallback.panels};
  }
  // Ratios land near 1MP; total pixels stay under MAX_PIXELS for every listed ratio.
  function dimensionsForRatio(ratio){
    if(!ASPECT_RATIOS.includes(ratio))return null;
    const [a,b]=ratio.split(':').map(Number),width=Math.sqrt(1024**2*a/b);
    return{width:Math.round(width/16)*16,height:Math.round(width*b/a/16)*16};
  }
  const ratioFromDimensions=(width,height)=>ASPECT_RATIOS.find(ratio=>{const size=dimensionsForRatio(ratio);return size.width===width&&size.height===height;})||ASPECT_RATIOS.find(ratio=>{const [a,b]=ratio.split(':').map(Number);return Math.abs(width/height-a/b)<.002;})||'custom';
  const withinPixels=(width,height)=>width*height<=MAX_PIXELS;
  const unsupported=node=>node.schemaVersion!==SCHEMA_VERSION;
  function normalize(node){
    if(node.type!==TYPE)return node;
    node.width=WIDTH;
    if(node.schemaVersion===undefined)node.schemaVersion=SCHEMA_VERSION;
    if(unsupported(node)){node.height=clamp(node.height,HEIGHT,4096,HEIGHT);return node;} // A newer draft stays intact and blocks execution.
    node.mode=MODES.includes(node.mode)?node.mode:'text';
    node.height=clamp(node.height,HEIGHT,4096,HEIGHT);
    node.prompt=text(node.prompt);node.promptSource=normalizeSource(node.promptSource);
    normalizeSize(node);
    node.preset=PRESETS[node.preset]?node.preset:DEFAULT_PRESET;
    const requested=String(node.baseModelId||'').toLowerCase();node.baseModelId=/^[a-z0-9][a-z0-9._-]{0,119}$/.test(requested)?requested:DEFAULT_MODEL_ID;
    node.seed=normalizeSeed(node.seed);
    node.telegramEnabled=node.telegramEnabled===true;node.drawGrid=node.drawGrid===true;node.splitPanels=node.splitPanels!==false;
    node.settingsExpanded=node.settingsExpanded!==false;
    const seen=new Set();node.loras=(Array.isArray(node.loras)?node.loras:[]).filter(item=>/^[a-f0-9]{64}$/.test(String(item?.assetId||''))&&!seen.has(item.assetId)&&seen.add(item.assetId)).slice(0,MAX_LORAS).map(item=>({assetId:item.assetId,scale:normalizeLoraScale(item.scale)}));
    node.freeDraft=normalizeFreeDraft(node.freeDraft);node.gridDraft=normalizeGridDraft(node.gridDraft);
    node.draftRevision=Math.max(0,Math.floor(clamp(node.draftRevision,0,Number.MAX_SAFE_INTEGER,0)));
    node.jobId=/^moss_[a-f0-9]{32}$/.test(String(node.jobId||''))?node.jobId:'';
    node.resultJobId=String(node.resultJobId||'');node.panelJobId=String(node.panelJobId||'');node.status=String(node.status||'idle');return node;
  }
  // Only text nodes feed MOSS, and only by explicit field reference; images and old Layout nodes are refused.
  const targets=Object.freeze({text:[TYPE],moss:['image']});
  function policy(from,to){
    if(!targets[from?.type]?.includes(to?.type))return null;
    if(from.type===TYPE)return{inputRole:'image',outputRole:'image',single:false};
    return{inputRole:'prompt',outputRole:'prompt',single:false};
  }
  const freeBindings=node=>(node.freeDraft?.items||[]).map(item=>item.label==='text'?{targetId:item.id,field:'text',source:item.textSource}:{targetId:item.id,field:'caption',source:item.captionSource});
  const gridBindings=node=>(node.gridDraft?.panels||[]).map(panel=>({targetId:panel.id,field:'caption',source:panel.captionSource}));
  const globalBinding=node=>({targetId:GLOBAL,field:'prompt',source:node.promptSource});
  const modeBindings=node=>[globalBinding(node),...(node.mode==='layout'?freeBindings(node):node.mode==='storyboard'?gridBindings(node):[])];
  const allBindings=node=>[globalBinding(node),...freeBindings(node),...gridBindings(node)];
  // The one place that knows where a field keeps its value and its source.
  function bindingSlot(node,targetId,field){
    if(targetId===GLOBAL)return field==='prompt'?{holder:node,valueKey:'prompt',sourceKey:'promptSource'}:null;
    const item=(node.freeDraft?.items||[]).find(entry=>entry.id===targetId)||(node.gridDraft?.panels||[]).find(entry=>entry.id===targetId);
    if(!item)return null;
    if(field==='text')return item.label==='text'?{holder:item,valueKey:'text',sourceKey:'textSource'}:null;
    return field==='caption'&&item.label!=='text'?{holder:item,valueKey:'caption',sourceKey:'captionSource'}:null;
  }
  const ids=bindings=>[...new Set(bindings.filter(item=>bound(item.source)).map(item=>item.source.nodeId))];
  // Every draft counts: the dependency edge is the projection of all field references, active or not.
  const textDependencies=node=>ids(allBindings(node));
  const missingDependencies=(node,exportedIds)=>{const kept=new Set(exportedIds);return textDependencies(node).filter(id=>!kept.has(id));};
  function readSource(binding,{getNodeState,materializeText}){
    const nodeId=binding.source.nodeId,state=getNodeState(nodeId),issue=reason=>({issue:{targetId:binding.targetId,field:binding.field,nodeId,reason}});
    if(!state)return issue('missing');
    if(state.type!=='text')return issue('incompatible');
    if((state.promptDocument?.segments||[]).some(segment=>segment?.type==='image_reference'))return issue('image_reference');
    const value=materializeText(state);
    if(typeof value!=='string'||!value.trim())return issue('empty');
    return{value,trace:{sourceNodeId:nodeId,targetId:binding.targetId,field:binding.field,sourceAlias:text(state.alias).trim().slice(0,120),contentHash:sha256(value)}};
  }
  function resolveTextSources(node,ports){
    const textSources=[],issues=[];
    if(unsupported(node))issues.push({targetId:GLOBAL,field:'prompt',nodeId:'',reason:'schema'});
    const resolve=binding=>{
      const result=readSource(binding,ports);
      if(result.issue){issues.push(result.issue);return'';}
      textSources.push(result.trace);return result.value;
    };
    const value=(source,binding)=>bound(binding.source)?resolve(binding):source;
    const prompt=unsupported(node)?'':value(node.prompt,globalBinding(node));
    let layoutDraft=null;
    const summary=draft=>isObject(draft.summary)&&Object.keys(draft.summary).length?{summary:clone(draft.summary)}:{};
    if(!unsupported(node)&&node.mode==='layout'){
      const items=node.freeDraft.items.map((item,index)=>{
        const binding=freeBindings(node)[index],{textSource,captionSource,...plain}=clone(item);
        if(item.label==='text')plain.text=value(item.text,binding);else plain.caption=value(item.caption,binding);
        if(!plain.caption)delete plain.caption;
        return plain;
      });
      layoutDraft={items,...summary(node.freeDraft)};
    }else if(!unsupported(node)&&node.mode==='storyboard'){
      const grid=node.gridDraft,panels=grid.panels.map((panel,index)=>({id:panel.id,caption:value(panel.caption,gridBindings(node)[index])}));
      layoutDraft={rows:grid.rows,cols:grid.cols,margin:grid.margin,gutter:grid.gutter,panels,...summary(grid)};
    }
    // Aliases stay out: renaming a source changes nothing the model reads. Hashes are redundant with
    // the resolved text today but keep the identity of each bound field in the fingerprint.
    const negativePrompt=unsupported(node)?'':text(ports.getNegativePrompt?.(node)).trim();
    const fingerprint=JSON.stringify([node.mode,node.imageWidth,node.imageHeight,prompt,layoutDraft,textSources.map(item=>[item.targetId,item.field,item.sourceNodeId,item.contentHash]),issues,...(negativePrompt?[negativePrompt]:[])]);
    return{prompt,negativePrompt,layoutDraft,textSources,issues,draftRevision:node.draftRevision,inputFingerprint:'moss:'+sha256(fingerprint)};
  }
  // Output size changes keep regions where they are relative to the page.
  function scaleFreeDraft(node,width,height){
    const scaleX=node.imageWidth/width,scaleY=node.imageHeight/height;
    node.freeDraft.items.forEach(item=>{const [x1,y1,x2,y2]=item.bbox;item.bbox=[Math.floor(x1*scaleX),Math.floor(y1*scaleY),Math.min(node.imageWidth,Math.ceil(x2*scaleX)),Math.min(node.imageHeight,Math.ceil(y2*scaleY))];});
  }
  const toWireSource=source=>bound(source)?{kind:'text_node',node_id:source.nodeId}:inline();
  const fromWireSource=normalizeSource;
  function exportDraft(node){
    const{summary:freeSummary,items}=node.freeDraft,grid=node.gridDraft;
    return{schema:SCHEMA,schema_version:SCHEMA_VERSION,mode:node.mode,width:node.imageWidth,height:node.imageHeight,prompt:node.prompt,prompt_source:toWireSource(node.promptSource),
      free_draft:{summary:clone(freeSummary),items:items.map(item=>{
        const{textSource,captionSource,...plain}=clone(item);
        return{...plain,...(item.label==='text'?{text_source:toWireSource(textSource)}:{caption_source:toWireSource(captionSource)})};
      })},
      grid_draft:{summary:clone(grid.summary),rows:grid.rows,cols:grid.cols,margin:grid.margin,gutter:grid.gutter,panels:grid.panels.map(panel=>({id:panel.id,caption:panel.caption,caption_source:toWireSource(panel.captionSource)}))}};
  }
  // Official drafts have no references: materialized text only, and no storyboard form exists there.
  function exportOfficial(node,materialized){
    if(materialized.issues.length)throw new Error('存在失效的文本来源，无法导出');
    if(node.mode==='text')return{caption:materialized.prompt};
    if(node.mode!=='layout')throw new Error('分镜网格没有官方草稿格式');
    return{width:node.imageWidth,height:node.imageHeight,bbox_coord_space:'abs',bbox_format:'xyxy',summary:{caption:materialized.prompt,...clone(node.freeDraft.summary)},items:materialized.layoutDraft.items.map(({id,...item})=>item)};
  }
  // `draft` is the server's import receipt, already checked against the original text. Sources stay
  // references and are resolved later; a node id absent from this workflow surfaces as a missing source.
  function applyImport(node,draft){
    node.mode=draft.mode;node.imageWidth=draft.width;node.imageHeight=draft.height;
    node.prompt=text(draft.prompt);node.promptSource=fromWireSource(draft.prompt_source);
    if(draft.free_draft)node.freeDraft=normalizeFreeDraft({summary:draft.free_draft.summary,items:draft.free_draft.items.map(({text_source,caption_source,...item})=>({...item,textSource:fromWireSource(text_source),captionSource:fromWireSource(caption_source)}))});
    if(draft.grid_draft)node.gridDraft=normalizeGridDraft({...draft.grid_draft,panels:draft.grid_draft.panels.map(({caption_source,...panel})=>({...panel,captionSource:fromWireSource(caption_source)}))});
    node.draftRevision+=1;
    return normalize(node);
  }
  // Sources inside the cloned set move with it; sources outside stay shared. Run state never follows a clone.
  function remapClone(node,idMap={}){
    const copy=clone(node);
    const move=source=>{if(bound(source)&&idMap[source.nodeId])source.nodeId=idMap[source.nodeId];};
    move(copy.promptSource);
    (copy.freeDraft?.items||[]).forEach(item=>{move(item.textSource);move(item.captionSource);});
    (copy.gridDraft?.panels||[]).forEach(panel=>move(panel.captionSource));
    copy.jobId='';copy.resultJobId='';copy.panelJobId='';copy.status='idle';
    return copy;
  }
  window.DesktopMossModel=Object.freeze({TYPE,WIDTH,HEIGHT,SCHEMA,SCHEMA_VERSION,DEFAULT_MODEL_ID,DEFAULT_PRESET,MODES,PRESETS,GLOBAL,ASPECT_RATIOS,dimensionsForRatio,ratioFromDimensions,withinPixels,allBindings,bindingSlot,bound,LORA_SCALE_MIN,LORA_SCALE_MAX,MAX_LORAS,ICON,MENU_ITEM,sha256,active,normalizeLoraScale,normalizeSource,normalize,unsupported,targets,policy,modeBindings,textDependencies,missingDependencies,resolveTextSources,scaleFreeDraft,exportDraft,exportOfficial,applyImport,remapClone});
})();

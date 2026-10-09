// Qwen 2.1 canvas state and connection contract; no DOM or transport.
(function () {
  const TYPE='qwen21', WIDTH=720, HEIGHT=500;
  const DEFAULT_MODEL_ID='qwen-image-2.1-heretic-mlx-8bit';
  const DEFAULT_PRESET='viggle-v03-r256';
  const ASPECT_RATIOS=Object.freeze(['1:1','2:3','3:2','3:4','4:3','4:5','5:4','9:16','16:9','9:21','21:9']);
  const PRESETS=Object.freeze({'standard':{label:'标准 · 默认 40 步',steps:40,minSteps:2},
    'viggle-v021-r256':{label:'Viggle v0.2.1 · r256',steps:6,minSteps:5},
    'viggle-v03-r256':{label:'Viggle v0.3 · r256',steps:6,minSteps:5},
    'viggle-v021-r128':{label:'Viggle v0.2.1 · r128',steps:6,minSteps:5}});
  const clamp=(value,lo,hi,fallback)=>Number.isFinite(Number(value))?Math.max(lo,Math.min(hi,Number(value))):fallback;
  const active=status=>['submitting','queued','processing','running'].includes(String(status||''));
  function selectAvailableBase(node,status){
    if(node.type!==TYPE||active(node.status)||(status?.models||[]).some(item=>item.id===node.baseModelId))return false;
    const replacement=status?.model_replacements?.[node.baseModelId];
    if(!replacement||!(status?.models||[]).some(item=>item.id===replacement&&item.ready))return false;
    node.baseModelId=replacement;return true;
  }
  function dimensionsForRatio(ratio){if(!ASPECT_RATIOS.includes(ratio))return null;const [a,b]=ratio.split(':').map(Number),w=Math.sqrt(1024**2*a/b);return{width:Math.round(w/32)*32,height:Math.round(w*b/a/32)*32};}
  function ratioFromDimensions(width,height){
    return ASPECT_RATIOS.find(ratio=>{const size=dimensionsForRatio(ratio);return size.width===width&&size.height===height;})||
      ASPECT_RATIOS.find(ratio=>{const [a,b]=ratio.split(':').map(Number);return Math.abs(width/height-a/b)<.002;})||'custom';
  }
  // Canvas addNode accepts a center, but persisted node x/y are top-left bounds.
  function outputPosition(source,previous=null){
    return{x:source.x+source.width+100,y:previous?previous.y+previous.height+40:source.y};
  }
  function normalize(node){
    if(node.type!==TYPE)return node;
    node.width=WIDTH;node.height=HEIGHT;
    node.mode=['text','edit'].includes(node.mode)?node.mode:'text';
    const legacySteps={'viggle-6':6,'viggle-8':8}[node.preset];
    if(legacySteps){node.preset=DEFAULT_PRESET;if(node.steps===undefined)node.steps=legacySteps;}
    node.preset=PRESETS[node.preset]?node.preset:DEFAULT_PRESET;
    const requested=String(node.baseModelId||'').toLowerCase();node.baseModelId=/^[a-z0-9][a-z0-9._-]{0,119}$/.test(requested)?requested:DEFAULT_MODEL_ID;
    const dimensions=dimensionsForRatio(node.ratio);
    node.imageWidth=Math.round(clamp(node.imageWidth,256,2048,dimensions?.width||1024)/32)*32;
    node.imageHeight=Math.round(clamp(node.imageHeight,256,2048,dimensions?.height||1024)/32)*32;
    node.ratio=ratioFromDimensions(node.imageWidth,node.imageHeight);
    node.steps=Math.round(clamp(node.steps,PRESETS[node.preset].minSteps,60,PRESETS[node.preset].steps));
    node.guidance=node.preset==='standard'?clamp(node.guidance,1,10,1):1;
    node.imageCount=Math.round(clamp(node.imageCount,1,4,1));
    node.seed=node.seed===null||node.seed===undefined?'':String(node.seed).replace(/[^0-9]/g,'').slice(0,10);
    node.telegramEnabled=node.telegramEnabled===true;
    const seen=new Set();node.loras=(Array.isArray(node.loras)?node.loras:[]).filter(item=>/^[a-f0-9]{64}$/.test(String(item?.assetId||''))&&!seen.has(item.assetId)&&seen.add(item.assetId)).slice(0,4).map(item=>({assetId:item.assetId,scale:clamp(item.scale,0,2,1)}));
    node.referenceOrder=[...new Set((Array.isArray(node.referenceOrder)?node.referenceOrder:[]).filter(id=>typeof id==='string'&&id.length<300))];
    node.jobId=/^qwen21_[a-f0-9]{32}$/.test(String(node.jobId||''))?node.jobId:'';
    node.resultJobId=String(node.resultJobId||'');node.status=String(node.status||'idle');return node;
  }
  const targets=Object.freeze({text:[TYPE],image:[TYPE],image_group:[TYPE],layout:[TYPE],pose:[TYPE],qwen21:['image']});
  function policy(from,to){if(!targets[from?.type]?.includes(to?.type))return null;if(from.type===TYPE)return{inputRole:'image',outputRole:'image',single:false,replaceAllInputs:true};return{inputRole:from.type==='text'?'prompt':'image',outputRole:from.type==='text'?'prompt':'image',single:false};}
  function imageInputIds(node,canvas){
    return [...new Set((canvas?.edges||[]).filter(edge=>edge.to===node.id&&policy(canvas?.nodes?.[edge.from],node)?.inputRole==='image').map(edge=>edge.from))];
  }
  const resolveMode=(node,canvas)=>imageInputIds(node,canvas).length?'edit':'text';
  const ICON='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M5 4h14v14H5zM8 14l3-4 5 5M15 7h.01M13 18l4 4"/></svg>';
  const MENU_ITEM=Object.freeze({type:TYPE,title:'Qwen 2.1 · MLX',subtitle:'本地生成 / 多参考编辑 · Viggle Turbo',icon:ICON});
  window.DesktopQwen21Model=Object.freeze({TYPE,WIDTH,HEIGHT,DEFAULT_MODEL_ID,DEFAULT_PRESET,ASPECT_RATIOS,PRESETS,ICON,MENU_ITEM,normalize,active,selectAvailableBase,dimensionsForRatio,ratioFromDimensions,outputPosition,targets,policy,imageInputIds,resolveMode});
})();

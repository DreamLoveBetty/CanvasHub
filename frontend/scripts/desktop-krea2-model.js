// Krea 2 MLX canvas schema and typed connection contract. No DOM or transport.
(function () {
  const TYPE='krea2';
  const BUILTIN_MODEL_IDS=Object.freeze({
    '8bit':'krea-2-turbo-alis-mlx-8bit',
    'mixed-4-8':'krea-2-turbo-alis-mlx-mixed-4-8'
  });
  const DEFAULT_MODEL_ID=BUILTIN_MODEL_IDS['8bit'];
  const MODES=Object.freeze(['standard','edit']);
  const FIT_MODES=Object.freeze(['fit','crop']);
  const ASPECT_RATIOS=Object.freeze(['1:1','2:3','3:2','3:4','4:3','4:5','5:4','9:16','16:9','9:21','21:9']);
  const RATIO_DIMENSIONS=Object.freeze({
    '1:1':Object.freeze([1024,1024]),'2:3':Object.freeze([832,1248]),'3:2':Object.freeze([1248,832]),
    '3:4':Object.freeze([864,1152]),'4:3':Object.freeze([1152,864]),'4:5':Object.freeze([896,1120]),
    '5:4':Object.freeze([1120,896]),'9:16':Object.freeze([720,1280]),'16:9':Object.freeze([1280,720]),
    '9:21':Object.freeze([672,1568]),'21:9':Object.freeze([1568,672])
  });
  const active=status=>['submitting','queued','processing','running'].includes(String(status||''));
  const clamp=(value,min,max,fallback)=>{const number=Number(value);return Number.isFinite(number)?Math.max(min,Math.min(max,number)):fallback;};
  function ratioFromDimensions(width,height){
    const actual=Number(width)/Number(height);if(!Number.isFinite(actual)||actual<=0)return'custom';
    return ASPECT_RATIOS.find(ratio=>{const [w,h]=ratio.split(':').map(Number);return Math.abs(actual-w/h)<0.002;})||'custom';
  }
  function dimensionsForRatio(ratio){
    const dimensions=RATIO_DIMENSIONS[String(ratio||'')];return dimensions?{width:dimensions[0],height:dimensions[1]}:null;
  }
  function normalize(node){
    if(node.type!==TYPE)return node;
    // Krea keeps one fixed canvas footprint. The extra 20px over the canonical
    // input card reserves a real row for edit-only controls and the compact
    // LoRA summary, so the footer never covers selected adapters.
    node.width=720;node.height=480;
    node.precision=['8bit','mixed-4-8','bf16'].includes(node.precision)?node.precision:'8bit';
    const requestedModel=String(node.baseModelId||'').trim().toLowerCase();
    const validModel=/^[a-z0-9][a-z0-9._-]{0,127}$/.test(requestedModel);
    if(!validModel&&node.precision==='bf16')node.precision='8bit';
    node.baseModelId=validModel?requestedModel:BUILTIN_MODEL_IDS[node.precision];
    const requestedRatio=String(node.ratio||'');
    const requestedDimensions=dimensionsForRatio(requestedRatio);
    if(requestedDimensions&&(node.imageWidth===undefined||node.imageHeight===undefined)){
      node.imageWidth=requestedDimensions.width;node.imageHeight=requestedDimensions.height;
    }
    node.imageWidth=Math.round(clamp(node.imageWidth,256,2048,1024)/16)*16;
    node.imageHeight=Math.round(clamp(node.imageHeight,256,2048,1024)/16)*16;
    node.ratio=ratioFromDimensions(node.imageWidth,node.imageHeight);
    node.steps=Math.round(clamp(node.steps,1,50,8));
    node.imageCount=Math.round(clamp(node.imageCount,1,4,1));
    node.seed=node.seed===''||node.seed===null||node.seed===undefined?'':String(node.seed).replace(/[^0-9]/g,'').slice(0,19);
    node.mode=MODES.includes(String(node.mode||'').toLowerCase())?String(node.mode).toLowerCase():'standard';
    node.strength=clamp(node.strength,0.01,1,0.6);
    node.editAdapterId=/^[a-f0-9]{64}$/.test(String(node.editAdapterId||''))?String(node.editAdapterId):'';
    node.editAdapterScale=clamp(node.editAdapterScale,0.01,2,1);
    node.referenceStrength=clamp(node.referenceStrength,0.01,20,4);
    node.groundingPx=Math.round(clamp(node.groundingPx,0,2048,768)/32)*32;
    if(node.groundingPx>0&&node.groundingPx<256)node.groundingPx=256;
    node.fitMode=FIT_MODES.includes(String(node.fitMode||'').toLowerCase())?String(node.fitMode).toLowerCase():'fit';
    node.safetyEnabled=node.safetyEnabled===true;
    node.telegramEnabled=node.telegramEnabled===true;
    // Auto mode changes must not discard the fourth ordinary LoRA or a LoRA
    // temporarily used as the edit adapter. Enforce the active limit at submit.
    node.loras=Array.isArray(node.loras)?node.loras.slice(0,4).map(item=>({
      assetId:/^[a-f0-9]{64}$/.test(String(item?.assetId||''))?String(item.assetId):'',
      scale:clamp(item?.scale,0,2,1)
    })).filter(item=>item.assetId):[];
    node.jobId=/^krea2_[a-f0-9]{32}$/.test(String(node.jobId||''))?node.jobId:'';
    node.resultJobId=String(node.resultJobId||'');
    node.status=String(node.status||'idle');
    return node;
  }
  const targets=Object.freeze({text:[TYPE],image:[TYPE],krea2:['image']});
  function policy(from,to){
    if(!targets[from?.type]?.includes(to?.type))return null;
    if(from.type==='krea2')return{inputRole:'image',outputRole:'image',single:false,replaceAllInputs:true};
    return{inputRole:from.type==='text'?'prompt':'image',outputRole:from.type==='text'?'prompt':'image',single:from.type==='image'};
  }
  function imageInputIds(node,canvas){
    return [...new Set((canvas?.edges||[]).filter(edge=>edge.to===node.id&&policy(canvas?.nodes?.[edge.from],node)?.inputRole==='image').map(edge=>edge.from))];
  }
  const resolveMode=(node,canvas)=>imageInputIds(node,canvas).length?'edit':'standard';
  const regularLoras=node=>(node.loras||[]).filter(item=>node.mode!=='edit'||item.assetId!==node.editAdapterId);
  const ICON='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 2.8 14.2 8l5.2.7-4 3.5 1.2 5.1-4.6-2.7-4.6 2.7 1.2-5.1-4-3.5L9.8 8 12 2.8Z"/><path d="M18 3v4M16 5h4"/></svg>';
  const MENU_ITEM=Object.freeze({type:TYPE,title:'Krea 2 · MLX',subtitle:'Apple Silicon 本地生成 · 多 LoRA',icon:ICON});
  window.DesktopKrea2Model=Object.freeze({TYPE,ICON,MENU_ITEM,ASPECT_RATIOS,RATIO_DIMENSIONS,
    BUILTIN_MODEL_IDS,DEFAULT_MODEL_ID,MODES,FIT_MODES,active,normalize,ratioFromDimensions,dimensionsForRatio,targets,policy,imageInputIds,resolveMode,regularLoras});
})();

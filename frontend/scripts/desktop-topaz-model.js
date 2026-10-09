// Topaz owns its schema and graph compatibility; no Spandrel/music dependencies.
(function () {
  const TYPE = 'topaz';
  const MODELS = [
  {
    "value": "topaz-standard-v2",
    "label": "Standard V2",
    "profile": "classic",
    "protocol": "native",
    "verified": true
  },
  {
    "value": "topaz-standard-v1",
    "label": "Standard V1",
    "profile": "legacy",
    "protocol": "stack",
    "verified": true
  },
  {
    "value": "topaz-high-fidelity-v3",
    "label": "High Fidelity V3",
    "profile": "strength",
    "protocol": "native",
    "verified": true
  },
  {
    "value": "topaz-high-fidelity-v2",
    "label": "High Fidelity V2",
    "profile": "classic",
    "protocol": "native",
    "verified": true
  },
  {
    "value": "topaz-high-fidelity-v1",
    "label": "High Fidelity V1",
    "profile": "legacy",
    "protocol": "stack",
    "verified": true
  },
  {
    "value": "topaz-low-res-v2",
    "label": "Low res V2",
    "profile": "classic",
    "protocol": "native",
    "verified": true
  },
  {
    "value": "topaz-low-res-v1",
    "label": "Low res V1",
    "profile": "legacy",
    "protocol": "stack",
    "verified": true
  },
  {
    "value": "topaz-text-shapes",
    "label": "Text & shapes",
    "profile": "classic",
    "protocol": "native",
    "verified": true
  },
  {
    "value": "topaz-art-cg",
    "label": "Art & CG",
    "profile": "classic",
    "protocol": "native",
    "verified": true
  },
  {
    "value": "topaz-wonder-35",
    "label": "Wonder 3.5",
    "profile": "wonder",
    "protocol": "neuro",
    "verified": true
  },
  {
    "value": "topaz-wonder-3",
    "label": "Wonder 3",
    "profile": "wonder",
    "protocol": "neuro",
    "verified": true
  },
  {
    "value": "topaz-wonder-2",
    "label": "Wonder 2",
    "profile": "wonder2",
    "protocol": "neuro",
    "verified": true
  },
  {
    "value": "topaz-wonder-1",
    "label": "Wonder 1",
    "profile": "natural",
    "protocol": "stack",
    "verified": true
  },
  {
    "value": "topaz-standard-max",
    "label": "Standard Max",
    "profile": "strength",
    "protocol": "stack",
    "verified": true
  },
  {
    "value": "topaz-recover-v3",
    "label": "Recover V3",
    "profile": "recover3",
    "protocol": "stack",
    "verified": true
  },
  {
    "value": "topaz-recover-v2",
    "label": "Recover V2",
    "profile": "recover2",
    "protocol": "native",
    "verified": true
  },
  {
    "value": "topaz-recover-v1",
    "label": "Recover V1",
    "profile": "recover1",
    "protocol": "native",
    "verified": true
  },
  {
    "value": "topaz-redefine-realistic",
    "label": "Redefine realistic",
    "profile": "redefine_realistic",
    "protocol": "stack",
    "verified": true
  },
  {
    "value": "topaz-redefine-creative",
    "label": "Redefine creative",
    "profile": "redefine_creative",
    "protocol": "stack",
    "verified": true
  }
];
  const defaults = {resize_mode:'scale',scale:2,dimension:2048,unit:'px',ppi:300,auto:false,
    denoise:20,sharpen:20,fix_compression:0,strength:75,gamma_correction:false,
    grain:false,grain_strength:10,grain_intensity:50,grain_size:1,
    face_enhancement:false,face_strength:80,face_creativity:0,output_format:'png',jpeg_quality:95,enhancement_strength:1,detail:50,creativity:3,realistic_detail:0,texture:3,seed:42,description:''};
  const ranges = {scale:[.2,6],dimension:[.01,32000],ppi:[1,1200],denoise:[0,100],sharpen:[0,100],fix_compression:[0,100],strength:[0,100],
    grain_strength:[0,100],grain_intensity:[0,100],grain_size:[1,5],face_strength:[0,100],face_creativity:[0,1],jpeg_quality:[1,100],enhancement_strength:[.7,1.3],detail:[0,100],creativity:[2,5],realistic_detail:[0,1],texture:[1,5],seed:[0,2147483647]};
  const choices = {resize_mode:['scale','width','height','longest'], unit:['px','in','cm'],output_format:['png','jpg','tiff']};
  function minScale(model) {
    return MODELS.find(item=>item.value===model)?.protocol==='neuro'?1:ranges.scale[0];
  }
  function normalize(node) {
    node.width=760; node.height=550;
    node.model=MODELS.some(m=>m.value===node.model)?node.model:MODELS[0].value;
    const old = node.topaz || {}, options={};
    Object.entries(defaults).forEach(([key, fallback])=>{
      const v=old[key];
      options[key]=key==='description'?(typeof v==='string'?v.slice(0,2000):''):typeof fallback==='boolean'?v===true:choices[key]?(choices[key].includes(v)?v:fallback)
        :Number.isFinite(Number(v)) && typeof v!=='boolean' && v!==null && v!=='' && Number(v)>=ranges[key][0] && Number(v)<=ranges[key][1]?Number(v):fallback;
    });
    options.scale=Math.max(options.scale,minScale(node.model));
    for(const key of ['creativity','realistic_detail','texture','seed','face_creativity'])options[key]=Math.round(options[key]);
    if(![.7,1,1.3].includes(options.enhancement_strength))options.enhancement_strength=1;
    options.jpeg_quality=Math.round(options.jpeg_quality);
    node.topaz=options;
    node.output={archiveEnabled:true,telegramEnabled:node.output?.telegramEnabled===true};
    return node;
  }
  function migrate(node) {
    if (node.type==='upscale' && String(node.model||'').startsWith('topaz-')) {
      node.type=TYPE; node.topaz={...defaults,scale:2};
      delete node.autoUpscaleSourceKey;
    }
    return node.type===TYPE?normalize(node):node;
  }
  const targets={image:[TYPE],layout:[TYPE],pose:[TYPE],input:[TYPE],comfy:[TYPE],topaz:['image']};
  function policy(from,to) {
    return targets[from?.type]?.includes(to?.type)?{inputRole:'image',outputRole:'image',single:true,replaceAllInputs:true}:null;
  }
  const ICON='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="m12 3 9 5-9 13L3 8 12 3Z M3 8h18M8 8l4 13 4-13"/></svg>';
  window.DesktopTopazModel=Object.freeze({TYPE,MODELS,defaults,ranges,choices,minScale,normalize,migrate,targets,policy,ICON,
    menu:{type:TYPE,title:'Topaz Gigapixel',subtitle:'原生图像增强 · 独立模型与尺寸控制',icon:ICON}});
})();

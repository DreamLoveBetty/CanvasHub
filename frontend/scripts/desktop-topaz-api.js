// Called through DesktopApi's authenticated task adapter. No separate task state.
(function () {
  function imageSize(source) {
    return new Promise((resolve,reject)=>{
      const image=new Image();
      image.onload=()=>resolve({width:image.naturalWidth,height:image.naturalHeight});
      image.onerror=()=>reject(new Error('无法读取 Topaz 输入图片尺寸'));
      image.src=source;
    });
  }
  async function validateWonderSize(model,options,image) {
    if(window.DesktopTopazModel.minScale(model)<1)return;
    if(options.resize_mode==='scale') {
      if(Number(options.scale)<1)throw new Error('所选 Wonder 模型的生成倍数不能低于 1×');
      return;
    }
    const {width,height}=await imageSize(image);
    if(!width||!height)throw new Error('无法读取 Topaz 输入图片尺寸');
    const pixels=Number(options.dimension)*(options.unit==='px'?1:Number(options.ppi)/(options.unit==='cm'?2.54:1));
    const source=options.resize_mode==='width'?width:options.resize_mode==='height'?height:Math.max(width,height);
    if(pixels<source)throw new Error('所选 Wonder 模型的目标尺寸不能小于原图（至少 1×）');
  }
  async function submit(client,{config,images,lineage,telegramEnabled}) {
    if(images.length!==1)throw new Error('请连接一张图片到 Topaz 节点');
    await validateWonderSize(config.params.model,config.params.topaz,images[0]);
    return client.json('/api/topaz/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      prompt:config.prompt,model:config.params.model,options:config.params.topaz,images,
      telegram_enabled:telegramEnabled, ...(lineage?{lineage}: {})})});
  }
  window.DesktopTopazApi=Object.freeze({submit,catalog:client=>client.json('/api/topaz/models')});
})();

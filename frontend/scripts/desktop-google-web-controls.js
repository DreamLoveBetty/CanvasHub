// Google-only capability presentation. Existing API model/resolution values are retained.
(function () {
  function apply(node, provider) {
    if(!node)return;
    const web=provider==='google'&&node.querySelector('[data-field="googleProviderRoute"]')?.value==='google_web';
    for(const [selector,label,title] of [
      ['[data-field="model"], #deskModelSelect','Nano Banana Pro','Gemini Web 生图模式，不使用 OAuth 模型目录'],
      ['[data-field="resolution"], #deskResolutionSelect','2K','生成时将画幅与 2K 分辨率添加到提示词开头；优先下载原图，实际尺寸以返回文件为准']
    ]){
      const select=node.querySelector(selector);if(!select)continue;
      const parent=select.closest('label');if(!parent)continue;
      let view=parent.querySelector('[data-google-web-capability]');
      if(!view&&web){view=document.createElement('span');view.className='desk-google-web-capability';view.dataset.googleWebCapability='';parent.appendChild(view);}
      if(view){view.textContent=label;view.title=title;view.hidden=!web;}
      if(web||select.dataset.googleWebHidden==='true'){
        select.hidden=web;select.dataset.googleWebHidden=web?'true':'false';
        window.DesktopSelect?.refresh?.(select);
      }
    }
  }
  window.DesktopGoogleWebControls={apply};
})();

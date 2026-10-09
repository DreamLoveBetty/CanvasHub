// Only connection/cache preferences live in Settings; descriptions belong to the asset library.
(function(){
  function create({library,rerender,notify}){
    const esc=window.DesktopLoRAData.esc;
    let current=null,draft={auto_sync:false,api_key:''},busy=false,active=false;
    const tell=error=>notify(error?.message||String(error));
    async function activate(){active=true;try{current=await library.settings();draft.auto_sync=current.auto_sync;}finally{if(active)rerender();}}
    function deactivate(){active=false;draft.api_key='';}
    function render(){return `<section class="desk-settings-card is-ok desk-lora-settings"><header><span class="desk-settings-dot" aria-hidden="true"></span><h3>LoRA 资料连接与缓存</h3></header><div class="desk-settings-card__body"><p>封面、触发词与收藏在资产库的 LoRA 分类管理。在线补全不加载模型，也不暂停本地推理。</p><label class="desk-switch"><input type="checkbox" data-lora-setting="auto_sync"${draft.auto_sync?' checked':''}${!current||busy?' disabled':''}><span></span><em>自动补全新发现的 LoRA</em></label><div class="desk-lora-actions"><input class="desk-input" type="password" autocomplete="new-password" data-lora-setting="api_key" placeholder="${current?.api_key_configured?'已配置，留空保持不变':'Civitai API Key（可选）'}" value="${esc(draft.api_key)}"><button type="button" class="desk-button" data-lora-setting-action="save"${!current||busy?' disabled':''}>保存连接设置</button><button type="button" class="desk-button" data-lora-setting-action="remove-key"${!current?.api_key_configured||busy?' disabled':''}>清除 Key</button><button type="button" class="desk-button" data-lora-setting-action="clear-cache"${busy?' disabled':''}>清理远端预览缓存</button></div><small>Key 仅保存于后端。清理缓存不会删除用户添加的示例图、触发词或权重。</small></div></section>`;}
    function handleInput(event){const field=event.target.closest('[data-lora-setting]');if(!field)return false;draft[field.dataset.loraSetting]=field.type==='checkbox'?field.checked:field.value;return true;}
    function handleClick(event){const button=event.target.closest('[data-lora-setting-action]');if(!button)return false;if(busy)return true;
      const action=button.dataset.loraSettingAction;
      if(action==='clear-cache'&&!window.confirm('清理可重新获取的远端预览缓存？用户添加的图片和权重不会删除。'))return true;
      busy=true;rerender();
      (async()=>{if(action==='save'){current=await library.settings({auto_sync:draft.auto_sync,...(draft.api_key?{api_key:draft.api_key}:{})});draft.api_key='';notify('LoRA 连接设置已保存');}
        else if(action==='remove-key'){current=await library.settings({api_key:''});draft.api_key='';notify('Civitai API Key 已清除');}
        else if(action==='clear-cache'){const result=await library.clearCache();notify(`已清理 ${result.removed} 张远端预览`);}
      })().catch(tell).finally(()=>{busy=false;if(active)rerender();});return true;
    }
    return Object.freeze({activate,deactivate,render,handleInput,handleClick});
  }
  window.DesktopLoRASettings=Object.freeze({create});
})();

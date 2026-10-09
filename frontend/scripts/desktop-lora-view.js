// Reusable library/picker/details presentation. Host supplies all graph and asset ports.
(function () {
  const {esc, parseWords} = window.DesktopLoRAData;
  const engines = {krea2:'Krea 2', qwen21:'Qwen 2.1'};
  const button = (action, text, extra = '') => `<button type="button" class="desk-button${['add','add-card','confirm-add','save','confirm-insert','confirm-reset'].includes(action) ? ' desk-button--primary' : action === 'delete-weight' ? ' desk-button--danger' : ''}" data-lora-action="${action}" ${extra}>${text}</button>`;
  const wordsLabel = item => item.trigger_status === 'none' ? '已确认不需要触发词' : item.trigger_words?.length ? item.trigger_words.join(' · ') : '触发词未填写';
  function create({library, assets, listTargets = () => [], addToNode, triggerTargets, insertTriggers, notify: onNotify = () => {}}) {
    let root = null, request = 0, page = 0, items = [], total = 0, engine = '', filter = 'all', query = '';
    let disposeView = null, picker = null, addDialog = null, detailDialog = null, detailItem = null, detailRequest = 0;
    let fixedNode = '', fixedEngine = '', timer = 0, searchTimer = 0, busy = false;
    const syncVersions = new Map();
    const pendingAdds = new Set();
    const media = value => esc(library.mediaUrl(value));
    function notify(message) {
      onNotify(message);
      const modal = [...document.querySelectorAll('.desk-lora-dialog[open]')].at(-1);
      const status = modal?.querySelector('[data-lora-feedback]');
      if (status) status.textContent = message;
    }
    const tell = error => notify(error?.message || String(error));
    const active = () => Boolean(root?.isConnected || detailDialog?.isConnected);
    function dialog(title, large = false) {
      const element = document.createElement('dialog');
      element.className = 'desk-lora-dialog' + (large ? ' desk-lora-dialog--large' : '');
      element.setAttribute('aria-label', title);
      element.innerHTML = `<header><div><small>本地模型资料</small><h2>${esc(title)}</h2></div>${button('close', '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17"></path></svg>', 'aria-label="关闭 LoRA 面板" title="关闭"')}</header><p class="desk-lora-feedback" data-lora-feedback role="status" aria-live="polite"></p><div class="desk-lora-dialog__body"></div><footer class="desk-lora-dialog__footer" hidden></footer>`;
      document.querySelector('.desk-app').append(element);
      element.querySelector('[data-lora-action="close"]').onclick = () => element.close();
      element.addEventListener('click', event => { if (event.target === element) { const r=element.getBoundingClientRect(); if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)element.querySelector('[data-lora-action="close"]').click(); } });
      element.addEventListener('keydown', event => event.stopPropagation());
      element.addEventListener('pointerdown', event => event.stopPropagation());
      element.showModal(); return element;
    }
    function cards() {
      if (!items.length) return '<div class="desk-lora-empty">没有匹配的本地 LoRA。将权重放入对应模型的 LoRA 目录后刷新；没有线上资料也可以手动设置。</div>';
      return items.map(item => `<article class="desk-lora-card">
        <button type="button" class="desk-lora-card__open" data-lora-id="${item.asset_id}" aria-label="查看 ${esc(item.name)}">
          <div class="desk-lora-card__image">${item.cover ? `<img src="${media(item.cover.thumb_url)}" alt="${esc(item.name)} 示例" loading="lazy" decoding="async">` : '<span>LoRA<small>添加效果示例</small></span>'}</div>
          <div class="desk-lora-card__text"><strong title="${esc(item.name)}">${esc(item.name)}</strong><small>${esc(item.version || '本地模型')} · ${esc(item.engines.map(e => engines[e] || e).join(' / ') || '文件缺失')}</small><p>${esc(wordsLabel(item))}</p></div>
        </button><footer><span>${item.favorite ? '★ 已收藏' : item.sync?.status === 'ready' ? '资料已同步' : '本地资料'}</span>${button('add-card', pendingAdds.has(item.asset_id) ? '添加中…' : '添加', `data-id="${item.asset_id}" title="添加到节点" aria-label="添加 ${esc(item.name)} 到节点" ${!item.available || pendingAdds.has(item.asset_id) ? 'disabled' : ''}`)}</footer>
      </article>`).join('');
    }
    function renderShell() {
      if (!root) return;
      root.classList.add('desk-lora-library');
      root.innerHTML = `<div class="desk-lora-toolbar"><input class="desk-input" type="search" data-lora-query placeholder="搜索名称 / 触发词 / 标签" value="${esc(query)}" aria-label="搜索 LoRA">
        <select class="desk-select" data-lora-engine aria-label="LoRA 推理框架" ${fixedEngine ? 'disabled' : ''}><option value="">全部框架</option>${Object.entries(engines).map(([key,label])=>`<option value="${key}"${engine===key?' selected':''}>${label}</option>`).join('')}</select>
        <select class="desk-select" data-lora-filter aria-label="LoRA 筛选">${[['all','全部模型'],['favorite','收藏'],['incomplete','资料待补全'],['missing','文件缺失'],['hidden','已隐藏']].map(([key,label])=>`<option value="${key}"${filter===key?' selected':''}>${label}</option>`).join('')}</select>
        ${button('refresh','刷新目录')}${button('sync-page','补全本页资料')}</div>
        <div class="desk-lora-status" role="status" aria-live="polite">正在读取本地资料…</div><div class="desk-lora-grid"></div>
        <footer class="desk-lora-pagination">${button('prev','上一页')}<span data-lora-page></span>${button('next','下一页')}</footer>`;
      window.DesktopSelect?.refreshAll?.();
    }
    function paintList(message = '') {
      if (!root?.isConnected) return;
      root.querySelector('.desk-lora-grid').innerHTML = cards();
      root.querySelector('.desk-lora-status').textContent = message || `共 ${total} 个 LoRA · 资料本地保存，在线补全不影响推理`;
      root.querySelector('[data-lora-page]').textContent = `${page + 1} / ${Math.max(1,Math.ceil(total / 40))}`;
      root.querySelector('[data-lora-action="prev"]').disabled = page === 0;
      root.querySelector('[data-lora-action="next"]').disabled = (page + 1) * 40 >= total;
    }
    async function refresh(force = false) {
      if (!root?.isConnected) return;
      const current = ++request;
      try {
        const result = await library.list({engine, filter, query, offset:page * 40, limit:40, refresh:force ? '1' : '0'});
        if (current !== request || !root?.isConnected) return;
        items = result.items; total = result.total;
        if (page && !items.length) { page = Math.max(0, Math.ceil(total / 40) - 1); return refresh(); }
        paintList(result.scan_errors?.length ? `发现 ${result.scan_errors.length} 个目录／模型问题：${result.scan_errors.map(e=>[e.name,e.error].filter(Boolean).join('：')).join(' · ')}` : '');
      } catch (error) { if (current === request && root?.isConnected) paintList(error.message); }
    }
    function mount(container) {
      unmount(); root = container; page = 0; renderShell();
      const controller = new AbortController();
      root.addEventListener('input', event => { if (event.target.matches('[data-lora-query]')) { clearTimeout(searchTimer); searchTimer=setTimeout(()=>{query=event.target.value;page=0;refresh();},180); } },{signal:controller.signal});
      root.addEventListener('change', event => { if(event.target.matches('[data-lora-engine]'))engine=event.target.value;else if(event.target.matches('[data-lora-filter]'))filter=event.target.value;else return;page=0;refresh(); },{signal:controller.signal});
      root.addEventListener('click', event => {
        const card = event.target.closest('[data-lora-id]');
        if (card) { openDetail(card.dataset.loraId).catch(tell); return; }
        const target=event.target.closest('[data-lora-action]'); if(!target||target.disabled)return;
        const action=target.dataset.loraAction;
        if(action==='refresh')refresh(true);
        else if(action==='prev'||action==='next'){page+=action==='prev'?-1:1;refresh();}
        else if(action==='sync-page')sync(items.filter(item=>item.available).map(item=>item.asset_id));
        else if(action==='add-card')quickAdd(target.dataset.id).catch(tell);
      },{signal:controller.signal});
      const unsubscribe=library.subscribe(()=>refresh());
      disposeView=()=>{controller.abort();unsubscribe();};
      refresh(); resumeSync();
    }
    function unmount() {
      closeAddDialog();
      request++; disposeView?.(); disposeView=null; clearTimeout(searchTimer); clearTimeout(timer);
      if(root)root.classList.remove('desk-lora-library');root=null;
    }
    function openPicker(nodeId, modelEngine) {
      if (!closeDetail()) return;
      closePicker();fixedNode=nodeId;fixedEngine=modelEngine;engine=modelEngine;query='';filter='all';
      picker=dialog('选择 LoRA',true);
      const current=picker;
      current.addEventListener('close',()=>{current.remove();if(picker===current){unmount();picker=null;fixedNode='';fixedEngine='';}},{once:true});
      mount(current.querySelector('.desk-lora-dialog__body'));
    }
    function closePicker() {
      const current=picker;
      if(!current)return;
      picker=null;unmount();fixedNode='';fixedEngine='';current.close();current.remove();
    }
    function closeAddDialog() {
      const current=addDialog;addDialog=null;
      if(current){current.close();current.remove();}
    }
    function paintAddButtons(id) {
      root?.querySelectorAll('[data-lora-action="add-card"]').forEach(control=>{
        if(control.dataset.id!==id)return;
        control.disabled=pendingAdds.has(id)||!items.find(item=>item.asset_id===id)?.available;
        control.textContent=pendingAdds.has(id)?'添加中…':'添加';
      });
    }
    async function addCardToNode(nodeId,item) {
      if(pendingAdds.has(item.asset_id))return false;
      pendingAdds.add(item.asset_id);paintAddButtons(item.asset_id);
      try {
        // The existing engine controller owns capacity, duplicates, busy state
        // and async node-lifetime validation. Never edit graph state here.
        await addToNode(nodeId,item.asset_id);
        notify('已添加 LoRA；强度和提示词不会被自动修改');
        return true;
      } finally {pendingAdds.delete(item.asset_id);paintAddButtons(item.asset_id);}
    }
    async function quickAdd(id) {
      if(pendingAdds.has(id))return;
      const item=items.find(value=>value.asset_id===id);
      if(!item?.available)throw new Error('LoRA 文件已不存在，请刷新目录');
      const choices=targets(item);
      if(!choices.length)throw new Error(fixedNode?'目标节点已不存在或不兼容':'请先创建兼容的 Krea 2 或 Qwen 2.1 节点');
      if(choices.length===1){await addCardToNode(choices[0].id,item);return;}
      closeAddDialog();
      const modal=addDialog=dialog('添加 LoRA 到节点');
      modal.querySelector('.desk-lora-dialog__body').innerHTML=`<p>${esc(item.name)}</p><div class="desk-lora-actions"><select class="desk-select" data-lora-add-target aria-label="目标节点">${choices.map(node=>`<option value="${esc(node.id)}">${esc(node.label)}</option>`).join('')}</select>${button('confirm-add','添加到节点')}</div>`;
      const confirm=modal.querySelector('[data-lora-action="confirm-add"]');
      confirm.onclick=async()=>{
        if(confirm.disabled)return;
        confirm.disabled=true;
        try {
          const nodeId=modal.querySelector('[data-lora-add-target]').value;
          if(!targets(item).some(node=>node.id===nodeId))throw new Error('目标节点已不存在或不兼容');
          if(await addCardToNode(nodeId,item)){
            modal.close();modal.remove();if(addDialog===modal)addDialog=null;
          }
        } catch(error){tell(error);} finally {confirm.disabled=false;}
      };
      modal.addEventListener('close',()=>{modal.remove();if(addDialog===modal)addDialog=null;},{once:true});
      window.DesktopSelect?.refreshAll?.();
    }
    async function sync(ids) {
      if(!ids.length){tell('没有可同步的 LoRA');return;}
      try { await library.sync(ids.slice(0,100));notify('资料已加入后台同步队列');resumeSync(); }
      catch(error){tell(error);}
    }
    async function resumeSync() {
      clearTimeout(timer); if(!active())return;
      try {
        const state=await library.syncState(); if(!active())return;
        if(root?.isConnected&&state.active)root.querySelector('.desk-lora-status').textContent='正在后台同步资料，不占用推理资源…';
        const current=state.items.find(item=>item.asset_id===detailItem?.asset_id);
        if(detailDialog?.isConnected&&current)detailDialog.querySelector('[data-lora-sync-state]').textContent=current.message||current.status;
        if(state.active)timer=setTimeout(resumeSync,1800);
        else {
          // Refresh cached descriptions before notifying node labels. Ordinary
          // list/detail reads remain silent to avoid subscriber refresh loops.
          const updated=state.items.filter(item=>library.peek(item.asset_id)&&syncVersions.get(item.asset_id)!==JSON.stringify(item));
          for(let index=0;index<updated.length;index+=5){
            await Promise.all(updated.slice(index,index+5).map(async item=>{
              await library.detail(item.asset_id);syncVersions.set(item.asset_id,JSON.stringify(item));
            }));
            if(!active())return;
          }
          library.changed();if(detailDialog?.isConnected)detailDialog.querySelector('[data-lora-sync-state]').textContent=(current?.message||'')+' · 重新打开详情可查看最新资料';
        }
      }catch(error){if(active())tell(error);}
    }
    const input=(key,label,value,type='text',hint='')=>`<label${hint?` title="${esc(hint)}"`:''}><span>${label}</span><input class="desk-input" data-lora-edit="${key}" type="${type}" value="${esc(value??'')}" ${type==='number'?'min="0" max="2" step="0.05"':''}></label>`;
    async function openDetailForNode(id,nodeId,modelEngine) {if(detailDialog&&!closeDetail())return;fixedNode=nodeId;fixedEngine=modelEngine;return openDetail(id);}
    async function openDetail(id) {
      closeAddDialog();
      if(detailDialog){if(!closeDetail())return;}
      const token=++detailRequest, item=await library.detail(id);if(token!==detailRequest)return;
      detailItem=item;detailDialog=dialog(item.name,true);const current=detailDialog;
      current.classList.add('desk-lora-dialog--detail');
      current.addEventListener('cancel',event=>{event.preventDefault();closeDetail();});
      current.querySelector('[data-lora-action="close"]').onclick=()=>closeDetail();
      current.addEventListener('close',()=>{current.remove();if(detailDialog===current){detailRequest++;detailDialog=null;detailItem=null;if(!picker){fixedNode='';fixedEngine='';}}},{once:true});
      renderDetail();
    }
    function dirty() {return Boolean(detailDialog?.dataset.dirty==='true');}
    function closeDetail() {
      if(busy){tell('正在保存，请稍候');return false;}
      if(dirty()&&!window.confirm('有未保存的 LoRA 资料，放弃修改并关闭？'))return false;
      const current=detailDialog;
      detailRequest++;
      if(current){detailDialog=null;detailItem=null;if(!picker){fixedNode='';fixedEngine='';}current.close();current.remove();}
      return true;
    }
    function targets(item) {return listTargets().filter(target=>item.engines.includes(target.engine)&&(!fixedNode||target.id===fixedNode));}
    function renderDetail() {
      const item=detailItem, host=detailDialog?.querySelector('.desk-lora-dialog__body');if(!host||!item)return;
      const choices=targets(item),pictures=item.previews||[];
      detailDialog.querySelector('header h2').textContent=item.name;
      const footer=detailDialog.querySelector('.desk-lora-dialog__footer');
      detailDialog.setAttribute('aria-label', item.name);
      host.innerHTML=`<div class="desk-lora-detail"><section class="desk-lora-detail__visual" aria-label="效果示例与文件">
        <div class="desk-lora-hero">${item.cover?`<img src="${media(item.cover.url)}" alt="LoRA 效果示例" data-lora-hero>`:'<span>尚无示例图</span>'}</div>
        <div class="desk-lora-thumbs">${pictures.map((p,index)=>`<div><button type="button" data-lora-preview="${p.id}" title="${esc(p.caption||'查看示例')}"><img src="${media(p.thumb_url)}" alt="示例 ${index+1}"></button><div>${button('cover','封面',`data-id="${p.id}"`)}${button('move-preview','←',`data-id="${p.id}" ${index===0?'disabled':''} aria-label="前移示例 ${index+1}"`)}${button('remove-preview','×',`data-id="${p.id}" aria-label="删除示例 ${index+1}"`)}</div></div>`).join('')}</div>
        <div class="desk-lora-actions">${button('upload','上传示例')}${button('asset-image','从资产库选择')}</div><input type="file" accept="image/png,image/jpeg,image/webp,image/gif" data-lora-upload hidden>
        <small>示例独立保存，不修改权重；远端示例可能包含其他模型。</small>
        <details class="desk-lora-disclosure desk-lora-source"><summary>Civitai 资料</summary><div class="desk-lora-disclosure__body">
          <p data-lora-sync-state>${esc(item.sync?.message||'尚未同步')}</p><small>${item.binding?.version_id?'人工关联版本 '+esc(item.binding.version_id):item.sync?.matched_by==='hash'?'文件哈希精确匹配':'可通过哈希匹配，或绑定具体版本'}</small>
          <input class="desk-input" type="url" data-lora-bind aria-label="Civitai 具体版本链接" placeholder="Civitai 具体版本链接" value="${esc(item.binding?.url||'')}">
          <div class="desk-lora-actions">${button('bind','绑定版本')}${button('unbind','取消关联')}${button('sync','同步资料')}${item.source_url?`<a class="desk-button" href="${esc(item.source_url)}" target="_blank" rel="noopener noreferrer">原页面</a>`:''}</div>
        </div></details>
        <details class="desk-lora-disclosure"><summary>文件信息与权重操作</summary><div class="desk-lora-disclosure__body">
          <dl class="desk-lora-file-info">${item.members.map(m=>`<dt>${engines[m.engine]||esc(m.engine)} · ${m.present?'本地可用':'文件缺失'}</dt><dd>${esc(m.filename||m.name)} · ${(Number(m.file_size)/1024**2).toFixed(1)} MB</dd>`).join('')}<dt>SHA256</dt><dd>${item.asset_id}</dd></dl>
          <div class="desk-lora-danger"><p>仅删除所选框架的权重，资料保留；运行或排队中的模型不可删除。</p><div class="desk-lora-actions"><select class="desk-select" data-lora-delete-engine aria-label="删除权重的框架">${item.engines.map(e=>`<option value="${e}">${engines[e]}</option>`).join('')}</select>${button('delete-weight','删除权重文件',!item.available?'disabled':'')}</div></div>
        </div></details>
      </section><section class="desk-lora-detail__info" aria-label="LoRA 资料">
        <div class="desk-lora-fields desk-lora-fields--identity">${input('name','显示名称',item.name)}${input('version','版本',item.version)}${input('recommended_scale','推荐强度',item.recommended_scale??'','number','仅作为推荐值，不自动应用到节点')}</div>
        <section class="desk-lora-apply"><label><span>目标节点</span><select class="desk-select" data-lora-node aria-label="目标节点">${choices.length?choices.map(t=>`<option value="${esc(t.id)}">${esc(t.label)}</option>`).join(''):'<option value="">请先在画布创建兼容节点</option>'}</select></label>${button('add','添加到节点',!choices.length?'disabled':'')}</section>
        <section class="desk-lora-triggers"><div class="desk-lora-section-head"><h3>触发词</h3><label class="desk-lora-trigger-status"><span>状态</span><select class="desk-select" data-lora-edit="trigger_status" aria-label="触发词状态">${[['unknown','未填写'],['provided','已填写'],['none','确认不需要触发词']].map(([key,label])=>`<option value="${key}"${item.trigger_status===key?' selected':''}>${label}</option>`).join('')}</select></label></div>
          <div class="desk-lora-trigger-tools"><div class="desk-lora-chips">${(item.trigger_words||[]).map((word,index)=>`<div class="desk-lora-chip"><label><input type="checkbox" data-lora-word="${index}" checked><span>${esc(word)}</span></label>${button('copy-word','复制',`data-index="${index}"`)}</div>`).join('')||`<small>${esc(wordsLabel(item))}</small>`}</div><div class="desk-lora-actions">${button('copy','复制所选')}${button('insert','插入提示词')}</div></div>
          <details class="desk-lora-disclosure desk-lora-trigger-editor"${item.trigger_words?.length?'':' open'}><summary>编辑触发词</summary><div class="desk-lora-disclosure__body">
            <label><span>每行一个完整词组</span><textarea class="desk-input" rows="2" data-lora-edit="trigger_words">${esc((item.trigger_words||[]).join('\n'))}</textarea></label>
          </div></details>
        </section>
        <label><span>使用说明</span><textarea class="desk-input" rows="3" data-lora-edit="description">${esc(item.description||'')}</textarea></label>
        <label><span>标签 · 每行一个</span><textarea class="desk-input" rows="2" data-lora-edit="tags">${esc(item.tags.join('\n'))}</textarea></label>
        <details class="desk-lora-disclosure"><summary>来源与资料维护</summary><div class="desk-lora-disclosure__body">
          <div class="desk-lora-fields">${input('source_name','来源名称',item.source_name)}${input('source_url','来源链接',item.source_url,'url')}</div>
          <small>手动字段：${esc(item.manual_fields.join('、')||'无')}。同步不覆盖手动设置。</small>
          <div class="desk-lora-actions">${button('reset','恢复自动字段')}</div>
        </div></details>
      </section></div>`;
      footer.hidden=false;
      footer.innerHTML=`<div class="desk-lora-actions"><label><input type="checkbox" data-lora-edit="favorite"${item.favorite?' checked':''}> 收藏</label><label><input type="checkbox" data-lora-edit="hidden"${item.hidden?' checked':''}> 隐藏</label></div><div class="desk-lora-actions"><small>修改后保存资料</small>${button('save','保存资料')}</div>`;
      detailDialog.dataset.dirty='false';host.oninput=footer.oninput=event=>{if(event.target.matches('[data-lora-edit]'))detailDialog.dataset.dirty='true';};
      host.onchange=footer.onchange=event=>{if(event.target.matches('[data-lora-edit]'))detailDialog.dataset.dirty='true';if(event.target.matches('[data-lora-upload]'))perform(async()=>{for(const file of event.target.files)await library.upload(item.asset_id,file);await reloadDetail();});};
      host.onclick=event=>{const preview=event.target.closest('[data-lora-preview]');if(preview){const p=item.previews.find(p=>p.id===preview.dataset.loraPreview);host.querySelector('.desk-lora-hero').innerHTML=`<img src="${media(p.url)}" alt="LoRA 效果示例" data-lora-hero>`;return;}
        if(event.target.matches('[data-lora-hero]')){const enlarged=dialog('效果示例',true);enlarged.querySelector('.desk-lora-dialog__body').innerHTML=`<img class="desk-lora-enlarged" src="${esc(event.target.src)}" alt="放大示例">`;enlarged.addEventListener('close',()=>enlarged.remove(),{once:true});return;}
        const target=event.target.closest('[data-lora-action]');if(target)perform(()=>action(target.dataset.loraAction,target));};
      footer.onclick=event=>{const target=event.target.closest('[data-lora-action]');if(target)perform(()=>action(target.dataset.loraAction,target));};
      window.DesktopSelect?.refreshAll?.();
    }
    async function perform(task) {
      if(busy)return;busy=true;
      const current=detailDialog;current?.setAttribute('aria-busy','true');
      try{await task();}catch(error){tell(error);}finally{busy=false;current?.setAttribute('aria-busy','false');}
    }
    async function reloadDetail() {const id=detailItem?.asset_id;if(!id)return;const item=await library.detail(id);if(detailItem?.asset_id===id){detailItem=item;renderDetail();}}
    function selectedWords() {return [...detailDialog.querySelectorAll('[data-lora-word]:checked')].map(el=>detailItem.trigger_words[Number(el.dataset.loraWord)]);}
    function changes() {
      const result={};
      detailDialog.querySelectorAll('[data-lora-edit]').forEach(el=>{
        const key=el.dataset.loraEdit;let value=el.type==='checkbox'?el.checked:el.value;
        if(key==='trigger_words'||key==='tags')value=parseWords(value);
        if(key==='recommended_scale')value=value===''?null:Number(value);
        const before=detailItem[key]??(Array.isArray(value)?[]:typeof value==='boolean'?false:key==='recommended_scale'?null:'');
        if(JSON.stringify(value)!==JSON.stringify(before))result[key]=value;
      });
      if('trigger_words'in result||'trigger_status'in result){result.trigger_words=parseWords(detailDialog.querySelector('[data-lora-edit="trigger_words"]').value);result.trigger_status=detailDialog.querySelector('[data-lora-edit="trigger_status"]').value;if(result.trigger_words.length&&result.trigger_status==='unknown')result.trigger_status='provided';}
      return result;
    }
    async function save() {if(!dirty())return;await library.update(detailItem,changes());detailDialog.dataset.dirty='false';await reloadDetail();notify('LoRA 资料已保存');}
    async function action(name,target) {
      const id=detailItem.asset_id;
      // Saving re-renders the form. Keep explicit selections and binding drafts.
      const bindUrl=detailDialog.querySelector('[data-lora-bind]').value;
      const selectedNode=detailDialog.querySelector('[data-lora-node]').value;
      const selectedEngine=detailDialog.querySelector('[data-lora-delete-engine]').value;
      if(name==='save'){await save();return;}
      if(['copy','copy-word','insert'].includes(name)){
        const words=name==='copy-word'?[detailItem.trigger_words[Number(target.dataset.index)]]:selectedWords();
        if(!words.length)throw new Error('请先填写并保存触发词，再选择要使用的词组');
        if(name==='insert'){await chooseText(words);return;}
        await navigator.clipboard.writeText(words.join(', '));notify('触发词已复制');return;
      }
      if(dirty())await save();
      if(name==='upload')detailDialog.querySelector('[data-lora-upload]').click();
      else if(name==='asset-image')chooseAsset();
      else if(name==='cover'){await library.update(detailItem,{cover_id:target.dataset.id});await reloadDetail();}
      else if(name==='move-preview'){const order=detailItem.previews.map(p=>p.id),index=order.indexOf(target.dataset.id);if(index>0){[order[index-1],order[index]]=[order[index],order[index-1]];await library.update(detailItem,{preview_order:order});await reloadDetail();}}
      else if(name==='remove-preview'){if(window.confirm('删除这张 LoRA 示例图？不影响原资产和权重。')){await library.deletePreview(id,target.dataset.id);await reloadDetail();}}
      else if(name==='reset')resetFields();
      else if(name==='bind'||name==='unbind'){await library.bind(id,name==='unbind'?'':bindUrl);await reloadDetail();}
      else if(name==='sync')await sync([id]);
      else if(name==='add'){if(!selectedNode)throw new Error('请先创建兼容节点');await addToNode(selectedNode,id);notify('已添加 LoRA；强度和提示词不会被自动修改');}
      else if(name==='delete-weight'){if(window.confirm(`删除 ${engines[selectedEngine]} 中的 ${detailItem.name} 权重文件？此操作不能通过图库撤销。`)){await library.deleteWeight(id,selectedEngine);await reloadDetail();}}
    }
    function resetFields() {
      const fields=detailItem.manual_fields;if(!fields.length){notify('没有人工覆盖字段');return;}
      const modal=dialog('恢复自动资料');modal.querySelector('.desk-lora-dialog__body').innerHTML=`<p>仅重置勾选字段。用户上传的示例图不会删除。</p><div class="desk-lora-reset">${fields.map(key=>`<label><input type="checkbox" value="${key}"> ${esc(key)}</label>`).join('')}</div>${button('confirm-reset','恢复所选字段')}`;
      modal.querySelector('[data-lora-action="confirm-reset"]').onclick=()=>perform(async()=>{const keys=[...modal.querySelectorAll('input:checked')].map(el=>el.value);if(!keys.length)return;await library.update(detailItem,{},keys);modal.close();await reloadDetail();});modal.addEventListener('close',()=>modal.remove(),{once:true});
    }
    async function chooseText(words) {
      const nodeId=detailDialog.querySelector('[data-lora-node]').value;if(!nodeId)throw new Error('请选择兼容的目标节点');
      const texts=triggerTargets?.(nodeId)||[],modal=dialog('插入触发词');
      modal.querySelector('.desk-lora-dialog__body').innerHTML=`<p>${esc(words.join(', '))}</p><p>明确选择目标文本。共享文本的修改会影响其他连接。</p><select class="desk-select" data-lora-text>${texts.length?texts.map(t=>`<option value="${esc(t.id)}">${esc(t.label)}</option>`).join(''):'<option value="">新建文本节点并连接</option>'}</select>${button('confirm-insert',texts.length?'插入到所选文本':'新建文本并插入')}`;
      modal.querySelector('[data-lora-action="confirm-insert"]').onclick=()=>perform(async()=>{await insertTriggers(nodeId,modal.querySelector('[data-lora-text]').value,words);modal.close();notify('触发词已插入，保留原提示词与素材块');});modal.addEventListener('close',()=>modal.remove(),{once:true});window.DesktopSelect?.refreshAll?.();
    }
    function chooseAsset() {
      const id=detailItem.asset_id,modal=dialog('选择图片资产',true),body=modal.querySelector('.desk-lora-dialog__body');let generation=0,offset=0;
      body.innerHTML=`<div class="desk-lora-toolbar"><input class="desk-input" type="search" data-asset-query placeholder="搜索生成图片">${button('search-assets','搜索')}</div><div class="desk-lora-grid" data-asset-grid></div><div class="desk-lora-actions">${button('prev-assets','上一页')}${button('next-assets','下一页')}</div>`;
      async function load(){const token=++generation;try{const result=await assets({query:body.querySelector('[data-asset-query]').value,limit:24,offset,fields:'card'});if(!modal.isConnected||token!==generation)return;const rows=result.assets||[];body.querySelector('[data-asset-grid]').innerHTML=rows.map((asset,index)=>`<button type="button" class="desk-lora-card__open" data-asset-index="${index}"><div class="desk-lora-card__image"><img src="${media(asset.thumbUrl||asset.imageUrl)}" alt="${esc(asset.title||asset.file||'图片')}" loading="lazy"></div></button>`).join('')||'<p>没有匹配的图片资产</p>';body.querySelector('[data-lora-action="prev-assets"]').disabled=offset===0;body.querySelector('[data-lora-action="next-assets"]').disabled=offset+24>=result.total;body.querySelectorAll('[data-asset-index]').forEach(el=>{el.onclick=()=>perform(async()=>{const asset=rows[Number(el.dataset.assetIndex)];await library.upload(id,await library.imageBlob(asset.imageUrl));modal.close();await reloadDetail();});});}catch(error){if(modal.isConnected)tell(error);}}
      body.querySelector('[data-lora-action="search-assets"]').onclick=()=>{offset=0;load();};body.querySelector('[data-lora-action="prev-assets"]').onclick=()=>{offset=Math.max(0,offset-24);load();};body.querySelector('[data-lora-action="next-assets"]').onclick=()=>{offset+=24;load();};modal.addEventListener('close',()=>{generation++;modal.remove();},{once:true});load();
    }
    function dispose(){if(!closeDetail())return false;closePicker();unmount();return true;}
    return Object.freeze({mount,unmount,refresh,openPicker,openDetail,openDetailForNode,dispose});
  }
  window.DesktopLoRAView=Object.freeze({create});
})();

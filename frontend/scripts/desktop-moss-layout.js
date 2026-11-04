// MOSS in-node layout board. The draft stays on the node; this editor owns only selection, drag and undo.
(function () {
  const MAX_REGIONS=64,MIN_EDGE=16,DEFAULT_BOX=[240,140],BOARD_WIDTH=692,BOARD_MAX_HEIGHT=420;
  const LABELS=Object.freeze({text:'文字',object:'物体',character:'人物'});
  const ALIGN=Object.freeze([['left','左对齐'],['center','水平居中'],['right','右对齐'],['top','顶对齐'],['middle','垂直居中'],['bottom','底对齐']]);
  const clamp=(value,lo,hi)=>Math.max(lo,Math.min(hi,value));
  // Client rects already include the outer canvas zoom, so one mapping serves every scale.
  const toImage=(point,rect,size)=>({x:clamp(Math.round((point.x-rect.left)/rect.width*size.width),0,size.width),y:clamp(Math.round((point.y-rect.top)/rect.height*size.height),0,size.height)});
  function boxFromPoints(a,b,size){
    const box=[Math.min(a.x,b.x),Math.min(a.y,b.y),Math.max(a.x,b.x),Math.max(a.y,b.y)];
    if(box[2]-box[0]>=MIN_EDGE&&box[3]-box[1]>=MIN_EDGE)return box;
    const width=Math.min(DEFAULT_BOX[0],size.width),height=Math.min(DEFAULT_BOX[1],size.height),x=clamp(a.x-width/2,0,size.width-width),y=clamp(a.y-height/2,0,size.height-height);
    return[x,y,x+width,y+height].map(Math.round);
  }
  function moveBox(box,dx,dy,size){const width=box[2]-box[0],height=box[3]-box[1],x=clamp(box[0]+dx,0,size.width-width),y=clamp(box[1]+dy,0,size.height-height);return[x,y,x+width,y+height];}
  // A corner is named by the edges it drags, e.g. "nw" moves the left and top edges.
  function resizeBox(box,corner,dx,dy,size){
    const next=[...box];
    if(corner.includes('w'))next[0]=clamp(box[0]+dx,0,box[2]-MIN_EDGE);
    if(corner.includes('e'))next[2]=clamp(box[2]+dx,box[0]+MIN_EDGE,size.width);
    if(corner.includes('n'))next[1]=clamp(box[1]+dy,0,box[3]-MIN_EDGE);
    if(corner.includes('s'))next[3]=clamp(box[3]+dy,box[1]+MIN_EDGE,size.height);
    return next;
  }
  function alignBox(box,edge,size){
    const width=box[2]-box[0],height=box[3]-box[1],x={left:0,center:Math.round((size.width-width)/2),right:size.width-width}[edge],y={top:0,middle:Math.round((size.height-height)/2),bottom:size.height-height}[edge];
    return moveBox(box,(x??box[0])-box[0],(y??box[1])-box[1],size);
  }
  const newId=items=>{let index=items.length+1;while(items.some(item=>item.id===`region-${index}`))index++;return`region-${index}`;};
  function createItem(items,label,bbox){return label==='text'?{id:newId(items),label,text:'',caption:'',textSource:{kind:'inline'},bbox}:{id:newId(items),label,caption:'',captionSource:{kind:'inline'},bbox};}
  function duplicateItem(items,item,size){return{...JSON.parse(JSON.stringify(item)),id:newId(items),bbox:moveBox(item.bbox,24,24,size)};}
  // Switching between text and picture regions carries the content and its binding across fields.
  function changeLabel(item,label){
    const wasText=item.label==='text',isText=label==='text';item.label=label;
    if(wasText===isText)return item;
    if(isText){item.text=item.caption;item.textSource=item.captionSource;item.caption='';delete item.captionSource;}
    else{item.caption=item.text;item.captionSource=item.textSource;delete item.text;delete item.textSource;}
    return item;
  }
  const sourceField=item=>item.label==='text'?'text':'caption';
  function create({host,getNode,canEdit,updateDraft,listTextSources,bindTextSource,focusTextNode,fieldPreview,compile,importDraft,collapse,select,notify,resized}){
    const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    const abort=new AbortController(),undo=[],redo=[];
    let tool='',selected='',drag=null,pressed=false,editing=null,signature='',previewText='';
    const size=()=>{const node=getNode();return{width:node.imageWidth,height:node.imageHeight};};
    const items=()=>getNode().freeDraft.items;
    const current=()=>items().find(item=>item.id===selected)||null;
    const percent=(value,total)=>`${value/total*100}%`;
    const place=(el,box)=>{const{width,height}=size();el.style.left=percent(box[0],width);el.style.top=percent(box[1],height);el.style.width=percent(box[2]-box[0],width);el.style.height=percent(box[3]-box[1],height);};
    function commit(mutate){
      const node=getNode(),before=JSON.parse(JSON.stringify(node.freeDraft)),draft=JSON.parse(JSON.stringify(node.freeDraft));
      mutate(draft);
      try{updateDraft(draft);undo.push(before);if(undo.length>100)undo.shift();redo.length=0;}catch(error){notify(error.message);}
      render(true);
    }
    function restore(from,to){
      const draft=from.pop();if(!draft)return;
      try{to.push(JSON.parse(JSON.stringify(getNode().freeDraft)));updateDraft(draft);}catch(error){to.pop();from.push(draft);notify(error.message);}
      if(!items().some(item=>item.id===selected))selected='';render(true);
    }
    function bind(sourceId){
      const item=current();if(!item)return;const before=JSON.parse(JSON.stringify(getNode().freeDraft));
      try{bindTextSource(item.id,sourceField(item),sourceId||null);undo.push(before);redo.length=0;}catch(error){notify(error.message);}
      render(true);
    }
    function remove(){if(!selected)return;const id=selected;selected='';commit(draft=>{draft.items=draft.items.filter(item=>item.id!==id);});}
    function duplicate(){const item=current();if(!item)return;if(items().length>=MAX_REGIONS){notify(`最多 ${MAX_REGIONS} 个区域`);return;}let id='';commit(draft=>{const copy=duplicateItem(draft.items,item,size());id=copy.id;draft.items.push(copy);});selected=id;render(true);}
    function setBox(id,bbox){commit(draft=>{const item=draft.items.find(entry=>entry.id===id);if(item)item.bbox=bbox;});}
    function beginEdit(id){
      const item=items().find(entry=>entry.id===id);if(!item||!canEdit())return;
      if(fieldPreview(item).bound){notify('内容来自文本节点，请在来源节点修改或先解除绑定。');return;}
      const field=sourceField(item);selected=id;render(true);
      const box=host.querySelector(`[data-moss-box="${CSS.escape(id)}"]`),input=document.createElement('textarea');
      input.className='desk-moss-layout__input';input.value=item[field];input.setAttribute('aria-label',`${LABELS[item.label]}内容`);input.placeholder=item.label==='text'?'输入画面上的实际文字':'描述这个区域的内容';
      editing={id,field,input,canceled:false};box.replaceChildren(input);input.focus();
    }
    function finishEdit(){
      if(!editing)return;const{id,field,input,canceled}=editing;editing=null;
      if(!canceled&&input.value!==items().find(item=>item.id===id)?.[field])commit(draft=>{const item=draft.items.find(entry=>entry.id===id);if(item)item[field]=input.value;});else render(true);
      focusKeys();
    }
    const focusKeys=()=>host.querySelector('[data-moss-keys]')?.focus({preventScroll:true});
    function boxHtml(item){
      const preview=fieldPreview(item),text=preview.issue||preview.text;
      return`<div class="desk-moss-layout__box desk-moss-layout__box--${esc(item.label)}${item.id===selected?' is-selected':''}" data-moss-box="${esc(item.id)}"><span class="desk-moss-layout__tag">${LABELS[item.label]||esc(item.label)}</span><p class="${preview.issue?'is-error':text?'':'is-empty'}">${esc(text||'双击输入')}</p>${preview.bound?`<em title="来源文本节点">⛓ ${esc(preview.alias||'')}</em>`:''}${item.id===selected?['nw','ne','sw','se'].map(corner=>`<i data-moss-handle="${corner}" class="desk-moss-layout__handle--${corner}"></i>`).join(''):''}</div>`;
    }
    function toolbarHtml(item){
      const preview=fieldPreview(item),boundId=preview.bound?preview.nodeId:'',sources=listTextSources();
      const known=!boundId||sources.some(source=>source.id===boundId);
      return`<div class="desk-moss-layout__float" data-moss-float><select aria-label="区域类型" data-moss-box-label>${Object.entries(LABELS).map(([id,name])=>`<option value="${id}"${id===item.label?' selected':''}>${name}</option>`).join('')}</select><select aria-label="绑定文本节点" data-moss-box-source><option value="">不绑定</option>${known?'':`<option value="${esc(boundId)}" selected>来源已失效</option>`}${sources.map(source=>`<option value="${esc(source.id)}"${source.id===boundId?' selected':''}>${esc(source.alias)}</option>`).join('')}</select>${boundId?`<button type="button" data-moss-box-focus title="跳转到来源">跳转</button>`:''}${ALIGN.map(([id,name])=>`<button type="button" data-moss-box-align="${id}" title="${name}" aria-label="${name}">${name.slice(0,1)}</button>`).join('')}<button type="button" data-moss-box-duplicate title="复制">复制</button><button type="button" data-moss-box-delete title="删除">删除</button></div>`;
    }
    function render(force=false){
      if(host.hidden||drag||editing)return;
      const{width,height}=size(),editable=canEdit(),state=JSON.stringify([items().map(item=>[item,fieldPreview(item)]),selected,tool,editable,width,height,undo.length,redo.length,previewText,listTextSources()]);
      if(!force&&state===signature)return;signature=state;
      const keys=host.querySelector('[data-moss-keys]'),refocus=keys&&document.activeElement===keys;
      const boardWidth=Math.min(BOARD_WIDTH,BOARD_MAX_HEIGHT*width/height),item=current();
      host.innerHTML=`<div class="desk-moss-layout__tools">${Object.entries(LABELS).map(([id,name])=>`<button type="button" class="desk-button${tool===id?' is-active':''}" data-moss-tool="${id}" aria-pressed="${tool===id}"${editable?'':' disabled'}>${name}</button>`).join('')}<button type="button" class="desk-button" data-moss-undo${editable&&undo.length?'':' disabled'}>撤销</button><button type="button" class="desk-button" data-moss-redo${editable&&redo.length?'':' disabled'}>重做</button><span></span><button type="button" class="desk-button" data-moss-preview>提示词预览</button><button type="button" class="desk-button" data-moss-import${editable?'':' disabled'}>导入草稿</button><button type="button" class="desk-button" data-moss-collapse>收起</button></div>
        <div class="desk-moss-layout__board${editable?'':' is-readonly'}" data-moss-board style="width:${boardWidth}px;aspect-ratio:${width}/${height}"><input class="desk-moss-layout__keys" data-moss-keys readonly aria-label="布局画板键盘操作">${items().map(boxHtml).join('')}${item&&editable?toolbarHtml(item):''}${items().length?'':'<p class="desk-moss-layout__hint">选择上方类型后在画板上拖出区域</p>'}</div>${previewText?`<pre class="desk-moss-layout__preview" data-moss-preview-text>${esc(previewText)}</pre>`:''}`;
      host.querySelectorAll('[data-moss-box]').forEach(el=>place(el,items().find(entry=>entry.id===el.dataset.mossBox).bbox));
      if(refocus)focusKeys();
      resized?.();
    }
    function pointerDown(event){
      const board=event.target.closest('[data-moss-board]');if(!board)return;event.stopPropagation();
      if(event.target.closest('[data-moss-float],textarea')||!canEdit())return;
      pressed=true;select();const rect=board.getBoundingClientRect(),point=toImage({x:event.clientX,y:event.clientY},rect,size()),handle=event.target.closest('[data-moss-handle]'),boxEl=event.target.closest('[data-moss-box]');
      if(boxEl){
        const id=boxEl.dataset.mossBox,box=items().find(item=>item.id===id).bbox;
        if(selected!==id){selected=id;render(true);}
        drag={kind:handle?'resize':'move',corner:handle?.dataset.mossHandle,id,box:[...box],next:box,origin:point,rect,el:host.querySelector(`[data-moss-box="${CSS.escape(id)}"]`)};
      }else if(tool){
        if(items().length>=MAX_REGIONS){notify(`最多 ${MAX_REGIONS} 个区域`);return;}
        const ghost=document.createElement('div');ghost.className='desk-moss-layout__ghost';board.append(ghost);drag={kind:'create',origin:point,next:point,rect,el:ghost};
      }else if(selected){selected='';render(true);}
      if(drag)host.querySelector('[data-moss-board]').setPointerCapture?.(event.pointerId);
      focusKeys();
    }
    function pointerMove(event){
      if(!drag)return;const point=toImage({x:event.clientX,y:event.clientY},drag.rect,size()),dx=point.x-drag.origin.x,dy=point.y-drag.origin.y;
      if(drag.kind==='create'){drag.next=point;place(drag.el,boxFromPoints(drag.origin,point,size()));return;}
      drag.next=drag.kind==='move'?moveBox(drag.box,dx,dy,size()):resizeBox(drag.box,drag.corner,dx,dy,size());place(drag.el,drag.next);
    }
    function pointerUp(){
      const finished=drag,wasPressed=pressed;drag=null;pressed=false;
      if(finished?.kind==='create'){
        finished.el.remove();let id='';commit(draft=>{const item=createItem(draft.items,tool,boxFromPoints(finished.origin,finished.next,size()));id=item.id;draft.items.push(item);});
        selected=id;tool='';beginEdit(id);return;
      }
      if(finished){if(finished.next.some((value,index)=>value!==finished.box[index]))setBox(finished.id,finished.next);else render(true);}
      // A render during pointerdown removes the pressed element, so mousedown cannot be canceled and focus lands on the canvas.
      if(wasPressed&&!editing)focusKeys();
    }
    async function showPreview(){
      if(previewText){previewText='';render(true);return;}
      try{const receipt=await compile();if(!receipt){notify('输入已变化，请重新预览');return;}previewText=receipt.compiled.prompt;render(true);}catch(error){notify(error.message);}
    }
    function pickDraft(){
      const input=document.createElement('input');input.type='file';input.accept='application/json,.json';
      input.addEventListener('change',async()=>{const file=input.files?.[0];if(!file)return;try{if(await importDraft(await file.text())){undo.length=0;redo.length=0;selected='';render(true);}}catch(error){notify(error.message);}},{once:true});
      input.click();
    }
    function click(event){
      const target=event.target,toolButton=target.closest('[data-moss-tool]');
      if(toolButton){tool=tool===toolButton.dataset.mossTool?'':toolButton.dataset.mossTool;render(true);return;}
      if(target.closest('[data-moss-collapse]')){collapse();return;}
      if(target.closest('[data-moss-preview]')){showPreview();return;}
      if(!canEdit())return;
      if(target.closest('[data-moss-undo]'))restore(undo,redo);
      else if(target.closest('[data-moss-redo]'))restore(redo,undo);
      else if(target.closest('[data-moss-import]'))pickDraft();
      else if(target.closest('[data-moss-box-delete]'))remove();
      else if(target.closest('[data-moss-box-duplicate]'))duplicate();
      else if(target.closest('[data-moss-box-focus]')){const preview=current()&&fieldPreview(current());if(preview?.nodeId)focusTextNode(preview.nodeId);}
      else{const align=target.closest('[data-moss-box-align]');if(align&&current())setBox(selected,alignBox(current().bbox,align.dataset.mossBoxAlign,size()));}
    }
    function changed(event){
      if(!canEdit())return;
      if(event.target.matches('[data-moss-box-source]'))bind(event.target.value);
      else if(event.target.matches('[data-moss-box-label]')){const label=event.target.value,id=selected;commit(draft=>{changeLabel(draft.items.find(item=>item.id===id),label);});}
    }
    function keydown(event){
      event.stopPropagation();
      if(editing&&event.target===editing.input){
        if(event.isComposing)return;
        if(event.key==='Escape'){editing.canceled=true;editing.input.blur();}
        else if(event.key==='Enter'&&(event.metaKey||event.ctrlKey))editing.input.blur();
        return;
      }
      if(!event.target.matches('[data-moss-keys]')||!canEdit())return;
      const command=event.metaKey||event.ctrlKey,key=event.key.toLowerCase();
      if(key==='delete'||key==='backspace'){event.preventDefault();remove();}
      else if(command&&key==='z'){event.preventDefault();event.shiftKey?restore(redo,undo):restore(undo,redo);}
      else if(command&&key==='d'){event.preventDefault();duplicate();}
      else if(key==='enter'&&selected){event.preventDefault();beginEdit(selected);}
      else if(event.key.startsWith('Arrow')&&current()){event.preventDefault();const step=event.shiftKey?16:1,delta={ArrowLeft:[-step,0],ArrowRight:[step,0],ArrowUp:[0,-step],ArrowDown:[0,step]}[event.key];setBox(selected,moveBox(current().bbox,delta[0],delta[1],size()));}
    }
    const signal={signal:abort.signal};
    host.addEventListener('pointerdown',pointerDown,signal);host.addEventListener('pointermove',pointerMove,signal);host.addEventListener('pointerup',pointerUp,signal);host.addEventListener('pointercancel',()=>{if(drag?.kind==='create')drag.el.remove();drag=null;render(true);},signal);
    // Native mousedown would move focus off the key sink onto the canvas viewport right after pointerdown set it.
    host.addEventListener('mousedown',event=>{if(event.target.closest('[data-moss-board]')&&!event.target.closest('textarea,select,input,button,[data-moss-float]'))event.preventDefault();},signal);
    host.addEventListener('click',click,signal);host.addEventListener('change',changed,signal);host.addEventListener('keydown',keydown,signal);
    host.addEventListener('dblclick',event=>{const box=event.target.closest('[data-moss-box]');if(box&&!event.target.closest('textarea'))beginEdit(box.dataset.mossBox);},signal);
    host.addEventListener('focusout',event=>{if(editing&&event.target===editing.input)finishEdit();},signal);
    return Object.freeze({render,open:()=>render(true),close:()=>{if(editing){editing.canceled=false;editing.input.blur();}},dispose:()=>abort.abort()});
  }
  window.DesktopMossLayout=Object.freeze({create,MODES:Object.freeze(['layout']),toImage,boxFromPoints,moveBox,resizeBox,alignBox,createItem,duplicateItem,changeLabel});
})();

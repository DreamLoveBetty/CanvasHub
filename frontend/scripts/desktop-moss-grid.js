// MOSS storyboard board. Panels are written inside their cell; geometry always comes from the output size and the grid fields.
(function () {
  const SHAPES=Object.freeze({3:[1,3],4:[2,2],6:[2,3],8:[2,4],9:[3,3]});
  const MIN_PANEL_EDGE=256,BOARD_WIDTH=692,BOARD_MAX_HEIGHT=420;
  // Mirrors backend/moss/layout.py _partition: the remainder goes to the leading cells, one pixel each.
  function partition(total,parts,margin,gutter){
    const usable=total-2*margin-(parts-1)*gutter;if(usable<parts)return null;
    const base=Math.floor(usable/parts),extra=usable%parts,spans=[];let start=margin;
    for(let index=0;index<parts;index++){const end=start+base+(index<extra?1:0);spans.push([start,end]);start=end+gutter;}
    return spans;
  }
  function cells(grid,size){
    const xs=partition(size.width,grid.cols,grid.margin,grid.gutter),ys=partition(size.height,grid.rows,grid.margin,grid.gutter);
    if(!xs||!ys)return null;
    return ys.flatMap(([y1,y2])=>xs.map(([x1,x2])=>[x1,y1,x2,y2]));
  }
  const nextId=panels=>{let index=panels.length+1;while(panels.some(panel=>panel.id===`p${index}`))index++;return`p${index}`;};
  // Panels are matched by position only when the count changes; surviving ones keep their id, text and binding.
  function resizeGrid(grid,rows,cols){
    const count=rows*cols,panels=grid.panels.slice(0,count);
    while(panels.length<count)panels.push({id:nextId(panels),caption:'',captionSource:{kind:'inline'}});
    return{...grid,rows,cols,panels};
  }
  const transpose=grid=>({...grid,rows:grid.cols,cols:grid.rows});
  function movePanel(grid,id,delta){
    const panels=[...grid.panels],from=panels.findIndex(panel=>panel.id===id),to=from+delta;
    if(from<0||to<0||to>=panels.length)return grid;
    [panels[from],panels[to]]=[panels[to],panels[from]];return{...grid,panels};
  }
  function create({host,getNode,canEdit,updateDraft,listTextSources,bindTextSource,focusTextNode,fieldPreview,compile,importDraft,collapse,select,notify,resized,setOption,warnings,hasPanels,expandPanels}){
    const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    const abort=new AbortController(),undo=[],redo=[],copy=value=>JSON.parse(JSON.stringify(value));
    let selected='',pressed=false,editing=null,signature='',previewText='';
    const grid=()=>getNode().gridDraft;
    const size=()=>{const node=getNode();return{width:node.imageWidth,height:node.imageHeight};};
    const current=()=>grid().panels.find(panel=>panel.id===selected)||null;
    const focusKeys=()=>host.querySelector('[data-moss-keys]')?.focus({preventScroll:true});
    function commit(next){
      if(!cells(next,size())){notify('边距和间隔过大，分格没有面积');render(true);return;}
      const before=copy(grid());
      try{updateDraft(copy(next));undo.push(before);if(undo.length>100)undo.shift();redo.length=0;}catch(error){notify(error.message);}
      if(!current())selected='';render(true);
    }
    function restore(from,to){
      const draft=from.pop();if(!draft)return;
      try{to.push(copy(grid()));updateDraft(draft);}catch(error){to.pop();from.push(draft);notify(error.message);}
      if(!current())selected='';render(true);
    }
    function bind(sourceId){
      const panel=current();if(!panel)return;const before=copy(grid());
      try{bindTextSource(panel.id,'caption',sourceId||null);undo.push(before);redo.length=0;}catch(error){notify(error.message);}
      render(true);
    }
    function beginEdit(id){
      const panel=grid().panels.find(entry=>entry.id===id);if(!panel||!canEdit())return;
      if(fieldPreview(panel).bound){notify('内容来自文本节点，请在来源节点修改或先解除绑定。');return;}
      selected=id;render(true);
      const cell=host.querySelector(`[data-moss-cell="${CSS.escape(id)}"]`),input=document.createElement('textarea');
      input.className='desk-moss-layout__input';input.value=panel.caption;input.setAttribute('aria-label','分镜描述');input.placeholder='描述这一格的画面';
      editing={id,input,canceled:false};cell.replaceChildren(input);input.focus();
    }
    function finishEdit(){
      if(!editing)return;const{id,input,canceled}=editing;editing=null;
      const panel=grid().panels.find(entry=>entry.id===id);
      if(!canceled&&panel&&input.value!==panel.caption)commit({...grid(),panels:grid().panels.map(entry=>entry.id===id?{...entry,caption:input.value}:entry)});else render(true);
      focusKeys();
    }
    function cellHtml(panel,index,box){
      const preview=fieldPreview(panel),text=preview.issue||preview.text,width=box[2]-box[0],height=box[3]-box[1],low=Math.min(width,height)<MIN_PANEL_EDGE;
      return`<div class="desk-moss-layout__box desk-moss-grid__cell${panel.id===selected?' is-selected':''}" data-moss-cell="${esc(panel.id)}" style="left:${box[0]/size().width*100}%;top:${box[1]/size().height*100}%;width:${width/size().width*100}%;height:${height/size().height*100}%"><span class="desk-moss-layout__tag">${index+1} · ${width}×${height}${low?' · 细节可能不足':''}</span><p class="${preview.issue?'is-error':text?'':'is-empty'}">${esc(text||'双击输入这一格')}</p>${preview.bound?`<em title="来源文本节点">⛓ ${esc(preview.alias||'')}</em>`:''}</div>`;
    }
    function selectionHtml(panel,editable){
      if(!panel||!editable)return'<div class="desk-moss-grid__selection"><small>点选一格可绑定文本节点或调整顺序</small></div>';
      const preview=fieldPreview(panel),boundId=preview.bound?preview.nodeId:'',sources=listTextSources(),known=!boundId||sources.some(source=>source.id===boundId),index=grid().panels.indexOf(panel);
      return`<div class="desk-moss-grid__selection desk-moss-layout__float" data-moss-float><select aria-label="绑定文本节点" data-moss-cell-source><option value="">不绑定</option>${known?'':`<option value="${esc(boundId)}" selected>来源已失效</option>`}${sources.map(source=>`<option value="${esc(source.id)}"${source.id===boundId?' selected':''}>${esc(source.alias)}</option>`).join('')}</select>${boundId?'<button type="button" data-moss-cell-focus>跳转</button>':''}<button type="button" data-moss-cell-move="-1"${index>0?'':' disabled'}>前移</button><button type="button" data-moss-cell-move="1"${index<grid().panels.length-1?'':' disabled'}>后移</button></div>`;
    }
    function render(force=false){
      if(host.hidden||editing)return;
      const draft=grid(),{width,height}=size(),node=getNode(),editable=canEdit(),notes=warnings().map(item=>item.message),expandable=hasPanels(),state=JSON.stringify([draft.panels.map(panel=>[panel,fieldPreview(panel)]),draft.rows,draft.cols,draft.margin,draft.gutter,selected,editable,width,height,undo.length,redo.length,previewText,listTextSources(),notes,expandable,node.drawGrid,node.splitPanels]);
      if(!force&&state===signature)return;signature=state;
      const keys=host.querySelector('[data-moss-keys]'),refocus=keys&&document.activeElement===keys;
      const off=editable?'':' disabled',boardWidth=Math.min(BOARD_WIDTH,BOARD_MAX_HEIGHT*width/height),boxes=cells(draft,size()),count=draft.rows*draft.cols,square=draft.rows===draft.cols;
      host.innerHTML=`<div class="desk-moss-layout__tools"><select class="desk-moss-grid__count" data-moss-grid-count aria-label="分镜格数"${off}>${Object.keys(SHAPES).map(id=>`<option value="${id}"${Number(id)===count?' selected':''}>${id} 格</option>`).join('')}</select><button type="button" class="desk-button" data-moss-grid-transpose${editable&&!square?'':' disabled'}>${draft.rows}×${draft.cols} 转置</button><button type="button" class="desk-button" data-moss-undo${editable&&undo.length?'':' disabled'}>撤销</button><button type="button" class="desk-button" data-moss-redo${editable&&redo.length?'':' disabled'}>重做</button><span></span>${expandable?'<button type="button" class="desk-button" data-moss-grid-expand>展开分格</button>':''}<button type="button" class="desk-button" data-moss-preview>提示词预览</button><button type="button" class="desk-button" data-moss-import${off}>导入草稿</button><button type="button" class="desk-button" data-moss-collapse>收起</button></div>
        <div class="desk-moss-grid__controls"><label>边距 <input class="desk-number" type="number" min="0" max="256" step="1" data-stepper="off" data-moss-grid-spacing="margin" value="${draft.margin}"${off}></label><label>间隔 <input class="desk-number" type="number" min="0" max="256" step="1" data-stepper="off" data-moss-grid-spacing="gutter" value="${draft.gutter}"${off}></label><label><input type="checkbox" data-moss-grid-option="splitPanels"${node.splitPanels?' checked':''}${off}> 生成后切图</label><label><input type="checkbox" data-moss-grid-option="drawGrid"${node.drawGrid?' checked':''}${off}> 另存描线图</label></div>
        ${selectionHtml(current(),editable)}
        <div class="desk-moss-layout__board${editable?'':' is-readonly'}" data-moss-board style="width:${boardWidth}px;aspect-ratio:${width}/${height}"><input class="desk-moss-layout__keys" data-moss-keys readonly aria-label="分镜画板键盘操作">${boxes?draft.panels.map((panel,index)=>boxes[index]?cellHtml(panel,index,boxes[index]):'').join(''):'<p class="desk-moss-layout__hint">边距和间隔过大，分格没有面积</p>'}</div>${notes.length?`<p class="desk-moss-grid__notes">${notes.map(esc).join(' · ')}</p>`:''}${previewText?`<pre class="desk-moss-layout__preview" data-moss-preview-text>${esc(previewText)}</pre>`:''}`;
      if(refocus)focusKeys();
      resized?.();
    }
    function pointerDown(event){
      const board=event.target.closest('[data-moss-board]');if(!board)return;event.stopPropagation();
      if(event.target.closest('textarea')||!canEdit())return;
      pressed=true;select();const id=event.target.closest('[data-moss-cell]')?.dataset.mossCell||'';
      if(id!==selected){selected=id;render(true);}
      focusKeys();
    }
    // A render during pointerdown removes the pressed element, so focus has to be taken back on release.
    function pointerUp(){const wasPressed=pressed;pressed=false;if(wasPressed&&!editing)focusKeys();}
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
      const target=event.target;
      if(target.closest('[data-moss-collapse]')){collapse();return;}
      if(target.closest('[data-moss-preview]')){showPreview();return;}
      if(target.closest('[data-moss-grid-expand]')){expandPanels();return;}
      if(!canEdit())return;
      const move=target.closest('[data-moss-cell-move]');
      if(move)commit(movePanel(grid(),selected,Number(move.dataset.mossCellMove)));
      else if(target.closest('[data-moss-grid-transpose]'))commit(transpose(grid()));
      else if(target.closest('[data-moss-undo]'))restore(undo,redo);
      else if(target.closest('[data-moss-redo]'))restore(redo,undo);
      else if(target.closest('[data-moss-import]'))pickDraft();
      else if(target.closest('[data-moss-cell-focus]')){const preview=current()&&fieldPreview(current());if(preview?.nodeId)focusTextNode(preview.nodeId);}
    }
    function changed(event){
      const target=event.target;if(!canEdit())return;
      if(target.matches('[data-moss-cell-source]'))bind(target.value);
      else if(target.matches('[data-moss-grid-count]')){const[rows,cols]=SHAPES[target.value];commit(resizeGrid(grid(),rows,cols));}
      else if(target.matches('[data-moss-grid-spacing]')){const value=Number(target.value);if(Number.isInteger(value)&&value>=0&&value<=256)commit({...grid(),[target.dataset.mossGridSpacing]:value});else render(true);}
      else if(target.matches('[data-moss-grid-option]'))setOption(target.dataset.mossGridOption,target.checked);
    }
    function keydown(event){
      event.stopPropagation();
      if(editing&&event.target===editing.input){
        if(event.isComposing)return;
        if(event.key==='Escape'){editing.canceled=true;editing.input.blur();}
        else if(event.key==='Enter'&&(event.metaKey||event.ctrlKey))editing.input.blur();
        return;
      }
      if(!event.target.matches('[data-moss-keys]'))return;
      const command=event.metaKey||event.ctrlKey,key=event.key.toLowerCase();
      if(key==='delete'||key==='backspace')event.preventDefault();
      else if(!canEdit())return;
      else if(command&&key==='z'){event.preventDefault();event.shiftKey?restore(redo,undo):restore(undo,redo);}
      else if(key==='enter'&&selected){event.preventDefault();beginEdit(selected);}
    }
    const signal={signal:abort.signal};
    host.addEventListener('pointerdown',pointerDown,signal);host.addEventListener('pointerup',pointerUp,signal);
    host.addEventListener('mousedown',event=>{if(event.target.closest('[data-moss-board]')&&!event.target.closest('textarea'))event.preventDefault();},signal);
    host.addEventListener('click',click,signal);host.addEventListener('change',changed,signal);host.addEventListener('keydown',keydown,signal);
    host.addEventListener('dblclick',event=>{const cell=event.target.closest('[data-moss-cell]');if(cell&&!event.target.closest('textarea'))beginEdit(cell.dataset.mossCell);},signal);
    host.addEventListener('focusout',event=>{if(editing&&event.target===editing.input)finishEdit();},signal);
    return Object.freeze({render,open:()=>render(true),close:()=>{if(editing){editing.canceled=false;editing.input.blur();}},dispose:()=>abort.abort()});
  }
  window.DesktopMossGrid=Object.freeze({create,MODES:Object.freeze(['storyboard']),SHAPES,partition,cells,resizeGrid,transpose,movePanel});
})();

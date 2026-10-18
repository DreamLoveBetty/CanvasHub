// Area-control geometry + its canvas editor. No inference, uploads or model state.
(function(){
  const TYPE='krea2_control',PROFILE='editutils-area-v1';
  const PRESETS=Object.freeze({flat:.0149,small:.0294,medium:.0322,large:.0718,huge:.1395,gigantic:.1650});
  const labels={flat:'平坦',small:'小',medium:'中',large:'大',huge:'较大',gigantic:'特大'};
  const clamp=(value,low,high,fallback)=>Number.isFinite(Number(value))?Math.max(low,Math.min(high,Number(value))):fallback;
  const initial=()=>[.42,.58].map(cx=>({cx,cy:.48,rx:Math.sqrt(.0322/(2*Math.PI)),ry:Math.sqrt(.0322/(2*Math.PI)),angle:0}));
  function normalize(node){
    if(node.type!==TYPE)return node;
    node.width=390;node.height=528;
    node.circles=(Array.isArray(node.circles)&&node.circles.length?node.circles:initial()).slice(0,2).map(c=>({
      cx:clamp(c?.cx,0,1,.5),cy:clamp(c?.cy,0,1,.5),rx:clamp(c?.rx,.001,1,.08),ry:clamp(c?.ry,.001,1,.08),angle:clamp(c?.angle,-180,180,0)}));
    node.selectedMarker=Math.round(clamp(node.selectedMarker,0,node.circles.length-1,0));
    node.guideVisible=node.guideVisible!==false;return node;
  }
  function applyPreset(node,name){
    if(!PRESETS[name])return;normalize(node);
    const area=node.circles.reduce((total,c)=>total+Math.PI*c.rx*c.ry,0);
    const scale=Math.sqrt(PRESETS[name]/area);
    node.circles.forEach(c=>{c.rx=Math.min(1,c.rx*scale);c.ry=Math.min(1,c.ry*scale);});
  }
  const request=node=>({profile:PROFILE,circles:node.circles.map(c=>({...c}))});
  const ICON='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="2" y="3" width="20" height="18" rx="3"/><ellipse cx="9" cy="12" rx="3" ry="4"/><ellipse cx="16" cy="12" rx="3" ry="4"/></svg>';
  const MENU_ITEM={type:TYPE,title:'Krea 2 区域控制',subtitle:'绘制控制图 · 实验性',icon:ICON};
  function create({getCanvas,getNodeState,getNodeElement,getImageReferences,saveState}={}){
    const sessions=new Map(),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const live=s=>getNodeState(s.id)===s.node&&getNodeElement(s.id)===s.el;
    const targets=s=>(getCanvas().edges||[]).filter(e=>e.from===s.id).map(e=>getNodeState(e.to)).filter(n=>n?.type==='krea2');
    function dimensions(s){const target=targets(s)[0];return{width:target?.imageWidth||832,height:target?.imageHeight||1248};}
    function nodeHtml(node){normalize(node);return `<section class="desk-node desk-node--krea2-control desk-glass" data-node-id="${esc(node.id)}" aria-label="Krea 2 区域控制节点">
      <header class="desk-node__header" data-node-drag-handle><div><p class="desk-node__eyebrow">控制图 · 实验性</p><h2>Krea 2 区域控制</h2></div><button type="button" class="desk-node-delete" data-node-delete aria-label="删除区域控制节点">删</button></header>
      <button class="desk-port desk-port--in" data-port="in" data-node-id="${esc(node.id)}" aria-label="连接辅助底图，不参与生成"></button><button class="desk-port desk-port--out" data-port="out" data-node-id="${esc(node.id)}" aria-label="连接 Krea2 区域控制输入"></button>
      <div class="desk-krea2-control__body" data-node-drag-ignore>
        <div class="desk-krea2-control__presets">${Object.keys(PRESETS).map(key=>`<button type="button" class="desk-button" data-area-preset="${key}" title="标记面积 ${(PRESETS[key]*100).toFixed(2)}%">${labels[key]}</button>`).join('')}</div>
        <div class="desk-krea2-control__stage"><svg data-area-canvas aria-label="拖动椭圆移动，拖动手柄缩放或旋转" role="img"></svg></div>
        <div class="desk-krea2-control__fields"><label><span>标记</span><select class="desk-select" data-area-marker></select></label><label><span>面积 %</span><input class="desk-number" type="number" min="0.01" max="100" step="0.1" data-area-value="area"></label><label><span>旋转 °</span><input class="desk-number" type="number" min="-180" max="180" step="1" data-area-value="angle"></label></div>
        <div class="desk-krea2-control__actions"><label class="desk-switch"><input type="checkbox" data-area-guide ${node.guideVisible?'checked':''}><span></span><em>辅助底图</em></label><button type="button" class="desk-button" data-area-add>＋ 标记</button><button type="button" class="desk-button" data-area-remove>移除</button><button type="button" class="desk-button" data-area-reset>重置</button></div>
        <small data-area-status></small><small>底图仅辅助定位，不参与生成；面积预设不是局部蒙版。</small>
      </div></section>`;}
    function paint(s){
      if(!live(s))return;const node=normalize(s.node),{width:w,height:h}=dimensions(s),svg=s.svg;
      const r=(getImageReferences?.(s.id)||[])[0],guide=r&&(r.base64||r.imageData||r.imageUrl||r.url);
      svg.setAttribute('viewBox',`0 0 ${w} ${h}`);
      const knob=Math.max(w,h)*.018;
      svg.innerHTML=`<rect width="${w}" height="${h}" fill="black"/>${guide&&node.guideVisible?`<image href="${esc(guide)}" width="${w}" height="${h}" preserveAspectRatio="none" opacity=".32"/>`:''}`+
        node.circles.map((c,i)=>`<g data-area-index="${i}" transform="translate(${c.cx*w} ${c.cy*h}) rotate(${c.angle})"><ellipse data-area-handle="move" rx="${c.rx*w}" ry="${c.ry*h}" fill="#FADBAE"/>${i===node.selectedMarker?`<ellipse class="desk-krea2-control__selection" rx="${c.rx*w}" ry="${c.ry*h}"/><rect data-area-handle="rx" x="${c.rx*w-knob/2}" y="${-knob/2}" width="${knob}" height="${knob}"/><rect data-area-handle="ry" x="${-knob/2}" y="${c.ry*h-knob/2}" width="${knob}" height="${knob}"/><circle data-area-handle="angle" cx="0" cy="${-c.ry*h-knob*2}" r="${knob/2}"/>`:''}</g>`).join('');
      const selected=node.circles[node.selectedMarker],selector=s.el.querySelector('[data-area-marker]');
      selector.innerHTML=node.circles.map((_,i)=>`<option value="${i}"${i===node.selectedMarker?' selected':''}>标记 ${i+1}</option>`).join('');
      s.el.querySelector('[data-area-value="area"]').value=(Math.PI*selected.rx*selected.ry*100).toFixed(2);
      s.el.querySelector('[data-area-value="angle"]').value=Math.round(selected.angle);
      s.el.querySelector('[data-area-add]').disabled=node.circles.length>=2;
      s.el.querySelector('[data-area-remove]').disabled=node.circles.length<=1;
      const sizes=new Set(targets(s).map(n=>`${n.imageWidth}×${n.imageHeight}`));
      const status=s.el.querySelector('[data-area-status]');status.textContent=`${w} × ${h} · 标记面积合计 ${(node.circles.reduce((v,c)=>v+Math.PI*c.rx*c.ry,0)*100).toFixed(2)}%${sizes.size>1?' · 多目标画幅不同，预览以首个为准':sizes.size?' · 跟随 Krea2 画幅':' · 请连接 Krea2'}（重叠按并集绘制）`;
      status.title=status.textContent;
      if(!s.drag)window.DesktopSelect?.refreshAll?.();
    }
    function commit(s){paint(s);saveState?.();}
    function point(s,event){const rect=s.svg.getBoundingClientRect(),d=dimensions(s),scale=Math.min(rect.width/d.width,rect.height/d.height);return{x:(event.clientX-rect.left-(rect.width-d.width*scale)/2)/scale,y:(event.clientY-rect.top-(rect.height-d.height*scale)/2)/scale,...d};}
    function mount(node){
      const el=getNodeElement(node.id);if(!el||sessions.has(node.id))return;
      const s={id:node.id,node,el,svg:el.querySelector('[data-area-canvas]'),abort:new AbortController(),drag:null};sessions.set(node.id,s);const options={signal:s.abort.signal};
      el.addEventListener('click',event=>{
        const button=event.target.closest('button');if(!button)return;
        if(button.dataset.areaPreset){applyPreset(node,button.dataset.areaPreset);commit(s);}
        else if(button.hasAttribute('data-area-add')&&node.circles.length<2){node.circles.push({...node.circles[0],cx:Math.min(.9,node.circles[0].cx+.2)});node.selectedMarker=1;commit(s);}
        else if(button.hasAttribute('data-area-remove')&&node.circles.length>1){node.circles.splice(node.selectedMarker,1);node.selectedMarker=0;commit(s);}
        else if(button.hasAttribute('data-area-reset')){node.circles=initial();node.selectedMarker=0;commit(s);}
      },options);
      el.addEventListener('change',event=>{
        const input=event.target,c=node.circles[node.selectedMarker];
        if(input.hasAttribute('data-area-guide'))node.guideVisible=input.checked;
        else if(input.hasAttribute('data-area-marker'))node.selectedMarker=Number(input.value);
        else if(input.dataset.areaValue==='angle')c.angle=Number(input.value);
        else if(input.dataset.areaValue==='area'){const scale=Math.sqrt(clamp(input.value,.01,100,1)/100/(Math.PI*c.rx*c.ry));c.rx*=scale;c.ry*=scale;}
        else return;commit(s);
      },options);
      s.svg.addEventListener('pointerdown',event=>{
        if(event.button!==0)return;event.stopPropagation();event.preventDefault();
        const group=event.target.closest('[data-area-index]');if(!group)return;
        node.selectedMarker=Number(group.dataset.areaIndex);
        s.drag={pointer:event.pointerId,handle:event.target.dataset.areaHandle||'move',start:point(s,event),circle:{...node.circles[node.selectedMarker]}};
        s.svg.setPointerCapture(event.pointerId);paint(s);
      },options);
      s.svg.addEventListener('pointermove',event=>{
        if(!s.drag||s.drag.pointer!==event.pointerId||!live(s))return;event.stopPropagation();
        const p=point(s,event),d=s.drag,c=node.circles[node.selectedMarker],a=d.circle;
        if(d.handle==='move'){c.cx=a.cx+(p.x-d.start.x)/p.width;c.cy=a.cy+(p.y-d.start.y)/p.height;}
        else{const x=p.x-a.cx*p.width,y=p.y-a.cy*p.height,t=a.angle*Math.PI/180;
          if(d.handle==='rx')c.rx=Math.abs(x*Math.cos(t)+y*Math.sin(t))/p.width;
          if(d.handle==='ry')c.ry=Math.abs(-x*Math.sin(t)+y*Math.cos(t))/p.height;
          if(d.handle==='angle')c.angle=((Math.atan2(y,x)*180/Math.PI+90+540)%360)-180;
        }paint(s);
      },options);
      const end=event=>{if(s.drag?.pointer!==event.pointerId)return;s.drag=null;if(s.svg.hasPointerCapture(event.pointerId))s.svg.releasePointerCapture(event.pointerId);commit(s);};
      s.svg.addEventListener('pointerup',end,options);s.svg.addEventListener('pointercancel',end,options);
      paint(s);
    }
    function dispose(id){const s=sessions.get(id);if(s){s.abort.abort();sessions.delete(id);}}
    function reconcile(){sessions.forEach(s=>{if(!live(s))dispose(s.id);});Object.values(getCanvas().nodes||{}).filter(n=>n.type===TYPE).forEach(mount);sessions.forEach(paint);}
    const graphChanged=()=>sessions.forEach(paint);
    return{nodeHtml,reconcile,dispose,disposeAll:()=>[...sessions.keys()].forEach(dispose),graphChanged,
      connections:{targets:{image:[TYPE]},policy:(a,b)=>a?.type==='image'&&b?.type===TYPE?{inputRole:'control_guide',outputRole:'image',single:true}:null,changed:graphChanged,removed:graphChanged}};
  }
  window.DesktopKrea2Control=Object.freeze({TYPE,PROFILE,PRESETS,normalize,applyPreset,request,ICON,MENU_ITEM,create});
})();

// Canvas port adapter. Preserve structured prompt segments and existing undo/save semantics.
(function () {
  function create({getCanvas,getNodeState,getNodeElement,getTextNodes,materializeText,cloneDocument,
    setDocument,addNode,removeNode,connectNodes,getController,getSelectedIds}) {
    function listTargets() {
      const selected=new Set(getSelectedIds());
      return Object.values(getCanvas().nodes||{}).filter(node=>['krea2','qwen21'].includes(node.type))
        .sort((a,b)=>Number(selected.has(b.id))-Number(selected.has(a.id)))
        .map(node=>({id:node.id,engine:node.type,label:`${selected.has(node.id)?'当前选择 · ':''}${node.type==='krea2'?'Krea 2':'Qwen 2.1'} · ${node.id.slice(-6)}`}));
    }
    function target(id) {
      const node=getNodeState(id);
      if(!node||!['krea2','qwen21'].includes(node.type))throw new Error('目标节点已不存在或不兼容');
      return node;
    }
    function listTextTargets(id) {target(id);return (getTextNodes(id)||[]).map(node=>({id:node.id,label:node.alias||node.title||materializeText(node).slice(0,60)||`文本 ${node.id.slice(-6)}`}));}
    async function addToNode(id,identity) {const node=target(id);return getController(node.type).addLoRA(id,identity);}
    function insertTriggers(id,textId,words) {
      const node=target(id);
      if(!getController(node.type).canEdit(id))throw new Error('节点正在运行或准备模型，请稍后修改提示词');
      if(!Array.isArray(words)||!words.length)throw new Error('没有选择触发词');
      let text;
      if(textId){text=(getTextNodes(id)||[]).find(value=>value.id===textId);if(!text)throw new Error('目标文本已断开连接，请重新选择');}
      else{
        if((getTextNodes(id)||[]).length)throw new Error('节点已有文本输入，请选择目标文本');
        const created=addNode('text',{x:node.x-380,y:node.y});text=getNodeState(created);
        if(!text)throw new Error('新建文本节点失败');
        connectNodes(created,id,{quiet:true});
        if(!(getCanvas().edges||[]).some(edge=>edge.from===created&&edge.to===id)){removeNode(created);throw new Error('文本节点连接失败');}
      }
      const {suffix}=window.DesktopLoRAData.appendWords(materializeText(text),words);
      if(!suffix)return false;
      const document=cloneDocument(text.promptDocument,text.text||'');
      const last=document.segments.at(-1);
      if(last?.type==='text')last.text+=suffix;else document.segments.push({type:'text',text:suffix});
      setDocument(getNodeElement(text.id),text,document);
      return true;
    }
    return Object.freeze({listTargets,listTextTargets,addToNode,insertTriggers});
  }
  window.DesktopCanvasLoRA=Object.freeze({create});
})();

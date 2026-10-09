// Owns only video-control sessions/jobs; canvas graph, video display and status are ports.
(function () {
  function create({ model, api, view, getCanvas, getNodeState, getNodeElement, addNode, connectNodes,
    refreshVideoNode, saveState, reportStatus }) {
    const sessions=new Map(), submissions=new Set();
    const live=s=>sessions.get(s.id)===s && getNodeState(s.id)===s.node && getNodeElement(s.id)===s.el;
    const sourceFor=node=>(getCanvas().edges || []).filter(edge=>edge.to===node.id).map(edge=>getNodeState(edge.from)).find(n=>n?.type==='video');
    function feedback(s, error='', force=false) {
      if (!live(s)) return;
      if (error) s.noticeError=error;
      error=s.noticeError || '';
      const job=s.job, state=error?'failed':s.pending?'submitting':s.node.status, label=model.labels[state] || '就绪';
      const summary=error?'操作失败，点击查看详情':model.stageLabel(job?.stage) || label;
      const value={message:`视频控制 · ${summary}`,tone:error || ['failed','interrupted'].includes(state)?'error':state==='succeeded'?'success':'info',task:{
        task_id:job?.id || '',node_id:s.id,node_title:`ReShot 视频控制 · ${s.id.slice(-6)}`,operation_label:'视频控制',
        status:state==='running'?'processing':state==='cancelled'?'canceled':state,status_label:label,
        provider_route:'reshot_local',detail_title:'视频控制日志',stage:summary,progress_text:summary,
        raw_detail:JSON.stringify({engine:'ReShot',control:job?.spec?.control || s.node.control,status:state,stage:job?.stage || summary,message:error || job?.progress_message || label,events:job?.events || []},null,2)+(error || job?.error ? '\n\n'+(error || job.error):'') }};
      const key=JSON.stringify(value); if (!force && key===s.lastFeedback) return;
      s.lastFeedback=key; reportStatus(value); if(error) paint(s);
    }
    function paint(s) {
      if (!live(s)) return;
      view.paint(s.el,s.noticeError?{...s.node,status:'failed'}:s.node,s.job,Boolean(s.pending));
      const source=sourceFor(s.node);
      s.el.querySelector('[data-control-source]').textContent=source?.mediaUrl ? (source.mediaName || '已连接视频') : '连接视频节点，或导入本地视频';
    }
    function position(node, before=false) {
      const x=before?node.x-440:node.x+node.width+60;
      let y=node.y;
      const nodes=Object.values(getCanvas().nodes);
      for (let pass=0;pass<=nodes.length;pass++) {
        const hits=nodes.filter(n=>x<n.x+n.width+20 && x+400+20>n.x && y<n.y+n.height+20 && y+260+20>n.y);
        if (!hits.length) break;
        y=Math.max(...hits.map(n=>n.y+n.height))+40;
      }
      return {x:x+200,y:y+130};
    }
    function publish(s, job, onlyTarget=null) {
      if (!live(s) || s.node.jobId!==job.id || (!onlyTarget && s.node.resultJobId===job.id)) return;
      const artifact=job.artifacts?.find(f=>f.name==='result/control.mp4');
      if (!artifact) throw new Error('任务完成但未返回控制视频');
      const url=api.sourceUrl(artifact.url);
      let targets=(getCanvas().edges || []).filter(e=>e.from===s.id).map(e=>getNodeState(e.to)).filter(n=>n?.type==='video');
      if (onlyTarget) targets=targets.filter(n=>n.id===onlyTarget);
      if (!targets.length && onlyTarget) return;
      if (!targets.length) {
        const id=addNode('video',position(s.node));
        s.publishing=true; try { connectNodes(s.id,id,{quiet:true}); } finally { s.publishing=false; }
        targets=[getNodeState(id)];
      }
      targets.forEach(target=> {
        Object.assign(target,{mediaUrl:url,mediaName:`${job.spec.control}-control.mp4`,mimeType:'video/mp4',status:'succeeded',
          sourceTaskId:job.id,mediaWidth:job.media?.width || 0,mediaHeight:job.media?.height || 0,fps:job.media?.fps || 24,
          fileSize:artifact.file_size,videoControlAssetId:'',durationSeconds:0,
          controlMetadata:{kind:job.spec.control,engine:job.engine,sourceAssetId:job.spec.asset_id}});
        refreshVideoNode(target.id);
      });
      s.node.resultJobId=job.id; saveState(); graphChanged();
    }
    async function poll(s) {
      clearTimeout(s.timer); const id=s.node.jobId, epoch=s.epoch || 0;
      if (!id || !live(s)) return;
      try {
        const job=await api.job(id);
        if (!live(s) || s.node.jobId!==id || (s.epoch || 0)!==epoch) return;
        s.noticeError=''; s.job=job; s.node.status=job.status;
        if (job.status==='succeeded') publish(s,job);
        paint(s); feedback(s); saveState();
        if (model.active(job.status)) s.timer=setTimeout(()=>poll(s),1200);
      } catch (error) {
        if (!live(s) || s.node.jobId!==id || (s.epoch || 0)!==epoch) return;
        feedback(s,error.message); paint(s);
        if (model.active(s.node.status)) s.timer=setTimeout(()=>poll(s),3000);
      }
    }
    async function cancel(s) {
      if (s.pending) { s.pending.cancelled=true; if(s.pending.jobId) await api.cancel(s.pending.jobId); }
      else if (s.node.jobId && model.active(s.node.status)) await api.cancel(s.node.jobId);
      if (live(s)) { s.node.status='cancelling'; paint(s); if (!s.pending) poll(s); }
    }
    async function run(id) {
      const s=sessions.get(id); if(!s || s.pending || model.active(s.node.status)) return;
      s.noticeError='';
      const source=sourceFor(s.node);
      if (!source?.mediaUrl) { feedback(s,'请先连接有内容的视频节点'); return; }
      s.epoch=(s.epoch || 0)+1; s.noticeError='';
      const op={s,cancelled:false,jobId:''}; submissions.add(op); s.pending=op; s.job=null;
      const snapshot=model.request(s.node,''), sourceSnapshot={...source};
      paint(s); feedback(s);
      try {
        let assetId=sourceSnapshot.videoControlAssetUrl===sourceSnapshot.mediaUrl ? sourceSnapshot.videoControlAssetId : null;
        if (!assetId) {
          const blob=await api.blob(sourceSnapshot.mediaUrl);
          if (op.cancelled || !live(s)) return;
          const asset=await api.upload(blob,sourceSnapshot.mediaName);
          assetId=asset.asset_id;
          if (getNodeState(source.id)===source && source.mediaUrl===sourceSnapshot.mediaUrl) { source.videoControlAssetId=assetId; source.videoControlAssetUrl=sourceSnapshot.mediaUrl; saveState(); }
        }
        if (op.cancelled || !live(s)) return;
        const job=await api.submit({...snapshot,asset_id:assetId}); op.jobId=job.id;
        if (op.cancelled || !live(s)) { await api.cancel(job.id); return; }
        s.node.jobId=job.id; s.node.status=job.status; s.node.resultJobId=''; s.job=job;
        saveState();
      } catch(error) {
        if (live(s)) { s.pending=null; s.node.status=op.cancelled?'cancelled':'failed'; feedback(s,error.message); }
      } finally {
        submissions.delete(op); if(s.pending===op) s.pending=null;
        if(live(s)) {
          if(op.cancelled) { s.node.status='cancelled'; feedback(s); }
          paint(s); saveState();
          if(op.jobId && !op.cancelled) poll(s);
        }
      }
    }
    async function importFile(s,file) {
      if (!file || s.pending || model.active(s.node.status)) return;
      s.noticeError='';
      const op={s,cancelled:false}; s.pending=op; submissions.add(op); paint(s);
      try {
        const asset=await api.upload(file,file.name);
        if(!live(s) || op.cancelled) return;
        const id=addNode('video',position(s.node,true));
        Object.assign(getNodeState(id),{mediaUrl:`/api/video_control/source?id=${encodeURIComponent(asset.asset_id)}`,
          mediaName:file.name,videoControlAssetUrl:`/api/video_control/source?id=${encodeURIComponent(asset.asset_id)}`,videoControlAssetId:asset.asset_id,status:'succeeded',fps:24});
        refreshVideoNode(id); connectNodes(id,s.id,{quiet:true}); saveState();
      } catch(error) { feedback(s,error.message); }
      finally { submissions.delete(op); if(s.pending===op) s.pending=null; if(live(s) && op.cancelled) { s.node.status='cancelled'; feedback(s); saveState(); } paint(s); }
    }
    function mount(node) {
      const el=getNodeElement(node.id); if (!el || sessions.has(node.id)) return;
      model.normalize(node); const s={id:node.id,node,el,abort:new AbortController()}; sessions.set(node.id,s);
      const options={signal:s.abort.signal};
      el.addEventListener('click',event=> {
        if(event.target.closest('[data-control-run]')) run(s.id);
        if(event.target.closest('[data-control-import]')) el.querySelector('[data-control-file]').click();
      },options);
      el.addEventListener('change',event=> {
        const input=event.target;
        if(input.matches('[data-control-file]')) { const file=input.files?.[0]; input.value=''; importFile(s,file); return; }
        const key=input.dataset.controlField;
        if(!key || s.pending || model.active(node.status)) return;
        node[key]=input.type==='checkbox'?input.checked:['maxRes','maxSeconds','cannyLow','cannyHigh'].includes(key)?Number(input.value):input.value;
        model.normalize(node); if(input.type!=='checkbox') input.value=String(node[key]); paint(s); saveState();
      },options);
      if (node.status==='submitting') node.status='idle';
      paint(s); if(node.jobId) poll(s);
    }
    function dispose(id, removed=false) {
      const s=sessions.get(id); if(!s) return;
      if(s.pending) s.pending.cancelled=true;
      if ((removed || getNodeState(id)!==s.node) && s.node.jobId && model.active(s.node.status)) api.cancel(s.node.jobId).catch(()=>{});
      sessions.delete(id); s.abort.abort(); clearTimeout(s.timer);
      // Persisted backend jobs keep running when navigating/reloading; resume on mount.
    }
    function disposeAll(removed=false) { [...sessions.keys()].forEach(id=>dispose(id,removed)); }
    function reconcile() {
      [...sessions.values()].forEach(s=> {if(!live(s)) dispose(s.id);});
      Object.values(getCanvas().nodes).filter(n=>n.type===model.TYPE).forEach(mount);
    }
    function graphChanged() { sessions.forEach(paint); }
    function connected(fromId,toId) {
      const s=sessions.get(fromId);
      if(s?.job?.status==='succeeded' && !s.pending && !s.publishing) {
        try { publish(s,s.job,toId); } catch(error) { feedback(s,error.message); }
      }
      graphChanged();
    }
    function getCancelableTasks() {
      const entries=[];
      sessions.forEach(s=> { if(s.pending || model.active(s.node.status)) entries.push({kind:'video_control',key:`video_control:${s.id}`,cancel:()=>cancel(s)}); });
      for(const op of submissions) if(!sessions.has(op.s.id)) entries.push({kind:'video_control',key:`video_control:pending:${op.s.id}`,cancel:async()=> {op.cancelled=true; if(op.jobId) await api.cancel(op.jobId);}});
      return entries;
    }
    return {nodeHtml:view.html,reconcile,dispose,disposeAll,run,graphChanged,getCancelableTasks,
      showStatus:id=> {const s=sessions.get(id); if(s?.job || s?.noticeError) feedback(s,'',true);},
      connections:{targets:model.targets,policy:model.policy,changed:connected,removed:graphChanged}};
  }
  window.DesktopCanvasVideoControl=Object.freeze({create});
})();

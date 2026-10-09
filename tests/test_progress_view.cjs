const test=require('node:test'),assert=require('node:assert/strict');
const {harness,Element}=require('./helpers/progress-harness.cjs');
const receipt=(extra={})=>({visible:true,running:true,taskId:'synthetic-task',percent:60,title:'正在采样 21 / 24',detail:'Qwen 2.1 · MLX',startedAt:1790910740,...extra});
const track=root=>root.querySelector('.desk-progress-material__track');

test('only intersecting active tracks allocate a renderer; all nodes share one RAF and clock',()=>{
 const h=harness(),roots=Array.from({length:12},()=>h.root());
 roots.forEach(r=>h.controller.update(r,receipt()));assert.equal(h.frames.size,0);assert.equal(h.renderers.length,0);
 roots.slice(0,3).forEach(r=>h.intersect(r));assert.equal(h.frames.size,1);assert.equal(h.timers.size,1);
 h.step();assert.equal(h.renderers.length,3);assert.equal(h.frames.size,1);
 roots.forEach(r=>h.intersect(r,false));assert.equal(h.frames.size,0);assert.equal(h.timers.size,0);
 h.controller.destroy();assert.ok(h.renderers.every(r=>r.destroyed));
});
test('true percent, stage and real elapsed are inside the track; unknown does not expose numeric ARIA',()=>{
 const h=harness(),root=h.root();h.controller.update(root,receipt());h.intersect(root);h.step();
 assert.equal(track(root).getAttribute('aria-valuenow'),'60');
 assert.equal(root.querySelector('.desk-progress-material__title').textContent,'正在采样 21 / 24');
 assert.equal(root.querySelector('.desk-progress-material__time').textContent,'已用时 00:10');
 h.seconds(3);assert.equal(root.querySelector('.desk-progress-material__time').textContent,'已用时 00:13');
 h.controller.update(root,receipt({percent:null,startedAt:0}));
 assert.equal(track(root).getAttribute('aria-valuenow'),null);
 assert.equal(root.querySelector('.desk-progress-material__value').textContent,'处理中');
 assert.equal(root.querySelector('.desk-progress-material__time').textContent,'用时 —');
 h.controller.destroy();
});
test('style/height/color switching does not restart task time, change numbers or hide legacy permanently',()=>{
 const h=harness(),root=h.root(),original=root.children[0];h.controller.update(root,receipt());h.intersect(root);h.step();
 for(const style of ['slosh','smoke','drops','bands','threads','diamond','grain']) {
  h.preferences({style,height:56,colors:{[style]:'#35D1C4'}});h.step();
  assert.equal(root.dataset.progressStyle,style);assert.equal(root.dataset.progressSize,'56');
  assert.equal(track(root).getAttribute('aria-valuenow'),'60');
  assert.equal(root.querySelector('.desk-progress-material__time').textContent,'已用时 00:10');
  assert.equal(h.renderers.at(-1).draws.at(-1).color,'#35D1C4');
 }
 h.preferences({style:'classic'});assert.equal(track(root),null);assert.equal(h.frames.size,0);assert.equal(h.timers.size,0);
 assert.equal(root.children[0],original);assert.ok(h.renderers[0].destroyed);
 h.preferences({style:'liquid',height:36});h.step();assert.equal(root.dataset.progressSize,'36');assert.equal(track(root).getAttribute('aria-valuenow'),'60');
 h.controller.destroy();
});
test('all terminal states release overlays, observers and backing stores immediately',()=>{
 const h=harness();for(const state of ['succeeded','failed','canceled','idle']) {
  const root=h.root();h.controller.update(root,receipt());h.intersect(root);h.step();
  h.controller.update(root,receipt({visible:false,running:false,title:state}));
  assert.equal(track(root),null);assert.ok(h.renderers.at(-1).destroyed);assert.equal(h.frames.size,0);assert.equal(h.timers.size,0);
  assert.ok(h.observers.every(o=>!o.targets.has(root)));
 }
 h.controller.destroy();
});
test('page visibility and reduced motion stop loops, resuming uses elapsed wall time not frame count',()=>{
 const h=harness(),root=h.root();h.controller.update(root,receipt());h.intersect(root);h.step();
 h.hidden(true);assert.equal(h.frames.size,0);assert.equal(h.timers.size,0);
 h.seconds(12);h.hidden(false);h.step();assert.equal(root.querySelector('.desk-progress-material__time').textContent,'已用时 00:22');
 h.reduce(true);h.step();assert.equal(h.frames.size,0);assert.equal(h.renderers[0].draws.at(-1).energy,0);
 assert.equal(h.timers.size,1);h.reduce(false);h.step();assert.equal(h.frames.size,1);
 h.controller.destroy();assert.equal(h.listeners.size,0);assert.equal(h.docListeners.size,0);
});
test('node resizing uses layout pixels and no layout reads on a steady draw',()=>{
 const h=harness(),root=h.root();h.controller.update(root,receipt());h.resize(root,640);h.intersect(root);h.step();
 assert.deepEqual(h.renderers[0].sizes,[[640,36]]);
 for(let i=0;i<20;i++)h.step();assert.equal(h.renderers[0].sizes.length,1);
 h.resize(root,820);h.step();assert.deepEqual(h.renderers[0].sizes.at(-1),[820,36]);h.controller.destroy();
});
test('node deletion and workflow clear release even floating roots owned by the removed node',()=>{
 const h=harness(),node=new Element('section'),root=h.root();h.controller.update(root,receipt(),node);h.intersect(root);h.step();
 h.controller.releaseWithin(node);assert.equal(track(root),null);assert.equal(h.frames.size,0);
 const r=h.root();h.controller.update(r,receipt());h.intersect(r);h.step();h.controller.clear();assert.equal(h.frames.size,0);
 h.controller.update(r,receipt());h.intersect(r);h.step();assert.ok(track(r));h.controller.destroy();
});
test('H3 polling replacement moves the same canvas and preserves the flowing phase',()=>{
 const h=harness(),root=h.root();h.controller.update(root,receipt());h.intersect(root);for(let i=0;i<60;i++)h.step();
 const canvas=root.querySelector('canvas'),phase=h.renderers[0].draws.at(-1).flowPhase,next=h.root();root.connected=false;
 h.controller.replaceRoot(root,next);h.controller.update(next,receipt({percent:61}));h.intersect(next);h.step();
 assert.equal(next.querySelector('canvas'),canvas);assert.equal(h.renderers.length,1);
 assert.ok(h.renderers[0].draws.at(-1).flowPhase>phase);assert.equal(track(next).getAttribute('aria-valuenow'),'61');h.controller.destroy();
});
test('queued-to-running receipt retargets gradually; a different job does not inherit old fill',()=>{
 const h=harness(),r=h.root();h.controller.update(r,receipt());h.intersect(r);h.step();
 h.controller.update(r,receipt({percent:90}));h.step();assert.ok(h.renderers[0].draws.at(-1).value<.9);
 h.controller.update(r,receipt({taskId:'next-task',percent:2}));h.step();assert.equal(h.renderers[0].draws.at(-1).value,.02);h.controller.destroy();
});
test('fair frame budget does not starve later nodes or allocate per-node animation loops',()=>{
 const h=harness({drawCost:5}),roots=Array.from({length:20},()=>h.root());
 roots.forEach(r=>{h.controller.update(r,receipt());h.intersect(r);});
 for(let i=0;i<40;i++){h.step(34);assert.equal(h.frames.size,1);}
 assert.equal(h.renderers.length,20);assert.ok(h.renderers.every(r=>r.draws.length>=2));h.controller.destroy();
});
test('Canvas2D unavailable falls back to a readable static track without a failing loop',()=>{
 const h=harness({failCanvas:true}),r=h.root();h.controller.update(r,receipt());h.intersect(r);h.step();
 assert.equal(h.frames.size,0);assert.match(track(r).style.background,/60%/);assert.equal(r.querySelector('canvas').hidden,true);h.controller.destroy();
});
test('one failed renderer falls back without interrupting other active nodes',()=>{
 const h=harness(),bad=h.root(),good=h.root();
 for(const r of [bad,good]){h.controller.update(r,receipt());h.intersect(r);}h.step();
 const failed=h.renderers[0],healthy=h.renderers[1],before=healthy.draws.length;
 failed.draw=()=>{throw Error('context lost');};
 h.step();assert.ok(failed.destroyed);assert.equal(bad.querySelector('canvas').hidden,true);
 assert.match(track(bad).style.background,/60%/);assert.ok(healthy.draws.length>before);
 assert.equal(h.frames.size,1);h.controller.destroy();
});
test('classic allocates no canvas, retains its chrome and restores original fill after color reset',()=>{
 const h=harness({style:'classic'}),r=h.root(),bar=r.querySelector('[data-progress-bar]');bar.style.background='original';
 h.controller.update(r,receipt());h.intersect(r);h.step();assert.equal(h.renderers.length,0);assert.equal(track(r),null);
 h.preferences({colors:{classic:'#35D1C4'}});assert.match(bar.style.background,/linear-gradient/);
 h.preferences({colors:{}});assert.equal(bar.style.background,'original');h.controller.destroy();
});
test('legacy music progress semantics are not nested or replaced by the material',()=>{
 const h=harness(),r=h.root();r.setAttribute('role','progressbar');r.setAttribute('aria-label','音乐生成进度');r.setAttribute('aria-valuenow','50');
 h.controller.update(r,receipt({percent:50,valueLabel:'阶段 50%'}));h.intersect(r);h.step();
 assert.equal(track(r).getAttribute('role'),'presentation');assert.equal(track(r).getAttribute('aria-valuenow'),null);
 assert.equal(track(r).getAttribute('aria-live'),'off');assert.equal(r.getAttribute('aria-valuenow'),'50');
 h.preferences({style:'classic'});assert.equal(r.getAttribute('role'),'progressbar');assert.equal(r.getAttribute('aria-label'),'音乐生成进度');h.controller.destroy();
});

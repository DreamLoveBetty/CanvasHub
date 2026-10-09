const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const scope = {window:{}};
for(const file of ['desktop-topaz-video-pipeline.js','desktop-topaz-video-inspector.js','desktop-topaz-video-model.js'])
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../frontend/scripts',file),'utf8'),scope);
const pipeline=scope.window.DesktopTopazVideoPipeline;
const status={processing_ready:true,encoding:{codecs:['h264','hevc','hevc10']},capabilities:{
  interpolation:{available:true,models:[{id:'chf-3',label:'Chronos Fast',available:true}]},
  denoise:{available:true},hdr:{available:true},motion_deblur:{available:true},stabilization:{available:true,full_frame:true,jitter:true}}};
test('old workflows gain disabled filters and retain legacy payload shape',()=>{
  const node=pipeline.normalize({}); assert.equal(node.enhancementEnabled,true);
  assert.equal(node.videoFilters.hdr.enabled,false);assert.equal(JSON.stringify(pipeline.request(node,null)),'{}');
});
test('processing is persistent node state, requests translate keys only at boundary',()=>{
  const node=pipeline.normalize({});pipeline.patch(node,{group:'stabilization',key:'enabled',value:true},status);
  pipeline.patch(node,{group:'stabilization',key:'rollingShutter',value:true},status);
  const body=pipeline.request(node,status);assert.equal(body.filters.stabilization.rolling_shutter,true);
  assert.equal(body.filters.stabilization.rollingShutter,undefined);
  assert.equal(pipeline.normalize(JSON.parse(JSON.stringify(node))).videoFilters.stabilization.enabled,true);
});
test('HDR activation selects ten-bit output and blocks invalid later codec changes',()=>{
  const node=pipeline.normalize({});pipeline.patch(node,{group:'hdr',key:'enabled',value:true},status);
  assert.equal(node.encodingOptions.codec,'hevc10');assert.equal(pipeline.request(node,status).filters.hdr.model,'hyp-2');
  assert.throws(()=>pipeline.patch(node,{group:'encoding',key:'codec',value:'h264'},status),/HDR/);
});
test('lost capability does not silently disable persisted filters or submit fake tasks',()=>{
  const node=pipeline.normalize({});pipeline.patch(node,{group:'interpolation',key:'enabled',value:true},status);
  assert.throws(()=>pipeline.request(node,{...status,capabilities:{}}),/资源/);
  assert.equal(node.videoFilters.interpolation.enabled,true);
  assert.throws(()=>pipeline.patch(node,{group:'hdr',key:'enabled',value:true},{}),/就绪/);
});
test('effective output duration and frame rate include slow motion',()=>{
  const node=pipeline.normalize({videoFilters:{interpolation:{enabled:true,fps:60,slowmo:4}}});
  assert.equal(pipeline.timing(node,{duration:2,fps:24}).duration,8);
  assert.equal(pipeline.timing(node,{duration:2,fps:24}).fps,60);
});
test('invalid imported numbers cannot cross the API boundary',()=>{
  for(const value of [-1,121,NaN]){const node=pipeline.normalize({});node.videoFilters.interpolation={enabled:true,model:'chf-3',fps:value,slowmo:1,rdt:.01};assert.throws(()=>pipeline.request(node,status));}
  const node=pipeline.normalize({});node.encodingOptions.bitrateMbps=-1;assert.throws(()=>pipeline.request(node,status),/编码/);
});
test('invalid encoding edits do not overwrite the last valid workflow state',()=>{
  const node=pipeline.normalize({});
  for(const value of [-1,201,NaN]) assert.throws(()=>pipeline.patch(node,{group:'encoding',key:'bitrateMbps',value},status),/编码/);
  assert.equal(node.encodingOptions.bitrateMbps,0);
  pipeline.patch(node,{group:'denoise',key:'enabled',value:true},status);
  pipeline.patch(node,{group:'denoise',key:'noise',value:.4},status);
  assert.equal(pipeline.request(node,status).filters.denoise.noise,.4);
});
test('inspector renders actual editable independent controls and no fake placeholders',()=>{
  const inspector=scope.window.DesktopTopazVideoInspector.create({pipeline,escapeHtml:s=>String(s).replaceAll('<','&lt;')});
  const node=pipeline.normalize({});const html=inspector.filters(node,status);
  for(const group of ['interpolation','hdr','stabilization','motionDeblur'])assert.ok(html.includes(`data-tvwb-feature="${group}"`));
  assert.doesNotMatch(html,/运行时未接入/);assert.match(inspector.output(node,{width:256,height:256,fps:24,duration:1},status),/data-tvwb-key="codec"/);
  assert.equal(inspector.change({dataset:{tvwbProcessing:'interpolation',tvwbKey:'fps'},type:'number',value:'60'}).processing.value,60);
});

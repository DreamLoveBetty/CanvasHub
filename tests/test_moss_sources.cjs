const {test}=require('node:test');
const assert=require('node:assert/strict');
const {load,plain,textNode,ports}=require('./moss_frontend_fixture.cjs');
const M=load(['desktop-moss-model.js']).window.DesktopMossModel;
const ref=nodeId=>({kind:'text_node',nodeId});
const layout=(items,extra={})=>M.normalize({type:'moss',mode:'layout',prompt:'全局',freeDraft:{items},...extra});

test('全局、文字、caption 各按自己的字段解析，不盲拼',()=>{
  const node=layout([{id:'t',label:'text',caption:'标题字',textSource:ref('a'),bbox:[0,0,9,9]},{id:'o',label:'object',captionSource:ref('b'),bbox:[0,0,9,9]}],{promptSource:ref('c')});
  const unused=textNode('z','不该出现');
  const input=M.resolveTextSources(node,ports(textNode('a','文案'),textNode('b','一只猫'),textNode('c','风格'),unused));
  assert.equal(input.prompt,'风格');
  const [t,o]=input.layoutDraft.items;
  assert.equal(t.text,'文案');assert.equal(t.caption,'标题字');assert.equal(o.caption,'一只猫');
  assert.deepEqual(plain(input.textSources.map(item=>[item.targetId,item.field])),[['global','prompt'],['t','text'],['o','caption']]);
  assert.doesNotMatch(JSON.stringify(input),/不该出现/);
  assert.equal(input.textSources[0].contentHash,M.sha256('风格'));
});

test('草稿送模型时剥离 Source 对象与视图字段',()=>{
  const node=layout([{id:'o',label:'object',caption:'猫',captionSource:{kind:'inline'},bbox:[0,0,9,9]}]);
  const input=M.resolveTextSources(node,ports());
  assert.deepEqual(plain(input.layoutDraft),{items:[{id:'o',label:'object',caption:'猫',bbox:[0,0,9,9]}]});
  assert.doesNotMatch(JSON.stringify(input.layoutDraft),/Source|settingsExpanded/);
});

test('同源复用只算一个依赖，两份草稿都计入',()=>{
  const node=layout([{id:'o',label:'object',captionSource:ref('a'),bbox:[0,0,9,9]}],{promptSource:ref('a'),gridDraft:{rows:1,cols:3,panels:[{id:'p',captionSource:ref('b')}]}});
  assert.deepEqual(plain(M.textDependencies(node)),['a','b']);
  assert.deepEqual(plain(M.missingDependencies(node,['a'])),['b']);
});

test('只解析活动模式：未激活草稿失效不阻止',()=>{
  const node=layout([{id:'o',label:'object',captionSource:ref('gone'),bbox:[0,0,9,9]}],{prompt:'普通'});
  node.mode='text';
  const input=M.resolveTextSources(node,ports());
  assert.deepEqual(plain(input.issues),[]);assert.equal(input.layoutDraft,null);assert.equal(input.prompt,'普通');
});

test('全局源失效仍阻止当前提交，不回落到内联备用值',()=>{
  const input=M.resolveTextSources(M.normalize({type:'moss',prompt:'旧备用',promptSource:ref('gone')}),ports());
  assert.equal(input.prompt,'');assert.equal(input.issues[0].reason,'missing');assert.equal(input.issues[0].nodeId,'gone');
});

test('不兼容、含图片引用、空文本都拒绝',()=>{
  const cases=[[{id:'x',type:'image'},'incompatible'],[textNode('x','文字',{promptDocument:{segments:[{type:'image_reference'}]}}),'image_reference'],[textNode('x','  '),'empty']];
  for(const [source,reason] of cases){
    const input=M.resolveTextSources(M.normalize({type:'moss',promptSource:ref('x')}),ports(source));
    assert.equal(input.issues[0].reason,reason);assert.deepEqual(plain(input.textSources),[]);
  }
});

test('分镜按 panel_id 解析，空 Source 走内联',()=>{
  const node=M.normalize({type:'moss',mode:'storyboard',gridDraft:{rows:1,cols:3,margin:8,gutter:4,panels:[{id:'b',captionSource:ref('a')},{id:'a',caption:'内联'},{id:'c',caption:'三'}]}});
  const input=M.resolveTextSources(node,ports(textNode('a','绑定')));
  assert.deepEqual(plain(input.layoutDraft),{rows:1,cols:3,margin:8,gutter:4,panels:[{id:'b',caption:'绑定'},{id:'a',caption:'内联'},{id:'c',caption:'三'}]});
  assert.equal(input.textSources[0].targetId,'b');
});

test('inputFingerprint：源内容改变即失效，改名与视图字段不变',()=>{
  const node=layout([{id:'o',label:'object',captionSource:ref('a'),bbox:[0,0,9,9]}]);
  const fingerprint=(source,target=node)=>M.resolveTextSources(target,ports(source)).inputFingerprint;
  const base=fingerprint(textNode('a','一'));
  assert.notEqual(fingerprint(textNode('a','二')),base);
  assert.equal(fingerprint({...textNode('a','一'),alias:'改名'}),base);
  assert.equal(M.resolveTextSources(node,ports(textNode('a','一'))).draftRevision,node.draftRevision);
  const viewOnly={...node,settingsExpanded:false,height:1234,selectedId:'o'};
  assert.equal(fingerprint(textNode('a','一'),viewOnly),base);
  assert.notEqual(fingerprint(textNode('a','一'),{...node,imageWidth:2048,imageHeight:512}),base);
  assert.match(base,/^moss:[a-f0-9]{64}$/);
});

test('长文本不截断',()=>{
  const value='长'.repeat(20000);
  assert.equal(M.resolveTextSources(M.normalize({type:'moss',promptSource:ref('a')}),ports(textNode('a',value))).prompt,value);
});

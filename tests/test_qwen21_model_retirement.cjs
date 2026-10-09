const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const read=name=>fs.readFileSync(path.join(__dirname,'../frontend/scripts',name),'utf8');
const context={window:{}};
vm.runInNewContext(read('desktop-qwen21-model.js'),context);
const M=context.window.DesktopQwen21Model;
const status={default_model_id:'synthetic-bf16',models:[{id:'synthetic-bf16',ready:true,label:'Synthetic（BF16）'}],
  model_replacements:{[M.DEFAULT_MODEL_ID]:'synthetic-bf16'}};

test('仅显式退役的旧 Base 自动改选可用 BF16，参数和生成记录不变',()=>{
  const node=M.normalize({type:'qwen21',baseModelId:M.DEFAULT_MODEL_ID,steps:8,seed:'42',status:'succeeded',jobId:'qwen21_'+'a'.repeat(32)});
  const before={...node};
  assert.equal(M.selectAvailableBase(node,status),true);
  assert.equal(node.baseModelId,'synthetic-bf16');
  assert.deepEqual({...node,baseModelId:before.baseModelId},before);
  assert.equal(M.selectAvailableBase(node,status),false);
});

test('不改变活动任务、缺失的自定义模型、未准备的替代模型或仍存在的旧 Base',()=>{
  for(const state of ['submitting','queued','processing','running']){
    const node=M.normalize({type:'qwen21',status:state});
    assert.equal(M.selectAvailableBase(node,status),false);
    assert.equal(node.baseModelId,M.DEFAULT_MODEL_ID);
  }
  assert.equal(M.selectAvailableBase(M.normalize({type:'qwen21',baseModelId:'missing-custom'}),status),false);
  assert.equal(M.selectAvailableBase(M.normalize({type:'qwen21'}),{...status,model_replacements:{}}),false);
  assert.equal(M.selectAvailableBase(M.normalize({type:'qwen21'}),{...status,models:[{id:'synthetic-bf16',ready:false}]}),false);
  assert.equal(M.selectAvailableBase(M.normalize({type:'qwen21'}),{...status,models:[...status.models,{id:M.DEFAULT_MODEL_ID,ready:false}]}),false);
});

test('模型工具准备使用服务端默认 Base，不会硬编码补下载旧 8-bit',async()=>{
  const calls=[];
  const sandbox={window:{dispatchEvent(){}},CustomEvent:class{},setTimeout,clearTimeout};
  vm.runInNewContext(read('desktop-qwen21-tools.js'),sandbox);
  const tool=sandbox.window.DesktopQwen21Tools.create({api:{
    modelTools:async()=>({...status,runtime:{},conversion:{status:'idle'},preparation:{status:'idle'}}),
    prepare:async(...args)=>calls.push(args)}});
  await tool.activate();
  tool.handleClick({preventDefault(){},target:{closest:()=>({dataset:{},matches:s=>s==='[data-qwen21-tools-prepare]'})}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(calls,[['synthetic-bf16','standard']]);
  tool.deactivate();
});

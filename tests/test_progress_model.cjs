const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const context = vm.createContext({ window: {} });
for (const name of ['model', 'materials']) vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/scripts/desktop-progress-' + name + '.js'), 'utf8'), context);
const M = context.window.DesktopProgressModel, P = context.window.DesktopProgressMaterials;
const { LiquidMotion, FlowMotion, normalizeProgress, sampleFront } = M;
const plain = v => JSON.parse(JSON.stringify(v));

test('nine accepted styles, validated local preferences and migration default Liquid / 36px', () => {
  assert.deepEqual(Object.keys(M.PROGRESS_STYLES), ['liquid','slosh','smoke','drops','bands','threads','diamond','grain','classic']);
  for (const input of [undefined, null, 1, { style: 'invalid', height: 1000 }]) {
    assert.deepEqual(plain(M.normalizePreferences(input)), { style: 'liquid', height: 36, colors: {} });
  }
  const value = M.normalizePreferences({ style:'slosh', height:'48', colors:{ slosh:'#abc', liquid:'url(x)', bad:'#123456' } });
  assert.deepEqual(plain(value), { style:'slosh', height:48, colors:{slosh:'#AABBCC'} });
  assert.equal(M.normalizePreferences({style:'__proto__'}).style, 'liquid');
});
test('real receipt values include zero and one percent, never guessed stages/NaN or clamped unknowns', () => {
  for (const input of [undefined,null,'',true,false,NaN,Infinity]) assert.equal(M.knownPercent(input),null);
  for (const [input, expected] of [[0,0],[1,1],['39',39],[-5,0],[101,100]]) assert.equal(M.knownPercent(input),expected);
  const d=M.normalizeDisplay({visible:true,running:true,title:'采样 21/24',percent:null});
  assert.equal(d.percent,null);assert.equal(M.elapsedLabel(d,1e12),'—');
  assert.equal(M.normalizeDisplay({visible:false,running:true}).running,false);
});
test('elapsed uses authoritative seconds or milliseconds and survives repeated identical receipts', () => {
  const epoch=1790910750;
  for(const startedAt of [epoch, epoch*1000]) {
    const d=M.normalizeDisplay({visible:true,running:true,startedAt});
    assert.equal(M.elapsedLabel(d,epoch*1000+61100),'01:01');
    assert.equal(M.elapsedLabel(d,epoch*1000+3661999),'01:01:01');
    assert.equal(M.elapsedLabel({...d,finishedAt:epoch*1000+22000},epoch*1000+3600000),'00:22');
  }
  assert.equal(M.elapsedLabel(M.normalizeDisplay({elapsedText:'04:12'}),0),'04:12');
  assert.equal(M.formatElapsed(-1),'00:00');assert.equal(M.formatElapsed(NaN),'00:00');
});
test('continuous flow cannot receive a position-target impulse and is stable at 30/60/120Hz', () => {
  const samples=[];
  for(const fps of [30,60,120]) {
    const flow=new FlowMotion(),position=new LiquidMotion(.6);
    for(let i=0;i<fps*4;i++) flow.step(1/fps,{running:true,velocity:i<fps*2?.3:-.25});
    const before=plain(flow);position.setTarget(.8);assert.deepEqual(plain(flow),before);
    samples.push(flow);
    for(let i=0;i<fps*4;i++) flow.step(1/fps,{running:false});
    assert.equal(flow.active,false);const phase=flow.phase;flow.step(.1);assert.equal(flow.phase,phase);
  }
  for(const sample of samples.slice(1)) assert.ok(Math.abs(sample.phase-samples[0].phase)<1e-8);
});
test('Slosh front and blue body keep authoritative fill area and never add a black bottom glaze', () => {
  for(const [width,height] of [[320,36],[720,56]]) for(const progress of [0,.001,.6,.999,1]) {
    const front=P.sampleSloshFront({width,height,progress,energy:1,phase:3,velocity:-2});
    const n=front.length-1,mean=front.reduce((s,x,i)=>s+x*(i===0||i===n?.5:1),0)/n;
    assert.ok(Math.abs(mean-width*progress)<1e-8);assert.ok(front.every(x=>x>=0&&x<=width));
    const [start,end]=P.sloshGradientExtent(width,height,progress);assert.equal(start,0);assert.ok(end>=width*progress);
  }
  for(const [,hex] of P.SLOSH_STOPS) {
    const channels=hex.slice(1).match(/../g).map(v=>parseInt(v,16));assert.ok(channels[2]>=131);
  }
});
test('smoke transports forwards coherently and uses a bounded narrow raster regardless of width/DPR', () => {
  let changed=0;
  for(let y=0;y<=1;y+=.1) for(let phase=0;phase<6;phase+=.3) {
    assert.equal(P.sampleSmokeDensity(1.1,y,phase,1),1);assert.equal(P.sampleSmokeDensity(-.8,y,phase,1),0);
    const a=P.sampleSmokeDensity(.1,y,phase,.7),b=P.sampleSmokeDensity(.1,y,phase+.01,.7);
    assert.ok(a>=0&&a<=1&&Math.abs(a-b)<.15);if(a!==b)changed++;
  }
  assert.ok(changed>100);
  for(const w of [320,4096]) for(const h of [36,56,148,600]) for(const dpr of [1,2,8]) {
    const size=P.flowRasterSize(w,h,dpr);assert.ok(size.width<=256&&size.height<=192);
  }
});
test('fill colors accept only HEX, original reset is identity and any hue retains shade variation', () => {
  assert.equal(M.normalizeFillColor('#abc'),'#AABBCC');
  for(const v of ['red','url(x)','#ffff','#fff;','',null]) assert.equal(M.normalizeFillColor(v),null);
  for(const color of ['#000000','#FFFFFF','#35D1C4','#EF7FA7']) {
    const tint=new M.FillTint(color), shades=[[18,59,131],[26,100,194],[163,228,255]].map(c=>tint.rgb(c));
    assert.ok(shades.flat().every(c=>Number.isFinite(c)&&c>=-1e-9&&c<=255+1e-9));
    assert.notDeepEqual(plain(shades[0]),plain(shades[2]));
  }
  const original=[18,59,131];assert.equal(M.ORIGINAL_FILL_TINT.rgb(original),original);
});
const advance = (motion, seconds, fps = 60) => {
  for (let i = 0; i < Math.round(seconds * fps); i++) motion.step(1 / fps);
  return motion;
};

test('normalizes untrusted visual inputs without NaN', () => {
  assert.equal(normalizeProgress(NaN), 0);
  assert.equal(normalizeProgress(Infinity), 0);
  assert.equal(normalizeProgress(-0.5), 0);
  assert.equal(normalizeProgress(3), 1);
  assert.equal(normalizeProgress('0.65'), 0.65);
});
test('forward progress converges without overshooting the authoritative target', () => {
  const motion = new LiquidMotion(0);
  motion.setTarget(0.79);
  let prior = 0;
  for (let i = 0; i < 420; i++) {
    motion.step(1 / 60);
    assert.ok(motion.value >= prior - 1e-10 && motion.value <= 0.79);
    prior = motion.value;
  }
  assert.equal(motion.value, 0.79);
  assert.equal(motion.active, false);
  assert.equal(motion.energy, 0);
});
test('reverse movement remains finite and settles exactly', () => {
  const motion = new LiquidMotion(0.9);
  motion.setTarget(0.25);
  advance(motion, 0.35);
  assert.ok(motion.value > 0.25 && motion.value < 0.9);
  assert.ok(motion.energy > 0.1);
  advance(motion, 4);
  assert.equal(motion.value, 0.25);
  assert.equal(motion.active, false);
});
test('a paused input leaves a short tail, not a permanently waving front', () => {
  const motion = new LiquidMotion(0.60);
  motion.setTarget(0.79);
  advance(motion, 0.3);
  const energy = motion.energy;
  advance(motion, 1);
  assert.ok(motion.energy < energy * 0.5);
  advance(motion, 3);
  assert.equal(motion.active, false);
});
test('same target does not re-excite an idle bar', () => {
  const motion = new LiquidMotion(0.6);
  for (let i = 0; i < 100; i++) motion.setTarget(0.6);
  assert.equal(motion.active, false);
});
test('30/60/120 Hz produce equivalent position and envelope', () => {
  const samples = [30, 60, 120].map(fps => {
    const m = new LiquidMotion(0.1); m.setTarget(0.9); advance(m, 0.5, fps); return m;
  });
  for (const m of samples.slice(1)) {
    assert.ok(Math.abs(m.value - samples[0].value) < 1e-10);
    assert.ok(Math.abs(m.energy - samples[0].energy) < 1e-10);
  }
});
test('reduced motion snaps, reset has no trailing animation', () => {
  const motion = new LiquidMotion(0.1);
  motion.setTarget(0.6, true);
  assert.equal(motion.value, 0.6); assert.equal(motion.active, false);
  motion.setTarget(0.9); motion.step(0.1, true);
  assert.equal(motion.value, 0.9); assert.equal(motion.active, false);
  motion.setTarget(1); motion.reset(0);
  assert.equal(motion.active, false); assert.equal(motion.value, 0);
});
test('wave has zero-mean area and scales with component dimensions', () => {
  const input = { width: 720, height: 56, progress: .6, energy: .9, phase: 2.5, amount: 1 };
  const first = sampleFront(input);
  const scaled = sampleFront({ ...input, width: 1440, height: 112 });
  let sum = 0;
  first.forEach((value, i) => {
    sum += value * (i === 0 || i === first.length - 1 ? .5 : 1);
    assert.ok(Math.abs(value * 2 - scaled[i]) < 1e-9);
  });
  assert.ok(Math.abs(sum / (first.length - 1) - 720 * .6) < 1e-9);
});
test('zero/full edges and idle front are flat, rapid retargeting stays in range', () => {
  for (const progress of [0, 1]) {
    const front = sampleFront({ width: 720, height: 56, progress, energy: 1, phase: 4 });
    assert.ok(front.every(x => x === 720 * progress));
  }
  const still = sampleFront({ width: 720, height: 56, progress: .3, energy: 0, phase: 4 });
  assert.ok(still.every(x => x === 216));
  const motion = new LiquidMotion();
  for (let i = 0; i < 120; i++) {
    motion.setTarget(i % 2); motion.step(1 / 30);
    assert.ok(Number.isFinite(motion.value) && motion.value >= 0 && motion.value <= 1);
  }
});

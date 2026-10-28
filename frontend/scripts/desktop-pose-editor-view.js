// Pose editor markup: shell, scene outline and inspector panels. Pure string builders; the
// controller (desktop-pose-editor.js) owns state, three.js and events.
import { timelineHtml } from './desktop-pose-timeline.js';

const model = window.DesktopPoseModel;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const ICON_PATHS = {
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
  redo: '<path d="m15 14 5-5-5-5"/><path d="M20 9H9a5 5 0 0 0 0 10h3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  eyeOff: '<path d="M9.9 4.2A10 10 0 0 1 12 4c6.4 0 10 8 10 8a17 17 0 0 1-2.2 3.2M6.6 6.6A17 17 0 0 0 2 12s3.6 8 10 8a9.7 9.7 0 0 0 5.4-1.6M2 2l20 20"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  camera: '<path d="M3 7h12v10H3zM15 10l6-3v10l-6-3"/>',
};
const icon = (name, cls = '') => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICON_PATHS[name]}</svg>`;
// Front view: the character's right side is on the viewer's left.
export const BODY_MAP = Object.freeze({Head: [50, 9], Neck1: [50, 19], Chest: [50, 29], Spine1: [50, 40], Hips: [50, 50],
  RightShoulder: [42, 22], RightArm: [33, 25], RightForeArm: [27, 38], RightHand: [22, 50], LeftShoulder: [58, 22], LeftArm: [67, 25], LeftForeArm: [73, 38], LeftHand: [78, 50],
  RightLeg: [44, 54], RightShin: [42, 72], RightFoot: [41, 90], LeftLeg: [56, 54], LeftShin: [58, 72], LeftFoot: [59, 90]});
const BODY_BONES = [['Neck1', 'Chest'], ['Chest', 'Spine1'], ['Spine1', 'Hips'], ['RightShoulder', 'LeftShoulder'], ['RightShoulder', 'RightArm'], ['RightArm', 'RightForeArm'],
  ['RightForeArm', 'RightHand'], ['LeftShoulder', 'LeftArm'], ['LeftArm', 'LeftForeArm'], ['LeftForeArm', 'LeftHand'], ['Hips', 'RightLeg'], ['RightLeg', 'RightShin'],
  ['RightShin', 'RightFoot'], ['Hips', 'LeftLeg'], ['LeftLeg', 'LeftShin'], ['LeftShin', 'LeftFoot'], ['RightLeg', 'LeftLeg']];

export function shellHtml() {
  const passes = Object.entries(model.PASSES).map(([key, label]) => `<button type="button" data-pe-pass="${key}">${esc(label)}</button>`).join('');
  return `<div class="desk-pose-editor__scrim" data-pe-close></div>
  <section class="desk-pose-editor__dialog" role="dialog" aria-modal="true" aria-label="姿态编辑器">
    <header class="desk-pose-editor__header">
      <span class="desk-pose-editor__brand">${model.ICON}</span>
      <div class="desk-pose-editor__heading"><strong>姿态编辑器</strong><small data-pe-node-title></small></div>
      <div class="desk-pose-editor__passes" role="group" aria-label="视口通道">${passes}</div>
      <span class="desk-pose-editor__status" data-pe-status></span>
      <button type="button" class="desk-pose-editor__header-button is-icon" data-pe-undo title="撤销（⌘Z）" aria-label="撤销" disabled>${icon('undo')}</button>
      <button type="button" class="desk-pose-editor__header-button is-icon" data-pe-redo title="重做（⇧⌘Z）" aria-label="重做" disabled>${icon('redo')}</button>
      <button type="button" class="desk-pose-editor__header-button is-icon" data-pe-sidebar-toggle aria-pressed="false" title="收起检查器">›</button>
      <button type="button" class="desk-pose-editor__header-button is-icon" data-pe-close aria-label="关闭姿态编辑器">×</button>
    </header>
    <div class="desk-pose-editor__layout">
      <aside class="desk-pose-editor__outline" aria-label="场景大纲">
        <section class="desk-pose-editor__outline-section">
          <header><h3>角色</h3><button type="button" data-pe-add-character title="添加角色" aria-label="添加角色">${icon('plus')}</button></header>
          <ul class="desk-pose-editor__rows" data-pe-characters></ul>
        </section>
        <section class="desk-pose-editor__outline-section">
          <header><h3>机位</h3><button type="button" data-pe-add-camera title="以当前视角添加机位" aria-label="添加机位">${icon('plus')}</button></header>
          <ul class="desk-pose-editor__rows" data-pe-cameras></ul>
        </section>
        <section class="desk-pose-editor__outline-section is-library">
          <header><h3>姿势库</h3><span>应用到选中角色</span></header>
          <div class="desk-pose-editor__library" data-pe-library></div>
        </section>
      </aside>
      <div class="desk-pose-editor__stage">
        <div class="desk-pose-editor__toolbar">
          <div class="desk-pose-editor__segments" role="group" aria-label="操作工具">
            <button type="button" data-pe-tool="rotate" title="旋转关节（R）">旋转<kbd>R</kbd></button>
            <button type="button" data-pe-tool="translate" title="移动角色；选中手腕或脚踝时拖动肢体（G）">移动<kbd>G</kbd></button>
            <button type="button" data-pe-tool="select" title="仅选择（Q）">选择<kbd>Q</kbd></button>
          </div>
          <div class="desk-pose-editor__segments" role="group" aria-label="坐标空间">
            <button type="button" data-pe-space="local" title="局部坐标（L）">局部</button>
            <button type="button" data-pe-space="world" title="世界坐标（L）">世界</button>
          </div>
          <div class="desk-pose-editor__segments" role="group" aria-label="辅助">
            <button type="button" data-pe-toggle="snap" title="旋转吸附 15°">吸附 15°</button>
            <button type="button" data-pe-toggle="joints" title="显示关节点">关节</button>
            <button type="button" data-pe-toggle="hands" title="显示手指关节">手指</button>
            <button type="button" data-pe-toggle="reference" title="在机位视角叠加连接的参考图" hidden>参考图</button>
          </div>
          <div class="desk-pose-editor__segments" role="group" aria-label="视角">
            <button type="button" data-pe-view="free" title="自由视角（0 切换）">自由视角</button>
            <button type="button" data-pe-view="camera" title="透过机位查看（0）">机位视角</button>
          </div>
          <span class="desk-pose-editor__selection-label" data-pe-selection-label></span>
        </div>
        <div class="desk-pose-editor__viewer" data-pe-viewer tabindex="0" aria-label="三维视口">
          <canvas class="desk-pose-editor__canvas" data-pe-canvas></canvas>
          <canvas class="desk-pose-editor__overlay" data-pe-overlay aria-hidden="true"></canvas>
          <div class="desk-pose-editor__frame" data-pe-frame hidden><img class="desk-pose-editor__reference" data-pe-reference alt="" hidden><video class="desk-pose-editor__reference" data-pe-reference-video muted playsinline preload="auto" hidden></video><span data-pe-frame-label></span></div>
          <canvas class="desk-pose-editor__axes" data-pe-axes width="128" height="128" aria-label="视角方向，点击轴切换正交方向"></canvas>
          <div class="desk-pose-editor__hint"><span><kbd>单击</kbd>选择关节</span><span><kbd>左键拖动</kbd>环绕</span><span><kbd>右键</kbd>平移</span><span><kbd>滚轮</kbd>缩放</span><span><kbd>F</kbd>聚焦</span><span><kbd>M</kbd>镜像</span><span><kbd>Esc</kbd>取消选择</span></div>
          <div class="desk-pose-editor__notice" data-pe-loading><strong>正在加载 SOMA 人偶</strong><span>首次打开需要读取人偶文件</span></div>
        </div>
        ${timelineHtml()}
      </div>
      <aside class="desk-pose-editor__inspector">
        <nav class="desk-pose-editor__tabs"><button type="button" data-pe-tab="pose">姿势</button><button type="button" data-pe-tab="character">角色</button><button type="button" data-pe-tab="camera">机位</button><button type="button" data-pe-tab="output">输出</button></nav>
        <div class="desk-pose-editor__panel" data-pe-panel></div>
        <footer class="desk-pose-editor__footer"><button type="button" data-pe-reset-pose>重置为站立</button><button type="button" class="is-export" data-pe-export>导出到节点</button><small data-pe-footer-note></small></footer>
      </aside>
    </div>
  </section>`;
}

export function charactersHtml(scene, activeId, activeJoint) {
  return scene.characters.map(c => `<li class="desk-pose-editor__row${c.id === activeId ? ' is-active' : ''}${c.visible ? '' : ' is-hidden'}" data-pe-character="${esc(c.id)}">
    <span class="desk-pose-editor__swatch" style="background:${esc(c.color)}"></span>
    <span class="desk-pose-editor__row-copy"><strong>${esc(c.name)}</strong><small>${c.id === activeId && activeJoint ? esc(model.jointLabel(activeJoint)) : `${model.bodyLabel(c.body)} · ${c.height} cm`}</small></span>
    <span class="desk-pose-editor__row-tools"><button type="button" data-pe-character-lock="${esc(c.id)}" aria-pressed="${c.locked}" title="${c.locked ? '解锁姿势' : '锁定姿势'}">${icon('lock')}</button><button type="button" data-pe-character-eye="${esc(c.id)}" aria-pressed="${!c.visible}" title="${c.visible ? '隐藏（不参与导出）' : '显示'}">${icon(c.visible ? 'eye' : 'eyeOff')}</button></span></li>`).join('');
}

export function camerasHtml(scene) {
  return scene.cameras.map(c => `<li class="desk-pose-editor__row${c.id === scene.activeCameraId ? ' is-active' : ''}" data-pe-camera="${esc(c.id)}">${icon('camera', 'desk-pose-editor__row-icon')}
    <span class="desk-pose-editor__row-copy"><strong>${esc(c.name)}</strong><small>${c.focalMm} mm · ${c.aspect} · 高 ${c.position[1].toFixed(2)} m</small></span>
    ${c.id === scene.activeCameraId ? '<span class="desk-pose-editor__badge">输出</span>' : ''}</li>`).join('');
}

export function libraryHtml(thumbs) {
  const preset = p => `<button type="button" class="desk-pose-editor__preset" data-pe-preset="${p.id}"${p.facing == null ? '' : ' title="按当前机位转向"'}>${thumbs?.get(p.id) ? `<img src="${thumbs.get(p.id)}" alt="">` : '<span class="desk-pose-editor__preset-placeholder"></span>'}${esc(p.label)}</button>`;
  return model.PRESET_GROUPS.map(group => `<h4 class="desk-pose-editor__library-group">${esc(group)}</h4>${model.PRESETS.filter(p => p.group === group).map(preset).join('')}`).join('');
}

function slider(key, label, min, max, step, value, unit = '') {
  const plain = label.replace(/<[^>]+>/g, '');
  return `<label><span>${label}</span><div><input type="range" min="${min}" max="${max}" step="${step}" value="${value}" data-pe-input="${key}" aria-label="${esc(plain)}"><input type="number" min="${min}" max="${max}" step="${step}" value="${value}" data-pe-input="${key}" data-stepper="off" aria-label="${esc(plain + unit)}"></div></label>`;
}
const sectionTitle = (title, note = '') => `<div class="desk-pose-editor__section-title"><h3>${title}</h3><span>${note}</span></div>`;
const segments = (attr, entries, current, disabled = false) => `<div class="desk-pose-editor__segments is-fill">${entries.map(([value, label]) =>
  `<button type="button" class="${value === current ? 'is-active' : ''}" data-${attr}="${value}"${disabled ? ' disabled' : ''}>${label}</button>`).join('')}</div>`;

// The hand presets, led by the character's own fingers when it has any: recognised ones (识别) or ones
// rotated by hand (自定义).
function handChoices(character, side, track) {
  const own = track || model.hasFingers(character.rotations, side) || character.hands[side.toLowerCase()] === model.CAPTURED_HAND;
  const label = track || character.capturedBody ? '识别' : '自定义';
  return [...(own ? [[model.CAPTURED_HAND, label]] : []), ...Object.entries(model.HAND_SHAPES)];
}

export function posePanel({character, joint, euler, edited, track = false}) {
  if (!character) return '<p class="desk-pose-editor__note">场景中没有角色，请在左侧添加。</p>';
  const P = name => [BODY_MAP[name][0] * 3.2, BODY_MAP[name][1] * 2.08];
  const bones = BODY_BONES.map(([a, b]) => `M${P(a).join(' ')}L${P(b).join(' ')}`).join('');
  const map = Object.entries(BODY_MAP).map(([name, [x, y]]) => `<button type="button" style="left:${x}%;top:${y}%" class="${name === joint ? 'is-active' : ''}${edited.has(name) ? ' is-edited' : ''}" data-pe-joint="${name}" title="${model.jointLabel(name)}" aria-label="${model.jointLabel(name)}"></button>`).join('');
  const yaw = Math.round(character.yaw);
  return `<section class="desk-pose-editor__section">
      <div class="desk-pose-editor__selection"><span class="desk-pose-editor__swatch" style="background:${esc(character.color)}"></span><strong>${esc(character.name)}${joint ? ' · ' + esc(model.jointLabel(joint)) : ''}</strong><small>${joint ? esc(joint) : '未选关节'}</small></div>
      <div class="desk-pose-editor__bodymap"><svg viewBox="0 0 320 208" preserveAspectRatio="none" aria-hidden="true"><circle cx="160" cy="13" r="11"/><path d="${bones}"/></svg>${map}<small class="is-right">角色右侧</small><small class="is-left">角色左侧</small></div>
    </section>
    <section class="desk-pose-editor__section">
      ${sectionTitle('水平旋转', '绕站立中心 · 姿势不变')}
      <div class="desk-pose-editor__params">${slider('yaw', '角度', -180, 180, 1, yaw)}</div>
      <div class="desk-pose-editor__field"><span>朝向机位</span>${segments('pe-facing', [['0', '正面'], ['90', '右侧面'], ['180', '背面'], ['-90', '左侧面']], '')}</div>
    </section>
    <section class="desk-pose-editor__section">
      ${sectionTitle('关节旋转', '相对 T 姿势 · 度')}
      ${joint ? `<div class="desk-pose-editor__params">
        ${slider('rx', '<i class="desk-pose-editor__axis is-x">X</i>俯仰', -180, 180, 1, euler[0])}
        ${slider('ry', '<i class="desk-pose-editor__axis is-y">Y</i>扭转', -180, 180, 1, euler[1])}
        ${slider('rz', '<i class="desk-pose-editor__axis is-z">Z</i>侧摆', -180, 180, 1, euler[2])}
      </div>
      <div class="desk-pose-editor__actions"><button type="button" data-pe-action="reset-joint">重置关节</button><button type="button" data-pe-action="mirror-joint"${model.mirrorName(joint) === joint ? ' disabled' : ''}>镜像到对侧</button><button type="button" data-pe-action="mirror-all">整体左右镜像</button></div>`
        : '<p class="desk-pose-editor__note">在视口点选关节，或在上方人体图中选择。按 R 旋转；未选关节时旋转工具会整体水平转动角色；选中手腕或脚踝后按 G 可直接拖动整条手臂或腿。</p>'}
    </section>
    <section class="desk-pose-editor__section">
      ${sectionTitle('手势', track ? '预设覆盖整段视频的这只手' : '预设覆盖整只手的手指')}
      <div class="desk-pose-editor__field"><span>左手</span>${segments('pe-hand-left', handChoices(character, 'Left', track), character.hands.left)}</div>
      <div class="desk-pose-editor__field"><span>右手</span>${segments('pe-hand-right', handChoices(character, 'Right', track), character.hands.right)}</div>
    </section>
    <section class="desk-pose-editor__section">
      ${sectionTitle('角色位置', track ? '视频角色 · 整段轨迹偏移' : '米 · 地面')}
      <div class="desk-pose-editor__params">
        ${slider('px', '左右 X', -5, 5, 0.01, character.position[0].toFixed(2))}
        ${slider('py', '离地 Y', 0, model.MAX_ELEVATION, 0.01, character.elevation.toFixed(2))}
        ${slider('pz', '前后 Z', -5, 5, 0.01, character.position[1].toFixed(2))}
      </div>
    </section>`;
}

export function characterPanel({character, count, missingBody = false}) {
  if (!character) return '<p class="desk-pose-editor__note">场景中没有角色，请在左侧添加。</p>';
  return `<section class="desk-pose-editor__section">
      ${sectionTitle('角色', `${count} / ${model.MAX_CHARACTERS}`)}
      <label class="desk-pose-editor__field"><span>名称</span><input type="text" value="${esc(character.name)}" data-pe-input="name" maxlength="16"></label>
      <div class="desk-pose-editor__field"><span>遮罩颜色</span><div class="desk-pose-editor__colors">${model.SWATCHES.map(c => `<button type="button" style="background:${c}" class="${c === character.color ? 'is-active' : ''}" data-pe-color="${c}" aria-label="遮罩颜色 ${c}"></button>`).join('')}</div></div>
      <div class="desk-pose-editor__params">${slider('height', '身高 cm', 140, 200, 1, character.height)}</div>
    </section>
    <section class="desk-pose-editor__section">
      ${sectionTitle('体型', 'SOMA identity')}
      <div class="desk-pose-editor__field"><span>体型</span>${segments('pe-body', [...Object.entries(model.BODIES), ...(character.capturedBody ? [[character.capturedBody, '识别']] : [])], character.body)}</div>
      <p class="desk-pose-editor__note">${missingBody ? '识别体型文件不存在（可能已删除或来自其他电脑），暂以中性人偶显示。'
        : '女性 / 男性为 Anny 成人体型；识别体型来自照片里的人物，只有低精度网格。身高按中性人偶刻度换算。'}</p>
    </section>
    <section class="desk-pose-editor__section">
      <label class="desk-pose-editor__check"><input type="checkbox" data-pe-input="visible"${character.visible ? ' checked' : ''}>参与导出<small>隐藏后各通道都不渲染</small></label>
      <label class="desk-pose-editor__check"><input type="checkbox" data-pe-input="grounded"${character.grounded ? ' checked' : ''}>自动贴地<small>最低的脚落在离地 Y 高度</small></label>
      <label class="desk-pose-editor__check"><input type="checkbox" data-pe-input="locked"${character.locked ? ' checked' : ''}>锁定姿势<small>防止误拖</small></label>
      <button type="button" class="desk-pose-editor__wide-button" data-pe-action="delete-character"${count < 2 ? ' disabled' : ''}>删除角色</button>
    </section>`;
}

export function cameraPanel({shot, count, inCameraView}) {
  const p = shot.position;
  return `<section class="desk-pose-editor__section">
      ${sectionTitle(esc(shot.name), '当前输出机位')}
      <label class="desk-pose-editor__field"><span>名称</span><input type="text" value="${esc(shot.name)}" data-pe-input="camera-name" maxlength="16"></label>
      <div class="desk-pose-editor__row-fields"><label><span>画幅</span><select data-pe-input="aspect">${Object.keys(model.ASPECTS).map(a => `<option${a === shot.aspect ? ' selected' : ''}>${a}</option>`).join('')}</select></label>
        <label><span>镜头预设</span><select data-pe-input="lens">${[18, 24, 35, 50, 85, 135].map(f => `<option value="${f}"${f === shot.focalMm ? ' selected' : ''}>${f} mm</option>`).join('')}${[18, 24, 35, 50, 85, 135].includes(shot.focalMm) ? '' : `<option value="${shot.focalMm}" selected>${shot.focalMm} mm</option>`}</select></label></div>
      <div class="desk-pose-editor__params">${slider('focal', '焦距 mm', 14, 200, 1, shot.focalMm)}${slider('camera-height', '机位高度 m', 0.1, 4, 0.01, p[1].toFixed(2))}</div>
    </section>
    <section class="desk-pose-editor__section">
      ${sectionTitle('构图', `位置 ${p.map(v => v.toFixed(2)).join(', ')}`)}
      <div class="desk-pose-editor__actions"><button type="button" data-pe-action="toggle-camera-view">${inCameraView ? '回到自由视角' : '透过机位查看'}</button><button type="button" data-pe-action="camera-from-view">设为当前视角</button><button type="button" data-pe-action="delete-camera"${count < 2 ? ' disabled' : ''}>删除机位</button></div>
      <p class="desk-pose-editor__note">透过机位查看时，环绕与平移直接移动这个机位；框外变暗区域不会导出。</p>
    </section>`;
}

export function outputPanel({node, width, height}) {
  const seq = node.scene.sequence;
  const video = seq ? `<section class="desk-pose-editor__section">
      ${sectionTitle('输出类型', `${seq.fps} fps`)}
      <div class="desk-pose-editor__field"><span>导出</span>${segments('pe-output-kind', [['video', '姿态视频'], ['image', '当前帧图片']], node.output.kind)}</div>
      <p class="desk-pose-editor__note">${node.output.kind === 'video'
        ? `导出第 ${seq.inFrame + 1}–${seq.outFrame + 1} 帧（共 ${seq.outFrame - seq.inFrame + 1} 帧，帧率与原视频相同），完成后写入右侧连接的视频节点；首帧同时作为节点图片。用时间轴的「入点 / 出点」调整范围。`
        : '只导出当前帧为图片，供图像节点使用。'}</p>
    </section>` : '';
  return `${video}<section class="desk-pose-editor__section">
      ${sectionTitle('节点输出通道', seq && node.output.kind === 'video' ? 'MP4 · H.264' : 'PNG')}
      <div class="desk-pose-editor__pass-grid">${Object.entries(model.PASSES).map(([key, label]) => `<button type="button" class="desk-pose-editor__pass${key === node.output.pass ? ' is-active' : ''}" data-pe-output-pass="${key}"><canvas data-pe-pass-thumb="${key}" width="96" height="96"></canvas>${esc(label)}</button>`).join('')}</div>
      <p class="desk-pose-editor__note">下游节点接收所选通道。需要多个通道时，可复制节点并各选一种。</p>
    </section>
    <section class="desk-pose-editor__section">
      <div class="desk-pose-editor__row-fields"><label><span>输出尺寸（长边）</span><select data-pe-input="size">${Object.keys(model.SIZES).map(k => `<option value="${k}"${k === node.output.size ? ' selected' : ''}>${k} px</option>`).join('')}</select></label>
        <label><span>实际像素</span><input type="text" value="${width} × ${height}" readonly aria-label="实际像素"></label></div>
      <p class="desk-pose-editor__note">画幅由机位决定，短边按 8 的倍数取整。</p>
    </section>
    <section class="desk-pose-editor__section">
      ${sectionTitle('OpenPose', 'COCO-18')}
      <label class="desk-pose-editor__check"><input type="checkbox" data-pe-input="openpose-hands"${node.settings.openposeHands ? ' checked' : ''}>包含手部 21 点</label>
      <div class="desk-pose-editor__field"><span>线宽</span>${segments('pe-openpose-width', [['standard', '标准'], ['bold', '加粗']], node.settings.openposeWidth)}</div>
      <p class="desk-pose-editor__note">不输出面部 70 点：SOMA 只有眼睛与下颌关节，硬凑面部点会误导下游模型。</p>
    </section>
    <section class="desk-pose-editor__section">
      ${sectionTitle('背景', '人偶通道')}
      ${segments('pe-background', [['black', '纯黑'], ['transparent', '透明']], node.settings.background)}
      <p class="desk-pose-editor__note">深度按可见角色自动取近远范围，近处为白；法线为相机空间。</p>
    </section>`;
}

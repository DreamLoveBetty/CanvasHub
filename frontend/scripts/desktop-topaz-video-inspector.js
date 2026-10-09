// Processing inspector presentation. State and validation are injected explicitly.
(function () {
  function create({pipeline, escapeHtml}) {
    const esc = value => escapeHtml(String(value ?? ''));
    const option = (value, label, active, disabled = false) => `<option value="${esc(value)}"${String(value) === String(active) ? ' selected' : ''}${disabled ? ' disabled' : ''}>${esc(label)}</option>`;
    const select = (group, key, label, value, options) => `<label><span>${esc(label)}</span><select data-tvwb-processing="${group}" data-tvwb-key="${key}">${options.map(row => option(row[0], row[1], value, row[2])).join('')}</select></label>`;
    const number = (group, key, label, value, min, max, step) => `<label><span>${esc(label)}</span><input type="number" data-tvwb-processing="${group}" data-tvwb-key="${key}" value="${esc(value)}" min="${min}" max="${max}" step="${step}"></label>`;
    function toggle(group, key, label, checked, disabled = false) {
      return `<label class="desk-topaz-video-workbench__switch"><input type="checkbox" data-tvwb-processing="${group}" data-tvwb-key="${key}"${checked ? ' checked' : ''}${disabled ? ' disabled' : ''} data-tvwb-unavailable="${disabled}"><span>${esc(label)}</span></label>`;
    }
    function filters(node, status) {
      pipeline.normalize(node);
      const names = {denoise: ['独立降噪', 'Nyx 3 · 可与增强模型叠加'], interpolation: ['帧插值', '升帧 · 慢动作 · 重复帧修复'], hdr: ['SDR 转 HDR', 'Hyperion 2 · ACES → HDR10'], stabilization: ['视频稳定', '自动裁切 · 全帧 · 滚动快门'], motionDeblur: ['运动去模糊', 'Themis · 修复运动拖影']};
      return Object.entries(names).map(([group, [name, description]]) => {
        const cap = pipeline.capability(status, group), value = node.videoFilters[group];
        let fields = '';
        if (group === 'denoise') fields = number(group, 'noise', '降噪强度', value.noise, 0, 1, .05)
          + number(group, 'details', '减少大颗粒', value.details, 0, 1, .05)
          + '<p>单独运行 Nyx 3，不更改当前增强模型。默认值为模型中性参数，可先生成选区预览。</p>';
        if (group === 'interpolation') fields = select(group, 'model', 'AI 模型', value.model, (cap.models || []).map(item => [item.id, item.label, !item.available]))
          + `<div class="desk-topaz-video-workbench__setting-row">${number(group, 'fps', '输出帧率 · 0 跟随原片', value.fps, 0, 120, .001)}${select(group, 'slowmo', '慢动作', value.slowmo, [1,2,4,8,16].map(n => [n, n === 1 ? '关闭 · 原速' : n + '× 慢动作']))}</div>`
          + number(group, 'rdt', '重复帧阈值 · −0.01 关闭', value.rdt, -.01, .2, .01);
        if (group === 'hdr') fields = select(group, 'strength', '增强强度', value.strength, [[.7, '低 · 0.7'], [1, '中 · 1.0'], [1.3, '高 · 1.3']])
          + '<p>使用真实线性 HDR 帧，经 ACES 色彩转换输出 BT.2020 / PQ 10-bit；HDR 显示效果取决于浏览器和显示器。</p>';
        if (group === 'stabilization') fields = select(group, 'mode', '稳定模式', value.mode, [['auto_crop', '自动裁切'], ['full_frame', '全帧补边', !cap.full_frame]])
          + number(group, 'strength', '平滑强度', value.strength, 0, 16, .5)
          + toggle(group, 'rollingShutter', '滚动快门修复', value.rollingShutter, !cap.jitter)
          + select(group, 'reduceJitter', '抖动修复次数', value.reduceJitter, [0,1,2,3,4,5].map(n => [n, n ? n + ' 次' : '关闭', n > 0 && !cap.jitter]))
          + '<p>自动裁切后缩放至目标分辨率；全帧模式用模型补齐边缘。先预览检查裁切与补边。</p>';
        if (group === 'motionDeblur') fields = '<p>Themis 使用独立运动去模糊模型，先于增强与补帧执行，不替代锐化滑杆。</p>';
        return `<details class="desk-topaz-video-workbench__feature" data-tvwb-feature="${group}"${value.enabled ? ' open' : ''}>
          <summary><span><strong>${name}</strong><small>${description}</small></span><i>${value.enabled ? '已启用' : cap.available ? '可用' : '缺少资源'}</i></summary>
          <div class="desk-topaz-video-workbench__feature-body">${toggle(group, 'enabled', '启用' + name, value.enabled, !cap.available && !value.enabled)}
          ${!cap.available ? `<p class="is-unavailable">${esc(cap.reason || '刷新运行时后查看资源状态')}</p>` : ''}
          <fieldset${value.enabled && cap.available ? '' : ' disabled'}>${fields}</fieldset></div></details>`;
      }).join('');
    }
    function output(node, source, status) {
      pipeline.normalize(node);
      const encoding = node.encodingOptions, timing = pipeline.timing(node, source), scale = node.enhancementEnabled ? node.scale : 1;
      const width = (source?.width || 0) * scale, height = (source?.height || 0) * scale;
      return `<section class="desk-topaz-video-workbench__output"><div class="desk-topaz-video-workbench__section-title"><h3>编码设置</h3><span>本机 VideoToolbox</span></div>
        ${select('encoding', 'codec', '视频编码器', encoding.codec, [['h264', 'H.264 · 8-bit', node.videoFilters.hdr.enabled], ['hevc', 'H.265 · 8-bit', node.videoFilters.hdr.enabled], ['hevc10', 'H.265 · 10-bit']])}
        ${number('encoding', 'bitrateMbps', '码率 Mbps · 0 自动', encoding.bitrateMbps, 0, 200, 1)}
        ${select('encoding', 'audio', '音轨', encoding.audio, [['aac', '保留 · AAC 192 kbps'], ['mute', '移除音轨']])}
        <dl class="desk-topaz-video-workbench__codec-list"><div><dt>容器</dt><dd>MP4</dd></div><div><dt>分辨率</dt><dd>${width ? `${width} × ${height}` : '等待素材'}</dd></div>
        <div><dt>帧率</dt><dd>${timing.fps} fps</dd></div><div><dt>全片时长</dt><dd>${timing.duration.toFixed(2)} 秒${timing.slowmo > 1 ? ` · ${timing.slowmo}× 慢动作` : ''}</dd></div>
        <div><dt>色彩</dt><dd>${node.videoFilters.hdr.enabled ? 'BT.2020 · PQ · 1000 nits' : 'SDR'}</dd></div></dl>
        <p>慢动作同步延长音轨、保留音高。预览只处理选区，导出可选择全片或选区；预览结果不会替换画布下游。</p>
        ${status?.encoding ? '' : '<p class="is-unavailable">后端尚未加载新版编码能力，请更新并刷新运行时。</p>'}</section>`;
    }
    function change(input) {
      const group = input.dataset.tvwbProcessing, key = input.dataset.tvwbKey;
      if (!group || !key) return null;
      let value = input.type === 'checkbox' ? input.checked : input.value;
      if (input.type === 'number' || ['slowmo', 'strength', 'reduceJitter'].includes(key)) value = input.value === '' ? NaN : Number(input.value);
      return {processing: {group, key, value}};
    }
    return Object.freeze({filters, output, toggle, change});
  }
  window.DesktopTopazVideoInspector = Object.freeze({create});
})();

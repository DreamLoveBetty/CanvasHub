// Pure workflow processing state / snake_case adapter. No DOM, jobs or API calls.
(function () {
  const definitions = Object.freeze({
    denoise: {enabled: false, noise: 0, details: 0},
    interpolation: {enabled: false, model: 'chf-3', fps: 60, slowmo: 1, rdt: .01},
    stabilization: {enabled: false, mode: 'auto_crop', strength: 6, rollingShutter: false, reduceJitter: 0},
    motionDeblur: {enabled: false, model: 'thm-2'},
    hdr: {enabled: false, model: 'hyp-2', strength: 1},
  });
  const defaults = Object.freeze({codec: 'h264', bitrateMbps: 0, audio: 'aac'});
  const backendKeys = Object.freeze({motionDeblur: 'motion_deblur', rollingShutter: 'rolling_shutter', reduceJitter: 'reduce_jitter', bitrateMbps: 'bitrate_mbps'});
  const object = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const pick = (source, template) => Object.fromEntries(Object.entries(template).map(([key, value]) =>
    [key, typeof source[key] === typeof value && (typeof value !== 'number' || Number.isFinite(source[key])) ? source[key] : value]));
  function normalize(node) {
    node.enhancementEnabled = node.enhancementEnabled !== false;
    const previous = object(node.videoFilters);
    node.videoFilters = Object.fromEntries(Object.entries(definitions).map(([key, value]) => [key, pick(object(previous[key]), value)]));
    node.encodingOptions = pick(object(node.encodingOptions), defaults);
    return node;
  }
  function capability(status, group) {return status?.capabilities?.[backendKeys[group] || group] || {};}
  function validateEncoding(encoding) {
    if (!['h264', 'hevc', 'hevc10'].includes(encoding.codec) || !['aac', 'mute'].includes(encoding.audio)
        || !Number.isFinite(encoding.bitrateMbps) || encoding.bitrateMbps < 0 || encoding.bitrateMbps > 200) throw new Error('编码设置无效');
  }
  function validate(group, values) {
    const between = (key, low, high, integer = false) => {
      if (!Number.isFinite(values[key]) || values[key] < low || values[key] > high || (integer && !Number.isInteger(values[key]))) throw new Error(key + ' 超出有效范围');
    };
    if (group === 'denoise') {between('noise', 0, 1); between('details', 0, 1);}
    else if (group === 'interpolation') {
      if (!['chf-3', 'chr-2', 'apo-8', 'apf-2'].includes(values.model)) throw new Error('未知补帧模型');
      between('fps', 0, 120); if (values.fps > 0 && values.fps < 1) throw new Error('帧率至少为 1');
      between('slowmo', 1, 16); between('rdt', -.01, .2);
    } else if (group === 'stabilization') {
      if (!['auto_crop', 'full_frame'].includes(values.mode)) throw new Error('未知稳定模式');
      between('strength', 0, 16); between('reduceJitter', 0, 5, true);
    } else if (group === 'hdr' && ![.7, 1, 1.3].includes(values.strength)) throw new Error('Hyperion 强度无效');
  }
  function request(node, status) {
    const filters = {};
    for (const [group, template] of Object.entries(definitions)) {
      const value = {...template, ...object(node.videoFilters?.[group])};
      if (!value.enabled) continue;
      validate(group, value);
      const cap = capability(status, group);
      if (!cap.available) throw new Error(cap.reason || '请刷新本地运行时，确认滤镜资源已就绪');
      if (group === 'interpolation' && !cap.models?.some(item => item.id === value.model && item.available)) throw new Error('所选补帧模型尚未就绪');
      if (group === 'stabilization') {
        if (value.mode === 'full_frame' && !cap.full_frame) throw new Error('全帧稳定权重尚未就绪');
        if ((value.rollingShutter || value.reduceJitter) && !cap.jitter) throw new Error('抖动修复需要 Chronos Fast 和 IFI 权重');
      }
      filters[backendKeys[group] || group] = Object.fromEntries(Object.entries(value).filter(([key]) => key !== 'enabled')
        .map(([key, value]) => [backendKeys[key] || key, value]));
    }
    const encoding = {...defaults, ...object(node.encodingOptions)};
    validateEncoding(encoding);
    if (filters.hdr && encoding.codec !== 'hevc10') throw new Error('HDR 输出需要 H.265 10-bit');
    if (node.enhancementEnabled === false && !status?.processing_ready) throw new Error('本地视频运行时尚未就绪');
    if (!Object.keys(filters).length && node.enhancementEnabled !== false && JSON.stringify(encoding) === JSON.stringify(defaults)) return {};
    if (!status?.encoding) throw new Error('后端尚未加载新版处理链，请更新运行时后重试');
    return {enhancement: node.enhancementEnabled !== false, filters,
      encoding: {codec: encoding.codec, bitrate_mbps: encoding.bitrateMbps, audio: encoding.audio}};
  }
  function patch(node, change, status) {
    normalize(node);
    const {group, key, value} = change;
    if (group === 'enhancement') {node.enhancementEnabled = value === true; return;}
    if (group === 'encoding') {
      if (!Object.hasOwn(defaults, key)) return;
      if (key === 'codec' && node.videoFilters.hdr.enabled && value !== 'hevc10') throw new Error('请先关闭 HDR，再切换到 8-bit 编码');
      const next = {...node.encodingOptions, [key]: value};
      validateEncoding(next);
      node.encodingOptions = next; return;
    }
    if (!definitions[group] || !Object.hasOwn(definitions[group], key)) return;
    if (key === 'enabled' && value && !capability(status, group).available) throw new Error(capability(status, group).reason || '滤镜资源尚未就绪');
    const next = {...node.videoFilters[group], [key]: value};
    validate(group, next);
    node.videoFilters[group] = next;
    if (group === 'hdr' && next.enabled) node.encodingOptions.codec = 'hevc10';
  }
  function timing(node, source) {
    const interpolation = node.videoFilters?.interpolation;
    const slowmo = interpolation?.enabled ? Number(interpolation.slowmo) || 1 : 1;
    return {fps: interpolation?.enabled ? Number(interpolation.fps) || Number(source?.fps) || 30 : Number(source?.fps) || 30,
      slowmo, duration: (Number(source?.duration) || 0) * slowmo};
  }
  window.DesktopTopazVideoPipeline = Object.freeze({normalize, request, patch, capability, timing});
})();

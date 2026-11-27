// Authenticated transport for Kandinsky ImageSR 2.0 (/api/kandinsky_sr/*).
(function () {
  const preparation = raw => ({
    status: String(raw?.status || 'idle'),
    stage: String(raw?.stage || ''),
    message: String(raw?.message || ''),
    downloaded: Number(raw?.downloaded || 0),
    total: Number(raw?.total || 0),
  });

  function status() {
    return api.json('/api/kandinsky_sr/status').then(data => ({
      ok: Boolean(data?.ok),
      engine: String(data?.engine || ''),
      modelVariant: String(data?.model_variant || 'Kandinsky ImageSR 2.0'),
      ready: Boolean(data?.ready),
      reasons: Array.isArray(data?.reasons) ? data.reasons.map(String) : [],
      preparedAt: Number(data?.prepared_at || 0),
      downloadBytes: Number(data?.download_bytes || 0),
      preparation: preparation(data?.preparation),
      models: Array.isArray(data?.models) ? data.models : [],
    }));
  }

  function prepare() {
    return api.json('/api/kandinsky_sr/prepare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    }).then(data => ({
      preparation: preparation(data?.preparation),
      alreadyRunning: Boolean(data?.already_running),
    }));
  }

  async function submit(client, { config, images, lineage, telegramEnabled }) {
    if (!Array.isArray(images) || images.length !== 1) {
      throw new Error('请连接一张图片到 Kandinsky SR 节点');
    }
    const rawOptions = config?.params?.kandinsky_sr || {};
    const options = window.DesktopKandinskySrModel?.normalizeOptions
      ? window.DesktopKandinskySrModel.normalizeOptions(rawOptions)
      : {
          upscale_factor: Number(rawOptions.upscale_factor || 2),
          creativity: Number(rawOptions.creativity ?? 4),
          overlap: Number(rawOptions.overlap || 0.25),
        };
    return client.json('/api/kandinsky_sr/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt: config?.prompt || 'Kandinsky SR 2.0 超分',
        model: config?.params?.model || 'kandinsky-imagesr-2.0',
        options,
        images,
        telegram_enabled: telegramEnabled === true,
        ...(lineage ? { lineage } : {}),
      }),
    });
  }

  window.DesktopKandinskySrAPI = Object.freeze({
    status,
    prepare,
    submit,
  });
})();

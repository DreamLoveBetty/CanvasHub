// The gallery's video folder: generated and imported video resources, the source switch,
// folder cards with their expandable detail and playback, sending a video to the canvas,
// and the video stats line. desktop-history.js owns the gallery view, search and grid;
// it passes them in explicitly and reads video state only through the returned API.
(function () {
  function create({
    closeGallery, coercePositiveNumber, copyPinterestSplitText, els, escapeHtml,
    formatFileSize, formatTime, inferOrientation, mediaUrl, normalizeEpochSeconds,
    normalizeImageFormat, orientationLabel, renderGalleryStats, scheduleGalleryRender,
    getGalleryView, getGalleryQuery
  }) {
    let galleryVideos = [];
    let galleryVideoStats = {};
    let galleryVideoSource = 'generated';
    let galleryVideosLoading = false;
    let galleryVideosError = '';
    let galleryVideoRequestId = 0;
    let expandedGalleryVideoId = '';

    function normalizeGalleryVideoResource(item, index = 0) {
      const type = String(item?.type || item?.kind || 'file').trim().toLowerCase();
      const name = String(item?.file_name || item?.fileName || item?.name || `资源 ${index + 1}`);
      const url = String(item?.resource_url || item?.resourceUrl || item?.url || '');
      return {
        ...item,
        id: String(item?.id || item?.resource_id || item?.resourceId || `${type}:${name}:${index}`),
        type,
        role: String(item?.role || ''),
        label: String(item?.label || (type === 'video' ? '视频' : (type === 'image' ? '参考图片' : '附件'))),
        name,
        url,
        mimeType: String(item?.mime_type || item?.mimeType || ''),
        fileSize: coercePositiveNumber(item?.file_size_bytes || item?.fileSizeBytes || item?.file_size || item?.fileSize),
        modifiedAt: normalizeEpochSeconds(item?.modified_at || item?.modifiedAt || item?.created_at || item?.createdAt)
      };
    }

    function normalizeGalleryVideo(item) {
      const mediaName = String(item?.media_name || item?.mediaName || item?.file_name || item?.filename || item?.name || item?.file || '视频资产');
      const relativePath = String(item?.relative_path || item?.relativePath || item?.archive_rel_path || item?.archiveRelPath || '');
      const mediaUrl = String(item?.media_url || item?.mediaUrl || item?.video_url || item?.videoUrl || item?.url || '');
      const rawSourceType = String(item?.source_type || item?.sourceType || item?.asset_source || item?.assetSource || '').trim().toLowerCase();
      const sourceType = rawSourceType === 'imported' || rawSourceType === 'generated'
        ? rawSourceType
        : (item?.is_generated === true || item?.isGenerated === true ? 'generated' : 'imported');
      const sourceLabel = String(item?.source_label || item?.sourceLabel || (sourceType === 'generated' ? '生成视频' : '导入素材'));
      const mediaWidth = coercePositiveNumber(item?.media_width || item?.mediaWidth || item?.width);
      const mediaHeight = coercePositiveNumber(item?.media_height || item?.mediaHeight || item?.height);
      const fileSize = coercePositiveNumber(item?.file_size || item?.fileSize || item?.size_bytes || item?.size);
      const durationSeconds = coercePositiveNumber(item?.duration_seconds || item?.durationSeconds || item?.duration);
      const fps = coercePositiveNumber(item?.fps || item?.frame_rate) || 24;
      const orientation = inferOrientation(mediaWidth, mediaHeight, item?.orientation);
      const resources = (Array.isArray(item?.resources) ? item.resources : [])
        .map(normalizeGalleryVideoResource)
        .filter(resource => resource.id && resource.name);
      const parameters = item?.parameters && typeof item.parameters === 'object' && !Array.isArray(item.parameters)
        ? { ...item.parameters }
        : {};
      const resourceFolder = item?.resource_folder && typeof item.resource_folder === 'object'
        ? { ...item.resource_folder }
        : {};
      return {
        ...item,
        id: String(item?.video_id || item?.videoId || item?.id || relativePath || mediaName),
        mediaUrl,
        posterUrl: String(item?.poster_url || item?.posterUrl || ''),
        mediaName,
        mimeType: String(item?.mime_type || item?.mimeType || 'video/mp4'),
        sourceTaskId: String(item?.source_task_id || item?.sourceTaskId || item?.task_id || item?.taskId || ''),
        createdAt: normalizeEpochSeconds(item?.created_at || item?.createdAt || item?.modified_at || item?.modifiedAt || item?.timestamp),
        durationSeconds,
        mediaWidth,
        mediaHeight,
        fps,
        fileSize,
        fileSizeLabel: String(item?.file_size_label || item?.fileSizeLabel || formatFileSize(fileSize)),
        relativePath,
        prompt: String(item?.prompt || ''),
        subject: String(item?.subject || item?.prompt_subject || item?.promptSubject || ''),
        parameters,
        resources,
        resourceCount: Math.max(resources.length, Number(item?.resource_count || item?.resourceCount || 0)),
        resourceFolder,
        hasPrompt: item?.has_prompt === true || item?.hasPrompt === true || Boolean(item?.prompt),
        hasParameters: item?.has_parameters === true || item?.hasParameters === true || Boolean(Object.keys(parameters).length),
        hasReferenceImages: item?.has_reference_images === true || item?.hasReferenceImages === true || resources.some(resource => resource.type === 'image'),
        sourceType,
        sourceLabel,
        isGenerated: sourceType === 'generated',
        orientation,
        orientationLabel: orientationLabel(orientation),
        format: normalizeImageFormat(item?.format, mediaName) || 'VIDEO'
      };
    }

    function getVisibleGalleryVideos() {
      const query = getGalleryQuery().trim().toLowerCase();
      return galleryVideos.filter(item => {
        if (!query) return true;
        const haystack = [
          item.mediaName,
          item.relativePath,
          item.prompt,
          JSON.stringify(item.parameters || {}),
          ...(item.resources || []).flatMap(resource => [resource.name, resource.label]),
          item.sourceTaskId,
          item.mimeType,
          item.format,
          item.orientationLabel,
          item.mediaWidth && item.mediaHeight ? `${item.mediaWidth}x${item.mediaHeight}` : '',
          item.mediaWidth && item.mediaHeight ? `${item.mediaWidth}×${item.mediaHeight}` : ''
        ].filter(Boolean).join(' ').toLowerCase();
        return haystack.includes(query);
      });
    }

    function galleryVideoSourceCounts() {
      const stats = galleryVideoStats || {};
      const raw = stats.by_source && typeof stats.by_source === 'object'
        ? stats.by_source
        : (stats.source_counts && typeof stats.source_counts === 'object' ? stats.source_counts : {});
      const generated = Number(raw.generated ?? stats.generated_count ?? galleryVideos.filter(item => item.isGenerated).length);
      const imported = Number(raw.imported ?? stats.imported_count ?? galleryVideos.filter(item => !item.isGenerated).length);
      const all = Number(raw.all ?? stats.total_all ?? stats.all_count ?? (generated + imported));
      return {
        generated: Number.isFinite(generated) ? generated : 0,
        imported: Number.isFinite(imported) ? imported : 0,
        all: Number.isFinite(all) ? all : 0
      };
    }

    function renderGalleryVideoSourceSwitch() {
      const control = els.deskGalleryVideoSource;
      if (!control) return;
      const visible = getGalleryView() === 'videos';
      control.hidden = !visible;
      if (!visible) return;
      const counts = galleryVideoSourceCounts();
      control.querySelectorAll('[data-gallery-video-source]').forEach(button => {
        const source = button.dataset.galleryVideoSource || 'generated';
        const active = source === galleryVideoSource;
        button.classList.toggle('is-active', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
      control.querySelectorAll('[data-gallery-video-source-count]').forEach(output => {
        const source = output.dataset.galleryVideoSourceCount || 'all';
        output.textContent = Number(counts[source] || 0).toLocaleString('zh-CN');
      });
    }

    function formatGalleryVideoDuration(seconds) {
      const total = Math.max(0, Math.round(Number(seconds || 0)));
      if (!total) return '';
      const hours = Math.floor(total / 3600);
      const minutes = Math.floor((total % 3600) / 60);
      const remainder = total % 60;
      return hours
        ? `${hours}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`
        : `${minutes}:${String(remainder).padStart(2, '0')}`;
    }

    function galleryVideoAccelerationLabel(value) {
      return ({
        off: '标准模式',
        first_block_cache: 'FirstBlockCache',
        sol_attn: 'Sol-Attn',
        combined: 'FirstBlockCache + Sol-Attn'
      })[String(value || '')] || String(value || '');
    }

    function galleryVideoParameterEntries(video) {
      const params = video.parameters || {};
      const width = Number(params.width || video.mediaWidth || 0);
      const height = Number(params.height || video.mediaHeight || 0);
      const pixelBudget = Number(params.pixel_budget_mp || 0);
      const actualMp = Number(params.actual_megapixels || 0);
      const duration = Number(params.duration_seconds || video.durationSeconds || 0);
      const fps = Number(params.fps || video.fps || 0);
      const elapsed = Number(params.elapsed_seconds || 0);
      const mode = ({ image_to_video: '图生视频', reference_to_video: '参考驱动' })[params.mode] || params.mode;
      const quality = pixelBudget
        ? `${pixelBudget.toFixed(1)} MP${actualMp ? ` · 实际 ${actualMp.toFixed(3)} MP` : ''}`
        : '';
      return [
        ['模式', mode],
        ['画幅', params.aspect_ratio],
        ['质量', quality],
        ['分辨率', width && height ? `${width}×${height}` : ''],
        ['时长', duration ? `${Number(duration.toFixed(3))} 秒` : ''],
        ['采样步数', params.steps],
        ['去噪强度', params.denoise],
        ['CRF', params.crf],
        ['随机种子', params.seed],
        ['加速模式', galleryVideoAccelerationLabel(params.acceleration_mode)],
        ['缓存阈值', params.first_block_cache_threshold],
        ['帧率', fps ? `${Number(fps.toFixed(2))} fps` : ''],
        ['帧数', params.frame_count],
        ['生成用时', elapsed ? formatGalleryVideoDuration(elapsed) : '']
      ].filter(([, value]) => value !== '' && value !== null && value !== undefined);
    }

    function renderGalleryVideoResource(resource) {
      const rawType = String(resource.type || 'file');
      const type = ['video', 'image', 'text', 'markdown'].includes(rawType) ? rawType : 'file';
      const url = mediaUrl(resource.url);
      const extension = String(resource.name || '').split('.').pop()?.slice(0, 5).toUpperCase() || '文件';
      const preview = type === 'image' && url
        ? `<img src="${escapeHtml(url)}" alt="" loading="lazy">`
        : `<strong>${escapeHtml(extension)}</strong>`;
      const body = `
      <span class="desk-gallery-video-resource__preview" data-resource-type="${escapeHtml(type)}">${preview}</span>
      <span class="desk-gallery-video-resource__copy">
        <strong>${escapeHtml(resource.label || '资源文件')}</strong>
        <span title="${escapeHtml(resource.name)}">${escapeHtml(resource.name)}</span>
        <em>${escapeHtml(formatFileSize(resource.fileSize) || resource.mimeType || '')}</em>
      </span>`;
      return url
        ? `<a class="desk-gallery-video-resource" href="${escapeHtml(url)}" target="_blank" rel="noopener">${body}</a>`
        : `<div class="desk-gallery-video-resource">${body}</div>`;
    }

    function galleryVideoSubject(video) {
      const prompt = String(video?.prompt || '').replace(/\s+/g, ' ').trim();
      const commonSubjects = [
        '机甲女战士', '机甲男战士', '东亚成熟女性', '东亚成年女性', '成熟女性',
        '成年女性', '年轻女性', '年轻男子', '女战士', '男战士', '机器人', '机械角色',
        '女性角色', '男性角色', '少女', '少年', '女性', '男性', '人物', '角色',
        '橘猫', '黑猫', '白猫', '猫', '狗', '汽车', '建筑', '城市', '产品'
      ];
      const compact = value => {
        let subject = String(value || '')
          .replace(/[“”"'`]/g, '')
          .replace(/^(?:参考图|图中|画面中|镜头中|视频中|同一位|一位|一名|一个|一只|一台|一辆)\s*/i, '')
          .replace(/^(?:气质优雅的|漂亮的|美丽的|年轻的|年长的|可爱的|高大的|身材高挑的)/, '')
          .replace(/(?:的)?(?:脚部|手部|脸部|面部|头部|胸部|腰部|身体|全身|背部|眼睛|动作|姿态|服装|周围|身后|面前|特写).*$/, '')
          .replace(/^[\s，。；：,:;!！?？]+|[\s，。；：,:;!！?？]+$/g, '')
          .trim();
        if (!subject) return '';
        if (Array.from(subject).length > 12) {
          const known = commonSubjects.find(candidate => subject.includes(candidate));
          if (known) subject = known;
        }
        return Array.from(subject).slice(0, 12).join('');
      };
      const explicit = compact(video?.subject);
      if (explicit) return explicit;
      if (prompt) {
        const contextualPatterns = [
          /(?:参考图|图中|画面中|镜头中|视频中)\s*([^，。；！？,:;!\n]{2,24}?)(?=的(?:脚|手|脸|面部|头|胸|腰|身体|全身|背|眼|动作|姿态|服装|周围|身后|面前|特写)|正在|穿着|站在|坐在|走在|跑向|[，。；！？,:;!\n]|$)/i,
          /(?:主体|主角)\s*(?:为|是|：|:)\s*([^，。；！？,:;!\n]{2,24})/i,
          /(?:一位|一名|一个|一只|一台|一辆)\s*([^，。；！？,:;!\n]{2,24}?)(?=正在|穿着|站在|坐在|走在|跑向|[，。；！？,:;!\n]|$)/i,
          /\b(?:a|an|the)\s+([a-z][a-z -]{2,32}?)(?=\s+(?:in|with|wearing|standing|sitting)|[,.;!?]|$)/i
        ];
        for (const pattern of contextualPatterns) {
          const match = prompt.match(pattern);
          const subject = compact(match?.[1]);
          if (subject) return subject;
        }
        const known = commonSubjects.find(candidate => prompt.includes(candidate));
        if (known) return known;
      }
      if (!video?.isGenerated) {
        const name = String(video?.mediaName || '').replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ');
        const fallback = compact(name);
        if (fallback && !/^h3\b/i.test(fallback)) return fallback;
      }
      return video?.isGenerated ? '视频任务' : '视频素材';
    }

    function renderGalleryVideoFolderVisual(video) {
      const posterUrl = mediaUrl(video.posterUrl);
      const sourceUrl = mediaUrl(video.mediaUrl);
      const folderTitle = galleryVideoSubject(video);
      const coverLabel = video.isGenerated ? 'MiniMax H3' : 'Video asset';
      const listIndex = galleryVideos.findIndex(item => item.id === video.id);
      const caseNumber = String(listIndex >= 0 ? listIndex + 1 : 1).padStart(2, '0').slice(-2);
      const frame = posterUrl
        ? `<img src="${escapeHtml(posterUrl)}" alt="" loading="lazy" decoding="async">`
        : (sourceUrl
          ? `<video src="${escapeHtml(sourceUrl)}" muted playsinline preload="metadata" tabindex="-1" aria-hidden="true"></video>`
          : '<i></i>');
      return `
      <span class="desk-gallery-video-folder__visual" aria-hidden="true">
        <span class="desk-gallery-video-folder__back">
          ${frame}
          <em>${escapeHtml(coverLabel)}</em>
        </span>
        <span class="desk-gallery-video-folder__face">
          <svg class="desk-gallery-video-folder__face-shape" viewBox="0 0 100 77" preserveAspectRatio="none" shape-rendering="geometricPrecision" aria-hidden="true" focusable="false">
            <path d="M0 12.32H58.6Q59.4 12.32 59.8 11.627L65.8 .77Q66.2 0 67.2 0H100V77H0Z" shape-rendering="geometricPrecision"></path>
          </svg>
          <span class="desk-gallery-video-folder__case"><i>CASE</i><b>${escapeHtml(caseNumber)}</b></span>
          <strong title="${escapeHtml(folderTitle)}">${escapeHtml(folderTitle)}</strong>
          <span>${video.resourceCount || 1} 个文件 · ${escapeHtml(video.sourceLabel || '视频资产')}</span>
        </span>
      </span>`;
    }

    function renderGalleryVideoDetails(video) {
      const source = mediaUrl(video.mediaUrl);
      const poster = mediaUrl(video.posterUrl);
      const parameters = galleryVideoParameterEntries(video);
      const resources = video.resources || [];
      const detailId = `desk-gallery-video-detail-${video.id}`;
      const resourceNote = video.isGenerated && !video.hasReferenceImages
        ? '该历史任务未归档参考图'
        : (resources.length === 1 ? '仅视频文件' : '');
      return `
      <section class="desk-gallery-video-detail" id="${escapeHtml(detailId)}" aria-label="${escapeHtml(video.mediaName)} 资源详情">
        <div class="desk-gallery-video-detail__content">
          <div class="desk-gallery-video-detail__media">
            ${source
              ? `<video controls playsinline preload="metadata" src="${escapeHtml(source)}"${poster ? ` poster="${escapeHtml(poster)}"` : ''} aria-label="播放 ${escapeHtml(video.mediaName)}"></video>`
              : '<div class="desk-gallery-video__missing">视频不可用</div>'}
            <div class="desk-gallery-video__actions">
              <button type="button" data-gallery-video-canvas="${escapeHtml(video.id)}"${source ? '' : ' disabled'}>到画布</button>
              ${source ? `<a href="${escapeHtml(source)}" target="_blank" rel="noopener">打开视频</a>` : ''}
            </div>
          </div>
          <div class="desk-gallery-video-detail__info">
            <section class="desk-gallery-video-prompt">
              <header><strong>提示词</strong>${video.prompt ? `<button type="button" data-gallery-video-copy-prompt="${escapeHtml(video.id)}">复制</button>` : ''}</header>
              ${video.prompt
                ? `<p>${escapeHtml(video.prompt)}</p>`
                : `<p class="is-empty">${video.isGenerated ? '未找到提示词侧车' : '导入素材没有提示词'}</p>`}
            </section>
            <section class="desk-gallery-video-parameters">
              <header><strong>${video.isGenerated ? '生成参数' : '媒体信息'}</strong><span>${parameters.length} 项</span></header>
              ${parameters.length
                ? `<dl>${parameters.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd title="${escapeHtml(String(value))}">${escapeHtml(String(value))}</dd></div>`).join('')}</dl>`
                : '<p>暂无可用参数</p>'}
            </section>
            <section class="desk-gallery-video-resources">
              <header><strong>资源文件</strong><span>${resources.length} 个${resourceNote ? ` · ${escapeHtml(resourceNote)}` : ''}</span></header>
              <div>${resources.map(renderGalleryVideoResource).join('') || '<p>没有可用的归档文件</p>'}</div>
            </section>
          </div>
        </div>
      </section>`;
    }

    function renderGalleryVideoCard(video) {
      const isExpanded = video.id === expandedGalleryVideoId;
      const detailId = `desk-gallery-video-detail-${video.id}`;
      const dimensions = video.mediaWidth && video.mediaHeight ? `${video.mediaWidth}×${video.mediaHeight}` : '';
      const duration = formatGalleryVideoDuration(video.durationSeconds);
      const primaryMeta = [dimensions, duration, video.fileSizeLabel].filter(Boolean).join(' · ') || '归档视频';
      return `
      <article class="desk-gallery-video${isExpanded ? ' is-expanded' : ''}" data-video-id="${escapeHtml(video.id)}">
        <button class="desk-gallery-video-folder" type="button" data-gallery-video-toggle="${escapeHtml(video.id)}" aria-expanded="${isExpanded ? 'true' : 'false'}" aria-controls="${escapeHtml(detailId)}">
          ${renderGalleryVideoFolderVisual(video)}
          <span class="desk-gallery-video__body">
            <strong title="${escapeHtml(video.mediaName)}">${escapeHtml(video.mediaName)}</strong>
            <span>${escapeHtml(primaryMeta)}</span>
            <em>${escapeHtml([video.sourceLabel, formatTime(video.createdAt)].filter(Boolean).join(' · '))}</em>
          </span>
          ${isExpanded ? '<span class="desk-gallery-video-folder__collapse">收起</span>' : ''}
        </button>
        ${isExpanded ? renderGalleryVideoDetails(video) : ''}
      </article>`;
    }

    function findGalleryVideo(id) {
      return galleryVideos.find(item => item.id === id || item.relativePath === id);
    }

    function sendGalleryVideoToCanvas(video, button) {
      if (!video?.mediaUrl) throw new Error('视频资产没有可播放地址');
      if (!window.DesktopCanvas?.createVideoNodeFromAsset) throw new Error('画布视频节点尚未就绪');
      if (button) button.disabled = true;
      window.DesktopCanvas.createVideoNodeFromAsset(video);
      closeGallery();
      DesktopResults.showTransientMessage('视频已发送到画布。');
    }

    function patchGalleryVideoCards(ids) {
      const grid = els.deskGalleryGrid;
      if (!grid) return false;
      const uniqueIds = [...new Set((ids || []).filter(Boolean))];
      if (!uniqueIds.length) return false;
      let replaced = 0;
      uniqueIds.forEach(id => {
        const video = findGalleryVideo(id);
        const current = grid.querySelector(`[data-video-id="${CSS.escape(id)}"]`);
        if (!video || !current) return;
        const template = document.createElement('template');
        template.innerHTML = renderGalleryVideoCard(video).trim();
        const replacement = template.content.firstElementChild;
        if (!replacement) return;
        current.replaceWith(replacement);
        replaced += 1;
      });
      if (replaced) bindGalleryVideoEvents();
      return replaced === uniqueIds.length;
    }

    function bindGalleryVideoEvents() {
      els.deskGalleryGrid?.querySelectorAll('[data-gallery-video-toggle]').forEach(button => {
        if (button.dataset.videoToggleBound === '1') return;
        button.dataset.videoToggleBound = '1';
        button.addEventListener('click', event => {
          event.preventDefault();
          event.stopPropagation();
          const id = button.dataset.galleryVideoToggle || '';
          const previousId = expandedGalleryVideoId;
          expandedGalleryVideoId = expandedGalleryVideoId === id ? '' : id;
          if (!patchGalleryVideoCards([previousId, expandedGalleryVideoId || id])) renderGalleryVideos();
          window.requestAnimationFrame(() => {
            const article = els.deskGalleryGrid?.querySelector(`[data-video-id="${CSS.escape(id)}"]`);
            article?.querySelector('.desk-gallery-video-folder')?.focus?.({ preventScroll: true });
            if (expandedGalleryVideoId) {
              els.deskGalleryGrid?.querySelector(`[data-video-id="${CSS.escape(expandedGalleryVideoId)}"]`)?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
            }
          });
        });
      });
      els.deskGalleryGrid?.querySelectorAll('[data-gallery-video-canvas]').forEach(button => {
        if (button.dataset.videoCanvasBound === '1') return;
        button.dataset.videoCanvasBound = '1';
        button.addEventListener('click', () => {
          try {
            sendGalleryVideoToCanvas(findGalleryVideo(button.dataset.galleryVideoCanvas || ''), button);
          } catch (error) {
            button.disabled = false;
            DesktopResults.showError(error);
          }
        });
      });
      els.deskGalleryGrid?.querySelectorAll('[data-gallery-video-copy-prompt]').forEach(button => {
        if (button.dataset.videoPromptBound === '1') return;
        button.dataset.videoPromptBound = '1';
        button.addEventListener('click', () => {
          const video = findGalleryVideo(button.dataset.galleryVideoCopyPrompt || '');
          copyPinterestSplitText(video?.prompt || '')
            .then(() => DesktopResults.showTransientMessage('提示词已复制。'))
            .catch(error => DesktopResults.showError(error));
        });
      });
    }

    function renderGalleryVideos() {
      const grid = els.deskGalleryGrid;
      if (!grid) return;
      if (galleryVideosLoading && !galleryVideos.length) {
        grid.innerHTML = '<div class="desk-gallery-empty">正在扫描视频资产...</div>';
        return;
      }
      if (galleryVideosError && !galleryVideos.length) {
        grid.innerHTML = `<div class="desk-gallery-empty">${escapeHtml(galleryVideosError)}</div>`;
        return;
      }
      const videos = getVisibleGalleryVideos();
      if (!videos.length) {
        const emptyLabel = galleryVideoSource === 'generated'
          ? '暂无生成视频'
          : (galleryVideoSource === 'imported' ? '暂无导入素材' : '没有匹配的视频资产');
        grid.innerHTML = `<div class="desk-gallery-empty">${escapeHtml(emptyLabel)}</div>`;
        return;
      }
      grid.innerHTML = videos.map(renderGalleryVideoCard).join('');
      bindGalleryVideoEvents();
    }

    async function loadGalleryVideos(options = {}) {
      if (!DesktopApi.listVideoAssets) return galleryVideos;
      const requestId = ++galleryVideoRequestId;
      galleryVideosLoading = true;
      galleryVideosError = '';
      if (options.reset === true) galleryVideos = [];
      if (getGalleryView() === 'videos') scheduleGalleryRender({ selection: true });
      try {
        const data = await DesktopApi.listVideoAssets({
          limit: 500,
          offset: 0,
          query: getGalleryQuery(),
          source: galleryVideoSource,
          refresh: options.refresh === true
        });
        if (requestId !== galleryVideoRequestId) return galleryVideos;
        galleryVideos = (Array.isArray(data.videos) ? data.videos : (Array.isArray(data.items) ? data.items : []))
          .map(normalizeGalleryVideo)
          .filter(item => item.id && item.mediaUrl);
        if (expandedGalleryVideoId && !galleryVideos.some(item => item.id === expandedGalleryVideoId)) {
          expandedGalleryVideoId = '';
        }
        galleryVideoStats = {
          ...(data.stats || {}),
          source_counts: data.source_counts || data.stats?.source_counts || data.stats?.by_source || {},
          source_filter: data.source || data.source_filter || galleryVideoSource
        };
        return galleryVideos;
      } catch (error) {
        if (requestId !== galleryVideoRequestId) return galleryVideos;
        galleryVideosError = String(error?.message || error || '视频资产加载失败');
        throw error;
      } finally {
        if (requestId === galleryVideoRequestId) {
          galleryVideosLoading = false;
          if (getGalleryView() === 'videos') scheduleGalleryRender({ selection: true });
        }
      }
    }

    function bindGalleryVideoSourceEvents() {
      els.deskGalleryVideoSource?.addEventListener('click', event => {
        const button = event.target.closest?.('[data-gallery-video-source]');
        if (!button || getGalleryView() !== 'videos') return;
        const nextSource = button.dataset.galleryVideoSource || 'generated';
        if (!['generated', 'imported', 'all'].includes(nextSource) || nextSource === galleryVideoSource) return;
        expandedGalleryVideoId = '';
        galleryVideoSource = nextSource;
        renderGalleryVideoSourceSwitch();
        renderGalleryStats();
        loadGalleryVideos({ reset: true }).catch(error => DesktopResults.showError(error));
      });
    }

    function renderGalleryVideoStats() {
      const visible = getVisibleGalleryVideos();
      const stats = galleryVideoStats || {};
      const sourceCounts = galleryVideoSourceCounts();
      const formats = stats.by_format && typeof stats.by_format === 'object' ? stats.by_format : {};
      const totalBytes = Number(stats.total_file_size_bytes || stats.total_size_bytes || stats.totalSizeBytes || galleryVideos.reduce((sum, item) => sum + Number(item.fileSize || 0), 0));
      const total = Number(stats.total ?? galleryVideos.length).toLocaleString('zh-CN');
      const mp4Count = Number(formats.mp4 ?? galleryVideos.filter(item => item.format === 'MP4').length).toLocaleString('zh-CN');
      const landscapeCount = galleryVideos.filter(item => item.orientation === 'landscape').length.toLocaleString('zh-CN');
      const portraitCount = galleryVideos.filter(item => item.orientation === 'portrait').length.toLocaleString('zh-CN');
      els.deskGalleryStats.innerHTML = [
        `${galleryVideoSource === 'generated' ? '生成视频' : (galleryVideoSource === 'imported' ? '导入素材' : '全部视频')} ${total}`,
        `当前 ${visible.length.toLocaleString('zh-CN')}`,
        `生成 ${sourceCounts.generated.toLocaleString('zh-CN')}`,
        `导入 ${sourceCounts.imported.toLocaleString('zh-CN')}`,
        `MP4 ${mp4Count}`,
        `横屏 ${landscapeCount}`,
        `竖屏 ${portraitCount}`,
        totalBytes ? `总计 ${formatFileSize(totalBytes)}` : null
      ].filter(Boolean).map(item => `<span>${escapeHtml(item)}</span>`).join('');
    }

    function collapseExpandedGalleryVideo() {
      expandedGalleryVideoId = '';
    }

    return {
      load: loadGalleryVideos,
      render: renderGalleryVideos,
      renderSourceSwitch: renderGalleryVideoSourceSwitch,
      renderStats: renderGalleryVideoStats,
      bindSourceSwitchEvents: bindGalleryVideoSourceEvents,
      visibleVideos: getVisibleGalleryVideos,
      source: () => galleryVideoSource,
      collapseExpanded: collapseExpandedGalleryVideo
    };
  }

  window.DesktopGalleryVideos = { create };
})();

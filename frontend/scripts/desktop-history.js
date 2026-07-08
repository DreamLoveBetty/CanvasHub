(function () {
  const els = {};
  let lastHistoryDragAt = 0;
  let galleryView = 'images';
  let galleryFilter = 'all';
  let galleryQuery = '';
  let galleryTag = '';
  let galleryAssets = [];
  let gallerySets = [];
  let galleryFiles = [];
  let galleryFileStats = {};
  let promptSources = [];
  let promptSourceItems = [];
  let promptSourceFilter = 'all';
  let promptSourceTaxonomyFilters = { style: '', subject: '', type: '' };
  let promptSourceTaxonomyFacets = { style: [], subject: [], type: [] };
  let promptSourceTaxonomyCollapsed = true;
  let promptSourceTotal = 0;
  let promptSourceSyncRunId = '';
  let promptSourceSyncRun = null;
  let lastPromptSourceSyncRun = null;
  let promptSourceSyncTimer = null;
  let activeGallerySet = null;
  let galleryAssetTotal = 0;
  let galleryAssetStats = {};
  let galleryAssetsFromIndex = false;
  let comparePair = [];
  let previewCompareQueue = [];
  let galleryRenderLimit = 28;
  let gallerySearchTimer = null;
  let historyGenieTimer = null;
  let historyGenieRaf = 0;
  let historyGenieRunId = 0;
  const HISTORY_GENIE_DURATION_MS = 500;
  let previewAsset = null;
  let previewZoom = 1;
  let previewPan = { x: 0, y: 0 };
  let previewDrag = null;
  let previewPromptCompareOpen = false;
  let previewLineageItems = [];
  let previewEditableFile = null;
  let lastDeleteBatchIds = [];
  const remoteImageChoice = new Map();
  const selectedGalleryIds = new Set();
  const GALLERY_ASSET_LOAD_LIMIT = 5000;
  const GALLERY_INITIAL_RENDER_LIMIT = 28;
  const PROMPT_SOURCE_INITIAL_RENDER_LIMIT = 28;
  const GALLERY_VIRTUAL_OVERSCAN_ROWS = 3;
  const PROMPT_SOURCE_TAXONOMY_GROUPS = [
    ['style', '风格'],
    ['subject', '主体'],
    ['type', '类型']
  ];
  const PREVIEW_ZOOM_MIN = 0.5;
  const PREVIEW_ZOOM_MAX = 2;
  let galleryRenderFrame = 0;
  let gallerySelectionRenderPending = false;

  function $(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, char => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[char]));
  }

  function mediaUrl(url) {
    if (window.miniappMediaUrl) return window.miniappMediaUrl(url);
    return String(url || '');
  }

  function sourceImageUrl(relPath) {
    const clean = String(relPath || '').replace(/\\/g, '/').replace(/^\/+/, '');
    if (!clean) return '';
    if (clean.startsWith('source_image/')) return `/${clean}`;
    if (clean.startsWith('/source_image/')) return clean;
    if (/^https?:\/\//i.test(clean)) return clean;
    return `/source_image/${clean.split('/').map(part => encodeURIComponent(part)).join('/')}`;
  }

  function thumbUrlForMediaUrl(url) {
    const raw = String(url || '').trim();
    if (!raw || raw.startsWith('data:') || raw.startsWith('blob:') || /^https?:\/\//i.test(raw)) return raw;
    let path = raw;
    try {
      path = new URL(raw, window.location.origin).pathname;
    } catch (error) {
      path = raw.split('?')[0].split('#')[0];
    }
    if (!path.startsWith('/')) path = `/${path.replace(/^\/+/, '')}`;
    return `/thumb/${encodeURIComponent(path)}.webp?w=420`;
  }

  function preferredThumbUrl(thumbUrl, imageUrl) {
    const thumb = String(thumbUrl || '').trim();
    const image = String(imageUrl || '').trim();
    if (!thumb) return thumbUrlForMediaUrl(image) || image;
    if (thumb.startsWith('/thumb/') || thumb.startsWith('data:') || thumb.startsWith('blob:') || /^https?:\/\//i.test(thumb)) return thumb;
    return thumbUrlForMediaUrl(image || thumb) || thumb;
  }

  function parseTags(value) {
    if (Array.isArray(value)) {
      return [...new Set(value.map(item => String(item || '').trim().replace(/^#/, '')).filter(Boolean))].slice(0, 12);
    }
    return [...new Set(String(value || '')
      .split(/[,，;；\n]+/)
      .map(item => item.trim().replace(/^#/, ''))
      .filter(Boolean))].slice(0, 12);
  }

  function normalizeTaxonomy(value) {
    const source = value && typeof value === 'object' ? value : {};
    return {
      style: parseTags(source.style || []),
      subject: parseTags(source.subject || []),
      type: parseTags(source.type || [])
    };
  }

  function normalizeTaxonomyFacets(value) {
    const source = value && typeof value === 'object' ? value : {};
    const result = { style: [], subject: [], type: [] };
    PROMPT_SOURCE_TAXONOMY_GROUPS.forEach(([key]) => {
      const seen = new Set();
      result[key] = (Array.isArray(source[key]) ? source[key] : [])
        .map(item => {
          const label = String(item?.label || item?.value || '').trim();
          const facetValue = String(item?.value || label).trim();
          if (!label || !facetValue || seen.has(facetValue)) return null;
          seen.add(facetValue);
          return {
            value: facetValue,
            label,
            count: Number(item?.count || 0)
          };
        })
        .filter(Boolean);
    });
    return result;
  }

  function coercePositiveNumber(value) {
    const number = Number(value || 0);
    return Number.isFinite(number) && number > 0 ? number : 0;
  }

  function coerceBooleanFlag(value) {
    if (typeof value === 'boolean') return value;
    const raw = String(value ?? '').trim().toLowerCase();
    if (!raw) return false;
    return !['false', '0', 'no', 'off', '否'].includes(raw);
  }

  function formatFileSize(bytes) {
    const value = Number(bytes || 0);
    if (!Number.isFinite(value) || value <= 0) return '';
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = value;
    let unit = units[0];
    for (const nextUnit of units) {
      unit = nextUnit;
      if (size < 1024 || unit === units[units.length - 1]) break;
      size /= 1024;
    }
    return unit === 'B' ? `${Math.round(size)} B` : `${size.toFixed(1)} ${unit}`;
  }

  function normalizeImageFormat(value, file = '') {
    const raw = String(value || '').trim();
    if (raw) return raw.toUpperCase() === 'JPEG' ? 'JPG' : raw.toUpperCase();
    const match = String(file || '').toLowerCase().match(/\.([a-z0-9]+)$/);
    if (!match) return '';
    return match[1] === 'jpeg' ? 'JPG' : match[1].toUpperCase();
  }

  function inferOrientation(width, height, fallback = '') {
    const cleanFallback = String(fallback || '').trim().toLowerCase();
    if (cleanFallback) return cleanFallback;
    if (!width || !height) return '';
    if (Math.abs(width - height) / Math.max(width, height) <= 0.02) return 'square';
    return width > height ? 'landscape' : 'portrait';
  }

  function orientationLabel(value) {
    return {
      landscape: '横图',
      portrait: '竖图',
      square: '方图'
    }[String(value || '').toLowerCase()] || '';
  }

  function normalizeResolutionLabel(value) {
    const raw = String(value || '').trim().toLowerCase();
    if (!raw) return '';
    const compact = raw.replace(/\s+/g, '');
    if (['1k', '2k', '4k'].includes(compact)) return compact;
    if (['standard', 'normal', 'low'].includes(compact)) return '1k';
    if (compact === 'medium') return '2k';
    if (['hd', 'high'].includes(compact)) return '4k';
    const match = raw.match(/(\d{3,5})\s*[x×]\s*(\d{3,5})/);
    if (!match) return '';
    const longest = Math.max(Number(match[1]) || 0, Number(match[2]) || 0);
    if (longest >= 3600) return '4k';
    if (longest >= 1800) return '2k';
    if (longest >= 900) return '1k';
    return '';
  }

  function prettyResolutionLabel(value) {
    const normalized = normalizeResolutionLabel(value);
    if (normalized) return normalized.toUpperCase();
    return String(value || '').trim();
  }

  function requestedAssetResolution(asset, params = {}) {
    return normalizeResolutionLabel(
      params.requested_resolution
      || params.requestedResolution
      || asset?.requestedResolution
      || asset?.requested_resolution
      || params.resolution
      || params.image_size
      || params.size
      || ''
    );
  }

  function actualAssetResolution(asset, params = {}) {
    return normalizeResolutionLabel(
      params.actual_resolution
      || params.actualResolution
      || asset?.actualResolution
      || asset?.actual_resolution
      || asset?.resolution
      || params.effective_resolution
      || params.effectiveResolution
      || asset?.effectiveResolution
      || asset?.effective_resolution
      || ''
    );
  }

  function assetResolution(asset, params = {}) {
    return actualAssetResolution(asset, params) || requestedAssetResolution(asset, params);
  }

  function simplifyAspectRatio(width, height) {
    const a = Math.round(Number(width || 0));
    const b = Math.round(Number(height || 0));
    if (!a || !b) return '';
    const gcd = (x, y) => (y ? gcd(y, x % y) : Math.abs(x));
    const divisor = gcd(a, b) || 1;
    return `${Math.round(a / divisor)}:${Math.round(b / divisor)}`;
  }

  function compactGalleryModelLabel(value) {
    const label = String(value || '').trim();
    const normalized = label.toLowerCase();
    if (normalized === 'gemini-3-pro-image' || normalized === 'gemini-3-pro-image-preview') return 'gemini-pro';
    if (
      normalized === 'gemini-3-flash-image'
      || normalized === 'gemini-3-flash-image-preview'
      || normalized === 'gemini-3.1-flash-image'
      || normalized === 'gemini-3.1-flash-image-preview'
    ) {
      return 'gemini-flash';
    }
    return label;
  }

  function galleryAssetModelLabel(asset, params = {}) {
    return compactGalleryModelLabel(
      params.main_model
      || asset?.mainModel
      || params.model
      || params.modelAlias
      || asset?.item?.model
      || asset?.providerLabel
      || providerLabel(asset)
      || '未知模型'
    );
  }

  function galleryAssetRatioLabel(asset, params = {}) {
    return String(
      params.ratio
      || params.aspect_ratio
      || params.aspectRatio
      || asset?.aspectRatio
      || simplifyAspectRatio(asset?.width || asset?.imageWidth, asset?.height || asset?.imageHeight)
      || 'auto'
    ).trim();
  }

  function galleryAssetResolutionLabel(asset, params = {}) {
    const actual = actualAssetResolution(asset, params);
    const requested = requestedAssetResolution(asset, params);
    if (actual && requested && actual !== requested) {
      return `实际 ${prettyResolutionLabel(actual)}（请求 ${prettyResolutionLabel(requested)}）`;
    }
    return String(prettyResolutionLabel(actual || requested) || asset?.dimensions || 'auto').trim();
  }

  function assetMetaSearchText(asset) {
    const params = asset?.params && typeof asset.params === 'object' ? asset.params : {};
    return [
      asset?.prompt,
      asset?.file,
      asset?.title,
      asset?.providerLabel,
      asset?.dimensions,
      asset?.aspectRatio,
      asset?.orientation,
      orientationLabel(asset?.orientation),
      asset?.format,
      asset?.fileSizeLabel,
      assetResolution(asset, params),
      galleryAssetResolutionLabel(asset, params),
      requestedAssetResolution(asset, params),
      actualAssetResolution(asset, params),
      params.ratio,
      params.aspect_ratio,
      params.aspectRatio,
      params.quality,
      ...(parseTags(asset?.tags))
    ].filter(Boolean).join(' ');
  }

  function normalizeGalleryAsset(asset) {
    const id = asset?.asset_id || asset?.id || '';
    const params = asset?.params && typeof asset.params === 'object' ? asset.params : {};
    const imagePaths = [
      ...(Array.isArray(asset?.imagePaths) ? asset.imagePaths : []),
      ...(Array.isArray(asset?.image_paths) ? asset.image_paths : [])
    ].map(item => String(item || '').trim()).filter(Boolean);
    const imageUrls = [
      ...(Array.isArray(asset?.imageUrls) ? asset.imageUrls : []),
      ...(Array.isArray(asset?.image_urls) ? asset.image_urls : []),
      ...imagePaths.map(sourceImageUrl),
      asset?.imageUrl || asset?.image_url || asset?.imagePath || asset?.image_path || ''
    ].map(item => String(item || '').trim()).filter(Boolean);
    const uniqueImageUrls = [...new Set(imageUrls)];
    const width = coercePositiveNumber(asset?.width || asset?.imageWidth || asset?.image_width || params.width);
    const height = coercePositiveNumber(asset?.height || asset?.imageHeight || asset?.image_height || params.height);
    const dimensions = asset?.dimensions || params.dimensions || (width && height ? `${width} × ${height}` : '');
    const aspectRatio = asset?.aspectRatio || asset?.aspect_ratio || params.ratio || params.aspect_ratio || params.aspectRatio || '';
    const fileSizeBytes = coercePositiveNumber(asset?.fileSizeBytes || asset?.file_size_bytes);
    const fileSizeLabel = asset?.fileSizeLabel || asset?.file_size_label || formatFileSize(fileSizeBytes);
    const format = normalizeImageFormat(asset?.format || params.format, asset?.file);
    const orientation = inferOrientation(width, height, asset?.orientation);
    const requestedResolution = requestedAssetResolution(asset, params);
    const actualResolution = actualAssetResolution(asset, params);
    return {
      ...asset,
      id,
      asset_id: id,
      taskId: asset?.taskId || asset?.task_id || '',
      imageUrl: uniqueImageUrls[0] || '',
      imagePath: asset?.imagePath || asset?.imageUrl || uniqueImageUrls[0] || '',
      thumbUrl: preferredThumbUrl(asset?.thumbUrl || asset?.thumb_url, uniqueImageUrls[0]),
      imagePaths,
      imageUrls: uniqueImageUrls,
      imageCount: uniqueImageUrls.length,
      archiveRelPath: asset?.archiveRelPath || asset?.archive_rel_path || '',
      providerLabel: asset?.providerLabel || asset?.provider_label || providerLabel(asset),
      createdAt: asset?.createdAt || asset?.created_at || asset?.timestamp || 0,
      updatedAt: asset?.updatedAt || asset?.updated_at || 0,
      width,
      height,
      imageWidth: width,
      imageHeight: height,
      dimensions,
      aspectRatio,
      aspect_ratio: aspectRatio,
      orientation,
      orientationLabel: orientationLabel(orientation),
      megapixels: coercePositiveNumber(asset?.megapixels),
      format,
      fileSizeBytes,
      file_size_bytes: fileSizeBytes,
      fileSizeLabel,
      file_size_label: fileSizeLabel,
      resolution: actualResolution || requestedResolution,
      requestedResolution,
      requested_resolution: requestedResolution,
      actualResolution,
      actual_resolution: actualResolution,
      resolutionMismatch: coerceBooleanFlag(asset?.resolutionMismatch || asset?.resolution_mismatch || params.resolution_mismatch || (actualResolution && requestedResolution && actualResolution !== requestedResolution)),
      resolution_mismatch: coerceBooleanFlag(asset?.resolutionMismatch || asset?.resolution_mismatch || params.resolution_mismatch || (actualResolution && requestedResolution && actualResolution !== requestedResolution)),
      favorite: !!asset?.favorite,
      hidden: !!asset?.hidden,
      stale: !!asset?.stale,
      hasTaskRecord: !!(asset?.hasTaskRecord || asset?.has_task_record),
      sourceKind: asset?.sourceKind || asset?.assetSource || asset?.source_kind || (asset?.hasTaskRecord || asset?.has_task_record ? 'history' : 'archive'),
      missingArchive: !!(asset?.missingArchive || asset?.missing_archive),
      tags: parseTags(asset?.tags),
      lineage: asset?.lineage || {},
      referenceAssets: Array.isArray(asset?.referenceAssets)
        ? asset.referenceAssets
        : (Array.isArray(asset?.lineage?.referenceAssets) ? asset.lineage.referenceAssets : (Array.isArray(asset?.lineage?.reference_assets) ? asset.lineage.reference_assets : [])),
      referenceAssetIds: Array.isArray(asset?.referenceAssetIds)
        ? asset.referenceAssetIds
        : (Array.isArray(asset?.lineage?.referenceAssetIds) ? asset.lineage.referenceAssetIds : (Array.isArray(asset?.lineage?.reference_asset_ids) ? asset.lineage.reference_asset_ids : [])),
      derivedAssets: Array.isArray(asset?.derivedAssets)
        ? asset.derivedAssets
        : (Array.isArray(asset?.lineage?.derivedAssets) ? asset.lineage.derivedAssets : (Array.isArray(asset?.lineage?.derived_assets) ? asset.lineage.derived_assets : [])),
      derivedCount: Number(asset?.derivedCount || asset?.lineage?.derivedCount || asset?.lineage?.derived_count || 0),
      relatedAssets: Array.isArray(asset?.relatedAssets)
        ? asset.relatedAssets
        : (Array.isArray(asset?.lineage?.relatedAssets) ? asset.lineage.relatedAssets : (Array.isArray(asset?.lineage?.related_assets) ? asset.lineage.related_assets : [])),
      relatedCount: Number(asset?.relatedCount || asset?.lineage?.relatedCount || asset?.lineage?.related_count || 0)
    };
  }

  function normalizeEditableFile(item) {
    const primary = item?.primary || {};
    const zip = item?.zip || null;
    const preview = item?.preview || {};
    const firstPage = Array.isArray(preview.pages) ? preview.pages[0] : null;
    const previewUrl = preview.image_url || preview.imageUrl || firstPage?.url || '';
    const kind = String(item?.artifact_type || item?.kind || 'file').toUpperCase();
    const sizeLabel = formatFileSize(Number(primary.size || 0));
    const subject = String(item?.subject || primary.name || `${kind} 文件`);
    return {
      ...item,
      id: item?.directory_relative || item?.manifest_url || item?.task_id || primary.relative_path || subject,
      kind,
      title: primary.name || `${subject}.${kind.toLowerCase()}`,
      subject,
      prompt: item?.prompt || '',
      createdAt: Number(item?.created_at || item?.createdAt || 0),
      archived: item?.archived !== false,
      directoryRelative: item?.directory_relative || '',
      primary,
      zip,
      preview,
      previewUrl,
      sizeLabel,
      metaLabel: [kind, preview.page_count ? `${preview.page_count} 页` : '', preview.layer_count ? `${preview.layer_count} 图层` : '', sizeLabel].filter(Boolean).join(' · ')
    };
  }

  function normalizePromptSourceItem(item) {
    const taxonomy = normalizeTaxonomy(item?.taxonomy || item?.promptTaxonomy);
    return normalizeGalleryAsset({
      ...item,
      id: item?.itemId || item?.item_id || item?.id || '',
      asset_id: item?.itemId || item?.item_id || item?.id || '',
      taskId: item?.itemId || item?.id || '',
      title: item?.title || '远程提示词',
      imageUrl: item?.imageUrl || item?.image_url || '',
      imagePath: item?.imagePath || item?.imageUrl || '',
      thumbUrl: preferredThumbUrl(item?.thumbUrl || item?.thumb_url, item?.imageUrl || item?.image_url || ''),
      imagePaths: Array.isArray(item?.imagePaths) ? item.imagePaths : (Array.isArray(item?.image_paths) ? item.image_paths : []),
      sourceSlug: item?.sourceSlug || item?.source_slug || '',
      sourceName: item?.sourceName || item?.source_name || '',
      repoUrl: item?.repoUrl || item?.repo_url || '',
      sourceUrl: item?.sourceUrl || item?.source_url || '',
      provider: 'remote',
      providerLabel: item?.sourceName || item?.source_name || '远程源',
      sourceKind: 'remote_source',
      hasTaskRecord: false,
      favorite: false,
      hidden: false,
      tags: parseTags(item?.tags),
      taxonomy,
      promptTaxonomy: taxonomy,
      params: {
        ...(item?.params || {}),
        source_kind: 'remote_prompt',
        prompt_source: item?.sourceSlug || item?.source_slug || '',
        source_repo: item?.repoUrl || item?.repo_url || '',
        source_url: item?.sourceUrl || item?.source_url || ''
      }
    });
  }

  function assetSnapshotForSet(asset) {
    if (!asset?.id) return null;
    return {
      id: asset.id,
      asset_id: asset.id,
      taskId: asset.taskId || '',
      file: asset.file || '',
      imageUrl: asset.imageUrl || '',
      imagePath: asset.imagePath || asset.imageUrl || '',
      thumbUrl: preferredThumbUrl(asset.thumbUrl, asset.imageUrl),
      archiveRelPath: asset.archiveRelPath || '',
      title: asset.title || '图片资产',
      prompt: asset.prompt || '',
      type: asset.type || '',
      provider: asset.provider || providerGroup(asset),
      providerLabel: asset.providerLabel || providerLabel(asset),
      status: asset.status || '',
      createdAt: asset.createdAt || 0,
      updatedAt: asset.updatedAt || 0,
      params: asset.params || {},
      width: Number(asset.width || 0),
      height: Number(asset.height || 0),
      imageWidth: Number(asset.imageWidth || asset.width || 0),
      imageHeight: Number(asset.imageHeight || asset.height || 0),
      dimensions: asset.dimensions || '',
      aspectRatio: asset.aspectRatio || asset.aspect_ratio || '',
      aspect_ratio: asset.aspectRatio || asset.aspect_ratio || '',
      orientation: asset.orientation || '',
      format: asset.format || '',
      fileSizeBytes: Number(asset.fileSizeBytes || asset.file_size_bytes || 0),
      file_size_bytes: Number(asset.fileSizeBytes || asset.file_size_bytes || 0),
      fileSizeLabel: asset.fileSizeLabel || asset.file_size_label || '',
      file_size_label: asset.fileSizeLabel || asset.file_size_label || '',
      resolution: asset.resolution || '',
      requestedResolution: asset.requestedResolution || asset.requested_resolution || '',
      requested_resolution: asset.requestedResolution || asset.requested_resolution || '',
      actualResolution: asset.actualResolution || asset.actual_resolution || '',
      actual_resolution: asset.actualResolution || asset.actual_resolution || '',
      resolutionMismatch: coerceBooleanFlag(asset.resolutionMismatch || asset.resolution_mismatch),
      resolution_mismatch: coerceBooleanFlag(asset.resolutionMismatch || asset.resolution_mismatch),
      megapixels: Number(asset.megapixels || 0),
      index: Number(asset.index || 0),
      total: Number(asset.total || 1),
      favorite: !!asset.favorite,
      hidden: !!asset.hidden,
      hasTaskRecord: !!asset.hasTaskRecord,
      sourceKind: asset.sourceKind || '',
      missingArchive: !!asset.missingArchive,
      tags: parseTags(asset.tags),
      rating: Number(asset.rating || 0),
      note: asset.note || '',
      lineage: asset.lineage || {},
      referenceAssets: asset.referenceAssets || [],
      referenceAssetIds: asset.referenceAssetIds || [],
      derivedAssets: asset.derivedAssets || [],
      derivedCount: Number(asset.derivedCount || 0),
      relatedAssets: asset.relatedAssets || [],
      relatedCount: Number(asset.relatedCount || 0)
    };
  }

  function normalizeAssetSet(item) {
    const id = item?.set_id || item?.id || '';
    const assets = (Array.isArray(item?.assets) ? item.assets : [])
      .map(normalizeGalleryAsset)
      .filter(asset => asset.id && asset.imageUrl);
    const rawIds = Array.isArray(item?.assetIds)
      ? item.assetIds
      : (Array.isArray(item?.asset_ids) ? item.asset_ids : []);
    const assetIds = [...new Set([
      ...rawIds.map(value => String(value || '').trim()).filter(Boolean),
      ...assets.map(asset => asset.id)
    ])];
    return {
      ...item,
      id,
      set_id: id,
      name: item?.name || '未命名候选集',
      tags: parseTags(item?.tags),
      assetIds,
      asset_ids: assetIds,
      assets,
      count: Number(item?.count || assetIds.length || assets.length || 0),
      createdAt: item?.createdAt || item?.created_at || 0,
      updatedAt: item?.updatedAt || item?.updated_at || item?.createdAt || item?.created_at || 0
    };
  }

  function mergeAssetsFromSet(assetSet) {
    const byId = new Map(galleryAssets.map(asset => [asset.id, asset]));
    (assetSet?.assets || []).forEach(asset => {
      if (!asset?.id) return;
      const current = byId.get(asset.id);
      if (current) {
        Object.assign(current, {
          ...asset,
          favorite: current.favorite || asset.favorite,
          hidden: current.hidden || asset.hidden,
          tags: parseTags(current.tags?.length ? current.tags : asset.tags)
        });
        return;
      }
      galleryAssets.push(asset);
      byId.set(asset.id, asset);
    });
  }

  function replaceGallerySet(assetSet) {
    const normalized = normalizeAssetSet(assetSet);
    if (!normalized.id) return normalized;
    const index = gallerySets.findIndex(item => item.id === normalized.id);
    if (index >= 0) gallerySets.splice(index, 1, normalized);
    else gallerySets.unshift(normalized);
    if (activeGallerySet?.id === normalized.id) activeGallerySet = normalized;
    mergeAssetsFromSet(normalized);
    return normalized;
  }

  function activeSetAssets(assetSet = activeGallerySet) {
    return (assetSet?.assets || []).map(normalizeGalleryAsset).filter(asset => asset.id && asset.imageUrl);
  }

  async function persistAssetSet(assetSet, patch = {}, message = '') {
    if (!assetSet?.id) return null;
    const nextAssets = Array.isArray(patch.assets) ? patch.assets.map(normalizeGalleryAsset) : activeSetAssets(assetSet);
    const payload = {
      set_id: assetSet.id,
      name: patch.name ?? assetSet.name ?? '未命名候选集',
      tags: patch.tags ?? parseTags(assetSet.tags),
      asset_ids: nextAssets.map(asset => asset.id),
      assets: nextAssets.map(assetSnapshotForSet).filter(Boolean)
    };
    const result = await DesktopApi.saveAssetSet(payload);
    const updated = replaceGallerySet(result.set || result);
    renderGallery();
    renderGallerySelection();
    if (message) DesktopResults.showTransientMessage(message);
    return updated;
  }

  function parseSetNameAndTags(raw, selected) {
    const value = String(raw || '').trim();
    const tagMatches = [...value.matchAll(/#([^#\s,，;；]+)/g)].map(match => match[1]);
    const name = value.replace(/#([^#\s,，;；]+)/g, '').replace(/\s+/g, ' ').trim();
    const fallback = selected.length === 1
      ? `候选集 · ${selected[0].title || '1 张'}`
      : `候选集 · ${selected.length} 张`;
    return {
      name: name || fallback,
      tags: parseTags(tagMatches)
    };
  }

  function applyAssetMeta(asset, meta = {}) {
    if (!asset || !meta) return asset;
    if ('favorite' in meta) asset.favorite = !!meta.favorite;
    if ('hidden' in meta) asset.hidden = !!meta.hidden;
    if ('tags' in meta) asset.tags = parseTags(meta.tags);
    if ('rating' in meta) asset.rating = Number(meta.rating || 0);
    if ('note' in meta) asset.note = meta.note || '';
    return asset;
  }

  function galleryMessage(message) {
    if (window.DesktopResults?.showTransientMessage) {
      DesktopResults.showTransientMessage(message);
    }
  }

  function galleryError(error, fallback = '图库操作失败') {
    const message = error?.message || String(error || fallback);
    console.error('[Gallery]', message, error);
    galleryMessage(`${fallback}：${message}`);
  }

  function collectElements() {
    [
      'deskHistoryPanel',
      'deskHistoryList',
      'deskHistoryCollapseBtn',
      'deskHistoryExpandBtn',
      'deskHistoryGenieCanvas',
      'deskHistoryBtn',
      'deskTodayCount',
      'deskQueueCount',
      'deskGalleryPanel',
      'deskGalleryGrid',
      'deskGalleryRefreshBtn',
      'deskGalleryHealthBtn',
      'deskGalleryCloseBtn',
      'deskGallerySearchInput',
      'deskGalleryFilterSelect',
      'deskGalleryTagInput',
      'deskGalleryStats',
      'deskGallerySelectedCount',
      'deskGallerySelectedList',
      'deskGalleryCompareBtn',
      'deskGalleryCanvasBtn',
      'deskGallerySaveSetBtn',
      'deskGalleryRefreshMetaBtn',
      'deskGalleryTagBtn',
      'deskGalleryHideBtn',
      'deskGalleryDeleteBtn',
      'deskGalleryUndoDeleteBtn',
      'deskGalleryClearBtn',
      'deskGalleryPreviewModal',
      'deskGalleryPreviewStage',
      'deskGalleryPreviewImg',
      'deskGalleryPreviewTitle',
      'deskGalleryPreviewPrompt',
      'deskGalleryPreviewPromptCompareBtn',
      'deskGalleryPreviewRevisedBlock',
      'deskGalleryPreviewRevisedPrompt',
      'deskGalleryPreviewCopyRevisedBtn',
      'deskGalleryPreviewNegativeDivider',
      'deskGalleryPreviewNegativeBlock',
      'deskGalleryPreviewNegativePrompt',
      'deskGalleryPreviewMeta',
      'deskGalleryPreviewLineageDivider',
      'deskGalleryPreviewLineageBlock',
      'deskGalleryPreviewLineage',
      'deskGalleryPreviewCopyBtn',
      'deskGalleryPreviewApplyBtn',
      'deskGalleryPreviewCanvasBtn',
      'deskGalleryPreviewEditBtn',
      'deskGalleryPreviewOpenBtn',
      'deskGalleryPreviewFavoriteBtn',
      'deskGalleryPreviewTagBtn',
      'deskGalleryPreviewHideBtn',
      'deskGalleryPreviewDeleteBtn',
      'deskGalleryPreviewCompareBtn',
      'deskGalleryPreviewLayoutBtn',
      'deskGalleryPreviewSendBtn',
      'deskGalleryPreviewCloseBtn',
      'deskGalleryPreviewPrevBtn',
      'deskGalleryPreviewNextBtn',
      'deskGalleryPreviewZoomOutBtn',
      'deskGalleryPreviewZoomInBtn',
      'deskGalleryPreviewCounter',
      'deskFilePreviewModal',
      'deskFilePreviewStage',
      'deskFilePreviewKind',
      'deskFilePreviewTitle',
      'deskFilePreviewMeta',
      'deskFilePreviewPrompt',
      'deskFilePreviewLayersBlock',
      'deskFilePreviewLayers',
      'deskFilePreviewOpenBtn',
      'deskFilePreviewZipBtn',
      'deskFilePreviewManifestBtn',
      'deskFilePreviewSendBtn',
      'deskFilePreviewDeleteBtn',
      'deskFilePreviewCloseBtn',
      'deskCompareModal',
      'deskCompareBaseImg',
      'deskCompareTopImg',
      'deskCompareOverlay',
      'deskCompareDivider',
      'deskCompareRange',
      'deskCompareLeftLabel',
      'deskCompareRightLabel',
      'deskCompareMetaDiff',
      'deskComparePromptLeft',
      'deskComparePromptRight',
      'deskCompareSwapBtn',
      'deskCompareCloseBtn'
    ].forEach(id => {
      els[id] = $(id);
    });
  }

  function setHistoryCollapsed(collapsed, save = true) {
    const nextValue = !!collapsed;
    const panel = els.deskHistoryPanel;
    if (historyGenieTimer) {
      window.clearTimeout(historyGenieTimer);
      historyGenieTimer = null;
    }
    stopHistoryGenieAnimation();
    const runId = ++historyGenieRunId;
    syncHistoryPanelBounds();
    const shouldAnimateClosing = nextValue
      && save
      && panel
      && !panel.classList.contains('is-collapsed')
      && !window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    const shouldAnimateOpening = !nextValue
      && save
      && panel
      && panel.classList.contains('is-collapsed')
      && !window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    panel?.classList.remove('is-genie-closing');
    panel?.classList.remove('is-genie-materializing');
    if (shouldAnimateClosing || shouldAnimateOpening) {
      if (shouldAnimateClosing) {
        animateHistoryGenieClose(panel, runId);
      } else {
        animateHistoryGenieOpen(panel, runId);
      }
      const storageValue = nextValue ? '1' : '0';
      document.body.classList.remove('desk-history-collapsed');
      els.deskHistoryCollapseBtn?.setAttribute('aria-expanded', nextValue ? 'false' : 'true');
      els.deskHistoryExpandBtn?.setAttribute('aria-expanded', nextValue ? 'false' : 'true');
      try {
        window.localStorage?.setItem('desktop_history_collapsed_v1', storageValue);
      } catch (e) {
        // Ignore private-mode storage failures.
      }
      scheduleHistoryPanelBoundsSync(0);
      scheduleHistoryPanelBoundsSync(HISTORY_GENIE_DURATION_MS);
      return;
    }
    panel?.classList.toggle('is-collapsed', nextValue);
    document.body.classList.toggle('desk-history-collapsed', nextValue);
    els.deskHistoryCollapseBtn?.setAttribute('aria-expanded', nextValue ? 'false' : 'true');
    els.deskHistoryExpandBtn?.setAttribute('aria-expanded', nextValue ? 'false' : 'true');
    if (save) {
      try {
        window.localStorage?.setItem('desktop_history_collapsed_v1', nextValue ? '1' : '0');
      } catch (e) {
        // Ignore private-mode storage failures.
      }
    }
    scheduleHistoryPanelBoundsSync(0);
    scheduleHistoryPanelBoundsSync(260);
  }

  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const lerp = (a, b, t) => a + (b - a) * t;
  const easeInOutCubic = t => (
    t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
  );
  const easeInQuad = t => t * t;
  const easeOutQuad = t => 1 - (1 - t) * (1 - t);

  function historyGenieCanvasReady() {
    return Boolean(els.deskHistoryGenieCanvas?.getContext);
  }

  function stopHistoryGenieAnimation() {
    if (historyGenieRaf) {
      window.cancelAnimationFrame(historyGenieRaf);
      historyGenieRaf = 0;
    }
    const canvas = els.deskHistoryGenieCanvas;
    if (!canvas?.getContext) return;
    const width = window.innerWidth || document.documentElement.clientWidth || 1;
    const height = window.innerHeight || document.documentElement.clientHeight || 1;
    canvas.classList.remove('is-active');
    canvas.getContext('2d')?.clearRect(0, 0, width, height);
  }

  function historyGenieCollapsedRect() {
    const width = 52;
    const height = 72;
    const top = 24;
    const right = 18;
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;
    return {
      left: Math.max(0, viewportWidth - right - width),
      top,
      width,
      height
    };
  }

  function historyGenieExpandedRect(panel) {
    syncHistoryPanelBounds();
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
    const style = getComputedStyle(panel);
    const width = parseFloat(style.getPropertyValue('--desk-side-panel-width')) || 224;
    const top = 36;
    const right = 0;
    const bottom = parseFloat(style.getPropertyValue('--desk-history-bottom')) || 92;
    return {
      left: Math.max(0, (window.innerWidth || document.documentElement.clientWidth || width) - right - width),
      top,
      width,
      height: Math.max(120, viewportHeight - top - bottom)
    };
  }

  function setupHistoryGenieCanvas() {
    const canvas = els.deskHistoryGenieCanvas;
    if (!canvas?.getContext) return null;
    const width = window.innerWidth || document.documentElement.clientWidth || 1;
    const height = window.innerHeight || document.documentElement.clientHeight || 1;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.ceil(width * dpr);
    canvas.height = Math.ceil(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    return { canvas, ctx, width, height };
  }

  function drawHistoryPanelFallback(rect) {
    const canvas = document.createElement('canvas');
    const width = Math.max(1, Math.round(rect.width));
    const height = Math.max(1, Math.round(rect.height));
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    const radius = 7;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = 'rgba(255,255,255,0.72)';
    ctx.strokeStyle = 'rgba(180,210,235,0.55)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(radius, 0);
    ctx.lineTo(width - radius, 0);
    ctx.quadraticCurveTo(width, 0, width, radius);
    ctx.lineTo(width, height - radius);
    ctx.quadraticCurveTo(width, height, width - radius, height);
    ctx.lineTo(radius, height);
    ctx.quadraticCurveTo(0, height, 0, height - radius);
    ctx.lineTo(0, radius);
    ctx.quadraticCurveTo(0, 0, radius, 0);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = 'rgba(22,32,43,0.86)';
    ctx.font = '700 14px -apple-system, BlinkMacSystemFont, sans-serif';
    ctx.fillText('最近记录', 14, 28);
    for (let y = 54; y < height - 22; y += 52) {
      ctx.fillStyle = 'rgba(255,255,255,0.38)';
      ctx.fillRect(12, y, width - 24, 40);
      ctx.fillStyle = 'rgba(99,113,130,0.28)';
      ctx.fillRect(24, y + 12, width - 72, 5);
      ctx.fillRect(24, y + 24, width - 108, 4);
    }
    return canvas;
  }

  async function snapshotHistoryPanel(panel, rect) {
    const fallback = () => drawHistoryPanelFallback(rect);
    try {
      const clone = panel.cloneNode(true);
      clone.classList.remove('is-collapsed', 'is-genie-closing', 'is-genie-materializing');
      clone.style.position = 'relative';
      clone.style.top = '0';
      clone.style.right = 'auto';
      clone.style.bottom = 'auto';
      clone.style.left = '0';
      clone.style.width = `${Math.round(rect.width)}px`;
      clone.style.height = `${Math.round(rect.height)}px`;
      clone.style.margin = '0';
      clone.style.opacity = '1';
      clone.style.transform = 'none';
      clone.style.animation = 'none';
      clone.style.pointerEvents = 'none';
      clone.querySelector('#deskHistoryExpandBtn')?.remove();
      const cssText = Array.from(document.styleSheets)
        .map(sheet => {
          try {
            return Array.from(sheet.cssRules || []).map(rule => rule.cssText).join('\n');
          } catch (e) {
            return '';
          }
        })
        .join('\n');
      const markup = `
        <svg xmlns="http://www.w3.org/2000/svg" width="${Math.round(rect.width)}" height="${Math.round(rect.height)}">
          <foreignObject width="100%" height="100%">
            <div xmlns="http://www.w3.org/1999/xhtml">
              <style>${cssText}</style>
              ${clone.outerHTML}
            </div>
          </foreignObject>
        </svg>
      `;
      const blob = new Blob([markup], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      try {
        const image = new Image();
        await new Promise((resolve, reject) => {
          image.onload = resolve;
          image.onerror = reject;
          image.src = url;
        });
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(rect.width));
        canvas.height = Math.max(1, Math.round(rect.height));
        canvas.getContext('2d').drawImage(image, 0, 0);
        return canvas;
      } finally {
        URL.revokeObjectURL(url);
      }
    } catch (e) {
      return fallback();
    }
  }

  function renderHistoryGenieFrame(ctx, source, viewportWidth, viewportHeight, progress, direction, target, panelRect) {
    ctx.clearRect(0, 0, viewportWidth, viewportHeight);
    const sourceWidth = source.width;
    const sourceHeight = source.height;
    const dock = {
      x: target.left + target.width / 2,
      y: target.top + target.height / 2
    };
    const win = {
      x: panelRect.left,
      y: panelRect.top,
      width: panelRect.width,
      height: panelRect.height
    };
    for (let y = 0; y < sourceHeight; y += 1) {
      const row = y / sourceHeight;
      const rowXStart = direction === 'minimize' ? (1 - row) * 0.65 : row * 0.65;
      const xProgress = clamp((progress - rowXStart) / (1 - rowXStart), 0, 1);
      const xEase = easeInOutCubic(xProgress);
      const rowYStart = direction === 'minimize' ? (1 - row) * 0.2 : row * 0.2;
      const yProgress = clamp((progress - rowYStart) / (1 - rowYStart), 0, 1);
      const yEase = easeInQuad(yProgress);
      let left;
      let right;
      let destY;
      const sourceY = y;
      const naturalY = win.y + (y / sourceHeight) * win.height;
      if (direction === 'minimize') {
        left = lerp(win.x, dock.x, xEase);
        right = lerp(win.x + win.width, dock.x, xEase);
        destY = lerp(naturalY, dock.y, yEase);
      } else {
        left = lerp(dock.x, win.x, xEase);
        right = lerp(dock.x, win.x + win.width, xEase);
        destY = lerp(dock.y, naturalY, yEase);
      }
      const rowWidth = right - left;
      if (rowWidth < 0.8) continue;
      ctx.drawImage(source, 0, sourceY, sourceWidth, 1, left, destY, rowWidth, Math.max(1, win.height / sourceHeight));
    }
    const glowRaw = direction === 'minimize' ? progress : 1 - progress;
    if (glowRaw > 0.75) {
      const alpha = easeOutQuad((glowRaw - 0.75) / 0.25) * 0.24;
      const gradient = ctx.createRadialGradient(dock.x, dock.y, 0, dock.x, dock.y, 58);
      gradient.addColorStop(0, `rgba(255,255,255,${alpha})`);
      gradient.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, viewportWidth, viewportHeight);
    }
  }

  function runHistoryGenieAnimation({ runId, direction, source, targetRect, panelRect, onStart, onDone }) {
    if (runId !== historyGenieRunId) return;
    const setup = setupHistoryGenieCanvas();
    if (!setup) {
      onStart?.();
      onDone?.();
      return;
    }
    const { canvas, ctx, width, height } = setup;
    let startedAt = 0;
    canvas.classList.add('is-active');
    onStart?.();
    const tick = timestamp => {
      if (runId !== historyGenieRunId) {
        ctx.clearRect(0, 0, width, height);
        canvas.classList.remove('is-active');
        historyGenieRaf = 0;
        return;
      }
      if (!startedAt) startedAt = timestamp;
      const progress = clamp((timestamp - startedAt) / HISTORY_GENIE_DURATION_MS, 0, 1);
      renderHistoryGenieFrame(ctx, source, width, height, progress, direction, targetRect, panelRect);
      if (progress < 1) {
        historyGenieRaf = window.requestAnimationFrame(tick);
        return;
      }
      historyGenieRaf = 0;
      canvas.classList.remove('is-active');
      ctx.clearRect(0, 0, width, height);
      onDone?.();
    };
    historyGenieRaf = window.requestAnimationFrame(tick);
  }

  async function animateHistoryGenieClose(panel, runId) {
    if (!historyGenieCanvasReady()) {
      panel.classList.add('is-collapsed');
      document.body.classList.add('desk-history-collapsed');
      return;
    }
    const panelRect = panel.getBoundingClientRect();
    const targetRect = historyGenieCollapsedRect();
    const source = await snapshotHistoryPanel(panel, panelRect);
    if (runId !== historyGenieRunId) return;
    runHistoryGenieAnimation({
      runId,
      direction: 'minimize',
      source,
      targetRect,
      panelRect,
      onStart: () => {
        panel.classList.add('is-genie-closing');
      },
      onDone: () => {
        panel.classList.remove('is-genie-closing');
        panel.classList.add('is-collapsed');
        document.body.classList.add('desk-history-collapsed');
        scheduleHistoryPanelBoundsSync(0);
        scheduleHistoryPanelBoundsSync(260);
      }
    });
  }

  async function animateHistoryGenieOpen(panel, runId) {
    if (!historyGenieCanvasReady()) {
      panel.classList.remove('is-collapsed');
      document.body.classList.remove('desk-history-collapsed');
      return;
    }
    const targetRect = historyGenieCollapsedRect();
    const panelRect = historyGenieExpandedRect(panel);
    panel.classList.remove('is-collapsed');
    panel.classList.add('is-genie-materializing');
    document.body.classList.remove('desk-history-collapsed');
    scheduleHistoryPanelBoundsSync(0);
    await new Promise(resolve => window.requestAnimationFrame(resolve));
    if (runId !== historyGenieRunId) return;
    const source = await snapshotHistoryPanel(panel, panelRect);
    if (runId !== historyGenieRunId) return;
    runHistoryGenieAnimation({
      runId,
      direction: 'open',
      source,
      targetRect,
      panelRect,
      onStart: () => {},
      onDone: () => {
        panel.classList.remove('is-genie-materializing');
        scheduleHistoryPanelBoundsSync(0);
        scheduleHistoryPanelBoundsSync(260);
      }
    });
  }

  function restoreHistoryCollapsedState() {
    try {
      setHistoryCollapsed(window.localStorage?.getItem('desktop_history_collapsed_v1') === '1', false);
    } catch (e) {
      setHistoryCollapsed(false, false);
    }
  }

  function getLayoutTopWithin(element, ancestor) {
    if (!element || !ancestor) return 0;
    let top = 0;
    let node = element;
    while (node && node !== ancestor && node !== document.documentElement) {
      top += node.offsetTop || 0;
      node = node.offsetParent;
    }
    if (node === ancestor) return top;
    const elementRect = element.getBoundingClientRect?.();
    const ancestorRect = ancestor.getBoundingClientRect?.();
    if (elementRect && ancestorRect) return elementRect.top - ancestorRect.top;
    return 0;
  }

  function syncHistoryPanelBounds(options = {}) {
    const panel = els.deskHistoryPanel;
    if (!panel) return;
    const controls = document.querySelector('.desk-zoom-controls');
    const parent = panel.offsetParent || panel.parentElement || document.documentElement;
    const parentRect = parent.getBoundingClientRect?.() || { height: window.innerHeight || 0 };
    const parentHeight = parent.clientHeight || parentRect.height || window.innerHeight || 0;
    let bottom = 92;
    if (controls) {
      const controlsTop = getLayoutTopWithin(controls, parent);
      const controlsHeight = controls.offsetHeight || controls.getBoundingClientRect?.().height || 0;
      const controlsBottom = controlsTop + controlsHeight;
      const targetHeight = Number(options.targetHeight || 0);
      if (targetHeight > 0 && Number.isFinite(targetHeight)) {
        bottom = Math.max(18, Math.ceil(parentHeight - controlsBottom + targetHeight + 10));
      } else {
        bottom = Math.max(18, Math.ceil(parentHeight - controlsTop + 10));
      }
    }
    panel.style.setProperty('--desk-history-bottom', `${bottom}px`);
  }

  function scheduleHistoryPanelBoundsSync(delay = 0, options = {}) {
    const run = () => window.requestAnimationFrame(() => syncHistoryPanelBounds(options));
    if (delay > 0) {
      window.setTimeout(run, delay);
      return;
    }
    run();
  }

  function bindHistoryPanelBounds() {
    const controls = document.querySelector('.desk-zoom-controls');
    if (controls) {
      ['transitionend'].forEach(eventName => {
        controls.addEventListener(eventName, () => {
          scheduleHistoryPanelBoundsSync(0);
          scheduleHistoryPanelBoundsSync(220);
        });
      });
    }
    window.addEventListener('resize', () => {
      scheduleHistoryPanelBoundsSync(0);
      scheduleHistoryPanelBoundsSync(220);
    });
    window.addEventListener('desktop:minimap-layout-change', event => {
      const targetHeight = Number(event.detail?.targetHeight || 0);
      scheduleHistoryPanelBoundsSync(0, { targetHeight });
      scheduleHistoryPanelBoundsSync(220);
    });
    scheduleHistoryPanelBoundsSync(0);
    scheduleHistoryPanelBoundsSync(220);
  }

  function formatTime(timestamp) {
    const value = Number(timestamp || 0);
    if (!value) return '未知时间';
    try {
      return new Date(value * 1000).toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch (e) {
      return '未知时间';
    }
  }

  function formatPreviewTime(timestamp) {
    const value = Number(timestamp || 0);
    if (!value) return '未知时间';
    try {
      return new Date(value * 1000).toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch (e) {
      return '未知时间';
    }
  }

  function normalizePromptSourceRun(run) {
    if (!run || typeof run !== 'object') return null;
    const progressPercent = Number(run.progress_percent ?? run.progressPercent ?? 0);
    return {
      ...run,
      runId: String(run.run_id || run.runId || ''),
      sourceSlug: String(run.source_slug || run.sourceSlug || ''),
      status: String(run.status || '').trim(),
      phase: String(run.phase || '').trim(),
      message: String(run.message || '').trim(),
      currentSource: String(run.current_source || run.currentSource || ''),
      currentSourceName: String(run.current_source_name || run.currentSourceName || ''),
      sourceIndex: Number(run.source_index ?? run.sourceIndex ?? 0),
      totalSources: Number(run.total_sources ?? run.totalSources ?? 0),
      processedItems: Number(run.processed_items ?? run.processedItems ?? 0),
      totalItems: Number(run.total_items ?? run.totalItems ?? 0),
      processedImages: Number(run.processed_images ?? run.processedImages ?? 0),
      totalImages: Number(run.total_images ?? run.totalImages ?? 0),
      itemCount: Number(run.item_count ?? run.itemCount ?? 0),
      imageCount: Number(run.image_count ?? run.imageCount ?? 0),
      errorCount: Number(run.error_count ?? run.errorCount ?? 0),
      startedAt: Number(run.started_at ?? run.startedAt ?? 0),
      finishedAt: Number(run.finished_at ?? run.finishedAt ?? 0),
      progressPercent: Math.max(0, Math.min(100, Number.isFinite(progressPercent) ? progressPercent : 0))
    };
  }

  function pickLatestPromptSourceRun(sources, latestRun) {
    const candidates = [normalizePromptSourceRun(latestRun)];
    (Array.isArray(sources) ? sources : []).forEach(source => {
      candidates.push(normalizePromptSourceRun(source?.lastRun));
    });
    return candidates
      .filter(Boolean)
      .sort((a, b) => Math.max(b.finishedAt, b.startedAt) - Math.max(a.finishedAt, a.startedAt))[0] || null;
  }

  function isToday(timestamp) {
    const value = Number(timestamp || 0);
    if (!value) return false;
    const date = new Date(value * 1000);
    const now = new Date();
    return date.getFullYear() === now.getFullYear()
      && date.getMonth() === now.getMonth()
      && date.getDate() === now.getDate();
  }

  function historySortTime(item) {
    return Number(
      item?.finished_at
      || item?.updated_at
      || item?.created_at
      || item?.timestamp
      || 0
    ) || 0;
  }

  function getPromptTitle(item, limit = 22) {
    const prompt = String(item?.prompt || '').trim();
    if (!prompt) return '无提示词';
    return prompt.length > limit ? `${prompt.slice(0, limit)}...` : prompt;
  }

  function providerGroup(itemOrType) {
    const type = String(typeof itemOrType === 'string' ? itemOrType : itemOrType?.type || '').toLowerCase();
    if (type.startsWith('gpt')) return 'gpt';
    if (type === 'comfy') return 'comfy';
    if (type.includes('layout')) return 'layout';
    return 'google';
  }

  function providerLabel(itemOrType) {
    return {
      gpt: 'GPT',
      google: 'Google',
      comfy: 'Comfy',
      layout: '排版'
    }[providerGroup(itemOrType)] || '图片';
  }

  function imagePathForFile(item, file, index) {
    const paths = Array.isArray(item?.image_paths) ? item.image_paths : [];
    if (paths[index]) return paths[index];
    if (!file) return DesktopApi.getImagePath(item);
    return providerGroup(item) === 'gpt' ? `/gpt_outputs/${file}` : `/image/${file}`;
  }

  function thumbPathForAsset(item, file, imageUrl) {
    return thumbUrlForMediaUrl(imageUrl);
  }

  function flattenHistoryItems(items) {
    return (items || []).flatMap(item => {
      const resultFiles = Array.isArray(item.result_files) && item.result_files.length
        ? item.result_files
        : (Array.isArray(item.output_files) ? item.output_files : []);
      const primary = item.result_file || item.output_file || '';
      const files = resultFiles.length ? resultFiles : (primary ? [primary] : []);
      const paths = Array.isArray(item.image_paths) ? item.image_paths : [];
      const count = Math.max(files.length, paths.length);
      if (!count) return [];
      return Array.from({ length: count }, (_, index) => {
        const file = files[index] || files[0] || '';
        const imageUrl = paths[index] || imagePathForFile(item, file, index);
        const thumbUrl = thumbPathForAsset(item, file, imageUrl);
        const taskId = item.task_id || `history_${item.timestamp || item.created_at || index}`;
        return {
          id: `${taskId}:${index}:${file || imageUrl}`,
          taskId,
          file,
          imageUrl,
          imagePath: imageUrl,
          thumbUrl,
          title: `${getPromptTitle(item, 34)}${count > 1 ? ` · ${index + 1}/${count}` : ''}`,
          prompt: item.prompt || '',
          type: item.type || '',
          provider: providerGroup(item),
          providerLabel: providerLabel(item),
          status: item.status || '',
          createdAt: item.created_at || item.timestamp || 0,
          params: item.params || {},
          lineage: item.params?.lineage || {},
          referenceAssets: item.params?.lineage?.referenceAssets || item.params?.lineage?.reference_assets || [],
          referenceAssetIds: item.params?.lineage?.referenceAssetIds || item.params?.lineage?.reference_asset_ids || [],
          derivedAssets: [],
          derivedCount: 0,
          relatedAssets: [],
          relatedCount: 0,
          index,
          total: count,
          favorite: false,
          hidden: false,
          tags: [],
          item
        };
      }).filter(asset => asset.imageUrl);
    });
  }

  function isFileHistoryItem(item) {
    const type = String(item?.type || '').toLowerCase();
    const params = item?.params && typeof item.params === 'object' ? item.params : {};
    const artifactType = String(item?.artifact_type || item?.artifactType || params.artifact_type || params.artifactType || '').toLowerCase();
    const taskType = String(params.task_type || params.taskType || item?.task_type || item?.taskType || '').toLowerCase();
    return type === 'gpt-file'
      || artifactType === 'ppt'
      || artifactType === 'psd'
      || taskType === 'ppt'
      || taskType === 'psd';
  }

  function shouldShowHistoryItem(item) {
    if (isFileHistoryItem(item)) return false;
    if (flattenHistoryItems([item]).length) return true;
    return DesktopState.isInFlight(item?.status);
  }

  function setFooterStatusTone(el, tone = 'ok') {
    if (!el) return;
    el.classList.remove(
      'desk-status-chip--ok',
      'desk-status-chip--warn',
      'desk-status-chip--error',
      'desk-status-chip--checking'
    );
    const safeTone = ['ok', 'warn', 'error', 'checking'].includes(tone) ? tone : 'ok';
    el.classList.add(`desk-status-chip--${safeTone}`);
    el.dataset.tone = safeTone;
  }

  function renderCounters(items) {
    const todayCount = items.filter(item => isToday(item.created_at || item.timestamp)).length;
    const queueCount = items.filter(item => DesktopState.isInFlight(item.status)).length;
    DesktopState.state.todayCount = todayCount;
    DesktopState.state.queueCount = queueCount;
    if (els.deskTodayCount) {
      els.deskTodayCount.textContent = `今日任务 ${todayCount}`;
      setFooterStatusTone(els.deskTodayCount, 'ok');
    }
    if (els.deskQueueCount) {
      els.deskQueueCount.textContent = `队列 ${queueCount}`;
      setFooterStatusTone(els.deskQueueCount, queueCount > 0 ? 'warn' : 'ok');
      els.deskQueueCount.title = queueCount > 0 ? '有任务正在排队或生成' : '当前没有排队任务';
    }
  }

  function makeDragPayload(asset) {
    const activeAsset = withSelectedRemoteImage(asset);
    return {
      id: activeAsset.id || '',
      assetId: activeAsset.assetId || activeAsset.asset_id || activeAsset.id || '',
      taskId: activeAsset.taskId || '',
      imageUrl: activeAsset.imageUrl || '',
      imagePath: activeAsset.imagePath || activeAsset.imageUrl || '',
      title: activeAsset.title || '图库图片',
      prompt: activeAsset.prompt || '',
      type: activeAsset.type || '',
      provider: activeAsset.provider || '',
      file: activeAsset.file || '',
      archiveRelPath: activeAsset.archiveRelPath || '',
      sourceKind: activeAsset.sourceKind || '',
      hasTaskRecord: !!activeAsset.hasTaskRecord,
      source: activeAsset.source || 'gallery'
    };
  }

  function getRemoteImageUrls(asset) {
    if (asset?.sourceKind !== 'remote_source') return [];
    return Array.isArray(asset?.imageUrls) ? asset.imageUrls.filter(Boolean) : [];
  }

  function getRemoteImageIndex(asset) {
    const urls = getRemoteImageUrls(asset);
    if (!asset?.id || urls.length <= 1) return 0;
    const index = Number(remoteImageChoice.get(asset.id) || 0);
    return Math.max(0, Math.min(urls.length - 1, Number.isFinite(index) ? index : 0));
  }

  function withSelectedRemoteImage(asset) {
    if (!asset || asset.sourceKind !== 'remote_source') return asset;
    const urls = getRemoteImageUrls(asset);
    if (urls.length <= 1) return asset;
    const index = getRemoteImageIndex(asset);
    const imageUrl = urls[index] || asset.imageUrl || '';
    const imagePath = Array.isArray(asset.imagePaths) ? (asset.imagePaths[index] || asset.imagePaths[0] || '') : '';
    return {
      ...asset,
      imageUrl,
      imagePath: imageUrl,
      thumbUrl: thumbUrlForMediaUrl(imageUrl),
      file: imagePath ? imagePath.split('/').pop() : (asset.file || ''),
      index,
      total: urls.length,
      activeImageIndex: index
    };
  }

  function updateRemoteImageCard(asset) {
    if (!asset?.id) return;
    const urls = getRemoteImageUrls(asset);
    if (urls.length <= 1) return;
    const activeAsset = withSelectedRemoteImage(asset);
    const activeIndex = getRemoteImageIndex(asset);
    document.querySelectorAll('.desk-gallery-card[data-asset-id]').forEach(card => {
      if (card.dataset.assetId !== asset.id) return;
      const img = card.querySelector('.desk-gallery-card__image img');
      const imageUrl = activeAsset.imageUrl || '';
      if (img && imageUrl) {
        const src = mediaUrl(activeAsset.thumbUrl || thumbUrlForMediaUrl(imageUrl) || imageUrl);
        img.src = src;
        img.setAttribute('src', src);
        img.dataset.fallback = mediaUrl(imageUrl);
        card.draggable = true;
        card.classList.add('is-image-switching');
        window.setTimeout(() => card.classList.remove('is-image-switching'), 180);
      }
      const counter = card.querySelector('.desk-gallery-card__switcher span');
      if (counter) counter.textContent = `${activeIndex + 1}/${urls.length}`;
    });
  }

  function setRemoteImageIndex(assetId, nextIndex) {
    const asset = findAssetById(assetId, { raw: true });
    const urls = getRemoteImageUrls(asset);
    if (!asset?.id || urls.length <= 1) return;
    const index = (Number(nextIndex || 0) + urls.length) % urls.length;
    remoteImageChoice.set(asset.id, index);
    updateRemoteImageCard(asset);
    if (previewAsset?.id === asset.id) {
      previewAsset = withSelectedRemoteImage(asset);
      setPreviewAsset(previewAsset, true);
    }
    if (selectedGalleryIds.has(asset.id)) renderGallerySelection();
  }

  function isGalleryOpen() {
    return !!els.deskGalleryPanel?.classList.contains('is-open');
  }

  function resetGalleryRenderLimit() {
    galleryRenderLimit = galleryView === 'sources' ? PROMPT_SOURCE_INITIAL_RENDER_LIMIT : GALLERY_INITIAL_RENDER_LIMIT;
    if (els.deskGalleryGrid) {
      els.deskGalleryGrid.scrollTop = 0;
      const sourceScroll = els.deskGalleryGrid.querySelector('[data-prompt-source-scroll]');
      if (sourceScroll) sourceScroll.scrollTop = 0;
    }
  }

  function renderHistory(items) {
    const list = els.deskHistoryList;
    const visibleItems = (Array.isArray(items) ? items : [])
      .filter(shouldShowHistoryItem)
      .sort((a, b) => historySortTime(b) - historySortTime(a));
    DesktopState.state.history = visibleItems;
    const historyAssets = flattenHistoryItems(visibleItems);
    if (!galleryAssetsFromIndex || !isGalleryOpen()) {
      galleryAssets = historyAssets;
      galleryAssetTotal = galleryAssets.length;
    }
    if (isGalleryOpen()) {
      renderGallery();
      renderGallerySelection();
    }
    if (!list) return;
    if (!visibleItems.length) {
      list.innerHTML = '<div class="desk-history-empty">还没有历史记录</div>';
      list.scrollTop = 0;
      renderCounters([]);
      return;
    }

    list.innerHTML = visibleItems.slice(0, 24).map(item => {
      const firstAsset = flattenHistoryItems([item])[0] || null;
      const imagePath = firstAsset?.imageUrl || DesktopApi.getImagePath(item);
      const thumbPath = firstAsset?.thumbUrl || imagePath;
      const selected = item.task_id && item.task_id === DesktopState.state.selectedTaskId;
      const title = getPromptTitle(item);
      const retryable = isRetryableHistoryItem(item);
      const batchText = getBatchHistoryLabel(item);
      const editable = !!imagePath;
      const hasActions = retryable || editable;
      return `
        <div class="desk-history-row${hasActions ? ' has-actions' : ''}">
          <button type="button" class="desk-history-item${selected ? ' is-selected' : ''}" data-task-id="${escapeHtml(item.task_id || '')}" draggable="${imagePath ? 'true' : 'false'}" title="${imagePath ? '拖到画布创建图片节点' : '点击载入历史记录'}">
            <span class="desk-history-item__thumb">
              ${imagePath ? `<img src="${escapeHtml(mediaUrl(thumbPath))}" data-fallback="${escapeHtml(mediaUrl(imagePath))}" alt="" loading="lazy" decoding="async">` : '无图'}
            </span>
            <span class="desk-history-item__copy">
              <strong>${escapeHtml(title)}</strong>
              <span class="desk-history-item__meta">${DesktopState.getStatusLabel(item.status)}${batchText ? ` · ${escapeHtml(batchText)}` : ''} · ${formatTime(item.created_at || item.timestamp)}</span>
            </span>
          </button>
          ${hasActions ? `<span class="desk-history-row__actions">
            ${editable ? `<button type="button" class="desk-history-edit" data-history-edit="${escapeHtml(item.task_id || '')}" title="继续编辑" aria-label="继续编辑"><span class="desk-icon desk-icon--edit" aria-hidden="true"></span></button>` : ''}
            ${retryable ? `<button type="button" class="desk-history-retry" data-history-retry="${escapeHtml(item.task_id || '')}" title="创建新的重跑任务">重跑</button>` : ''}
          </span>` : ''}
        </div>
      `;
    }).join('');
    list.scrollTop = 0;

    list.querySelectorAll('img[data-fallback]').forEach(img => {
      img.addEventListener('error', () => {
        const fallback = img.dataset.fallback || '';
        if (fallback && img.src !== fallback) {
          img.removeAttribute('data-fallback');
          img.src = fallback;
        }
      }, { once: true });
    });

    list.querySelectorAll('.desk-history-item').forEach(button => {
      button.addEventListener('dragstart', event => {
        const item = DesktopState.state.history.find(entry => entry.task_id === button.dataset.taskId);
        const imagePath = DesktopApi.getImagePath(item);
        if (!item || !imagePath) {
          event.preventDefault();
          return;
        }
        event.dataTransfer.effectAllowed = 'copy';
        event.dataTransfer.setData('application/x-desktop-history-image', JSON.stringify({
          id: item.task_id || '',
          taskId: item.task_id || '',
          imageUrl: imagePath,
          title: getPromptTitle(item),
          prompt: item.prompt || '',
          type: item.type || '',
          provider: providerGroup(item),
          source: 'history'
        }));
        try {
          event.dataTransfer.setData('text/uri-list', new URL(imagePath, window.location.origin).href);
        } catch (e) {}
        button.classList.add('is-dragging');
      });
      button.addEventListener('dragend', () => {
        lastHistoryDragAt = Date.now();
        button.classList.remove('is-dragging');
      });
      button.addEventListener('click', () => {
        if (Date.now() - lastHistoryDragAt < 250) return;
        const item = DesktopState.state.history.find(entry => entry.task_id === button.dataset.taskId);
        if (!item) return;
        selectHistoryItem(item);
      });
    });
    list.querySelectorAll('[data-history-retry]').forEach(button => {
      button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        retryHistoryItem(button.dataset.historyRetry || '', button).catch(error => DesktopResults.showError(error));
      });
    });
    list.querySelectorAll('[data-history-edit]').forEach(button => {
      button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        continueEditHistoryItem(button.dataset.historyEdit || '').catch(error => DesktopResults.showError(error));
      });
    });

    renderCounters(items);
  }

  function getVisibleAssets() {
    const query = galleryQuery.trim().toLowerCase();
    const tagQuery = galleryTag.trim().replace(/^#/, '').toLowerCase();
    return galleryAssets.filter(asset => {
      const tags = parseTags(asset.tags);
      if (asset.hidden && galleryFilter !== 'hidden') return false;
      if (galleryFilter === 'today' && !isToday(asset.createdAt)) return false;
      if (galleryFilter === 'selected' && !selectedGalleryIds.has(asset.id)) return false;
      if (galleryFilter === 'favorite' && !asset.favorite) return false;
      if (galleryFilter === 'hidden' && !asset.hidden) return false;
      if (['gpt', 'google', 'comfy', 'layout'].includes(galleryFilter) && asset.provider !== galleryFilter) return false;
      if (galleryFilter === 'linked' && !asset.hasTaskRecord) return false;
      if (galleryFilter === 'orphan' && asset.hasTaskRecord) return false;
      if (galleryFilter === 'missing_history' && !asset.missingArchive) return false;
      if (['landscape', 'portrait', 'square'].includes(galleryFilter) && asset.orientation !== galleryFilter) return false;
      if (['1k', '2k', '4k'].includes(galleryFilter) && String(asset.resolution || '').toLowerCase() !== galleryFilter) return false;
      if (['png', 'jpg', 'webp'].includes(galleryFilter) && String(asset.format || '').toLowerCase() !== galleryFilter) return false;
      if (tagQuery && !tags.some(tag => tag.toLowerCase().includes(tagQuery))) return false;
      if (!query) return true;
      const haystack = assetMetaSearchText(asset).toLowerCase();
      return haystack.includes(query);
    });
  }

  function getVisibleEditableFiles() {
    const query = galleryQuery.trim().toLowerCase();
    return galleryFiles.filter(item => {
      if (galleryFilter === 'today' && !isToday(item.createdAt)) return false;
      if (galleryFilter === 'ppt' && item.kind !== 'PPT') return false;
      if (galleryFilter === 'psd' && item.kind !== 'PSD') return false;
      if (!query) return true;
      const haystack = [
        item.title,
        item.subject,
        item.prompt,
        item.kind,
        item.directoryRelative,
        item.primary?.name,
        item.zip?.name
      ].filter(Boolean).join(' ').toLowerCase();
      return haystack.includes(query);
    });
  }

  function getVisibleAssetSets() {
    const query = galleryQuery.trim().toLowerCase();
    const tagQuery = galleryTag.trim().replace(/^#/, '').toLowerCase();
    return gallerySets.filter(assetSet => {
      const setTags = parseTags(assetSet.tags);
      const assets = assetSet.assets || [];
      if (galleryFilter === 'today' && !isToday(assetSet.createdAt)) return false;
      if (galleryFilter === 'selected' && !assets.some(asset => selectedGalleryIds.has(asset.id))) return false;
      if (galleryFilter === 'favorite' && !assets.some(asset => asset.favorite)) return false;
      if (galleryFilter === 'hidden' && !assets.some(asset => asset.hidden)) return false;
      if (['gpt', 'google', 'comfy', 'layout'].includes(galleryFilter) && !assets.some(asset => asset.provider === galleryFilter)) return false;
      if (galleryFilter === 'linked' && !assets.some(asset => asset.hasTaskRecord)) return false;
      if (galleryFilter === 'orphan' && !assets.some(asset => !asset.hasTaskRecord)) return false;
      if (galleryFilter === 'missing_history' && !assets.some(asset => asset.missingArchive)) return false;
      if (['landscape', 'portrait', 'square'].includes(galleryFilter) && !assets.some(asset => asset.orientation === galleryFilter)) return false;
      if (['1k', '2k', '4k'].includes(galleryFilter) && !assets.some(asset => String(asset.resolution || '').toLowerCase() === galleryFilter)) return false;
      if (['png', 'jpg', 'webp'].includes(galleryFilter) && !assets.some(asset => String(asset.format || '').toLowerCase() === galleryFilter)) return false;
      if (tagQuery) {
        const allTags = [
          ...setTags,
          ...assets.flatMap(asset => parseTags(asset.tags))
        ].map(tag => tag.toLowerCase());
        if (!allTags.some(tag => tag.includes(tagQuery))) return false;
      }
      if (!query) return true;
      const haystack = [
        assetSet.name,
        setTags.join(' '),
        ...assets.map(assetMetaSearchText)
      ].join(' ').toLowerCase();
      return haystack.includes(query);
    });
  }

  function getVisiblePromptSourceItems() {
    const query = galleryQuery.trim().toLowerCase();
    const tagQuery = galleryTag.trim().replace(/^#/, '').toLowerCase();
    return promptSourceItems.filter(asset => {
      const tags = parseTags(asset.tags);
      const taxonomy = normalizeTaxonomy(asset.taxonomy || asset.promptTaxonomy);
      if (promptSourceFilter !== 'all' && asset.params?.prompt_source !== promptSourceFilter && asset.sourceSlug !== promptSourceFilter) return false;
      if (promptSourceTaxonomyFilters.style && !taxonomy.style.includes(promptSourceTaxonomyFilters.style)) return false;
      if (promptSourceTaxonomyFilters.subject && !taxonomy.subject.includes(promptSourceTaxonomyFilters.subject)) return false;
      if (promptSourceTaxonomyFilters.type && !taxonomy.type.includes(promptSourceTaxonomyFilters.type)) return false;
      if (tagQuery && !tags.some(tag => tag.toLowerCase().includes(tagQuery))) return false;
      if (!query) return true;
      const haystack = [
        asset.title,
        asset.prompt,
        asset.providerLabel,
        asset.file,
        asset.sourceUrl,
        tags.join(' ')
      ].filter(Boolean).join(' ').toLowerCase();
      return haystack.includes(query);
    });
  }

  function getSelectedAssets() {
    const byId = new Map();
    galleryAssets.forEach(asset => {
      if (asset?.id) byId.set(asset.id, asset);
    });
    promptSourceItems.forEach(asset => {
      if (asset?.id) byId.set(asset.id, asset);
    });
    (activeGallerySet?.assets || []).forEach(asset => {
      const normalized = normalizeGalleryAsset(asset);
      if (normalized.id && !byId.has(normalized.id)) byId.set(normalized.id, normalized);
    });
    gallerySets.forEach(assetSet => {
      (assetSet.assets || []).forEach(asset => {
        const normalized = normalizeGalleryAsset(asset);
        if (normalized.id && !byId.has(normalized.id)) byId.set(normalized.id, normalized);
      });
    });
    if (previewAsset?.id && selectedGalleryIds.has(previewAsset.id) && !byId.has(previewAsset.id)) {
      byId.set(previewAsset.id, previewAsset);
    }
    const selected = [...selectedGalleryIds].map(id => byId.get(id)).filter(Boolean).map(withSelectedRemoteImage);
    selectedGalleryIds.forEach(id => {
      if (!selected.some(asset => asset.id === id)) selectedGalleryIds.delete(id);
    });
    return selected;
  }

  function updateGalleryCardState(assetId) {
    if (!assetId) return;
    const asset = findAssetById(assetId, { raw: true });
    const selected = selectedGalleryIds.has(assetId);
    const focused = previewAsset?.id === assetId;
    document.querySelectorAll('.desk-gallery-card[data-asset-id]').forEach(card => {
      if (card.dataset.assetId !== assetId) return;
      card.classList.toggle('is-selected', selected);
      card.classList.toggle('is-focus-active', focused);
      card.classList.toggle('is-favorite', !!asset?.favorite);
      const selectButton = card.querySelector('[data-gallery-select]');
      if (selectButton) {
        selectButton.setAttribute('aria-pressed', selected ? 'true' : 'false');
        selectButton.title = selected ? '取消选择' : '选择图片';
        selectButton.setAttribute('aria-label', selected ? '取消选择' : '选择');
      }
      const favoriteButton = card.querySelector('[data-gallery-favorite]');
      if (favoriteButton) {
        favoriteButton.setAttribute('aria-pressed', asset?.favorite ? 'true' : 'false');
        favoriteButton.title = asset?.favorite ? '取消收藏' : '收藏';
        favoriteButton.setAttribute('aria-label', asset?.favorite ? '取消收藏' : '收藏');
      }
    });
  }

  function restoreGalleryCardFocus(assetId) {
    if (!assetId) return;
    updateGalleryCardState(assetId);
    window.requestAnimationFrame(() => {
      const cards = Array.from(document.querySelectorAll('.desk-gallery-card[data-asset-id]'))
        .filter(card => card.dataset.assetId === assetId);
      const card = cards[0];
      if (!card) return;
      card.setAttribute('tabindex', '-1');
      try {
        card.focus({ preventScroll: true });
      } catch (error) {
        card.focus();
      }
    });
  }

  function focusGalleryAsset(assetId) {
    const asset = findAssetById(assetId);
    if (!asset) return null;
    previewAsset = asset;
    if (els.deskGalleryPreviewModal?.classList.contains('is-open')) {
      setPreviewAsset(asset, false);
    }
    updateGalleryCardState(assetId);
    return asset;
  }

  function toggleAssetSelection(assetId, force) {
    if (!assetId) return;
    focusGalleryAsset(assetId);
    const shouldSelect = typeof force === 'boolean' ? force : !selectedGalleryIds.has(assetId);
    if (shouldSelect) selectedGalleryIds.add(assetId);
    else selectedGalleryIds.delete(assetId);
    if (galleryFilter === 'selected') {
      renderGallery();
    } else {
      updateGalleryCardState(assetId);
    }
    renderGallerySelection();
    restoreGalleryCardFocus(assetId);
  }

  function getPreviewAssets() {
    if (galleryView === 'sources') {
      const visible = getVisiblePromptSourceItems();
      if (previewAsset && visible.some(asset => asset.id === previewAsset.id)) return visible.map(withSelectedRemoteImage);
      return promptSourceItems.map(withSelectedRemoteImage);
    }
    if (galleryView === 'setDetail' && activeGallerySet?.assets?.length) {
      return activeSetAssets(activeGallerySet);
    }
    const visible = getVisibleAssets();
    if (previewAsset && visible.some(asset => asset.id === previewAsset.id)) return visible;
    return galleryAssets;
  }

  function getPreviewIndex(asset = previewAsset) {
    const assets = getPreviewAssets();
    return assets.findIndex(item => item.id === asset?.id);
  }

  function getPreviewNegativePrompt(asset) {
    const params = asset?.params && typeof asset.params === 'object' ? asset.params : {};
    return params.negative_prompt
      || params.negativePrompt
      || params.negative
      || asset?.item?.negative_prompt
      || asset?.item?.negativePrompt
      || '';
  }

  function normalizeLineageAsset(item) {
    if (!item || typeof item !== 'object') return null;
    const id = item.asset_id || item.id || '';
    const imageUrl = item.imageUrl || item.image_url || item.imagePath || item.image_path || '';
    const missing = !!(item.missing || item.deleted || item.isMissing || item.isDeleted);
    if (!id && !imageUrl && !missing) return null;
    return {
      ...item,
      id,
      asset_id: id,
      taskId: item.taskId || item.task_id || '',
      imageUrl,
      imagePath: item.imagePath || item.image_path || imageUrl,
      thumbUrl: preferredThumbUrl(item.thumbUrl || item.thumb_url, imageUrl),
      title: item.title || item.name || item.file || '图片资产',
      prompt: item.prompt || '',
      provider: item.provider || '',
      providerLabel: item.providerLabel || item.provider_label || item.source || '来源',
      createdAt: item.createdAt || item.created_at || 0,
      missing
    };
  }

  function getLineageReferences(asset) {
    const params = asset?.params && typeof asset.params === 'object' ? asset.params : {};
    const lineage = asset?.lineage || params.lineage || {};
    const refs = Array.isArray(asset?.referenceAssets)
      ? asset.referenceAssets
      : (Array.isArray(lineage.referenceAssets) ? lineage.referenceAssets : (Array.isArray(lineage.reference_assets) ? lineage.reference_assets : []));
    return refs.map(normalizeLineageAsset).filter(Boolean);
  }

  function getLineageChildren(asset) {
    const lineage = asset?.lineage || {};
    const children = Array.isArray(asset?.derivedAssets)
      ? asset.derivedAssets
      : (Array.isArray(lineage.derivedAssets) ? lineage.derivedAssets : (Array.isArray(lineage.derived_assets) ? lineage.derived_assets : []));
    return children.map(normalizeLineageAsset).filter(Boolean);
  }

  function getRelatedLineageAssets(asset) {
    const lineage = asset?.lineage || {};
    const related = Array.isArray(asset?.relatedAssets)
      ? asset.relatedAssets
      : (Array.isArray(lineage.relatedAssets) ? lineage.relatedAssets : (Array.isArray(lineage.related_assets) ? lineage.related_assets : []));
    return related.map(normalizeLineageAsset).filter(Boolean);
  }

  function findAssetById(assetId, options = {}) {
    const id = String(assetId || '').trim();
    if (!id) return null;
    const asset = galleryAssets.find(asset => asset.id === id)
      || promptSourceItems.find(asset => asset.id === id)
      || (activeGallerySet?.assets || []).find(asset => asset.id === id)
      || gallerySets.flatMap(assetSet => assetSet.assets || []).find(asset => asset.id === id)
      || null;
    return options.raw ? asset : withSelectedRemoteImage(asset);
  }

  function lineageThumb(asset) {
    if (asset?.missing) {
      return '<span class="is-missing" aria-hidden="true">删</span>';
    }
    const image = asset.thumbUrl || asset.imageUrl || '';
    if (image) {
      return `<img src="${escapeHtml(mediaUrl(image))}" alt="${escapeHtml(asset.title || '图片资产')}" loading="lazy">`;
    }
    return '<span aria-hidden="true">源</span>';
  }

  function renderLineageGroup(title, items, emptyLabel = '') {
    if (!items.length) return emptyLabel ? `<div class="desk-gallery-lineage-empty">${escapeHtml(emptyLabel)}</div>` : '';
    return `
      <div class="desk-gallery-lineage-group">
        <strong>${escapeHtml(title)}</strong>
        <div class="desk-gallery-lineage-list">
          ${items.slice(0, 8).map(item => {
            const index = previewLineageItems.push(item) - 1;
            const missing = !!item.missing;
            const chipTitle = missing ? '来源已删除' : (item.title || '查看图片');
            return `
              <button type="button" class="desk-gallery-lineage-chip${missing ? ' is-missing' : ''}" data-lineage-index="${index}" title="${escapeHtml(chipTitle)}"${missing ? ' aria-disabled="true"' : ''}>
                ${lineageThumb(item)}
                <em>${escapeHtml(missing ? '来源已删除' : (item.title || item.asset_id || '图片资产'))}</em>
              </button>
            `;
          }).join('')}
        </div>
      </div>
    `;
  }

  function renderPreviewLineage(asset) {
    const refs = getLineageReferences(asset);
    const children = getLineageChildren(asset);
    const related = getRelatedLineageAssets(asset);
    const hasLineage = refs.length || children.length || related.length || Number(asset?.derivedCount || 0) || Number(asset?.relatedCount || 0);
    previewLineageItems = [];
    if (els.deskGalleryPreviewLineageBlock) els.deskGalleryPreviewLineageBlock.hidden = !hasLineage;
    if (els.deskGalleryPreviewLineageDivider) els.deskGalleryPreviewLineageDivider.hidden = !hasLineage;
    if (!els.deskGalleryPreviewLineage) return;
    if (!hasLineage) {
      els.deskGalleryPreviewLineage.innerHTML = '';
      return;
    }
    const totalDerived = Number(asset?.derivedCount || 0);
    const derivedLabel = totalDerived > children.length
      ? (children.length ? `已派生 ${totalDerived} 张，显示最近 ${children.length} 张` : `已派生 ${totalDerived} 张`)
      : '';
    const totalRelated = Number(asset?.relatedCount || 0);
    const relatedLabel = totalRelated > related.length
      ? (related.length ? `同源 ${totalRelated} 张，显示最近 ${related.length} 张` : `同源 ${totalRelated} 张`)
      : '';
    els.deskGalleryPreviewLineage.innerHTML = [
      renderLineageGroup('使用了这些参考图', refs, refs.length ? '' : '没有记录参考图'),
      renderLineageGroup('同源图片', related, relatedLabel),
      renderLineageGroup('派生出了这些图片', children, derivedLabel)
    ].filter(Boolean).join('');
    els.deskGalleryPreviewLineage.querySelectorAll('[data-lineage-index]').forEach(button => {
      button.addEventListener('click', () => {
        const item = previewLineageItems[Number(button.dataset.lineageIndex || 0)];
        if (!item || item.missing) return;
        const fullAsset = findAssetById(item.id) || normalizeGalleryAsset(item);
        if (fullAsset) setPreviewAsset(fullAsset, true);
      });
    });
  }

  function getPreviewMetaRows(asset) {
    const params = asset?.params && typeof asset.params === 'object' ? asset.params : {};
    const routeTrace = Array.isArray(params.route_trace)
      ? params.route_trace
        .map(item => {
          const routeLabels = {
            chatgpt_pool: '账号池',
            chatgpt_pool_editable: '账号池文件',
            browser: '浏览器',
            codex: 'Codex',
            codex_edit: 'Codex 编辑'
          };
          const categoryLabels = {
            offline: '离线',
            auth: '鉴权',
            rate_limited: '限流',
            quota: '额度',
            timeout: '超时',
            artifact_download: '文件下载',
            model_refusal: '模型拒绝',
            proxy: '代理链路',
            browser: '浏览器',
            sidecar: 'Sidecar',
            provider: 'Provider',
            unknown: '未知'
          };
          const route = routeLabels[item?.route] || item?.route;
          const status = item?.status === 'succeeded' ? '成功' : (item?.status === 'failed' ? '失败' : (item?.status === 'skipped' ? '跳过' : (item?.status === 'started' ? '开始' : item?.status)));
          const elapsed = item?.elapsed_seconds != null ? ` ${item.elapsed_seconds}s` : '';
          const category = item?.status === 'failed' && item?.error_category ? ` · ${categoryLabels[item.error_category] || item.error_category}` : '';
          return [route, status].filter(Boolean).join(':') + elapsed + category;
        })
        .filter(Boolean)
        .join(' → ')
      : '';
    const model = params.main_model || asset?.mainModel || params.model || params.modelAlias || asset?.item?.model || asset?.providerLabel || providerLabel(asset);
    const ratio = params.ratio || params.aspect_ratio || params.aspectRatio || asset?.aspectRatio || '';
    const resolution = galleryAssetResolutionLabel(asset, params);
    const source = asset?.sourceKind === 'remote_source'
      ? (asset?.sourceName || asset?.providerLabel || '远程源')
      : (asset?.missingArchive ? '记录缺图' : (asset?.hasTaskRecord ? '有任务记录' : '仅归档文件'));
    const pixels = asset?.megapixels ? `${Number(asset.megapixels).toFixed(2).replace(/\.?0+$/, '')} MP` : '';
    const rows = [
      ['Model', model],
      ['线路', params.gpt_provider_route === 'chatgpt_pool' ? '账号池 API' : (['codex', 'managed_codex_oauth'].includes(params.gpt_provider_route) ? '本地 Codex' : '')],
      ['路由轨迹', routeTrace],
      ['主模型', params.main_model || asset?.mainModel || ''],
      ['推理强度', params.reasoning_effort || asset?.reasoningEffort || ''],
      ['提示词模式', params.prompt_mode || ''],
      ['类型', asset?.providerLabel || providerLabel(asset)],
      ['来源', source],
      ['尺寸', asset?.dimensions || (asset?.width && asset?.height ? `${asset.width} × ${asset.height}` : '')],
      ['比例', ratio],
      ['方向', asset?.orientationLabel || orientationLabel(asset?.orientation)],
      ['分辨率', resolution],
      ['质量', params.quality || ''],
      ['格式', asset?.format || normalizeImageFormat(params.format, asset?.file)],
      ['大小', asset?.fileSizeLabel || formatFileSize(asset?.fileSizeBytes)],
      ['像素', pixels],
      ['序号', asset?.total > 1 ? `${asset.index + 1} / ${asset.total}` : ''],
      ['收藏', asset?.favorite ? '是' : ''],
      ['隐藏', asset?.hidden ? '是' : ''],
      ['标签', parseTags(asset?.tags).join(' / ')],
      ['远程链接', asset?.sourceUrl || params.source_url || ''],
      ['仓库', asset?.repoUrl || params.source_repo || ''],
      ['文件', asset?.file || ''],
      ['生成时间', formatPreviewTime(asset?.createdAt)]
    ].filter(([, value]) => String(value || '').trim());
    return rows.map(([label, value]) => `
      <div class="desk-gallery-preview__meta-row">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `).join('');
  }

  function updatePreviewCounter() {
    const assets = getPreviewAssets();
    const index = getPreviewIndex();
    const galleryTotal = galleryView === 'images' && galleryAssetsFromIndex
      ? Number(galleryAssetTotal || 0)
      : 0;
    const total = Math.max(assets.length, galleryTotal, previewAsset ? 1 : 0);
    if (els.deskGalleryPreviewCounter) {
      els.deskGalleryPreviewCounter.textContent = total ? `${Math.max(index, 0) + 1} / ${total}` : '0 / 0';
    }
    const disabled = total <= 1;
    if (els.deskGalleryPreviewPrevBtn) els.deskGalleryPreviewPrevBtn.disabled = disabled;
    if (els.deskGalleryPreviewNextBtn) els.deskGalleryPreviewNextBtn.disabled = disabled;
  }

  function renderPreviewActions(asset = previewAsset) {
    const hasAsset = !!asset;
    const hasImage = !!(asset?.imageUrl || asset?.imagePath);
    const isRemote = asset?.sourceKind === 'remote_source';
    const hasFile = !!asset?.file && !isRemote;
    const hasConfig = !!(asset?.prompt || (asset?.params && Object.keys(asset.params || {}).length));
    if (els.deskGalleryPreviewFavoriteBtn) {
      const active = !!asset?.favorite;
      els.deskGalleryPreviewFavoriteBtn.disabled = !hasAsset || isRemote;
      els.deskGalleryPreviewFavoriteBtn.setAttribute('aria-pressed', active ? 'true' : 'false');
      els.deskGalleryPreviewFavoriteBtn.title = active ? '取消收藏' : '收藏';
      els.deskGalleryPreviewFavoriteBtn.setAttribute('aria-label', active ? '取消收藏' : '收藏');
    }
    if (els.deskGalleryPreviewHideBtn) {
      const active = !!asset?.hidden;
      els.deskGalleryPreviewHideBtn.disabled = !hasAsset || isRemote;
      els.deskGalleryPreviewHideBtn.setAttribute('aria-pressed', active ? 'true' : 'false');
      els.deskGalleryPreviewHideBtn.title = active ? '取消隐藏' : '隐藏';
      els.deskGalleryPreviewHideBtn.setAttribute('aria-label', active ? '取消隐藏' : '隐藏');
    }
    if (els.deskGalleryPreviewTagBtn) els.deskGalleryPreviewTagBtn.disabled = !hasAsset || isRemote;
    if (els.deskGalleryPreviewApplyBtn) els.deskGalleryPreviewApplyBtn.disabled = !hasConfig;
    if (els.deskGalleryPreviewCanvasBtn) els.deskGalleryPreviewCanvasBtn.disabled = !hasImage;
    if (els.deskGalleryPreviewEditBtn) els.deskGalleryPreviewEditBtn.disabled = !hasImage;
    if (els.deskGalleryPreviewSendBtn) els.deskGalleryPreviewSendBtn.disabled = !hasFile;
    if (els.deskGalleryPreviewLayoutBtn) els.deskGalleryPreviewLayoutBtn.disabled = !hasImage;
    if (els.deskGalleryPreviewDeleteBtn) els.deskGalleryPreviewDeleteBtn.disabled = !hasAsset || isRemote;
    if (els.deskGalleryPreviewCompareBtn) {
      const queued = previewCompareQueue.some(item => item.id === asset?.id);
      const label = queued ? '移出待对比' : (previewCompareQueue.length ? '加入对比 B' : '加入对比');
      els.deskGalleryPreviewCompareBtn.disabled = !hasImage;
      els.deskGalleryPreviewCompareBtn.setAttribute('aria-pressed', queued ? 'true' : 'false');
      els.deskGalleryPreviewCompareBtn.title = label;
      els.deskGalleryPreviewCompareBtn.setAttribute('aria-label', label);
    }
  }

  function getPreviewStageRect() {
    return els.deskGalleryPreviewStage?.getBoundingClientRect?.() || null;
  }

  function getPreviewFitRect() {
    const stageRect = getPreviewStageRect();
    const img = els.deskGalleryPreviewImg;
    if (!stageRect || !img) return null;
    const naturalWidth = Number(img.naturalWidth || 0);
    const naturalHeight = Number(img.naturalHeight || 0);
    if (!naturalWidth || !naturalHeight || !stageRect.width || !stageRect.height) {
      return {
        left: 0,
        top: 0,
        width: stageRect?.width || 0,
        height: stageRect?.height || 0,
        stageWidth: stageRect?.width || 0,
        stageHeight: stageRect?.height || 0
      };
    }
    const ratio = Math.min(stageRect.width / naturalWidth, stageRect.height / naturalHeight);
    const width = naturalWidth * ratio;
    const height = naturalHeight * ratio;
    return {
      left: (stageRect.width - width) / 2,
      top: (stageRect.height - height) / 2,
      width,
      height,
      stageWidth: stageRect.width,
      stageHeight: stageRect.height
    };
  }

  function clampPreviewPan() {
    const fit = getPreviewFitRect();
    if (!fit) return;
    const scaledWidth = fit.width * previewZoom;
    const scaledHeight = fit.height * previewZoom;
    const maxX = Math.max(0, Math.abs(scaledWidth - fit.stageWidth) / 2);
    const maxY = Math.max(0, Math.abs(scaledHeight - fit.stageHeight) / 2);
    previewPan = {
      x: Math.max(-maxX, Math.min(maxX, Number(previewPan.x) || 0)),
      y: Math.max(-maxY, Math.min(maxY, Number(previewPan.y) || 0))
    };
  }

  function applyPreviewZoom() {
    const img = els.deskGalleryPreviewImg;
    const fit = getPreviewFitRect();
    if (img && fit) {
      img.style.left = `${fit.left}px`;
      img.style.top = `${fit.top}px`;
      img.style.width = `${fit.width}px`;
      img.style.height = `${fit.height}px`;
      clampPreviewPan();
      img.style.transform = `translate(${previewPan.x}px, ${previewPan.y}px) scale(${previewZoom})`;
    }
    if (els.deskGalleryPreviewZoomOutBtn) els.deskGalleryPreviewZoomOutBtn.disabled = previewZoom <= PREVIEW_ZOOM_MIN;
    if (els.deskGalleryPreviewZoomInBtn) els.deskGalleryPreviewZoomInBtn.disabled = previewZoom >= PREVIEW_ZOOM_MAX;
  }

  function getPreviewRevisedPrompt(asset) {
    const params = asset?.params && typeof asset.params === 'object' ? asset.params : {};
    const revised = asset?.revisedPrompt || asset?.revised_prompt || params.revised_prompt || '';
    if (revised) return String(revised);
    const list = Array.isArray(params.revised_prompts) ? params.revised_prompts : [];
    return String(list.find(Boolean) || '');
  }

  function renderPromptCompare(asset = previewAsset) {
    const revisedPrompt = getPreviewRevisedPrompt(asset);
    const hasRevised = !!revisedPrompt.trim();
    const open = previewPromptCompareOpen && hasRevised;
    els.deskGalleryPreviewModal?.classList.toggle('is-prompt-compare', open);
    if (els.deskGalleryPreviewRevisedPrompt) {
      els.deskGalleryPreviewRevisedPrompt.textContent = revisedPrompt || '无 revised_prompt';
    }
    if (els.deskGalleryPreviewRevisedBlock) {
      els.deskGalleryPreviewRevisedBlock.hidden = !open;
    }
    if (els.deskGalleryPreviewPromptCompareBtn) {
      els.deskGalleryPreviewPromptCompareBtn.disabled = !hasRevised;
      els.deskGalleryPreviewPromptCompareBtn.classList.toggle('is-active', open);
      els.deskGalleryPreviewPromptCompareBtn.setAttribute('aria-pressed', open ? 'true' : 'false');
      els.deskGalleryPreviewPromptCompareBtn.title = hasRevised ? (open ? '收起 revised_prompt' : '对比 revised_prompt') : '当前图片没有 revised_prompt';
    }
    if (els.deskGalleryPreviewCopyRevisedBtn) {
      els.deskGalleryPreviewCopyRevisedBtn.disabled = !hasRevised;
    }
    requestAnimationFrame(applyPreviewZoom);
  }

  function setPreviewAsset(asset, resetZoom = true) {
    if (!asset) return;
    previewAsset = asset;
    if (resetZoom) {
      previewZoom = 1;
      previewPan = { x: 0, y: 0 };
    }
    const negativePrompt = getPreviewNegativePrompt(asset);
    const imageSrc = mediaUrl(asset.imageUrl || '');
    if (els.deskGalleryPreviewBackdropImg) {
      els.deskGalleryPreviewBackdropImg.src = imageSrc;
      els.deskGalleryPreviewBackdropImg.alt = '';
    }
    if (els.deskGalleryPreviewImg) {
      els.deskGalleryPreviewImg.src = imageSrc;
      els.deskGalleryPreviewImg.alt = asset.title || '原图预览';
    }
    if (els.deskGalleryPreviewTitle) els.deskGalleryPreviewTitle.textContent = asset.title || '图片资产';
    if (els.deskGalleryPreviewPrompt) els.deskGalleryPreviewPrompt.textContent = asset.prompt || '无提示词';
    if (els.deskGalleryPreviewNegativePrompt) els.deskGalleryPreviewNegativePrompt.textContent = negativePrompt || '无';
    if (els.deskGalleryPreviewNegativeBlock) els.deskGalleryPreviewNegativeBlock.hidden = !negativePrompt;
    if (els.deskGalleryPreviewNegativeDivider) els.deskGalleryPreviewNegativeDivider.hidden = !negativePrompt;
    if (els.deskGalleryPreviewMeta) els.deskGalleryPreviewMeta.innerHTML = getPreviewMetaRows(asset);
    renderPreviewLineage(asset);
    if (els.deskGalleryPreviewCopyBtn) els.deskGalleryPreviewCopyBtn.disabled = !asset.prompt;
    renderPromptCompare(asset);
    updatePreviewCounter();
    renderPreviewActions(asset);
    applyPreviewZoom();
  }

  function openPreview(asset) {
    if (!asset) return;
    setPreviewAsset(asset, true);
    els.deskGalleryPreviewModal?.classList.add('is-open');
    els.deskGalleryPreviewModal?.setAttribute('aria-hidden', 'false');
  }

  function closePreview() {
    els.deskGalleryPreviewModal?.classList.remove('is-open');
    els.deskGalleryPreviewModal?.classList.remove('is-prompt-compare');
    els.deskGalleryPreviewModal?.setAttribute('aria-hidden', 'true');
    previewPromptCompareOpen = false;
    if (els.deskGalleryPreviewImg) {
      els.deskGalleryPreviewImg.style.transform = '';
      els.deskGalleryPreviewImg.style.left = '';
      els.deskGalleryPreviewImg.style.top = '';
      els.deskGalleryPreviewImg.style.width = '';
      els.deskGalleryPreviewImg.style.height = '';
    }
    if (els.deskGalleryPreviewBackdropImg) {
      els.deskGalleryPreviewBackdropImg.src = '';
    }
    els.deskGalleryPreviewStage?.classList.remove('is-dragging');
    previewAsset = null;
    previewZoom = 1;
    previewPan = { x: 0, y: 0 };
    previewDrag = null;
  }

  async function copyPreviewPrompt() {
    const prompt = previewAsset?.prompt || '';
    if (!prompt) return;
    await navigator.clipboard.writeText(prompt);
    DesktopResults.showTransientMessage('提示词已复制。');
  }

  async function copyPreviewRevisedPrompt() {
    const prompt = getPreviewRevisedPrompt(previewAsset);
    if (!prompt) return;
    await navigator.clipboard.writeText(prompt);
    DesktopResults.showTransientMessage('revised_prompt 已复制。');
  }

  function togglePreviewPromptCompare() {
    const hasRevised = !!getPreviewRevisedPrompt(previewAsset).trim();
    if (!hasRevised) return;
    previewPromptCompareOpen = !previewPromptCompareOpen;
    renderPromptCompare(previewAsset);
  }

  function openPreviewOriginal() {
    const url = previewAsset?.imageUrl || '';
    if (!url) return;
    window.open(mediaUrl(url), '_blank', 'noopener');
  }

  function navigatePreview(direction) {
    const assets = getPreviewAssets();
    if (!previewAsset || assets.length <= 1) return;
    const index = getPreviewIndex();
    const currentIndex = index >= 0 ? index : 0;
    const nextIndex = (currentIndex + direction + assets.length) % assets.length;
    setPreviewAsset(assets[nextIndex], true);
  }

  function zoomPreview(delta) {
    previewZoom = Math.max(PREVIEW_ZOOM_MIN, Math.min(PREVIEW_ZOOM_MAX, Number((previewZoom + delta).toFixed(2))));
    applyPreviewZoom();
  }

  function startPreviewDrag(event) {
    if (!previewAsset || event.button !== 0) return;
    previewDrag = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      baseX: previewPan.x,
      baseY: previewPan.y
    };
    els.deskGalleryPreviewStage?.classList.add('is-dragging');
    try {
      els.deskGalleryPreviewStage?.setPointerCapture?.(event.pointerId);
    } catch (e) {}
    event.preventDefault();
  }

  function movePreviewDrag(event) {
    if (!previewDrag || event.pointerId !== previewDrag.pointerId) return;
    previewPan = {
      x: previewDrag.baseX + (event.clientX - previewDrag.startX),
      y: previewDrag.baseY + (event.clientY - previewDrag.startY)
    };
    applyPreviewZoom();
    event.preventDefault();
  }

  function endPreviewDrag(event) {
    if (!previewDrag || event.pointerId !== previewDrag.pointerId) return;
    previewDrag = null;
    els.deskGalleryPreviewStage?.classList.remove('is-dragging');
    try {
      els.deskGalleryPreviewStage?.releasePointerCapture?.(event.pointerId);
    } catch (e) {}
  }

  function renderGalleryImageCard(asset, index) {
    const activeAsset = withSelectedRemoteImage(asset);
    const selected = selectedGalleryIds.has(asset.id);
    const focused = previewAsset?.id === asset.id;
    const refCount = getLineageReferences(asset).length;
    const derivedCount = Number(asset.derivedCount || 0);
    const isRemote = asset.sourceKind === 'remote_source';
    const remoteImages = getRemoteImageUrls(asset);
    const activeImageIndex = getRemoteImageIndex(asset);
    const hasSwitcher = remoteImages.length > 1;
    const hasIndexBadge = !hasSwitcher && asset.total > 1;
    const params = activeAsset?.params && typeof activeAsset.params === 'object' ? activeAsset.params : {};
    const imageHtml = activeAsset.imageUrl
      ? `<img src="${escapeHtml(mediaUrl(activeAsset.thumbUrl || activeAsset.imageUrl))}" data-fallback="${escapeHtml(mediaUrl(activeAsset.imageUrl))}" alt="" draggable="false" loading="lazy" decoding="async" fetchpriority="${index < 8 ? 'high' : 'low'}">`
      : '<div class="desk-gallery-card__missing">记录缺图</div>';
    const sourceBadge = isRemote ? (asset.stale ? '远程已删' : '远程源') : (asset.missingArchive ? '记录缺图' : (asset.hasTaskRecord ? '有记录' : '仅归档'));
    const modelLabel = galleryAssetModelLabel(activeAsset, params);
    const ratioLabel = galleryAssetRatioLabel(activeAsset, params);
    const resolutionLabel = galleryAssetResolutionLabel(activeAsset, params);
    const summaryLine = `比例 ${ratioLabel} · 分辨率 ${resolutionLabel}`;
    const detailLine = [
      modelLabel,
      sourceBadge,
      asset.format
    ].filter(Boolean).join(' · ');
    return `
      <article class="desk-gallery-card${selected ? ' is-selected' : ''}${focused ? ' is-focus-active' : ''}${asset.favorite ? ' is-favorite' : ''}${isRemote ? ' is-remote-source' : ''}${hasSwitcher ? ' has-gallery-switcher' : ''}${hasIndexBadge ? ' has-gallery-count' : ''}${asset.hidden ? ' is-hidden-asset' : ''}${asset.missingArchive ? ' is-missing-archive' : ''}${asset.stale ? ' is-stale-remote' : ''}" data-asset-id="${escapeHtml(asset.id)}" draggable="${asset.imageUrl ? 'true' : 'false'}" tabindex="-1">
        <div class="desk-gallery-card__image">
          ${imageHtml}
          ${asset.stale ? '<div class="desk-gallery-card__remote-state">远程已删</div>' : ''}
          ${hasSwitcher ? `
            <div class="desk-gallery-card__switcher" aria-label="切换示例图">
              <button type="button" data-remote-image-step="-1" data-asset-id="${escapeHtml(asset.id)}" title="上一张示例图" aria-label="上一张示例图">‹</button>
              <span>${activeImageIndex + 1}/${remoteImages.length}</span>
              <button type="button" data-remote-image-step="1" data-asset-id="${escapeHtml(asset.id)}" title="下一张示例图" aria-label="下一张示例图">›</button>
            </div>
          ` : (hasIndexBadge ? `<span>${asset.index + 1}/${asset.total}</span>` : '')}
        </div>
        <div class="desk-gallery-card__meta">
          <div class="desk-gallery-card__meta-copy">
            <div class="desk-gallery-card__meta-head">
              <strong>${escapeHtml(modelLabel)}</strong>
            </div>
            <span class="desk-gallery-card__description">${escapeHtml(summaryLine)}</span>
            <em>${escapeHtml(detailLine)}</em>
          </div>
          <div class="desk-gallery-card__meta-actions" aria-label="图片操作">
            ${refCount || derivedCount ? `
              <div class="desk-gallery-card__lineage" aria-label="图片溯源">
                ${refCount ? `<em>源 ${refCount}</em>` : ''}
                ${derivedCount ? `<em>派 ${derivedCount}</em>` : ''}
              </div>
            ` : ''}
            ${isRemote ? '' : `
              <button type="button" class="desk-gallery-card__favorite" data-gallery-favorite="${escapeHtml(asset.id)}" aria-pressed="${asset.favorite ? 'true' : 'false'}" title="${asset.favorite ? '取消收藏' : '收藏'}" aria-label="${asset.favorite ? '取消收藏' : '收藏'}">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5 14.7 9l6 .9-4.3 4.2 1 5.9-5.4-2.8L6.6 20l1-5.9L3.3 9.9l6-.9L12 3.5Z"></path></svg>
              </button>
            `}
            <button type="button" class="desk-gallery-card__select" data-gallery-select="${escapeHtml(asset.id)}" aria-pressed="${selected ? 'true' : 'false'}" title="${selected ? '取消选择' : '选择图片'}" aria-label="${selected ? '取消选择' : '选择'}">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4 10-10"></path></svg>
            </button>
          </div>
        </div>
      </article>
    `;
  }

  function renderGalleryScrollHint(remaining) {
    if (remaining <= 0) return '';
    return `
      <div class="desk-gallery-scroll-hint" data-gallery-scroll-hint>
        向下滚动加载剩余 ${remaining} 张
      </div>
    `;
  }

  function renderGalleryStats() {
    if (!els.deskGalleryStats) return;
    if (galleryView === 'sources') {
      els.deskGalleryStats.hidden = true;
      els.deskGalleryStats.innerHTML = '';
      return;
    }
    els.deskGalleryStats.hidden = false;
    if (galleryView === 'files') {
      const stats = galleryFileStats || {};
      const value = key => Number(stats[key] || 0).toLocaleString('zh-CN');
      els.deskGalleryStats.innerHTML = [
        `文件 ${value('total')}`,
        `PPT ${value('ppt')}`,
        `PSD ${value('psd')}`,
        `已归档 ${value('archived')}`,
        `本地临时 ${value('local')}`
      ].map(item => `<span>${escapeHtml(item)}</span>`).join('');
      return;
    }
    const stats = galleryAssetStats || {};
    const value = key => Number(stats[key] || 0).toLocaleString('zh-CN');
    els.deskGalleryStats.innerHTML = [
      `Obsidian ${value('obsidian_image_count')}`,
      `图库 ${value('gallery_asset_count')}`,
      `有记录 ${value('task_record_image_count')}`,
      `孤儿 ${value('orphan_asset_count')}`,
      `有尺寸 ${value('metadata_image_count')}`,
      `记录缺图 ${value('history_missing_count')}`
    ].map(item => `<span>${escapeHtml(item)}</span>`).join('');
  }

  function renderGalleryImages() {
    const grid = els.deskGalleryGrid;
    if (!grid) return;
    renderGalleryStats();
    const assets = getVisibleAssets();
    if (!assets.length) {
      grid.innerHTML = '<div class="desk-gallery-empty">没有匹配的图片资产</div>';
      return;
    }
    renderVirtualGalleryCards(grid, assets);
    bindGalleryCardEvents();
  }

  function galleryVirtualMetrics(container) {
    const styles = window.getComputedStyle(container);
    const readPx = (name, fallback) => {
      const value = parseFloat(styles.getPropertyValue(name) || styles[name] || '');
      return Number.isFinite(value) && value > 0 ? value : fallback;
    };
    const cardWidth = readPx('--desk-gallery-card-size', 142);
    const cardHeight = readPx('--desk-gallery-card-height', 214);
    const gap = readPx('--desk-gallery-card-gap', 8);
    const padLeft = readPx('padding-left', 0);
    const padRight = readPx('padding-right', 0);
    const padTop = readPx('padding-top', 0);
    const padBottom = readPx('padding-bottom', 0);
    const availableWidth = Math.max(cardWidth, container.clientWidth - padLeft - padRight);
    const columns = Math.max(1, Math.floor((availableWidth + gap) / (cardWidth + gap)));
    const contentWidth = columns * cardWidth + Math.max(0, columns - 1) * gap;
    const align = styles.justifyContent || '';
    const extraWidth = Math.max(0, availableWidth - contentWidth);
    const offsetLeft = padLeft + (align.includes('center') ? extraWidth / 2 : 0);
    return {
      cardWidth,
      cardHeight,
      gap,
      columns,
      rowHeight: cardHeight + gap,
      padTop,
      padBottom,
      offsetLeft,
    };
  }

  function virtualGalleryWindow(container, total, metrics) {
    const rows = Math.ceil(total / metrics.columns);
    const scrollTop = Math.max(0, container.scrollTop - metrics.padTop);
    const startRow = Math.max(0, Math.floor(scrollTop / metrics.rowHeight) - GALLERY_VIRTUAL_OVERSCAN_ROWS);
    const visibleRows = Math.max(1, Math.ceil(container.clientHeight / metrics.rowHeight));
    const endRow = Math.min(rows, startRow + visibleRows + GALLERY_VIRTUAL_OVERSCAN_ROWS * 2 + 1);
    return {
      rows,
      startIndex: Math.max(0, startRow * metrics.columns),
      endIndex: Math.min(total, endRow * metrics.columns),
      totalHeight: Math.max(0, rows * metrics.rowHeight - metrics.gap) + metrics.padTop + metrics.padBottom,
    };
  }

  function renderVirtualGalleryCards(container, assets) {
    const items = Array.isArray(assets) ? assets : [];
    if (!items.length) {
      container.innerHTML = '<div class="desk-gallery-empty">没有匹配的图片资产</div>';
      return;
    }
    const metrics = galleryVirtualMetrics(container);
    const range = virtualGalleryWindow(container, items.length, metrics);
    const cards = items.slice(range.startIndex, range.endIndex).map((asset, offset) => {
      const index = range.startIndex + offset;
      const column = index % metrics.columns;
      const row = Math.floor(index / metrics.columns);
      const x = Math.round(metrics.offsetLeft + column * (metrics.cardWidth + metrics.gap));
      const y = Math.round(metrics.padTop + row * metrics.rowHeight);
      return `<div class="desk-gallery-virtual-cell" style="transform: translate3d(${x}px, ${y}px, 0); width: ${metrics.cardWidth}px; height: ${metrics.cardHeight}px;">${renderGalleryImageCard(asset, index)}</div>`;
    }).join('');
    container.innerHTML = `
      <div class="desk-gallery-virtual-canvas" data-gallery-virtual-canvas style="height: ${Math.ceil(range.totalHeight)}px;">
        ${cards}
      </div>
    `;
  }

  function scheduleGalleryVirtualRender(container = null) {
    const target = container || (galleryView === 'sources'
      ? els.deskGalleryGrid?.querySelector('[data-prompt-source-scroll]')
      : els.deskGalleryGrid);
    if (!target || !['images', 'sources'].includes(galleryView)) return;
    if (target.__galleryVirtualFrame) return;
    target.__galleryVirtualFrame = window.requestAnimationFrame(() => {
      target.__galleryVirtualFrame = 0;
      const assets = galleryView === 'sources' ? getVisiblePromptSourceItems() : getVisibleAssets();
      if (!assets.length) return;
      renderVirtualGalleryCards(target, assets);
      bindGalleryCardEvents();
    });
  }

  function renderEditableFileCard(file) {
    const previewHtml = file.previewUrl
      ? `<img src="${escapeHtml(file.previewUrl)}" alt="" loading="lazy" decoding="async">`
      : `<div class="desk-gallery-file__missing">${escapeHtml(file.kind)}</div>`;
    const storage = file.archived ? '已归档' : '本地临时';
    const previewStatus = file.preview?.status ? `预览 ${file.preview.status}` : '';
    return `
      <article class="desk-gallery-file" data-file-id="${escapeHtml(file.id)}">
        <button type="button" class="desk-gallery-file__preview" data-gallery-file-preview="${escapeHtml(file.id)}" title="预览文件">
          ${previewHtml}
          <span>${escapeHtml(file.kind)}</span>
        </button>
        <div class="desk-gallery-file__body">
          <strong title="${escapeHtml(file.title)}">${escapeHtml(file.title)}</strong>
          <span>${escapeHtml([file.metaLabel, storage, previewStatus].filter(Boolean).join(' · '))}</span>
          <em title="${escapeHtml(file.directoryRelative)}">${escapeHtml(file.directoryRelative || file.subject)}</em>
        </div>
        <div class="desk-gallery-file__actions">
          ${file.primary?.url ? `<a href="${escapeHtml(file.primary.url)}" target="_blank" rel="noopener">打开</a>` : ''}
          ${file.zip?.url ? `<a href="${escapeHtml(file.zip.url)}" target="_blank" rel="noopener">ZIP</a>` : ''}
          <button type="button" data-gallery-file-send="${escapeHtml(file.id)}">发送</button>
          <button type="button" class="is-danger" data-gallery-file-delete="${escapeHtml(file.id)}">删除</button>
        </div>
      </article>
    `;
  }

  function findEditableFile(id) {
    return galleryFiles.find(item => item.id === id || item.directoryRelative === id);
  }

  function filePreviewStageHtml(file) {
    const preview = file?.preview || {};
    const firstPage = Array.isArray(preview.pages) ? preview.pages[0] : null;
    const imageUrl = file?.previewUrl || preview.image_url || preview.imageUrl || firstPage?.url || '';
    if (imageUrl) {
      return `<img src="${escapeHtml(imageUrl)}" alt="${escapeHtml(file?.title || '文件预览')}">`;
    }
    if (preview.pdf_url || preview.pdfUrl) {
      return `<iframe src="${escapeHtml(preview.pdf_url || preview.pdfUrl)}" title="PPT PDF 预览"></iframe>`;
    }
    const message = preview.message || (preview.status === 'missing_dependency' ? '未检测到预览依赖，文件已保存。' : '暂无预览，可直接打开主文件。');
    return `<div class="desk-file-preview-modal__fallback"><strong>${escapeHtml(file?.kind || '文件')}</strong><span>${escapeHtml(message)}</span></div>`;
  }

  function filePreviewMetaHtml(file) {
    const rows = [
      ['类型', file?.kind || ''],
      ['状态', file?.archived ? '已归档' : '本地临时'],
      ['预览', file?.preview?.status || ''],
      ['页数', file?.preview?.page_count ? `${file.preview.page_count} 页` : ''],
      ['图层', file?.preview?.layer_count ? `${file.preview.layer_count} 图层` : ''],
      ['大小', file?.sizeLabel || ''],
      ['目录', file?.directoryRelative || '']
    ].filter(([, value]) => value !== '');
    return rows.map(([label, value]) => `<span><b>${escapeHtml(label)}</b>${escapeHtml(value)}</span>`).join('');
  }

  function setActionLink(link, url) {
    if (!link) return;
    const hasUrl = !!url;
    link.href = hasUrl ? url : '#';
    link.toggleAttribute('aria-disabled', !hasUrl);
    link.classList.toggle('is-disabled', !hasUrl);
  }

  function renderEditableFilePreview(file) {
    if (!file) return;
    if (els.deskFilePreviewStage) els.deskFilePreviewStage.innerHTML = filePreviewStageHtml(file);
    if (els.deskFilePreviewKind) els.deskFilePreviewKind.textContent = `${file.kind || '文件'} 资产`;
    if (els.deskFilePreviewTitle) els.deskFilePreviewTitle.textContent = file.title || file.subject || '文件预览';
    if (els.deskFilePreviewMeta) els.deskFilePreviewMeta.innerHTML = filePreviewMetaHtml(file);
    if (els.deskFilePreviewPrompt) els.deskFilePreviewPrompt.textContent = file.prompt || '无提示词';
    const layers = Array.isArray(file.preview?.layers) ? file.preview.layers : [];
    if (els.deskFilePreviewLayersBlock) els.deskFilePreviewLayersBlock.hidden = !layers.length;
    if (els.deskFilePreviewLayers) {
      els.deskFilePreviewLayers.innerHTML = layers.slice(0, 24).map(layer => `
        <a href="${escapeHtml(layer.url)}" target="_blank" rel="noopener" title="${escapeHtml(layer.name || '图层')}">
          <img src="${escapeHtml(layer.url)}" alt="">
          <span>${escapeHtml(layer.name || '图层')}</span>
        </a>
      `).join('');
    }
    setActionLink(els.deskFilePreviewOpenBtn, file.primary?.url || '');
    setActionLink(els.deskFilePreviewZipBtn, file.zip?.url || '');
    setActionLink(els.deskFilePreviewManifestBtn, file.manifest_url || file.manifestUrl || '');
    if (els.deskFilePreviewSendBtn) els.deskFilePreviewSendBtn.disabled = !file.primary?.relative_path;
    if (els.deskFilePreviewDeleteBtn) els.deskFilePreviewDeleteBtn.disabled = !file.directoryRelative;
  }

  function openEditableFilePreview(file) {
    if (!file) return;
    previewEditableFile = file;
    renderEditableFilePreview(file);
    els.deskFilePreviewModal?.classList.add('is-open');
    els.deskFilePreviewModal?.setAttribute('aria-hidden', 'false');
  }

  function closeEditableFilePreview() {
    els.deskFilePreviewModal?.classList.remove('is-open');
    els.deskFilePreviewModal?.setAttribute('aria-hidden', 'true');
    previewEditableFile = null;
  }

  async function sendEditableFile(file, button) {
    if (!file?.primary?.relative_path) throw new Error('文件不存在');
    const originalText = button?.textContent;
    try {
      if (button) {
        button.disabled = true;
        button.textContent = '发送中';
      }
      await DesktopApi.sendEditableFile({
        relative_path: file.primary.relative_path,
        caption: `📎 ${file.kind} 文件\n${file.subject || file.title || ''}`.trim()
      });
      DesktopResults.showTransientMessage(`${file.kind} 文件已发送到 Telegram。`);
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = originalText || '发送';
      }
    }
  }

  async function deleteEditableFile(file, button) {
    if (!file) return;
    if (!window.confirm(`删除文件目录？\n${file.title}`)) return;
    const originalText = button?.textContent;
    try {
      if (button) {
        button.disabled = true;
        button.textContent = '删除中';
      }
      await DesktopApi.deleteEditableFile({ directory_relative: file.directoryRelative });
      galleryFiles = galleryFiles.filter(item => item.id !== file.id);
      if (previewEditableFile?.id === file.id) closeEditableFilePreview();
      renderGallery();
      DesktopResults.showTransientMessage('文件目录已删除。');
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = originalText || '删除';
      }
    }
  }

  function bindGalleryFileEvents() {
    els.deskGalleryGrid?.querySelectorAll('[data-gallery-file-preview]').forEach(button => {
      if (button.dataset.filePreviewBound === '1') return;
      button.dataset.filePreviewBound = '1';
      button.addEventListener('click', () => {
        openEditableFilePreview(findEditableFile(button.dataset.galleryFilePreview || ''));
      });
    });
    els.deskGalleryGrid?.querySelectorAll('[data-gallery-file-send]').forEach(button => {
      if (button.dataset.fileSendBound === '1') return;
      button.dataset.fileSendBound = '1';
      button.addEventListener('click', async () => {
        const file = findEditableFile(button.dataset.galleryFileSend || '');
        try {
          await sendEditableFile(file, button);
        } catch (error) {
          DesktopResults.showError(error);
        }
      });
    });
    els.deskGalleryGrid?.querySelectorAll('[data-gallery-file-delete]').forEach(button => {
      if (button.dataset.fileDeleteBound === '1') return;
      button.dataset.fileDeleteBound = '1';
      button.addEventListener('click', async () => {
        const file = findEditableFile(button.dataset.galleryFileDelete || '');
        try {
          await deleteEditableFile(file, button);
        } catch (error) {
          DesktopResults.showError(error);
        }
      });
    });
  }

  function renderGalleryFiles() {
    const grid = els.deskGalleryGrid;
    if (!grid) return;
    renderGalleryStats();
    const files = getVisibleEditableFiles();
    if (!files.length) {
      grid.innerHTML = '<div class="desk-gallery-empty">没有匹配的 PPT / PSD 文件</div>';
      return;
    }
    grid.innerHTML = files.map(renderEditableFileCard).join('');
    bindGalleryFileEvents();
  }

  function promptSourceSummaryChips() {
    const itemCount = promptSources.reduce((sum, source) => sum + Number(source.itemCount || 0), 0);
    const imageCount = promptSources.reduce((sum, source) => sum + Number(source.imageCount || 0), 0);
    const staleCount = promptSources.reduce((sum, source) => sum + Number(source.staleItemCount || source.stale_item_count || 0), 0);
    const activeSource = promptSourceFilter === 'all'
      ? null
      : promptSources.find(source => source.slug === promptSourceFilter);
    const activeName = promptSourceFilter === 'all'
      ? '全部远程源'
      : (activeSource?.name || '远程源');
    const activeItems = activeSource ? Number(activeSource.itemCount || 0) : Number(promptSourceTotal || itemCount);
    const activeImages = activeSource ? Number(activeSource.imageCount || 0) : imageCount;
    const activeStale = activeSource ? Number(activeSource.staleItemCount || activeSource.stale_item_count || 0) : staleCount;
    const activePath = activeSource?.localPath || activeSource?.local_path || '';
    const activeRun = normalizePromptSourceRun(promptSourceSyncRun || lastPromptSourceSyncRun);
    const syncLabel = activeRun?.status === 'running' ? `同步 ${Math.max(1, Math.round(activeRun.progressPercent || 1))}%` : '';
    const chips = [
      { label: activeName, type: 'name' },
      promptSourceFilter === 'all' ? { label: `源 ${promptSources.length.toLocaleString('zh-CN')}` } : null,
      { label: `条目 ${activeItems.toLocaleString('zh-CN')}` },
      { label: `本地图 ${activeImages.toLocaleString('zh-CN')}` },
      activeStale ? { label: `已删 ${activeStale.toLocaleString('zh-CN')}` } : null,
      activePath ? { label: `路径 ${activePath}`, type: 'path' } : null,
      ...PROMPT_SOURCE_TAXONOMY_GROUPS
        .map(([key, label]) => promptSourceTaxonomyFilters[key] ? { label: `${label} ${promptSourceTaxonomyFilters[key]}` } : null),
      syncLabel ? { label: syncLabel, type: 'sync' } : null
    ].filter(Boolean);
    return chips.map(item => {
      const typeClass = item.type ? ` desk-prompt-source-chip--${item.type}` : '';
      return `<span class="desk-prompt-source-chip${typeClass}" title="${escapeHtml(item.label)}">${escapeHtml(item.label)}</span>`;
    }).join('');
  }

  function renderPromptSourceTabs() {
    const buttons = [
      `<button type="button" class="${promptSourceFilter === 'all' ? 'is-active' : ''}" data-prompt-source-filter="all">全部</button>`,
      ...promptSources.map(source => `
        <button type="button" class="${promptSourceFilter === source.slug ? 'is-active' : ''}" data-prompt-source-filter="${escapeHtml(source.slug)}" title="${escapeHtml(source.localPath || '')}">
          ${escapeHtml(source.name)}
        </button>
      `)
    ];
    return `<div class="desk-prompt-source-tabs"><i class="desk-prompt-source-tabs__slider" aria-hidden="true"></i>${buttons.join('')}</div>`;
  }

  function renderPromptSourceTaxonomyFilters() {
    const activeFilters = PROMPT_SOURCE_TAXONOMY_GROUPS
      .map(([key, label]) => promptSourceTaxonomyFilters[key] ? `${label}: ${promptSourceTaxonomyFilters[key]}` : '')
      .filter(Boolean);
    const hasActiveFilters = activeFilters.length > 0;
    const rows = PROMPT_SOURCE_TAXONOMY_GROUPS.map(([key, label]) => {
      const facets = Array.isArray(promptSourceTaxonomyFacets[key]) ? promptSourceTaxonomyFacets[key] : [];
      const activeValue = promptSourceTaxonomyFilters[key] || '';
      const buttons = [
        `<button type="button" class="${activeValue ? '' : 'is-active'}" data-prompt-taxonomy-group="${escapeHtml(key)}" data-prompt-taxonomy-value="">全部</button>`,
        ...facets.map(facet => `
          <button type="button" class="${activeValue === facet.value ? 'is-active' : ''}" data-prompt-taxonomy-group="${escapeHtml(key)}" data-prompt-taxonomy-value="${escapeHtml(facet.value)}">
            ${escapeHtml(facet.label)} <span>${Number(facet.count || 0).toLocaleString('zh-CN')}</span>
          </button>
        `)
      ];
      return `
        <div class="desk-prompt-source-taxonomy__row">
          <strong>${escapeHtml(label)}</strong>
          <div>${buttons.join('')}</div>
        </div>
      `;
    });
    return `
      <div class="desk-prompt-source-taxonomy ${promptSourceTaxonomyCollapsed ? 'is-collapsed' : ''}">
        <div class="desk-prompt-source-taxonomy__head">
          <button type="button" data-prompt-taxonomy-toggle>
            ${promptSourceTaxonomyCollapsed ? '展开分类' : '收起分类'}
          </button>
          <span>${hasActiveFilters ? escapeHtml(activeFilters.join(' / ')) : '风格 / 主体 / 类型'}</span>
          ${hasActiveFilters ? '<button type="button" data-prompt-taxonomy-clear>清除</button>' : ''}
        </div>
        ${promptSourceTaxonomyCollapsed ? '' : `<div class="desk-prompt-source-taxonomy__body">${rows.join('')}</div>`}
      </div>
    `;
  }

  function renderPromptSourceSyncStatus() {
    const run = normalizePromptSourceRun(promptSourceSyncRun || lastPromptSourceSyncRun);
    if (!run || run.status !== 'running') return '';
    const isRunning = run.status === 'running';
    const percent = isRunning ? Math.max(1, Math.round(run.progressPercent || 1)) : 100;
    const title = isRunning
      ? `同步中 ${percent}%`
      : `${run.status === 'succeeded' ? '同步完成' : (run.status === 'canceled' ? '已停止同步' : '同步结束')} · ${formatPreviewTime(run.finishedAt)}`;
    const sourceText = run.currentSourceName
      ? `${run.currentSourceName}${run.totalSources ? ` ${run.sourceIndex || 1}/${run.totalSources}` : ''}`
      : (run.sourceSlug === 'all' ? '全部远程源' : '远程源');
    const itemText = run.totalItems
      ? `条目 ${run.processedItems}/${run.totalItems}`
      : (run.itemCount ? `条目 ${run.itemCount}` : '');
    const imageText = run.totalImages
      ? `图片 ${run.processedImages}/${run.totalImages}`
      : (run.imageCount ? `图片 ${run.imageCount}` : '');
    const errorText = run.errorCount ? `失败 ${run.errorCount}` : '';
    const detail = [run.phase, sourceText, itemText, imageText, errorText].filter(Boolean).join(' · ');
    const message = run.message ? run.message.slice(0, 140) : '';
    return `
      <div class="desk-prompt-source-sync ${isRunning ? 'is-running' : 'is-done'}">
        <div class="desk-prompt-source-sync__top">
          <strong>${escapeHtml(title)}</strong>
          <span>${escapeHtml(detail)}</span>
        </div>
        <div class="desk-prompt-source-sync__bar" aria-hidden="true">
          <i style="width: ${percent}%"></i>
        </div>
        ${message ? `<em>${escapeHtml(message)}</em>` : ''}
      </div>
    `;
  }

  function renderPromptSourceHeader() {
    const activeRun = normalizePromptSourceRun(promptSourceSyncRun);
    const isRunning = activeRun?.status === 'running';
    return `
      <section class="desk-prompt-source-head">
        <div class="desk-prompt-source-head__main">
          <div>
            <strong>远程源资料库</strong>
            <div class="desk-prompt-source-head__meta">${promptSourceSummaryChips()}</div>
          </div>
        </div>
        <div class="desk-prompt-source-actions">
          ${isRunning ? `<button type="button" class="is-danger" data-prompt-source-stop="${escapeHtml(activeRun.runId || promptSourceSyncRunId || '')}">停止同步</button>` : ''}
          ${promptSourceFilter !== 'all' ? `<button type="button" data-prompt-source-sync="${escapeHtml(promptSourceFilter)}">同步当前</button>` : ''}
          <button type="button" data-prompt-source-sync="all">同步全部</button>
          <button type="button" data-prompt-source-refresh>刷新</button>
        </div>
      </section>
    `;
  }

  function renderPromptSources() {
    const grid = els.deskGalleryGrid;
    if (!grid) return;
    renderGalleryStats();
    const items = getVisiblePromptSourceItems();
    grid.innerHTML = [
      `<div class="desk-prompt-source-controls">
        ${renderPromptSourceHeader()}
        ${renderPromptSourceTabs()}
        ${renderPromptSourceTaxonomyFilters()}
        ${renderPromptSourceSyncStatus()}
      </div>`,
      `<div class="desk-prompt-source-scroll" data-prompt-source-scroll>
        ${items.length ? '' : '<div class="desk-gallery-empty">还没有同步远程源，或没有匹配的提示词。</div>'}
      </div>`
    ].join('');
    if (items.length) {
      const scroller = grid.querySelector('[data-prompt-source-scroll]');
      renderVirtualGalleryCards(scroller, items);
    }
    bindPromptSourceEvents();
    bindGalleryCardEvents();
    schedulePromptSourceTabSlider();
  }

  function schedulePromptSourceTabSlider() {
    if (galleryView !== 'sources') return;
    window.requestAnimationFrame(updatePromptSourceTabSlider);
  }

  function updatePromptSourceTabSlider() {
    const tabs = els.deskGalleryGrid?.querySelector('.desk-prompt-source-tabs');
    const slider = tabs?.querySelector('.desk-prompt-source-tabs__slider');
    const active = tabs?.querySelector('button.is-active');
    if (!tabs || !slider || !active) return;
    slider.style.setProperty('--prompt-source-slider-x', `${active.offsetLeft}px`);
    slider.style.setProperty('--prompt-source-slider-w', `${active.offsetWidth}px`);
  }

  function bindPromptSourceEvents() {
    els.deskGalleryGrid?.querySelectorAll('[data-prompt-source-filter]').forEach(button => {
      button.addEventListener('click', () => {
        promptSourceFilter = button.dataset.promptSourceFilter || 'all';
        promptSourceTaxonomyFilters = { style: '', subject: '', type: '' };
        promptSourceTaxonomyCollapsed = true;
        resetGalleryRenderLimit();
        loadPromptSourceItems().catch(error => DesktopResults.showError(error));
      });
    });
    els.deskGalleryGrid?.querySelector('.desk-prompt-source-tabs')?.addEventListener('scroll', schedulePromptSourceTabSlider, { passive: true });
    els.deskGalleryGrid?.querySelector('[data-prompt-taxonomy-toggle]')?.addEventListener('click', () => {
      promptSourceTaxonomyCollapsed = !promptSourceTaxonomyCollapsed;
      renderGallery();
    });
    els.deskGalleryGrid?.querySelector('[data-prompt-taxonomy-clear]')?.addEventListener('click', () => {
      promptSourceTaxonomyFilters = { style: '', subject: '', type: '' };
      promptSourceTaxonomyCollapsed = true;
      resetGalleryRenderLimit();
      loadPromptSourceItems().catch(error => DesktopResults.showError(error));
    });
    els.deskGalleryGrid?.querySelectorAll('[data-prompt-taxonomy-group]').forEach(button => {
      button.addEventListener('click', () => {
        const group = button.dataset.promptTaxonomyGroup || '';
        if (!Object.prototype.hasOwnProperty.call(promptSourceTaxonomyFilters, group)) return;
        promptSourceTaxonomyFilters = {
          ...promptSourceTaxonomyFilters,
          [group]: button.dataset.promptTaxonomyValue || ''
        };
        resetGalleryRenderLimit();
        loadPromptSourceItems().catch(error => DesktopResults.showError(error));
      });
    });
    els.deskGalleryGrid?.querySelectorAll('[data-prompt-source-sync]').forEach(button => {
      button.addEventListener('click', () => {
        const source = button.dataset.promptSourceSync || 'all';
        syncPromptSources(source, button).catch(error => DesktopResults.showError(error));
      });
    });
    els.deskGalleryGrid?.querySelectorAll('[data-prompt-source-stop]').forEach(button => {
      button.addEventListener('click', () => {
        stopPromptSourceSync(button.dataset.promptSourceStop || promptSourceSyncRunId, button).catch(error => DesktopResults.showError(error));
      });
    });
    els.deskGalleryGrid?.querySelector('[data-prompt-source-refresh]')?.addEventListener('click', () => {
      refreshPromptSources().catch(error => DesktopResults.showError(error));
    });
    els.deskGalleryGrid?.querySelector('[data-prompt-source-scroll]')?.addEventListener('scroll', event => {
      scheduleGalleryVirtualRender(event.currentTarget);
    }, { passive: true });
  }

  function clearGalleryHoverState(container) {
    if (!container) return;
    if (typeof container.__clearGalleryHover === 'function') container.__clearGalleryHover();
    container.classList.remove('is-card-hovering');
    container.querySelectorAll('.is-hover-active').forEach(card => card.classList.remove('is-hover-active'));
  }

  // Hover focus uses native pointer-event delegation: the browser hit-tests which
  // card is under the pointer (event.target), so we never compute coordinates,
  // offsets, or per-card caches. Exactly one card is active globally, which also
  // stops two nested scroll containers (image grid vs remote-source scroll) from
  // each lighting up a card. Bind once on the outer grid; both image cards and
  // remote-source cards are descendants, so their pointerover events bubble here.
  function bindGalleryHoverState(container) {
    if (!container || container.dataset.galleryHoverBound === '1') return;
    container.dataset.galleryHoverBound = '1';
    const cardSelector = '.desk-gallery-card, .desk-gallery-set';
    const scopeSelector = '.desk-gallery-grid, .desk-prompt-source-scroll';
    let activeCard = null;
    const scopeOf = card => card.closest(scopeSelector) || container;
    const clear = () => {
      if (!activeCard) return;
      activeCard.classList.remove('is-hover-active');
      scopeOf(activeCard).classList.remove('is-card-hovering');
      activeCard = null;
    };
    const setActive = card => {
      if (!card || card === activeCard) return;
      if (activeCard) {
        activeCard.classList.remove('is-hover-active');
        const prevScope = scopeOf(activeCard);
        const nextScope = scopeOf(card);
        if (prevScope !== nextScope) prevScope.classList.remove('is-card-hovering');
      }
      activeCard = card;
      card.classList.add('is-hover-active');
      scopeOf(card).classList.add('is-card-hovering');
    };
    container.__clearGalleryHover = clear;
    // pointerover switches the active card; over a gap/controls we keep the last
    // active card (no flicker when crossing the gap between cards). Full clear
    // happens only when the pointer leaves the whole grid. Scrolling moves a new
    // card under a stationary pointer, which also fires pointerover and switches.
    container.addEventListener('pointerover', event => {
      if (event.pointerType === 'touch') return;
      const card = event.target?.closest?.(cardSelector);
      if (card && container.contains(card)) setActive(card);
    }, { passive: true });
    container.addEventListener('pointerleave', clear, { passive: true });
  }

  function renderGallerySetCard(assetSet) {
    const assets = assetSet.assets || [];
    const thumbs = assets.slice(0, 4);
    const tags = parseTags(assetSet.tags);
    const count = Number(assetSet.count || assets.length || 0);
    return `
      <article class="desk-gallery-set" data-asset-set-id="${escapeHtml(assetSet.id)}" draggable="${assets.length ? 'true' : 'false'}">
        <div class="desk-gallery-set__thumbs">
          ${thumbs.length ? thumbs.map(asset => `<img src="${escapeHtml(mediaUrl(asset.thumbUrl || asset.imageUrl))}" data-fallback="${escapeHtml(mediaUrl(asset.imageUrl))}" alt="" loading="lazy" decoding="async">`).join('') : '<em>空集</em>'}
        </div>
        <div class="desk-gallery-set__info">
          <strong>${escapeHtml(assetSet.name || '未命名候选集')}</strong>
          <em>${count} 张 · ${escapeHtml(formatTime(assetSet.updatedAt || assetSet.createdAt))}</em>
          ${tags.length ? `<div class="desk-gallery-set__meta">${tags.slice(0, 4).map(tag => `<span>#${escapeHtml(tag)}</span>`).join('')}</div>` : ''}
          <div class="desk-gallery-set__actions">
            <button type="button" data-asset-set-detail="${escapeHtml(assetSet.id)}">详情</button>
            <button type="button" data-asset-set-open="${escapeHtml(assetSet.id)}">选择</button>
            <button type="button" data-asset-set-input="${escapeHtml(assetSet.id)}" ${assets.length ? '' : 'disabled'}>模型</button>
            <button type="button" data-asset-set-compare="${escapeHtml(assetSet.id)}" ${assets.length < 2 ? 'disabled' : ''}>对比</button>
            <button type="button" data-asset-set-layout="${escapeHtml(assetSet.id)}" ${assets.length ? '' : 'disabled'}>排版</button>
            <button type="button" data-asset-set-delete="${escapeHtml(assetSet.id)}">删除</button>
          </div>
        </div>
      </article>
    `;
  }

  function openAssetSet(assetSet, switchToImages = true) {
    if (!assetSet?.assets?.length) {
      DesktopResults.showTransientMessage('候选集里还没有可用图片。');
      return;
    }
    mergeAssetsFromSet(assetSet);
    selectedGalleryIds.clear();
    assetSet.assets.forEach(asset => selectedGalleryIds.add(asset.id));
    if (switchToImages) {
      activeGallerySet = null;
      galleryView = 'images';
      galleryFilter = 'selected';
      resetGalleryRenderLimit();
      renderGallery();
    } else {
      renderGallery();
    }
    renderGallerySelection();
    DesktopResults.showTransientMessage(`${assetSet.assets.length} 张图片已放入选择篮。`);
  }

  function openAssetSetDetail(assetSet) {
    if (!assetSet?.id) return;
    activeGallerySet = normalizeAssetSet(assetSet);
    replaceGallerySet(activeGallerySet);
    galleryView = 'setDetail';
    resetGalleryRenderLimit();
    renderGallery();
  }

  function compareAssetSet(assetSet) {
    if (!assetSet?.assets || assetSet.assets.length < 2) {
      DesktopResults.showTransientMessage('候选集至少需要 2 张图片才能对比。');
      return;
    }
    mergeAssetsFromSet(assetSet);
    openCompare(assetSet.assets.slice(0, 2));
  }

  function attachAssetSetToLayout(assetSet) {
    const assets = assetSet?.assets || [];
    if (!assets.length) {
      DesktopResults.showTransientMessage('候选集里还没有可用图片。');
      return;
    }
    mergeAssetsFromSet(assetSet);
    window.DesktopCanvas?.attachHistoryImagesToLayout?.(assets.map(makeDragPayload))
      ?.catch?.(error => DesktopResults.showError(error));
  }

  function attachAssetSetToInput(assetSet) {
    const assets = assetSet?.assets || [];
    if (!assets.length) {
      DesktopResults.showTransientMessage('候选集里还没有可用图片。');
      return;
    }
    mergeAssetsFromSet(assetSet);
    window.DesktopCanvas?.attachHistoryImagesToInput?.(assets.map(makeDragPayload))
      ?.catch?.(error => DesktopResults.showError(error));
  }

  async function deleteAssetSetById(setId) {
    const assetSet = gallerySets.find(item => item.id === setId);
    if (!assetSet) return;
    if (!window.confirm(`删除候选集「${assetSet.name || '未命名候选集'}」？图片文件不会被删除。`)) return;
    await DesktopApi.deleteAssetSet(setId);
    gallerySets = gallerySets.filter(item => item.id !== setId);
    if (activeGallerySet?.id === setId) {
      activeGallerySet = null;
      galleryView = 'sets';
    }
    renderGallery();
    DesktopResults.showTransientMessage('候选集已删除。');
  }

  function bindGallerySetEvents() {
    bindGalleryCardEvents();
    els.deskGalleryGrid?.querySelectorAll('.desk-gallery-set').forEach(card => {
      if (card.dataset.gallerySetBound === '1') return;
      card.dataset.gallerySetBound = '1';
      card.addEventListener('dragstart', event => {
        const assetSet = gallerySets.find(item => item.id === card.dataset.assetSetId);
        const assets = assetSet?.assets || [];
        if (!assets.length) {
          event.preventDefault();
          return;
        }
        event.dataTransfer.effectAllowed = 'copy';
        event.dataTransfer.setData('application/x-desktop-gallery-images', JSON.stringify(assets.map(makeDragPayload)));
        event.dataTransfer.setData('application/x-desktop-history-image', JSON.stringify(makeDragPayload(assets[0])));
        try {
          event.dataTransfer.setData('text/uri-list', new URL(assets[0].imageUrl, window.location.origin).href);
        } catch (e) {}
        card.classList.add('is-dragging');
      });
      card.addEventListener('dragend', () => {
        card.classList.remove('is-dragging');
      });
      card.addEventListener('click', event => {
        if (event.target.closest('button')) return;
        const assetSet = gallerySets.find(item => item.id === card.dataset.assetSetId);
        openAssetSetDetail(assetSet);
      });
    });
    els.deskGalleryGrid?.querySelectorAll('[data-asset-set-detail]').forEach(button => {
      button.addEventListener('click', () => openAssetSetDetail(gallerySets.find(item => item.id === button.dataset.assetSetDetail)));
    });
    els.deskGalleryGrid?.querySelectorAll('[data-asset-set-open]').forEach(button => {
      button.addEventListener('click', () => openAssetSet(gallerySets.find(item => item.id === button.dataset.assetSetOpen)));
    });
    els.deskGalleryGrid?.querySelectorAll('[data-asset-set-compare]').forEach(button => {
      button.addEventListener('click', () => compareAssetSet(gallerySets.find(item => item.id === button.dataset.assetSetCompare)));
    });
    els.deskGalleryGrid?.querySelectorAll('[data-asset-set-input]').forEach(button => {
      button.addEventListener('click', () => attachAssetSetToInput(gallerySets.find(item => item.id === button.dataset.assetSetInput)));
    });
    els.deskGalleryGrid?.querySelectorAll('[data-asset-set-layout]').forEach(button => {
      button.addEventListener('click', () => attachAssetSetToLayout(gallerySets.find(item => item.id === button.dataset.assetSetLayout)));
    });
    els.deskGalleryGrid?.querySelectorAll('[data-asset-set-delete]').forEach(button => {
      button.addEventListener('click', () => {
        deleteAssetSetById(button.dataset.assetSetDelete).catch(error => DesktopResults.showError(error));
      });
    });
  }

  function renderGallerySets() {
    const grid = els.deskGalleryGrid;
    if (!grid) return;
    const sets = getVisibleAssetSets();
    if (!sets.length) {
      grid.innerHTML = '<div class="desk-gallery-empty">还没有候选集。选中图片后点击“存候选集”。</div>';
      return;
    }
    grid.innerHTML = sets.map(renderGallerySetCard).join('');
    bindGallerySetEvents();
  }

  function renderSetDetailAsset(asset, index, total) {
    const selected = selectedGalleryIds.has(asset.id);
    return `
      <article class="desk-gallery-set-asset${selected ? ' is-selected' : ''}" data-set-asset-id="${escapeHtml(asset.id)}">
        <button type="button" class="desk-gallery-set-asset__image" data-set-preview="${escapeHtml(asset.id)}" title="查看原图" aria-label="查看原图">
          <img src="${escapeHtml(mediaUrl(asset.thumbUrl || asset.imageUrl))}" data-fallback="${escapeHtml(mediaUrl(asset.imageUrl))}" alt="" loading="lazy" decoding="async">
          <span>${index + 1}</span>
        </button>
        <div class="desk-gallery-set-asset__meta">
          <strong>${escapeHtml(asset.title || '图片资产')}</strong>
          <span>${escapeHtml(asset.providerLabel || providerLabel(asset))} · ${escapeHtml(formatTime(asset.createdAt))}</span>
        </div>
        <div class="desk-gallery-set-asset__actions">
          <button type="button" data-set-select="${escapeHtml(asset.id)}" aria-pressed="${selected ? 'true' : 'false'}" title="${selected ? '移出选择篮' : '加入选择篮'}" aria-label="${selected ? '移出选择篮' : '加入选择篮'}">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4 10-10"></path></svg>
          </button>
          <button type="button" data-set-move-left="${escapeHtml(asset.id)}" ${index <= 0 ? 'disabled' : ''} title="前移" aria-label="前移">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 18-6-6 6-6"></path></svg>
          </button>
          <button type="button" data-set-move-right="${escapeHtml(asset.id)}" ${index >= total - 1 ? 'disabled' : ''} title="后移" aria-label="后移">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6"></path></svg>
          </button>
          <button type="button" data-set-remove="${escapeHtml(asset.id)}" title="移出候选集" aria-label="移出候选集">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M10 11v6"></path><path d="M14 11v6"></path><path d="m6 7 1 14h10l1-14"></path><path d="M9 7V4h6v3"></path></svg>
          </button>
        </div>
      </article>
    `;
  }

  function renderAssetSetTags(assetSet) {
    const tags = parseTags(assetSet?.tags);
    if (!tags.length) return '<span>无标签</span>';
    return tags.slice(0, 6).map(tag => `<span>#${escapeHtml(tag)}</span>`).join('');
  }

  function renderAssetSetDetail() {
    const grid = els.deskGalleryGrid;
    if (!grid) return;
    if (!activeGallerySet) {
      galleryView = 'sets';
      renderGallerySets();
      return;
    }
    const assetSet = normalizeAssetSet(activeGallerySet);
    const assets = activeSetAssets(assetSet);
    activeGallerySet = { ...assetSet, assets, count: assets.length };
    const canCompare = assets.length >= 2;
    grid.innerHTML = `
      <section class="desk-gallery-set-detail" data-active-set-id="${escapeHtml(assetSet.id)}">
        <header class="desk-gallery-set-detail__head">
          <button type="button" class="desk-gallery-set-detail__back" data-set-detail-back title="返回候选集" aria-label="返回候选集">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 18-6-6 6-6"></path></svg>
          </button>
          <div class="desk-gallery-set-detail__title">
            <strong>${escapeHtml(assetSet.name || '未命名候选集')}</strong>
            <span>${assets.length} 张 · ${escapeHtml(formatTime(assetSet.updatedAt || assetSet.createdAt))}</span>
            <div class="desk-gallery-set-detail__tags">${renderAssetSetTags(assetSet)}</div>
          </div>
          <div class="desk-gallery-set-detail__actions">
            <button type="button" data-set-edit-meta>编辑</button>
            <button type="button" data-set-select-all ${assets.length ? '' : 'disabled'}>选择全部</button>
            <button type="button" data-set-add-selected ${getSelectedAssets().length ? '' : 'disabled'}>追加选中</button>
            <button type="button" data-set-detail-input ${assets.length ? '' : 'disabled'}>模型</button>
            <button type="button" data-set-detail-apply ${assets.some(hasAssetModelConfig) ? '' : 'disabled'}>套用</button>
            <button type="button" data-set-detail-compare ${canCompare ? '' : 'disabled'}>对比</button>
            <button type="button" data-set-detail-layout ${assets.length ? '' : 'disabled'}>排版</button>
          </div>
        </header>
        <div class="desk-gallery-set-detail__grid">
          ${assets.length ? assets.map((asset, index) => renderSetDetailAsset(asset, index, assets.length)).join('') : '<div class="desk-gallery-empty">这个候选集还没有图片</div>'}
        </div>
      </section>
    `;
    bindAssetSetDetailEvents();
  }

  function closeAssetSetDetail() {
    activeGallerySet = null;
    galleryView = 'sets';
    resetGalleryRenderLimit();
    renderGallery();
  }

  async function editActiveAssetSetMeta() {
    if (!activeGallerySet) return;
    const currentTags = parseTags(activeGallerySet.tags).map(tag => `#${tag}`).join(' ');
    const raw = window.prompt('候选集名称（可在名称后添加 #标签）', `${activeGallerySet.name || '未命名候选集'}${currentTags ? ` ${currentTags}` : ''}`);
    if (raw === null) return;
    const { name, tags } = parseSetNameAndTags(raw, activeSetAssets(activeGallerySet));
    await persistAssetSet(activeGallerySet, { name, tags }, '候选集信息已更新。');
  }

  async function addSelectedToActiveSet() {
    if (!activeGallerySet) return;
    const selected = getSelectedAssets();
    const current = activeSetAssets(activeGallerySet);
    const currentIds = new Set(current.map(asset => asset.id));
    const additions = selected.filter(asset => !currentIds.has(asset.id));
    if (!additions.length) {
      DesktopResults.showTransientMessage(selected.length ? '选中的图片已经在候选集里。' : '选择篮里还没有图片。');
      return;
    }
    await persistAssetSet(activeGallerySet, { assets: [...current, ...additions] }, `已追加 ${additions.length} 张图片。`);
  }

  async function removeAssetFromActiveSet(assetId) {
    if (!activeGallerySet || !assetId) return;
    const current = activeSetAssets(activeGallerySet);
    if (current.length <= 1) {
      DesktopResults.showTransientMessage('候选集至少保留 1 张图片；需要清空时可直接删除候选集。');
      return;
    }
    const nextAssets = current.filter(asset => asset.id !== assetId);
    await persistAssetSet(activeGallerySet, { assets: nextAssets }, '图片已移出候选集。');
  }

  async function moveAssetInActiveSet(assetId, direction) {
    if (!activeGallerySet || !assetId) return;
    const current = activeSetAssets(activeGallerySet);
    const index = current.findIndex(asset => asset.id === assetId);
    const nextIndex = index + direction;
    if (index < 0 || nextIndex < 0 || nextIndex >= current.length) return;
    const nextAssets = current.slice();
    [nextAssets[index], nextAssets[nextIndex]] = [nextAssets[nextIndex], nextAssets[index]];
    await persistAssetSet(activeGallerySet, { assets: nextAssets }, '候选集顺序已更新。');
  }

  function toggleSetAssetSelection(assetId) {
    toggleAssetSelection(assetId);
    if (galleryView === 'setDetail') renderAssetSetDetail();
  }

  function bindAssetSetDetailEvents() {
    bindGalleryCardEvents();
    els.deskGalleryGrid?.querySelector('[data-set-detail-back]')?.addEventListener('click', closeAssetSetDetail);
    els.deskGalleryGrid?.querySelector('[data-set-edit-meta]')?.addEventListener('click', () => {
      editActiveAssetSetMeta().catch(error => DesktopResults.showError(error));
    });
    els.deskGalleryGrid?.querySelector('[data-set-select-all]')?.addEventListener('click', () => {
      if (activeGallerySet) openAssetSet(activeGallerySet, false);
    });
    els.deskGalleryGrid?.querySelector('[data-set-add-selected]')?.addEventListener('click', () => {
      addSelectedToActiveSet().catch(error => DesktopResults.showError(error));
    });
    els.deskGalleryGrid?.querySelector('[data-set-detail-compare]')?.addEventListener('click', () => {
      if (activeGallerySet) compareAssetSet(activeGallerySet);
    });
    els.deskGalleryGrid?.querySelector('[data-set-detail-input]')?.addEventListener('click', () => {
      if (activeGallerySet) attachAssetSetToInput(activeGallerySet);
    });
    els.deskGalleryGrid?.querySelector('[data-set-detail-apply]')?.addEventListener('click', () => {
      applyAssetToInput(activeSetAssets(activeGallerySet).find(hasAssetModelConfig));
    });
    els.deskGalleryGrid?.querySelector('[data-set-detail-layout]')?.addEventListener('click', () => {
      if (activeGallerySet) attachAssetSetToLayout(activeGallerySet);
    });
    els.deskGalleryGrid?.querySelectorAll('[data-set-preview]').forEach(button => {
      button.addEventListener('click', () => {
        const asset = activeSetAssets().find(item => item.id === button.dataset.setPreview);
        if (asset) openPreview(asset);
      });
    });
    els.deskGalleryGrid?.querySelectorAll('[data-set-select]').forEach(button => {
      button.addEventListener('click', () => toggleSetAssetSelection(button.dataset.setSelect || ''));
    });
    els.deskGalleryGrid?.querySelectorAll('[data-set-move-left]').forEach(button => {
      button.addEventListener('click', () => {
        moveAssetInActiveSet(button.dataset.setMoveLeft || '', -1).catch(error => DesktopResults.showError(error));
      });
    });
    els.deskGalleryGrid?.querySelectorAll('[data-set-move-right]').forEach(button => {
      button.addEventListener('click', () => {
        moveAssetInActiveSet(button.dataset.setMoveRight || '', 1).catch(error => DesktopResults.showError(error));
      });
    });
    els.deskGalleryGrid?.querySelectorAll('[data-set-remove]').forEach(button => {
      button.addEventListener('click', () => {
        removeAssetFromActiveSet(button.dataset.setRemove || '').catch(error => DesktopResults.showError(error));
      });
    });
  }

  function scheduleGalleryRender(options = {}) {
    if (options.selection) gallerySelectionRenderPending = true;
    if (galleryRenderFrame) return;
    galleryRenderFrame = window.requestAnimationFrame(() => {
      galleryRenderFrame = 0;
      renderGallery();
      if (gallerySelectionRenderPending) {
        gallerySelectionRenderPending = false;
        renderGallerySelection();
      }
    });
  }

  function renderGallery() {
    if (!els.deskGalleryGrid) return;
    clearGalleryHoverState(els.deskGalleryGrid);
    clearGalleryHoverState(els.deskGalleryGrid.querySelector('[data-prompt-source-scroll]'));
    document.querySelectorAll('[data-gallery-view]').forEach(button => {
      const view = button.dataset.galleryView;
      button.classList.toggle('is-active', view === galleryView || (galleryView === 'setDetail' && view === 'sets'));
    });
    if (els.deskGalleryFilterSelect) els.deskGalleryFilterSelect.value = galleryFilter;
    if (els.deskGalleryTagInput && els.deskGalleryTagInput.value !== galleryTag) els.deskGalleryTagInput.value = galleryTag;
    renderGalleryStats();
    if (!['images', 'sets', 'setDetail', 'sources', 'files'].includes(galleryView)) galleryView = 'images';
    els.deskGalleryGrid.classList.toggle('is-prompt-sources', galleryView === 'sources');
    els.deskGalleryGrid.classList.toggle('is-file-assets', galleryView === 'files');
    if (galleryView === 'setDetail') renderAssetSetDetail();
    else if (galleryView === 'sets') renderGallerySets();
    else if (galleryView === 'files') renderGalleryFiles();
    else if (galleryView === 'sources') renderPromptSources();
    else renderGalleryImages();
  }

  function renderGallerySelection() {
    if (galleryView === 'files') {
      const count = getVisibleEditableFiles().length;
      if (els.deskGallerySelectedCount) els.deskGallerySelectedCount.textContent = `${count} 件`;
      if (els.deskGallerySelectedList) {
        els.deskGallerySelectedList.innerHTML = '<div class="desk-gallery-empty">文件页可直接打开、发送或删除 PPT/PSD 目录。</div>';
      }
      [
        els.deskGalleryCompareBtn,
        els.deskGalleryCanvasBtn,
        els.deskGallerySaveSetBtn,
        els.deskGalleryTagBtn,
        els.deskGalleryHideBtn,
        els.deskGalleryDeleteBtn,
        els.deskGalleryUndoDeleteBtn,
        els.deskGalleryClearBtn
      ].forEach(button => {
        if (button) button.disabled = true;
      });
      return;
    }
    const selected = getSelectedAssets();
    const hasRemote = selected.some(asset => asset.sourceKind === 'remote_source');
    if (els.deskGallerySelectedCount) els.deskGallerySelectedCount.textContent = `${selected.length} 张`;
    if (els.deskGallerySelectedList) {
      if (!selected.length) {
        els.deskGallerySelectedList.innerHTML = '<div class="desk-gallery-empty">选择图片后可对比、发送到画布或整理候选集。</div>';
      } else {
        els.deskGallerySelectedList.innerHTML = selected.map(asset => `
          <button type="button" class="desk-gallery-selected-item" data-remove-asset="${escapeHtml(asset.id)}" title="移出选择篮">
            <img src="${escapeHtml(mediaUrl(asset.thumbUrl || asset.imageUrl))}" data-fallback="${escapeHtml(mediaUrl(asset.imageUrl))}" alt="" loading="lazy" decoding="async">
            <span>${escapeHtml(asset.title)}</span>
          </button>
        `).join('');
        els.deskGallerySelectedList.querySelectorAll('[data-remove-asset]').forEach(button => {
          button.addEventListener('click', () => toggleAssetSelection(button.dataset.removeAsset, false));
        });
        els.deskGallerySelectedList.querySelectorAll('img[data-fallback]').forEach(img => {
          img.addEventListener('error', () => {
            const fallback = img.dataset.fallback || '';
            if (fallback && img.src !== fallback) {
              img.removeAttribute('data-fallback');
              img.src = fallback;
            }
          }, { once: true });
        });
      }
    }
    if (els.deskGalleryCompareBtn) els.deskGalleryCompareBtn.disabled = selected.length !== 2;
    if (els.deskGalleryCanvasBtn) els.deskGalleryCanvasBtn.disabled = !selected.length;
    if (els.deskGallerySaveSetBtn) els.deskGallerySaveSetBtn.disabled = !selected.length || hasRemote;
    if (els.deskGalleryTagBtn) els.deskGalleryTagBtn.disabled = !selected.length || hasRemote;
    if (els.deskGalleryHideBtn) {
      els.deskGalleryHideBtn.disabled = !selected.length || hasRemote;
      els.deskGalleryHideBtn.textContent = selected.length && selected.every(asset => asset.hidden) ? '取消隐藏' : '隐藏';
    }
    if (els.deskGalleryDeleteBtn) els.deskGalleryDeleteBtn.disabled = !selected.length || hasRemote;
    if (els.deskGalleryUndoDeleteBtn) els.deskGalleryUndoDeleteBtn.disabled = !lastDeleteBatchIds.length;
    if (els.deskGalleryClearBtn) els.deskGalleryClearBtn.disabled = !selected.length;
  }

  function bindGalleryCardEvents() {
    // One delegated hover controller on the outer grid covers both image cards
    // and remote-source cards (descendants), so no per-mode/per-container binding.
    bindGalleryHoverState(els.deskGalleryGrid);
    const grid = els.deskGalleryGrid;
    if (!grid || grid.dataset.galleryDelegatesBound === '1') return;
    grid.dataset.galleryDelegatesBound = '1';
    grid.addEventListener('error', event => {
      const img = event.target?.closest?.('img[data-fallback]');
      if (!img || !grid.contains(img)) return;
      const fallback = img.dataset.fallback || '';
      if (fallback && img.src !== fallback) {
        img.removeAttribute('data-fallback');
        img.src = fallback;
      }
    }, true);
    grid.addEventListener('click', event => {
      const selectButton = event.target?.closest?.('[data-gallery-select]');
      if (selectButton && grid.contains(selectButton)) {
        event.preventDefault();
        event.stopPropagation();
        toggleAssetSelection(selectButton.dataset.gallerySelect || '');
        return;
      }
      const stepButton = event.target?.closest?.('[data-remote-image-step]');
      if (stepButton && grid.contains(stepButton)) {
        event.preventDefault();
        event.stopPropagation();
        const asset = findAssetById(stepButton.dataset.assetId || '', { raw: true });
        if (!asset) return;
        setRemoteImageIndex(asset.id, getRemoteImageIndex(asset) + Number(stepButton.dataset.remoteImageStep || 0));
        return;
      }
      const favoriteButton = event.target?.closest?.('[data-gallery-favorite]');
      if (favoriteButton && grid.contains(favoriteButton)) {
        event.preventDefault();
        event.stopPropagation();
        const asset = galleryAssets.find(item => item.id === favoriteButton.dataset.galleryFavorite);
        if (!asset) return;
        focusGalleryAsset(asset.id);
        toggleAssetFavorite(asset, { render: galleryFilter === 'favorite' })
          .then(() => restoreGalleryCardFocus(asset.id))
          .catch(error => DesktopResults.showError(error));
        return;
      }
      if (event.target?.closest?.('button')) return;
      const card = event.target?.closest?.('.desk-gallery-card');
      if (!card || !grid.contains(card)) return;
      const asset = findAssetById(card.dataset.assetId);
      openPreview(asset);
    });
    grid.addEventListener('dragstart', event => {
      const card = event.target?.closest?.('.desk-gallery-card');
      if (!card || !grid.contains(card)) return;
      const asset = findAssetById(card.dataset.assetId);
      if (!asset || !asset.imageUrl) {
        event.preventDefault();
        return;
      }
      if (!selectedGalleryIds.has(asset.id)) {
        selectedGalleryIds.clear();
        selectedGalleryIds.add(asset.id);
        renderGallerySelection();
      }
      const selected = getSelectedAssets();
      event.dataTransfer.effectAllowed = 'copy';
      event.dataTransfer.setData('application/x-desktop-history-image', JSON.stringify(makeDragPayload(asset)));
      event.dataTransfer.setData('application/x-desktop-gallery-images', JSON.stringify(selected.map(makeDragPayload)));
      try {
        event.dataTransfer.setData('text/uri-list', new URL(asset.imageUrl, window.location.origin).href);
      } catch (e) {}
      card.classList.add('is-dragging');
    });
    grid.addEventListener('dragend', event => {
      const card = event.target?.closest?.('.desk-gallery-card');
      if (card && grid.contains(card)) card.classList.remove('is-dragging');
    });
  }

  function selectHistoryItem(item) {
    DesktopState.state.selectedTaskId = item.task_id || '';
    DesktopState.state.selectedHistoryId = item.task_id || '';
    DesktopState.state.prompt = item.prompt || DesktopState.state.prompt;
    DesktopState.state.provider = providerGroup(item);
    if (item.params && typeof item.params === 'object') {
      DesktopState.state.params = {
        ...DesktopState.state.params,
        ratio: item.params.ratio || DesktopState.state.params.ratio,
        resolution: item.params.resolution || item.params.quality || DesktopState.state.params.resolution,
        quality: item.params.quality || DesktopState.state.params.quality,
        imageCount: item.params.image_count || DesktopState.state.params.imageCount,
        moderation: item.params.moderation || DesktopState.state.params.moderation,
        promptMode: item.params.prompt_mode || DesktopState.state.params.promptMode,
        gptMainModel: item.params.main_model || DesktopState.state.params.gptMainModel,
        reasoningEffort: item.params.reasoning_effort || DesktopState.state.params.reasoningEffort
      };
    }
    DesktopCanvas.syncFormFromState();
    DesktopResults.applyTask({
      ...item,
      result_files: item.result_files || item.output_files || [],
      image_paths: item.image_paths || [],
      result_file: item.result_file || item.output_file,
      progress_text: item.progress_text || '已从历史记录载入'
    });
    renderHistory(DesktopState.state.history);
  }

  function isRetryableHistoryItem(item) {
    if (!item || item.is_old || !item.task_id) return false;
    if (!DesktopState.isFailure(item.status)) return false;
    return !['gpt-edit', 'google-edit', 'comfy'].includes(String(item.type || ''));
  }

  function getBatchHistoryLabel(item) {
    const params = item?.params && typeof item.params === 'object' ? item.params : {};
    if (!params.batch_id) return '';
    const index = Number(params.batch_index || 0);
    const total = Number(params.batch_total || 0);
    return index && total ? `批量 ${index}/${total}` : '批量';
  }

  async function retryHistoryItem(taskId, button) {
    if (!taskId) throw new Error('缺少 task_id');
    if (button) {
      button.disabled = true;
      button.classList.add('is-loading');
      button.textContent = '提交中';
    }
    try {
      const task = await DesktopApi.retryTask(taskId);
      DesktopResults.trackRetriedTask?.(task);
      DesktopResults.showTransientMessage('重跑任务已提交。', 'success');
      await loadHistory().catch(() => {});
      return task;
    } finally {
      if (button && button.isConnected) {
        button.disabled = false;
        button.classList.remove('is-loading');
        button.textContent = '重跑';
      }
    }
  }

  async function continueEditHistoryItem(taskId) {
    const item = DesktopState.state.history.find(entry => entry.task_id === taskId);
    if (!item) throw new Error('历史记录不存在');
    const firstAsset = flattenHistoryItems([item])[0] || null;
    const payload = firstAsset || {
      taskId: item.task_id || '',
      imageUrl: DesktopApi.getImagePath(item),
      title: getPromptTitle(item),
      prompt: item.prompt || '',
      provider: providerGroup(item),
      source: 'history'
    };
    await window.DesktopCanvas?.continueEditFromHistoryItem?.(payload);
  }

  async function loadHistory(limit = 60) {
    const data = await DesktopApi.getHistory(limit, 0);
    const items = Array.isArray(data.history) ? data.history : [];
    DesktopState.state.history = items;
    renderHistory(items);
    return items;
  }

  async function loadGalleryAssets() {
    if (!DesktopApi.getAssets) {
      galleryAssetsFromIndex = false;
      return galleryAssets;
    }
    const data = await DesktopApi.getAssets({
      limit: GALLERY_ASSET_LOAD_LIMIT,
      offset: 0,
      query: galleryQuery,
      filter: galleryFilter,
      tag: galleryTag,
      includeHidden: galleryFilter === 'hidden'
    });
    galleryAssets = (Array.isArray(data.assets) ? data.assets : []).map(normalizeGalleryAsset);
    galleryAssetTotal = Number(data.total || galleryAssets.length);
    galleryAssetStats = data.stats || galleryAssetStats || {};
    galleryAssetsFromIndex = true;
    selectedGalleryIds.forEach(id => {
      if (!galleryAssets.some(asset => asset.id === id)) selectedGalleryIds.delete(id);
    });
    scheduleGalleryRender({ selection: true });
    return galleryAssets;
  }

  async function loadGallerySets() {
    if (!DesktopApi.listAssetSets) return gallerySets;
    const data = await DesktopApi.listAssetSets({
      limit: 120,
      offset: 0,
      query: galleryQuery,
      tag: galleryTag
    });
    gallerySets = (Array.isArray(data.sets) ? data.sets : []).map(normalizeAssetSet);
    if (activeGallerySet) {
      activeGallerySet = gallerySets.find(item => item.id === activeGallerySet.id) || activeGallerySet;
    }
    if (galleryView === 'sets' || galleryView === 'setDetail') scheduleGalleryRender();
    return gallerySets;
  }

  async function loadGalleryFiles() {
    if (!DesktopApi.listEditableFiles) return galleryFiles;
    const data = await DesktopApi.listEditableFiles({
      limit: 500,
      query: galleryQuery,
      kind: ['ppt', 'psd'].includes(galleryFilter) ? galleryFilter : '',
      includeLocal: true
    });
    galleryFiles = (Array.isArray(data.files) ? data.files : []).map(normalizeEditableFile);
    galleryFileStats = data.stats || {};
    if (galleryView === 'files') scheduleGalleryRender({ selection: true });
    return galleryFiles;
  }

  async function loadPromptSources() {
    if (!DesktopApi.getPromptSources) return promptSources;
    const data = await DesktopApi.getPromptSources();
    promptSources = Array.isArray(data.sources) ? data.sources : [];
    const latestRun = pickLatestPromptSourceRun(promptSources, data.latestRun);
    if (latestRun?.status === 'running') {
      promptSourceSyncRun = latestRun;
      promptSourceSyncRunId = latestRun.runId || promptSourceSyncRunId;
      if (promptSourceSyncRunId && !promptSourceSyncTimer) {
        promptSourceSyncTimer = window.setTimeout(() => {
          pollPromptSourceRun(promptSourceSyncRunId).catch(error => DesktopResults.showError(error));
        }, 600);
      }
    } else if (latestRun && promptSourceSyncRun?.status !== 'running') {
      promptSourceSyncRun = latestRun;
      lastPromptSourceSyncRun = latestRun;
      promptSourceSyncRunId = '';
    }
    if (galleryView === 'sources') scheduleGalleryRender();
    return promptSources;
  }

  async function loadPromptSourceItems() {
    if (!DesktopApi.getPromptSourceItems) return promptSourceItems;
    const source = promptSourceFilter === 'all' ? '' : promptSourceFilter;
    const pageSize = 1000;
    const baseOptions = {
      source,
      query: galleryQuery,
      tag: galleryTag,
      style: promptSourceTaxonomyFilters.style,
      subject: promptSourceTaxonomyFilters.subject,
      type: promptSourceTaxonomyFilters.type
    };
    const firstPage = await DesktopApi.getPromptSourceItems({
      ...baseOptions,
      limit: pageSize,
      offset: 0
    });
    const total = Number(firstPage.total || 0);
    const pages = [firstPage];
    for (let offset = pageSize; total && offset < total; offset += pageSize) {
      pages.push(await DesktopApi.getPromptSourceItems({
        ...baseOptions,
        limit: pageSize,
        offset
      }));
    }
    promptSourceItems = pages
      .flatMap(page => Array.isArray(page.items) ? page.items : [])
      .map(normalizePromptSourceItem);
    promptSourceTaxonomyFacets = normalizeTaxonomyFacets(firstPage.taxonomyFacets || firstPage.taxonomy_facets);
    promptSourceTotal = total || promptSourceItems.length;
    selectedGalleryIds.forEach(id => {
      if (id.startsWith('remote_') && !promptSourceItems.some(asset => asset.id === id)) selectedGalleryIds.delete(id);
    });
    if (galleryView === 'sources') scheduleGalleryRender({ selection: true });
    return promptSourceItems;
  }

  async function refreshPromptSources() {
    resetGalleryRenderLimit();
    await loadPromptSources();
    await loadPromptSourceItems();
  }

  async function pollPromptSourceRun(runId) {
    if (!runId || !DesktopApi.getPromptSourceRun) return;
    const data = await DesktopApi.getPromptSourceRun(runId);
    const run = normalizePromptSourceRun(data.run || {});
    if (!run) return;
    promptSourceSyncRun = run;
    if (galleryView === 'sources') {
      renderGallery();
      renderGallerySelection();
    } else {
      renderGalleryStats();
    }
    if (run.status === 'running') {
      galleryMessage(`远程源同步中：${Math.max(1, Math.round(run.progressPercent || 1))}%`);
      if (promptSourceSyncTimer) window.clearTimeout(promptSourceSyncTimer);
      promptSourceSyncTimer = window.setTimeout(() => {
        pollPromptSourceRun(runId).catch(error => DesktopResults.showError(error));
      }, 1800);
      return;
    }
    promptSourceSyncRunId = '';
    if (promptSourceSyncTimer) {
      window.clearTimeout(promptSourceSyncTimer);
      promptSourceSyncTimer = null;
    }
    promptSourceSyncRun = run;
    lastPromptSourceSyncRun = run;
    await refreshPromptSources();
    const itemCount = Number(run.itemCount || 0);
    const imageCount = Number(run.imageCount || 0);
    const finishedAt = formatPreviewTime(run.finishedAt);
    galleryMessage(run.status === 'succeeded'
      ? `远程源同步完成：${finishedAt}，${itemCount} 条提示词，${imageCount} 张图片。`
      : (run.status === 'canceled'
        ? `远程源同步已停止：${finishedAt}。`
        : `远程源同步结束：${finishedAt}，${run.message || '有部分失败'}`));
  }

  async function stopPromptSourceSync(runId = '', button = null) {
    const cleanRunId = String(runId || promptSourceSyncRunId || '').trim();
    if (!cleanRunId || !DesktopApi.stopPromptSourceSync) return;
    const originalText = button?.textContent || '';
    try {
      if (button) {
        button.disabled = true;
        button.textContent = '停止中';
      }
      await DesktopApi.stopPromptSourceSync(cleanRunId);
      promptSourceSyncRun = normalizePromptSourceRun({
        ...(promptSourceSyncRun || {}),
        run_id: cleanRunId,
        status: 'running',
        phase: '停止中',
        message: '正在停止远程源同步'
      });
      galleryMessage('已请求停止远程源同步。');
      if (galleryView === 'sources') renderGallery();
      if (!promptSourceSyncTimer) {
        promptSourceSyncTimer = window.setTimeout(() => {
          pollPromptSourceRun(cleanRunId).catch(error => DesktopResults.showError(error));
        }, 600);
      }
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = originalText;
      }
    }
  }

  async function syncPromptSources(source = 'all', button = null) {
    if (!DesktopApi.syncPromptSource) return;
    const originalText = button?.textContent || '';
    try {
      if (button) {
        button.disabled = true;
        button.textContent = source === 'all' ? '同步中' : '拉取中';
      }
      promptSourceSyncRun = normalizePromptSourceRun({
        source_slug: source,
        status: 'running',
        phase: '准备同步',
        message: '同步任务已创建，正在连接远程源',
        started_at: Math.floor(Date.now() / 1000),
        total_sources: source === 'all' ? promptSources.length : 1,
        progress_percent: 1
      });
      if (galleryView === 'sources') renderGallery();
      const result = await DesktopApi.syncPromptSource(source);
      promptSourceSyncRunId = result.run_id || '';
      promptSourceSyncRun = normalizePromptSourceRun({
        ...promptSourceSyncRun,
        run_id: promptSourceSyncRunId,
        message: '同步任务已开始，正在计算进度'
      });
      if (galleryView === 'sources') renderGallery();
      galleryMessage('远程源同步已开始，正在计算进度。');
      if (promptSourceSyncRunId) await pollPromptSourceRun(promptSourceSyncRunId);
    } catch (error) {
      promptSourceSyncRunId = '';
      promptSourceSyncRun = null;
      if (galleryView === 'sources') renderGallery();
      throw error;
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = originalText;
      }
    }
  }

  async function saveSelectedAsSet() {
    const selected = getSelectedAssets();
    if (!selected.length) return;
    const defaultName = selected.length === 1
      ? `候选集 · ${selected[0].title || '1 张'}`
      : `候选集 · ${selected.length} 张`;
    const raw = window.prompt('候选集名称（可在名称后添加 #标签）', defaultName);
    if (raw === null) return;
    const { name, tags } = parseSetNameAndTags(raw, selected);
    const result = await DesktopApi.saveAssetSet({
      name,
      tags,
      asset_ids: selected.map(asset => asset.id),
      assets: selected.map(assetSnapshotForSet).filter(Boolean)
    });
    const assetSet = normalizeAssetSet(result.set || result);
    if (assetSet.id) {
      gallerySets = [assetSet, ...gallerySets.filter(item => item.id !== assetSet.id)];
      mergeAssetsFromSet(assetSet);
    }
    galleryView = 'sets';
    resetGalleryRenderLimit();
    renderGallery();
    renderGallerySelection();
    DesktopResults.showTransientMessage(`已保存候选集：${assetSet.name || name}`);
  }

  function refreshGalleryAssets() {
    resetGalleryRenderLimit();
    if (galleryView === 'images') {
      loadGalleryAssets().catch(error => DesktopResults.showError(error));
    } else if (galleryView === 'sets' || galleryView === 'setDetail') {
      loadGallerySets().catch(error => DesktopResults.showError(error));
    } else if (galleryView === 'files') {
      loadGalleryFiles().catch(error => DesktopResults.showError(error));
    } else if (galleryView === 'sources') {
      refreshPromptSources().catch(error => DesktopResults.showError(error));
    } else {
      renderGallery();
    }
  }

  async function openGallery() {
    els.deskGalleryPanel?.classList.add('is-open');
    els.deskGalleryPanel?.setAttribute('aria-hidden', 'false');
    resetGalleryRenderLimit();
    renderGallery();
    renderGallerySelection();
    const sourceLoad = galleryView === 'sources' ? refreshPromptSources() : loadPromptSources();
    const results = await Promise.allSettled([
      loadHistory(80),
      loadGalleryAssets(),
      loadGallerySets(),
      loadGalleryFiles(),
      sourceLoad
    ]);
    results
      .filter(result => result.status === 'rejected')
      .forEach(result => DesktopResults.showError(result.reason));
  }

  function closeGallery() {
    els.deskGalleryPanel?.classList.remove('is-open');
    els.deskGalleryPanel?.setAttribute('aria-hidden', 'true');
  }

  function normalizeCompareValue(value) {
    if (Array.isArray(value)) return value.filter(Boolean).join(' / ');
    return String(value || '').trim();
  }

  function basenameFromAssetPath(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    const clean = raw.split(/[?#]/)[0];
    const name = clean.split('/').filter(Boolean).pop() || clean;
    try {
      return decodeURIComponent(name);
    } catch (error) {
      return name;
    }
  }

  function compareAssetName(asset, fallback = '图片') {
    return basenameFromAssetPath(asset?.file)
      || basenameFromAssetPath(asset?.imagePath)
      || basenameFromAssetPath(asset?.imageUrl)
      || String(asset?.name || asset?.title || fallback).trim()
      || fallback;
  }

  function getAssetParam(asset, keys) {
    const params = asset?.params && typeof asset.params === 'object' ? asset.params : {};
    for (const key of keys) {
      const value = params[key] ?? asset?.[key];
      if (value !== undefined && value !== null && String(value).trim()) return value;
    }
    return '';
  }

  function getCompareRows(left, right) {
    const fields = [
      ['模型', getAssetParam(left, ['model', 'modelAlias']), getAssetParam(right, ['model', 'modelAlias'])],
      ['来源', left?.providerLabel || providerLabel(left), right?.providerLabel || providerLabel(right)],
      ['比例', getAssetParam(left, ['ratio', 'aspect_ratio', 'aspectRatio']), getAssetParam(right, ['ratio', 'aspect_ratio', 'aspectRatio'])],
      ['分辨率', galleryAssetResolutionLabel(left, left?.params || {}), galleryAssetResolutionLabel(right, right?.params || {})],
      ['质量', getAssetParam(left, ['quality']), getAssetParam(right, ['quality'])],
      ['标签', parseTags(left?.tags), parseTags(right?.tags)],
      ['文件', left?.file || '', right?.file || ''],
      ['时间', formatTime(left?.createdAt), formatTime(right?.createdAt)]
    ];
    return fields
      .map(([label, leftValue, rightValue]) => {
        const a = normalizeCompareValue(leftValue) || '无';
        const b = normalizeCompareValue(rightValue) || '无';
        return { label, leftValue: a, rightValue: b, different: a !== b };
      })
      .filter(row => row.leftValue !== '无' || row.rightValue !== '无');
  }

  function renderCompareInfo(left, right) {
    if (els.deskCompareMetaDiff) {
      const rows = getCompareRows(left, right);
      els.deskCompareMetaDiff.innerHTML = rows.map(row => `
        <div class="desk-compare__diff-row${row.different ? ' is-different' : ''}">
          <span>${escapeHtml(row.label)}</span>
          <strong>${escapeHtml(row.leftValue)}</strong>
          <strong>${escapeHtml(row.rightValue)}</strong>
        </div>
      `).join('') || '<div class="desk-compare__empty">暂无可比较参数</div>';
    }
    if (els.deskComparePromptLeft) els.deskComparePromptLeft.textContent = left?.prompt || '无提示词';
    if (els.deskComparePromptRight) els.deskComparePromptRight.textContent = right?.prompt || '无提示词';
  }

  function updateComparePosition(value = els.deskCompareRange?.value || 50) {
    const percent = Math.max(0, Math.min(100, Number(value) || 50));
    if (els.deskCompareOverlay) {
      els.deskCompareOverlay.style.clipPath = `inset(0 ${100 - percent}% 0 0)`;
    }
    if (els.deskCompareDivider) els.deskCompareDivider.style.left = `${percent}%`;
  }

  function openCompare(assets = getSelectedAssets()) {
    if (assets.length !== 2) {
      DesktopResults.showTransientMessage('请选择 2 张图片进入对比。');
      return;
    }
    comparePair = assets.slice(0, 2);
    const [left, right] = comparePair;
    if (els.deskCompareBaseImg) els.deskCompareBaseImg.src = mediaUrl(left.imageUrl);
    if (els.deskCompareTopImg) els.deskCompareTopImg.src = mediaUrl(right.imageUrl);
    const leftName = compareAssetName(left, 'A');
    const rightName = compareAssetName(right, 'B');
    if (els.deskCompareLeftLabel) {
      els.deskCompareLeftLabel.textContent = leftName;
      els.deskCompareLeftLabel.title = leftName;
    }
    if (els.deskCompareRightLabel) {
      els.deskCompareRightLabel.textContent = rightName;
      els.deskCompareRightLabel.title = rightName;
    }
    renderCompareInfo(left, right);
    if (els.deskCompareRange) els.deskCompareRange.value = '50';
    updateComparePosition(50);
    els.deskCompareModal?.classList.add('is-open');
    els.deskCompareModal?.setAttribute('aria-hidden', 'false');
  }

  function closeCompare() {
    els.deskCompareModal?.classList.remove('is-open');
    els.deskCompareModal?.setAttribute('aria-hidden', 'true');
  }

  function swapCompare() {
    if (comparePair.length !== 2) return;
    comparePair = [comparePair[1], comparePair[0]];
    openCompare(comparePair);
  }

  async function sendAssetToTelegram(asset) {
    if (!asset?.file) throw new Error('没有可发送的原图');
    return DesktopApi.exportTelegram({
      task_id: asset.taskId,
      archiveRelPath: asset.archiveRelPath || asset.archive_rel_path || '',
      primaryFile: asset.file,
      result_file: asset.file,
      output_file: asset.file,
      type: asset.type,
      prompt: asset.prompt
    });
  }

  async function sendAssetsToCanvas(assets, options = {}) {
    const payloads = (Array.isArray(assets) ? assets : [assets])
      .filter(asset => asset?.imageUrl || asset?.imagePath)
      .map(makeDragPayload);
    if (!payloads.length) {
      DesktopResults.showTransientMessage('没有可发送到画布的图片。');
      return 0;
    }
    const created = await window.DesktopCanvas?.createImageNodesFromHistoryItems?.(payloads);
    const count = Number(created || payloads.length);
    if (options.closePreview) closePreview();
    if (options.closeGallery !== false) closeGallery();
    DesktopResults.showTransientMessage(count > 1 ? `${count} 张图片已发送到画布。` : '图片已发送到画布。');
    return count;
  }

  function sendSelectedToCanvas() {
    const selected = getSelectedAssets();
    if (!selected.length) return;
    sendAssetsToCanvas(selected).catch(error => DesktopResults.showError(error));
  }

  function sendPreviewAssetToCanvas() {
    if (!previewAsset) return;
    sendAssetsToCanvas([previewAsset], { closePreview: true }).catch(error => DesktopResults.showError(error));
  }

  function continueEditPreviewAsset() {
    if (!previewAsset) return;
    const payload = makeDragPayload(previewAsset);
    closePreview();
    window.DesktopCanvas?.continueEditFromHistoryItem?.(payload)
      ?.catch?.(error => DesktopResults.showError(error));
  }

  function hasAssetModelConfig(asset) {
    return !!(asset?.prompt || (asset?.params && Object.keys(asset.params || {}).length));
  }

  function applyAssetToInput(asset) {
    if (!asset || !hasAssetModelConfig(asset)) {
      DesktopResults.showTransientMessage('这张图没有可套用的提示词或参数。');
      return;
    }
    window.DesktopCanvas?.applyAssetConfigToInput?.(asset, { mode: 'all' });
  }

  function applyPreviewAssetToInput() {
    applyAssetToInput(previewAsset);
  }

  async function updateAssetMeta(asset, patch, options = {}) {
    if (!asset?.id || !DesktopApi.updateAssetMeta) return null;
    const result = await DesktopApi.updateAssetMeta(asset.id, patch);
    const meta = result.asset || result.meta || {};
    applyAssetMeta(asset, meta);
    gallerySets.forEach(assetSet => {
      (assetSet.assets || []).forEach(setAsset => {
        if (setAsset.id === asset.id) applyAssetMeta(setAsset, meta);
      });
    });
    if (previewAsset?.id === asset.id) {
      applyAssetMeta(previewAsset, meta);
      setPreviewAsset(previewAsset, false);
    }
    if (options.render === false) {
      updateGalleryCardState(asset.id);
    } else {
      renderGallery();
    }
    renderGallerySelection();
    return meta;
  }

  async function toggleAssetFavorite(asset, options = {}) {
    const nextValue = !asset.favorite;
    await updateAssetMeta(asset, { favorite: nextValue }, options);
    DesktopResults.showTransientMessage(nextValue ? '已收藏。' : '已取消收藏。');
  }

  async function editAssetTags(asset) {
    if (!asset) return;
    const current = parseTags(asset.tags).join('，');
    const raw = window.prompt('标签（逗号分隔，留空清除）', current);
    if (raw === null) return;
    const tags = parseTags(raw);
    await updateAssetMeta(asset, { tags });
    DesktopResults.showTransientMessage(tags.length ? '标签已更新。' : '标签已清除。');
  }

  async function toggleAssetHidden(asset) {
    if (!asset) return;
    const nextValue = !asset.hidden;
    await updateAssetMeta(asset, { hidden: nextValue });
    if (nextValue && galleryFilter !== 'hidden') selectedGalleryIds.delete(asset.id);
    renderPreviewActions(asset);
    DesktopResults.showTransientMessage(nextValue ? '图片已隐藏。' : '图片已取消隐藏。');
  }

  function removeAssetsFromGalleryState(assetIds) {
    const ids = new Set((assetIds || []).filter(Boolean));
    if (!ids.size) return;
    galleryAssets = galleryAssets.filter(asset => !ids.has(asset.id));
    galleryAssetTotal = Math.max(0, galleryAssetTotal - ids.size);
    gallerySets = gallerySets.map(assetSet => {
      const assets = (assetSet.assets || []).filter(asset => !ids.has(asset.id));
      const assetIds = (assetSet.assetIds || assetSet.asset_ids || []).filter(id => !ids.has(id));
      return {
        ...assetSet,
        assets,
        assetIds,
        asset_ids: assetIds,
        count: assetIds.length || assets.length
      };
    });
    ids.forEach(id => selectedGalleryIds.delete(id));
    if (previewAsset && ids.has(previewAsset.id)) closePreview();
    renderGallery();
    renderGallerySelection();
  }

  async function deleteAssetsFromDisk(assets, options = {}) {
    const targets = (Array.isArray(assets) ? assets : [assets])
      .filter(asset => asset?.id)
      .sort((a, b) => {
        const taskCompare = String(a.taskId || '').localeCompare(String(b.taskId || ''));
        if (taskCompare) return taskCompare;
        return Number(b.index || 0) - Number(a.index || 0);
      });
    if (!targets.length) return;
    const label = targets.length > 1 ? `${targets.length} 张图片` : `「${targets[0].title || '这张图片'}」`;
    const confirmed = window.confirm(`确认删除 ${label}？\n\n将把 Obsidian 归档原图、同名提示词和本地预览/缩略图移入废纸篓，并从图库和候选集中移除。`);
    if (!confirmed) return;

    const button = options.button || null;
    const originalText = button?.textContent || '';
    const canSetButtonText = !!button?.classList?.contains('desk-button');
    const deletedIds = [];
    const batchIds = [];
    try {
      if (button) {
        button.disabled = true;
        if (canSetButtonText) button.textContent = targets.length > 1 ? '删除中' : originalText;
      }
      const result = await (DesktopApi.deleteAssets
        ? DesktopApi.deleteAssets(targets.map(asset => asset.id))
        : DesktopApi.deleteAsset(targets[0].id));
      if (!result?.ok) throw new Error(result?.error || '删除失败');
      const processedIds = Array.isArray(result.asset_ids) && result.asset_ids.length
        ? result.asset_ids
        : targets.map(asset => asset.id);
      deletedIds.push(...processedIds);
      const batchId = result.delete_batch_id || result.undo_id || '';
      if (batchId) batchIds.push(batchId);
      lastDeleteBatchIds = batchIds;
      removeAssetsFromGalleryState(deletedIds);
      await Promise.all([
        loadHistory(80),
        loadGalleryAssets(),
        loadGallerySets()
      ]);
      const missingCount = Array.isArray(result.missing_asset_ids) ? result.missing_asset_ids.length : 0;
      const suffix = missingCount ? `，${missingCount} 张记录已失效` : '';
      galleryMessage(deletedIds.length > 1 ? `${deletedIds.length} 张图片已移入废纸篓，可撤销${suffix}。` : `图片和提示词已移入废纸篓，可撤销${suffix}。`);
    } catch (error) {
      if (deletedIds.length) removeAssetsFromGalleryState(deletedIds);
      if (batchIds.length) lastDeleteBatchIds = batchIds;
      galleryError(error, '删除图片失败');
    } finally {
      if (button && canSetButtonText && originalText) button.textContent = originalText;
      renderGallerySelection();
      if (previewAsset) renderPreviewActions(previewAsset);
    }
  }

  function deleteSelectedAssets() {
    const selected = getSelectedAssets();
    if (!selected.length) {
      galleryMessage('请先选择要删除的图片。');
      return;
    }
    deleteAssetsFromDisk(selected, { button: els.deskGalleryDeleteBtn }).catch(() => {});
  }

  function deletePreviewAsset() {
    if (!previewAsset) {
      galleryMessage('没有可删除的预览图片。');
      return;
    }
    deleteAssetsFromDisk([previewAsset], { button: els.deskGalleryPreviewDeleteBtn }).catch(() => {});
  }

  function formatAssetHealthSummary(health = {}) {
    const stats = health.stats || health || {};
    const parts = [];
    parts.push(`Obsidian ${Number(stats.obsidian_image_count || 0).toLocaleString('zh-CN')} 张`);
    parts.push(`图库 ${Number(stats.gallery_asset_count || 0).toLocaleString('zh-CN')} 张`);
    parts.push(`有任务记录 ${Number(stats.task_record_image_count || 0).toLocaleString('zh-CN')} 张`);
    parts.push(`孤儿图 ${Number(stats.orphan_asset_count || 0).toLocaleString('zh-CN')} 张`);
    if (stats.history_missing_count) parts.push(`记录缺图 ${Number(stats.history_missing_count || 0).toLocaleString('zh-CN')} 条`);
    if (health.missing_count) parts.push(`缺文件资产 ${health.missing_count} 个`);
    if (health.invalid_set_refs) parts.push(`候选集失效引用 ${health.invalid_set_refs} 个`);
    if (health.empty_set_count) parts.push(`空候选集 ${health.empty_set_count} 个`);
    if (health.invalid_lineage_refs) parts.push(`失效溯源 ${health.invalid_lineage_refs} 个`);
    if (health.no_image_history) parts.push(`无图历史 ${health.no_image_history} 条`);
    return parts.length ? parts.join('、') : '图库状态正常';
  }

  async function runGalleryHealthCheck() {
    const button = els.deskGalleryHealthBtn;
    if (button) button.disabled = true;
    galleryMessage('正在体检图库...');
    try {
      if (!DesktopApi.getAssetHealth || !DesktopApi.cleanupAssetHealth) {
        throw new Error('图库体检接口未加载，请强制刷新页面');
      }
      const result = await DesktopApi.getAssetHealth();
      const health = result.health || result || {};
      const summary = formatAssetHealthSummary(health);
      if (health.stats) {
        galleryAssetStats = health.stats;
        renderGalleryStats();
      }
      if (health.ok || !health.issue_count) {
        galleryMessage(`图库状态正常：${summary}。`);
        return;
      }
      const confirmed = window.confirm(`图库体检发现：${summary}。\n\n是否现在清理？`);
      if (!confirmed) {
        galleryMessage(summary);
        return;
      }
      galleryMessage('正在清理图库...');
      const cleanup = await DesktopApi.cleanupAssetHealth();
      await Promise.all([
        loadHistory(80),
        loadGalleryAssets(),
        loadGallerySets()
      ]);
      const after = cleanup.after || {};
      galleryMessage(after.ok ? '图库清理完成，状态正常。' : `图库清理完成，剩余：${formatAssetHealthSummary(after)}。`);
    } catch (error) {
      galleryError(error, '图库体检失败');
    } finally {
      if (button) button.disabled = false;
      renderGallerySelection();
    }
  }

  async function refreshGalleryMetadata() {
    const button = els.deskGalleryRefreshMetaBtn;
    const originalText = button?.textContent || '';
    try {
      if (button) {
        button.disabled = true;
        button.textContent = '刷新中';
      }
      galleryMessage('正在刷新图库元数据...');
      await Promise.all([
        loadHistory(80),
        loadGalleryAssets(),
        loadGallerySets()
      ]);
      const count = Number(galleryAssetStats.metadata_image_count || 0).toLocaleString('zh-CN');
      galleryMessage(`元数据已刷新，${count} 张图片已有尺寸信息。`);
    } catch (error) {
      galleryError(error, '刷新元数据失败');
    } finally {
      if (button && originalText) {
        button.textContent = originalText;
        button.disabled = false;
      }
      renderGallerySelection();
    }
  }

  async function undoLastAssetDelete() {
    if (!lastDeleteBatchIds.length) {
      galleryMessage('没有可撤销的删除。');
      return;
    }
    const button = els.deskGalleryUndoDeleteBtn;
    const originalText = button?.textContent || '';
    try {
      if (button) {
        button.disabled = true;
        button.textContent = '撤销中';
      }
      const result = await DesktopApi.undoAssetDelete(lastDeleteBatchIds);
      if (!result?.ok) throw new Error(result?.error || result?.errors?.join('；') || '撤销失败');
      lastDeleteBatchIds = [];
      await Promise.all([
        loadHistory(80),
        loadGalleryAssets(),
        loadGallerySets()
      ]);
      galleryMessage(`已撤销删除，恢复 ${result.restored_files || 0} 个文件。`);
    } catch (error) {
      galleryError(error, '撤销删除失败');
    } finally {
      if (button && originalText) button.textContent = originalText;
      renderGallerySelection();
    }
  }

  async function sendPreviewAssetToTelegram() {
    if (!previewAsset) return;
    const button = els.deskGalleryPreviewSendBtn;
    try {
      if (button) button.disabled = true;
      await sendAssetToTelegram(previewAsset);
      DesktopResults.showTransientMessage('图片已发送到 Telegram。');
    } finally {
      renderPreviewActions(previewAsset);
    }
  }

  function attachPreviewAssetToLayout() {
    if (!previewAsset) return;
    const payload = [makeDragPayload(previewAsset)];
    window.DesktopCanvas?.attachHistoryImagesToLayout?.(payload)
      ?.catch?.(error => DesktopResults.showError(error));
  }

  function addPreviewAssetToCompare() {
    if (!previewAsset) return;
    const queuedIndex = previewCompareQueue.findIndex(asset => asset.id === previewAsset.id);
    if (queuedIndex >= 0) {
      previewCompareQueue.splice(queuedIndex, 1);
      renderPreviewActions(previewAsset);
      DesktopResults.showTransientMessage('已移出待对比。');
      return;
    }
    previewCompareQueue.push(previewAsset);
    if (previewCompareQueue.length < 2) {
      renderPreviewActions(previewAsset);
      DesktopResults.showTransientMessage('已加入对比 A，继续打开另一张图片。');
      return;
    }
    const pair = previewCompareQueue.slice(0, 2);
    previewCompareQueue = [];
    renderPreviewActions(previewAsset);
    openCompare(pair);
  }

  async function editSelectedTags() {
    const selected = getSelectedAssets();
    if (!selected.length) return;
    const current = [...new Set(selected.flatMap(asset => parseTags(asset.tags)))].join('，');
    const raw = window.prompt('标签（逗号分隔，留空清除）', current);
    if (raw === null) return;
    const tags = parseTags(raw);
    for (const asset of selected) {
      await updateAssetMeta(asset, { tags });
    }
    DesktopResults.showTransientMessage(tags.length ? `${selected.length} 张图片已更新标签。` : `${selected.length} 张图片已清除标签。`);
  }

  async function toggleSelectedHidden() {
    const selected = getSelectedAssets();
    if (!selected.length) return;
    const nextValue = !selected.every(asset => asset.hidden);
    for (const asset of selected) {
      await updateAssetMeta(asset, { hidden: nextValue });
    }
    if (nextValue && galleryFilter !== 'hidden') {
      selected.forEach(asset => selectedGalleryIds.delete(asset.id));
    }
    renderGallery();
    renderGallerySelection();
    DesktopResults.showTransientMessage(nextValue ? `${selected.length} 张图片已隐藏。` : `${selected.length} 张图片已取消隐藏。`);
  }

  function bindEvents() {
    document.addEventListener('click', event => {
      if (event.__galleryActionHandled) return;
      const target = event.target;
      if (!target?.closest) return;
      if (target.closest('#deskGalleryHealthBtn')) {
        event.preventDefault();
        event.__galleryActionHandled = true;
        runGalleryHealthCheck().catch(() => {});
        return;
      }
      if (target.closest('#deskGalleryDeleteBtn')) {
        event.preventDefault();
        event.__galleryActionHandled = true;
        deleteSelectedAssets();
        return;
      }
      if (target.closest('#deskGalleryUndoDeleteBtn')) {
        event.preventDefault();
        event.__galleryActionHandled = true;
        undoLastAssetDelete().catch(() => {});
      }
    });

    els.deskHistoryCollapseBtn?.addEventListener('click', () => {
      setHistoryCollapsed(true);
    });
    els.deskHistoryExpandBtn?.addEventListener('click', () => {
      setHistoryCollapsed(false);
    });
    els.deskHistoryBtn?.addEventListener('click', () => {
      setHistoryCollapsed(false);
      loadHistory().catch(error => DesktopResults.showError(error));
    });
    els.deskFilePreviewCloseBtn?.addEventListener('click', closeEditableFilePreview);
    els.deskFilePreviewModal?.addEventListener('click', event => {
      if (event.target === els.deskFilePreviewModal) closeEditableFilePreview();
    });
    els.deskFilePreviewSendBtn?.addEventListener('click', async () => {
      try {
        await sendEditableFile(previewEditableFile, els.deskFilePreviewSendBtn);
      } catch (error) {
        DesktopResults.showError(error);
      }
    });
    els.deskFilePreviewDeleteBtn?.addEventListener('click', async () => {
      try {
        await deleteEditableFile(previewEditableFile, els.deskFilePreviewDeleteBtn);
      } catch (error) {
        DesktopResults.showError(error);
      }
    });

    els.deskGalleryRefreshBtn?.addEventListener('click', () => {
      if (galleryView === 'sources') {
        refreshPromptSources().catch(error => DesktopResults.showError(error));
        return;
      }
      Promise.all([
        loadHistory(80),
        loadGalleryAssets(),
        loadGallerySets()
      ]).catch(error => DesktopResults.showError(error));
    });
    els.deskGalleryHealthBtn?.addEventListener('click', event => {
      event.__galleryActionHandled = true;
      runGalleryHealthCheck().catch(() => {});
    });
    els.deskGalleryCloseBtn?.addEventListener('click', closeGallery);
    els.deskGallerySearchInput?.addEventListener('input', event => {
      const value = event.target.value || '';
      if (gallerySearchTimer) window.clearTimeout(gallerySearchTimer);
      gallerySearchTimer = window.setTimeout(() => {
        galleryQuery = value;
        refreshGalleryAssets();
      }, 120);
    });
    els.deskGalleryFilterSelect?.addEventListener('change', event => {
      galleryFilter = event.target.value || 'all';
      refreshGalleryAssets();
    });
    els.deskGalleryTagInput?.addEventListener('input', event => {
      const value = event.target.value || '';
      if (gallerySearchTimer) window.clearTimeout(gallerySearchTimer);
      gallerySearchTimer = window.setTimeout(() => {
        galleryTag = value;
        refreshGalleryAssets();
      }, 120);
    });
    document.querySelectorAll('[data-gallery-view]').forEach(button => {
      button.addEventListener('click', () => {
        activeGallerySet = null;
        galleryView = button.dataset.galleryView || 'images';
        resetGalleryRenderLimit();
        renderGallery();
        renderGallerySelection();
        refreshGalleryAssets();
      });
    });
    els.deskGalleryGrid?.addEventListener('scroll', () => {
      const grid = els.deskGalleryGrid;
      if (!grid || galleryView !== 'images') return;
      scheduleGalleryVirtualRender(grid);
    }, { passive: true });
    els.deskGalleryCompareBtn?.addEventListener('click', () => openCompare());
    els.deskGalleryCanvasBtn?.addEventListener('click', sendSelectedToCanvas);
    els.deskGallerySaveSetBtn?.addEventListener('click', () => {
      saveSelectedAsSet().catch(error => DesktopResults.showError(error));
    });
    els.deskGalleryRefreshMetaBtn?.addEventListener('click', () => {
      refreshGalleryMetadata().catch(error => DesktopResults.showError(error));
    });
    els.deskGalleryTagBtn?.addEventListener('click', () => {
      editSelectedTags().catch(error => DesktopResults.showError(error));
    });
    els.deskGalleryHideBtn?.addEventListener('click', () => {
      toggleSelectedHidden().catch(error => DesktopResults.showError(error));
    });
    els.deskGalleryDeleteBtn?.addEventListener('click', event => {
      event.__galleryActionHandled = true;
      deleteSelectedAssets();
    });
    els.deskGalleryUndoDeleteBtn?.addEventListener('click', event => {
      event.__galleryActionHandled = true;
      undoLastAssetDelete().catch(() => {});
    });
    els.deskGalleryClearBtn?.addEventListener('click', () => {
      selectedGalleryIds.clear();
      renderGallery();
      renderGallerySelection();
    });

    els.deskGalleryPreviewCopyBtn?.addEventListener('click', () => {
      copyPreviewPrompt().catch(error => DesktopResults.showError(error));
    });
    els.deskGalleryPreviewPromptCompareBtn?.addEventListener('click', togglePreviewPromptCompare);
    els.deskGalleryPreviewCopyRevisedBtn?.addEventListener('click', () => {
      copyPreviewRevisedPrompt().catch(error => DesktopResults.showError(error));
    });
    els.deskGalleryPreviewApplyBtn?.addEventListener('click', applyPreviewAssetToInput);
    els.deskGalleryPreviewCanvasBtn?.addEventListener('click', sendPreviewAssetToCanvas);
    els.deskGalleryPreviewEditBtn?.addEventListener('click', continueEditPreviewAsset);
    els.deskGalleryPreviewOpenBtn?.addEventListener('click', openPreviewOriginal);
    els.deskGalleryPreviewFavoriteBtn?.addEventListener('click', () => {
      if (previewAsset) toggleAssetFavorite(previewAsset).catch(error => DesktopResults.showError(error));
    });
    els.deskGalleryPreviewTagBtn?.addEventListener('click', () => {
      if (previewAsset) editAssetTags(previewAsset).catch(error => DesktopResults.showError(error));
    });
    els.deskGalleryPreviewHideBtn?.addEventListener('click', () => {
      if (previewAsset) toggleAssetHidden(previewAsset).catch(error => DesktopResults.showError(error));
    });
    els.deskGalleryPreviewDeleteBtn?.addEventListener('click', deletePreviewAsset);
    els.deskGalleryPreviewCompareBtn?.addEventListener('click', addPreviewAssetToCompare);
    els.deskGalleryPreviewLayoutBtn?.addEventListener('click', attachPreviewAssetToLayout);
    els.deskGalleryPreviewSendBtn?.addEventListener('click', () => {
      sendPreviewAssetToTelegram().catch(error => DesktopResults.showError(error));
    });
    els.deskGalleryPreviewCloseBtn?.addEventListener('click', closePreview);
    els.deskGalleryPreviewPrevBtn?.addEventListener('click', () => navigatePreview(-1));
    els.deskGalleryPreviewNextBtn?.addEventListener('click', () => navigatePreview(1));
    els.deskGalleryPreviewZoomOutBtn?.addEventListener('click', () => zoomPreview(-0.2));
    els.deskGalleryPreviewZoomInBtn?.addEventListener('click', () => zoomPreview(0.2));
    els.deskGalleryPreviewImg?.addEventListener('load', applyPreviewZoom);
    els.deskGalleryPreviewStage?.addEventListener('pointerdown', startPreviewDrag);
    els.deskGalleryPreviewStage?.addEventListener('pointermove', movePreviewDrag);
    els.deskGalleryPreviewStage?.addEventListener('pointerup', endPreviewDrag);
    els.deskGalleryPreviewStage?.addEventListener('pointercancel', endPreviewDrag);
    els.deskGalleryPreviewModal?.addEventListener('click', event => {
      if (event.target === els.deskGalleryPreviewModal) closePreview();
    });
    window.addEventListener('resize', () => {
      if (els.deskGalleryPreviewModal?.classList.contains('is-open')) applyPreviewZoom();
      scheduleGalleryVirtualRender();
      schedulePromptSourceTabSlider();
    });

    els.deskCompareRange?.addEventListener('input', event => updateComparePosition(event.target.value));
    els.deskCompareCloseBtn?.addEventListener('click', closeCompare);
    els.deskCompareSwapBtn?.addEventListener('click', swapCompare);
    els.deskCompareModal?.addEventListener('click', event => {
      if (event.target === els.deskCompareModal) closeCompare();
    });
    document.addEventListener('keydown', event => {
      const previewOpen = els.deskGalleryPreviewModal?.classList.contains('is-open');
      if (previewOpen && event.key === 'ArrowLeft') {
        navigatePreview(-1);
        return;
      }
      if (previewOpen && event.key === 'ArrowRight') {
        navigatePreview(1);
        return;
      }
      if (previewOpen && (event.key === '+' || event.key === '=')) {
        zoomPreview(0.2);
        return;
      }
      if (previewOpen && event.key === '-') {
        zoomPreview(-0.2);
        return;
      }
      if (event.key !== 'Escape') return;
      if (els.deskFilePreviewModal?.classList.contains('is-open')) {
        closeEditableFilePreview();
        return;
      }
      if (previewOpen) {
        closePreview();
        return;
      }
      if (els.deskCompareModal?.classList.contains('is-open')) {
        closeCompare();
        return;
      }
      if (els.deskGalleryPanel?.classList.contains('is-open')) closeGallery();
    });
  }

  function init() {
    collectElements();
    bindHistoryPanelBounds();
    restoreHistoryCollapsedState();
    bindEvents();
  }

  window.DesktopHistory = {
    init,
    loadHistory,
    renderHistory,
    selectHistoryItem,
    setHistoryCollapsed,
    syncHistoryPanelBounds,
    openGallery,
    closeGallery,
    flattenHistoryItems,
    getSelectedAssets
  };
})();

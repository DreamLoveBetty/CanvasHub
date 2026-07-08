// Cinematic creation stream cards
  let cinematicHistoryThumbObserver = null;

  function disconnectCinematicHistoryThumbObserver() {
    if (cinematicHistoryThumbObserver) {
      cinematicHistoryThumbObserver.disconnect();
      cinematicHistoryThumbObserver = null;
    }
  }

  function resolveCinematicHistoryThumbObserver() {
    if (cinematicHistoryThumbObserver) return cinematicHistoryThumbObserver;

    const root = document.querySelector('.cinematic-main');
    if (!('IntersectionObserver' in window)) return null;

    cinematicHistoryThumbObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        hydrateCinematicDeferredThumb(entry.target);
        cinematicHistoryThumbObserver?.unobserve(entry.target);
      });
    }, {
      root,
      rootMargin: '0px',
      threshold: 0.01
    });

    return cinematicHistoryThumbObserver;
  }

  function hydrateCinematicDeferredThumb(img) {
    if (!img || img.dataset.loaded === 'true') return;

    const nextSrc = img.dataset.src || '';
    if (!nextSrc) return;

    img.dataset.loaded = 'true';
    img.src = nextSrc;
  }

  function queueCinematicDeferredThumb(img, onMissing) {
    if (!img) return;
    img.__onMissing = onMissing;
    img.onerror = function onThumbError() {
      if (this.dataset.fallback && this.dataset.fallback !== this.src) {
        this.src = this.dataset.fallback;
        this.dataset.fallback = '';
        return;
      }
      if (typeof this.__onMissing === 'function') this.__onMissing();
    };

    const observer = resolveCinematicHistoryThumbObserver();
    if (!observer) {
      hydrateCinematicDeferredThumb(img);
      return;
    }
    observer.observe(img);
  }

  function createCinematicActionButton(label, className, handler) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `cinematic-record-action ${className || ''}`.trim();
    button.textContent = label;
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      handler();
    });
    return button;
  }

  function getCinematicHistoryImageUrls(item) {
    if (!item) return [];
    const urls = [];
    const pushUrl = (url) => {
      const normalized = String(url || '').trim();
      if (normalized && !urls.includes(normalized)) urls.push(normalized);
    };

    if (Array.isArray(item.image_paths)) {
      item.image_paths.forEach(pushUrl);
    }

    const files = item.output_files || item.result_files || [];
    if ((item.type === 'gpt' || item.type === 'gpt-edit') && Array.isArray(files)) {
      files.forEach((name) => pushUrl(String(name || '').startsWith('/') ? name : `/gpt_outputs/${name}`));
    }

    const primary = getHistoryImageSource(item);
    if (primary) pushUrl(primary);
    return urls;
  }

  function getCinematicGptFilenameFromUrl(url) {
    const cleaned = String(url || '').split('?')[0];
    return decodeURIComponent(cleaned.slice(cleaned.lastIndexOf('/') + 1));
  }

  function getCinematicHistoryPreviewUrl(url) {
    const rawUrl = String(url || '').trim();
    if (!rawUrl) return '';
    const [path, query = ''] = rawUrl.split('?');
    if (path.includes('/gpt_outputs/') && path.toLowerCase().endsWith('.png') && !path.toLowerCase().endsWith('_thumb.png')) {
      return `${path.slice(0, -4)}_thumb.png${query ? `?${query}` : ''}`;
    }
    return rawUrl;
  }

  function openCinematicHistoryImage(item, url) {
    if (!item || !url) return;
    if ((item.type === 'gpt' || item.type === 'gpt-edit') && url.includes('/gpt_outputs/')) {
      openDetailModal({ ...item, output_file: getCinematicGptFilenameFromUrl(url) });
      return;
    }
    openDetailModal(item);
  }

  function createCinematicHistoryCard(item) {
    const card = document.createElement('article');
    const isPendingTask = isPendingHistoryRecord(item);
    card.className = `cinematic-record-card${isPendingTask ? ' is-pending-task' : ''}`;
    const imageUrls = getCinematicHistoryImageUrls(item);
    const extraImageUrls = (!isPendingTask && (item.type === 'gpt' || item.type === 'gpt-edit')) ? imageUrls.slice(1) : [];
    const canFlipImages = extraImageUrls.length > 0;

    const thumbMeta = getHistoryThumbMeta(item);
    const media = document.createElement('button');
    const applyMissingState = () => {
      markHistoryAssetMissing(item);
      media.classList.add('is-empty', 'is-missing');
      media.innerHTML = '<span>FILE MISSING</span>';
      source.classList.add('is-missing');
      sourceThumb.innerHTML = '<span>!</span>';
      sourceText.textContent = '原始图片文件已丢失';
    };

    media.type = 'button';
    media.className = `cinematic-record-media${thumbMeta.src ? ' is-pending' : ' is-empty'}${isHistoryAssetMissing(item) ? ' is-missing' : ''}${isPendingTask ? ' is-generating' : ''}`;
    if (!isPendingTask) {
      media.addEventListener('click', () => openDetailModal(item));
    }
    if (isPendingTask) {
      media.disabled = true;
      media.innerHTML = '<span class="cinematic-pending-glow"><i></i><b></b></span>';
    } else if (thumbMeta.src) {
      const img = document.createElement('img');
      img.alt = getCinematicTypeLabel(item);
      img.loading = 'eager';
      img.dataset.src = thumbMeta.src;
      img.dataset.loaded = 'false';
      img.dataset.fallback = thumbMeta.fallback || '';
      img.onload = function onThumbLoad() {
        clearHistoryAssetMissing(item);
        media.classList.remove('is-pending');
      };
      media.appendChild(img);
      queueCinematicDeferredThumb(img, applyMissingState);
    } else {
      media.innerHTML = `<span>${isHistoryAssetMissing(item) ? 'FILE MISSING' : 'NO PREVIEW'}</span>`;
    }

    const body = document.createElement('div');
    body.className = `cinematic-record-body${canFlipImages ? ' has-gallery-flip' : ''}`;
    body.addEventListener('click', () => {
      if (isPendingTask) return;
      if (!canFlipImages) {
        openDetailModal(item);
        return;
      }
      body.classList.toggle('is-flipped');
    });

    const frontFace = document.createElement('div');
    frontFace.className = 'cinematic-record-face cinematic-record-face-front';

    const backFace = document.createElement('div');
    backFace.className = 'cinematic-record-face cinematic-record-face-back';

    const head = document.createElement('div');
    head.className = 'cinematic-record-head';

    const titleWrap = document.createElement('div');
    const title = document.createElement('div');
    title.className = 'cinematic-record-title';
    title.textContent = getCinematicTypeLabel(item);
    const time = document.createElement('div');
    time.className = 'cinematic-record-time';
    time.textContent = getHistoryDateMeta(item.timestamp).full.replace(/\//g, '.');
    titleWrap.appendChild(title);
    titleWrap.appendChild(time);

    const badges = document.createElement('div');
    badges.className = 'cinematic-record-badges';
    const primaryBadge = document.createElement('span');
    primaryBadge.className = 'cinematic-badge is-primary';
    primaryBadge.textContent = getCinematicPrimaryBadge(item);
    const secondaryBadge = document.createElement('span');
    secondaryBadge.className = 'cinematic-badge';
    secondaryBadge.textContent = getCinematicSecondaryBadge(item);
    badges.appendChild(primaryBadge);
    badges.appendChild(secondaryBadge);
    if (canFlipImages) {
      const multiBadge = document.createElement('span');
      multiBadge.className = 'cinematic-badge is-gallery';
      multiBadge.textContent = `+${extraImageUrls.length}`;
      multiBadge.title = '点击参数卡片查看其余图片';
      badges.appendChild(multiBadge);
    }

    head.appendChild(titleWrap);
    head.appendChild(badges);

    const prompt = document.createElement('p');
    prompt.className = 'cinematic-record-prompt';
    prompt.textContent = item.prompt || item.error || '这条记录暂时没有可展示的提示词。';

    const foot = document.createElement('div');
    foot.className = 'cinematic-record-foot';

    const source = document.createElement('div');
    source.className = `cinematic-record-source${isHistoryAssetMissing(item) ? ' is-missing' : ''}${isPendingTask ? ' is-pending-task' : ''}`;
    const sourceThumb = document.createElement('span');
    sourceThumb.className = 'cinematic-record-source-thumb';
    if (isPendingTask) {
      sourceThumb.innerHTML = '<span class="cinematic-pending-dot"></span>';
    } else if (isHistoryAssetMissing(item)) {
      sourceThumb.innerHTML = '<span>!</span>';
    } else if (thumbMeta.src) {
      const sourceImg = document.createElement('img');
      sourceImg.alt = '';
      sourceImg.loading = 'eager';
      sourceImg.dataset.src = thumbMeta.src;
      sourceImg.dataset.loaded = 'false';
      sourceImg.dataset.fallback = thumbMeta.fallback || '';
      sourceImg.onerror = () => {
        source.classList.add('is-missing');
        sourceThumb.innerHTML = '<span>!</span>';
        sourceText.textContent = '原始图片文件已丢失';
      };
      sourceThumb.appendChild(sourceImg);
      queueCinematicDeferredThumb(sourceImg, () => {
        source.classList.add('is-missing');
        sourceThumb.innerHTML = '<span>!</span>';
        sourceText.textContent = '原始图片文件已丢失';
      });
    } else {
      sourceThumb.textContent = '•';
    }
    const sourceText = document.createElement('span');
    sourceText.textContent = isPendingTask ? (item.__pendingText || item.progress_text || '任务已提交，等待结果回传') : (isHistoryAssetMissing(item) ? '原始图片文件已丢失' : getCinematicSourceLabel(item));
    source.appendChild(sourceThumb);
    source.appendChild(sourceText);

    const actions = document.createElement('div');
    actions.className = 'cinematic-record-actions';
    if (isPendingTask) {
      const pendingChip = document.createElement('span');
      pendingChip.className = 'cinematic-record-pending-chip';
      pendingChip.textContent = '生成中';
      actions.appendChild(pendingChip);
    } else {
      actions.appendChild(createCinematicActionButton('↺', '', () => retryCinematicHistoryItem(item)));
      actions.appendChild(createCinematicActionButton('⎘', '', () => copyHistoryPromptToCinematic(item)));
      actions.appendChild(createCinematicActionButton('⌫', 'is-danger', () => deleteHistoryItemByIdentity(item.task_id, item.timestamp)));
    }

    foot.appendChild(source);
    foot.appendChild(actions);

    frontFace.appendChild(head);
    frontFace.appendChild(prompt);
    frontFace.appendChild(foot);
    body.appendChild(frontFace);

    if (canFlipImages) {
      const galleryHead = document.createElement('div');
      galleryHead.className = 'cinematic-record-gallery-head';
      galleryHead.innerHTML = `<span>其余 ${extraImageUrls.length} 张</span><small>点击缩略图打开</small>`;

      const gallery = document.createElement('div');
      gallery.className = 'cinematic-record-gallery';
      extraImageUrls.slice(0, 9).forEach((url, index) => {
        const previewUrl = getCinematicHistoryPreviewUrl(url);
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'cinematic-record-gallery-tile';
        button.addEventListener('click', (event) => {
          event.stopPropagation();
          openCinematicHistoryImage(item, url);
        });

        const img = document.createElement('img');
        img.alt = `GPT 结果 ${index + 2}`;
        img.loading = 'eager';
        img.src = previewUrl || url;
        if (previewUrl && previewUrl !== url) {
          img.dataset.fallback = url;
          img.onerror = function onGalleryThumbError() {
            if (this.dataset.fallback && this.src !== this.dataset.fallback) {
              this.src = this.dataset.fallback;
              this.dataset.fallback = '';
            }
          };
        }
        button.appendChild(img);
        gallery.appendChild(button);
      });

      backFace.appendChild(galleryHead);
      backFace.appendChild(gallery);
      body.appendChild(backFace);
    }

    card.appendChild(media);
    card.appendChild(body);
    return card;
  }

  function renderCinematicHistoryStream() {
    const list = document.getElementById('cinematicHistoryList');
    if (!list) return;
    const main = document.querySelector('.cinematic-main');
    const hadCards = !!list.querySelector('.cinematic-record-card');
    const scrollSnapshot = main ? {
      top: main.scrollTop,
      height: main.scrollHeight,
      nearBottom: typeof isCinematicMainNearBottom === 'function' ? isCinematicMainNearBottom(main) : true
    } : null;

    disconnectCinematicHistoryThumbObserver();
    list.innerHTML = '';
    if (!historyRecords.length) {
      updateCinematicViewportMetrics();
      setCinematicHistoryMessage('可以开始创作', '历史记录会在后台同步，不会阻塞当前输入。');
      return;
    }

    const fragment = document.createDocumentFragment();
    [...historyRecords]
      .sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0))
      .forEach(item => fragment.appendChild(createCinematicHistoryCard(item)));

    list.appendChild(fragment);

    if (!hadCards || scrollSnapshot?.nearBottom) {
      syncCinematicLatestRecordFocus({ force: true });
    } else if (main && scrollSnapshot) {
      requestAnimationFrame(() => {
        const heightDelta = main.scrollHeight - scrollSnapshot.height;
        main.scrollTop = Math.max(0, scrollSnapshot.top + Math.max(0, heightDelta));
        updateCinematicViewportMetrics();
      });
    }
  }

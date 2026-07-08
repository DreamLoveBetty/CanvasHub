#!/usr/bin/env node

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => (data += chunk));
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

function readProjectSettings() {
  const settingsPath = process.env.APP_SETTINGS_PATH || path.join(__dirname, 'settings.json');
  try {
    if (!fs.existsSync(settingsPath)) return {};
    return JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
  } catch {
    return {};
  }
}

function gptBrowserDefaults() {
  const settings = readProjectSettings();
  const browser = settings && typeof settings.gpt_browser === 'object' ? settings.gpt_browser : {};
  const profile = process.env.GPT_BROWSER_PROFILE || browser.profile || 'tg-mini-app-img-gen';
  const fallbackUserDataDir = path.join(__dirname, 'data', 'gpt_browser', profile, 'user-data');
  const userDataDir = process.env.GPT_BROWSER_USER_DATA_DIR || browser.user_data_dir || fallbackUserDataDir;
  const port = Number(process.env.GPT_CDP_PORT || browser.cdp_port || 19333);
  const chromePath = process.env.GPT_CHROME_PATH || browser.chrome_path || '';
  return { profile, userDataDir, port, chromePath };
}

async function fetchText(url, opts = {}) {
  const res = await fetch(url, opts);
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} ${url} :: ${text.slice(0, 400)}`);
  }
  return text;
}

async function fetchJson(url, opts = {}) {
  const text = await fetchText(url, opts);
  return text ? JSON.parse(text) : {};
}

async function isBrowserUp(baseUrl) {
  try {
    await fetchJson(`${baseUrl}/json/version`);
    return true;
  } catch {
    return false;
  }
}

async function waitForBrowser(baseUrl, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await isBrowserUp(baseUrl)) return true;
    await sleep(500);
  }
  return false;
}

function candidateChromePaths() {
  const { chromePath } = gptBrowserDefaults();
  return [
    chromePath,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
  ].filter(Boolean);
}

function resolveChromePath() {
  for (const p of candidateChromePaths()) {
    if (fs.existsSync(p)) return p;
  }
  throw new Error('No supported Chrome/Chromium executable found. Set GPT_CHROME_PATH or gpt_browser.chrome_path.');
}

function launchChrome({ chromePath, port, userDataDir, startupUrl }) {
  fs.mkdirSync(userDataDir, { recursive: true });
  const args = [
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${userDataDir}`,
    '--profile-directory=Default',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-features=DialMediaRouteProvider',
    startupUrl || 'https://chatgpt.com/'
  ];

  const child = spawn(chromePath, args, {
    detached: true,
    stdio: 'ignore'
  });
  child.unref();
}

async function listTargets(baseUrl) {
  const targets = await fetchJson(`${baseUrl}/json/list`);
  return Array.isArray(targets) ? targets : [];
}

async function createPageTarget(baseUrl, url) {
  const encodedUrl = encodeURIComponent(url || 'https://chatgpt.com/');
  try {
    return await fetchJson(`${baseUrl}/json/new?${encodedUrl}`, { method: 'PUT' });
  } catch {
    return null;
  }
}

function pickPageTarget(targets) {
  const pages = targets.filter((t) => t && t.type === 'page' && t.webSocketDebuggerUrl);
  const chatgpt = pages.find((t) => String(t.url || '').includes('chatgpt.com'));
  if (chatgpt) return chatgpt;
  const useful = pages.find((t) => !String(t.url || '').startsWith('chrome://') && !String(t.url || '').startsWith('devtools://'));
  return useful || pages[0] || null;
}

class CdpClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.ws = null;
    this.nextId = 1;
    this.pending = new Map();
  }

  async connect() {
    await new Promise((resolve, reject) => {
      const ws = new WebSocket(this.wsUrl);
      this.ws = ws;
      const onError = (err) => reject(err instanceof Error ? err : new Error(String(err)));
      ws.addEventListener('error', onError, { once: true });
      ws.addEventListener('open', () => resolve(), { once: true });
      ws.addEventListener('message', (event) => {
        try {
          const msg = JSON.parse(String(event.data));
          if (msg.id && this.pending.has(msg.id)) {
            const { resolve, reject } = this.pending.get(msg.id);
            this.pending.delete(msg.id);
            if (msg.error) reject(new Error(msg.error.message || JSON.stringify(msg.error)));
            else resolve(msg.result || {});
          }
        } catch (err) {
          // ignore malformed events
        }
      });
      ws.addEventListener('close', () => {
        for (const { reject } of this.pending.values()) {
          reject(new Error('CDP websocket closed'));
        }
        this.pending.clear();
      });
    });
  }

  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression, { returnByValue = true } = {}) {
    const result = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue,
      userGesture: true
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.text || 'Runtime.evaluate failed');
    }
    return result.result ? result.result.value : undefined;
  }

  async close() {
    try {
      this.ws && this.ws.close();
    } catch {}
  }
}

async function ensureBrowserSession({ port, userDataDir, startupUrl }) {
  const baseUrl = `http://127.0.0.1:${port}`;
  if (!await isBrowserUp(baseUrl)) {
    launchChrome({
      chromePath: resolveChromePath(),
      port,
      userDataDir,
      startupUrl
    });
    const ok = await waitForBrowser(baseUrl, 30000);
    if (!ok) {
      throw new Error(`Chrome CDP did not start on ${baseUrl}. Check whether the profile dir is locked: ${userDataDir}`);
    }
    await sleep(1500);
  }
  let target = pickPageTarget(await listTargets(baseUrl));
  if (!target) {
    await sleep(1500);
    target = pickPageTarget(await listTargets(baseUrl));
  }
  if (!target) {
    const created = await createPageTarget(baseUrl, startupUrl);
    if (created && created.webSocketDebuggerUrl) {
      target = created;
    } else {
      await sleep(1500);
      target = pickPageTarget(await listTargets(baseUrl));
    }
  }
  if (!target) throw new Error('No debuggable page target found');
  return { baseUrl, target };
}

async function waitForReady(cdp, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const ready = await cdp.evaluate(`(() => document.readyState)()`);
      if (ready === 'complete' || ready === 'interactive') return true;
    } catch {}
    await sleep(500);
  }
  return false;
}

async function navigateToChatGPT(cdp, url) {
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Page.bringToFront');
  const currentUrl = await cdp.evaluate('(() => location.href)()').catch(() => '');
  if (!String(currentUrl || '').includes('chatgpt.com')) {
    await cdp.send('Page.navigate', { url });
    await waitForReady(cdp, 30000);
    await sleep(2500);
  } else {
    await cdp.send('Page.navigate', { url });
    await waitForReady(cdp, 30000);
    await sleep(2000);
  }
}

async function pageState(cdp) {
  return await cdp.evaluate(`(() => {
    const text = (document.body?.innerText || '').trim();
    const looksLikeGeneratedImageUrl = (raw) => {
      const u = String(raw || '').trim();
      if (!u) return false;
      const lower = u.toLowerCase();
      return lower.startsWith('blob:')
        || lower.startsWith('data:image/')
        || lower.includes('/backend-api/estuary/content?id=file_')
        || lower.includes('/backend-api/files/')
        || lower.includes('oaiusercontent.com')
        || lower.includes('oaistatic.com/files/')
        || /\\.(png|jpe?g|webp)(\\?|#|$)/i.test(lower);
    };
    const imageUrls = Array.from(document.querySelectorAll('img'))
      .flatMap((img) => {
        const candidates = [img.currentSrc, img.src];
        const srcset = img.getAttribute('srcset') || '';
        for (const part of srcset.split(',')) {
          const src = part.trim().split(/\\s+/)[0];
          if (src) candidates.push(src);
        }
        return candidates.map((u) => ({
          url: u,
          width: img.naturalWidth || img.width || 0,
          height: img.naturalHeight || img.height || 0
        }));
      })
      .filter((item) => item.url && (looksLikeGeneratedImageUrl(item.url) || (item.width >= 256 && item.height >= 256)))
      .map((item) => item.url);
    const linkedImageUrls = Array.from(document.querySelectorAll('a[href]'))
      .map((a) => a.href || '')
      .filter(looksLikeGeneratedImageUrl);
    const buttonNames = Array.from(document.querySelectorAll('button'))
      .map((btn) => (btn.getAttribute('aria-label') || btn.innerText || '').trim())
      .filter(Boolean)
      .slice(-50);
    return {
      title: document.title || '',
      url: location.href,
      text,
      imageUrls: Array.from(new Set([...imageUrls, ...linkedImageUrls])),
      buttonNames
    };
  })()`);
}

async function submitPrompt(cdp, prompt) {
  const composerReady = await waitForComposer(cdp, 30000);
  if (!composerReady) {
    throw new Error('composer_not_found');
  }

  const escaped = JSON.stringify(prompt);
  const fillResult = await cdp.evaluate(`(() => {
    const text = ${escaped};
    const selectors = [
      '#prompt-textarea',
      'div[contenteditable="true"]',
      'textarea[placeholder]',
      'textarea',
      'p[data-placeholder]'
    ];
    let el = null;
    for (const sel of selectors) {
      el = document.querySelector(sel);
      if (el) break;
    }
    if (!el) return { ok: false, error: 'composer_not_found' };

    el.focus();

    if (el.isContentEditable || el.contentEditable === 'true') {
      el.innerHTML = '';
      try {
        document.execCommand('insertText', false, text);
      } catch {
        el.textContent = text;
      }
      el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
    } else {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
      if (setter) setter.call(el, text);
      else el.value = text;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }

    const sendSelectors = [
      'button[data-testid*="send"]',
      'button[aria-label*="Send"]',
      'button[aria-label*="发送"]',
      'button[title*="Send"]',
      'button svg[aria-label*="Send"]',
      'form button[type="submit"]'
    ];

    let btn = null;
    for (const sel of sendSelectors) {
      const found = document.querySelector(sel);
      if (found) {
        btn = found.closest('button') || found;
        if (btn) break;
      }
    }

    if (!btn) {
      btn = Array.from(document.querySelectorAll('button')).find((b) => {
        const name = (b.getAttribute('aria-label') || b.innerText || '').trim().toLowerCase();
        return name.includes('send') || name.includes('发送');
      }) || null;
    }

    if (btn) {
      return { ok: true, method: 'filled', hasButton: true };
    }

    return { ok: true, method: 'filled', hasButton: false };
  })()`);

  if (!fillResult || !fillResult.ok) {
    throw new Error(fillResult?.error || 'submit_prompt_failed');
  }

  await sleep(800);

  for (let attempt = 0; attempt < 10; attempt += 1) {
    const state = await cdp.evaluate(`(() => {
      const composer = document.querySelector('#prompt-textarea');
      const btn = document.querySelector('#composer-submit-button')
        || document.querySelector('button[data-testid*="send"]')
        || Array.from(document.querySelectorAll('button')).find((b) => {
          const name = (b.getAttribute('aria-label') || b.innerText || '').trim().toLowerCase();
          return name.includes('send') || name.includes('发送');
        })
        || null;
      return {
        composerText: composer ? (composer.innerText || composer.textContent || '').trim() : '',
        hasButton: !!btn,
        buttonDisabled: btn ? !!btn.disabled : true
      };
    })()`);

    if (!state || !state.composerText) {
      return { ok: true, method: 'already-sent' };
    }

    if (state.hasButton && !state.buttonDisabled) {
      const clickResult = await cdp.evaluate(`(() => {
        const btn = document.querySelector('#composer-submit-button')
          || document.querySelector('button[data-testid*="send"]')
          || Array.from(document.querySelectorAll('button')).find((b) => {
            const name = (b.getAttribute('aria-label') || b.innerText || '').trim().toLowerCase();
            return name.includes('send') || name.includes('发送');
          })
          || null;
        if (!btn) return { ok: false, error: 'send_button_missing' };
        btn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
        btn.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
        btn.click();
        return { ok: true };
      })()`);
      if (!clickResult || !clickResult.ok) {
        throw new Error(clickResult?.error || 'send_button_click_failed');
      }

      for (let confirm = 0; confirm < 10; confirm += 1) {
        await sleep(400);
        const postState = await cdp.evaluate(`(() => {
          const composer = document.querySelector('#prompt-textarea');
          return {
            composerText: composer ? (composer.innerText || composer.textContent || '').trim() : ''
          };
        })()`);
        if (!postState || !postState.composerText) {
          return { ok: true, method: 'click' };
        }
      }
    }

    await sleep(400);
  }

  throw new Error('submit_prompt_timeout');
}

async function waitForComposer(cdp, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const state = await cdp.evaluate(`(() => {
        const selectors = [
          '#prompt-textarea',
          'div[contenteditable="true"]',
          'textarea[placeholder]',
          'textarea',
          'p[data-placeholder]'
        ];
        for (const sel of selectors) {
          const el = document.querySelector(sel);
          if (!el) continue;
          const rect = el.getBoundingClientRect();
          const visible = !!(rect.width || rect.height || el.getClientRects().length);
          return {
            ok: visible,
            selector: sel,
            readyState: document.readyState,
            title: document.title || '',
            textHead: (document.body?.innerText || '').slice(0, 240)
          };
        }
        return {
          ok: false,
          readyState: document.readyState,
          title: document.title || '',
          textHead: (document.body?.innerText || '').slice(0, 240)
        };
      })()`);
      if (state?.ok) return true;
    } catch {}
    await sleep(500);
  }
  return false;
}

function isLoginRequired(text) {
  const lower = String(text || '').toLowerCase();
  return ['登录', 'log in', 'sign up', '继续使用 google', 'continue with google'].some((k) => lower.includes(k));
}

function isQuotaLimited(text) {
  const lower = String(text || '').toLowerCase();
  return [
    '达到图片创建上限',
    'image generation limit',
    'rate limit',
    '请于明天',
    'try again tomorrow'
  ].some((k) => lower.includes(k));
}

function detectRefusal(text) {
  const lower = String(text || '').toLowerCase();
  const kws = [
    '非常抱歉，生成的图片可能违反了',
    '可能违反了关于裸露、色情或情色内容的防护限制',
    '无法满足该请求',
    '我不能帮助生成',
    '违反了我们的内容政策',
    'content policy',
    'cannot help with that',
    "can't help with that",
    'safety policy',
    'request was rejected'
  ];
  return kws.find((k) => lower.includes(k.toLowerCase())) || null;
}

function hasCompletionSignal(text) {
  const lower = String(text || '').toLowerCase();
  return [
    '图片已创建',
    '生成的图片已就绪',
    'image created',
    'image is ready',
    'created image',
    'your image is ready'
  ].some((k) => lower.includes(k.toLowerCase()));
}

function hasInProgressSignal(text) {
  const lower = String(text || '').toLowerCase();
  return [
    '正在创建图片',
    '正在生成图片',
    '图片生成中',
    'creating image',
    'generating image',
    'rendering',
    'processing image'
  ].some((k) => lower.includes(k.toLowerCase()));
}

function uniqueImageUrls(urls) {
  const seen = new Set();
  const out = [];
  for (const raw of Array.isArray(urls) ? urls : []) {
    const url = String(raw || '').trim();
    if (!url || seen.has(url)) continue;
    seen.add(url);
    out.push(url);
  }
  return out;
}

function freshImageUrls(state, baselineUrls) {
  const urls = Array.isArray(state?.imageUrls) ? state.imageUrls : [];
  return uniqueImageUrls(urls.filter((u) => !baselineUrls.has(u)));
}

function hasActiveGenerationControl(buttonNames) {
  const names = Array.isArray(buttonNames)
    ? buttonNames.map((name) => String(name || '').toLowerCase())
    : [];
  return names.some((name) => (
    name.includes('stop generating')
    || name.includes('cancel generation')
    || name.includes('停止生成')
    || name.includes('停止回应')
    || name.includes('停止回答')
  ));
}

function inferExtensionFromContentType(contentType) {
  const ct = String(contentType || '').toLowerCase();
  if (ct.includes('jpeg') || ct.includes('jpg')) return '.jpg';
  if (ct.includes('webp')) return '.webp';
  if (ct.includes('gif')) return '.gif';
  if (ct.includes('png')) return '.png';
  return '.bin';
}

async function fetchImageBase64(cdp, imageUrl) {
  const payload = await cdp.evaluate(`(async () => {
    const url = ${JSON.stringify(imageUrl)};
    const resp = await fetch(url, { credentials: 'include' });
    if (!resp.ok) {
      throw new Error('image fetch failed: ' + resp.status + ' ' + resp.statusText);
    }
    const contentType = resp.headers.get('content-type') || 'application/octet-stream';
    const buf = await resp.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let binary = '';
    const step = 0x4000;
    for (let i = 0; i < bytes.length; i += step) {
      binary += String.fromCharCode(...bytes.slice(i, i + step));
    }
    return {
      contentType,
      bytes: bytes.length,
      base64: btoa(binary)
    };
  })()`);
  if (!payload || !payload.base64) {
    throw new Error('No image payload returned from page fetch');
  }
  return payload;
}

async function cmdHealth(payload) {
  const defaults = gptBrowserDefaults();
  const port = Number(payload.port || defaults.port);
  const userDataDir = payload.userDataDir || defaults.userDataDir;
  const startupUrl = payload.startupUrl || 'https://chatgpt.com/';
  const { target } = await ensureBrowserSession({ port, userDataDir, startupUrl });
  const cdp = new CdpClient(target.webSocketDebuggerUrl);
  try {
    await cdp.connect();
    await navigateToChatGPT(cdp, startupUrl);
    const state = await pageState(cdp);
    return {
      ok: true,
      backend: 'cdp',
      port,
      userDataDir,
      title: state.title,
      url: state.url,
      loginRequired: isLoginRequired(state.text)
    };
  } finally {
    await cdp.close();
  }
}

async function cmdGenerate(payload) {
  const defaults = gptBrowserDefaults();
  const port = Number(payload.port || defaults.port);
  const userDataDir = payload.userDataDir || defaults.userDataDir;
  const startupUrl = payload.startupUrl || 'https://chatgpt.com/';
  const outputPath = payload.outputPath;
  const prompt = String(payload.prompt || '');
  const genTimeoutMs = Number(payload.genTimeoutMs || 420000);

  if (!outputPath) throw new Error('outputPath is required');
  if (!prompt.trim()) throw new Error('prompt is required');

  const { target } = await ensureBrowserSession({ port, userDataDir, startupUrl });
  const cdp = new CdpClient(target.webSocketDebuggerUrl);

  try {
    await cdp.connect();
    await navigateToChatGPT(cdp, startupUrl);

    const baseline = await pageState(cdp);
    if (isLoginRequired(baseline.text)) {
      throw new Error('GPT worker 未登录 chatgpt.com，请先在 GPT 浏览器 profile 完成登录');
    }

    const baselineUrls = new Set(baseline.imageUrls || []);
    await submitPrompt(cdp, prompt);
    await sleep(1500);

    const deadline = Date.now() + genTimeoutMs;
    let finalUrl = null;
    let finalUrls = [];
    let candidateUrls = [];
    let candidateKey = '';
    let stablePolls = 0;
    let quotaPolls = 0;

    while (Date.now() < deadline) {
      const state = await pageState(cdp);
      const refusal = detectRefusal(state.text);
      if (refusal) {
        throw new Error(`模型返回拒绝文本：${refusal}`);
      }

      const fresh = freshImageUrls(state, baselineUrls);
      const inProgressTextNow = hasInProgressSignal(state.text);
      const inProgressUiNow = hasActiveGenerationControl(state.buttonNames);
      if (isQuotaLimited(state.text) && fresh.length === 0 && candidateUrls.length === 0 && !inProgressTextNow && !inProgressUiNow) {
        quotaPolls += 1;
        if (quotaPolls >= 3) {
          throw new Error('ChatGPT 图片额度已达上限，请稍后重试');
        }
      } else {
        quotaPolls = 0;
      }

      if (fresh.length > 0) {
        const freshKey = fresh.join('\n');
        if (freshKey === candidateKey) {
          stablePolls += 1;
        } else {
          candidateKey = freshKey;
          candidateUrls = fresh;
          stablePolls = 1;
        }

        const done = hasCompletionSignal(state.text);
        const inProgressText = hasInProgressSignal(state.text);
        const inProgressUi = hasActiveGenerationControl(state.buttonNames);
        const allowStableFallback = stablePolls >= 5 && !inProgressUi;

        if (candidateUrls.length > 0 && stablePolls >= 3 && ((done && !inProgressUi) || allowStableFallback)) {
          await sleep(4500);
          const settled = await pageState(cdp);
          const settledFresh = freshImageUrls(settled, baselineUrls);
          const settledKey = settledFresh.join('\n');
          const settledDone = hasCompletionSignal(settled.text);
          const settledInProgressText = hasInProgressSignal(settled.text);
          const settledInProgressUi = hasActiveGenerationControl(settled.buttonNames);
          const settledStable = settledFresh.length > 0 && settledKey === candidateKey;
          const settledAllowByStability = stablePolls >= 5 && !settledInProgressUi;

          if (settledStable && ((settledDone && !settledInProgressUi) || (!settledInProgressUi && (!settledInProgressText || settledAllowByStability)))) {
            finalUrls = settledFresh;
            finalUrl = finalUrls[finalUrls.length - 1] || null;
            break;
          }

          if (settledFresh.length > 0) {
            candidateKey = settledKey;
            candidateUrls = settledFresh;
            stablePolls = 1;
          }
        }
      }

      await sleep(3000);
    }

    if (!finalUrl && candidateUrls.length > 0) {
      const settleTail = await pageState(cdp);
      const tailFresh = freshImageUrls(settleTail, baselineUrls);
      const tailInProgressUi = hasActiveGenerationControl(settleTail.buttonNames);
      if (tailFresh.length > 0 && !tailInProgressUi) {
        finalUrls = tailFresh;
        finalUrl = finalUrls[finalUrls.length - 1] || null;
      }
    }

    if (!finalUrl) {
      if (candidateUrls.length > 0) {
        throw new Error('等待生成图片超时（检测到图片中间态，但未等到稳定完成态）');
      }
      throw new Error('等待生成图片超时（未检测到新图片链接）');
    }

    const orderedUrls = finalUrls.length > 0 ? finalUrls : candidateUrls;
    const primaryUrl = orderedUrls[orderedUrls.length - 1];
    const prioritizedUrls = [primaryUrl, ...orderedUrls.filter((u) => u !== primaryUrl)];
    const downloadedImages = [];

    for (const url of prioritizedUrls) {
      let image = null;
      for (let retry = 0; retry < 3; retry += 1) {
        try {
          image = await fetchImageBase64(cdp, url);
          if (image && image.bytes >= 24 * 1024) break;
        } catch {}
        await sleep(1200);
      }
      if (image && image.base64) {
        downloadedImages.push({ url, ...image });
      }
    }

    if (downloadedImages.length === 0) {
      throw new Error('检测到图片链接，但下载图片失败');
    }

    const primaryImage = downloadedImages[0];
    fs.mkdirSync(path.dirname(outputPath), { recursive: true });
    fs.writeFileSync(outputPath, Buffer.from(primaryImage.base64, 'base64'));

    const outputStem = path.parse(outputPath).name;
    const outputDir = path.dirname(outputPath);
    const outputPaths = [];
    const images = [];

    for (let i = 0; i < downloadedImages.length; i += 1) {
      const item = downloadedImages[i];
      const ext = inferExtensionFromContentType(item.contentType);
      const numberedPath = path.join(outputDir, `${outputStem}_${String(i + 1).padStart(2, '0')}${ext}`);
      fs.writeFileSync(numberedPath, Buffer.from(item.base64, 'base64'));
      outputPaths.push(numberedPath);
      images.push({
        index: i,
        url: item.url,
        outputPath: numberedPath,
        contentType: item.contentType,
        bytes: item.bytes
      });
    }

    return {
      ok: true,
      backend: 'cdp',
      port,
      userDataDir,
      imageUrl: primaryUrl,
      imageUrls: prioritizedUrls,
      imageCount: downloadedImages.length,
      outputPaths,
      images,
      outputPath,
      contentType: primaryImage.contentType,
      bytes: primaryImage.bytes
    };
  } finally {
    await cdp.close();
  }
}

async function main() {
  const raw = await readStdin();
  const payload = raw.trim() ? JSON.parse(raw) : {};
  const action = payload.action || 'health';

  let result;
  if (action === 'health') result = await cmdHealth(payload);
  else if (action === 'generate') result = await cmdGenerate(payload);
  else throw new Error(`unknown action: ${action}`);

  process.stdout.write(JSON.stringify(result));
}

main().catch((err) => {
  process.stderr.write(String(err && err.stack ? err.stack : err));
  process.exit(1);
});

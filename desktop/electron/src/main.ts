import { app, BrowserWindow, dialog, ipcMain, session, shell } from 'electron';
import { autoUpdater } from 'electron-updater';
import { ChildProcess, spawn, spawnSync } from 'node:child_process';
import {
  accessSync,
  chmodSync,
  constants,
  copyFileSync,
  createWriteStream,
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  statSync,
  unlinkSync,
} from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { randomBytes } from 'node:crypto';

type ServiceName = 'server' | 'sidecar';

interface ServiceProcess {
  child: ChildProcess;
  name: ServiceName;
}

interface ReleaseConfiguration {
  update_url?: string;
  upscale_manifest_url?: string;
}

type UpdateState = 'idle' | 'checking' | 'current' | 'available' | 'downloaded' | 'installing' | 'error';

interface DesktopUpdateStatus {
  state: UpdateState;
  currentVersion: string;
  version: string;
  releaseName: string;
  releaseDate: string;
  releaseUrl: string;
  error: string;
  canInstall: boolean;
}

interface DownloadedDesktopUpdate {
  filePath: string;
  version: string;
  sha512: string;
  size: number;
}

interface CustomUpdateState {
  status?: string;
  expected_version?: string;
  target_app?: string;
  backup_app?: string;
  error?: string;
}

const APP_VERSION = '26.2.1';
const PROJECT_ROOT = path.resolve(__dirname, '../../..');
const services: ServiceProcess[] = [];
let mainWindow: BrowserWindow | null = null;
let startupWindow: BrowserWindow | null = null;
let quitting = false;
let installStarted = false;
let downloadedUpdate: DownloadedDesktopUpdate | null = null;
let updateStatus: DesktopUpdateStatus = {
  state: 'idle',
  currentVersion: APP_VERSION,
  version: '',
  releaseName: '',
  releaseDate: '',
  releaseUrl: '',
  error: '',
  canInstall: false,
};

function randomSecret(prefix: string): string {
  return `${prefix}${randomBytes(32).toString('base64url')}`;
}

function getFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      const port = typeof address === 'object' && address ? address.port : 0;
      server.close(error => error ? reject(error) : resolve(port));
    });
  });
}

function desktopPaths() {
  const dataDir = path.resolve(process.env.CANVASHUB_DESKTOP_DATA_DIR || app.getPath('userData'));
  const resourceDir = app.isPackaged
    ? path.join(process.resourcesPath, 'app-resources')
    : PROJECT_ROOT;
  const logsDir = path.join(dataDir, 'logs');
  mkdirSync(logsDir, { recursive: true });
  mkdirSync(path.join(dataDir, 'components', 'upscale'), { recursive: true });
  mkdirSync(path.join(dataDir, 'downloads'), { recursive: true });
  return { dataDir, resourceDir, logsDir };
}

function loadReleaseConfiguration(): ReleaseConfiguration {
  const configPath = app.isPackaged
    ? path.join(process.resourcesPath, 'release-config.json')
    : path.join(PROJECT_ROOT, 'desktop', 'electron', 'app-dist', 'release-config.json');
  try {
    const parsed = JSON.parse(readFileSync(configPath, 'utf8')) as unknown;
    return parsed && typeof parsed === 'object' ? parsed as ReleaseConfiguration : {};
  } catch {
    return {};
  }
}

function currentMacAppPath(): string {
  return path.resolve(path.dirname(app.getPath('exe')), '../..');
}

function customUpdateStatePath(dataDir: string): string {
  return path.join(dataDir, 'updater', 'update-state.json');
}

function isSafeUpdateBackup(targetApp: string, backupApp: string): boolean {
  const target = path.resolve(targetApp);
  const backup = path.resolve(backupApp);
  const expectedPrefix = `.${path.basename(target)}.backup-`;
  return path.dirname(backup) === path.dirname(target)
    && path.basename(backup).startsWith(expectedPrefix);
}

function reconcileCustomUpdate(dataDir: string): string {
  if (!app.isPackaged || process.platform !== 'darwin') return '';
  const statePath = customUpdateStatePath(dataDir);
  if (!existsSync(statePath)) return '';
  try {
    const state = JSON.parse(readFileSync(statePath, 'utf8')) as CustomUpdateState;
    if (state.status === 'installed'
      && state.expected_version === APP_VERSION
      && path.resolve(String(state.target_app || '')) === currentMacAppPath()) {
      const backupApp = String(state.backup_app || '');
      if (backupApp && isSafeUpdateBackup(currentMacAppPath(), backupApp) && existsSync(backupApp)) {
        rmSync(backupApp, { recursive: true, force: true });
      }
      unlinkSync(statePath);
      return '';
    }
    if (state.status === 'failed') {
      unlinkSync(statePath);
      return String(state.error || '自定义更新助手未能完成安装');
    }
  } catch {
    return '';
  }
  return '';
}

function githubReleasePageUrl(updateUrl: string): string {
  try {
    const parsed = new URL(updateUrl);
    if (parsed.hostname === 'github.com' && parsed.pathname.endsWith('/releases/latest/download')) {
      parsed.pathname = parsed.pathname.slice(0, -'/download'.length);
      return parsed.toString().replace(/\/$/, '');
    }
  } catch {
    return updateUrl;
  }
  return updateUrl;
}

function publishUpdateStatus(patch: Partial<DesktopUpdateStatus>): void {
  updateStatus = { ...updateStatus, ...patch };
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('desktop:update-status', updateStatus);
  }
}

function runtimeCommand(command: ServiceName, port: number, paths: ReturnType<typeof desktopPaths>) {
  const commonArgs = [command, '--port', String(port), '--resource-dir', paths.resourceDir, '--data-dir', paths.dataDir];
  if (app.isPackaged) {
    const executable = process.platform === 'win32'
      ? path.join(process.resourcesPath, 'runtime', 'canvashub-runtime.exe')
      : path.join(process.resourcesPath, 'runtime', 'canvashub-runtime');
    return { executable, args: commonArgs };
  }
  const python = process.env.CANVASHUB_DEV_PYTHON
    || (process.platform === 'win32'
      ? path.join(PROJECT_ROOT, '.venv-desktop', 'Scripts', 'python.exe')
      : path.join(PROJECT_ROOT, '.venv-desktop', 'bin', 'python'));
  return { executable: python, args: ['-m', 'backend.desktop_runtime', ...commonArgs] };
}

function startService(
  name: ServiceName,
  port: number,
  paths: ReturnType<typeof desktopPaths>,
  sharedEnv: NodeJS.ProcessEnv,
): ChildProcess {
  const command = runtimeCommand(name, port, paths);
  const log = createWriteStream(path.join(paths.logsDir, `${name}.log`), { flags: 'a' });
  const child = spawn(command.executable, command.args, {
    cwd: paths.resourceDir,
    env: sharedEnv,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  child.stdout?.pipe(log, { end: false });
  child.stderr?.pipe(log, { end: false });
  child.on('error', error => log.write(`\n[desktop] process error: ${String(error)}\n`));
  child.on('exit', (code, signal) => {
    log.write(`\n[desktop] exited code=${String(code)} signal=${String(signal)}\n`);
    log.end();
    if (!quitting && mainWindow && !mainWindow.isDestroyed()) {
      dialog.showMessageBox(mainWindow, {
        type: 'error',
        title: 'CanvasHub 服务已停止',
        message: `${name} 服务意外退出`,
        detail: `退出码：${String(code)}。日志位于 ${paths.logsDir}`,
      }).catch(() => undefined);
    }
  });
  services.push({ child, name });
  return child;
}

async function waitForUrl(url: string, child: ChildProcess, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastError = '';
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`服务已退出，退出码 ${child.exitCode}`);
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(1500) });
      if (response.status >= 200 && response.status < 500) return;
      lastError = `HTTP ${response.status}`;
    } catch (error) {
      lastError = String(error);
    }
    await new Promise(resolve => setTimeout(resolve, 350));
  }
  throw new Error(`等待服务超时：${url}\n${lastError}`);
}

function createStartupWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 420,
    height: 240,
    frame: false,
    resizable: false,
    show: false,
    backgroundColor: '#202628',
    webPreferences: { sandbox: true },
  });
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>
    html,body{height:100%;margin:0}body{display:grid;place-items:center;background:#202628;color:#edf2f3;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;letter-spacing:0}
    main{text-align:center}strong{display:block;font-size:24px;margin-bottom:14px}.bar{width:180px;height:3px;overflow:hidden;background:#384144;border-radius:2px}.bar:after{display:block;width:42%;height:100%;content:"";background:#ff6a22;animation:move 1.1s ease-in-out infinite}@keyframes move{0%{transform:translateX(-110%)}100%{transform:translateX(340%)}}p{font-size:12px;color:#aeb9bc}
  </style></head><body><main><strong>CanvasHub</strong><div class="bar"></div><p>正在启动本地服务...</p></main></body></html>`;
  window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
  window.once('ready-to-show', () => window.show());
  return window;
}

async function authenticateDesktopSession(baseUrl: string, password: string): Promise<void> {
  const response = await fetch(`${baseUrl}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  });
  const payload = await response.json() as { ok?: boolean; auth_token?: string; error?: string };
  if (!response.ok || !payload.ok || !payload.auth_token) {
    throw new Error(payload.error || `桌面会话登录失败：HTTP ${response.status}`);
  }
  await session.defaultSession.cookies.set({
    url: baseUrl,
    name: 'miniapp_auth',
    value: payload.auth_token,
    path: '/',
    httpOnly: true,
    sameSite: 'lax',
  });
}

function createMainWindow(baseUrl: string): BrowserWindow {
  const window = new BrowserWindow({
    width: 1440,
    height: 940,
    minWidth: 1180,
    minHeight: 720,
    show: false,
    backgroundColor: '#202628',
    title: 'CanvasHub',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url) && !url.startsWith(baseUrl)) shell.openExternal(url);
    return { action: 'deny' };
  });
  window.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith(baseUrl)) {
      event.preventDefault();
      if (/^https?:\/\//i.test(url)) shell.openExternal(url);
    }
  });
  window.loadURL(`${baseUrl}/desktop.html`);
  window.once('ready-to-show', () => {
    startupWindow?.close();
    startupWindow = null;
    window.maximize();
    window.show();
  });
  return window;
}

async function configureUpdater(updateUrl: string): Promise<void> {
  if (!app.isPackaged || !updateUrl) return;
  publishUpdateStatus({ releaseUrl: githubReleasePageUrl(updateUrl) });
  autoUpdater.on('checking-for-update', () => {
    publishUpdateStatus({ state: 'checking', error: '' });
  });
  autoUpdater.on('update-not-available', () => {
    downloadedUpdate = null;
    publishUpdateStatus({
      state: 'current',
      version: '',
      releaseName: '',
      releaseDate: '',
      error: '',
      canInstall: false,
    });
  });
  autoUpdater.on('update-available', info => {
    publishUpdateStatus({
      state: 'available',
      version: String(info.version || ''),
      releaseName: String(info.releaseName || ''),
      releaseDate: String(info.releaseDate || ''),
      error: '',
      canInstall: false,
    });
  });
  autoUpdater.on('update-downloaded', info => {
    const rawDownloadedFile = String(info.downloadedFile || '').trim();
    const downloadedFile = rawDownloadedFile ? path.resolve(rawDownloadedFile) : '';
    const downloadedName = path.basename(downloadedFile);
    const zipInfo = info.files.find(file => {
      try {
        return path.basename(new URL(file.url, 'https://updates.invalid/').pathname) === downloadedName;
      } catch {
        return false;
      }
    }) || info.files.find(file => String(file.url || '').toLowerCase().endsWith('.zip'));
    let downloadedSize = 0;
    try {
      const downloadedStat = statSync(downloadedFile);
      downloadedSize = downloadedStat.isFile() ? downloadedStat.size : 0;
    } catch {
      downloadedSize = 0;
    }
    const canInstall = process.platform === 'darwin'
      && downloadedSize > 0
      && !!zipInfo
      && !!String(zipInfo.sha512 || '')
      && downloadedSize === Number(zipInfo.size || 0);
    downloadedUpdate = canInstall && zipInfo ? {
      filePath: downloadedFile,
      version: String(info.version || ''),
      sha512: String(zipInfo.sha512 || ''),
      size: Number(zipInfo.size || 0),
    } : null;
    publishUpdateStatus({
      state: 'downloaded',
      version: String(info.version || ''),
      releaseName: String(info.releaseName || ''),
      releaseDate: String(info.releaseDate || ''),
      error: '',
      canInstall,
    });
  });
  autoUpdater.on('error', error => {
    const hasDownloadedUpdate = !!downloadedUpdate;
    publishUpdateStatus({
      state: hasDownloadedUpdate ? 'downloaded' : 'error',
      error: String(error?.message || error || ''),
      canInstall: hasDownloadedUpdate,
    });
  });
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = process.platform !== 'darwin';
  autoUpdater.setFeedURL({ provider: 'generic', url: updateUrl });
  await autoUpdater.checkForUpdates().catch(() => undefined);
}

async function bootstrap(): Promise<void> {
  const paths = desktopPaths();
  const releaseConfig = loadReleaseConfiguration();
  startupWindow = createStartupWindow();
  const [serverPort, sidecarPort] = await Promise.all([getFreePort(), getFreePort()]);
  const desktopPassword = randomSecret('desktop-');
  const poolKey = randomSecret('sk-local-desktop-');
  const updateUrl = String(
    process.env.CANVASHUB_UPDATE_URL
    || releaseConfig.update_url
    || ''
  ).trim().replace(/\/+$/, '');
  const upscaleManifestUrl = String(
    process.env.CANVASHUB_UPSCALE_MANIFEST_URL
    || releaseConfig.upscale_manifest_url
    || (updateUrl ? `${updateUrl}/upscale-manifest.json` : '')
  ).trim();
  const sharedEnv: NodeJS.ProcessEnv = {
    ...process.env,
    CANVASHUB_APP_VERSION: APP_VERSION,
    CANVASHUB_RESOURCE_DIR: paths.resourceDir,
    CANVASHUB_DATA_DIR: paths.dataDir,
    APP_SETTINGS_PATH: path.join(paths.dataDir, 'settings.json'),
    TASKS_DB_PATH: path.join(paths.dataDir, 'tasks.db'),
    IMAGE_ARCHIVE_DIR: path.join(paths.dataDir, 'archive'),
    SOURCE_IMAGE_DIR: path.join(paths.dataDir, 'source_images'),
    UPSCALE_MODEL_DIR: path.join(paths.dataDir, 'components', 'upscale', 'current', 'models'),
    CANVASHUB_UPSCALE_COMPONENT_DIR: path.join(paths.dataDir, 'components', 'upscale'),
    CHATGPT_POOL_HOST: '127.0.0.1',
    CHATGPT_POOL_PORT: String(sidecarPort),
    CHATGPT_POOL_BASE_URL: `http://127.0.0.1:${sidecarPort}`,
    CHATGPT_POOL_DB: path.join(paths.dataDir, 'chatgpt_pool', 'accounts.db'),
    CHATGPT_POOL_AUTH_KEY: poolKey,
    MINIAPP_ACCESS_PASSWORD: desktopPassword,
    MINIAPP_PUBLIC_MODE: '0',
    PYTHONUNBUFFERED: '1',
    PYTHONUTF8: '1',
  };
  if (upscaleManifestUrl) sharedEnv.CANVASHUB_UPSCALE_MANIFEST_URL = upscaleManifestUrl;

  const sidecar = startService('sidecar', sidecarPort, paths, sharedEnv);
  await waitForUrl(`http://127.0.0.1:${sidecarPort}/health`, sidecar, 45_000);
  const server = startService('server', serverPort, paths, sharedEnv);
  const baseUrl = `http://127.0.0.1:${serverPort}`;
  await waitForUrl(`${baseUrl}/desktop.html`, server, 90_000);
  await authenticateDesktopSession(baseUrl, desktopPassword);
  mainWindow = createMainWindow(baseUrl);
  const customUpdateError = reconcileCustomUpdate(paths.dataDir);
  if (customUpdateError) {
    mainWindow.once('ready-to-show', () => {
      if (!mainWindow || mainWindow.isDestroyed()) return;
      dialog.showMessageBox(mainWindow, {
        type: 'error',
        title: 'CanvasHub 更新失败',
        message: '自动更新未能完成，已保留原版本',
        detail: `${customUpdateError}\n日志位于 ${path.join(paths.logsDir, 'updater.log')}`,
      }).catch(() => undefined);
    });
  }
  configureUpdater(updateUrl).catch(() => undefined);
}

function stopServices(): void {
  for (const service of services.splice(0)) {
    const pid = service.child.pid;
    if (!pid || service.child.exitCode !== null) continue;
    if (process.platform === 'win32') {
      spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true });
    } else {
      service.child.kill('SIGTERM');
    }
  }
}

ipcMain.handle('desktop:open-external', async (_event, rawUrl: unknown) => {
  const url = String(rawUrl || '').trim();
  if (!/^https?:\/\//i.test(url)) throw new Error('Unsupported external URL');
  await shell.openExternal(url);
  return true;
});

ipcMain.handle('desktop:get-update-status', () => ({ ...updateStatus }));

ipcMain.handle('desktop:install-update', async () => {
  if (!app.isPackaged || process.platform !== 'darwin') {
    throw new Error('当前运行方式不支持自定义自动安装');
  }
  if (installStarted) {
    return { ok: true };
  }
  if (!downloadedUpdate || updateStatus.state !== 'downloaded') {
    throw new Error('新版尚未下载完成');
  }

  const paths = desktopPaths();
  const targetApp = currentMacAppPath();
  const targetParent = path.dirname(targetApp);
  const bundledHelper = path.join(process.resourcesPath, 'updater', 'canvashub-updater');
  if (!existsSync(bundledHelper)) {
    throw new Error('安装包中缺少自定义更新助手');
  }
  if (!existsSync(downloadedUpdate.filePath)
    || statSync(downloadedUpdate.filePath).size !== downloadedUpdate.size) {
    throw new Error('已下载的更新文件不完整，请重新启动应用后再试');
  }
  try {
    accessSync(targetParent, constants.W_OK);
  } catch {
    throw new Error(`没有权限更新 ${targetApp}，请将 CanvasHub 移到可写的 Applications 目录`);
  }

  const helperDir = path.join(paths.dataDir, 'updater');
  const helperPath = path.join(helperDir, 'canvashub-updater');
  mkdirSync(helperDir, { recursive: true });
  copyFileSync(bundledHelper, helperPath);
  chmodSync(helperPath, 0o755);

  const args = [
    '--parent-pid', String(process.pid),
    '--archive', downloadedUpdate.filePath,
    '--target-app', targetApp,
    '--expected-version', downloadedUpdate.version,
    '--expected-sha512', downloadedUpdate.sha512,
    '--expected-size', String(downloadedUpdate.size),
    '--state-file', customUpdateStatePath(paths.dataDir),
    '--log-file', path.join(paths.logsDir, 'updater.log'),
  ];
  await new Promise<void>((resolve, reject) => {
    const child = spawn(helperPath, args, {
      detached: true,
      stdio: 'ignore',
      env: {
        HOME: app.getPath('home'),
        LANG: process.env.LANG || 'en_US.UTF-8',
        PATH: '/usr/bin:/bin:/usr/sbin:/sbin',
      },
    });
    child.once('error', reject);
    child.once('spawn', () => {
      child.unref();
      resolve();
    });
  }).catch(error => {
    publishUpdateStatus({
      state: 'downloaded',
      error: String(error?.message || error || ''),
      canInstall: true,
    });
    throw error;
  });

  installStarted = true;
  publishUpdateStatus({ state: 'installing', error: '', canInstall: false });
  setTimeout(() => app.quit(), 250).unref();
  return { ok: true };
});

const hasInstanceLock = app.requestSingleInstanceLock();
if (!hasInstanceLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });
  app.on('before-quit', () => {
    quitting = true;
    stopServices();
  });
  app.on('window-all-closed', () => app.quit());
  app.whenReady().then(bootstrap).catch(async error => {
    stopServices();
    startupWindow?.close();
    await dialog.showMessageBox({
      type: 'error',
      title: 'CanvasHub 启动失败',
      message: '本地服务未能启动',
      detail: String(error?.stack || error),
    });
    app.quit();
  });
}

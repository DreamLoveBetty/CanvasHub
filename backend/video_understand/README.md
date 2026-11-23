# Video Understanding Domain (WeMM-Video MLX)

Apple Silicon 本地全模态视频理解领域，基于 [Tencent/WeMM-Video](https://github.com/Tencent/WeMM-Video) 与 [vanch007/mlx-wemm-video](https://github.com/vanch007/mlx-wemm-video)（默认对接 `vanch007/WeMM-Video-35BA3B-mlx-6bit`）。

## 边界与装配

- `contracts.py`：有界 `snake_case` 参数与 5 种预设模式（`storyboard` / `prompt_reverse` / `h3_prompt` / `summary` / `custom`），无 I/O。
- `prompts.py`：五种预设模式的提示词组装与切镜时间锚点模板（含 MiniMax H3 多模态反推规范）。
- `environment.py`：显式准备与状态检查。隔离环境在 `APP_DATA_DIR/components/video-understand/venv/`（Python 3.12，`requirements.lock` 哈希锁定、`--no-deps`、无 PyTorch）；固定版本源码在 `src/`；默认 6-bit 权重在 `assets/wemm-video-35ba3b-mlx-6bit/`，也支持 CLI `--model-dir` 只读绑定本地 4/6/8-bit 目录。
- `storage.py`：任务记录持久化在 `APP_DATA_DIR/data/video-understand/jobs.sqlite3`，服务重启后未完成任务标记为 `interrupted`。
- `runtime.py` / `worker.py`：每次任务启动一次性隔离 Python 3.12 子进程，通过 `pass_fds` 继承共享 `components/.local-inference.lock` 租约，执行前调用 `before_load` 触发 `IdleWorkerCoordinator` 释放常驻本地模型，任务结束即退出并完全归还统一内存。HTTP 进程绝不导入 `mlx` / `mlx_vlm` / `cv2`。
- `service.py`：串行队列（最多 8 个活跃任务）、复用 `video_edit.sources.SourceResolver` 解析同源画布视频 URL、流式 SHA-256 + 参数内容缓存、任务状态与取消。
- `routes/video_understand_routes.py`：薄认证 HTTP 适配器，不放行任意本机路径。

## 安装与准备

在设置中心「模型工具 → 通用工具」点击一键准备，或在命令行显式准备：

```bash
PYTHONPATH="$PWD" .venv/bin/python -m backend.video_understand.environment status
PYTHONPATH="$PWD" .venv/bin/python -m backend.video_understand.environment prepare
# 或只读绑定已有的本地 WeMM-Video MLX 4/6/8-bit 目录：
PYTHONPATH="$PWD" .venv/bin/python -m backend.video_understand.environment prepare --model-dir /path/to/WeMM-Video-35BA3B-mlx-6bit
```

依赖系统 `ffmpeg`、`ffprobe` 与 `uv`；源码与模型不在服务器启动时自动下载。

## 接口

- `GET /api/video_understand/status`
- `POST /api/video_understand/prepare`（202）
- `POST /api/video_understand/submit`
- `GET /api/video_understand/job?id=...`
- `POST /api/video_understand/cancel`
- `GET /api/video_understand/artifact?id=...&name=...`

## 验证边界

- 离线可移植回归：`tests/test_video_understand.py`、`tests/test_video_understand.cjs`（使用假 worker 与合成目录，不依赖真实 31.4 GB 权重或联网）。
- 依赖锁更新：`MACOSX_DEPLOYMENT_TARGET=14.0 uv pip compile --generate-hashes --no-config --python-version 3.12 --python-platform aarch64-apple-darwin -o backend/video_understand/requirements.lock -`。

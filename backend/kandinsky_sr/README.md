# Kandinsky ImageSR 2.0 域

Kandinsky ImageSR 2.0（`2x` / `4x` 单步扩散生成式图像超分）的独立运行域。HTTP 进程不导入 PyTorch、Diffusers 或 Transformers，所有推理均在隔离的 Python 3.12 虚拟环境中单次执行，任务结束即释放统一内存。

## 模块边界

| 文件 | 职责 | 依赖 |
|---|---|---|
| `contracts.py` | 常量、参数校验（`upscale_factor`/`creativity`/`overlap`）、分块估算 | 标准库 |
| `assets.lock.json` | 固定 GitHub 推理源码与 HuggingFace 权重清单（revision、大小、校验值） | 数据文件 |
| `requirements.lock` | 隔离环境哈希锁定依赖（`diffusers>=0.41`、`transformers>=5.20`、`torch`） | 锁定文件 |
| `environment.py` | 用户触发的显式准备、本地目录校验、`status`/`prepare` CLI | `app_config`、`local_image.downloads`、`contracts` |
| `worker.py` | 仅在 `components/kandinsky-sr/venv` 内运行的 MPS/CUDA/CPU 推理进程 | `torch`、`diffusers`、`kandinsky_image_sr`、`Pillow` |
| `runtime.py` | 持有 `.local-inference.lock` 与 `before_load` 卸载钩子的子进程监督器 | `runtime_resources`、`local_image.runtime`、`environment` |
| `service.py` | `Preparation` 生命周期管理与 `EnhancementEngine` 适配器 | `local_image.preparation`、`services.image_enhancement` |

## 准备与恢复

准备由用户在设置中心「模型工具」显式触发，生成期间完全离线（`HF_HUB_OFFLINE=1`）：

```bash
PYTHONPATH="$PWD" .venv/bin/python -m backend.kandinsky_sr.environment prepare
PYTHONPATH="$PWD" .venv/bin/python -m backend.kandinsky_sr.environment status
```

- 如已提前下载权重目录，可通过 `--model-dir <目录>` 只读绑定并校验。
- 隔离环境位于 `APP_DATA_DIR/components/kandinsky-sr/`（`venv/`、`src/`、`assets/kandinsky-imagesr-2.0/`、`installed.json`）。
- 若需更新依赖锁，执行：
  `MACOSX_DEPLOYMENT_TARGET=14.0 uv pip compile --generate-hashes --no-config --python-version 3.12 --python-platform aarch64-apple-darwin -o backend/kandinsky_sr/requirements.lock -`

## 验收与故障恢复

- 稳定离线回归：`tests/test_kandinsky_sr_domain.py` 与 `tests/test_kandinsky_sr_canvas.cjs`，不依赖权重下载与 GPU。
- M2 Max 实测与 UI 验证结果保留在被忽略目录 `tests/output/`。

# ReShot video control

独立本地视频预处理领域。第一版：视频 → Depth / Pose / Canny → 视频结果。
不调用音频 Provider、图像生成或账号池；不启动 ReShot WebUI。

## 边界与装配

- `contracts.py`：有界 snake_case 参数；不接受模型路径、命令、任意输入 URL。
- `storage.py`：独立素材文件与 SQLite 任务记录，服务重启后将未完成任务标记为中断。
- `service.py`：串行队列（最多 8 个未结束任务）、任务状态/取消、处理缓存及产物清单。缓存包含输入字节、有效参数、引擎版本、模型内容指纹。
- `runtime.py` / `worker.py`：主环境内的独立子进程；离线模型加载、真实阶段事件、日志限额、30 分钟上限、取消与父进程退出清理。HTTP 进程不导入 Torch/ONNX/ReShot。
- `pose_quality.py`：worker 编码后检查骨骼视频可见帧覆盖率（像素亮度 >32、数量至少 max(20, 面积×0.01%)），不足 10% 判失败，不发布黑片；10%–80% 在底部日志提示缺帧。覆盖率只代表可见内容，不代表姿态准确，不自动猜测漏检骨骼。诊断写入 metrics 的 pose_coverage；引擎缓存版本更新使旧黑片不再被复用。
- `install.py` / `requirements-py314.txt`：显式安装、固定依赖及模型校验。不在服务器启动时自动安装或下载。
- `routes/video_control_routes.py`：受保护 HTTP 适配。`routes/artifact_response.py` 提供中立的文件 Range 响应，音频也使用这一 HTTP 工具，不反向依赖视频领域。
- `server.py` 仅装配 `APP_DATA_DIR`、runtime、service、router。
- `runtime_resources.py` 是协作式本机资源租约，音频和 ReShot runtime 在启动 worker 前获取它；排队可取消。它不声称接管远程 H3 或已有 Upscale 的调度。

## 安装与持久化

复用主 macOS Python 3.14 虚拟环境与系统 FFmpeg / ffprobe，安装时锁住全部已有包版本，不升级/降级音频依赖：

```sh
.venv/bin/python -m backend.video_control.install --models-from /absolute/path/to/verified-models
```

源目录需要以下固定权重，SHA-256 在安装模块中校验：

- `depth/video_depth_anything_vits.pth`（Video Depth Anything Small）
- `pose/yolox_l.onnx`
- `pose/dw-ll_ucoco_384.onnx`

安装结果在 `APP_DATA_DIR/components/reshot/`（源码运行默认项目根），素材及结果在
`APP_DATA_DIR/data/video-control/`。不放在一次性发布目录；这两个运行目录不版本化。
冻结桌面包的外置 Python 安装/定位尚未提供，本阶段验证的是源码运行的本地服务。

每个成功任务保留 `result/control.mp4`、`result/metrics.json`、`result/result.json`，任务目录另有
`request.json`、有界 `runtime.log`。原素材保持不变，预处理临时视频完成后删除。
画布使用受保护 URL，不把本机路径或凭据写到节点。完整资产库索引接入后续统一处理，不在节点提供任务历史面板。

## 接口

`/api/video_control/status`、`job?id=...`、`artifact?id=...&name=...`、`source?id=...` 为 GET；
`upload?name=...`、`submit`、`cancel` 为 POST。复用已有鉴权，素材和结果也需要鉴权。
上传为原始视频 bytes，最大 200 MB；仅 MP4/MOV/WebM/MKV 容器，通过本机 ffprobe 校验。
解码禁用网络协议，不接受播放列表；任务预处理最多截取前 30 秒、输出最长边 1280、24 fps。
界面默认前 15 秒、640 像素、fast、Small 模型。控制视频不保留音轨。

处理参数包括 `asset_id`、`control`、`quality`、`max_res`、`max_seconds`、`canny_low/high`、
`pose_hands/face`、`invert`。取消使用任务 `id`，已成功任务不会因取消而删除结果。
恢复轮询不自动重新运行中断任务。

## 前端与验证边界

加载顺序：`desktop-video-control-model.js` → `desktop-video-control-api.js` →
`desktop-video-control-view.js` → `desktop-canvas-video-control.js` → 画布装配。
状态/API/控制器/视图分开；图连接域通过 `DesktopCanvasConnections.combineDomains` 明确组合。
新类型 `video_control` 只接受 `video`，只输出到 `video`；结果携带 `controlMetadata`，
新增、恢复、工作流导出和兼容连线都使用独立类型。已完成结果可重新连接到新的结果节点。

共用系统视觉 token、72px 生成按钮壳、节点圆角。进度下挂、日志进底部、全局停止，
节点不显示堆栈/产物列表。阶段来自真实 reporter，没有伪造百分比/ETA。
换工作流或删除节点取消所属任务；普通页面刷新保留后端任务并恢复轮询。

H3 Runtime 本轮离线，**尚未接通下游参考视频/专用 ControlNet 推理**。连接了控制结果的 H3
生成请求会明确拒绝，避免现有首帧接口静默忽略控制输入。普通图生视频行为不变。
后续需在线验证实际接口、补齐参考视频上传与依赖执行链，再开放该能力。

可移植回归：`tests/test_video_control.py`、`tests/test_video_control.cjs`。
本机验收探针/报告在 `tests/local/reshot_*` 与 `tests/output/reshot-ui/`。
真实小合成视频已覆盖三种处理、结果播放/恢复；不等于真人姿态质量或长片内存压力验收。

2026-09-21 黑片排查：机甲角色原片 360 帧仅 4 帧有可见输出（1.1%）；检测器漏检而非编码故障。
加入 worker 覆盖检查及缓存失效，原片重跑确认拒绝近乎全黑结果，服务 API 的无人物合成片也返回失败且不发布产物。
不更改依赖包、不降低人物置信阈值、不自动伪造骨骼；当前模型仍可能无法处理机甲/局部特写。

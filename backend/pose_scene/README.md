# 姿态场景（SOMA 人偶）

姿态参考节点的后端领域：SOMA 人偶资产、人偶 GLB、导出图存放。
不做识别（第 2 期另立 `pose_capture/`），不调用图像 Provider，不启动外部程序。

## 边界与装配

- `contracts.py`：固定的 SOMA 来源（`nvidia/soma-x` v0.3.4，固定 revision 与 SHA-256）、精细度
  `low` / `mid`、输出通道名、导出图校验（PNG data URL、尺寸 ≤ 4096、≤ 24 MB、场景快照 ≤ 256 KB）。不接受路径或 URL。
- `glb.py`：只用 numpy，把骨架数组写成蒙皮 GLB（前 4 大权重，three.js 上限），并在
  `scenes[0].extras.soma` 写入编辑器摆姿势所需的关节名、父关节、T-pose 世界朝向和 Hips 位置。
- `convert.py`：安装时在子进程运行，用 `py-soma-x` 的 legacy 模式（78 关节纯 LBS）生成三种体型 × low / mid 共 6 个 GLB：
  中性（SOMA 中性）、女性 / 男性（Anny 成人：性别 1 / 0，年龄 0.75 = Anny 的 young 锚点，其余取平均）。
  每个 GLB 的 extras 另写 `body`、`head_end`（静止 HeadEnd 高于最低关节，米）和 `height_ratio`（相对中性）；
  编辑器按 `height_cm / 175 / height_ratio` 缩放，所以身高在各体型下含义相同。`rig_arrays` / `rest_height`
  也供识别 worker 生成识别体型。HTTP 进程不导入 SOMA、torch、warp 或 anny。
- `install.py` / `requirements-py314.txt`：显式安装，沿用 ReShot 的做法：锁住主环境所有已有包版本，
  只新增固定版本的转换依赖；SOMA 文件逐一校验 SHA-256。不在服务器启动时自动安装或下载。
- `storage.py`：导出图存 `APP_DATA_DIR/data/pose/exports/YYYY-MM-DD/<id>.png`，旁边的 `<id>.json`
  记录通道、机位、尺寸和场景快照，方便追溯和重现。
- `service.py`：状态（missing / outdated / incomplete / ready）、GLB 查找、导出存取。不回传本机路径。
- `video_export.py`：姿态视频。编辑器按固定时间步逐帧渲染（不用 MediaRecorder），按顺序上传帧到 `data/pose/videos/<id>/`；
  帧默认是画布原始 RGBA 经浏览器 `CompressionStream` 压缩（约 10–40 KB/帧、约 10 ms；嵌入式浏览器 PNG/JPEG 编码要 1–7 秒/帧），
  服务端解压时限定大小，再经管道喂给 ffmpeg 编 H.264（yuv420p、与源相同帧率）。成品写进 `IMAGE_ARCHIVE_DIR/YYYY-MM-DD/pose_<通道>_*.mp4`
  并附 JSON 旁注（通道、机位、帧数、场景快照），由既有的 `/video/` 路由（带 Range）提供，下游视频节点与其他生成视频一视同仁。
  `server.py` 注入 `storage_paths.daily_output_dir`；没有注入时视频导出关闭。帧在编码后删除，超过一天未完成的会话自动清理。
- `routes/pose_routes.py`：受保护 HTTP 适配；`server.py` 只注入组件目录和数据目录。

## 安装

```sh
.venv/bin/python -m backend.pose_scene.install                     # 从 Hugging Face 下载约 59 MB
.venv/bin/python -m backend.pose_scene.install --assets-from DIR   # 已下载的文件（逐一校验）
```

只需要 `SOMA_neutral.npz`、`SOMA_template_rig.usda`、`SOMA_procedural_transforms.json`、`LICENSE`，
以及 Anny 的 `Anny/base_body.obj`、`Anny/SOMA_wrap.obj`（同一 SOMA revision）。
主环境新增 `py-soma-x`、`warp-lang`、`usd-core`、`cholespy`、`rtree`、`trimesh`、`anny`、`roma`（固定版本），已有包不变。
Anny 生成时会缓存约 1 GB 可重建数据，转换器把 `ANNY_CACHE_DIR` 指到临时目录，结束即删除；
Anny 只有转 SMPL 才会下载的非商用数据，这里用不到。
结果在 `APP_DATA_DIR/components/pose-soma/`（`assets/`、`glb/`、`installed.json`），不放发布目录、不版本化。
转换器输出变化时提高 `GLB_VERSION`，旧安装会显示为 outdated。

中性体型的骨架由 SOMA 的身份模型计算（关节回归与朝向拟合），不是资产文件里的现成数据，
所以生成 GLB 需要 `py-soma-x`；与验证 A（`tests/local/pose_soma_spike/`）的参考 GLB 逐项比对一致。

## 接口

| 路由 | 方法 | 用途 |
|---|---|---|
| `/api/pose/assets/status` | GET | 人偶安装状态、版本、安装命令 |
| `/api/pose/glb?lod=low\|mid&body=neutral\|female\|male` | GET | 体型 GLB（未安装时 503）；识别体型由 `/api/pose_capture/body` 提供 |
| `/api/pose/export/image` | POST | `{image, pass, camera?, scene?}`，返回 `{id, url, width, height, pass}` |
| `/api/pose/export/artifact?id=` | GET | 导出图（Range 响应） |
| `/api/pose/export/video/start` | POST | `{frames, fps, width, height, format: rgba\|png\|jpeg, pass, camera?, scene?}` → 导出会话 |
| `/api/pose/export/video/frame?id=&index=` | POST | 第 index 帧的原始字节（必须按顺序） |
| `/api/pose/export/video/finish`、`cancel` | POST | `{id}`：开始编码 / 取消 |
| `/api/pose/export/video/job?id=` | GET | 状态；完成时 `url` 为 `/video/<文件名>` |

全部走现有鉴权。下游节点通过受保护 URL 读取导出图，与其他参考图相同。

## 第一版限制

- 体型只有三个预设；年龄、胖瘦、肌肉等 Anny 连续参数未开放。
- 纯 LBS 与完整 SOMA（扭转骨 + 姿势修正）在深蹲、弯肘时轮廓有差异，关节位置不受影响（第 5 期补）。

可移植回归：`tests/test_pose_scene.py`。

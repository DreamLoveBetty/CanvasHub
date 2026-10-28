# 姿态识别（GEM-X 精简版）

姿态参考节点的识别领域：从照片或视频识别人物动作，输出 SOMA 77 关节的姿势序列（`docs/POSE_REFERENCE_REBUILD_PLAN.md` §4.1），
由画布转换成可编辑的人偶、照片 / 视频机位；视频结果是逐帧序列，编辑器用时间轴播放与修正。

## 边界与装配

- `contracts.py`：固定的 GEM-X 源码（`NVlabs/GEM-X` commit `3299255`）、HF 权重 revision、SOMA 0.1.3 资产（NVlabs/SOMA-X LFS）
  和 YOLOX，每个文件的大小与 SHA-256；上传与请求限制（PNG/JPEG/WebP ≤ 20 MB、≤ 4000 万像素、最多 6 人；
  视频 MP4/MOV/WebM ≤ 200 MB 以文件头识别，只识别前 30 秒，最多 4 人）。模式由素材种类决定，不听客户端。
- `engine.py`：**只在 worker 子进程导入**。照片流程：YOLOX 找出所有人 → 每人一次 VitPose（翻转测试、RGB 输入，等同 GEM-X PR #21）
  → 关键点复制成 32 帧静态片段 → GEM 去噪器 50 步 DDIM → 取中间帧 → 关键点贴合（`refine.py`）。全程 CPU，不需要 CoreML 编译。
  GEM-X 写死 CUDA 的地方在 `_prepare_runtime` 明确改到 CPU；py-soma-x 0.3.4 走 GEM-X 训练时的 0.1.3 旧骨架（无扭转骨、无姿势修正）。
- `video.py`：视频流程（worker 内）。YOLOX + ByteTrack（追踪器只在侦测帧更新；单人每 5 帧侦测、多人每帧）→ 同一人被拆开的轨迹
  缝合（短时间重叠且一框包住另一框、高度相近的「接力」；或一秒内接续：按前一段最后 0.5 秒的速度外推，横向容差取框宽 0.75、纵向取框高 0.5，最长边变化不超过一半。横向容差曾取最长边，站立的人框很高，群舞里左边离场的舞者被接到 270 px 外右边入场的另一人）→ 约 10 fps 关键帧上批次 VitPose（之后丢掉身体关键点平均置信度 < 0.3 的轨迹 `trusted_tracks`：容纳 4 人时会跟到远处的小点，实测 0.03；真人最低约 0.49）（裁切与镜像同批 16 张）、其余帧插值
  → 每条轨迹整段 GEM 去噪 → 关键帧批次贴合（`refine.fit_sequence`），修正量以旋转 slerp 补到中间帧。参数与实测见
  `tests/local/pose_gem_spike/VIDEO_SPEED.md`。
- `comotion.py`：可选的 CoMotion 多人追踪（设计文件 §31–32，worker 内）。Apple CoMotion（固定 `ml-comotion` `04b035a`）逐帧侦测
  SMPL 人体并维持轨迹，遮挡、交错时不像 YOLOX + ByteTrack 那样断轨或换人（长裙双人不再拆成两段、泳池后空翻合成一条、
  群舞后排覆盖 144→206 帧）。轨迹外框 = 投影的 SMPL 网格，之后照常缝合（`stitch`，可把 CoMotion 拆开的半身多人接回）、
  按面积选人、VitPose 与 GEM-X；每条轨迹带着它背后的 CoMotion 行（`bodies_for`：外框逐帧对得上的那一行）。侦测器与修正模块
  都放 MPS（CPU 侦测每帧约 3.5 秒，所以没有 MPS 就不启用）；随附的 CoreML 侦测器不用（coremltools 尚无 Python 3.14 正式版，
  MPS 结果与之相差 < 0.4 mm）。checkout 原样使用，载入时两处兼容：SMPL 是 chumpy pickle，改用 py-soma-x 自带的 chumpy 替身；
  transformers 5 的 `LlamaDecoderLayer` 直接返回张量（上游取 `[0]`，保留上游的 `fixed_dim_op` 维度展平）。与上游 py3.11 环境
  输出逐位相同。CoMotion 失败或一个人都没找到时，整段改走侦测器；`POSE_CAPTURE_TRACKER=detector` 可强制关闭。
  侦测器仍先跑一遍（每帧约 0.05 秒）：CoMotion 侦测的是整个 SMPL 人体，胸部以上的近景（自拍）认不出，侦测器看得到而 CoMotion
  几乎没盖到的大人物（中位框高 ≥ 画面一半、跨度 ≥ 30 帧）补进候选（`video.add_close_ups`，该人物没有 CoMotion 起始姿态），
  CoMotion 失败时也直接用这次的侦测结果，不再重跑。
- `comotion_pose.py`：CoMotion 的人体当 GEM-X 的起始姿态。每个 CoMotion id 的 SMPL 网格用 py-soma-x `PoseInversion`
  （SMPL 身份、SOMA 的 SMPL wrap）反解成 SOMA 旋转，去掉 joint orient 换成 GEM-X 的 T-pose 相对约定，覆写身体关节（手指保留
  GEM-X）；先做 0.06 秒局部线性平滑（CoMotion 是逐帧原始值，抖动为 GEM-X 的 2–3 倍）；髋部位置按 GEM-X 骨架与 SMPL 的身高比
  缩放、深度再按两者焦距比换算（一例 1.91 vs 1.54 m，不缩放时四肢对 VitPose 误差 6.6%，缩放后 2.4%），人偶在画面里的位置与
  大小不变；世界朝向沿用 GEM-X 同帧的相机→世界旋转，重力估计不变。之后照常贴合、影像证据、保持腿与地面。转换约 30 ms/帧/人。
- `accel.py`：视频的 CoreML 加速。VitPose 用固定批次 16、常数折叠的副本（安装时用 `onnx` 生成），CoreML 计算单元 CPU+GPU
  （神经引擎会在每次载入重新编译约 20 分钟）；YOLOX 用全部单元。缓存目录按「模型 SHA ＋ 计算单元 ＋ ORT 版本」命名，
  避免换模型或升级后悄悄读到旧编译结果。
- `refine.py`：识别后的关键点贴合。精简版靠动作先验从 2D 推 3D，少见姿势（膝盖交叉到支撑腿前、脚往后踢）会被先验拉回，
  肢体落在人旁边。用 Adam 调关节旋转，让投影贴合按置信度加权的 VitPose 关键点；同时锚定 GEM-X 的旋转（0.005/rad²）
  和每个关节相对髋部的深度（0.05/m²）——只贴合 2D 会把走路的腿甩成前后大弓步（实测脚的深度被推动 26–73 cm）。
  体型与平移不动；不降低 2D 误差就丢弃。结果写进 `diagnostics.keypoint_fit`（前后误差、最大深度变化、步数、秒数）。
  视频的批次贴合（`fit_sequence`）另给每帧一个根节点平移修正（相机坐标，0.1/m² 弱锚定）：特写时 GEM-X 把被裁切的人放得
  太远太高（推镜片段髋部在画面 65% 处，视频里在 92%），只调旋转移不动身体，人偶因此缩小、腿露进画面。加入后五段测试视频
  最差帧误差由 4–19% 降到 1–5%，修正量最大 34 cm。照片仍只调旋转。
  视频贴合只用置信度 ≥ 0.5 的关键点（与 GEM-X 一致；VitPose 失手的一帧曾把 0.37 的髋点标在胸口、把骨盆拉歪），
  手指权重 0.5（照片 0.1）：特写时手大、手指点决定掌向与握法，全身时手小、残差按人物框归一化本就很小。
  关键帧的短暂掉分（`video.fill_dropouts`）：≤ 1 秒、两端都有可信观测的空缺按直线补成 0.55；出画的关节不会回来，空缺开放不补。
- 关键帧的时间平滑与插值（`video.smooth_keypoints`、`interpolate_rows`、`interpolate_quats`）：VitPose 只在约 10 fps 的关键帧上
  侦测，各帧杂讯独立又以直线连接，24 fps 片段（每 2 帧一个关键帧）的手每帧拐一次弯，约 12 Hz 抖动，关键帧加速度是中间帧的 4 倍。
  现在送进 GEM 前先做按信心加权的局部线性平滑（直线而非平均，匀速动作不减速），宽度随该关节速度变化
  `0.12 s / (1 + 速度 / 0.3 人物框每秒)`；关键点、贴合的旋转修正与平移修正之间改用 PCHIP 平滑曲线（无过冲）。
  实测：推镜片段关键帧抖动 −64%、手指闪动 11.4→4.2 px；原地旋转舞抖动 −14%、手对原始侦测的偏差 +0.18 点（固定 0.07 s 时是 3 倍）；
  四人体操抖动 −20%、手 +0.15–0.22 点。
- `evidence.py`：可选的影像证据（SAM 3D Body，设计文件 §22）。GEM-X 精简版不看画面，分不出手贴在腰侧还是悬在肚子前
  （推镜片段的叉腰手腕被放在骨盆前 10–24 cm）；SAM 3D Body 读画面判对，2D 却不如 VitPose。所以它只提供相对 3D：手臂关节相对
  骨盆的深度、手指相对手腕的偏移（按躯干长度换算到识别骨架），2D 仍由 VitPose 决定，`fit_sequence` 合并（深度 5/m²、手指 1/m²）。
  把关：VitPose 看得到（≥ 0.5）且 SAM 的 2D 在人物框 10% 内；手指还要「手形」一致（相对手腕的 2D 偏移差 ≤ 手掌大小一半），
  SAM 判错掌向的叉腰手因此只给手腕深度、不给手指。抽样约每人每秒 2.5 帧、每段上限 60 帧，间隔 ≤ 0.6 秒插值。
  只把影像骨干放 Apple GPU（MPS，float32），MHR 头留 CPU（它用 float64）：完整模式 1.7 s/帧（CPU 43 s）。适配层定向修补上游的
  `.cuda()`、`recursive_to(..., "cuda")` 与 torch.hub 取 DINOv3 GitHub main 的行为（改用安装时固定的本地 checkout）。
  「不伤 2D」：贴合同时跑有/无证据两次（关键帧彼此独立），某帧只有在有证据的 2D 误差 ≤ 无证据 × 1.10 时才用证据结果
  （`video.keep_evidence`）——强制全用时原地旋转舞者 2D 误差多 25%；证据只决定 2D 看不出的部分，不拿看得到的去换。
  实测：10 秒推镜片段保留 86% 证据帧，叉腰手腕 18→6 cm、抓围巾手指形状与 SAM 差约 1 cm，2D 不变，总时间约 96 秒（证据 42 秒，
  首次载入另 11 秒）；15 秒原地舞约 110 秒、只保留 17%；5.5 秒四人约 156 秒（证据 81 秒，按 60 帧预算分给 4 人）。常驻约 7 GB。
  同一批观测也给出体型：`evidence.body_shape` 取各帧 SAM 3D Body 体型系数（与 GEM-X 同一 MHR 45 维空间）的中位数，至少 3 帧才采用，只换人偶网格（`body_shape` → 体型 GLB 与序列的 `identity`），骨架与身高仍用 GEM-X 的；GEM-X 只看关键点，曾把穿外套的女生、偏瘦的男生估成大肚男。节点上的「精修手部」开关（默认开）关掉或未安装时，结果与之前完全相同。
  视频另有 `hold_unseen_legs`：GEM-X 假设镜头不动，推镜时人变大、髋部在画面里下沉、脚出画，会被理解成人往镜头蹲，
  膝盖折成跪姿（实测 25°）。腿部关节的子关键点低于可靠门槛 0.7（到 0.45 全量）时，改用最近一次可靠看到的旋转
  （从未看到就是直腿）。门槛不用 GEM-X 的可见值 0.5：VitPose 对画面下方的脚仍会猜一个点（中位 0.36、偶尔 0.57，
  位置常在膝盖上方），真正看到的脚是 0.8–0.95；用 0.5 时这些猜测帧被当成「看到」，把 GEM-X 折起的腿当成保持目标；但只在「保持后的子关节投影落到画面外」时才生效——落在画面内说明是被另一条腿或衣物挡住，
  保留 GEM-X 的估计（全身舞蹈视频因此 0% 触发）。比例写进 `diagnostics.held_legs`。
  胸部以上的人（髋部关键点只在 < 15% 帧可见，`refine.upper_body_only`；评测集里这类人 0–4%，其余 ≥ 26%）改走「上半身模式」
  （`refine.steady_trunk`）：胸部旋转与位置不动（头、手臂、手的投影不变），骨盆跟随平滑 0.5 秒的胸部朝向，残差平分给三节脊椎，
  双腿直垂；到相机的距离沿胸部视线做 0.25 秒平滑（人偶尺寸固定，深度逐帧抖会变成大小忽胀忽缩）。序列里这类人的髋部不做 1 秒
  中位平滑、位置不做 5 帧平滑（没有脚要站稳，只能对齐画面），重力投票改用其骨盆轴（GEM-X 没有腿和地面可推重力）；
  `diagnostics.upper_body` 标记。鱼眼自拍：脊椎折叠 p5 129→164°、编辑器对位偏差 p95 4.7%→0.07%、深度抖动 0.56→0.07 cm。
- `scene.py` 的 `build_sequence`：视频转逐帧序列。每帧 Hips 世界旋转 + 76 关节旋转（base64）、Hips 世界位置（轻度平滑）、
  `lift`（编辑器让最低的脚站在这个高度，使髋部落到视频里的位置；保持的腿伸到地面以下时为负）。髋部高度 = 相机空间髋高的
  1 秒滑动中位数（滤掉深度逐帧抖动——沿视线方向会变成上下晃，原地跳舞的人曾中位浮 13 cm）+ GEM-X 重力世界髋高的快速部分
  （中位数基线之上的跳跃）。序列另给每帧 `hips`（髋部高度），编辑器按它放置人偶，所以女性/男性/识别体型腿长与识别骨架
  不同时也对得上视频（识别体型曾整体高 4.5 cm）；旧结果没有 `hips` 时仍按 `lift` 让最低的脚站地。中位数两端按端点拟合直线做点对称延拓，推镜持续到最后一帧也不会折回。共同地面只取脚可见且踩稳（最低的脚 0.2 秒平均后慢于 0.35 m/s）的帧，并按平滑后的髋部位置量：后空翻有一半时间脚在空中仍可见，旧的「可见帧中位数」把地面估在半空，人偶整段沉到地下 70 cm；踩稳帧不足 0.2 秒时退回全部可见帧。多人时每人的深度各自估计，常不在同一地面（群舞前后排离地 10–24 cm）：`common_ground` 取「踩稳且脚点可信（≥ 0.7）」的人的地面高度中位数为共同地面，把每人的相机坐标整体乘 k = 共同地面 / 自己的地面（沿视线前后移动并同比缩放身高，2D 投影不变），k 限制在 1/1.5–1.5，且缩放后身高须在编辑器的 140–200 cm 内（否则人偶按边界绘制、偏离视线）；可信的人少于两个、或地面离相机不到 20 cm（低机位分不出远近）时维持旧规则（最低者为地面、谁都不动）。单人片段完全不变。
  旧做法整段取 GEM-X 世界高度，它贴地但与画面脱节：推镜特写时髋部比画面高 22–27 cm，五段测试视频平均偏 7–25 cm，现为 1–4 cm。
- `scene.py`：只用 numpy，把引擎结果换到编辑器世界：由每个人的世界/相机朝向推出重力方向（按置信度加权），去掉偏航让机位看向 -Z，
  最低的脚落在地面，人群居中；只改 Hips 的全局旋转，其余关节沿用 SOMA 的 T-pose 相对轴角；推出照片机位（焦距、画幅、侧倾诊断）。
  单张照片无法确定绝对身高，只保留多人间的相对高矮，中位数对齐 175 cm，并以同一比例绕相机缩放整个场景，投影不变。
  多人的深度各自估计，常不在同一地面：每人最低的脚高出最低者多少记为 `floor_offset`，画布写进角色的「离地 Y」，照片机位因此仍对得上原图。
- `worker.py`：常驻 JSON-lines worker（`local_image/runtime.py` 的协议）；模型只加载一次，读图时套用 EXIF 方向、最长边限 2048。
- `runtime.py`：`JsonLineRuntime` 子类：首次请求启动、闲置 10 分钟退出、共享 `local_accelerator` 租约；安装状态
  （missing / outdated / incomplete / ready）。HTTP 进程不导入 torch、onnxruntime 或 GEM-X。
- `storage.py` / `service.py`：内容寻址的照片素材、SQLite 任务、串行队列、取消、重启后标记中断；成功任务直接附带结果 JSON。
- `bodies.py`：识别体型。worker 用 SOMA 的 MHR 身份模型把每人的 `identity_coeffs` 与 68 个部位比例（去掉第一个全局缩放，
  整体大小由 `height_cm` 决定）转成 SOMA 低精度人偶 GLB，按内容哈希存 `data/pose-capture/bodies/<id>.glb`，结果里每人带 `body_id`。
  需要已安装的姿态人偶（`server.py` 注入 `PoseSceneService.assets_dir`）；未安装或生成失败时只是没有体型，识别照常完成。
  MHR 的中精度模型约 700 MB，所以识别体型只有 low 网格。
- `install.py` / `requirements-py314.txt`：显式安装（见下）；影像证据与 CoMotion 的依赖另列 `requirements-evidence-py314.txt`、
  `requirements-comotion-py314.txt` 单独校验（任一不符只停用该功能，不影响照片与影片识别）。
- `routes/pose_capture_routes.py`：受保护 HTTP 适配。`server.py` 注入组件与数据目录，并把 worker 登记到本地模型的闲置释放清单。

## 安装

```sh
.venv/bin/python -m backend.pose_capture.install                       # 下载约 4.4 GB，再预编译 CoreML 约 14 分钟
.venv/bin/python -m backend.pose_capture.install --skip-video          # 只装照片识别
.venv/bin/python -m backend.pose_capture.install --models-from DIR     # 复用已有 GEM-X 目录的 inputs/（逐一校验）
.venv/bin/python -m backend.pose_capture.install --comotion-only       # 为已安装的引擎补装 CoMotion 多人追踪（下载 2.3 GB）
.venv/bin/python -m backend.pose_capture.install --skip-comotion       # 影片仍用 YOLOX + ByteTrack
```

共用主环境 CPython 3.14：锁住所有已有包版本，只新增 23 个固定版本的包（hydra、lightning、timm、onnx、ml_dtypes 等）；
某个需求文件自己固定的包可以移到固定版本（timm 由 0.6.7 升到 1.0.13：CoMotion 的 ConvNeXtV2 骨干需要 ≥ 0.9，GEM-X 只用
`vision_transformer.Mlp`，升级前后识别结果逐位相同）。CoMotion 另加 8 个纯 Python 包（tensordict、pypose、scenedetect 0.6.5 等；
pytest/pluggy/iniconfig 是 pypose 声明的运行依赖），模型来自 Apple 的固定压缩包（逐个成员校验 SHA-256）、SMPL 中性模型
（SMPLer-X Space 镜像的固定 revision，pickle 检查后固定 SHA-256）与 SOMA 的 SMPL wrap，约占 1.6 GB。
视频需要：生成固定批次折叠副本（约 1 分钟，3.4 GB）并预编译 CoreML（CPU+GPU，约 13.5 分钟，缓存约 16 GB），合计多占约 20 GB；
没有 CoreML 时视频退回较慢的 CPU 设置（15 秒约 2.7 分钟）。
`antlr4-python3-runtime 4.9.3` 只有源码包，安装器先在临时目录建出纯 Python wheel，其余一律只装 wheel。
GEM-X 自己声明的依赖不安装（会引入 opencv-python、open3d、wandb 等），推理不需要的 `wandb`、`o3d_render` 在 worker 内以空模块代替。
安装最后会在子进程加载一次引擎自检。结果在 `APP_DATA_DIR/components/pose-capture/`，素材和任务在 `APP_DATA_DIR/data/pose-capture/`。

## 接口

| 路由 | 方法 | 用途 |
|---|---|---|
| `/api/pose_capture/status` | GET | 安装状态、安装命令 |
| `/api/pose_capture/upload?name=` | POST | 原始图片字节，返回 `asset_id`（内容哈希，同一张图共用） |
| `/api/pose_capture/submit` | POST | `{asset_id, max_people?}` |
| `/api/pose_capture/job?id=` | GET | 任务状态；成功时附 `result`（姿势序列契约） |
| `/api/pose_capture/cancel` | POST | `{id}` |
| `/api/pose_capture/body?id=` | GET | 识别体型 GLB |
| `/api/pose_capture/result?id=` | GET | 视频识别的姿势序列（大，任务轮询只带 `result_url`） |

## 实测（M2 Max，2026-10-20）

| 情况 | 时间 |
|---|---|
| 首次请求（含加载模型） | 约 8 秒 |
| 单人照片（模型已加载） | 约 2.7–3.1 秒（贴合约 0.6 秒） |
| 4 人照片 | 约 8.3–9.1 秒（贴合约 1.8 秒；首次请求含加载与体型模型约 18–20 秒） |
| 15 秒单人视频 | 约 46–57 秒（模型已加载）；首次请求另加约 7 秒载入 |
| 5.5 秒 4 人视频 | 约 55–65 秒；推算 15 秒 4 人约 3 分钟 |
| CoMotion 追踪（2026-10-25） | 8–13 秒片段约 33–56 秒（MPS）；另加 YOLOX 侦测补近景约 0.05 秒/帧（10 秒 24 fps 约 12 秒）；首次载入约 7 秒 |

贴合后身体关节投影与 VitPose 的中位误差为人物框的 0.5–0.9%（贴合前 1.0–1.4%）；交叉腿舞蹈照的左膝从偏 87 px 降到 27 px。GEM-X 的骨架与人偶（SOMA 0.3.4 中性）在同一组旋转下，
骨骼方向中位差 0.03°（掌骨约 10°）。

## 限制

- 机位侧倾（roll）无法用「位置 + 目标点」表示，会被拉平；诊断里有 `roll_deg`。
- 每个人的深度各自估计，多人前后距离只是近似。实测多人照片里离地 0.1–0.5 m 很常见，用重力或脚部拟合地面都无法稳定消除
  （各人重力估计相差 8–14°），所以保留「离地 Y」；把它调成 0 可让人偶全部站地，代价是照片机位不再完全对齐。
- 手指来自 VitPose 手部关键点，精度低于身体。
- 贴合只修正照片看得到的方向；肢体朝向镜头或远离镜头仍以 GEM-X 估计为准。2D 关键点本身认错（遮挡、交叠）时贴合会跟着错。
  诊断工具：`tests/local/pose_gem_spike/diagnose_photo_local.py`（2D、反投影、侧视、俯视对照图）。
- 精简版不读图像特征，体型只由关键点比例推断：四肢长短可信（照片机位下腿长、脚位明显比中性人偶贴合），
  胖瘦、腹部等围度不可靠（实测苗条的人会被估成大腹便便）。编辑器可随时切回中性 / 女性 / 男性，识别体型仍保留可选。

可移植回归：`tests/test_pose_capture.py`。

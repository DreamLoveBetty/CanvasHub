# Topaz Gigapixel 独立节点

Topaz 自有模型、参数、请求和运行模块；不属于「本地高清放大」的 Spandrel 模块。
只复用画布统一的任务状态、进度、取消、结果图片、归档与 Telegram 投递流程。
生产调用不新增 Python 环境或常驻服务。运行文件及模型已从隔离验证的过滤副本导入本机 `APP_DATA_DIR/components/topaz/vendor/Contents/`，不随代码或发布包分发；未导入 Topaz 用户账号目录或模型目录的 `license.lic`。导入是显式操作，服务启动/请求不会从原 App 自动补文件。

## 已验证能力（2026-09-22）

macOS arm64，Topaz Gigapixel **1.3.6**；19 个模型/版本实际产生可解码图片，核对实际加载模型、尺寸和进度，而不只检查退出码。

| 模型 | 本地调用 | 节点调节 |
|---|---|---|
| Standard V2、V1 | native / stack | 锐化、降噪、压缩修复；V2 支持自动参数 |
| High Fidelity V3、V2、V1 | native / stack | V3 强度；V2/V1 锐化、降噪、压缩修复；V2 支持自动参数 |
| Low res V2、V1 | native / stack | 锐化、降噪、压缩修复；V2 支持自动参数 |
| Text & shapes、Art & CG | native | 自动或手动锐化、降噪、压缩修复 |
| Wonder 3.5、3、2 | bundled Neuro one-shot | 3/3.5 低、中、高增强档位；2 使用模型默认 |
| Wonder 1 | stack / Natural Upscale (`tpn`) | 增强档位、种子 |
| Standard Max | stack | 增强强度 |
| Recover V3、V2、V1 | stack / native | V3 增强档位；V1/V2 细节恢复 |
| Redefine realistic | stack | None / Subtle、种子 |
| Redefine creative | stack | Low / Medium / High / Max、纹理、种子、可选图像描述 |

**Wonder 1 复测**：当前运行目录完整链接 `.bin` 辅助数据且已有 CoreML 缓存后，128→256 px 成功（9–13 秒），384→768 px 成功（31 秒，连续原生进度）；4 秒取消无输出，随后任务成功。未触发模型下载。首次超时不能作为永久不可用结论；已解除禁用，目录检查要求精确 `new` UNet 文件及 `tpn_embeds.bin`，仍保留下载拦截与版本校验。较大生产图及全部参数组合不据此保证。

- 1× / 2× / 4× / 6×；普通模型可选 0.2–6× 自定义倍数，Wonder 2/3/3.5 最小 1×；或指定宽度、高度、最长边，单位 px / in / cm，PPI 可调、保持比例。
- 普通增强模型提供伽马校正；`native` 普通增强模型保留已验证的 Face Recovery **V2**。不向不支持的模型显示可操作的人脸恢复开关。
- 所有开放模型支持颗粒；stack 使用原生 Grain，Wonder 在 one-shot 输出后使用同一任务的原生 Grain 后处理，不另建任务或放大一次。
- PNG、JPEG（质量可调）、TIFF；内部 8 bit 像素桥接，PNG/TIFF 保留插值透明度，JPEG RGB。
- 输入最短边 ≥16 px、≤1600 万像素；输出最长边 ≤32000 px、≤1 亿像素。Wonder 2/3/3.5 的 Neuro 适配另限输入 400 万 / 输出 1600 万像素。这是运行边界，不是 App 的容量或画质保证。
- 两份原生库、Wonder 启动器与发布清单均校验 SHA-256。自有 runtime 的模型缺失/版本变化时禁用；运行中要求下载权重则终止，交由本机重新导入，不隐式切换云端或其他模型。
- Redefine 的嵌入模型还依赖 `rxl_vocab.txt`、`rxl_merges.txt`、`neg_emb.yaml`；creative 路径另需 512 px 的 `ggn_ap`、`apnb`、`slsp_ap` 辅助权重。目录检查和运行时链接均显式覆盖这些文件，而不宽泛复制任意许可/配置文件。

没有开放未经验证的 Face V3、主体蒙版、ICC 转换和 16 bit 输出。这里是固定版本的私有接口适配，不是公开稳定 SDK，不改变 Enterprise CLI 授权结果。

## 模块边界与状态所有权

| 模块 | 责任 |
|---|---|
| `topaz/routes.py` | 鉴权后的请求解析、参数校验、调度。认证仍由服务器既有路径执行 |
| `topaz/parameters.py` | 独立 schema、默认值、范围、物理尺寸换算、原生参数白名单 |
| `topaz/service.py` | 将 Topaz 引擎显式注入共享图像增强生命周期 |
| `topaz/catalog.py` | 模型、安装检查、版本指纹、实际可用能力 |
| `topaz/native.py` | C ABI、进程内请求上下文、原生日志回调；仅子进程加载 |
| `topaz/neuro.py` | App 自带 Wonder 一次性执行器适配，真实阶段进度、离线模型加载，与 worker 同进程组 |
| `topaz/evidence.py` | 核对原生日志中的实际模型 ID，拒绝静默别名回退 |
| `topaz/worker.py` | 输入/输出转换，尺寸校验，单次调用，父进程退出监测 |
| `topaz/runtime.py` | 本机资源租约、子进程监督、超时、终止与原子交付 |
| `topaz/provision.py` | 显式导入已过滤、已验证的本机资源；APFS 克隆、外部软链接审计和原子启用 |
| `services/image_enhancement.py` | 引擎无关的任务审计、状态、归档、sidecar、缩略图和 sendDocument |
| `services/upscale_generation.py` | 原接口的单一兼容转发，不维护另一份业务逻辑 |
| `services/upscale_backends.py` | 仅保留 Spandrel；拒绝旧 Topaz ID，不下载无关组件 |
| `services/image_preview.py` | 通用 TIFF → PNG 浏览器预览，原件下载和投递仍为 TIFF |
| `server.py` | 依赖装配和路由转发，不加载厂商推理库 |

任务状态只由现有任务库维护。前端 `desktop-topaz-model.js` 拥有节点 schema/连线策略和旧节点迁移；
`desktop-canvas-topaz.js` 拥有表单、依赖联动和任务展示；`desktop-topaz-api.js` 是认证 API 适配。
节点无单独停止按钮、轮询器或底部状态栏分支，走 `DesktopApi.tasks.generation` → `DesktopTasks` / `DesktopResults`。
旧 `upscale + topaz-*` 自动迁移为 `topaz`，保留 ID、位置、连线和历史输出。

## 统一接口

| 能力 | 接口 |
|---|---|
| 模型及 schema | `GET /api/topaz/models` |
| 提交 | `POST /api/topaz/run`，字段 `model`、`images`（一张 data URI）、`options`、`prompt`、`telegram_enabled`、`lineage` |
| 进度/结果 | 既有 `GET /api/status/<task_id>` / `/status/`，`result_files` / `image_paths` |
| 取消 | 既有 `POST /api/tasks/<task_id>/cancel` |

提交返回 `202 {task_id,status,type:"topaz"}`。未知参数拒绝；不接受本机路径、原生任意 JSON 或请求上下文。
归档沿用 `IMAGE_ARCHIVE_DIR/YYYY-MM-DD/`、配置/提示词 sidecar 和原件 `sendDocument`。
TIFF `image_paths` 使用 `/image/<filename>?preview=1`；原始下载仍通过文件名返回 TIFF。

## 原生契约

```c
int iai_init(const char *models_directory);
int iai_proc(const char *input_path, const char *output_path,
             const char *request_json_path, const unsigned char *request_context);
```

第四参数是库内请求协议上下文，不是进度/取消句柄。只复用当前库的进程内指针，不导出所指字节，不读取或修改账号/许可证文件。
版本校验先于加载。HTTP 进程不载入 Topaz / CoreML；每次任务使用独立子进程。

- `iai_proc` 为普通请求翻译器；`iai_stack_proc` 使用相同四参数 ABI，接收白名单生成的 FilterSettings 数组。两者名字不可互换：`Standard MAX` 在翻译器中会静默加载旧 Standard，正确 stack 名为 `Standard Max`；Recover V3 的底层类别名为 `Wonder`。
- Standard 三个参数与 HF `strength` 是 **0–1 数字字符串**。自动模式省略 Standard 三参数，调用原生估计。
- `gamma_correction` / `grain` 是 `"true"/"false"` 字符串。
- 颗粒 `grain_strength` / `grain_intensity` 为 0–1 数字字符串；`grain_size` 为数字字符串。
- `face_enhancement` 是 JSON bool，`face_enhancement_strength` 是 0–1 JSON float，`face_enhancement_creativity` 是 0 / 1 JSON int。包装层固定 Face Recovery V2。
- 原生返回 0、实际加载模型 ID 匹配且输出可解码、尺寸匹配后才交付。Wonder 另要求运行器确认选中模型和 one-shot OK。

进度来自原生 `[PROGRESS]` 日志；Wonder 来自编码、DiT、解码、后处理的真实阶段边界（不是凭时间估计的连续百分比）。统一映射到既有任务进度。取消为进程组终止：先 SIGTERM，3 秒仍未退出再 SIGKILL，等待结束并清理半成品。
没有声称存在原生协作取消 API。超时 30 分钟，父进程退出时 worker 自行终止。

## 数据与验证

`APP_DATA_DIR/components/topaz/vendor/Contents/` 是生产引擎、Wonder 运行器和模型的自有副本。`APP_DATA_DIR/components/topaz/models/` 仅链接这个自有副本中的 JSON/.tz/.bin 和精确列明的 Redefine 词表/配置；原先指向 `/Applications/Topaz Gigapixel.app` 的旧模型链接已清除并重建，既有 `coreMLCache/` 保留。
`jobs/<uuid>/` 保留小型 options/request/日志，像素中间文件完成/失败/取消后清理。
共享本地推理资源租约，不接管整个系统 GPU，也不修改其他模型环境。

资源导入命令（仅本机，需先用 `tests/local/topaz_isolated_runtime_local.py` 生成经过过滤和隔离验证的 `Contents`）：

```bash
python3 -m backend.topaz.provision --source tests/output/topaz-isolation-20260924/stage/Contents
```

导入工具拒绝覆盖现有 runtime、外部/断开的软链接以及不完整的模型集；运行目录和缓存被 `.gitignore` 排除。生产默认只读取自有目录；显式 `Runtime(..., app=...)` 仅供隔离探针/测试。

可移植测试：`tests/test_topaz.py`、`tests/test_topaz_upscale.cjs`、`tests/test_task_contract.cjs`。
本机探针和结果位于忽略的 `tests/local/topaz_*_local.py`、`tests/output/topaz-expand-20260922/`。
本次扩展：19 个模型/版本通过 worker 完整出图；覆盖 1×、1.5×、2×、4×、6×、颗粒和 Redefine 参数；
两执行器实测进程组取消及取消后再次出图；实际 `/desktop.html` 模型菜单、日夜主题、Wonder 提交/回填/统一全局取消。
既有测试保留格式、透明度、人脸 V2、旧节点迁移、归档、sendDocument、状态契约。
并非最大尺寸性能测试、所有参数组合穷举或人像质量评测。可用版本会随着本机安装变化重新检查。

**2026-09-24 本机隔离验证与生产切换**：用 APFS 副本仅保留 19 个模型所需文件；进程禁止读取原 App、Topaz 用户目录和网络。19/19 在同一轮中以 128→256 px 合成图产生可解码、非空且非纯插值的图片，进度与实际模型身份核对通过。该过滤副本现已导入生产自有 runtime，19/19 通过文件完整性检查，所有运行目录模型链接均指向自有资源。原生与 Wonder 路径的取消/恢复另已验证。结果和具体边界见 `tests/output/topaz-isolation-20260924/REPORT.md`（本机忽略目录）。生产切换不等于卸载 App 后授权行为或跨机器运行已验证；用户手测仍需完成。

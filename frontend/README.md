# Web build boundary

## 设置中心 · 左侧抽屉与搜索（2026-10-09）

设置中心改为左侧抽屉：位于标题栏与状态栏之间，从工具栏右侧滑入并盖在画布上方（画布不缩放、
不加遮罩）。默认宽 760px，右缘拖动 / 方向键调宽（560–1100px，双击恢复默认），宽度存于
`DesktopPreferences.state.settingsWidth`；显示宽度另按窗口收窄，保证工具栏与右侧留白。
11 个分类常驻左侧纵向导航，分组：常用 / 生成线路 / 本地模型 / 其它（取消“展开更多”）。
顶部搜索框按卡片标题、字段名（说明文字低权重）跨分类定位：切换分类、滚动到卡片并短暂高亮，
焦点落到该字段的实际控件；Esc 先清空搜索，再关闭抽屉。

- `scripts/desktop-settings-drawer.js`：宽度归一化、拖动（每帧最多一次样式写入）、键盘/双击、
  窗口变化重算；不管内容和开关。在 `desktop-preferences.js` 之前加载。
- `scripts/desktop-settings-search.js`：从各分类卡片 HTML 建索引（惰性 `<template>` 解析）、
  多词匹配与排序、结果列表与键盘交互；不持有设置数据、不负责跳转。在 `desktop-settings.js` 前加载。
- `desktop-settings.js`：`buildSections(data, tab)` 抽出原分类渲染（遮蔽 `activeTab`），搜索索引
  据此离屏生成各分类卡片，不额外请求；`selectTab()` 统一点击与搜索跳转；装配上述两个模块。
- 几何在 `desktop-geometry.css`（抽屉位置、导航、搜索、把手、内容区 ≥820px 两列），配色在
  `desktop-settings-auth.css` / `desktop-tokens.css`。大面板不用 backdrop-filter，改为近不透明底色
  （毛玻璃性能红线）。

便携验证：`tests/test_settings_drawer.cjs`、`tests/test_settings_disclosure_typography.py`；
本地探针 `tests/local/settings_drawer_probe_local.mjs`（真实前端 + 全合成 `/api/*`）。

## 花朵取色器（2026-10-10）

`scripts/desktop-color-bloom.js` + `styles/desktop-color-bloom.css`：共享取色组件（色板按钮 +
HEX 框，点开为花瓣色盘 + 弧形明度条）。由配色方案（提示词库）与设置中心（进度条填充色、按钮
材质的自定义颜色与强调色）共用，原提示词库内的实现已移除。组件只管自身标记、开合、花瓣/明度/
键盘交互和弹层定位（会被裁切时改为右对齐或向上展开）；值的含义与保存归宿主：已提交的颜色写入
带宿主属性的隐藏 `<input data-color-bloom-value>`，并派发冒泡的 `input`（拖动中）/`change`（提交）
事件，宿主沿用原有表单处理；宿主改值或禁用后调用 `DesktopColorBloom.refresh(root)`，Escape 时可先
`close(root)`。设置中心的颜色行（`.desk-settings-color-field`）与下拉行同为“标签 | 控件”一行。
便携验证：`tests/test_color_bloom.cjs`；本地探针 `tests/local/color_bloom_probe_local.mjs`。

## 节点按钮材质 · Ambient（2026-10-09）

设置中心 → 系统 → 节点按钮材质：现有（默认）/ 哑光 / 微光泽 / 磨砂玻璃；按键表面
（凹面·碟形 / 平面 / 凸面，仅哑光）；玻璃阴影偏移（100% 上游 / 75 / 50 / 25 / 0%，仅磨砂玻璃：上游阴影环偏移与宽度是固定像素，
小按键上显得错位）；键体颜色或玻璃染色（上游预设 Oxide/Steel/Brass、
Violet/Amber/Teal + 自定义 HEX）；强调色（悬停/焦点，默认上游 coral）。只作用于画布节点内的
按键：`.desk-button`、`.desk-node-delete`、`.desk-generation-action`，以及节点模板给自有按键
打上的 `.desk-key`（无任何自身样式的挂钩类，只有 Ambient 层引用；2026-10-10 覆盖文本节点操作栏、
图片工具条、排版/姿态、图片组、音频导入/下载、音乐操作、Topaz Video 与 ReShot 导入）。
分段选择（2026-10-10，上游 Select 带灯键组读法）：容器打 `.desk-key-bank` 挂钩（输入节点 GPT/Google、
音乐节点页签，以及设置中心的连接端点/连线/碰撞、H3 运行方式、账号池页签）。容器为凹槽（座深 .27，槽底
`--amb-lume`；深色主题再压黑 55%，凹袋改石墨），每个按钮是凹袋：`::before` 为 LED 灯罩、`::after` 为固定
磨砂玻璃扩散键帽（不随按键材质变化），文字仍是按钮本身。选中：灯罩点亮为灯色（`--amb-led-color`，否则强调色），
键帽被灯色晕染，光溢到槽上，文字压暗成剪影。未带入：玻璃键帽的阴影环（需第三层）。设置中心的分段在 Ambient 下加 3px 槽边。
开关与复选框（2026-10-10，上游 Switch + LED）：不改 HTML。`.desk-switch` 的 `<span>` 与节点/设置中心里的普通复选框
（`appearance: none`，仍是复选框）作为轨道：上游凹槽（`--amb-lume`，深色主题压黑 55%）；`::after` 为凸面药丸键帽（`ambient` +
`amb-fillet` + `amb-surface-convex`，宽 52%、高 78%、端距 11%）；`::before` 为 LED，位于键帽开启后露出的半边，只在开启时以强调色亮起。
字段、上传投放区、音频走带（转盘/圆钮/静音）、行内链接式按钮及节点外的其它面板/弹窗不变。偏好存于
`DesktopPreferences.state.controlMaterial`（本地偏好键），不进工作流、不改后端。

- `vendor/ambientcss/`：上游 Ambient CSS 固定 commit 原文件与 MIT 许可（哈希见其 README），
  页面不直接加载（含全局 `:root`/`*`/`@property`）。
- `tooling/build-ambient-controls.mjs`：按映射表抽取所需规则，声明体逐字复制，选择器改写到
  `#deskApp[data-control-material="ambient"] .desk-node :is(.desk-button, .desk-node-delete, .desk-generation-action, .desk-key)`
  ；分段键 `:is(.desk-node, .desk-settings) .desk-key-bank > button` 走 Select 三层（容器取上游 `.amb-groove`，键的 `::before`/`::after` 取 `.amb-select-lens` 与玻璃键帽），
  生成 `styles/desktop-ambient-controls.css`（`--check` 校验是否最新）。按钮本身即键帽：
  玻璃光环改用 `::before`，`::after` 留给上游碟形。
- `styles/desktop-control-material.css`：保留生产几何，只替换绘制/厚度/文字色与状态；深色主题
  下默认键体为中性石墨（`--amb-albedo #454d4f` + 中性光源，属本项目适配，上游无深色配方）。
- `scripts/desktop-control-material.js`：偏好模型、对 `<body>` 的属性/变量投影、设置卡片渲染与
  事件解析；在 `desktop-preferences.js` 之前加载。`desktop-settings.js` 只装配卡片和转发事件。
- `<body id="deskApp">` 提供作用域 id，使 Ambient 规则无需 `!important` 即可覆盖生产按钮类规则。

性能（24 个 Qwen 节点 / 96 个按钮，自驱平移 120 帧，本地无头 Chromium 相对值）：哑光与现有
持平，微光泽约 +0–5%，磨砂玻璃约 +12–18% 且深色下长帧略增，故设置文案提示玻璃较耗性能。
便携验证：`tests/test_control_material.cjs`；本地探针 `tests/local/control_material_*_local.*`。

## 画布节点进度材质（2026-10-07）

设置中心 → 系统 → 节点进度条提供 Liquid（默认）、Slosh、Smoke、Drops、Bands、
Threads、Diamond、Grain 与 Classic；新轨道默认 36px，可选 48/56px，阶段、任务名称、
真实用时和百分比内置。Classic 保留原来的胶囊/下挂标签。颜色按样式分别记忆，
只影响填充物；偏好由 `DesktopPreferences.state.progress` 验证并存于现有本地偏好键，
不进工作流、不改后端配置。无进度回执时显示“处理中”，不按用时伪造百分比。

模块与装配顺序（经典脚本，无框架/新运行依赖）：

1. `desktop-progress-model.js`：纯弹簧/连续材质驱动、色彩、样式目录、尺寸与显示契约。
2. `desktop-progress-materials.js` → `desktop-progress-renderer.js`：Canvas2D 材质与有限尺寸的
   前沿缓冲复用；不读任务、不调 API、不持有计时器。
3. `desktop-progress.js`：显式注入偏好与视口，统一管理 `update(root, display, owner)`、
   `replaceRoot`、`releaseWithin`、`clear`、`destroy`。一条公平调度 RAF，单秒级显示时钟，
   Intersection/ResizeObserver 仅观察已显示的进度条；离屏/后台/静止时不持续绘制，
   reduced-motion 禁用循环动画；每帧绘制预算 4ms，平移/缩放或多轨道时降频。
4. 以上先于 preferences、各领域 controller/view 与 canvas host 加载；CSS 在节点领域样式
   之后加载，只有 `.desk-progress-material` 覆盖轨道外观。画布 host 只装配及转发。

Qwen/Krea/绘栾、Topaz Video、ReShot、YuE 由原领域控制器/视图传入任务快照；
GPT/Google/Comfy/Topaz 图像/高清放大/文件结果由 DesktopResults 适配；输入节点的新材质
按节点挂载，不再共享经典样式的单一浮动层，因此并发图像任务不会互相覆盖。H3 在原模型节点
刷新入口接入并迁移原材质 DOM，避免轮询换壳重置波形。未知时间显示 `—`，收到服务端
started_at/created_at 后基于真实时戳推进，不随主题、样式或百分比重置。音乐保留原领域
的“当前阶段百分比”及显示时钟。节点删除、工作流替换、页面离开明确释放资源；不依赖
扫描全画布的 MutationObserver。任务提交/轮询/取消、Telegram 与存储协议保持不变。

便携验证：`tests/test_progress_model.cjs`、`tests/test_progress_view.cjs`、
`tests/test_progress_integration.cjs`；浏览器合成任务检查放在忽略的 `tests/output/`。

## Transformer 输出精度（2026-10-06）

Krea2 / Qwen2.1 模型工具在原有控制器内提供 `8bit`（默认）与 `bf16`，Krea2
另保留 `mixed-4-8`。工具草稿拥有精度选择，认证 API 继续发送原有 `precision`
字段；检查结果按所选精度展示 Transformer 磁盘估算。转换任务状态由后端拥有。
BF16 仅改变 Transformer，不替换共享编码器/所选 VAE；说明归原“模型工具”帮助抽屉，
不增加节点高度或第二份全局状态。完成事件仍刷新节点目录，节点按稳定模型 ID 加载，
显示目录返回的名称/精度标签；Krea 工作流规范化保留 BF16，但新节点仍默认内置 8-bit。
未增加脚本或改变装配顺序，现有设置工具/model/controller 的缓存版本同步更新。

## Qwen 2.1 · MLX（2026-10-01）

`desktop-qwen21-model.js` 拥有节点参数、连接契约和结果图外框布局；API、节点控制器、
设置工具分别在 `desktop-qwen21-api.js`、`desktop-canvas-qwen21.js`、
`desktop-qwen21-tools.js`。装配顺序是 tasks → model → API → tools/controller →
workflow/nodes → canvas → settings。主画布只注入状态、连线、图片结果和布局端口。
工作流保留 Base ID、预设、普通 LoRA ID/强度和参考图顺序，不保存本地权重路径。
工作模式由 model 的 `resolveMode(node, canvas)` 按实际输入连线派生，controller 展示只读
自动状态：仅文本为文生图，接入图像/图片组/排版或姿态参考为编辑。空参考节点不会退回
文生图，提交前须有可读取内容；断开和工作流重载重新识别，标准/Viggle 预设不随模式改变。
文生图和有序多参考编辑共用标准/Viggle；加速 LoRA 默认 v0.3 r256，版本/秩和步数
分离，标准 2–60 步、Viggle 5–60 步可调，不锁定推荐 6 步。进度挂在 720×500 节点下方。
只对新建输出按图片最终外框尺寸在节点右方堆叠，不移动用户已有的图片节点。
模型工具页的 Qwen 转换、目录、任务状态和 Krea 独立，仍复用认证及统一任务接口。

## 桌面画布模型节点视觉与尺寸规范（2026-09-28）

模型配置类节点以 `desk-node--input` 为基准：外壳使用 `desk-node desk-glass`，
标题区使用 `desk-node__header`、`desk-node__eyebrow`、`desk-node-tools`，参数控件
复用 `desk-select` / `desk-number`，底部状态与操作复用 `desk-input-footer`、
`desk-pill-row`、`desk-switch`、`desk-action-row` 和 `desk-generation-action`。
领域 CSS 只负责网格、密度和确有必要的局部结构，不得为普通输入、按钮、状态条
另造一套硬编码配色；明暗主题和交互状态统一由现有 tokens / controls 层提供。

固定尺寸节点的 schema 尺寸必须与实际 DOM 外框一致，并以内容预算反推高度；底部
操作区贴合内容，不保留无语义空白。多条目区域（如 LoRA）在标注清晰的内部区域
滚动，不能靠无限增高节点容纳。新增模型节点时需要同时验证空态、最大条目态、
明暗主题、原生/增强下拉和实际 `/desktop.html` 页面，并更新桌面资源缓存版本及局部
回归测试。

## Krea 2 · MLX 独立画布节点（2026-09-28）

`desktop-krea2-model.js` 拥有单一 `krea2` 节点 schema、参数默认值与
`text/image → krea2 → image` 连线规则；`desktop-krea2-api.js` 只经现有认证
客户端访问 `/api/krea2/*`，并在 snake_case 边界上传编辑参考图；
`desktop-canvas-krea2.js` 拥有环境/模型状态、首次生成自动准备、多 LoRA 选择与强度、
画布输入收集、任务轮询/取消和结果图片节点回流；`desktop-krea2.css` 只定义
`.desk-` 作用域展示。提示词和编辑图片只来自连线，节点不保存二进制 LoRA、
本地路径、HF 凭证或重复提示词输入框。工作流只保存 LoRA 内容哈希 ID/强度、
生成参数与任务 ID。`desktop-canvas.js`、`nodes.js`、`workflow.js` 仅装配生命周期、
连接域和状态持久化；model → API → controller 均先于 host 加载。
工作模式同样由 model 的 `resolveMode(node, canvas)` 自动识别：无图像输入时标准文生图，
接入单图时 Identity Edit（保留编辑适配器和兼容校验）。模式切换不删除普通 LoRA 选择；
编辑适配器不重复叠加，超过 3 个有效普通 LoRA 时明确提示用户移除，而不截断数据。
后端原标准重绘 API 仍保留；自动画布不再提供无效的文生图重绘强度控件。
两类 controller 都在准备/上传之前快照模式、参数和有序图源，图变化仅影响下一次任务；
异步工作流替换后旧会话不能提交。识别不增加全局图副本或新的主画布业务逻辑。

节点使用与标准模型输入一致的 720 × 480 锁定外框、共享标题/表单/状态/开关/
生成按钮材质；Base 权重与本地 LoRA 选择器在模型构建区并列，参数区固定为两行，
画幅比例选择会联动宽高，手动更改宽高后则反向匹配标准比例或显示“自定义”。已加载
LoRA 列表在节点内部滚动；生成进度条与其它生成节点一致悬挂在节点外框下方，隐藏时
不参与 Flex 布局；底部仅保留标准 14px 内边距。

模型准备是后台长任务，不单独暴露准备按钮：首次点击生成时自动启动并在节点进度
层展示状态。LoRA 下拉直接读取后端托管目录，打开下拉时刷新，不提供浏览器上传
按钮。节点提供复用标准控件的 `NSFW 安全检查` 开关，默认关闭；开启后首次生成会
自动补齐分类模型，并通过 API 边界传递 `safety_enabled`。实际生成复用统一任务状态与图片输出适配器。前端不导入 MLX，不启动额外
服务，也不改变 GPT、Comfy、绘栾等线路。

设置中心的 **模型工具** 页由 `desktop-krea2-tools.js` 独立管理，仅通过
`desktop-krea2-api.js` 调用受保护的检查、转换、取消、模型列表和删除接口。页面接收
本机绝对路径或托管导入目录中的文件名，不通过浏览器上传数十 GB 权重；展示的转换
进度来自后端持久任务。转换成功或删除后发出 `krea2-models-changed`，节点控制器重新
读取动态目录。节点工作流持久化 `baseModelId`，旧的 `precision` 自动迁移到内置模型
ID；下拉显示服务端返回的真实模型名称，而不是把量化方案当作模型身份。设置控制器
只负责页面生命周期与事件转发，不拥有 MLX 进程、磁盘路径解析或模型发布状态。

## 绘栾独立画布节点（2026-09-27）

`desktop-cyimg-model.js` 拥有图像/视频节点 schema 与连线规则；`desktop-cyimg-api.js` 仅通过认证 API 请求目录、上传、提交和已有任务状态；`desktop-canvas-cyimg.js` 拥有模型参数、画布连线素材收集、轮询及结果回流；`desktop-cyimg.css` 只使用 `desk-` 类和现有画布 tokens。提示词只读连接的文本节点，图片/视频/音频只读连接的素材节点；绘栾节点不提供重复输入框或本地文件控件。以上 JS 在 `desktop-canvas.js` 前按 model → API → controller 顺序加载；`desktop-canvas-nodes.js`/`workflow.js` 只负责生命周期与保存兼容。目录来自后端实时枚举的图像与视频渠道（含 Seedance、MiniMax H3）；保存服务端 Key 后节点状态刷新。API Key 不进入前端，现有 GPT/第三方图像线路不变。

## 历史面板与资产库模块边界（2026-10-16）

`desktop-history.js` 是最近记录面板与资产库工作区的装配宿主：持有面板/工作区共享状态（当前视图、搜索、选择、预览资产等）、事件绑定和 `window.DesktopHistory` 公开接口。有独立职责的部分拆为先于宿主加载的经典脚本：

- `desktop-genie-fx.js`：神灯引擎，面板快照（计算样式烘焙 + 已加载图片内联，SVG foreignObject 光栅化，失败走占位图）与逐行翘曲动画，独占覆盖层画布 `#deskHistoryGenieCanvas` 的绘制，并发布 `window.DeskGenieFX`（`ready` / `snapshotPanel` / `animate` / `clear` / `durationMs`）。不读取任何面板或业务状态；最近记录面板与提示词抽屉都是它的调用方，各自持有面板几何、开合状态和运行序号。

- `desktop-gallery-pinterest.js`：资产库 Pinterest 分页，`window.DesktopGalleryPinterest.create(deps)` 返回实例。持有图板/图片库与同步状态、图板与单图下载、分析弹窗与拆分弹窗（含其事件绑定）以及 Pinterest 统计行；宿主经显式参数注入卡片渲染/选择/预览/通用工具（`escapeHtml`、`mediaUrl`、`copyPinterestSplitText` 等），工作区实时状态只以 getter 传入（`getGalleryView` / `getGalleryQuery` / `getPreviewAsset`），模块不写宿主状态。宿主只经返回的 API 读取 Pinterest 状态（`pins()`、`visiblePins()`、`isPinDownloading()` 等）；剪贴板工具 `copyPinterestSplitText` 也供视频文件夹使用，故留在宿主。

- `desktop-gallery-prompt-sources.js`：资产库「提示词源」分页，`window.DesktopGalleryPromptSources.create(deps)`。持有远程提示词源列表与条目、来源页签与滑块、风格/主体/类型分类筛选、同步运行与轮询、可见条目缓存。宿主的视图/搜索/标签/虚拟网格数据版本号以 getter 传入；宿主的 `invalidateGalleryVirtualData()` 经 `invalidateVisibleCache()` 让模块清空自身缓存。共享虚拟网格的首屏数量常量 `PROMPT_SOURCE_INITIAL_RENDER_LIMIT` 由宿主 `resetGalleryRenderLimit()` 使用，故留在宿主。

- `desktop-gallery-videos.js`：资产库「视频」文件夹，`window.DesktopGalleryVideos.create(deps)`（宿主实例名 `galleryVideoFolder`）。持有视频与资源列表、生成/导入/全部来源切换（含其点击绑定）、文件夹卡片与展开详情/播放、发送到画布和视频统计行。宿主的视图/搜索以 getter 传入；宿主切换分页或关闭资产库时经 `collapseExpanded()` 收起展开的卡片，选择栏文案经 `source()` 读当前来源。历史面板自己的 `isVideoHistoryItem` 与共享剪贴板工具 `copyPinterestSplitText` 留在宿主。

加载顺序：`desktop-genie-fx.js` → `desktop-gallery-pinterest.js` → `desktop-gallery-prompt-sources.js` → `desktop-gallery-videos.js` → `desktop-history.js` → `desktop-prompt-drawer.js`。宿主以 `const genieFx = window.DeskGenieFX;`、`const galleryPinterest = window.DesktopGalleryPinterest.create({...});` 等显式取得依赖，不保留第二套实现。源码契约测试经 `tests/history_js.py` 按 `desktop.html` 加载顺序读取宿主及拆出的模块；边界回归：`tests/test_desktop_genie_fx.py`、`tests/test_desktop_gallery_pinterest.py`、`tests/test_desktop_gallery_prompt_sources.py`、`tests/test_desktop_gallery_videos.py`。

## 资产库对比视口（2026-09-22）

- `desktop-compare-viewport.js` 独占对比视口的缩放、平移、分界线、指针捕获与帧调度；仅接收显式 DOM 引用，无 API、存储或任务状态依赖。两图共用视图变换，左侧 A 为揭示层、右侧 B 为背景层。
- `desktop-history.js` 只负责资产选择、原图 URL、参数面板与 open / close / swap 装配；交换保留当前视图，重新打开重置。
- `desktop-compare.css` 仅作用于对比面板。该 JS 先于 history 加载，CSS 独立缓存版本。
- 支持滚轮定点缩放、按钮、1:1（按 A 图原始像素）、适应画面、拖动平移；分界线拖动独立于平移，原滑杆保留键盘操作。关闭释放捕获与待执行帧；销毁解除监听/尺寸观察。
- 局部测试：`tests/test_compare_viewport.cjs`；跨模块回归：`tests/test_gallery_phase2_regressions.py`。

## Topaz 独立节点（2026-09-22）

- `desktop-topaz-model.js`：节点 schema、默认值、范围、连线兼容与旧 `upscale + topaz-*` 迁移。
- `desktop-topaz-api.js`：认证客户端上的 `/api/topaz/models`、`/api/topaz/run` 适配，snake_case 参数，不拥有任务状态。
- `desktop-canvas-topaz.js`：按模型 profile 的独立表单、安装可用性/依赖联动、状态按钮、节点下挂进度与模型结果串联；显式注入画布/任务依赖。
- `desktop-topaz.css`：独立 `desk-` 样式，复用系统主题/圆角/生成按钮材质；参数平铺，不另建滚动区。
- 上述 JS 在 `desktop-api.js` / `desktop-canvas.js` 前加载；画布只装配节点、工作流、连接和共享输出回调。
- 任务继续使用 `DesktopApi.tasks.generation` / `DesktopTasks` / `DesktopResults`；无 Topaz 专用底部状态或轮询器。
- 原「本地高清放大」只包含 UltraSharp / AnimeSharp。旧 Topaz 节点自动迁移并保留连线、ID 和输出。
- PNG/JPEG/TIFF 输出，TIFF 的浏览器预览由通用后端图像适配提供，下载原件不转格式。

后端接口、支持范围和验证边界：`backend/topaz/README.md`。

CanvasHub keeps its Vanilla JS clients and existing JSON APIs. This is a build
layer, not a React/Vue migration, a new backend, or a runtime dependency.

## Canvas module boundary

`scripts/desktop-canvas-geometry.js` contains stateless rectangle, port-direction,
and connection-path calculations. It exposes the frozen `DesktopCanvasGeometry`
namespace and must load before `scripts/desktop-canvas.js` in the desktop HTML.
The build preserves that order and generates content-hashed URLs for both scripts.

The original canvas helper signatures remain as thin forwarding functions.
Geometry helpers must not access DOM, application state, timers, storage or APIs.
Connection rendering passes optional endpoint rectangles through the host to both
path styles. Classic curves deliberately ignore endpoint rectangles and always
use a single cubic Bezier based only on endpoint positions and port normals,
including backward/vertically stacked layouts and pointer previews. Node-boundary
avoidance remains exclusive to the unchanged straight-mode rounded orthogonal
router. This is geometry only: semantic
right-output/left-input ports, graph direction and persisted edges do not change.
Stateful responsibilities are described below; the host retains global event
dispatch, shared state replacement and compatibility wiring.
Portable curve/style/straight-mode-avoidance regressions live in
`tests/test_canvas_curve_routing.cjs`; the geometry module owns no graph state.
Keep source `?v=` values updated when changing either script. The Mini App does
not load this desktop-only module.

`scripts/desktop-canvas-port-geometry.js` similarly loads before the controller
and exposes `DesktopCanvasPortGeometry` for liquid/droplet port shapes, perimeter
sampling and spring calculations. It preserves the original mutations of
caller-supplied spring objects and path-command arrays. It does not own DOM nodes,
animation frames, hover/drag state, connection rules or saved preferences; these
belong to the connection/port-interaction controllers described below. Its constants
are shared through the frozen namespace,
not duplicated between modules. The previous geometry module is unchanged.

Swell geometry and connection anchors use the node's outer border-box coordinates.
The port-interaction controller places its SVG with explicit pixel dimensions and
compensates for the CSS border at the absolute-positioned padding-box origin;
floating hit targets use the same compensation without changing stored anchors.
Resolved CSS border-box sizes retain fractional image-group dimensions instead
of rounding through `offsetWidth`/`offsetHeight`.
Do not use percentage SVG dimensions here: they shrink the overlay on bordered
nodes and shift both liquid/droplet bulges inside the visible panel. Image-group
inset/outset geometry remains a separate, unchanged surface rule.

`scripts/desktop-canvas-selection.js` exposes a frozen `DesktopCanvasSelection`
factory for selection/group normalization, selection bounds and toolbar rendering,
grouping/ungrouping, alignment/distribution, marquee and snap-guide calculations.
Its controller receives explicit host callbacks and the shared element registry.
`getCanvas()` resolves current state on each call, including after workflow load;
never capture an old canvas object. The group-ID sequence belongs to this instance.
Global pointer/keyboard bindings, selection-change events and saving remain host
callbacks; node-layout implementation now belongs to the nodes controller. Calls
retain their original order. This module
loads before the canvas entrypoint and does not introduce APIs or runtime packages.

`scripts/desktop-canvas-viewport.js` exposes the `DesktopCanvasViewport` factory
for coordinate conversion, transforms, anchored zoom, centering, zoom presets,
wheel gestures and minimap rendering/pinning/navigation. It owns the pan animation
frame, wheel gesture timer/flag and transient minimap projection/pointer session;
graph-render scheduling and other interactions stay
in the host. Explicit callbacks and shared constants preserve selection, layout,
saving and scale-limit behavior. Deferred callbacks resolve the live `getCanvas()`
state. The host reads `isWheelGestureActive()` before switching to pointer pan,
while original event bindings and entrypoint signatures remain unchanged.

Accepted canvas pointer gestures explicitly focus the viewport with
`preventScroll`, since canceled pointerdown does not transfer focus away from
the last node control. The viewport controller owns a one-shot release-click
guard for completed primary pans: the host arms it on pointerup and consumes it
in viewport capture phase, before node buttons/selects receive the click. A new
pointerdown clears it immediately; keyboard/programmatic activation, cancelled
drags, stationary presses and other pointers are excluded. No global click lock
or node-specific activation workaround is used.
Zoom/workflow popovers dismiss when navigation starts instead of depending on
the release click that a moved pan now consumes.

Canvas zoom shares a 10%–180% range with workflow normalization; presets are
10%, 20%, 30%, 50% and 75%, and reset remains 75%. The image editor retains its
independent zoom range. A minimap click centers the viewport on the clicked world
position without changing zoom, nodes, edges or selection. Captured pointer drags
use the same letterboxed projection as rendering, frozen for the gesture to avoid
feedback as visible bounds move. Borders/CSS scaling are accounted for, and move
updates reuse the pan RAF. One save occurs on gesture completion; cancel, blur,
collapse, resize, zoom and pagehide release capture, while workflow replacement
invalidates stale pointers without writing/saving the new state. Expansion refreshes
the final rendered dimensions; delayed layout events use the current pin state.
The host wires
events only. Expanded maps support arrow-key panning (Shift for larger steps);
collapsed maps are excluded from keyboard focus. Regression coverage:
`tests/test_canvas_minimap.cjs`, with synthetic DOM/state and no services/storage.
The preset menu derives its temporary chrome layer from its existing `hidden`
attribute, so all five options stay clickable above history; the normal navigation
and history layers are unchanged. Navigation paint lives in `desktop-canvas-nodes.css`
and top-level stacking remains in `desktop-geometry.css`.
Projection and centering use untransformed layout offsets and live camera state
rather than the last rendered world DOMRect. The canvas uses `overflow: clip`:
focusing or scrolling a preset cannot introduce a second native camera offset.

`styles/desktop-performance.css` registers the viewport-only `--canvas-grid-x`,
`--canvas-grid-y` and `--canvas-grid-size` as non-inherited length properties.
The controller still owns their values and the world transform; descendants
must not consume these background-only values. Otherwise each pan frame
invalidates styles throughout the mounted node/control tree, including offscreen
nodes. Defaults retain the legacy 0px phase / 20px spacing, with no new visual
effects, layers or gesture state. Keep the declarations in the desktop-only
stylesheet and validate grid alignment/zoom plus browser style-invalidation
traces when changing this contract. Unsupported engines retain legacy behavior.

## Desktop canvas business modules

The desktop canvas remains Vanilla JS with ordered classic scripts. In addition
to the existing geometry, port-geometry, selection and viewport modules, the
following controllers load before `scripts/desktop-canvas.js`. Each file exposes
its own frozen `DesktopCanvas*` namespace with a `create(...)` factory; the host
assembles one instance and publishes the existing `window.DesktopCanvas` API.
There is no new framework, browser module loader, backend API or runtime package.

Connection proximity is measured in screen CSS pixels from the semantic input
port's bounds: `d <= 8` captures magnetically; only `8 < d < 20` shows a short,
pinned electric attraction arc. Its eight angular segments blend between bounded
key poses every 80 ms, with a brighter theme-colored halo/body and white-hot core.
The three strokes share one path calculation/RAF; light stays steady rather than
flashing on/off. No blur filter or graph-wide style invalidation is needed.
`connections` shares one nearest-target/policy/
occlusion scan per preview frame and passes phase, pointer and normalized strength
through `updateConnectionProximity`. Snap settles all arc layers in 100 ms and leaves a
static ring; it is not a successful commit. Only successful **manual releases**
notify `playConnectionCommit`; restored/programmatic edges and canceled previews
never trigger success feedback. `connections` retains the last free pointer within
that target's proximity band through magnetic capture, then adds its world-space
approach vector to the commit receipt (release-point fallback for a skipped preview).
This ephemeral metadata is cleared with the drag and never enters saved edges.

`connection-feedback` loads before the host and owns one transient proximity SVG,
one bounded 300 ms directional node recoil (~5.5 px peak at 51 ms, one <1 px
overshoot), a 480 ms split perimeter light, and a 300 ms contact bloom/ring/wire
confirmation. All shapes/offsets use node-local units and inherit zoom; interaction
thresholds remain screen-based. Commit lights the contact immediately without
jumping position; a damped velocity impulse responds from the first frame and
tapers smoothly to exact rest. Approach slope drives a bounded vertical component,
while the left input's inward normal stays dominant. No rotation/scale is applied.
Layered short strokes and a local radial gradient provide a soft light tail without
node-sized blur filters; light and recoil start together, with no waiting stage.
It owns the
visual offset, returned through `getNodeVisualOffset`; `connections` consumes it
for rendering only and owns the adjacency/path index rebuilt with settled SVG.
`refreshNodeConnectionGeometry` updates just the affected incoming/outgoing visual
and hit paths, without recreating the layer, minimap, forms or saved node coordinates.
There is no collision/autolayout/persistence work per animation frame. The host only
assembles callbacks, and port/node disposal explicitly invalidates feedback.
Leaving clears proximity; cancel, Escape, hidden page, blur, reduced-motion changes,
node disposal and new pointer manipulation clean transient resources/rest offsets.
Reduced motion uses static port confirmation instead. No graph/preferences/API changes.

All filenames in this table use the `scripts/desktop-canvas-` prefix and `.js`
suffix:

| Module | Responsibility | Deliberately outside its boundary |
| --- | --- | --- |
| `audio` | Audio material/result-node state normalization, hardware-style presentation, local playback, waveform extraction, binary input/result adapters and player cleanup. | IndexedDB belongs to `desktop-audio-assets`; graph lifecycle to `nodes`; future Provider requests to a separate generation adapter. |
| `workflow` | Workflow schema/version normalization, portable snapshots, file naming and save/load adapters. | Applying a snapshot and replacing shared application state remains a host operation. |
| `prompt-document` | Prompt segments/schema, image-reference semantics, materialization/fidelity, document versions/history model, generation metadata and connected-text prompt composition. | Editable DOM, selection/caret handling and Provider requests. |
| `text-editor` | Text-node presentation/aliases/styles, contenteditable documents, tokens/mentions/caret, editing undo/redo, token migration/freezing, prompt-target adapters and polish-result presentation/application. | The polish API request belongs to `generation`; document model rules belong to `prompt-document`. |
| `image-group-model` | Image-group items/roles/sizes, grouping/ungrouping, edge migration, persisted item ordering, node presentation and image-role prompt constraints. | Gesture timing, FLIP/proximity effects and prompt-token DOM updates. |
| `image-group-liquid-field` | Overlay-local SVG displacement/mask/radial-wave painting and bounded procedural-field caches, explicitly injected into interaction. | No graph state, pointer/RAF lifecycle, image-pixel readback or model mutation. |
| `image-group-interaction` | Group sorting gestures, FLIP/merge/split effects, proximity dwell/preview/release/drop and item focus interactions. | Actual group mutations are submitted through model callbacks. |
| `image-editor-tools` | Fabric object creation/modification, shapes/arrows/pins/text, selection colors, drawing tools and cursor assets. | Editor sessions, Fabric canvas ownership, history and generation submission. |
| `image-editor` | Editor modal/session, viewport/zoom, Fabric lifecycle/events, project/history serialization, mask/annotation export and open/save/close behavior. | `submitImageEditor` belongs to `generation`; file/media preparation belongs to `media-import`. |
| `media-import` | MIME/header/filename checks, image reading, external URL/HTML input, drag/drop/paste, image-node creation/replacement/result feedback and historical/video-asset import. | New upload/generation APIs, reference ordering policy or changes to media authentication. |
| `references` | Current reference stores, source normalization, connected-reference order, thumbnails, deduplication/limits, history/layout attachments and asset-parameter application. | Prompt-document token semantics and binary/remote file preparation. |
| `nodes` | Node lifecycle, node palette, non-model node presentation, graph DOM/layout operations, layout/pose inputs and existing migration adapters. | Shared pointer/keyboard dispatch, graph-frame scheduling and model forms. |
| `model-nodes` | Existing GPT/Google/Comfy/video/file/upscale controls, model catalogs, node templates, form-to-state adapters and media-size presentation. | Task submission/polling/cancellation. |
| `connections` | Shared type compatibility, menus, SVG edges, magnetic input-port capture, nearest compatible proximity target, connection previews, edge mutation and connect/detach/drop lifecycle. | Global pointer dispatch and port animation. |
| `port-interaction` | Liquid/droplet port DOM, hover/hold/release, source spring lifecycle and connection anchors; forwards node disposal. | Connection rules belong to `connections`; commit/proximity feedback to `connection-feedback`; pure shape/spring calculations to port-geometry. |
| `connection-feedback` | Ephemeral attraction/snap/commit presentation, temporary visual node offsets, animation lifecycle and cleanup. | Edge mutation/compatibility/adjacency and targeted wire rendering belong to `connections`; never mutates persistent coordinates or triggers collision/layout. |
| `generation-config` | Generation request/output configuration adapters, including existing form synchronization, Provider normalization, reference order and expected-output counts. | Executing a request. These adapters are not pure/read-only: their existing sync calls can update node/parameter state. |
| `collision` | Optional drag collision solving, passive-group translation and short-lived smooth position targets. | Preference persistence belongs to `desktop-preferences`; settings presentation to `desktop-settings`. No graph topology, Provider or image-group merge ownership. |
| `generation` | Existing image-editor/video/polish/upscale execution, video polling/cancellation, output slots/result propagation and upscale chaining. | Backend Provider fallback, archive persistence, Telegram delivery or new request schemas. |

`desktop-canvas-nodes.js` owns the sidebar palette's image/video/audio/enhance/general
grouping and renders the injected `NODE_MENU_ITEMS` catalog without copying node
definitions. Native named `details` provide a one-open-group accordion, initially
opening the first nonempty category; open/collapsed state stays in the menu DOM
across closing/reopening, not workflow or persisted settings. Unclassified catalog
entries fall back to General so new nodes cannot disappear. Buttons keep the same
click/drag payloads. The shared button renderer and connection picker remain flat;
connection compatibility/search are still owned by `connections`. Host event
dispatch closes the palette on Escape, with focus returned by the node controller.
`desktop-canvas-nodes.css` owns the 320px palette, compact two-line items and bounded
internal scrolling in both themes. No module or load-order change is required.
The rail's glass is painted on its noninteractive `::before` layer in
`desktop-shell.css`, not on the palette's ancestor: this lets the palette's own
backdrop blur sample the canvas. Its light/dark translucent fill stays in the
palette tokens; do not mask a nested backdrop-root problem with an opaque fill.

`desktop-canvas-image-group-liquid-field.js` loads before `image-group-interaction`
and the host explicitly injects its `create`/`render` port. It owns only the
temporary SVG filter and bounded paint caches; interaction owns containment,
elapsed time, the single RAF and all release/drop/model lifecycle decisions.
There is no reverse graph/state access or independent animation loop.

The photo, its rim and its same-sized opaque SVG silhouette share one local
displacement field. Approaching/partial entry masks noise displacement itself:
contact-facing pixels liquify first, with little distortion at the far side
(not an opacity fade between photo copies). Late containment continuously
blends into a full-image field. Once inside, positive radial travelling waves
with `sin(k*r - omega*t)` expand from the photo centre, with low-frequency noise
breaking the circular rim. Time is wall time, not RAF count; synthetic coordinate
SVGs contain no photo pixels/network references. Radial paint updates are capped
at 30 Hz and reuse at most 36 tiny wave SVGs per overlay. Reduced motion skips
displacement and the animation loop; settled contact-only previews stop their RAF.

The mother contour is locally pulled before the joined silhouette receives a
single outer edge/shadow; no rigid circular underlay or independent incoming
shadow remains. HTML thumbnail stacking, badges and titles stay crisp. Held
entry and every visible drop frame remain liquid until the completed group
presents clear photos. Definitions/caches disappear with the overlay. Release,
drop, item roles/order, dwell thresholds, model callbacks, graph edges and source
data retain their existing contracts. Regression: `tests/test_image_group_liquify.cjs`;
served-page pointer/frame checks use synthetic images with backend requests isolated.

### Audio material/result node

`desktop-audio-assets.js` and `desktop-audio-meter.js` load before `desktop-canvas-audio.js`, which loads before
the other canvas controllers and the host. `styles/desktop-audio.css` scopes the
powder-blue/white player and dark-graphite surfaces to desktop audio nodes. Daylight
consumes the existing canvas surface, text, border and shadow tokens; the black LCD
and round transport keep the hardware identity without a separate gray theme.
All audio-domain node shells (the player and five music nodes) must use the shared
`--desk-node-radius` alias of `--desk-radius-node` (currently 8px), like other canvas
nodes. Do not introduce larger per-domain shell radii. Internal circular transport
controls remain circular; port geometry reads the resolved shell radius.
The node palette
adds **音频节点**; this is a material/result player, not an audio generation model.
Playback, seek, ±10-second skips, stop, loop, mute/volume and original-file download
are functional. No placeholder recording or splitting controls are exposed.

The audio controller receives the asset and meter adapters, live node/element getters, an
HTML escaper and a save callback. It owns native players, object URLs, decode jobs,
listeners and playback RAFs. Only metadata, a local asset ID (or durable media URL),
up to 240 waveform peaks and volume/loop preferences live in canvas node state.
Current time and autoplay state are not persisted; playback does not serialize
canvas state every frame. Replacement, deletion, workflow load and page exit
release playback resources. Late async work checks live node/source identity.

The timeline preserves one real sample shape: an ID-free nested SVG reveals its
played-color copy up to native `currentTime / duration`. The existing player RAF
updates only this clip viewport and cursor, not the waveform path or saved state.
A small cursor glow follows playback and fades out on pause/end; stop resets the
clip and cursor. Reduced-motion disables decorative fades, not the progress cue.
Both imported materials and model results use this same rendering path.

`desktop-audio-meter.js` owns a read-only `captureStream` / Web Audio signal tap.
Its explicit `create(audio)` interface returns `start`, `pause`, `reset`, `sample`
and `dispose`; it has no canvas, DOM presentation, storage or animation-loop
dependency. The controller samples it from the existing playback RAF, capped at
30 Hz. The LCD shows stereo-output RMS dBFS and held sample peaks; mono is upmixed
to both output channels. Captured samples are adjusted once by the native element's
volume/mute, not system speaker volume. The analysis branch never connects to an
audio destination, reroutes playback, requests a microphone or sends audio data.
Capture/context creation is lazy on play. Source replacement resets readings,
stops old tracks and reuses the element's one capture tap; a fresh analysis window
prevents stale levels from the preceding source. Pause suspends analysis; disposal
closes/disconnects its resources and also stops queued late capture tracks.
Unsupported/blocked capture displays an unavailable meter without interrupting
native playback. No level values or capture state enter workflow serialization.

Audio binaries use the separate `canvashub_audio_assets_v1` IndexedDB store; imports
are limited to 100 MB each. Native playback supports browser-decodable audio.
Waveforms use actual local samples, with decoding limited to 24 MB / 15 minutes
to bound memory work; large files remain playable without a fabricated waveform.
Displayed sample rate is the Web Audio **decoded** rate, not an asserted source
recording rate. URL-backed results use native playback and do not add raw fetches.

`exportWorkflowSnapshot()` stays synchronous and lightweight (local asset IDs).
The existing async **Save workflow file** flow embeds local audio in its cloned
JSON payload; loading that file rehydrates independent binary storage. Missing
assets block portable export rather than silently dropping audio. Published local
assets are retained when nodes are replaced/deleted so older local snapshots stay
recoverable; node deletion releases the player/URL, not stored media. Clearing
browser site data removes these local assets; portable workflow files retain them.

Three explicit Promise-returning facade ports prepare future model integration:

- `DesktopCanvas.importAudioNodeFile(nodeId, file)` imports a local audio file.
- `DesktopCanvas.setAudioNodeResult(nodeId, result)` accepts `{ blob }` or a durable
  `{ url }`, plus `name`, `mime_type`, `file_size`, `duration_seconds`, `task_id`.
- `DesktopCanvas.getAudioNodeInput(nodeId)` returns `null` or
  `{ data_type: 'audio', blob, url, name, mime_type, duration_seconds, file_size }`.

Input/output ports are semantically audio-only. The shared compatibility table
currently permits no audio connections because existing image/video models do not
declare audio support. Future model adapters must add explicit accepted types and
use these ports; do not bypass compatibility or place Provider/auth code here.

### Connection magnet and node status paint

`desktop-canvas-connections.js` owns one type compatibility table used by the
node menu, target highlighting, magnetic capture and final edge validation.
During a connection drag, the nearest visible compatible input port captures the
preview within 8 CSS screen pixels of its hit box (Euclidean corner distance).
DOM bounds already include canvas zoom; do not multiply the threshold by zoom or
devicePixelRatio. Preview and pointerup both resolve live nodes and current bounds;
capture never commits early. Releasing creates the existing edge/input-role shape.
The controller owns the temporary screen pointer and snap target, and clears both
with the preview on completion/cancellation. The host only forwards pointer,
Escape and blur events. Existing compatible-body drops and blank-canvas menus stay
available; floating port springs and committed right-to-left routing are unchanged.

`styles/desktop-canvas-nodes.css` maps success status/pill labels and online video
runtime labels under `.desk-node` to the footer's success-soft silk tokens. This
paint-only override preserves label geometry, warning/error states, Settings and
the saturated service indicators in the shell.

### Shared node frames, depth and state icons (2026-10-04)

`desktop-geometry.css` reserves a 1px solid structural border and the shared
8px node radius on every ordinary shell. A structural border need not look like
a hard outline: normal paint uses a faint border and shallow, layered contact
shadows from `desktop-tokens.css`. `--desk-node-stroke` is a defined compatibility
alias, not a component-local variable. `desktop-canvas-nodes.css` applies the same
depth to non-glass domain shells without changing their backgrounds or internal
controls, then paints selected/connecting/pending/drop-target frames with the
common blue/orange selection color after normal material rules. A committed
connection is not selection: `has-settled-port-left/right` only exposes local
port caps, and must not change the shell or image-group mother frame. Completed
jobs likewise keep their status feedback inside the node. Visible image/video
surfaces own media depth; selected media does not double-stack root and preview
shadows. The image-group root remains borderless: its mother keeps the existing
2px, outset liquid selection frame and local radius, with the same semantic state
color. Liquid geometry, grouping/sorting timers and the SVG goo field stay local.
Panning/wheel transforms temporarily suppress ordinary/media shadows through
`desktop-performance.css`; no permanent compositor promotion is added.

`desktop-state-icon.js` loads before all consuming views/controllers. The canvas
host injects its `stateIcon` interface explicitly into audio, music, Topaz image,
ReShot, Topaz Video and its workbench. `html(icons, initial)` renders one SVG with
retained, static component-owned glyph layers; `paint(svg, state)` only changes
the current layer. Never pass user-authored SVG fragments to this interface.
Labels, disabled/aria-busy state, jobs, playback, requests and storage remain owned
by callers. CSS crossfades opacity/scale with a brief 1px glyph-only blur; spinner
rotation lives on a nested glyph and pauses when inactive. Repeated polls and
rapid reversals do not replace DOM, restart spinning glyphs or create JS timers.
Reduced-motion disables these glyph transitions, blur, scaling and rotation.

Ordinary mounted panels/popovers use a 120ms exit, a quiet 2px/0.995 closed pose
and their existing 180ms opacity / 280ms transform entry. Menu close finalization
and cancellation still belong to their existing controllers, preserving quick
reopen and keyboard focus. Notification dwell remains 3600ms; workbench mount,
theme reveal, prompt-genie and image-group liquid lifecycles are not retimed.
Portable regressions: `tests/test_node_surface_contract.py`,
`tests/test_state_icon.cjs`, `tests/test_exit_motion_contract.py`, plus existing
port geometry and domain tests. Served-page probes use synthetic images/media,
intercept backend APIs and keep reports under ignored `tests/output/`.

### Drag collision lifecycle

`desktop-canvas-collision.js` loads after the other canvas modules and before the
host. `solve(rects, movingIds, options)` is stateless; `create(...)` owns only
per-drag targets/originals and its animation frame. Dependencies are explicit.
The current canvas owns actual displayed x/y coordinates: each frame applies
layout and renders edges from those same positions, then performs the final drag
save after release and settling (existing selection saves remain unchanged).
A new drag/resize settles pending motion first; cancellation restores
the drag transaction; workflow replacement discards it. Deferred work checks
canvas and node identity and never recreates deleted nodes. There is no new global
undo subsystem. Multi-selection stays fixed, passive groups move rigidly, image
merge candidates are exempt, and snap ignores previously displaced nodes.

The setting is `DesktopPreferences.state.canvasCollisionEnabled` (strict boolean,
default false) in the existing local preference store, not backend settings or
workflow JSON. Switching it does not reorganize an idle canvas. The System tab
uses the existing canvas-interaction segmented controls; no extra CSS or runtime
dependency is required. Normal resizing/generation do not initiate collision
solving. Only a drag-connected collision chain is moved, not all existing overlaps.

### Host responsibilities and compatibility wiring

Agent prompt actions use `text-editor.fillNearestInputPrompt` with explicit
`createIfMissing` to create a missing live image model through the node lifecycle;
ordinary callers keep the missing-model error. The Agent adapter owns explicit
reference-image connections through `DesktopCanvas.connectNodes`. It acknowledges
the actual `input_node_id`, which `backend/agent_runtime.py` persists and uses for
subsequent generation instead of assuming the initial workflow snapshot's default
`input` exists. Video actions disable generic image-model creation. Workflow file
normalization retains its legacy default-node compatibility behavior.

`desktop-canvas.js` intentionally remains the integration host. It owns:

- Shared lexical state, common constants, the element registry and current
  interaction/editor/file-picker selections that cross module boundaries.
- Element collection and application initialization; factory assembly occurs
  after shared bindings exist and before the public API is published.
- Global event registration/delegation, keyboard/focus policy, the shared
  pan/drag/resize dispatcher and graph-render frame scheduling. Domain-specific
  widget/Fabric/port listeners may be bound inside the owning controller.
- Selection-change notifications, applying a workflow snapshot/state replacement,
  common download helpers, draft clearing and workflow-dock integration.
- Thin compatibility functions for existing callers, dependency callbacks and the
  unchanged public `window.DesktopCanvas` entrypoints.

Do not add a second implementation to a host forwarding function. Put changes in
the owning module and preserve the host boundary until its callers and event
wiring are deliberately migrated together. Likewise, do not let a module reach
into another controller's private state as an unofficial shortcut.

### Shared state, private caches and deferred work

Host lexical dependencies are passed explicitly. Reassignable cross-domain
bindings use live ports such as `activeInteractionRef.current`: a getter/setter
reads and writes the original host binding. Shared `const` objects, Maps and the
`els` registry retain their original object identity. Existing application
services such as `DesktopState` and `DesktopApi` remain the same global
singletons; introducing these controllers does not create duplicate services.

Read `DesktopState.state` / its current `canvas` when executing work. Do not
capture a state/canvas snapshot in `create()` or copy a shared reference store.
This applies especially after workflow load and inside Promise, timer, RAF and
Fabric callbacks. Existing local captures intentionally used by an operation are
not silently rewritten as part of module extraction.

Only state whose uses are entirely in one domain is private to that controller:
for example prompt/image-group ID sequences, text-style/polish UI state, group
sorting RAF/cleanup caches, the editor theme observer, connection-preview/menu
state, liquid-port animation state and the upscale-install Promise. Other
shared state remains host-owned even when one domain is its main writer. In
particular, the editor element/canvas/session handles and workflow-shared video
polling Map must not be copied into isolated controller caches.

Factories create their closures/private initial values but perform no DOM/API
work or event registration while assembling dependencies. Cross-controller
callbacks can therefore refer through the host without creating an eager
initialization cycle. The returned API objects and namespaces are frozen; the
application's mutable state is not frozen by this boundary.

### Async compatibility contract

The original async implementation and its default parameters live in the domain
module. Its host compatibility function is an ordinary forwarding function using
the original `arguments`; placeholder defaults preserve the function's `.length`
without pre-evaluating the real defaults. It returns the module's Promise
unchanged instead of wrapping it in another async function. This avoids an extra
Promise-adoption microtask and preserves tested result/rejection ordering and
single evaluation of defaults.

Synchronous forwarding preserves existing argument/default behavior; the current
destructured options parameter is normalized once rather than reading caller
getters twice. Keep returned values, thrown errors, callback order and Promise
behavior compatible. `AsyncFunction` constructor/prototype/source-string
reflection is not a supported compatibility guarantee; no runtime consumer was
found relying on it during this extraction.

### Verification and deployment boundary

- Verify the actual desktop HTML script order and cache-busting values; a new
  controller must load before the host. Source JS/CSS changes still require
  updating `frontend/desktop.html` `?v=` values. The build generates separate
  content-hashed script URLs and preserves order.
- Validate source and separately built `/desktop.html` in isolated state, not
  just JavaScript syntax or a compiler exit code. Exercise existing canvas,
  prompt/group/editor/import/reference/workflow interactions and mocked
  generation success/failure/cancellation/fallback paths. Keep real Provider,
  Telegram, auth secrets, archives and user task state out of refactor fixtures.
- Check body/signature/dependency extraction as well as behavior: returned values,
  errors, state mutations, callback/DOM order, async timing and state replacement.
  A test that searches only the former monolithic file is not evidence that a
  migrated feature disappeared. Report legacy source-location failures honestly;
  tracked tests are not rewritten or committed without maintainer authorization.
- Existing generation request fields, protected API adapters, Provider fallback,
  original-image archive/sidecars and uncompressed `sendDocument` delivery remain
  separate invariants. This frontend split does not change them.
- TypeScript/Node used by local migration/testing and the existing build tooling
  are development-time tools only. Normal Python/backend or installed-app startup
  gains no Node/npm requirement. The Mini App does not load these desktop modules.
- Source refresh, selecting a new built frontend, Docker deployment, Electron
  packaging and backend drain/restart remain separate operations. Passing these
  module checks does not by itself release a container, regenerate a frozen
  Python runtime, produce/install a signed app or validate Windows hardware.
  Runtime data must remain outside disposable build/release directories.


## Build and verify

From the repository root, with Node.js and npm available on the **build machine**:

~~~sh
npm ci --prefix frontend
npm run build --prefix frontend
npm run check --prefix frontend
~~~

The artifact is dist/web/, containing sibling frontend/ and static/ directories.
No backend code, account configuration, database, node_modules, or build tooling
is copied into it. The original HTML, JS and CSS are not rewritten.

- Classic scripts stay separate and retain their shared global bindings and HTML
  load order. Third-party classic/UMD scripts are copied without transformation.
- The existing pose ES Module is bundled, including its /static/pose/ imports.
- Scripts, stylesheets and bundled CSS assets receive content-hashed filenames.
- Both desktop and Mini App HTML references are generated from build outputs.
- asset-manifest.json records resource hashes, source hashes, immutable URLs,
  and compiler warnings. The check command detects changed sources and damaged artifacts.
- CSS ordering, inline HTML handlers, URLs of JSON APIs, media authentication and
  provider routing stay unchanged. Optional local GLB models retain their existing
  inclusion/fallback behavior.

The builder stages and verifies a complete artifact before replacing an earlier
builder-owned output. Failed builds preserve the previous artifact. It refuses
to replace unrelated directories or outputs containing unmanaged files.
Output/source overlap checks resolve existing parent-directory symlinks as well,
so an output alias cannot silently write a build into the source tree.

## Run with the existing backend

Normal startup remains unchanged and **does not need Node.js or a build**:

~~~sh
python3 server.py
~~~

To explicitly select a built frontend:

~~~sh
CANVASHUB_FRONTEND_DIR="$PWD/dist/web/frontend" python3 server.py
~~~

In PowerShell:

~~~powershell
$env:CANVASHUB_FRONTEND_DIR = "$PWD/dist/web/frontend"
python server.py
~~~

Only web-resource selection changes. Settings, task databases, archives and auth
files continue to use the original backend data-path configuration. The presence
of a dist/ directory never silently switches normal source startup to an old
build. Unset CANVASHUB_FRONTEND_DIR to return to the source frontend.

The backend still serves the HTML entrypoints without storage caching. Generated
immutable resources use long-lived caching; legacy source URLs keep their existing
?v= behavior. Source-only desktop changes still need the existing version bumps.

## Packaging and deployment

Electron pack, dist:mac, and dist:win build and check the web artifact first, then
copy its two resource directories into the existing app-resources layout.
Installed users do not install npm/esbuild; one-click startup stays unchanged.
The normal Electron development command continues to use source resources.

This first step does **not** change Docker packaging, split API origins, or add a
development proxy. Independent hosting must preserve /api/* and authenticated
media/file routes at the same origin; simply hosting the HTML cannot replace the
Python backend.

Do not rebuild a directory that is actively serving a release. Build a separate
output, verify it, and switch resources during the appropriate drain/restart or
app-install operation. Directory replacement is not a live-deployment guarantee:

~~~sh
node frontend/tooling/build.mjs --outdir dist/web-next
node frontend/tooling/build.mjs --check --outdir dist/web-next
~~~

No build step runs in watchdog or end-user startup scripts. Runtime/user data must
never be placed in these replaceable artifact directories.

### Verification and release boundaries

Verify source startup and a separately selected build with the same backend and
isolated data before changing the running service. Compare authentication,
generation submission/status, history, original downloads, local fonts, and both
HTML entrypoints; a successful compiler check alone is not browser acceptance.

This artifact contains web resources only. The backend-served local `font/`
directory is not copied into it, and the existing Electron resource map does not
bundle that directory. Testing fonts against a source resource root does not
prove those local fonts are present in a newly installed app.

Electron's frontend build step also does not rebuild the frozen Python runtime.
Regenerate that runtime from the intended backend revision before making a real
release. Resource-map/type checks and a staged-resource smoke test are separate
from a signed installer, installed-app, or Windows acceptance run.

## Google OAuth account pool (2026-09-14)

`desktop-google-pool.js` owns Google settings UI state, OAuth session presentation and
account actions. Load it after `desktop-api.js`, before `desktop-settings.js`; the
settings host only injects request/render callbacks and delegates events. GPT settings
remain in their original implementation. API calls use the existing authenticated adapter.

`googleProviderRoute` belongs to canvas parameters. `desktop-canvas-model-nodes.js`
renders and synchronizes both static and dynamic controls; generation-config and
references preserve it across submission/history reuse. `desktop-api.js` converts it
to `google_provider_route` for existing generate/edit/batch endpoints. Old workflows
default to `third_party`; explicit `google_pool` never changes GPT routing. Assets
are cache-busted in `desktop.html`. Google account credentials never enter canvas state.

## Settings presentation boundary

Settings typography, control sizes, compact form rows and category alignment are
owned by the Settings section of `styles/desktop-geometry.css`, loaded after the
feature and shared-control styles. Its compact size variables are scoped to
`.desk-settings`; canvas nodes, gallery and authentication keep their own scale.
`desktop-settings-auth.css` remains the theme-paint adapter, and settings/API state
remains in `desktop-settings.js` and the independent Google controller. Wide
textareas keep stacked labels; ordinary fields and checkboxes use aligned rows.
All eleven Settings tabs share the compact inspector geometry in
`styles/desktop-geometry.css`: 24px navigation/disclosure, single-line controls,
and complete segmented tracks; 11px readable text, medium-weight section/navigation
labels, 500-weight field labels, regular field values/help, and a 15px panel title.
Navigation retains a separate height variable so the expanded rows stay aligned.
Segment outlines use inset paint, not extra padding/border that enlarges the track.
Single-line fields in nested runtime and supervisor sections also use aligned rows;
wide textareas and native file pickers remain stacked. Secret inputs reserve room
for a separate 36px trailing clear action without changing DOM/keyboard order or
confirmation behavior. The label column is 100px to accommodate mixed Chinese and
English field names.
`desktop-controls.css` keeps category/mode selection flat with a soft accent in
both themes, and owns distinct hover/press/disabled states plus an inset focus ring.
Primary save commands retain shallow elevation; Settings-only header/secondary
commands and static cards do not cast heavy shadows. `desktop-settings-auth.css`
uses quiet transparent nested sections with dividers instead of duplicate frames;
real model compatibility/error frames and online/offline colors are preserved.
Multi-line fields remain vertically resizable; workflow thumbnail cards and switch
tracks retain their own geometry. The panel caps its width at 460px and stays within
narrow windows; account actions wrap separately on small screens. Supervisor status
actions align beside the status on desktop and below it in narrow windows.
The settings-only LoRA key field occupies its own full row.
The category disclosure is a neutral icon command, not a selected category:
`desktop-controls.css` owns its normal/hover/pressed/disabled states and keyboard
focus, while `desktop-geometry.css` fixes its square hit area. Expansion still
belongs to the existing Settings controller and only rotates the chevron.
Model-tool inspection results use the 11px caption scale and retain their
compatibility/error treatment. Static conversion and VAE guidance lives in the
existing contextual help drawer opened by the Settings header info button.
`desktop-settings.js` owns that help content and drawer lifecycle; Krea/Qwen tools
render only configuration, actionable preparation/current VAE state, real
inspection results, progress and errors. An idle inspection adds no placeholder
frame or guidance paragraph to the main form. No conversion API, draft state or
task scheduling moves into the help presenter.
The drawer's geometry uses a shrinkable column/header and wraps long technical
tokens, with a 24px close command. It scrolls independently without enlarging the
main form; ordinary task/status tooltips keep their existing geometry.

`styles/desktop-settings-auth.css` maps all Settings text fields (including model
tools outside legacy settings forms) to the shared light/dark material.
Standalone model-tool commands, destructive actions, native file buttons and
shared command states/focus are normalized in `desktop-controls.css`.
Settings custom selects and their native fallback use the same field border,
surface and ink as adjacent inputs, not the nearly-white generic button edge.
The Settings-scoped select rules keep distinct hover/pressed/open/keyboard focus
and disabled states; select geometry, portal menus and non-Settings controls are
unchanged.
Domain controllers continue to own configuration drafts,
API requests and saving; presentation rules must not change that behavior or
shrink controls in the canvas, asset library, Auth or mobile client. Portable
contracts live in `tests/test_settings_control_style.py`.

Success labels (summary, account/path badges, pool chips and completed actions)
use the same soft green silk tokens as the footer task/queue/archive chips in both
themes. Their material placement and shadow stay scoped to Settings; saturated
service badges, canvas result states and warning/error colors are unchanged.
Changes must check custom selects as well as native inputs, all settings tabs,
light/dark themes, narrow windows, expanded categories and keyboard focus against
the served desktop page. No runtime/API or persistence change is implied.

## Music domain (mlx-Yue)

Audio materials/results still use `desktop-canvas-audio.js` and its independent asset store,
waveform and meters. Music inference does not become an image Provider.

Load order after the audio modules, before canvas assembly:
`desktop-music-api.js` (existing authenticated transport), `desktop-music-model.js`
(pure node/request/connection contract), `desktop-music-score.js` (lazy local ABCJS rendering
and exports), `desktop-music-view.js` (five node presentations), `desktop-music-workflow.js`
(direct reference planning, dependency ordering and cache validity), `desktop-canvas-music.js`
(controller, async lifecycle, graph inputs, job polling and result publication).
`desktop-music.css` consumes canvas tokens and is scoped to `.desk-node--music`.

The host only injects live state, graph callbacks, text materialization and the existing audio
API. Node lifecycle and workflow normalization recognize `music_generate`, `music_transcribe`,
`music_abc`, `music_score`, `music_compare`. The connection controller combines its original
image/video table with an injected music contract; menu, 8px snap and final creation use the
same rule. Text edges carry explicit `style`/`lyrics` input roles, switchable in the generation
node. Style and lyrics are supplied exclusively by connected text nodes, not inline fields
or hidden fallback strings. Legacy inline fields are retained in old snapshots for data
compatibility but not submitted. Missing/disconnected/empty text inputs fail before submitting.
Music score and audio output roles cannot connect to image models.

Inference nodes contain parameters, compact input-role indicators and current-job controls.
The music generation node uses the model-node landscape footprint (720 × 460), with two
always-visible rows of four aligned parameter columns (no advanced accordion), a middle
input-reference area with the FLAC/WAV “生成格式” selector beside the linked sources,
and a fixed bottom-right run control. Its parameter/body wrappers are
ordinary non-scrolling, non-clipping layout containers so anchored menus remain visible.
Geometry is owned by `desktop-music-model`, markup by the music view and styling by
the music stylesheet; existing node/workflow normalization also upgrades old narrow nodes.
Visible audio parameters, edge roles and job lifecycle are unchanged; other music node
layouts are unaffected. No image-model classes, controls or Provider state are reused.
ABC/semantic sampling use the pinned upstream `GenerationConfig` defaults, not UI JSON
inputs or frontend copies of numeric defaults. Canvas submissions omit both sampling
overrides; legacy snapshot strings remain recoverable but are not silently reapplied or
parsed. Existing running-job specs/results and the backend's explicit-override API remain
unchanged. Native defaults are recorded in the generated `config.json` for reproducibility.

The generation node owns `audioFormat` (FLAC by default, or WAV), persisted with the
workflow and translated to top-level `audio_format` by the request model for songs only.
Only the completed job's `spec.audio_format` selects its published/reconnected/compared
audio, never the current control value or manifest ordering. Old jobs remain FLAC-compatible.
Generation/transcription panels show only compact state badges and run controls; generation
retains its suspended progress overlay. Detailed status/time/errors belong to the shared
bottom status area, not a node-local log. Generation still omits artifact-file buttons. The manifest and result spec
stay in state for downstream nodes and future asset management.

`DesktopMusicModel.taskFeedback` adapts matching audio receipts plus transient submission,
dependency-wait, cancellation and local-error state to a presentation-only report.
`desktop-canvas-music` emits changed reports through an injected `reportStatus` callback;
the host wires it to `DesktopResults.reportTaskStatus` and forwards canvas selection to
`showStatus(nodeId)`. No audio task enters `DesktopState.outputs`, no image submission or
polling path is reused, and no extra log endpoint/history store/timer is introduced.
The existing bottom detail/copy panel shows node/task identity, local runtime, actual stage
counts, terminal elapsed time and multiline raw errors. Transient notices cannot retarget
the detail snapshot. Identical music polls do not steal the displayed context; selecting an
inference node explicitly rebinds it. New submissions/local validation failures do not inherit
old job IDs or errors, and stale async replies are ignored. Publication errors are distinct
from generation errors, and success is reported only after result publication finishes.
Reports with `raw_detail` opt into a larger, viewport-bounded detail panel with scrollable
logs; ordinary image/settings tooltips keep their existing sizing.

The footer task-log trigger is a stationary information label sharing the
`--desk-status-ok-*` ink/background/border with the today/queue chips in both themes.
Its dedicated `--desk-status-feedback-shadow` uses only inset layers (dark upper
edge, soft cavity and lower rim highlight), with no outer drop shadow, so the log
reads as a recessed slot. Other status chips keep their existing elevation. Hover,
focus, press and open states do not change its material or position. A static keyboard
focus outline remains. Task tone still drives the detail summary, and the service,
warning/error indicators and global stop action retain their semantic styling.
`desktop-results.js` owns one horizontal dock for the label and task details:
its right edge meets the expanded Recent Records panel's left edge without overlap.
When history is collapsed/offscreen, the dock falls back to the visible footer edge,
before the stop control. Footer indicators scroll independently in small windows.
Resize/history observers coalesce placement in one animation frame and disconnect
on reinitialization; they do not read history's private state or change task ownership.

Music generation/transcription have no node-local task stop button. The music controller
exposes ephemeral `getCancelableTasks()` commands through `DesktopCanvas.getCancelableMusicTasks`;
the existing canvas stop action dispatches them alongside image/batch cancellation. Audio IDs,
pending-submit stop intent, deduplication, late-response guards and polling stay in the music
controller. Submitting tasks remember a stop intent and cancel once the backend returns an ID.
Playback stop buttons still control only their own players.

Every canvas "开始生成" button (input node incl. the static default one, Qwen, Krea,
绘栾, Topaz Gigapixel, music, ReShot, Topaz Video) is one component:
`desk-generation-action` plus an optional domain class, never `.desk-button` /
`.desk-button--generate` (2026-10-09). `desktop-controls.css` is its single style
source — node-radius 72px square, lightning/label layout, theme tokens, hover/pressed,
`:disabled` (muted) and `[aria-busy="true"]` (keeps the primary finish while a job
runs, even when disabled) — without naming domains. Controllers only set `disabled` /
`aria-busy`; footer placement (`margin-left`) stays in each node's stylesheet. Comfy,
upscale and video-inference runs keep the compact `.desk-button--generate` variant. Music button state is derived by
`desktop-music-model.js` from the controller's actual job plus transient submit,
upstream-wait and cancellation state. `desktop-music-view.js` paints labels,
accessible busy state and icons without replacing the spinner on every poll.
`desktop-state-icon.js` / `desktop-motion.css` own retained glyph transitions and
reduced-motion support; `desktop-music.css` keeps music-specific progress motion.
No second job state store, image-domain dependency or animation loop is introduced.
The shared icon helper loads first; model → view → controller order is unchanged.

Music generation also owns a per-node suspended progress view using the shared
`desk-progress-float` material, not the singleton image overlay or image task state.
The node-relative overlay follows node movement/zoom automatically and is visible
only while busy. The music model derives stage/count text and phase percentages
from the controller's latest matching job observation; unknown work totals use an
indeterminate flow, not a time-based estimate. A single controller display clock
updates elapsed time for all active music nodes, stops when idle, and is cleaned
up with node/workflow disposal. It performs no extra API polling. Existing submit,
queue, upstream-wait, cancellation, recovery and result publication paths remain
the only owners of task lifecycle.

Music selects reuse the shared select component's existing anchored mode. Do not add a
portal or scrolling/clipping parameter wrapper to work around an unnecessary layout boundary.

In the pinned mlx-Yue version, audio reference/cover means audio → transcription → ABC →
generation, not waveform/voice conditioning in `SongRequest`. Connect an audio node to
`music_transcribe`, then connect that node directly to `music_generate` with style/lyrics
text inputs. The generation action runs any required transcription and waits for successful
ABC publication before submitting the song. Raw `audio → music_generate` remains incompatible;
supplying ABC requires `full`/`melody`, not `off`.

The standalone transcription action is derived from live outgoing edges, never stored as a
second canvas flag: hide it when at least one direct `music_generate` consumer exists; show
it again after the last is disconnected/deleted. Score/compare-only consumers keep it visible.
An intervening editable ABC node is a manual editing boundary, not implicitly overwritten or
auto-executed. Merely connecting nodes does not run inference.

The workflow planner has no DOM, provider, task queue or second poll loop. It receives explicit
live-graph access and a controller-owned `runTranscription` callback. The controller's existing
submission/poll lifecycle supplies completion waiters; shared consumers join the same active
transcription. Reuse requires a succeeded job, published nonempty ABC and a matching audio
asset/URL/source-task + transcription task/preset/duration key. `transcriptionInputKey` and
`transcriptionResultKey` are persisted on music nodes alongside job/result IDs; legacy results
without a key are conservatively regenerated. No key depends on volume or playhead position.
An audio/parameter/connection change invalidates the pending downstream run; cancellation,
failure, partial result, missing input or reference cycles cannot silently fall back to
unconditioned generation. The canvas stop button aborts pending downstream waits and stops
upstream jobs through the existing music cancellation interface; workflow disposal releases
waiters. Jobs already submitted still belong to the backend, not the browser.
There are no API connection/detection widgets or node-level history/restore controls, and
mounting a node does not probe runtime status or list tasks. The API adapter is internal
transport to the local app worker, not a configurable external audio Provider. Library-based
history management is deferred; persistent backend receipts/artifacts are preserved.

No binary audio or player/RAF/AbortController objects enter normal canvas JSON. Generator
and transcriber state retain durable job IDs; returning to the page resumes polling, not
inference. Workflow replacement, node deletion and pagehide dispose UI resources, while jobs
remain server-owned and retain their receipts/artifacts. Existing canvas job IDs still
resume current-job polling; node-level task browsing/restoration has been removed. Generated songs go through
`setAudioNodeResult`, keeping waveform/playback/meters shared with uploaded audio. Generated
result placement avoids occupied rectangles. Stale async replies check current node identity.

ABCJS 6.7.0 is vendored under `vendor/abcjs/` with its MIT license and loaded only for scores.
No external CDN or remote soundfont fetch is needed. Its general notation preview is distinct
from backend native YuE dialect validation. SVG, PNG and MIDI exports are real; PDF is the
browser print dialog. Generic MIDI import is explicitly not enabled. Audio comparison uses
native players and existing real waveform metadata, with synchronized starts (not sample-
accurate transport); parameters/score are read from source task receipts where available.

The score visualization node owns an optional persisted `scoreTitle` (120 characters).
Its compact title field updates the preview immediately; clearing it restores the source
ABC title. The music model derives a first-tune `T:` header override, preserving notation,
body section titles and later tunes. The controller passes that same derived ABC to preview,
comparison and exports, re-rendering before graphical export to avoid stale titles while the
renderer loads. Upstream ABC, generation parameters and saved model artifacts are never
rewritten. This is metadata within the existing music modules, not a new service or store.
ABCJS owns an inner responsive wrapper; the outer paper keeps its flex/scroll sizing so a
title or long score cannot push the title/tools/export controls outside the node.

Backend operation, installation and limits: `backend/audio/README.md`.

## Video-control nodes (ReShot)

Load `desktop-video-control-model.js`, `desktop-video-control-api.js`,
`desktop-video-control-view.js`, `desktop-canvas-video-control.js` before canvas assembly.
The model owns normalisation/type contracts, API module adapts authenticated snake_case requests,
controller owns jobs/polling/publication, and view uses only shared desktop tokens/actions.
Canvas injects live graph/state access and video rendering; `combineDomains` composes music and
video-control connection policies without either domain reading the other's private state.
`desktop-canvas-nodes` and workflow normalisation register `video_control`; results reuse `video`
with typed `controlMetadata`. Status is reported through `DesktopResults.reportTaskStatus`;
its global stop includes video-control tasks. No new music/image state or external Provider UI.
H3 control-video input stays explicitly gated pending online backend integration.

## Topaz Video enhancement node

`desktop-topaz-video-pipeline.js` owns persistent optional filter / encoding state,
validation and its snake_case adapter; it has no DOM, API or task lifecycle.
`desktop-topaz-video-inspector.js` renders those controls with the pipeline injected;
it does not maintain another copy of the workflow state.
`desktop-topaz-video-model.js` owns the independent `topaz_video` workflow schema,
video-only edge contract and backend catalog normalization. `desktop-topaz-video-api.js`
adapts authenticated `/api/topaz_video/*` requests to `DesktopTasks`, accepting only
canvas-local video sources (archive paths, task artifacts, same-origin Blob URLs and
video data URLs). `desktop-topaz-video-view.js` renders the compact preset-driven node
and the common node action/progress material. Detailed model parameters, synchronized
original/result playback, draggable A/B divider, side-by-side comparison, viewer
sound/fit/zoom controls, filmstrip timeline, in/out selection, timeline zoom,
keyboard transport and preview/full-export actions live in the independent
`desktop-topaz-video-workbench.js`; its playback/draft state is transient and it owns
no uploads or tasks. `desktop-canvas-topaz-video.js` owns uploads, preview/export jobs,
polling, cancellation and publication of full exports to the existing `video` result
node. Preview artifacts remain inside the workbench and never replace a downstream
result. These modules do not read image Topaz or ReShot private state.

The expanded workbench mirrors the information architecture of a dedicated video
enhancement application without importing a second visual system into the canvas:
source/configuration tabs and viewer modes occupy the center stage; transport, trim,
filmstrip and Preview/Source/Export queue state stay below it; a collapsible right
inspector contains built-in workflow presets, the active enhancement filter and the
runtime's real output/codec facts. Built-in cards are executable mappings to catalog
models rather than decorative controls. Independent Nyx denoise, interpolation / slow
motion, Hyperion HDR, stabilization (automatic crop / full-frame / rolling shutter)
and Themis motion deblur now have real collapsible controls. They map to separate
backend filters, never pretend to be enhancement sliders. Enabling HDR selects HEVC
10-bit; encoding exposes H.264, H.265 8/10-bit, bitrate and AAC/mute. Enhancement can
be disabled for filter-only processing. Actual `status.capabilities` and missing-resource
reasons drive availability; refreshing runtime status does not start downloads.
The original viewer is not covered by a misleading empty-preview overlay. Panel
scroll, accordion state and processing-field focus survive edits. Busy jobs lock
controls, and progress/stop still belongs to the existing shared task registry.
Export can explicitly use either the full source or the marked selection. A preview
whose processing configuration changed stays available but is labelled stale. Slow-motion
preview seeks and playback map source time to `media.time_scale`, including audio.

The backend status catalog is authoritative for model availability, scales and
numeric parameter bounds. Until it loads, submission is disabled. Unavailable
models remain visible with their reason (including Precise 2.5 and Mini on the
current Mac). Asset-ready models without a confirmed export show “待验证”. The
backend merges machine-bound staging evidence with completed task records that
passed the no-watermark provenance gate; once any supported multiplier is proven,
the model-level badge is verified and `verified_scales` identifies the exact
multipliers. Only `available: true` permits submission. Compact mode exposes only model, preset, scale
and scope; selecting “模型默认” resets to backend-declared neutral defaults, while edits in
the workbench switch the node to “自定义参数”. `max_seconds: 0` means the whole video;
choosing “前 N 秒” is explicit short-test mode. Workbench previews submit explicit
`start_seconds` + duration ranges. This is not an implicit 15-second trim. Jobs report
through the shared bottom status and canvas stop registry—there is no second stop
button—while the node shows only compact state/progress. Generated MP4s use ordinary
video nodes and can continue into ReShot through its local artifact URL allow-list.

Catalog step metadata is part of the input contract rather than presentation only.
The UI resets stale persisted values that do not align to a field's declared step and
rejects a misaligned edit before submission. In particular, conventional `gsize` is
`0` (automatic) or an integer `1–5`; the former fractional `0.1` value is normalized
back to `0`. Conventional preview ranges also need at least four frames, matching the
backend temporal-filter guard.

Load pipeline → inspector → model → API → view → workbench → controller before workflow/nodes/canvas; CSS
remains scoped to `.desk-node--topaz-video` and `.desk-topaz-video-workbench`.
Regression: `tests/test_topaz_video_canvas.cjs`, `tests/test_topaz_video_pipeline.cjs`
and backend `tests/test_topaz_video_pipeline.py`. Cache: `20261005-topaz-pipeline1`.

Expanded-workbench presentation lives only in `desktop-topaz-video-workbench.css`
(CSS cache: `20261006-topaz-panel-polish2`). It consumes the shared node surface,
Settings field/segment, semantic status and primary action tokens; no global token
or compact-node overrides. At reduced effective viewport widths the modal stacks
its existing stage and inspector without hiding actions. The retained media/trim
hit areas, select implementation and all processing state stay in their existing
modules; this visual refinement changes no JavaScript or backend contracts.
The compact 40px title bar keeps the filename on the title baseline; inspector
fields use the existing 24px control scale. Fine range rails keep a 24px native
input hit area, and select geometry is scoped to the workbench's portal variant.

## Shared generation task contract

Load `desktop-tasks.js` and `desktop-task-output-adapter.js` before API adapters and
canvas assembly. `DesktopTasks.createClient` exposes `submit`, `progress`, `cancel`,
and `result` for each domain. Receipts use `schema_version`, `domain`, `task_id`,
`status`, `stage`, `message`, `progress`, `error`, `artifacts`, and `raw`.
Unknown progress is `null`; unknown states stay `unknown`, never success. `result(id)`
queries once; `result(receipt)` reuses the receipt, without polling or resubmission.
Submission payloads and artifact types remain domain-specific.

`DesktopApi.tasks` adapts generation (including image/edit/Comfy/upscale), H3 video,
and batch; `DesktopMusicAPI.tasks` and `DesktopVideoControlAPI.tasks` adapt music and
ReShot. Legacy methods forward and unwrap the original receipt to preserve callers.
Existing HTTP routes, auth, provider fallback, archive and Telegram contracts are unchanged.
This is an in-process frontend contract, not a new backend task database or service.

Canvas assembly owns a `DesktopTasks.createRegistry` with explicit domain registration.
Controllers report through its `report` callback; the existing bottom status renderer
remains the display adapter. The global stop button calls only `cancelAll`, without
model-specific branching. New domains register a client, optional `showStatus(nodeId)`
and `listCancelable()` returning stable `key` + async `cancel` commands. They inject the
registry's reporting callback into their controller instead of changing the status UI.
Domain controllers still own polling, current-job state, restore, publication and errors.
The registry stores only adapters and pending cancellation commands, not mirrored jobs.

`desktop-task-output-adapter.js` bridges legacy output state and batch cancellation.
Shared task IDs are deduplicated; H3 cancellation delegates to its controller. Async
receipts are applied only to the same workflow/output/task identity. Failed cancellation
does not stop unrelated polling and remains retryable. The registry namespaces domain keys
and deduplicates overlapping stop requests. Agent plans and provider-specific internals
are not flattened into this generation contract.

Regression coverage: `tests/test_task_contract.cjs`, `tests/test_music_status.cjs`,
`tests/test_video_control.cjs`; runtime integration checks also cover canvas assembly.

## Qwen-Image 2.1 node and model tools

Load `desktop-qwen21-model.js` → `desktop-qwen21-api.js` →
`desktop-qwen21-tools.js` → `desktop-canvas-qwen21.js` before workflow/nodes/canvas
assembly. The model owns typed edges and persisted Base/preset/geometry/LoRA/reference
order; the authenticated API adapter translates snake_case; the controller owns
transient sessions, automatic preparation, ordered uploads, polling/cancellation and
publication to ordinary image nodes. Async mutations check workflow/node/job identity.
Its task client is registered in the existing global stop/status registry.

The 720×500 node uses existing day/night control tokens, two parameter rows, compact
ordinary-LoRA cards and explicit Image 1 / Image 2 reference order. The progress float
is a sibling of the body, positioned below the whole node. Managed Viggle is selected
by version/rank, not duplicated in the ordinary LoRA selector. Editable steps survive
workflow reloads and switching between turbo adapters; readiness/preparation is checked
for the selected file, not merely for any existing accelerator. Actual Base names come from
the backend; the canvas never persists checkpoint paths. Settings → Model Tools
renders independent Qwen and Krea tools in the same page; each scans its own import
and output directory and retains its own conversion state/recipes.

Regression: `tests/test_qwen21_canvas.cjs`, `tests/test_krea2_canvas.cjs`,
`tests/test_local_image_auto_mode.cjs` (derived modes, graph changes, request snapshots,
empty inputs, workflow replacement, retained LoRAs and reference limits).

Qwen Base retirement: the server owns `default_model_id` / `model_replacements`.
`desktop-qwen21-model.js` accepts only an explicit replacement that is ready;
`desktop-canvas-qwen21.js` applies it through its existing save port only to live,
idle nodes (also on cached-status mounts), before the request snapshot. Active
jobs and unknown missing custom Bases are not redirected. Model tools prepare
the server-selected Base, not the retired built-in. Short BF16 option labels come
from the server; the MFLUX checkpoint filenames and shared components stay unchanged.
Regression: `tests/test_qwen21_model_retirement.cjs` and served-page dropdown checks.

Krea Base menu (2026-10-06): the Krea model store omits the optional, unprepared
Mixed 4/8-bit built-in; the node's loading fallback lists only the default 8-bit
entry. No persisted model selection or installed weight is changed. The Base
select opts into `data-desk-select-width="content"`: `desktop-select.js` measures
its rendered single-line labels, uses at least the trigger width, and clamps
width/position to the viewport in canvas zoom coordinates. The opt-in CSS keeps
overlong labels on one line with ellipsis and a full-text title. Other select
variants retain their original geometry. Tests: `test_krea2_model_menu.py/.cjs`
and served-page light/dark, zoom, edge-position and keyboard checks.

## Shared LoRA assets and visual picker

The Assets → LoRA tab owns model descriptions; Settings → Model Tools owns only
Civitai connection/cache preferences. Krea and Qwen use the same visual picker
and detail view, filtered by the target engine. Existing LoRA IDs, per-engine
limits, scales, managed turbo adapters and generation payloads are unchanged.

Load `desktop-lora-data.js` → `desktop-lora-settings.js` / `desktop-lora-view.js`
before `desktop-api.js`, history and settings. `DesktopApi.lora` lazily owns the
single authenticated data adapter/cache. Read operations do not broadcast
mutations; explicit updates notify mounted lists and node labels.
Load `desktop-canvas-lora.js` before canvas assembly. Its injected graph ports
handle node selection, validated addition and explicit trigger insertion. The
bridge preserves structured prompt segments/references and uses existing text
mutation/undo machinery. It never silently changes prompts or LoRA strength.

The view owns only mounted UI, draft edits, request generations and sync polling.
`desktop-history.js`, `desktop-settings.js` and `desktop-canvas.js` only assemble
these domain components. Native dialogs live above the transformed canvas, not
inside nodes, and use shared desktop day/night tokens. `desktop-select.js` mounts
fixed menus inside their closest native dialog (ordinary menus still use body,
canvas menus remain anchored), so LoRA can use the same enhanced selects in the
gallery, picker and nested dialogs. Dirty-close guards, inline feedback
and request-generation checks prevent silent draft loss and stale modal updates.

`desktop-lora.css` owns gallery/detail density: 28px controls, shared 11px control
and helper typography, 12px section labels and 16px detail titles. The detail view
uses a compact preview/form split, collapsible file/source maintenance sections,
and a non-scrolling save footer. Footer inputs participate in the same draft and
save lifecycle as the body; no second state or data adapter is introduced. Empty
trigger-word editors expand by default. Narrow windows stack the two columns.
Only single-line fields share columns (name, version, recommended scale); trigger
words, description and tags each span the form width. Trigger status stays in the
section heading, so textarea resizing cannot leave an uneven neighboring control.
Cards use flex columns with bottom-pushed action footers, keeping Add buttons
aligned despite wrapped metadata. Clicking a card opens editable details; Add
never opens metadata or writes it. In a node picker it calls the injected
`addToNode` port for that fixed node and keeps the picker open. In the asset
library one compatible node is used directly; multiple compatible nodes require
an explicit target-only dialog. Pending clicks are deduplicated, while engine
controllers still own duplicate/capacity/busy and async node-lifetime checks.

A user can upload previews or copy an existing image asset, edit/explicitly clear
trigger words, copy selected phrases, or choose a connected text node for insertion.
A new connected text node is created only after confirmation when no input exists.
Remote examples are illustrative and need not come from the identical full workflow.
Civitai sync never overwrites manual fields; lack of network metadata does not block
model selection or inference. Weight deletion, preview deletion and removing a
node's LoRA are separate explicit operations.

Tests: `tests/test_lora_library.cjs`, `tests/test_lora_presentation.cjs`, `tests/test_lora_quick_add.cjs`,
`tests/test_lora_library.py`, plus both engine
canvas suites. Actual served-page checks use synthetic APIs without writing the
user's canvas or executing MLX/remote generation.

### Qwen VAE selection (2026-10-02)

`desktop-qwen21-tools.js` displays a VAE card in Settings → Model Tools using
existing settings/control tokens. Draft import and selected IDs belong to that
controller; the server owns the applied default. Import does not silently apply.
`desktop-qwen21-api.js` translates `source_path` / `vae_id` through existing auth.
The new choice affects future submissions only; queued jobs keep their snapshot.
The model-tools response owns the available VAE list and errors; neither canvas
nor the main settings controller maintains a second registry. Existing script
load order is unchanged; both changed scripts use `20261002-qwen21-vae1`.

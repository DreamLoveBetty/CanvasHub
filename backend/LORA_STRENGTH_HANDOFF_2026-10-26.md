# 开发交接：LoRA 强度修复与 Krea2 编辑叠加诊断

记录日期：2026-10-26（Asia/Shanghai）。面向后续接手开发的 agent／维护者。

**记录时状态：代码修复、回归及本机空闲部署已完成；未暂存、未提交、未推送。**
工作区同时存在其他功能的改动，本文件的清单只描述本次 LoRA 工作，不代表整个工作区。
后续应以实际 `git status`／`git diff` 判断提交状态，不要依据本记录自动提交或重启。

## 1. 接手先看这几条

- Qwen 2.1 和 Krea2 的**普通 LoRA**现在都接受有限数 **−20～20**，包括负向 slider。
- 两种画布节点以前存在“输入框显示 20，实际保存／提交 2”的问题；本次同时修复了范围和显示同步，不能只保留其中一层。
- **专用适配器没有扩大范围**：Qwen Viggle 固定 1；Krea Identity Edit 为 0.01～2；Krea 区域控制专用适配器为 0～2。
- Krea2 本次复现的是“编辑正常，但额外 LoRA 效果弱／不出现”，不是编辑模式整体失效。
- 固定 seed 的交叉对照支持：这组案例中，参考图保真 4 抑制了额外 LoRA 的表现，降为 1 后额外效果明显。**没有因此修改默认保真值或自动改写用户工作流。**
- 已完成用户批准的空闲重启；不要为阅读、补充本文或运行离线回归再次重启生产服务。

## 2. 已确认的代码问题

旧链路中有多处独立的 0～2 限制：

1. 画布普通 LoRA 输入框的 HTML `min`／`max`。
2. controller 的 `change` 处理将值截断为 0～2，却没有回写输入框。
3. model 的工作流／节点状态归一化再次截断为 0～2。
4. 两个后端生成契约拒绝负数及大于 2 的强度。
5. 共享 LoRA 资料中的 `recommended_scale` 也只允许 0～2。

所以手输 `20` 可能仍显示 `20`，但实际状态和推理任务只收到 `2`；负值被截为 `0`。
绕过前端直接提交 `20`，则会被后端拒绝。不能只修改 HTML 上限来修复这个问题。

## 3. 修改文件与职责归属

### 3.1 后端契约

| 文件 | 本次变化 |
|---|---|
| [qwen21/contracts.py](qwen21/contracts.py) | 增加领域内 `LORA_SCALE_MIN`／`LORA_SCALE_MAX`；普通 `loras[].scale` 校验改为 −20～20。 |
| [krea2/contracts.py](krea2/contracts.py) | 同步放宽普通 LoRA；`catalog().limits.lora_scale` 同步为 `[-20, 20]`。专用编辑／控制参数的校验不变。 |
| [lora_library/contracts.py](lora_library/contracts.py) | `recommended_scale` 允许 `null` 或 −20～20 的有限数字；继续拒绝布尔值、非有限数及越界值。 |

没有新建 API、服务或依赖；现有认证路径、`snake_case` 请求字段和任务提交流程不变。

### 3.2 前端状态与展示

| 文件 | 本次变化 |
|---|---|
| [desktop-qwen21-model.js](../frontend/scripts/desktop-qwen21-model.js) | 导出普通 LoRA 的范围常量和 `normalizeLoraScale`；工作流归一化保留合法负数／高强度。 |
| [desktop-krea2-model.js](../frontend/scripts/desktop-krea2-model.js) | 同上；不改变 `editAdapterScale`、`controlAdapterScale`、`referenceStrength` 的范围或默认值。 |
| [desktop-canvas-qwen21.js](../frontend/scripts/desktop-canvas-qwen21.js) | 普通输入框使用 model 的范围；事件处理调用同一归一化 helper，并将实际值回写输入框。 |
| [desktop-canvas-krea2.js](../frontend/scripts/desktop-canvas-krea2.js) | 同上；普通 LoRA 的索引、编辑适配器过滤及提交快照行为保持不变。 |
| [desktop-lora-view.js](../frontend/scripts/desktop-lora-view.js) | 推荐强度资料输入框同步允许 −20～20；推荐值仍不会自动应用到节点。 |

依赖方向仍是：领域 model 拥有状态规则，controller 调用 model 并协调 DOM／提交；共享资料模块不接管生成状态。
没有向 `backend/server.py` 或 `desktop-canvas.js` 添加第二套强度逻辑，也没有修改推理加载器来绕过校验。

### 3.3 缓存与模块说明

- [frontend/desktop.html](../frontend/desktop.html) 中上述五个 JS 入口的缓存键更新为 `20261026-lora-signed20`。
- [frontend/asset-versions.lock.json](../frontend/asset-versions.lock.json) 已通过 `assets:record` 记录；相比本次开始时，仅这五个条目变化。
- [Qwen 模块说明](qwen21/README.md)、[Krea 模块说明](krea2/README.md)、[共享资料模块说明](lora_library/README.md) 已同步新的契约。
- 修复完成时前端 build/check 指纹为 `ea5f3bf8a1cdebd7`。这是当时的验证记录，不是后续测试应写死的版本字符串。

## 4. 当前参数契约及兼容行为

| 参数／用途 | 范围或固定值 | 说明 |
|---|---|---|
| Qwen 普通 `loras[].scale` | −20～20，有限数 | 默认仍为 1。 |
| Krea 普通 `loras[].scale` | −20～20，有限数 | 普通生成、Identity Edit、独立 control 模式共用普通栈规则；不表示专用适配器兼容任意模式。 |
| 共享资料 `recommended_scale` | `null` 或 −20～20，有限数字 | 仅作资料，不会自动修改节点。 |
| Qwen Viggle 加速适配器 | 固定 1 | 继续由预设管理，不与普通 slider 范围混同。 |
| Krea `edit_adapter_scale` | 0.01～2 | 专用 Identity Edit 参数。 |
| Krea `control_adapter_scale` | 0～2 | 专用区域控制参数；原有混用拒绝不变。 |
| Krea `reference_strength` | 0.01～20，默认 4 | 本次没有改变默认值。 |
| Krea `grounding_px` | 保持既有校验，默认 768 | 本次成图对照固定为 1024，没有自动调节它。 |

维护时需要保留的细节：

- 前端对越界输入进行限幅，并显示实际值，例如 `99 → 20`；直接请求后端的 `20.01`／`-20.01` 则会被拒绝。
- 后端继续拒绝 NaN／Infinity。前端非有限输入不会原样进入请求；空输入仍按既有数值归一化规则处理。
- 过去已被保存为 `2`／`0` 的用户意图无法逆推出 `20`／负数；**不做自动恢复或迁移**，需要用户重新输入。
- 范围放宽是输入能力，不是推荐所有 LoRA 使用 20。按具体文件／作者声明的范围调节。
- 没有改变既有 alpha/rank 处理，也没有根据 `slider_scale_factor` 等 metadata 对已归一化权重再乘一次系数。

## 5. Krea2 调查过程与已验证结论

### 5.1 排除“后加载者覆盖前者”

检查了 worker 的“编辑适配器＋普通 LoRA”装配、双路编辑条件及固定版本加载器：

- 编辑源图确实进入了 grounded Qwen3-VL 语义编码和源图 VAE token 两条条件路径。
- 加载器按目标层聚合多个低秩增量并相加，不是最后一份 LoRA 直接替换前一份。
- 使用实际已安装权重的小切片及真实加载器做 CPU 数值检查，覆盖编辑单独加载、编辑＋普通、交换顺序、调强度、移除、清空及重复热加载；输出与直接求和一致。
- 检查的三份适配器都覆盖相同的 256 个投影层，包含 224 个主干投影和 32 个文本融合投影。普通 LoRA 并不是只作用于希望改变的局部区域。

小张量检查只证明对应加载／计算行为，不等同于全模型成图质量保证。
本次未修改 Krea worker、`edit_mlx.py` 或上游加载器；不要把此次交接误写成修复了加载器覆盖 bug。

### 5.2 固定 seed 的 2×2 成图对照

对同一张已有穿衣人像，保持源图字节、提示词、seed、Base、输出尺寸及其他参数一致：

- 864×1152，Turbo 8 步。
- Identity Edit 适配器强度 0.8。
- `grounding_px=1024`，`fit_mode=fit`。
- 普通 slider 开启时强度为 2；该文件 metadata 声明的公开范围为 −5～5。

只交叉改变两个变量：

| 参考图保真 | 普通 LoRA 关闭 | 普通 LoRA 开启 |
|---|---|---|
| 4 | 本次新增对照 | 复用先前已完成任务 |
| 1 | 本次新增对照 | 本次新增对照 |

结果：

| 同一保真值下，普通 LoRA 开／关的比较 | 平均绝对像素差（0～255） | 观察 |
|---|---:|---|
| 保真 4 | 0.292953 | 肉眼近乎一致，复现用户所说的效果不出现。 |
| 保真 1 | 10.229724 | 额外 LoRA 的形体影响可见。 |

这个交叉对照避免将“降低保真本身产生的变化”误当作额外 LoRA 的效果。
结果支持：**在这组输入／模型／seed 下，高原图约束抑制了额外 LoRA 的表达**。
低保真同时放松了姿态、细节的保持，不是所有输入的通用最优设置；像素差也不是质量评分或通用效果倍数。

高保真开启组来自先前任务，另三组为本次新生成；不是四组全部重新生成。
新任务已校验源图哈希和保持不变的提交字段，均走现有队列、原图归档且不发送 Telegram。
原 Krea 源 checkout 没有改动。

针对这组工作流，给用户的验证设置是：先仅将参考图保真从 4 改为 1，保持编辑适配器 0.8、语义识图 1024，再按 slider 自己的声明范围调节。
**没有把这组设置写成新的全局默认值，也没有自动覆盖已保存的工作流。**

[上游作者对参考保真与语义识图的说明](https://github.com/lbouaraba/comfyui-krea2edit)可作为背景资料；本次没有升级到新版本适配器或更改条件协议。

## 6. 回归覆盖及复查命令

### 6.1 可版本化的稳定回归

| 文件 | 本次新增覆盖 |
|---|---|
| [test_qwen21_domain.py](../tests/test_qwen21_domain.py) | signed slider 值通过后端归一化；越界和非有限数拒绝。 |
| [test_qwen21_canvas.cjs](../tests/test_qwen21_canvas.cjs) | 工作流保存／重载保留负数及大于 2 的值。 |
| [test_qwen21_lora_controls.cjs](../tests/test_qwen21_lora_controls.cjs) | 输入框范围、可见值、保存值与提交值一致；越界回写。 |
| [test_krea2_domain.py](../tests/test_krea2_domain.py) | 普通／编辑请求接受 signed 普通强度；catalog 同步；专用适配器上限不变。 |
| [test_krea2_canvas.cjs](../tests/test_krea2_canvas.cjs) | 普通 slider 工作流重载；专用适配器不随之扩容。 |
| [test_local_image_auto_mode.cjs](../tests/test_local_image_auto_mode.cjs) | Krea 编辑模式下普通 LoRA 可见值与提交值一致；专用编辑强度保持独立。 |
| [test_lora_library.py](../tests/test_lora_library.py) | 推荐强度 metadata 的保存／读取及非法值拒绝。 |
| [test_lora_presentation.cjs](../tests/test_lora_presentation.cjs) | 推荐强度资料输入框允许 signed 范围。 |

用例先验证旧代码会失败，再实施修复。稳定回归使用合成夹具，不依赖真实凭据、权重或用户图片。

从仓库根目录复查：

```bash
PYTHONPATH="$PWD" .venv/bin/python -m unittest \
  tests.test_qwen21_domain tests.test_krea2_domain \
  tests.test_lora_library tests.test_krea2_control

PYTHONPATH="$PWD" .venv/bin/python tests/run_regressions.py
node tests/run_node_regressions.mjs
(cd frontend && npm run -s check)
```

若后续又修改桌面 JS，须按项目规则重新 bump 缓存键并运行 `assets:record`；需要重建时运行前端 `build`。
不要为了让测试通过固定写死本文的缓存键或 build 指纹。

### 6.2 修复完成时的验证记录

- Python 稳定回归：969 项，OK（31 skipped）。
- Node 稳定回归：573 pass，0 fail。
- 不含设置、数据库、权重、用户图片的隔离副本：104 个 Python、85 个 Node 局部回归通过。
- 真实服务 `/desktop.html`，隔离浏览器且 API 全部使用合成响应：两种节点验证了 `20`、`-20`、`-3.25`、`0` 的显示／请求／重载，以及 `99 → 20` 回写；无 JS 错误；专用适配器范围保持不变。
- 真实 Qwen／Krea API：`±20` 通过强度校验进入后续资产检查，`±20.01` 被强度校验拒绝。
  探针刻意使用不存在的 LoRA ID，因此合法强度对应的 HTTP 400 是“资产不存在”，**不是强度校验失败**，也没有创建生成任务。
- 本次修复文件的 diff whitespace 检查及前端 build/check 均通过。

以上是 2026-10-26 修复完成时的历史结果，不表示之后每个工作区状态都已重新验证。
本交接文档的新增本身不需要重复出图或重启服务。

## 7. 部署与数据边界

- 用户先后确认了 Qwen 范围修复、Krea 范围扩展及空闲重启。
- 分阶段重启前检查了 7 个任务存储、准备／转换任务、资料同步和本地推理锁；运行任务没有被中断。
- 重启前后设置和既有任务状态保持不变；成图诊断另外新增了三条正常任务，没有改写旧任务。
- `settings.json`、模型权重、VAE、共享文本编码器、依赖版本及原有 Provider fallback 未修改。
- 原图仍经既有 `IMAGE_ARCHIVE_DIR/YYYY-MM-DD/` 和 sidecar 流程保存；Telegram 的 `sendDocument` 路径不变。
- Docker、桌面打包没有重新发版；本机已生效不等于这些产物已经更新。
- 工作区有其他未提交内容，不要批量暂存／清理或归因于此次修复。提交与推送仍需维护者另行要求。

## 8. 本机证据与继续开发注意事项

本机详细证据位于 `tests/output/lora-strength-20261026/`：

- `report.md`：操作报告及本机对照图片入口。
- `deployment.json`：两个 API 的真实部署校验；早期 Qwen 单独部署另有记录。
- `ui-krea2.json`、`ui-qwen21.json`：真实页面的合成 API 交互结果。
- `krea-stack-probe.json`：真实加载器的小张量数值验证。
- `krea-slider-range.json`：slider 声明范围。
- `krea-ab/ab.json`、`krea-ab/pixel-comparison.json`：任务映射及成图差异。
- `python-stable-final.log`、`node-stable-final.log`、`isolated-*-final.log`：验证输出。

这些是**被 Git 忽略的本机产物**，新 checkout 中可能不存在；它们不是稳定回归必需的 fixture。
本文保留了不依赖这些产物的关键结论，不要把用户图片、任务数据库或报告整批加入版本控制。

相关机器专属探针在 `tests/local/`，也不是普通稳定套件的组成部分：

- `qwen21_signed_strength_ui_local.cjs`：通过 `LORA_UI_ENGINE=krea2` 可检查 Krea；依赖本机浏览器路径。
- `qwen21_signed_strength_reload_local.py`：名称沿用早期 Qwen 阶段，最终已验证两个领域；**会真实重启服务**，不能当作只读离线测试随手运行。
- `krea2_edit_lora_stack_local.py`：读取已安装权重的小切片，CPU 数值探针。
- `krea2_edit_effect_ab_local.py`：会通过真实 API 创建诊断任务，依赖本机历史输入；不能放进 CI 或未经确认反复运行。

明确未完成／不应误推的事项：

- 允许范围扩大不保证每个 LoRA 与任意 Base／编辑适配器兼容，也不代表已经验证强度 20 的成图质量。
- 本次没有实现普通 LoRA 的局部作用区域、自动强度校准或自动保真调节。
- 本记录不代表此前 Qwen Orbit LoRA 的人像转视角问题已经解决。
- [Krea 区域控制 × Identity Edit 研究已关闭](krea2/JOINT_EDIT_RESEARCH_CLOSED.md)，本次只是普通 LoRA 叠加诊断，没有重新开放联合编辑；原有混用拒绝必须保留。

若再次报告“LoRA 无效”，先区分输入／提交值不一致、额外 LoRA 效果弱、编辑指令不执行、身份丢失，再按实际提交参数做固定 seed 对照，不要只凭“权重加载成功”或单张结果下结论。

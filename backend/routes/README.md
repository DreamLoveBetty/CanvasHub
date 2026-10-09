# 当前模块化状态（2026-09-10）

剩余后端领域已完成分层迁移。当前结构、职责索引、兼容适配器和验收约定见 `backend/README.md`。
`server.py` 保留原调用入口、显式依赖装配和有序 HTTP 分发；领域实现位于 `routes/`、`services/`。
下面是此前渐进批次的行为契约记录，其中“本次不迁移”“下一批”等描述指对应历史批次，
不代表这些领域在当前版本仍未拆分。所有既有 API、鉴权、字段、异常与数据保护约定继续有效。

# 增量路由拆分

精确路由表目前迁移 GET /api/layout/fonts、GET /api/layout/drafts、GET /api/editable-files 和 GET /api/history。
草稿详情、预览、导出图、资产读取的处理函数也已移入 layout_routes.py，
但 /api/layout/drafts/ 前缀分发仍留在原来的 RequestHandler，不扩展通用路由器的匹配规则。
草稿创建、更新、素材上传及预览/导出图保存的控制逻辑同样已移入 layout_routes.py；
POST/PUT 的原分发与鉴权不变，发布到历史仍转发至 RequestHandler.publish_layout_draft 兼容入口，
实际发布编排已迁入 backend/services/layout_publish.py。
PPT/PSD 成品列表和文件读取处理已迁入 editable_routes.py；
/editable_file/ 的前缀分发、原有鉴权和一次 URL 解码仍留在 RequestHandler。
POST /api/editable-files/send、/api/editable-files/delete 的处理函数也已移入 editable_routes.py；
POST 分发与鉴权仍在 RequestHandler，不改动通用路由器。
历史列表查询处理已迁入 history_routes.py，原 handle_history 签名与子类覆盖入口保留。
数据库历史分批读取、旧 JSONL 兼容读取和合并排序去重编排已迁入 backend/services/history_query.py。
历史条目的响应格式化已迁入 backend/services/history_format.py，原 _format_history_task(task) 兼容入口保留。
共享分页、结果文件解析、时间戳、显示规则和去重键已迁入 backend/services/history_policy.py，五个原辅助入口保留。
任务状态、generation runs/events 的只读控制器已迁入 task_routes.py，三个原 Handler 入口和前缀分发保留。
图片资产列表、详情与体检的只读控制器已迁入 asset_routes.py，三个原 Handler 入口、精确路径分发及鉴权保留。
体检统计收集器已迁入 backend/services/asset_health.py，server.py 保留原零参数兼容入口；体检读取和清理继续共用同一实现，不迁移或执行清理。
候选集列表、新建/更新和删除控制器已迁入 asset_set_routes.py，三个原 Handler 入口与原分发/鉴权保留。
收藏/隐藏/标签/评分/备注的更新控制器已迁入 asset_meta_routes.py，原 Handler 入口、POST 精确分发与鉴权保留。
图片单项删除、批量删除与撤销控制器已迁入 asset_delete_routes.py，三个原 Handler 入口及分发/鉴权保留；底层文件移入废纸篓、恢复与存储实现不变。
删除业务编排已迁入 backend/services/asset_delete.py，server.py 保留 _delete_gallery_assets(asset_ids) 兼容入口。
撤销恢复编排已迁入 backend/services/asset_undo.py，原控制器保留参数解析、空 ID 拒绝、HTTP 状态及异常响应；实际清理仍独立处理。
其他 API、媒体路由分发和静态回退仍保持原样。

- base.py 的 ProtectedRouter 只精确匹配请求方法和 URL path，调用现有 require_auth，
  不另造鉴权机制，不改变 JSON 响应、异常或 CORS。
- dispatch 返回 True 表示请求已经被接管，包括鉴权拒绝；False 才继续旧路由。
  不在这里统一返回 404/405，不做前缀匹配、大小写转换、URL 解码或尾斜杠归一化。
- 路由表启动时复制并只读使用；新增路由必须显式注册，不能在请求线程里修改。
- history_routes.py 逐请求注入 page_int/collect_tasks/format_task，不反向导入服务器、读取配置或管理数据库。
  保留 limit/offset 默认值、裁剪范围、重复参数取值、先汇总再分页、仅格式化当前页的顺序；
  history/total/has_more 结构及原异常传播不变，不添加新的过滤、缓存或错误响应封装。
  通过原汇总、格式化和策略兼容入口调用历史服务；不绕过既有替换点或改变各调用方的参数处理。
  不改底层数据库查询、历史删除/Telegram 导出、重跑、生成状态机或 Provider fallback。
- history_query.py 不接收 HTTP Handler、不反向导入 server、不读取配置或初始化数据库。
  server 保留三个原零参数入口，逐调用传入 get_all_tasks、旧记录目录、safe_basename 及共享策略函数；
  汇总入口仍传入两个兼容读取入口，不绕过已有替换点，不引入全局上下文对象。
  保留每批 1000 条读取、数据库错误传播、旧记录 ID 和字段、坏 JSON 行跳过及读取异常返回已读前缀的边界。
  仍先读数据库再读 JSONL，按时间戳稳定降序排序，同时间重复项优先数据库，先筛可见性再去重；
  不下推分页、不增加缓存或新过滤条件，不顺带修复旧数据语义，也不改媒体、成品与 sidecar。
- history_format.py 仅依赖 urllib.parse 和显式传入的结果文件解析、H3 类型及公开参数策略、safe_basename。
  不接收 Handler、不访问存储或配置、不反向导入服务器；兼容包装逐调用解析依赖，保留已有调用/替换点。
  图片/视频/PPT/PSD 路径、字段别名、空值语义、状态与时间字段、manifest、错误/Run 元数据和原异常传播不变。
  仍由原 H3 策略过滤私有参数；本次格式化迁移不顺带改 gpt-file 的旧 image_count 语义。
- history_policy.py 只依赖标准库 json，不读配置/文件/数据库，不处理 HTTP，也不反向导入 server。
  五个原 _history_* 辅助入口保留原签名和默认参数；去重包装逐调用注入结果解析、时间戳和 safe_basename。
  保留文件优先、task_id 次之、时间戳加前 120 字符提示词的去重键；不新增路径规范化或跨提供商去重规则。
  结果列表解析保留字符串/JSON、主文件别名、重复项、顺序和异常边界；不把资产库的图片扩展名过滤套用到历史结果。
  分页转换失败仍直接返回传入默认值，仅成功转换后裁剪；显示规则仍为有结果或既有六种进行中状态。
  状态响应、generation runs/events、视频资产/提示词分页及资产体检/无图历史清理仍调用原入口；本次不改变其行为或执行真实清理。
- task_routes.py 逐请求注入任务/运行记录/事件读取、分页参数处理、状态格式化和缺失任务响应函数。
  不反向导入服务器、不读取配置或管理数据库；原 handle_status/handle_generation_runs/handle_generation_events 签名与子类覆盖保留。
  三个 URL 前缀的分发与鉴权仍在 do_GET，不扩展 ProtectedRouter；状态 ID 仍取末段原值，运行/事件 ID 仍只解码一次。
  保留空末段、额外路径段、查询参数首值、分页默认/范围与未知方法/路径行为，不顺带修正旧 URL 规则。
  缺失任务仍返回 HTTP 200 的终态失败，避免旧前端无限轮询；已有 _missing_task_payload/_status_response_task 不迁移、不改字段。
  状态读/格式化异常继续传播；运行/事件控制器原 try/except 与 500 响应、send_json 异常边界保持。
  未找到运行记录仍读取事件，保留 run 为 null、task_id 空字符串与原 count；不改变原始 JSON 字符串字段或响应压缩。
  不迁移批次状态/取消/重试、任务创建和运行状态机，不修改任务、日志、Provider/fallback、归档或 Telegram。

- asset_routes.py 只依赖 urllib.parse 和逐请求注入的 list_assets/get_asset/invalidate_cache/collect_health，
  不反向导入服务器或索引模块、不读取配置或管理数据库；保留 handle_assets/handle_asset_detail/handle_asset_health 签名和子类覆盖。
  GET /api/assets、/api/assets/detail、/api/assets/health 仍走原 do_GET 分发与鉴权，不扩展 ProtectedRouter，不增加路径/方法归一化。
  列表 limit/offset 仍直接 int 转换，非法值返回原 400，成功值交给底层裁剪；不套用历史分页策略。
  筛选别名、显式参数优先级、首个非空重复参数、布尔值不去空格等规则原样保留，统计与字段投影仍由原索引负责。
  refresh 仍只在原规则为真时先失效缓存再读取；普通列表与详情不新增刷新，底层 TTL/指纹与可再生 file_meta_cache 行为不变。
  详情仍只接受 id、去首尾空白并经 parse_qs 解码一次；缺 id 为 400、未找到为 404，完整资产字段原样补全。
  列表与详情保留各自原有错误 JSON 结构、try/except 和 send_json 异常边界，不统一错误包装或新增过滤。
  体检仍调用原 _collect_asset_health 一次，只剔除顶层 valid_asset_ids/all_asset_ids/missing_assets_all 三个内部字段；
  其他公开字段原样浅拷贝，不增加字段白名单、递归过滤、截断或查询参数处理，不修改收集器返回对象。
  外层 ok 表示接口成功，内层 health.ok 表示是否发现问题；原异常日志、500 响应及 send_json 异常边界保持。
  体检统计上限、缺失清单前 120 条、问题数累计口径、原文件存在性判断和隐藏/本地未归档资产规则仍通过原收集入口处理。
  不改变 asset_index.py、用户元数据/文件、删除/撤销/批量清理、候选集、视频资产或索引重建实现。
- asset_health.py 只接收 list_assets/list_sets/list_tasks/asset_exists/should_render_history 五个显式依赖，
  不接收 HTTP Handler、不反向导入服务器/存储，不读配置、不初始化数据库，不负责文件读取、缓存或写入。
  server 保留 _collect_asset_health()，逐调用解析五个原依赖；体检和清理仍通过该入口共享统计，不绕过现有替换点。
  保留资产 3000/候选集 300/任务 3000 的单批读取上限和先资产存在性、再候选集、再历史的调用顺序。
  ID/字段别名真值优先级、空白 ID 与重复项规则、排序后的内部 ID 集、完整缺失明细与公开前 120 条保持。
  候选集坏引用按出现次数累计，真正空集合不混入“无有效成员集合”；溯源坏引用数与涉及任务数仍分别统计。
  历史结果仍按原始 result_files 真值和 result_file 回退交给原可见性策略，不新增 JSON 解析、扩展名过滤或去重。
  统计字段默认值、显式空值和 history_missing_count 的 int 转换时机/异常保持，不新增归一化、裁剪或异常包装。
  服务仍返回包括三个内部字段的完整结果，由 HTTP 控制器剔除；清理的三次重新统计及完整缺失列表消费不变。
  不改底层原图存在性规则、索引缓存与元数据持久化，不新增清理、修复或事务；所有实际写操作继续独立处理。
- asset_set_routes.py 只依赖 urllib.parse 和逐请求注入的 list_sets/create_set/update_set/delete_set。
  不反向导入服务器或存储，不读配置、不管理数据库；候选集三个原 Handler 方法保留签名和子类覆盖。
  GET/POST /api/assets/sets、DELETE /api/assets/sets/<set_id> 仍由原分发鉴权，不扩展 ProtectedRouter。
  DELETE 仍取最后路径段并一次 unquote，空末段/额外路径段和与通用资产删除前缀的优先级不变。
  列表仍直接 int 转换分页参数，非法值 400，默认 80/0 及底层 300 上限保持；搜索/标签、返回字段和空库不扫描逻辑不变。
  POST 继续通过原 read_json_body 读取最多 4 MiB；set_id/id 和 asset_ids/assetIds 的真值优先级保持。
  更新只传入出现过的字段，显式 null/空值沿用原回退值；不新增 status 更新能力、参数容错或字段归一化。
  新建 201、更新/删除 200，错误仍为原 400（不存在也不改成 404）；列表与写入各自的错误包装、send_json 边界保持。
  底层候选集软删除、快照回退、资产去重、更新/读取的提交边界原样保留；不新增幂等、回滚、复活或缓存刷新。
  候选集删除不改成原图删除；图片删除/撤销由独立控制器处理，不混入候选集存储、体检清理或索引重建。
- asset_meta_routes.py 只依赖 json 和逐请求注入的 update_meta，不反向导入服务器/索引，不读配置或管理数据库。
  原 handle_asset_meta 签名与子类覆盖保留，POST /api/assets/meta 的分发/鉴权不变，不扩展 ProtectedRouter。
  仍直接按 Content-Length 读取请求体并 json.loads，不替换成具有不同限制的 read_json_body；原空体、异常和解析规则保持。
  asset_id/id 真值优先级不变；只传入出现的 favorite/hidden/tags/rating/note，保留显式 null，不新增类型转换或字段别名。
  成功原样包装为 ok/asset，错误仍为原 400，send_json 异常边界不变；不新增资产存在性检查、重试或回滚。
  布尔真值、标签去重/裁剪、评分范围、备注长度和空值语义仍由 update_asset_meta 处理；原未知 ID 元数据 upsert 保持。
  缓存仍由存储写入成功后失效，不新增控制器刷新；图片列表/详情/候选集的紧随读取仍使用原索引。
  不改变资产索引/存储、候选集记录、源图片/sidecar，删除/撤销/清理及生成链路仍单独处理。
- asset_delete_routes.py 不导入服务器、配置或存储；只导入无外部状态的撤销编排服务，使用逐请求注入的删除/恢复依赖及原 Handler I/O。
  原 handle_asset_delete/handle_asset_delete_batch/handle_asset_undo_delete 签名和子类覆盖保持，不扩展 ProtectedRouter。
  DELETE /api/assets/<id> 仍取最后一段并一次 unquote，候选集删除前缀优先级保持；两个 POST 仍精确匹配原路径。
  单项 ID 原样交给底层；批量读取上限 256 KiB，asset_ids/assetIds/ids 真值优先级、字符串包为单项和列表原样传递不变。
  删除去重、120 项上限、先快照再移文件及同任务多图合并更新仍归 _delete_gallery_assets，不新增控制层查找或缓存刷新。
  单项/批量 FileNotFoundError 为 404、ValueError 为 400、其他异常为 500；原成功响应与发送异常边界保持。
  撤销读取上限 128 KiB，batch_ids/batchIds/batch_id/batchId 优先级、字符串原值与列表清理、倒序且不预去重保持。
  依次恢复文件、任务、旧历史、候选集、取消隐藏并标记批次；每批任务 ID 去重及兼容单任务快照追加行为保持。
  完成/部分完成/均不可撤销仍为 200/207/400；撤销异常（含非法 JSON 和过大请求体）仍为 500，不顺带统一错误状态。
  exists/missing/skipped 计数、取消隐藏异常忽略、已处理批次标记及中途失败不自动回滚/重试的旧行为不变。
  批量非对象 JSON 原本会触发 500，缺失/非法参数与重复撤销规则不在本轮修正；不新增事务或幂等语义。
  文件允许根目录、废纸篓定位、同名保护、任务/JSONL/候选集快照与删除日志持久化仍归原辅助函数，不放入通用上下文对象。
  控制器迁移不执行真实删除/恢复/清理；物理移动与恢复验证只在临时 HOME/.Trash、临时归档和数据库中进行。
- asset_delete.py 仅依赖标准库 Path 和十个显式注入的查找、快照、文件移动、任务/元数据/候选集更新与日志函数。
  原 _delete_gallery_assets(asset_ids) 每次调用解析原依赖，删除控制器继续调用此入口；清理及撤销仍使用各自原有流程。
  服务不反向导入 server、不读取配置或管理数据库。
  ID 清理与首次出现顺序、去重后 120 项上限、两次包含隐藏项的 5000 项索引扫描、missing_history 覆盖与逐 ID 回退保持。
  先收集全部任务和候选集快照，再移文件、一次合并更新任务/旧历史、逐项隐藏并移除候选集引用，最后记录删除日志。
  旧任务排除、任务快照去重、集合快照同 ID 后值覆盖、Path.expanduser 路径去重保持，不新增 resolve 或文件策略。
  隐藏失败仍忽略并继续，其他原异常原样传播；中途失败不新增事务、补偿、回滚或重试。
  删除日志及响应的字段、顺序、列表和对象引用、批次 ID 别名与提示信息保持；文件允许目录、废纸篓和同名保护仍归原辅助函数。
  验证写入只使用内存桩或临时文件/数据库，不对真实资产发起删除、恢复或清理。
- asset_undo.py 接收已解析的 batch_ids 和七个明确的恢复/日志依赖，无导入、Handler、配置/存储初始化或 HTTP 状态决策。
  原撤销 Handler 与控制器签名不变，逐请求传入 get_batch/restore_move/restore_task/restore_history/restore_sets/update_meta/mark_restored。
  控制器保留原 128 KiB 正文上限、四个 ID 别名及真值优先级、字符串原值/列表清理、缺 ID 的 400，其他原异常仍为 500。
  服务倒序逐批读取，不预先去重或统一读取；每批仍按文件、任务、旧历史、候选集、取消隐藏、标记已恢复的顺序执行。
  保留未知/已撤销错误顺序、文件状态计数、每批任务 ID 去重和旧单快照追加，不修改原快照列表别名行为或增加 ID 规范化。
  未找回文件或取消隐藏失败仍可标记批次恢复；隐藏异常忽略，其他异常传播，不增加部分失败回滚、重试或原子性。
  服务原样形成响应字段，控制器根据 errors/batch_ids 保留 200/207/400 选择和 send_json 异常边界；不把 HTTP 状态放进业务服务。
  废纸篓路径与原图碰撞保护、文件/任务/旧历史/集合恢复及日志持久化仍归原辅助函数；本次不执行真实恢复或清理。

## 图片资产统计口径

资产库索引与历史任务列表是不同的计数：图片资产按文件/图片结果展开，历史接口按旧可见性和去重规则汇总条目。
图片索引仅接收支持的 PNG/JPG/JPEG/WebP 结果，PSD、ZIP、PPT/PDF、视频不参与图片缺失检查；原图片资产 ID 和索引位置不变。
history_missing_archive_count 统计未匹配图片归档的图片结果；history_missing_count 只计其中在既有本地原图目录也找不到原图的结果。
本地原图存在只显示“未归档记录”，仅有缩略图仍计“原图缺失”。这不是图片解码完整性检查，也不会补归档、改任务或删除文件。
保留 source=missing_history 及其别名、missingArchive/missing_archive 的“未归档”语义；前端筛选文案改为“未归档记录”，两个数量分别展示。
资产体检沿用原接口字段消费修正后的缺图数量，不把未归档本身计作缺图问题。

## 其他迁移边界
- 服务器保留 handle_layout_fonts、handle_layout_draft_list、handle_layout_draft_get/post 薄包装，
  兼容既有调用/测试/子类覆盖，逐请求传入字体目录和 list_drafts/load_draft/get_file 函数。
  写入入口逐请求注入 create_draft/update_draft/save_asset，发布仍调用 handler.publish_layout_draft，保留子类覆盖能力。
  layout_routes.py 不反向导入服务器、读取全局配置或管理数据库；存储操作只调用明确传入的函数。
- 草稿读取只移动控制层：查询参数默认值、转换异常、资源路径解析、响应字段及 400/404 保持不变。
  不新增分页规则、URL 归一化或路径解码；二进制响应继续使用原 send_binary_file。
  底层 layout_drafts.py 的存储位置、初始化及读取行为不变。
- 草稿写入仅移动控制层：沿用 read_json_body、原字段默认值/空值语义、调用顺序、200/201 与 400/404。
  不引入新事务、重试、回滚、字段校验或 URL 归一化。底层文件/SQLite 写入和发布归档/历史实现不变。
- 发布服务不接收 HTTP Handler、不反向导入 server、不读取全局配置或初始化存储。
  兼容入口逐请求传入草稿读取、图片解码、日期归档目录、sidecar、缩略图、任务写入和时间/随机数函数。
  文件名、data URL/已有导出图两条路径、TXT/Markdown、任务字段和响应格式、调用顺序及原错误行为保持不变。
  日期时间沿用原函数内 datetime.now；不新增幂等、碰撞处理、事务或失败回滚，不改变 Telegram/Provider 流程。
- 字体分组、字重推断、排序、文件名编码和响应结构保持现有规则；已离线准备的同名 WOFF2 优先于原字体，
  原文件不删除。不调整生成或 Provider fallback。
- 后续字体加载修复补齐 GET/HEAD /font/<文件名>，仍由 RequestHandler 校验既有鉴权，
  文件读取委托给 layout_routes.py。只开放字体目录的直接子文件和支持的字体扩展名，
  拒绝路径穿越及越界符号链接；分块发送，避免大型中文字体一次读入内存。
  不扩大通用静态目录白名单，也不提供目录浏览或自动安装/转换字体。
- editable_routes.py 只依赖显式传入的 list_files、coerce_bool、resolve_file；
  原 handle_editable_files/file 签名与子类覆盖入口保留，每请求解析依赖，不反向导入 server 或存储模块。
  列表参数解析、默认值、重复参数与布尔规则、JSON 原样返回及 500 异常边界不变；
  底层搜索、类型别名、数量裁剪、归档/本地成品和统计逻辑仍归 editable_file_service.py。
- 文件读取继续沿用原 MIME 推断、预览/附件区分、响应头顺序、整文件读取及 HTML 404。
  不改用其他二进制响应封装，不增加 Content-Length、Range、HEAD 支持或新的路径规范化规则。
  路径允许范围及符号链接判断仍由原 resolve_editable_file 决定。
- 这里的“只读”指只迁移 GET 控制层：底层列表原本可能按需补建缺失 PSD 预览，仍保留这一行为。
  不迁移成品生成、预览构建或保存，不改变任何产物目录和 sidecar。
- 成品发送/删除保留 handle_editable_file_send/delete 原签名及子类覆盖入口，逐请求注入
  resolve_file/send_telegram/delete_item；模块不读配置、不管理数据库、不反向导入存储或服务器。
  字段别名及优先级、空值与字符串转换、说明裁剪到 900 字符、JSON 响应和原 400/404/500 边界不变。
  Telegram 仍调用既有 send_telegram(None, path, caption)，底层 sendDocument 原文件发送不变。
  删除仍由 delete_editable_item 解析允许路径并移除成品目录，前端仍先二次确认；
  不引入回收站、幂等、重试、事务或新的路径校验。PPT 和 PSD 共用这些处理入口，均在验收范围内。

下一批迁移仍应先固定接口行为，再移动实现。不要把整个服务器放进通用上下文对象，
也不要用反向导入或大型 Mixin 把依赖问题藏起来。

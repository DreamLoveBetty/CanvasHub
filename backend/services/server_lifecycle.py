"""Ordered server startup, store recovery and HTTP listener lifecycle.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def run_server(
    *,
    APP_DATA_DIR,
    PORT,
    RequestHandler,
    SERVER_CONFIG,
    SERVER_HOST,
    SOURCE_IMAGE_DIR,
    STYLE_PRESETS_FILE,
    _ensure_db_file_permissions,
    _init_generation_semaphore,
    _validate_public_mode_password,
    cancel_orphan_prompt_source_runs,
    fail_stale_processing_tasks,
    get_agent_runtime,
    init_agent_store,
    init_asset_store,
    init_db,
    init_layout_draft_store,
    init_prompt_library_store,
    init_prompt_source_store,
    recover_cyimg_tasks,
    recover_krea2_tasks,
    socketserver,
    recover_qwen21_tasks=lambda: None,
):
    """启动服务器"""
    _validate_public_mode_password(server_config=SERVER_CONFIG)
    # 初始化数据库
    init_db()
    print("✅ 数据库初始化完成")
    stale_count = fail_stale_processing_tasks(max_age_seconds=0)
    if stale_count:
        print(f"⚠️ 已标记 {stale_count} 个重启后遗留的生成任务为失败")
    _init_generation_semaphore()
    recover_cyimg_tasks()
    recover_krea2_tasks()
    recover_qwen21_tasks()
    init_layout_draft_store()
    print("✅ 排版草稿库初始化完成")
    init_asset_store()
    print("✅ 图库资产索引初始化完成")
    init_prompt_source_store()
    orphan_prompt_runs = cancel_orphan_prompt_source_runs()
    if orphan_prompt_runs:
        print(f"⚠️ 已标记 {orphan_prompt_runs} 个重启后遗留的远程源同步任务为停止")
    init_prompt_library_store(legacy_style_presets_file=STYLE_PRESETS_FILE)
    print(f"✅ 提示词素材库初始化完成：{APP_DATA_DIR / 'prompt_library.db'}")
    init_agent_store()
    interrupted_agent_runs = get_agent_runtime().recover_after_restart()
    print("✅ Agent 运行库初始化完成")
    if interrupted_agent_runs:
        print(f"⚠️ 已暂停 {interrupted_agent_runs} 个服务重启前未完成的 Agent 运行")
    _ensure_db_file_permissions()
    SOURCE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"✅ 远程源素材库初始化完成：{SOURCE_IMAGE_DIR}")
    
    class ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
        allow_reuse_port = False
        daemon_threads = True

    # 启动服务器
    with ThreadingHTTPServer((SERVER_HOST, PORT), RequestHandler) as httpd:
        print(f"🚀 服务器启动在 http://{SERVER_HOST}:{PORT}")
        print(f"🔐 公网模式：{'开启' if SERVER_CONFIG.get('public_mode') else '关闭'}")
        print(f"📝 日志输出到 stdout")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n👋 服务器关闭")

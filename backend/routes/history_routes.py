"""Existing history read endpoint with explicit query dependencies."""

import urllib.parse


def handle_history(handler, *, page_int, collect_tasks, format_task):
    """处理历史查询（支持分页，兼容旧前端格式）"""
    parsed = urllib.parse.urlparse(handler.path)
    query = urllib.parse.parse_qs(parsed.query)

    limit = page_int(query.get('limit', [50])[0], 50, minimum=1, maximum=500)
    offset = page_int(query.get('offset', [0])[0], 0, minimum=0, maximum=100000)

    all_tasks = collect_tasks()
    page_tasks = all_tasks[offset:offset + limit]
    formatted_tasks = [format_task(task) for task in page_tasks]

    handler.send_json({
        "history": formatted_tasks,
        "total": len(all_tasks),
        "has_more": offset + len(page_tasks) < len(all_tasks),
    })

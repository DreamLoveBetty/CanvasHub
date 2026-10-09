"""Publish layout drafts to the archive and task history without HTTP dependencies.

Storage and task callbacks are explicitly supplied by the compatibility adapter.
Keep existing operation order and failure behavior; this is not a transaction layer.
"""

import json
from pathlib import Path
import shutil


def publish_layout_draft(
    draft_id,
    data,
    *,
    load_draft,
    get_draft_file,
    decode_image,
    daily_output_dir,
    write_prompt_sidecar,
    save_thumbnail,
    create_task,
    update_task,
    time_now,
    random_int,
):
    """把排版草稿导出为正式历史记录。"""
    draft = load_draft(draft_id)
    title = str(data.get('title') or draft.get('title') or '排版导出').strip()
    prompt = str(data.get('prompt') or title or '排版导出').strip()
    node_id = str(data.get('node_id') or draft.get('node_id') or '').strip()
    data_url = str(data.get('data_url') or '').strip()

    from datetime import datetime
    now = datetime.now()
    created_at = int(time_now())
    timestamp = now.strftime('%Y%m%d_%H%M%S')
    draft_suffix = str(draft_id)[-8:]

    if data_url:
        image_bytes, _mime_type, extension = decode_image(data_url)
        filename = f"layout_{timestamp}_{draft_suffix}{extension}"
    else:
        source_path = get_draft_file(draft_id, 'export')
        extension = source_path.suffix.lower() if source_path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp') else '.png'
        filename = f"layout_{timestamp}_{draft_suffix}{extension}"

    output_dir = daily_output_dir(now)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    if data_url:
        with open(output_path, 'wb') as f:
            f.write(image_bytes)
    else:
        shutil.copyfile(source_path, output_path)

    sidecar = output_dir / f"{Path(filename).stem}.txt"
    with open(sidecar, 'w', encoding='utf-8') as f:
        f.write(prompt)
        f.write('\n\n')
        f.write(f"layout_draft_id: {draft_id}\n")
        if node_id:
            f.write(f"layout_node_id: {node_id}\n")
    try:
        sidecar_content = sidecar.read_text(encoding='utf-8')
        write_prompt_sidecar(output_path, sidecar_content, txt_path=sidecar)
    except Exception as exc:
        print(f"⚠️ 写入 Obsidian 提示词 md 失败: {exc}")

    save_thumbnail(str(output_path), filename)

    task_id = f"layout_{created_at}_{random_int(1000, 9999)}"
    params = {
        'draft_id': draft_id,
        'node_id': node_id,
        'title': title,
        'ratio': 'layout',
        'archive_dir': str(output_dir),
    }
    create_task(task_id, prompt, params, status='succeeded', task_type='layout-export')
    update_task(
        task_id,
        'succeeded',
        result_file=filename,
        result_files=json.dumps([filename], ensure_ascii=False),
        stage='done',
        progress_text='排版导出完成',
        finished_at=created_at,
    )

    return {
        'ok': True,
        'task_id': task_id,
        'status': 'succeeded',
        'type': 'layout-export',
        'prompt': prompt,
        'params': params,
        'result_file': filename,
        'output_file': filename,
        'result_files': [filename],
        'output_files': [filename],
        'image_paths': [f"/image/{filename}"],
        'primary_image_path': f"/image/{filename}",
        'created_at': created_at,
        'updated_at': created_at,
        'progress_text': '排版导出完成',
    }

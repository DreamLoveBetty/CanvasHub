"""Format history records without HTTP, storage, or configuration dependencies.

The compatibility adapter supplies shared result parsing and public video policy.
Keep the existing output schema, field semantics, and error propagation.
"""

import urllib.parse

from .image_preview import image_url
from .generation_timing import task_total_seconds


def format_history_task(task, *, task_result_files, h3_task_type, public_h3_params, safe_basename):
    result_files, primary_output = task_result_files(task)
    is_video = task.get('type') in {h3_task_type, 'cyimg-video'}
    params = task.get('params') if isinstance(task.get('params'), dict) else {}
    if task.get('type') == h3_task_type:
        params = public_h3_params(params)
    duration_seconds = task_total_seconds(task, params)
    image_paths = []
    video_paths = []
    if task.get('type') == 'gpt-file':
        image_paths = []
    elif is_video:
        video_paths = [f"/video/{urllib.parse.quote(safe_basename(name))}" for name in result_files]
    elif task.get('type') in ('gpt', 'gpt-edit'):
        image_paths = [f"/gpt_outputs/{name}" for name in result_files]
    elif result_files:
        image_paths = [image_url(name) for name in result_files]

    return {
        'task_id': task.get('task_id', ''),
        'status': 'success' if task.get('status') == 'succeeded' else task.get('status', 'failed'),
        'prompt': task.get('prompt', ''),
        'params': params,
        'prompt_mode': params.get('prompt_mode'),
        'gpt_provider_route': params.get('gpt_provider_route'),
        'main_model': params.get('main_model'),
        'reasoning_effort': params.get('reasoning_effort'),
        'revised_prompt': params.get('revised_prompt'),
        'revised_prompts': params.get('revised_prompts') if isinstance(params.get('revised_prompts'), list) else [],
        'output_file': primary_output,
        'result_file': primary_output,
        'output_files': result_files,
        'result_files': result_files,
        'image_paths': image_paths,
        'image_count': 0 if is_video else len(result_files),
        'video_paths': video_paths,
        'video_path': video_paths[0] if video_paths else '',
        'video_count': len(video_paths),
        'video_metadata': {
            key: params.get(key)
            for key in ('width', 'height', 'fps', 'frame_count', 'duration_seconds', 'video_size_bytes', 'seed', 'elapsed_seconds', 'acceleration')
            if params.get(key) is not None
        } if is_video else None,
        'file_manifest': params.get('file_manifest') if isinstance(params.get('file_manifest'), dict) else None,
        'artifact_type': params.get('artifact_type') or params.get('task_type'),
        'error': task.get('error'),
        'display_error': task.get('display_error') or task.get('error'),
        'error_code': task.get('error_code', ''),
        'error_category': task.get('error_category', ''),
        'raw_error': task.get('raw_error', ''),
        'last_run_id': task.get('last_run_id', ''),
        'run_count': task.get('run_count', 0),
        'created_at': task.get('created_at', task.get('timestamp', 0)),
        'timestamp': task.get('created_at', task.get('timestamp', 0)),
        'updated_at': task.get('updated_at', task.get('created_at', 0)),
        'duration': duration_seconds or 0,
        'duration_seconds': duration_seconds or 0,
        'type': task.get('type', 'google-gen'),
        'stage': task.get('stage'),
        'progress_text': task.get('progress_text'),
        'progress': task.get('progress', 0),
        'heartbeat_at': task.get('heartbeat_at'),
        'first_byte_at': task.get('first_byte_at'),
        'bytes_received': task.get('bytes_received', 0),
        'transport_error_type': task.get('transport_error_type'),
        'ttfb_ms': task.get('ttfb_ms'),
        'started_at': task.get('started_at'),
        'finished_at': task.get('finished_at'),
        'is_old': task.get('is_old', False),
    }

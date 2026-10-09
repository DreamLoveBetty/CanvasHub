"""Archive video indexing and metadata probing.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _resolve_ffprobe_executable(*, BASE_DIR, Path, os, shutil, sys):
    executable_name = 'ffprobe.exe' if os.name == 'nt' else 'ffprobe'
    candidates = [
        os.environ.get('FFPROBE_PATH'),
        os.environ.get('FFPROBE_BINARY'),
        shutil.which(executable_name),
        Path(sys.executable).resolve().parent / executable_name,
        Path(BASE_DIR) / executable_name,
    ]
    if os.name != 'nt':
        candidates.extend((
            '/opt/homebrew/bin/ffprobe',
            '/usr/local/bin/ffprobe',
            '/usr/bin/ffprobe',
        ))
    for candidate in candidates:
        if not candidate:
            continue
        try:
            path = Path(candidate).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return ''


def _resolve_archive_video_file(rel_path, *, _ARCHIVE_VIDEO_EXTENSIONS, _resolve_archive_resource_file):
    """Resolve a public archive-relative video path without escaping its root."""
    return _resolve_archive_resource_file(rel_path, _ARCHIVE_VIDEO_EXTENSIONS)


def _parse_video_frame_rate(value, *, math):
    raw = str(value or '').strip()
    if not raw or raw in {'0/0', 'N/A'}:
        return None
    try:
        if '/' in raw:
            numerator, denominator = raw.split('/', 1)
            rate = float(numerator) / float(denominator)
        else:
            rate = float(raw)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if not math.isfinite(rate) or rate <= 0:
        return None
    return round(rate, 3)


def _positive_archive_media_number(value, integer=False, *, math):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return int(number) if integer else number


def _probe_archive_video_metadata(
    filepath,
    stat_result=None,
    *,
    Path,
    _ARCHIVE_VIDEO_METADATA_CACHE,
    _ARCHIVE_VIDEO_METADATA_CACHE_LIMIT,
    _ARCHIVE_VIDEO_METADATA_CACHE_LOCK,
    _parse_video_frame_rate,
    _resolve_ffprobe_executable,
    json,
    math,
    subprocess,
):
    """Read video metadata when ffprobe is available; failures are non-fatal."""
    filepath = Path(filepath)
    try:
        stat_result = stat_result or filepath.stat()
        cache_key = (str(filepath.resolve()), stat_result.st_mtime_ns, stat_result.st_size)
    except OSError:
        return {}

    with _ARCHIVE_VIDEO_METADATA_CACHE_LOCK:
        cached = _ARCHIVE_VIDEO_METADATA_CACHE.get(cache_key)
        if cached is not None:
            return dict(cached)

    metadata = {}
    ffprobe = _resolve_ffprobe_executable()
    if ffprobe:
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    '-v', 'error',
                    '-select_streams', 'v:0',
                    '-show_entries',
                    'stream=width,height,avg_frame_rate,r_frame_rate,duration:format=duration',
                    '-of', 'json',
                    str(filepath),
                ],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            if result.returncode == 0:
                payload = json.loads(result.stdout or '{}')
                streams = payload.get('streams') if isinstance(payload, dict) else []
                stream = streams[0] if isinstance(streams, list) and streams else {}
                format_data = payload.get('format') if isinstance(payload, dict) else {}
                width = int(stream.get('width') or 0)
                height = int(stream.get('height') or 0)
                fps = _parse_video_frame_rate(stream.get('avg_frame_rate') or stream.get('r_frame_rate'))
                duration_raw = stream.get('duration') or (
                    format_data.get('duration') if isinstance(format_data, dict) else None
                )
                duration = float(duration_raw or 0)
                if width > 0:
                    metadata['width'] = width
                if height > 0:
                    metadata['height'] = height
                if fps is not None:
                    metadata['fps'] = fps
                if math.isfinite(duration) and duration > 0:
                    metadata['duration_seconds'] = round(duration, 3)
        except (OSError, subprocess.SubprocessError, TypeError, ValueError, json.JSONDecodeError):
            pass

    with _ARCHIVE_VIDEO_METADATA_CACHE_LOCK:
        stale_keys = [key for key in _ARCHIVE_VIDEO_METADATA_CACHE if key[0] == cache_key[0]]
        for key in stale_keys:
            _ARCHIVE_VIDEO_METADATA_CACHE.pop(key, None)
        _ARCHIVE_VIDEO_METADATA_CACHE[cache_key] = dict(metadata)
        while len(_ARCHIVE_VIDEO_METADATA_CACHE) > _ARCHIVE_VIDEO_METADATA_CACHE_LIMIT:
            _ARCHIVE_VIDEO_METADATA_CACHE.pop(next(iter(_ARCHIVE_VIDEO_METADATA_CACHE)))
    return metadata


def _archive_video_task_map(*, H3_VIDEO_TASK_TYPE, Path, get_all_tasks):
    """Map archived H3 result basenames to an unambiguous persisted task."""
    mapping = {}
    try:
        tasks = get_all_tasks(limit=5000, offset=0)
    except Exception:
        return mapping
    for task in tasks or []:
        if str(task.get('type') or '').strip() != H3_VIDEO_TASK_TYPE:
            continue
        task_id = str(task.get('task_id') or '').strip()
        if not task_id:
            continue
        result_files = task.get('result_files') if isinstance(task.get('result_files'), list) else []
        result_files = list(result_files)
        if task.get('result_file'):
            result_files.append(task.get('result_file'))
        params = task.get('params') if isinstance(task.get('params'), dict) else {}
        if params.get('video_filename'):
            result_files.append(params.get('video_filename'))
        for result_file in result_files:
            name = Path(str(result_file or '')).name
            if not name:
                continue
            previous = mapping.get(name)
            if previous is None or str(previous.get('task_id') or '') == task_id:
                mapping[name] = task
            else:
                mapping[name] = {}
    return {name: task for name, task in mapping.items() if task}


def _public_archive_video_parameters(
    sidecar_parameters,
    task=None,
    metadata=None,
    *,
    _ARCHIVE_VIDEO_PUBLIC_PARAMETER_KEYS,
    re,
):
    """Return only generation controls and measured media values to the UI."""
    combined = {}
    if isinstance(sidecar_parameters, dict):
        combined.update(sidecar_parameters)
        runtime_output = sidecar_parameters.get('runtime_output')
        if isinstance(runtime_output, dict):
            for key in ('width', 'height', 'fps', 'frame_count', 'duration_seconds', 'seed', 'elapsed_seconds'):
                if runtime_output.get(key) is not None:
                    combined[key] = runtime_output.get(key)
    if isinstance(task, dict) and isinstance(task.get('params'), dict):
        for key, value in task.get('params').items():
            if value is not None and value != '':
                combined[key] = value
    if isinstance(metadata, dict):
        for key in ('width', 'height', 'fps', 'duration_seconds'):
            if combined.get(key) in (None, '', 0) and metadata.get(key) is not None:
                combined[key] = metadata.get(key)
    if (not combined.get('width') or not combined.get('height')) and combined.get('size'):
        match = re.fullmatch(r'\s*(\d+)\s*[x×]\s*(\d+)\s*', str(combined.get('size')))
        if match:
            combined.setdefault('width', int(match.group(1)))
            combined.setdefault('height', int(match.group(2)))
    public = {}
    for key in _ARCHIVE_VIDEO_PUBLIC_PARAMETER_KEYS:
        value = combined.get(key)
        if value is None or value == '' or isinstance(value, (dict, list, tuple)):
            continue
        if key == 'seed' and isinstance(value, int) and abs(value) > 9_007_199_254_740_991:
            value = str(value)
        public[key] = value
    return public


def _list_archive_videos(
    limit=200,
    offset=0,
    query='',
    source='generated',
    *,
    Path,
    _ARCHIVE_VIDEO_EXTENSIONS,
    _ARCHIVE_VIDEO_SOURCE_LABELS,
    _archive_video_folder_info,
    _archive_video_task_map,
    _classify_archive_video_source,
    _coerce_archive_video_source,
    _collect_archive_video_resources,
    _parse_archive_video_sidecars,
    _positive_archive_media_number,
    _probe_archive_video_metadata,
    _public_archive_video_parameters,
    archive_scan_roots,
    datetime,
    hashlib,
    json,
    mimetypes,
    os,
    thumb_url_for_media_url,
    urllib,
):
    """List archived videos using only public root-relative path information."""
    search = str(query or '').strip().casefold()
    source_filter = _coerce_archive_video_source(source)
    task_map = _archive_video_task_map()
    seen_files = set()
    candidates = []
    for root_key, root_path in archive_scan_roots():
        try:
            root = root_path.expanduser().resolve()
        except Exception:
            continue
        try:
            walker = os.walk(root, followlinks=False)
            for directory, _, filenames in walker:
                for filename in filenames:
                    if Path(filename).suffix.lower() not in _ARCHIVE_VIDEO_EXTENSIONS:
                        continue
                    candidate = Path(directory) / filename
                    try:
                        if candidate.is_symlink():
                            continue
                        resolved = candidate.resolve()
                        if resolved != root and root not in resolved.parents:
                            continue
                        stat_result = resolved.stat()
                        relative_path = resolved.relative_to(root).as_posix()
                    except (OSError, ValueError):
                        continue
                    physical_key = (
                        ('inode', stat_result.st_dev, stat_result.st_ino)
                        if stat_result.st_ino
                        else ('path', str(resolved))
                    )
                    if physical_key in seen_files:
                        continue
                    public_path = f'{root_key}/{relative_path}'
                    sidecar_data = _parse_archive_video_sidecars(resolved)
                    task = task_map.get(filename)
                    task_prompt = str(task.get('prompt') or '') if isinstance(task, dict) else ''
                    if search:
                        search_parameters = _public_archive_video_parameters(
                            sidecar_data.get('parameters'),
                            task=task,
                        )
                        search_text = '\n'.join((
                            filename,
                            public_path,
                            str(sidecar_data.get('prompt') or ''),
                            task_prompt,
                            json.dumps(search_parameters, ensure_ascii=False),
                        )).casefold()
                        if search not in search_text:
                            continue
                    seen_files.add(physical_key)
                    if isinstance(task, dict):
                        source_type, source_label, is_generated = 'generated', _ARCHIVE_VIDEO_SOURCE_LABELS['generated'], True
                    else:
                        source_type, source_label, is_generated = _classify_archive_video_source(resolved, sidecar_data)
                    candidates.append((
                        stat_result.st_mtime,
                        public_path,
                        root_key,
                        relative_path,
                        resolved,
                        stat_result,
                        source_type,
                        source_label,
                        is_generated,
                        sidecar_data,
                    ))
        except OSError:
            continue

    candidates.sort(key=lambda item: (-item[0], item[1].casefold()))
    source_counts = {
        'generated': sum(1 for item in candidates if item[6] == 'generated'),
        'imported': sum(1 for item in candidates if item[6] == 'imported'),
        'all': len(candidates),
    }
    filtered_candidates = (
        candidates
        if source_filter == 'all'
        else [item for item in candidates if item[6] == source_filter]
    )
    total = len(filtered_candidates)
    format_counts = {}
    total_file_size_bytes = 0
    for _, _, _, _, filepath, stat_result, _, _, _, _ in filtered_candidates:
        extension = filepath.suffix.lower().lstrip('.') or 'unknown'
        format_counts[extension] = format_counts.get(extension, 0) + 1
        total_file_size_bytes += stat_result.st_size
    page = filtered_candidates[offset:offset + limit]
    videos = []
    for (
        modified_timestamp,
        public_path,
        root_key,
        relative_path,
        filepath,
        stat_result,
        source_type,
        source_label,
        is_generated,
        sidecar_data,
    ) in page:
        metadata = _probe_archive_video_metadata(filepath, stat_result)
        mime_type = mimetypes.guess_type(filepath.name)[0] or 'application/octet-stream'
        modified_at = datetime.fromtimestamp(modified_timestamp).astimezone().isoformat(timespec='seconds')
        video_url = f"/video/{urllib.parse.quote(public_path, safe='/')}"
        resources = _collect_archive_video_resources(filepath, root_key, relative_path, sidecar_data)
        folder = _archive_video_folder_info(root_key, relative_path)
        task = task_map.get(filepath.name)
        task_id = str(task.get('task_id') or '').strip() if isinstance(task, dict) else ''
        if not task_id:
            candidate_task_id = str((sidecar_data.get('frontmatter') or {}).get('task_id') or '').strip()
            task_id = candidate_task_id if candidate_task_id.startswith('h3v_') else ''
        prompt = str(task.get('prompt') or '').strip() if isinstance(task, dict) else ''
        prompt = prompt or str(sidecar_data.get('prompt') or '')
        parameters = _public_archive_video_parameters(
            sidecar_data.get('parameters'),
            task=task,
            metadata=metadata,
        )
        media_width = _positive_archive_media_number(metadata.get('width'), integer=True) or _positive_archive_media_number(parameters.get('width'), integer=True)
        media_height = _positive_archive_media_number(metadata.get('height'), integer=True) or _positive_archive_media_number(parameters.get('height'), integer=True)
        media_duration = _positive_archive_media_number(metadata.get('duration_seconds')) or _positive_archive_media_number(parameters.get('duration_seconds'))
        media_fps = _positive_archive_media_number(metadata.get('fps')) or _positive_archive_media_number(parameters.get('fps'))
        reference_images = [resource for resource in resources if resource.get('type') == 'image']
        videos.append({
            'id': hashlib.sha256(public_path.encode('utf-8')).hexdigest()[:24],
            'name': filepath.name,
            'file_name': filepath.name,
            'url': video_url,
            'video_url': video_url,
            'poster_url': thumb_url_for_media_url(video_url, size=480),
            'path': public_path,
            'relative_path': relative_path,
            'root_key': root_key,
            'mime_type': mime_type,
            'file_size': stat_result.st_size,
            'file_size_bytes': stat_result.st_size,
            'created_at': modified_at,
            'modified_at': modified_at,
            'width': media_width,
            'height': media_height,
            'duration_seconds': media_duration,
            'fps': media_fps,
            'task_id': task_id,
            'prompt': prompt[:20_000],
            'parameters': parameters,
            'resources': resources,
            'resource_count': len(resources),
            'resource_folder': folder,
            'reference_images': reference_images,
            'has_prompt': bool(prompt),
            'has_parameters': bool(parameters),
            'has_reference_images': bool(reference_images),
            'source_type': source_type,
            'source_label': source_label,
            'is_generated': is_generated,
        })
    return {
        'ok': True,
        'videos': videos,
        'count': len(videos),
        'total': total,
        'stats': {
            'total': total,
            'all': source_counts['all'],
            'generated': source_counts['generated'],
            'imported': source_counts['imported'],
            'by_source': dict(source_counts),
            'total_file_size_bytes': total_file_size_bytes,
            'by_format': format_counts,
        },
        'limit': limit,
        'offset': offset,
        'source': source_filter,
        'has_more': offset + len(videos) < total,
    }

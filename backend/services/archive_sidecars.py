"""Archive video sidecars and associated resource discovery.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _coerce_archive_video_source(value, default='generated', *, _ARCHIVE_VIDEO_SOURCE_TYPES):
    source = str(value or default).strip().lower()
    return source if source in _ARCHIVE_VIDEO_SOURCE_TYPES else default


def _read_archive_video_sidecar(path, *, Path, _ARCHIVE_VIDEO_SIDECAR_MAX_BYTES):
    """Read a bounded, regular sibling sidecar without following symlinks."""
    sidecar = Path(path)
    try:
        if sidecar.is_symlink() or not sidecar.is_file():
            return ''
        with sidecar.open('rb') as stream:
            payload = stream.read(_ARCHIVE_VIDEO_SIDECAR_MAX_BYTES + 1)
    except OSError:
        return ''
    if len(payload) > _ARCHIVE_VIDEO_SIDECAR_MAX_BYTES:
        return ''
    return payload.decode('utf-8', errors='replace')


def _decode_archive_sidecar_value(value, *, json):
    raw = str(value or '').strip()
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return raw.split(' #', 1)[0].strip().strip("'\"")


def _parse_archive_markdown_frontmatter(content, *, _decode_archive_sidecar_value):
    text = str(content or '').lstrip('\ufeff')
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        return {}, text
    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() in {'---', '...'}),
        None,
    )
    if closing_index is None:
        return {}, text
    metadata = {}
    for line in lines[1:closing_index]:
        key, separator, value = line.partition(':')
        key = key.strip()
        if separator and key:
            metadata[key] = _decode_archive_sidecar_value(value)
    return metadata, '\n'.join(lines[closing_index + 1:])


def _archive_markdown_section(content, title, *, re):
    heading = re.search(
        rf'(?im)^#{{1,6}}[ \t]+{re.escape(str(title or "").strip())}[ \t]*$',
        str(content or ''),
    )
    if not heading:
        return ''
    tail = str(content or '')[heading.end():]
    next_heading = re.search(r'(?m)^#{1,6}[ \t]+\S.*$', tail)
    section = tail[:next_heading.start()] if next_heading else tail
    return section.strip()


def _strip_archive_markdown_fence(content, *, re):
    lines = str(content or '').strip().splitlines()
    if len(lines) < 2:
        return '\n'.join(lines).strip()
    opening = re.fullmatch(r'[ \t]*(`{3,}|~{3,})[^`~]*[ \t]*', lines[0])
    if not opening:
        return '\n'.join(lines).strip()
    fence = opening.group(1)
    closing_index = next(
        (
            index
            for index in range(len(lines) - 1, 0, -1)
            if re.fullmatch(rf'[ \t]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*', lines[index])
        ),
        None,
    )
    if closing_index is None:
        return '\n'.join(lines).strip()
    return '\n'.join(lines[1:closing_index]).strip()


def _extract_archive_json_object(content, preferred_task_type='', *, json, re):
    text = str(content or '')
    decoder = json.JSONDecoder()
    best = None
    for match in re.finditer(r'\{', text):
        start = match.start()
        try:
            payload, end = decoder.raw_decode(text, start)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        task_type = str(payload.get('task_type') or '').strip()
        score = (
            int(bool(preferred_task_type and task_type == preferred_task_type)),
            int(bool(task_type)),
            end - start,
            start,
        )
        if best is None or score > best[0]:
            best = (score, payload, start, end)
    if best is None:
        return {}, None, None
    return dict(best[1]), best[2], best[3]


def _parse_archive_video_text_sidecar(
    video_path,
    *,
    H3_VIDEO_TASK_TYPE,
    Path,
    _extract_archive_json_object,
    _read_archive_video_sidecar,
    _strip_archive_markdown_fence,
):
    content = _read_archive_video_sidecar(Path(video_path).with_suffix('.txt'))
    if not content:
        return {'prompt': '', 'parameters': {}}
    parameters, json_start, json_end = _extract_archive_json_object(
        content,
        preferred_task_type=H3_VIDEO_TASK_TYPE,
    )
    if json_start is None:
        prompt = content.strip()
    else:
        prompt_parts = [content[:json_start].strip(), content[json_end:].strip()]
        prompt = '\n\n'.join(part for part in prompt_parts if part)
    return {
        'prompt': _strip_archive_markdown_fence(prompt)[:20_000],
        'parameters': parameters,
    }


def _parse_archive_video_markdown_sidecar(
    video_path,
    *,
    H3_VIDEO_TASK_TYPE,
    Path,
    _archive_markdown_section,
    _extract_archive_json_object,
    _parse_archive_markdown_frontmatter,
    _read_archive_video_sidecar,
    _strip_archive_markdown_fence,
    re,
):
    content = _read_archive_video_sidecar(Path(video_path).with_suffix('.md'))
    if not content:
        return {'frontmatter': {}, 'prompt': '', 'parameters': {}, 'links': []}
    frontmatter, body = _parse_archive_markdown_frontmatter(content)
    prompt = _strip_archive_markdown_fence(_archive_markdown_section(body, 'Prompt'))[:20_000]
    parameters_section = _archive_markdown_section(body, 'Parameters')
    parameters, _, _ = _extract_archive_json_object(
        parameters_section,
        preferred_task_type=H3_VIDEO_TASK_TYPE,
    )
    links = []
    links.extend(match.group(1).strip() for match in re.finditer(r'!\[\[([^\]|#]+)', body))
    for match in re.finditer(r'!\[[^\]]*\]\((?:<([^>]+)>|([^\)]+))\)', body):
        links.append(str(match.group(1) or match.group(2) or '').strip())
    return {
        'frontmatter': frontmatter,
        'prompt': prompt,
        'parameters': parameters,
        'links': links,
    }


def _parse_archive_video_sidecars(
    video_path,
    *,
    H3_VIDEO_TASK_TYPE,
    _parse_archive_video_markdown_sidecar,
    _parse_archive_video_text_sidecar,
):
    text_data = _parse_archive_video_text_sidecar(video_path)
    markdown_data = _parse_archive_video_markdown_sidecar(video_path)
    parameters = dict(markdown_data.get('parameters') or {})
    parameters.update(text_data.get('parameters') or {})
    markdown_generated = str((markdown_data.get('frontmatter') or {}).get('type') or '').strip().casefold() == 'video_prompt'
    text_generated = str(parameters.get('task_type') or '').strip() == H3_VIDEO_TASK_TYPE
    if text_generated and text_data.get('prompt'):
        prompt = text_data.get('prompt')
    else:
        prompt = markdown_data.get('prompt') or text_data.get('prompt') or ''
    return {
        'prompt': str(prompt or '')[:20_000],
        'parameters': parameters,
        'frontmatter': dict(markdown_data.get('frontmatter') or {}),
        'links': list(markdown_data.get('links') or []),
        'markdown_generated': markdown_generated,
        'text_generated': text_generated,
    }


def _archive_video_markdown_is_generated(video_path, *, _parse_archive_video_sidecars):
    return bool(_parse_archive_video_sidecars(video_path).get('markdown_generated'))


def _archive_video_text_is_generated(video_path, *, _parse_archive_video_sidecars):
    return bool(_parse_archive_video_sidecars(video_path).get('text_generated'))


def _classify_archive_video_source(
    video_path,
    sidecar_data=None,
    *,
    _ARCHIVE_VIDEO_SOURCE_LABELS,
    _parse_archive_video_sidecars,
):
    sidecar_data = sidecar_data or _parse_archive_video_sidecars(video_path)
    is_generated = bool(sidecar_data.get('markdown_generated') or sidecar_data.get('text_generated'))
    source_type = 'generated' if is_generated else 'imported'
    return source_type, _ARCHIVE_VIDEO_SOURCE_LABELS[source_type], is_generated


def _archive_resource_url(resource_type, public_path, *, urllib):
    encoded = urllib.parse.quote(public_path, safe='/')
    if resource_type == 'video':
        return f'/video/{encoded}'
    if resource_type == 'image':
        return f'/archive_image/{encoded}'
    return f'/archive_resource/{encoded}'


def _archive_resource_entry(
    filepath,
    root_key,
    root,
    resource_type,
    role,
    label,
    *,
    Path,
    _archive_resource_url,
    datetime,
    hashlib,
    mimetypes,
):
    filepath = Path(filepath)
    try:
        if filepath.is_symlink() or not filepath.is_file():
            return None
        resolved = filepath.resolve()
        if resolved != root and root not in resolved.parents:
            return None
        stat_result = resolved.stat()
        relative_path = resolved.relative_to(root).as_posix()
    except (OSError, ValueError):
        return None
    public_path = f'{root_key}/{relative_path}'
    mime_type = mimetypes.guess_type(resolved.name)[0] or 'application/octet-stream'
    modified_at = datetime.fromtimestamp(stat_result.st_mtime).astimezone().isoformat(timespec='seconds')
    resource_id = hashlib.sha256(f'{role}:{public_path}'.encode('utf-8')).hexdigest()[:24]
    return {
        'id': resource_id,
        'type': resource_type,
        'kind': resource_type,
        'role': role,
        'label': label,
        'name': resolved.name,
        'file_name': resolved.name,
        'path': public_path,
        'relative_path': relative_path,
        'root_key': root_key,
        'url': _archive_resource_url(resource_type, public_path),
        'resource_url': _archive_resource_url(resource_type, public_path),
        'mime_type': mime_type,
        'file_size_bytes': stat_result.st_size,
        'modified_at': modified_at,
    }


def _iter_archive_reference_values(value, key='', *, _ARCHIVE_REFERENCE_PARAM_KEYS, _iter_archive_reference_values, re):
    key_name = re.sub(r'[^a-z0-9_]+', '_', str(key or '').strip().casefold()).strip('_')
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            yield from _iter_archive_reference_values(child_value, child_key)
        return
    if isinstance(value, (list, tuple)):
        for child_value in value:
            yield from _iter_archive_reference_values(child_value, key)
        return
    if key_name in _ARCHIVE_REFERENCE_PARAM_KEYS and isinstance(value, str):
        text = value.strip()
        if text:
            yield text


def _resolve_same_directory_archive_image(
    reference,
    video_path,
    *,
    Path,
    _ARCHIVE_IMAGE_EXTENSIONS,
    _resolve_archive_resource_file,
    urllib,
):
    """Resolve an explicitly referenced image and require the video's directory."""
    raw = str(reference or '').strip().strip('<>')
    if not raw or raw.startswith(('data:', 'http://', 'https://')):
        return None
    raw = raw.split('|', 1)[0].split('#', 1)[0].strip()
    if not raw or raw.startswith(('/', '\\')) or '\x00' in raw:
        return None
    raw = urllib.parse.unquote(raw).replace('\\', '/')
    basename = raw.rsplit('/', 1)[-1]
    if not basename or basename in {'.', '..'}:
        return None
    if '/' not in raw or raw.startswith('./'):
        candidate = Path(video_path).parent / basename
        try:
            if candidate.is_symlink() or not candidate.is_file():
                return None
            resolved = candidate.resolve()
        except OSError:
            return None
    else:
        resolved = _resolve_archive_resource_file(raw, _ARCHIVE_IMAGE_EXTENSIONS)
        if not resolved:
            return None
    if resolved.suffix.lower() not in _ARCHIVE_IMAGE_EXTENSIONS:
        return None
    try:
        if resolved.parent != Path(video_path).parent.resolve() or resolved.is_symlink():
            return None
    except OSError:
        return None
    return resolved


def _archive_image_name_looks_associated(video_stem, image_name, *, Path, _ARCHIVE_ASSOCIATED_IMAGE_TOKENS):
    stem = str(video_stem or '').casefold()
    image_stem = Path(image_name).stem.casefold()
    if not stem or image_stem == stem:
        return bool(stem and image_stem == stem)
    if not image_stem.startswith(stem):
        return False
    suffix = image_stem[len(stem):].lstrip('_-. ')
    return any(token in suffix for token in _ARCHIVE_ASSOCIATED_IMAGE_TOKENS)


def _archive_video_folder_info(root_key, relative_path, *, Path, hashlib):
    relative = Path(relative_path)
    directory = relative.parent.as_posix()
    if directory == '.':
        directory = ''
    public_path = f'{root_key}/{relative.as_posix()}'
    return {
        'id': hashlib.sha256(public_path.encode('utf-8')).hexdigest()[:24],
        'name': relative.stem,
        'path': public_path,
        'relative_path': relative.as_posix(),
        'directory': directory,
        'root_key': root_key,
    }


def _collect_archive_video_resources(
    filepath,
    root_key,
    relative_path,
    sidecar_data,
    *,
    Path,
    _ARCHIVE_IMAGE_EXTENSIONS,
    _archive_image_name_looks_associated,
    _archive_resource_entry,
    _iter_archive_reference_values,
    _resolve_same_directory_archive_image,
    archive_scan_roots,
):
    filepath = Path(filepath)
    try:
        root = next(
            root_path.expanduser().resolve()
            for key, root_path in archive_scan_roots()
            if key == root_key
        )
    except (StopIteration, OSError):
        return []

    resources = []
    seen_paths = set()

    def add(path, resource_type, role, label):
        try:
            key = str(Path(path).resolve())
        except OSError:
            return
        if key in seen_paths:
            return
        resource = _archive_resource_entry(path, root_key, root, resource_type, role, label)
        if not resource:
            return
        seen_paths.add(key)
        resources.append(resource)

    add(filepath, 'video', 'output_video', '视频')
    txt_path = filepath.with_suffix('.txt')
    md_path = filepath.with_suffix('.md')
    add(txt_path, 'text', 'prompt_text', '提示词 TXT')
    add(md_path, 'markdown', 'prompt_markdown', '提示词 Markdown')

    references = []
    parameters = sidecar_data.get('parameters') if isinstance(sidecar_data, dict) else {}
    references.extend(_iter_archive_reference_values(parameters))
    frontmatter = sidecar_data.get('frontmatter') if isinstance(sidecar_data, dict) else {}
    references.extend(_iter_archive_reference_values(frontmatter))
    references.extend(sidecar_data.get('links') or [] if isinstance(sidecar_data, dict) else [])
    for reference in references:
        resolved = _resolve_same_directory_archive_image(reference, filepath)
        if resolved:
            add(resolved, 'image', 'reference_image', '参考图片')

    try:
        directory_entries = list(filepath.parent.iterdir())
    except OSError:
        directory_entries = []
    for entry in directory_entries:
        try:
            if entry.is_symlink() or not entry.is_file() or entry.suffix.lower() not in _ARCHIVE_IMAGE_EXTENSIONS:
                continue
        except OSError:
            continue
        if not _archive_image_name_looks_associated(filepath.stem, entry.name):
            continue
        role = 'reference_image' if any(
            token in entry.stem.casefold() for token in ('reference', 'first_frame', 'source', 'input')
        ) else 'associated_image'
        label = '参考图片' if role == 'reference_image' else '关联图片'
        add(entry, 'image', role, label)
    return resources

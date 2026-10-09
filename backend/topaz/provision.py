"""Import a prevalidated Topaz runtime into persistent CanvasHub app data.

The source is an isolated, filtered Contents tree (not the full vendor App).
Copy-on-write clones are real files, not links back to the source. Installation
is explicit and never runs from a request handler or during server startup.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from backend.app_config import APP_DATA_DIR
from .catalog import MODELS, capabilities


def audit_links(contents: Path) -> None:
    root = contents.resolve(strict=True)
    for link in root.rglob('*'):
        if not link.is_symlink():
            continue
        target = link.resolve(strict=False)
        if not target.is_relative_to(root) or not target.exists():
            raise RuntimeError(f'Topaz runtime 存在外部或断开的软链接：{link.relative_to(root)}')


def require_complete(contents: Path) -> None:
    found = {entry['id']: entry for entry in capabilities(contents)}
    missing = [f"{key}: {found.get(key, {}).get('error', '未列出')}"
               for key in MODELS if not found.get(key, {}).get('available')]
    if missing:
        raise RuntimeError('Topaz runtime 未通过完整性检查：' + '; '.join(missing[:5]))


def install(source: Path, root: Path) -> Path:
    source = Path(source).expanduser().resolve(strict=True)
    root = Path(root).expanduser().resolve()
    destination = root / 'vendor' / 'Contents'
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f'Topaz 自有 runtime 已存在，不覆盖运行中的资源：{destination}')
    if root.is_relative_to(source) or source.is_relative_to(root):
        raise ValueError('Topaz runtime 源和目标目录不得重叠')
    audit_links(source)
    require_complete(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f'.Contents-install-{uuid.uuid4().hex}'
    try:
        # macOS APFS clone: source bytes become independent copy-on-write files.
        # Do not replace this with symlinks to a disposable test directory.
        subprocess.run(['cp', '-c', '-R', str(source), str(temporary)], check=True)
        audit_links(temporary)
        require_complete(temporary)
        os.replace(temporary, destination)
        (destination.parent / 'runtime.json').write_text(json.dumps({
            'schema_version': 1, 'models_verified': len(MODELS),
            'resource_path': str(destination), 'source_type': 'isolated_filtered_contents',
        }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return destination
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main() -> None:
    parser = argparse.ArgumentParser(description='导入已过滤且隔离验证的 Topaz Contents 到 CanvasHub 数据目录')
    parser.add_argument('--source', type=Path, required=True, help='已验证的独立 Contents 目录')
    parser.add_argument('--root', type=Path, default=APP_DATA_DIR / 'components' / 'topaz')
    args = parser.parse_args()
    print(install(args.source, args.root))


if __name__ == '__main__':
    main()

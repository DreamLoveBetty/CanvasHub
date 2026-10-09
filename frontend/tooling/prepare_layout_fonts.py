#!/usr/bin/env python3
"""Prepare Source Han Serif SC web fonts without changing the source collection.

Optional, offline-only tooling; never imported or run by the HTTP server.
Use a separate tooling environment (not the application's runtime environment):

    python3 -m venv /path/to/font-tools
    /path/to/font-tools/bin/python -m pip install 'fonttools[woff]==4.63.0'
    /path/to/font-tools/bin/python frontend/tooling/prepare_layout_fonts.py \
        --source font/思源宋体.ttc --outdir /path/to/new-font-output

After validation, put the seven resulting WOFF2 files beside the original TTC.
The regular companion has the same stem as the source; the catalog prefers it.
No glyph subsetting, source replacement, startup conversion or package download.
Existing output files are never overwritten. To regenerate, use a new directory.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile


FACE_WEIGHTS = {
    'ExtraLight': 200, 'Light': 300, 'Regular': 400, 'Medium': 500,
    'SemiBold': 600, 'Bold': 700, 'Heavy': 900,
}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def prepare_fonts(source: Path, outdir: Path) -> dict:
    try:
        from fontTools.ttLib import TTCollection, TTFont
    except ImportError as error:
        raise RuntimeError('Install fonttools[woff]==4.63.0 in a separate tooling environment.') from error

    source = source.resolve(strict=True)
    outdir = outdir.resolve()
    source_hash = file_hash(source)
    selected = {}
    with TTCollection(source, lazy=True) as collection:
        for index, font in enumerate(collection.fonts):
            name = font['name'].getDebugName(6) or ''
            prefix = 'SourceHanSerifSC-'
            if not name.startswith(prefix):
                continue
            suffix = name[len(prefix):]
            if suffix not in FACE_WEIGHTS or suffix in selected:
                raise ValueError(f'Unexpected or duplicate SC face: {name}')
            selected[suffix] = index
    if set(selected) != set(FACE_WEIGHTS):
        raise ValueError('Expected all seven SourceHanSerifSC weights in the collection.')

    filenames = {
        suffix: source.stem + ('' if suffix == 'Regular' else '-' + suffix) + '.woff2'
        for suffix in FACE_WEIGHTS
    }
    if any((outdir / name).exists() or (outdir / name).is_symlink() for name in filenames.values()):
        raise FileExistsError('Output font already exists; choose a new output directory.')
    outdir.mkdir(parents=True, exist_ok=True)
    faces = []
    installed = []
    with tempfile.TemporaryDirectory(prefix='.layout-fonts-', dir=outdir) as stage:
        stage = Path(stage)
        for suffix, weight in FACE_WEIGHTS.items():
            path = stage / filenames[suffix]
            with TTFont(source, fontNumber=selected[suffix], lazy=True,
                        recalcTimestamp=False, recalcBBoxes=False) as font:
                original_cmap = font.getBestCmap()
                glyphs = font['maxp'].numGlyphs
                font.flavor = 'woff2'
                font.save(path)
            with TTFont(path, lazy=True) as webfont:
                if webfont['maxp'].numGlyphs != glyphs or webfont.getBestCmap() != original_cmap:
                    raise ValueError(f'Glyph coverage changed: {path.name}')
            with path.open('rb') as stream:
                header = stream.read(20)
                sfnt_size = struct.unpack('>I', header[16:20])[0]
                if header[:4] != b'wOF2' or sfnt_size >= 128 * 1024 * 1024:
                    raise ValueError(f'Invalid or oversized web font: {path.name}')
            digest = file_hash(path)
            faces.append({'file': path.name, 'weight': weight, 'source_index': selected[suffix],
                          'glyph_count': glyphs, 'bytes': path.stat().st_size,
                          'decoded_bytes': sfnt_size, 'sha256': digest})
        if file_hash(source) != source_hash:
            raise ValueError('Source collection changed during conversion; no output installed.')
        try:
            for face in faces:
                destination = outdir / face['file']
                # Exclusive, atomic publication: even a concurrent file is not overwritten.
                os.link(stage / face['file'], destination)
                installed.append(destination)
        except OSError:
            for path in installed:
                if path.samefile(stage / path.name):
                    path.unlink()
            raise
    return {'source': source.name, 'source_sha256': source_hash,
            'source_bytes': source.stat().st_size, 'family': source.stem, 'faces': faces}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--outdir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare_fonts(args.source, args.outdir), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

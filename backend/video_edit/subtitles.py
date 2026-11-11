"""Burned-in subtitles (phase 3b): each cue becomes one transparent PNG that compose overlays
between its start and end. The system FFmpeg has no libass/drawtext, so text is drawn here with
Pillow and FreeType instead; FFmpeg only places images.

Sizes follow the output: the font is a share of the short side, wrapped to 86% of the width
(CJK breaks between any two characters, Latin between words), at most MAX_LINES lines, placed a
fixed share from the bottom or top edge. desktop-video-compose-subtitles.js mirrors the numbers
for the draft preview.

Fonts come from the project's flat font catalog (the one the layout editor serves at /font/):
only files FreeType reads (TTF/OTF/TTC). The browser preview may use a same-stem .woff2
companion of the same face.
"""
from __future__ import annotations

from pathlib import Path
import re

from .contracts import SUBTITLE_DEFAULTS

SIZES = {'small': 0.045, 'medium': 0.055, 'large': 0.07}
MARGIN = 0.08
WRAP = 0.86
LINE_HEIGHT = 1.3
MAX_LINES = 3
BOX_ALPHA = 150
NATIVE = ('.ttf', '.otf', '.ttc')
WEB = ('.woff2', '.woff')
DEFAULT_FONTS = ('ChironGoRoundTC-Bold.ttf', 'ChironGoRoundTC-SemiBold.ttf')
SYSTEM_FONTS = ('/System/Library/Fonts/STHeiti Medium.ttc', '/System/Library/Fonts/Hiragino Sans GB.ttc',
                '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc')
# A run of Latin letters/digits (with in-word punctuation) stays on one line; anything else breaks.
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’.,!?:;%&+\-]*|\s+|.")
# Closing punctuation stays at the end of the line it follows instead of starting the next one.
NO_LINE_START = frozenset('，。、；：！？）」』》〉】…,.;:!?)]')


def catalog(font_dir) -> list[dict]:
    """Fonts subtitles can use: {file, label, url}; url is what the browser preview loads."""
    root = Path(font_dir) if font_dir else None
    if not root or not root.is_dir():
        return []
    files = sorted((path for path in root.iterdir() if path.is_file()), key=lambda path: path.name.lower())
    web = {path.stem: path.name for path in files if path.suffix.lower() in WEB}
    return [{'file': path.name, 'label': path.stem, 'url': '/font/' + web.get(path.stem, path.name)}
            for path in files if path.suffix.lower() in NATIVE]


def font_path(font_dir, name: str = '') -> Path:
    """The chosen catalog file, else the default round face, else a system CJK font."""
    root = Path(font_dir) if font_dir else None
    if name:
        path = (root / name).resolve() if root else None
        if not path or path.parent != root.resolve() or not path.is_file() or path.suffix.lower() not in NATIVE:
            raise ValueError(f'找不到字幕字体：{name}')
        return path
    for candidate in [*(root / default for default in DEFAULT_FONTS if root), *map(Path, SYSTEM_FONTS)]:
        if candidate.is_file():
            return candidate
    raise RuntimeError('没有可用于字幕的中文字体，请在 font/ 放入 TTF/OTF 字体')


def metrics(style: dict, width: int, height: int) -> dict:
    short = min(width, height)
    size = max(12, round(short * SIZES.get(style.get('size'), SIZES[SUBTITLE_DEFAULTS['size']])))
    return {'size': size, 'line': round(size * LINE_HEIGHT), 'stroke': max(2, round(size * 0.08)),
            'pad_x': round(size * 0.45), 'pad_y': round(size * 0.22), 'radius': round(size * 0.25),
            'margin': round(height * MARGIN), 'wrap': round(width * WRAP)}


def wrap(text: str, measure, limit: float) -> list[str]:
    """Greedy wrap per explicit line; a single over-long Latin word is split by characters."""
    lines = []
    for paragraph in text.split('\n'):
        line = ''
        for token in TOKEN.findall(paragraph):
            if token.isspace() and not line:
                continue
            if measure(line + token) <= limit or (token in NO_LINE_START and line.strip()):
                line += token
                continue
            if line.strip():
                lines.append(line.rstrip())
            line = '' if token.isspace() else token
            while measure(line) > limit and len(line) > 1:
                cut = len(line) - 1
                while cut > 1 and measure(line[:cut]) > limit:
                    cut -= 1
                lines.append(line[:cut])
                line = line[cut:]
        if line.strip() or not lines:
            lines.append(line.rstrip())
    return lines


class Layout:
    """The font and per-cue line breaks for one output size; raises if a cue does not fit."""

    def __init__(self, cues: list[dict], style: dict, *, width: int, height: int, font_file: Path):
        from PIL import ImageFont

        self.style, self.width, self.height = style, width, height
        self.m = metrics(style, width, height)
        self.font = ImageFont.truetype(str(font_file), self.m['size'])
        self.outline = style.get('look') != 'box'
        self.stroke = self.m['stroke'] if self.outline else 0
        # Outlined text only needs room for its stroke; the box keeps its own padding.
        self.pad = (self.stroke + 2, self.stroke + 2) if self.outline else (self.m['pad_x'], self.m['pad_y'])
        self.cues = []
        for position, cue in enumerate(cues, 1):
            lines = wrap(cue['text'], self.font.getlength, self.m['wrap'] - 2 * self.pad[0])
            if len(lines) > MAX_LINES:
                raise ValueError(f'第 {position} 条字幕太长，换行后超过 {MAX_LINES} 行')
            self.cues.append(dict(cue, lines=lines))

    def render(self, folder: Path) -> list[dict]:
        """One PNG per cue in `folder`: [{path, x, y, start, end}] in cue order."""
        from PIL import Image, ImageDraw

        m, (pad_x, pad_y) = self.m, self.pad
        overlays = []
        for position, cue in enumerate(self.cues, 1):
            lines = cue['lines']
            text_w = max(1, round(max(self.font.getlength(line) for line in lines)))
            image_w, image_h = text_w + 2 * pad_x, m['line'] * len(lines) + 2 * pad_y
            image = Image.new('RGBA', (image_w, image_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            if not self.outline:
                draw.rounded_rectangle((0, 0, image_w - 1, image_h - 1), radius=m['radius'], fill=(0, 0, 0, BOX_ALPHA))
            for row, line in enumerate(lines):
                # 'mm' centres each line in its line box, so mixed scripts share one band.
                draw.text((image_w / 2, pad_y + m['line'] * (row + 0.5)), line, font=self.font, anchor='mm',
                          fill=(255, 255, 255, 255), stroke_width=self.stroke, stroke_fill=(0, 0, 0, 255))
            path = Path(folder) / f'cue_{position:03d}.png'
            image.save(path)
            y = m['margin'] if self.style.get('position') == 'top' else self.height - m['margin'] - image_h
            overlays.append({'path': path, 'x': max(0, (self.width - image_w) // 2),
                             'y': max(0, min(self.height - image_h, y)), 'start': cue['start'], 'end': cue['end']})
        return overlays


def _clock(seconds: float) -> str:
    millis = round(seconds * 1000)
    return f'{millis // 3600000:02d}:{millis // 60000 % 60:02d}:{millis // 1000 % 60:02d},{millis % 1000:03d}'


def srt(cues: list[dict]) -> str:
    return '\n'.join(f'{index}\n{_clock(cue["start"])} --> {_clock(cue["end"])}\n{cue["text"]}\n'
                     for index, cue in enumerate(cues, 1))

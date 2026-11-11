"""ASR limits and rules shared by the server side and the isolated worker request; no I/O."""
from __future__ import annotations

import re

ENGINE = "Qwen3-ASR 1.7B"
EVENT_PREFIX = "ASR_EVENT "
PYTHON_VERSION = "3.12"
# The forced aligner takes at most 180 s in one pass, which is also the compose limit.
MAX_AUDIO_SECONDS = 180
# Text script of Chinese results: OpenCC configs run inside the worker (length-preserving, so the
# aligned timestamps still index the converted text).
SCRIPTS = {"original": "", "traditional": "s2tw", "simplified": "t2s"}
CHINESE_LANGUAGES = ("Chinese", "Cantonese")

_FILLER_CHARS = set("啊阿哦噢喔嗯唔呃额诶欸哎唉嘿哈呀哇嘛呵吖")
_FILLER_WORDS = {"oh", "ah", "uh", "um", "umm", "hmm", "mm", "mhm", "ha", "haha", "hah", "eh", "huh", "ooh", "aah"}


def max_new_tokens(seconds: float) -> int:
    """Generation cap from the audio length. Music can make the model repeat a filler until the cap
    (a 12 s clip took 25 s at 1024 tokens, 3 s at 128); speech stays well under 8 tokens a second."""
    return int(min(2048, 32 + 8 * max(0.0, float(seconds))))


def timeout_seconds(seconds: float) -> int:
    """Whole worker run: model load plus recognition and alignment, generous for a cold start."""
    return int(180 + 3 * max(0.0, float(seconds)))


def is_filler(text: str) -> bool:
    """True for no speech: empty, or only short interjections (Qwen3-ASR answers music with 「啊。」/"Oh.")."""
    value = str(text or "").strip().lower()
    words = re.findall(r"[a-z]+", value)
    letters = [char for char in value if char.isalnum() and not ("a" <= char <= "z")]
    if not words and not letters:
        return True
    if words and letters:
        return False
    if words:
        return len(words) <= 4 and all(word in _FILLER_WORDS for word in words)
    return len(letters) <= 4 and all(char in _FILLER_CHARS for char in letters)


def script_config(script: str, language: str) -> str:
    """OpenCC config for this result, or '' to keep it (non-Chinese text is never converted)."""
    if script not in SCRIPTS:
        raise ValueError("文字转换选项无效")
    return SCRIPTS[script] if any(name in str(language or "") for name in CHINESE_LANGUAGES) else ""

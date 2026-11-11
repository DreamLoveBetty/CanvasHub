"""One-shot ASR worker, run by runtime.py inside components/asr/venv (Python 3.12).

argv: <request.json> <result.json>. The request names a 16 kHz mono WAV, the two model folders,
the generation cap and the text script. The worker loads Qwen3-ASR with its forced aligner,
transcribes once with timestamps and writes
    {"language", "text", "tokens": [{"start", "end", "text"}]}
where each token is one aligned unit (a CJK character or a word) carrying the punctuation and
spaces that follow it in the text, so the server can cut subtitle cues at punctuation. Then it
exits: nothing stays resident. Progress lines go to stdout as `ASR_EVENT {json}`.

Only the pure backend.asr.contracts and backend.local_image.parent_watch are imported from the
project (PYTHONPATH is the project root); everything else is the isolated environment's.
"""
import json
import os
import sys
import time

from backend.asr.contracts import EVENT_PREFIX, script_config
from backend.local_image.parent_watch import start_parent_watch


def emit(event, **values):
    print(EVENT_PREFIX + json.dumps({"event": event, **values}, ensure_ascii=False), flush=True)


def attach_text(text, items):
    """[(start, end, slice)] where slice runs from this item to the next one in `text`.

    `items` are the aligner's units (punctuation removed); each is looked up in order. A unit that
    cannot be found keeps its own text and the cursor stays put."""
    found, cursor, lowered = [], 0, text.lower()
    for item in items:
        word = str(item.text)
        index = lowered.find(word.lower(), cursor) if word else -1
        found.append([float(item.start_time), float(item.end_time), index, word])
        if index >= 0:
            cursor = index + len(word)
    tokens, stop = [], len(text)
    for start, end, index, word in reversed(found):  # each located slice ends where the next one starts
        if index < 0:
            tokens.append((start, end, word, None))
        else:
            tokens.append((start, end, text[index:stop], (index, stop)))
            stop = index
    tokens.reverse()
    return tokens


def convert(text, tokens, config):
    """Apply an OpenCC config to the text and every token. s2tw/t2s keep the length, so slices index
    the converted text; if a conversion ever changes it, each token is converted on its own."""
    if not config:
        return text, [{"start": s, "end": e, "text": t} for s, e, t, _ in tokens]
    import opencc
    converter = opencc.OpenCC(config)
    converted = converter.convert(text)
    same = len(converted) == len(text)
    out = []
    for start, end, value, span in tokens:
        piece = converted[span[0]:span[1]] if same and span else converter.convert(value)
        out.append({"start": start, "end": end, "text": piece})
    return converted, out


def main(request_path, result_path):
    started = time.monotonic()
    start_parent_watch()
    with open(request_path, encoding="utf-8") as stream:
        request = json.load(stream)
    emit("progress", ratio=0.05, stage="加载语音识别模型")
    import torch
    from qwen_asr import Qwen3ASRModel
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "mps" else torch.float32
    model = Qwen3ASRModel.from_pretrained(
        request["model"], forced_aligner=request["aligner"],
        forced_aligner_kwargs={"dtype": dtype, "device_map": device},
        dtype=dtype, device_map=device, max_inference_batch_size=1, max_new_tokens=int(request["max_new_tokens"]))
    emit("progress", ratio=0.3, stage="识别语音并对齐时间")
    result = model.transcribe(request["audio"], language=request.get("language") or None, return_time_stamps=True)[0]
    language, text = str(result.language or ""), str(result.text or "")
    tokens = attach_text(text, list(result.time_stamps or [])) if text.strip() else []
    text, tokens = convert(text, tokens, script_config(request.get("script") or "original", language))
    payload = {"language": language, "text": text, "tokens": tokens, "device": device,
               "seconds": round(time.monotonic() - started, 2)}
    pending = result_path + ".tmp"
    with open(pending, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False)
    os.replace(pending, result_path)
    emit("progress", ratio=1.0, stage="识别完成")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

"""Audited, exact-version Qwen-only source adaptation (no package upgrades)."""
from __future__ import annotations

import hashlib
from pathlib import Path

TARGET = "src/mflux/models/qwen21/variants/edit/qwen_image_21_edit.py"
ORIGINAL_SHA256 = "e58e69375c98560e0b8291121b87f2286ca0497d46a049f119ef13215981dbb5"
TEXT_TARGET = "src/mflux/models/qwen21/reference/model/qwen_image21_text_encoder/text_encoder.py"
TEXT_ORIGINAL_SHA256 = "62e3eb25d15d5f14adf5042f9b84cdee5e247e1af0a7b607c071aa4e8a04f000"
TARGETS = (TEXT_TARGET, TARGET)


def adapted_source(original):
    if hashlib.sha256(original).hexdigest() != ORIGINAL_SHA256:
        raise RuntimeError("Qwen 固定版本源文件校验失败，保留现场")
    text = original.decode("utf-8")
    replacements = (
        ("import json\n", "import json\nfrom backend.qwen21.profiles import edit_noise_seed\n"),
        ("        use_kv_cache: bool = True,\n", "        use_kv_cache: bool = True,\n"
         "        scheduler: str = \"linear\",\n"
         "        reference_resolution: int = 1024,\n"
         "        independent_edit_noise: bool = False,\n"),
        ("        QwenImage21LatentCreator.validate_resolution(output_resolution)\n",
         "        QwenImage21LatentCreator.validate_resolution(output_resolution)\n"
         "        QwenImage21LatentCreator.validate_resolution(reference_resolution)\n"),
        ("            guidance=guidance,\n", "            guidance=guidance,\n            scheduler=scheduler,\n"),
        ("QwenImage21LatentCreator.dimensions(output_resolution, image.width / image.height)",
         "QwenImage21LatentCreator.dimensions(reference_resolution, image.width / image.height)"),
        ("        mx.random.seed(seed)\n",
         "        mx.random.seed(edit_noise_seed(seed, images) if independent_edit_noise else seed)\n"),
        ("generation_parameters={\"use_kv_cache\": use_kv_cache, \"output_resolution\": output_resolution}",
         "generation_parameters={\"use_kv_cache\": use_kv_cache, \"output_resolution\": output_resolution, "
         "\"reference_resolution\": reference_resolution, \"scheduler\": scheduler, "
         "\"independent_edit_noise\": independent_edit_noise}"),
    )
    for before, after in replacements:
        if text.count(before) != 1:
            raise RuntimeError("Qwen 源码适配锚点不匹配，保留现场")
        text = text.replace(before, after, 1)
    return text.encode("utf-8")


def expected_files():
    # The original copy allows a deterministic patched hash without trusting a
    # receipt that might have been written by an interrupted preparation.
    original = Path(__file__).with_name("vendor") / "qwen_image_21_edit.py.original"
    text_original = original.with_name("text_encoder.py.original").read_bytes()
    if hashlib.sha256(text_original).hexdigest() != TEXT_ORIGINAL_SHA256:
        raise RuntimeError("Qwen 文本配置适配源文件校验失败")
    text = text_original.decode()
    anchor = "        self.embed_tokens = nn.Embedding(config[\"vocab_size\"], config[\"hidden_size\"])"
    if text.count(anchor) != 1:
        raise RuntimeError("Qwen 文本配置适配锚点不匹配")
    text = text.replace(anchor, "        config = dict(config)\n"
                        "        rope = config.get(\"rope_scaling\") or config.get(\"rope_parameters\") or {}\n"
                        "        config[\"rope_scaling\"] = rope\n"
                        "        config[\"rope_theta\"] = config.get(\"rope_theta\", rope.get(\"rope_theta\"))\n" + anchor)
    return {TARGET: (original.read_bytes(), adapted_source(original.read_bytes())),
            TEXT_TARGET: (text_original, text.encode())}


def recognized(source):
    try:
        return all((Path(source) / name).read_bytes() in pair for name, pair in expected_files().items())
    except OSError:
        return False


def apply(source):
    if not recognized(source):
        raise RuntimeError("Qwen 源码有非预期修改，已保留现场")
    digest = hashlib.sha256()
    for name, (_, expected) in sorted(expected_files().items()):
        target = Path(source) / name
        if target.read_bytes() != expected:
            pending = target.with_suffix(".py.tmp")
            pending.write_bytes(expected)
            pending.replace(target)
        digest.update(expected)
    return digest.hexdigest()


def ready(source):
    try:
        return all((Path(source) / name).read_bytes() == patched
                   for name, (_, patched) in expected_files().items())
    except (OSError, ValueError, RuntimeError):
        return False

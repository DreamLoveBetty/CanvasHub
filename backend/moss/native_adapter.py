"""Readers for MFlux BF16 checkpoints in the upstream moss-image-mlx sampler; no sampling logic lives here.

The transformer already uses upstream names and its time MLP goes through upstream's own sanitizer. MFlux text
tensors only lost `language_model.`; upstream's sanitizer restores offset norms and the Conv1d layout. MFlux VAE
convolutions are already OHWI, so the decoder must not transpose them again.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

BRIDGE_VERSION = "moss-native-bridge-v1"
PARTS = ("transformer", "text_encoder", "vae")


def text_source_key(key):
    if key in ("embed_tokens.weight", "norm.weight") or key.startswith("layers."):
        return "language_model." + key
    raise ValueError(f"未知的 MOSS 文本编码器张量：{key}")


def vae_target_key(key):
    if key in ("bn.running_mean", "bn.running_var"):
        return key.removeprefix("bn.")
    if key.startswith("decoder.mid_block.attentions.0.to_out."):
        return key.replace(".to_out.", ".to_out.0.", 1)
    if key.startswith(("decoder.", "post_quant_conv.")):
        return key
    if key.startswith(("encoder.", "quant_conv.")) or key == "bn.num_batches_tracked":
        return None
    raise ValueError(f"未知的 MOSS VAE 张量：{key}")


def create_view(source, configs, target, files, links=None):
    """Build a config-and-symlink view outside the source; `links` overrides where a bound file really lives."""
    source, configs, target = (Path(path).resolve() for path in (source, configs, target))
    if source == target or source in target.parents:
        raise ValueError("模型视图必须位于源权重目录之外")
    for part in PARTS:
        (target / part).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(configs / part / "config.json", target / part / "config.json")
    (target / "tokenizer").mkdir(parents=True, exist_ok=True)
    for name in files:
        if name.endswith(".safetensors") or name.startswith("tokenizer/"):
            (target / name).symlink_to((links or {}).get(name, source / name))
    return target


def make_pipeline(view, cache_dir, loras):
    """Upstream pipeline with only the two native-format readers replaced; both load strictly."""
    import mlx.core as mx
    from mlx_lm.models.qwen3_5 import Qwen3_5TextModel, TextModelArgs
    from moss_image_mlx.pipeline import MOSSImagePipeline
    from moss_image_mlx.text_encoder import TextEncoder, _use_reference_layers, sanitize
    from moss_image_mlx.vae import VAEDecoder
    from transformers import AutoTokenizer

    def read_shards(path):
        tensors = {}
        for file in sorted(Path(path).glob("*.safetensors")):
            shard = mx.load(str(file))
            if tensors.keys() & shard.keys():
                raise ValueError(f"MOSS 分片包含重复张量：{file.name}")
            tensors.update(shard)
        return tensors

    class NativeTextEncoder(TextEncoder):
        def __init__(self, path, tokenizer):
            config = json.loads((Path(path) / "config.json").read_text())
            args = TextModelArgs.from_dict(config["text_config"])
            self.model = Qwen3_5TextModel(args)
            _use_reference_layers(self.model, args)
            weights = sanitize({text_source_key(key): value for key, value in read_shards(path).items()})
            self.model.load_weights(list(weights.items()), strict=True)
            self.model.eval()
            self.tokenizer = AutoTokenizer.from_pretrained(str(tokenizer), local_files_only=True)

    class NativePipeline(MOSSImagePipeline):
        def _load_text_encoder(self):
            if self.text_encoder is None:
                self.text_encoder = NativeTextEncoder(self.model_dir / "text_encoder", self.model_dir / "tokenizer")

        def _load_vae(self):
            if self.vae is None:
                path = self.model_dir / "vae"
                model = VAEDecoder(json.loads((path / "config.json").read_text()))
                weights = {}
                for key, value in read_shards(path).items():
                    target = vae_target_key(key)
                    if target is not None:
                        weights[target] = value.astype(mx.float32)
                model.load_weights(list(weights.items()), strict=True)
                mx.eval(model.parameters())
                self.vae = model

    return NativePipeline(view, low_memory=True, cache_dir=cache_dir, loras=loras)

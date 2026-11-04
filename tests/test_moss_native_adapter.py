import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from backend.moss import native_adapter as adapter


class KeyBridge(unittest.TestCase):
    def test_text_keys_restore_only_the_reference_namespace(self):
        for key in ("embed_tokens.weight", "norm.weight", "layers.0.linear_attn.conv1d.weight"):
            self.assertEqual(adapter.text_source_key(key), "language_model." + key)

    def test_unknown_text_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            adapter.text_source_key("vision_model.unexpected.weight")

    def test_vae_decoder_layout_is_already_mlx_and_not_transposed_again(self):
        for key in ("decoder.conv_in.weight", "post_quant_conv.weight"):
            self.assertEqual(adapter.vae_target_key(key), key)

    def test_batch_norm_names_match_the_reference_decoder(self):
        self.assertEqual(adapter.vae_target_key("bn.running_mean"), "running_mean")
        self.assertEqual(adapter.vae_target_key("bn.running_var"), "running_var")

    def test_vae_attention_projection_restores_the_reference_list_index(self):
        for param in ("weight", "bias"):
            self.assertEqual(adapter.vae_target_key(f"decoder.mid_block.attentions.0.to_out.{param}"),
                             f"decoder.mid_block.attentions.0.to_out.0.{param}")

    def test_vae_encoder_is_not_loaded_for_text_to_image(self):
        for key in ("encoder.conv_in.weight", "quant_conv.weight", "bn.num_batches_tracked"):
            self.assertIsNone(adapter.vae_target_key(key))

    def test_unknown_vae_key_is_rejected(self):
        with self.assertRaises(ValueError):
            adapter.vae_target_key("unknown.weight")


class View(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.source, self.configs = self.root / "source", self.root / "configs"
        for part in adapter.PARTS:
            (self.source / part).mkdir(parents=True)
            (self.source / part / "0.safetensors").write_bytes(b"x")
            (self.source / part / "model.safetensors.index.json").write_text("{}")
            (self.configs / part).mkdir(parents=True)
            (self.configs / part / "config.json").write_text("{}")
        (self.source / "tokenizer").mkdir()
        (self.source / "tokenizer/tokenizer.json").write_text("{}")
        (self.source / "tokenizer/unlisted.json").write_text("{}")
        self.files = [f"{part}/0.safetensors" for part in adapter.PARTS] + ["tokenizer/tokenizer.json"]

    def test_links_only_listed_files_and_copies_configs(self):
        view = adapter.create_view(self.source, self.configs, self.root / "view", self.files)
        self.assertTrue((view / "vae/0.safetensors").is_symlink())
        self.assertFalse((view / "vae/config.json").is_symlink())
        self.assertFalse((view / "tokenizer/unlisted.json").exists())

    def test_view_inside_source_is_rejected(self):
        with self.assertRaises(ValueError):
            adapter.create_view(self.source, self.configs, self.source / "view", self.files)


class Recorder:
    def __init__(self, *_args, **_kwargs):
        self.calls = []

    def load_weights(self, items, strict=False):
        Recorder.loaded.append((dict(items), strict))

    def eval(self):
        return self

    def parameters(self):
        return {}


class Value:
    def __init__(self, name):
        self.name = name

    def astype(self, dtype):
        return (self.name, dtype)


class FakePipeline:
    def __init__(self, view, low_memory, cache_dir, loras):
        self.model_dir, self.low_memory, self.cache_dir, self.loras = Path(view), low_memory, cache_dir, loras
        self.text_encoder = self.vae = None


class StrictLoading(unittest.TestCase):
    """Upstream packages are faked: the bridge must stay strict without needing MLX here."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.view = Path(temp.name)
        for part in ("text_encoder", "vae"):
            (self.view / part).mkdir()
            (self.view / part / "config.json").write_text(json.dumps({"text_config": {}}))
            (self.view / part / "0.safetensors").write_bytes(b"")
        Recorder.loaded = []
        self.shards = {"text_encoder": {"norm.weight": Value("norm")},
                       "vae": {"decoder.conv_in.weight": Value("conv"), "encoder.conv_in.weight": Value("skip")}}
        core = types.SimpleNamespace(load=lambda path: self.shards[Path(path).parent.name],
                                     float32="float32", eval=lambda *_: None)
        modules = {"mlx": types.ModuleType("mlx"), "mlx.core": core,
                   "mlx_lm": types.ModuleType("mlx_lm"), "mlx_lm.models": types.ModuleType("mlx_lm.models"),
                   "mlx_lm.models.qwen3_5": types.SimpleNamespace(
                       Qwen3_5TextModel=Recorder, TextModelArgs=types.SimpleNamespace(from_dict=lambda value: value)),
                   "moss_image_mlx": types.ModuleType("moss_image_mlx"),
                   "moss_image_mlx.pipeline": types.SimpleNamespace(MOSSImagePipeline=FakePipeline),
                   "moss_image_mlx.text_encoder": types.SimpleNamespace(
                       TextEncoder=object, _use_reference_layers=lambda *_: None, sanitize=lambda value: value),
                   "moss_image_mlx.vae": types.SimpleNamespace(VAEDecoder=Recorder),
                   "transformers": types.SimpleNamespace(AutoTokenizer=types.SimpleNamespace(
                       from_pretrained=lambda *_a, **_k: "tokenizer"))}
        modules["mlx"].core = core
        patcher = patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_both_readers_load_strictly_with_bridged_names(self):
        pipeline = adapter.make_pipeline(self.view, "cache", [("lora", 1)])
        self.assertTrue(pipeline.low_memory)
        pipeline._load_text_encoder()
        pipeline._load_vae()
        (text, text_strict), (vae, vae_strict) = Recorder.loaded
        self.assertEqual(list(text), ["language_model.norm.weight"])
        self.assertEqual(vae, {"decoder.conv_in.weight": ("conv", "float32")})
        self.assertTrue(text_strict and vae_strict)


if __name__ == "__main__":
    unittest.main()

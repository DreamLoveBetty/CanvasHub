"""MOSS ordinary LoRA library on the shared direct-folder scanner."""
from __future__ import annotations

from pathlib import Path

from ..local_image.lora_store import LoRAStore as _LoRAStore
from . import lora_adapter
from .assets import managed_sha256


class LoRAStore(_LoRAStore):
    def __init__(self, root, *, cache_dir=None, managed=None):
        super().__init__(root, label="MOSS LoRA", allow_peft_default=True)
        self.cache_dir = Path(cache_dir) if cache_dir else self.root / "cache" / "lora"
        self.managed = managed_sha256() if managed is None else frozenset(managed)

    def _inspect(self, path):
        super()._inspect(path)
        result = lora_adapter.inspect(path)
        if self._digest(path) in self.managed:
            raise ValueError("受管适配器不能作为普通 LoRA 导入")
        return result

    def delete(self, asset_id):
        result = super().delete(asset_id)
        lora_adapter.evict(result["asset_id"], self.cache_dir)
        return result

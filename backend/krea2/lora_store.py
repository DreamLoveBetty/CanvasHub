"""Krea-specific policy over the shared content-addressed LoRA library."""
from ..local_image.lora_store import LoRAStore as _LoRAStore
from .lokr import inspect_lokr

class LoRAStore(_LoRAStore):
    def __init__(self, root):
        super().__init__(root, label="Krea 2 LoRA")

    def _inspect(self, path):
        report = inspect_lokr(path)
        if report is not None:
            return {key: report[key] for key in ("adapter_format", "tensor_count", "adapter_count")}
        return super()._inspect(path)

    @staticmethod
    def _public(item):
        result = _LoRAStore._public(item)
        if item.get("adapter_format"):
            result["adapter_format"] = item["adapter_format"]
        return result

"""Krea-specific policy over the shared content-addressed LoRA library."""
from ..local_image.lora_store import LoRAStore as _LoRAStore

class LoRAStore(_LoRAStore):
    def __init__(self, root):
        super().__init__(root, label="Krea 2 LoRA")

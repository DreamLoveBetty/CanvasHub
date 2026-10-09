"""Compatibility exports for the original Spandrel upscale service.

Model-independent image lifecycle is shared; Topaz has its own request/engine.
"""
from .image_enhancement import (
    _coerce_upscale_tile, _write_upscale_sidecar,
    process_image_enhancement_task as process_upscale_task,
)

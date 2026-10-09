"""Compatibility exports for the architecture-neutral scaled-FP8 decoder."""
try:
    from ..local_image.comfy_fp8 import *
except ImportError:  # Direct frozen/converter child execution.
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from backend.local_image.comfy_fp8 import *

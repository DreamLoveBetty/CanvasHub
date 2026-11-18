"""Project-side compatibility for moss-image-mlx LoRALinear.

moss-image-mlx 0.2.0 wraps adapted linears without exposing `.weight`.
The DiT still reads `time_embedding[0].weight.dtype` and
`text_embedder.proj.weight.dtype` during the first forward pass.

This installs a property that forwards to `base.weight` so the wrapper
stays compatible without registering a second parameter array. It is
idempotent and will not replace a weight already defined on the class.
"""


def ensure_loralinear_weight(cls=None):
    """Return True if the forwarding property was installed on this call."""
    if cls is None:
        from moss_image_mlx.lora import LoRALinear as cls
    if "weight" in cls.__dict__:
        return False

    def weight(self):
        return self.base.weight

    cls.weight = property(weight)
    return True

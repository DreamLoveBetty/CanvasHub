"""Krea 2 authenticated route binding; no business logic."""
from .local_image_routes import create_router as _create
from ..krea2.contracts import MAX_IMAGE_UPLOAD, MAX_LORA_UPLOAD

def create_router(service):
    return _create(service, domain="krea2", label="Krea 2",
                   max_image_upload=MAX_IMAGE_UPLOAD, max_lora_upload=MAX_LORA_UPLOAD)

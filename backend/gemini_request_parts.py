"""Native Gemini request parts shared by every route that sends inlineData images."""
from __future__ import annotations


def reference_label(index: int) -> dict:
    # Matches the 图片N numbering of image-group roles and @图片N mentions in the prompt.
    return {'text': f'图片{index}：'}


def labeled_reference_parts(image_parts) -> list[dict]:
    """Put a 图片N label before each image so prompt mentions map to a specific image."""
    parts = []
    for index, part in enumerate(image_parts, start=1):
        parts.extend((reference_label(index), part))
    return parts

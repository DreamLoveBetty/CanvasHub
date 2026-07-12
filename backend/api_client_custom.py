#!/usr/bin/env python3
"""
Custom Model API Client (OpenAI-compatible)

Endpoint: http://localhost:8080/v1
API Key: pwd
Model: GPT-5.4
"""

import json
import os
import random
import time
import urllib.request
import urllib.error
from pathlib import Path
from .app_config import APP_DATA_DIR
from .storage_paths import daily_output_dir, write_obsidian_prompt_sidecar

# Config
API_BASE_URL = os.environ.get("CUSTOM_API_URL", "http://localhost:8080/v1")
API_KEY = os.environ.get("CUSTOM_API_KEY", "pwd")
MODEL_NAME = os.environ.get("CUSTOM_MODEL_NAME", "GPT-5.4")
TIMEOUT_SECONDS = int(os.environ.get("CUSTOM_TIMEOUT", "120"))

CUSTOM_OUTPUT_DIR = APP_DATA_DIR / "custom_outputs"


def _normalize_ratio(ratio: str) -> str:
    return str(ratio or "1:1").strip()


def _resolve_custom_size(ratio: str, resolution: str) -> str:
    """把 ratio + resolution 转成 API 的 size 参数。"""
    ratio_key = _normalize_ratio(ratio)
    resolution_key = str(resolution or "4k").strip().lower()

    base_long_side_map = {
        "1k": 1024,
        "2k": 2048,
        "4k": 3840,
    }
    base_long_side = base_long_side_map.get(resolution_key, 3840)

    ratio_map = {
        "1:1": (1, 1),
        "16:9": (16, 9),
        "9:16": (9, 16),
        "4:3": (4, 3),
        "3:4": (3, 4),
    }
    w_ratio, h_ratio = ratio_map.get(ratio_key, ratio_map["1:1"])

    if w_ratio >= h_ratio:
        width = base_long_side
        height = round(base_long_side * h_ratio / w_ratio)
    else:
        height = base_long_side
        width = round(base_long_side * w_ratio / h_ratio)

    return f"{width}x{height}"


def generate_image_custom(prompt: str, ratio: str = "1:1", resolution: str = "4k", quality: str = "medium") -> dict:
    """
    Generate image using custom OpenAI-compatible API.
    
    Args:
        prompt: Image generation prompt
        ratio: Aspect ratio (1:1, 16:9, 9:16, 4:3, 3:4)
        resolution: Resolution preset (4k, 2k, 1k)
        quality: Quality preset (low, medium, high)
    
    Returns:
        dict: {
            "success": bool,
            "image_path": str (absolute path),
            "prompt_file": str,
            "error": str (if failed)
        }
    """
    result = {
        "success": False,
        "image_path": None,
        "prompt_file": None,
        "error": None
    }

    try:
        quality_key = str(quality or "medium").strip().lower()
        if quality_key not in ("low", "medium", "high", "auto"):
            quality_key = "medium"

        print(f"🎨 Custom API 生成任务开始：model={MODEL_NAME}, ratio={ratio}, resolution={resolution}, quality={quality_key}")
        
        # resolution 决定 size，quality 由用户选择
        size = _resolve_custom_size(ratio, resolution)
        
        # Build API request
        request_data = {
            "model": MODEL_NAME,
            "prompt": prompt,
            "size": size,
            "quality": quality_key,
            "background": "auto",
            "n": 1,
            "response_format": "url",
            "output_format": "png",
        }
        
        # Create request
        url = f"{API_BASE_URL}/images/generations"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}"
        }
        
        print(f"  · API endpoint: {url}")
        print(f"  · request size: {size}, quality: {quality_key}")
        
        req = urllib.request.Request(
            url,
            data=json.dumps(request_data).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        
        # Send request
        start_time = time.time()
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
        elapsed = time.time() - start_time
        print(f"  · API response received in {elapsed:.2f}s")
        
        # Extract image URL
        if "data" not in resp_data or len(resp_data["data"]) == 0:
            raise RuntimeError(f"API returned no image data: {resp_data}")
        
        image_url = resp_data["data"][0].get("url")
        if not image_url:
            raise RuntimeError(f"No image URL in response: {resp_data}")
        
        print(f"  · image URL: {image_url}")
        
        # Create output directories
        output_dir = daily_output_dir()
        CUSTOM_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Download image
        ts = int(time.time())
        filename = f"custom_{ts}_{random.randint(1000, 9999)}.png"
        image_path = CUSTOM_OUTPUT_DIR / filename
        final_path = output_dir / filename
        
        print("  · downloading image...")
        urllib.request.urlretrieve(image_url, image_path)
        
        # Copy to downloads folder
        import shutil
        shutil.copy2(image_path, final_path)
        
        # Save prompt file
        prompt_file = output_dir / filename.replace(".png", ".txt")
        prompt_content = (
            f"Model: {MODEL_NAME}\n"
            f"Ratio: {ratio}\n"
            f"Resolution: {resolution}\n"
            f"Prompt: {prompt}\n"
        )
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt_content)
        write_obsidian_prompt_sidecar(final_path, prompt_content, txt_path=prompt_file)
        
        result["success"] = True
        result["image_path"] = str(final_path)
        result["prompt_file"] = str(prompt_file)
        
        print(f"✅ Custom API 生成完成：{final_path}")
        
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        result["error"] = f"HTTP {e.code}: {error_body[:500]}"
        print(f"❌ HTTP Error: {result['error']}")
        
    except urllib.error.URLError as e:
        result["error"] = f"Connection failed: {e.reason}"
        print(f"❌ Connection Error: {result['error']}")
        
    except Exception as e:
        result["error"] = str(e)
        print(f"❌ Generation failed: {result['error']}")
    
    return result


def edit_image_custom(image_path: str, prompt: str, ratio: str = "1:1") -> dict:
    """
    Edit image using custom API (if supported).
    
    Args:
        image_path: Path to source image
        prompt: Edit instruction
        ratio: Aspect ratio
    
    Returns:
        dict: Same structure as generate_image_custom
    """
    result = {
        "success": False,
        "image_path": None,
        "prompt_file": None,
        "error": None
    }
    
    try:
        print(f"🎨 Custom API 编辑任务开始：{image_path}")
        
        # Check if API supports image editing
        # This is a placeholder - adjust based on actual API capabilities
        request_data = {
            "model": MODEL_NAME,
            "prompt": prompt,
            "image": image_path,
            "mode": "edit"
        }
        
        url = f"{API_BASE_URL}/images/edits"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}"
        }
        
        req = urllib.request.Request(
            url,
            data=json.dumps(request_data).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
        
        # Process response (similar to generate)
        if "data" not in resp_data or len(resp_data["data"]) == 0:
            raise RuntimeError(f"API returned no image data: {resp_data}")
        
        image_url = resp_data["data"][0].get("url")
        if not image_url:
            raise RuntimeError(f"No image URL in response: {resp_data}")
        
        # Download and save (same as generate)
        output_dir = daily_output_dir()
        CUSTOM_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        ts = int(time.time())
        filename = f"custom_edit_{ts}_{random.randint(1000, 9999)}.png"
        image_path_new = CUSTOM_OUTPUT_DIR / filename
        final_path = output_dir / filename
        
        urllib.request.urlretrieve(image_url, image_path_new)
        
        import shutil
        shutil.copy2(image_path_new, final_path)
        
        prompt_file = output_dir / filename.replace(".png", ".txt")
        prompt_content = (
            f"Model: {MODEL_NAME}\n"
            f"Edit Prompt: {prompt}\n"
            f"Source: {image_path}\n"
        )
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt_content)
        write_obsidian_prompt_sidecar(final_path, prompt_content, txt_path=prompt_file)
        
        result["success"] = True
        result["image_path"] = str(final_path)
        result["prompt_file"] = str(prompt_file)
        
        print(f"✅ Custom API 编辑完成：{final_path}")
        
    except Exception as e:
        result["error"] = str(e)
        print(f"❌ Edit failed: {result['error']}")
    
    return result


if __name__ == "__main__":
    # Test
    test_prompt = "A cute cat sitting on a windowsill, sunset lighting, photorealistic"
    result = generate_image_custom(test_prompt, ratio="1:1", resolution="2k")
    print(json.dumps(result, indent=2, ensure_ascii=False))

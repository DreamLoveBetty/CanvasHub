# Local Upscale Models

Put Spandrel-compatible 4x ESRGAN `.pth` weights here:

- `4x-UltraSharp.pth`
- `4x-AnimeSharp.pth`

The desktop upscale node loads these files lazily when `/api/upscale/run` is called.
Set `UPSCALE_MODEL_DIR=/path/to/models` to use another directory.

Current local files:

- `4x-UltraSharp.pth`
  - source: `https://huggingface.co/lokCX/4x-Ultrasharp/resolve/main/4x-UltraSharp.pth?download=true`
  - sha256: `a5812231fc936b42af08a5edba784195495d303d5b3248c24489ef0c4021fe01`
- `4x-AnimeSharp.pth`
  - source: `https://huggingface.co/utnah/esrgan/resolve/main/4x-AnimeSharp.pth?download=true`
  - sha256: `e7a7de2dafd7331c1992862bbbcd9e9712a9f9f8e6303f0aaa59b4341d359bab`

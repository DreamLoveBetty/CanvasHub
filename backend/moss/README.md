# MOSS 域

MOSS-Image 的本地生成域。主 HTTP 進程不載入 MLX，推理只在隔離 venv 的 worker 內執行（T04）。

## 模組邊界

| 檔案 | 職責 | 依賴 |
|---|---|---|
| `contracts.py` | 請求校驗、預設、上限；無檔案/模型 import | 標準庫 |
| `layout.py` | Layout/分鏡編譯與幾何 | contracts |
| `assets.py`、`assets.lock.json` | 固定資產清單（來源、revision、hash、授權） | 標準庫 |
| `lora_adapter.py` | LoRA 鍵名規範化、qkv 拆分、快取；只搬位元組 | contracts、local_image |
| `lora_store.py` | 普通 LoRA 庫；排除受管適配器 | lora_adapter、assets |
| `native_adapter.py` | MFlux BF16 格式橋接、模型視圖；MLX 只在 `make_pipeline` 內 import | 標準庫 |
| `model_store.py` | 只讀綁定、白名單指紋、失效判定 | native_adapter、lora_adapter、assets |
| `environment.py` | 顯式準備、狀態、CLI | model_store、assets |
| `runtime.py` | 監督 worker、token 預算、狀態；主進程端，不載 MLX | local_image、environment |
| `worker.py` | 隔離 venv 內的任務流程；MLX 只在 `MlxBackend` | lora_adapter、native_adapter、prompt_cache、tokenizer_probe |
| `tokenizer_probe.py` | `-I` 單次子進程算 token，不依賴 backend | transformers |
| `prompt_cache.py` | 上游提示詞快取的 2 GiB 淘汰 | 標準庫 |
| `service.py` | 編譯、准入、任務與發布協調；無 HTTP、無 MLX | 本域各模組、local_image |
| `artifacts.py` | 歸檔原圖、切圖、描線圖、Telegram 交付 | local_image.archiving、Pillow |

## 狀態位置

- `APP_DATA_DIR/components/moss/`：`venv/`、`assets/`（config、destripe、缺失時的 student）、`installed.json`。
- `APP_DATA_DIR/data/moss/`：`base-imports/`、`bases/<id>/`（社區 Base 權重）、`models/<id>/`（binding、視圖）、`loras/`、`cache/lora/`、`cache/prompt-embeds/<指紋前16位>/`。
- 來源權重只讀；視圖是配置副本加符號連結，LoRA 快取可隨時重建。

## 準備與恢復

準備只由使用者顯式觸發，生成流程不聯網：

```bash
PYTHONPATH="$PWD" .venv/bin/python -m backend.moss.environment prepare --source <權重目錄>
PYTHONPATH="$PWD" .venv/bin/python -m backend.moss.environment bind <權重目錄>
PYTHONPATH="$PWD" .venv/bin/python -m backend.moss.environment status
```

- `prepare` 需要 uv 與共享 Python；打包版從 Qwen/Krea 收據取解釋器。收據最後寫入，中斷後重跑即可。
- 社區 Base 走設定中心「MOSS 模型轉換」：放進 `data/moss/base-imports/`，支援 ComfyUI INT8 ConvRot、BF16 單檔與已轉換的 MLX 目錄。`base_converter.py` 在隔離 venv 的子進程執行，只用 NumPy；驗證後發布到 `data/moss/bases/<id>/` 並綁定。必須先綁官方權重，張量名稱、形狀、精度要與官方一致（`time_embedding.1/.2` 視為同名）。文字編碼器、tokenizer、VAE、Turbo student、destripe 沿用官方，並有自己的指紋與提示詞快取；官方或微調任一邊的檔案變化都會使它失效。
- 白名單檔案變化會使綁定失效，重新 `bind` 即恢復；完整校驗會計算約 27 GB 權重的 SHA256。
- 依賴鎖更新：以驗證過的版本為約束，執行 `MACOSX_DEPLOYMENT_TARGET=14.0 uv pip compile --generate-hashes --no-config --python-version 3.14 --python-platform aarch64-apple-darwin`，不得加入 mflux。

## LoRA 驗證分層

「可載入」只代表格式與形狀通過。`tests/local/moss_lora_real_local.py` 驗收 12 個第三方檔案的轉換；實際效果另行出圖判定。

## 驗收與故障恢復

- 穩定回歸：`tests/test_moss_*.py`、`tests/test_moss_*.cjs`，只用假 runtime，不需要模型。跨域保證在 `tests/test_moss_integration.py`。
- 本機真實驗收：`PYTHONPATH="$PWD" .venv/bin/python tests/local/moss_acceptance_local.py [案例前綴 ...]`。它開一個獨立端口和資料目錄的臨時實例，不碰運行中的服務和 Telegram，結果在 `tests/output/moss-acceptance-<日期>/`，切圖會逐像素對照整圖。

| 現象 | 處理 |
|---|---|
| 綁定失效 | 權重白名單檔案有變化，重新 `bind` |
| 環境未就緒 | 重跑 `prepare`；收據最後才寫入，中斷不會留下假就緒 |
| 服務重啟時有任務在跑 | 任務標記失敗，不自動重跑，需要手動再提交 |
| 切圖失敗 | 任務仍成功，整圖保留並記錄 warning，不重新採樣 |
| Telegram 失敗 | 檔案保留，狀態 `telegram_failed`，不重新採樣 |
| 非 Apple Silicon Mac | 環境永遠未就緒，節點提示前往模型工具 |

資料都在 `APP_DATA_DIR`，不寫進 release 或 app 目錄。第三方依賴的來源與授權見 `assets.lock.json`；分鏡提示詞格式參考 ZenHG ComfyUI-MOSS-Storyboard（MIT）與官方 `compile_prompt.py`（Apache-2.0）。

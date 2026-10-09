"""Explicit, offline imports of *separate* Topaz Video runtime stages.

The GUI process is never started by the task runtime. Import is an operator
action: it copies only selected local files into persistent app data. Initial
installation refuses to overwrite a stage; ``sync-conventional`` may add or
refresh declared model bundles in an existing, idle stage. No model download
is attempted. Credentials and ``license.lic`` are never imported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import uuid

from .features import FEATURE_MODELS


PRECISE_ENGINE_SHA256 = "d8c09cce3af24e4e767fb29b0fed72d6a1c60b1796e97e5c76f7139876185a91"
MANIFEST = "topaz-video-stage.json"
VALIDATION = "local-validation.json"
COMMON_CONVENTIONAL = (
    "tvai.tz", "prap-3.json", "prap-v3-fp16-ml.tz3",
    "nap-3.json", "nap-v3-fp16-ml.tz3",
)
# Downloaded support networks that are not exposed as standalone enhancement
# choices.  They are staged because installed model descriptors may use them
# for analysis, but they never become public catalog entries on their own.
CONVENTIONAL_AUXILIARY_FILES = (
    "cpe-1.json", "cpe-2.json",
    "cpe-v1-fp16-384x672-ml.tz3", "cpe-v2-fp16-384x672-ml.tz3",
)
NEURO_MODEL_PACKAGES = {"hyp-2": 43}
MODEL_FILES = {
    "artemis": (
        "ahq-12.json", "ahq-v12-fnet-fp16-448x576-2x-ml.tz3",
        "ahq-v12-gnet-fp16-448x576-2x-ml.tz3", "tvai.tz",
    ),
    "gaia": (
        "ghq-5.json", "ghq-v5-gaia-fp16-448x576-2x-ml.tz3", "tvai.tz",
    ),
    "gaia-animation": (
        "ganim-1.json", "ganim-v1-fp16-448x576-2x-OS15-mlp.tz3", "tvai.tz",
    ),
    "iris": (
        "iris-2.json", "iris-v2-fgnet-fp16-576x480-1x-13-mlp.tz3",
        "prap-3.json", "prap-v3-fp16-ml.tz3", "tvai.tz",
    ),
    "proteus-v4": (
        "prob-4.json", "prob-v4-fgnet-fp16-448x576-1x-13-mlp.tz3",
        "prob-v4-fnet-fp16-448x576-4x-0-ml.tz3",
        "prob-v4-gnet-fp16-448x576-4x-0-ml.tz3",
        "prap-3.json", "prap-v3-fp16-ml.tz3", "tvai.tz",
    ),
    "nyx-v3": (
        "nyx-3.json", "nyx-v3-fgnet-fp16-576x672-1x-13-ane-mlp.tz3",
        "nyx-v3-fgnet-fp16-576x672-2x-13-ane-mlp.tz3",
        "nap-3.json", "nap-v3-fp16-ml.tz3", "tvai.tz",
    ),
    "theia-v4": (
        "thf-4.json", "thf-v4-fnet-fp16-448x576-ml.tz3",
        "thf-v4-gnet-fp16-448x576-1x-ml.tz3",
        "thf-v4-gnet-fp16-448x576-2x-ml.tz3",
        "prap-3.json", "prap-v3-fp16-ml.tz3", "tvai.tz",
    ),
    "rhea": (
        "rhea-1.json", "rhea-v1-fgnet-fp16-448x576-4x-13-mlp.tz3",
        "prap-3.json", "prap-v3-fp16-ml.tz3", "tvai.tz",
    ),
}

# A downloaded CoreML model family can contain more than one tile/aspect
# variant for the same public model and scale.  ``MODEL_FILES`` remains the
# minimum bundle needed to expose a model, while these narrowly scoped
# prefixes allow the provisioner to carry every locally installed variant
# into the detached runtime.  This avoids treating a portrait smoke test as
# proof that the same model can also serve a landscape source.
MODEL_VARIANT_PREFIXES = {
    "artemis": ("ahq-v12-",),
    "gaia": ("ghq-v5-",),
    "gaia-animation": ("ganim-v1-",),
    "iris": ("iris-v2-",),
    "proteus-v4": ("prob-v4-",),
    "nyx-v3": ("nyx-v3-",),
    "theia-v4": ("thf-v4-",),
    "rhea": ("rhea-v1-",),
}


class StageError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _clone(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise StageError(f"不能从外部软链接导入资源：{source}")
    if source.is_dir():
        if sys.platform == "darwin":
            subprocess.run(["cp", "-c", "-R", str(source), str(destination)], check=True)
        else:
            shutil.copytree(source, destination, symlinks=True)
    elif source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform == "darwin":
            subprocess.run(["cp", "-c", str(source), str(destination)], check=True)
        else:
            shutil.copy2(source, destination)
    else:
        raise StageError(f"本机资源不存在：{source}")


def _audit_links(root: Path) -> None:
    absolute = root.resolve(strict=True)
    for path in root.rglob("*"):
        if path.is_symlink():
            try:
                target = path.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise StageError(f"运行时包含失效软链接：{path}") from exc
            if not target.is_relative_to(absolute):
                raise StageError(f"运行时软链接指向导入目录之外：{path}")


def _check_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink() and path.stat().st_size > 0


def _manifest(stage: Path, kind: str) -> dict | None:
    try:
        value = json.loads((stage / MANIFEST).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) and value.get("schema") == 1 and value.get("kind") == kind else None
    except (OSError, ValueError):
        return None


def _conventional_files(models: Path | None = None) -> tuple[str, ...]:
    """Return the allow-listed minimum bundle plus installed tile variants.

    Discovery is deliberately limited to regular top-level ``.tz3`` files
    whose names belong to a declared model family.  Account/license files and
    unrelated downloads therefore remain outside the detached runtime.
    """
    files = {*CONVENTIONAL_AUXILIARY_FILES,
             *(name for values in MODEL_FILES.values() for name in values)}
    if models and models.is_dir():
        prefixes = tuple(prefix for values in MODEL_VARIANT_PREFIXES.values() for prefix in values)
        # Optional video filters are imported only when locally downloaded;
        # their absence must not invalidate existing enhancement stages.
        prefixes += tuple(value[1] for value in FEATURE_MODELS.values())
        files.update(key + ".json" for key in FEATURE_MODELS if _check_file(models / (key + ".json")))
        files.update(path.name for path in models.iterdir()
                     if _check_file(path) and path.name.endswith(".tz3")
                     and path.name.startswith(prefixes))
    return tuple(sorted(files))


def _cache_names(files: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(sorted({name.removesuffix(".tz3") for name in files if name.endswith(".tz3")}))


def _write_conventional_manifest(stage: Path) -> None:
    models = stage / "Resources/models"
    files = _conventional_files(models)
    sizes = {name: (models / name).stat().st_size for name in files if _check_file(models / name)}
    payload = {
        "schema": 1,
        "kind": "conventional",
        "models": sorted(key for key, names in MODEL_FILES.items()
                         if all(_check_file(models / name) for name in names)),
        "files": sorted(sizes),
        "model_file_sizes": sizes,
        "helper_file_sizes": {name: (stage / "MacOS" / name).stat().st_size
                              for name in ("oiiotool",) if _check_file(stage / "MacOS" / name)},
    }
    temporary = stage / f".{MANIFEST}.{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, stage / MANIFEST)
    finally:
        temporary.unlink(missing_ok=True)


def inspect_precise(stage: Path | str) -> dict:
    """Cheap readiness check; the import operation performs the full link audit."""
    root = Path(stage).expanduser()
    errors: list[str] = []
    if not root.is_dir() or root.is_symlink():
        errors.append("独立 Precise stage 未导入")
    manifest = _manifest(root, "precise") if not errors else None
    if not manifest:
        errors.append("Precise stage 清单缺失")
    required = (
        root / "neuroserver/neuroserver",
        root / "ffmpeg/MacOS/ffmpeg",
        root / "ffmpeg/MacOS/ffprobe",
    )
    if not errors:
        for path in required:
            if not _check_file(path) or not os.access(path, os.X_OK):
                errors.append(f"Precise 文件缺失：{path.name}")
        if (not (root / "ffmpeg/Frameworks").is_dir()
                or not (root / "resources/deps/lib").is_dir()
                or not (root / "neuroserver/lib").is_dir()
                or not (root / "neuroserver/lib-dynload").is_dir()):
            errors.append("Precise 框架依赖不完整")
        blobs = tuple((root / "models/slp26").glob("blob.*"))
        if len(blobs) < 45 or not all(_check_file(path) for path in blobs):
            errors.append("Precise 2.6 模型权重不完整")
        expected = manifest.get("model_file_sizes")
        if isinstance(expected, dict) and (set(expected) != {path.name for path in blobs}
                                          or any(path.stat().st_size != expected.get(path.name) for path in blobs)):
            errors.append("Precise 2.6 模型文件与导入清单不符")
        if not errors and _sha256(required[0]) != manifest.get("engine_sha256"):
            errors.append("Precise 推理引擎与导入清单不符")
    ready = not errors
    return {"ready": ready, "verified": ready and manifest.get("engine_sha256") == PRECISE_ENGINE_SHA256,
            "stage": str(root), "errors": errors}


def inspect_conventional(stage: Path | str) -> dict:
    root = Path(stage).expanduser()
    errors: list[str] = []
    if not root.is_dir() or root.is_symlink():
        errors.append("独立常规增强 stage 未导入")
    manifest = _manifest(root, "conventional") if not errors else None
    if not manifest:
        errors.append("常规增强 stage 清单缺失")
    models: dict[str, bool] = {}
    if not errors:
        for name in ("ffmpeg", "ffprobe"):
            path = root / "MacOS" / name
            if not _check_file(path) or not os.access(path, os.X_OK):
                errors.append(f"常规增强缺少 {name}")
        if not (root / "Frameworks").is_dir():
            errors.append("常规增强 Frameworks 缺失")
        model_root = root / "Resources/models"
        expected = manifest.get("model_file_sizes")
        expected = expected if isinstance(expected, dict) else {}
        models = {}
        for key, minimum_files in MODEL_FILES.items():
            prefixes = MODEL_VARIANT_PREFIXES.get(key, ())
            recorded_variants = tuple(name for name in expected
                                      if name.endswith(".tz3") and name.startswith(prefixes))
            required = {*minimum_files, *recorded_variants}
            models[key] = all(
                _check_file(model_root / name)
                and (name not in expected or (model_root / name).stat().st_size == expected[name])
                for name in required
            )
    return {"ready": not errors, "stage": str(root), "models": models, "errors": errors}


def local_validation(stage: Path | str) -> dict[str, list[int]]:
    """Read authorized, no-watermark evidence bound to this host and stage."""
    root = Path(stage)
    try:
        record = json.loads((root / VALIDATION).read_text(encoding="utf-8"))
        expected = _sha256(root / MANIFEST)
    except (OSError, ValueError):
        return {}
    if (not isinstance(record, dict) or record.get("schema") != 2
            or record.get("manifest_sha256") != expected
            or record.get("host") != platform.node()
            or record.get("macos") != platform.mac_ver()[0]
            or record.get("machine") != platform.machine()
            or record.get("watermark_verified") is not True
            or record.get("authorization") != "licensed_topaz_checkout"):
        return {}
    scales = record.get("scales")
    if not isinstance(scales, dict):
        return {}
    return {key: value for key, value in scales.items()
            if key in MODEL_FILES and isinstance(value, list)
            and all(isinstance(item, int) and not isinstance(item, bool) for item in value)}


def record_conventional_validation(stage: Path | str, evidence_root: Path | str) -> dict:
    """Verify authorized 4-frame exports before marking variants tested.

    This is a narrow execution/authentication check, not visual-quality
    acceptance. The evidence directory is machine-local and is not served
    through the API. Legacy smoke exports that were produced without a
    successful owned-license checkout are deliberately rejected.
    """
    root = Path(stage).expanduser().resolve(strict=True)
    evidence = Path(evidence_root).expanduser().resolve(strict=True)
    checked = inspect_conventional(root)
    if not checked["ready"] or not all(checked["models"].values()):
        raise StageError("常规增强 stage 尚未就绪")
    probe = root / "MacOS/ffprobe"
    expected = {
        "proteus-v4": ((1, "proteus_v4_1x"), (4, "proteus_v4_4x")),
        "nyx-v3": ((1, "nyx_v3_1x"), (2, "nyx_v3_2x")),
        "theia-v4": ((1, "theia_v4_1x"),),
        "iris": ((1, "iris_v2_1x"),),
    }
    source = evidence / "input_4f_256.mp4"
    if not source.is_file():
        raise StageError("缺少 4 帧短片测试输入")
    scales: dict[str, list[int]] = {}
    result_hashes: dict[str, str] = {}
    for model, cases in expected.items():
        for scale, label in cases:
            output = evidence / label / "result/enhanced.mp4"
            provenance_path = evidence / label / "result/provenance.json"
            log = evidence / label / "runtime.log"
            if (not output.is_file() or output.stat().st_size == 0
                    or not log.is_file() or not provenance_path.is_file()):
                raise StageError(f"缺少已完成测试：{label}")
            log_text = log.read_text(encoding="utf-8", errors="replace")
            lowered = log_text.lower()
            if "progress=end" not in log_text:
                raise StageError(f"测试任务未正常结束：{label}")
            if "license checkout successful owned" not in lowered:
                raise StageError(f"测试任务未通过本机授权校验：{label}")
            if any(marker in lowered for marker in (
                    "parseauth got detailsnull", "watermark will be enabled",
                    "adding watermark", "applying watermark")):
                raise StageError(f"测试任务包含水印回退标记：{label}")
            try:
                provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise StageError(f"测试任务验收记录无效：{label}") from exc
            if (not isinstance(provenance, dict)
                    or provenance.get("watermark_verified") is not True
                    or provenance.get("verification") != "licensed_topaz_checkout"):
                raise StageError(f"测试任务未通过无水印验收：{label}")
            command = [str(probe), "-v", "error", "-count_frames", "-select_streams", "v:0",
                       "-show_entries", "stream=width,height,nb_read_frames", "-of", "json", str(output)]
            observed = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
            try:
                stream = json.loads(observed.stdout)["streams"][0]
                ok = (observed.returncode == 0 and int(stream["width"]) == 256 * scale
                      and int(stream["height"]) == 256 * scale and int(stream["nb_read_frames"]) == 4)
            except (ValueError, IndexError, KeyError, TypeError):
                ok = False
            if not ok:
                raise StageError(f"测试视频尺寸或帧数错误：{label}")
            scales.setdefault(model, []).append(scale)
            result_hashes[label] = _sha256(output)
    record = {"schema": 2, "manifest_sha256": _sha256(root / MANIFEST),
              "host": platform.node(), "macos": platform.mac_ver()[0],
              "machine": platform.machine(), "source_sha256": _sha256(source),
              "scales": scales, "result_sha256": result_hashes,
              "watermark_verified": True,
              "authorization": "licensed_topaz_checkout",
              "claim": ("authorized 4-frame synthetic short-video export only; "
                        "not long-video quality acceptance")}
    temp = root / f".{VALIDATION}.{uuid.uuid4().hex}.tmp"
    try:
        temp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, root / VALIDATION)
    finally:
        temp.unlink(missing_ok=True)
    return record


def _prepare_destination(source: Path, stage: Path) -> tuple[Path, Path]:
    source = source.expanduser().resolve(strict=True)
    stage = stage.expanduser().resolve(strict=False)
    if stage.exists() or stage.is_symlink():
        raise FileExistsError(f"不覆盖既有 Topaz Video 运行时：{stage}")
    if stage.is_relative_to(source) or source.is_relative_to(stage):
        raise ValueError("运行资源来源与目标不得重叠")
    stage.parent.mkdir(parents=True, exist_ok=True)
    return source, stage


def install_precise(source: Path, stage: Path, *, ffprobe_source: Path) -> dict:
    """Import a previously isolated/tested Neuroserver tree to persistent data."""
    source, stage = _prepare_destination(Path(source), Path(stage))
    ffprobe_source = Path(ffprobe_source).expanduser().resolve(strict=True)
    if not _check_file(source / "neuroserver/neuroserver"):
        raise StageError("Precise 源缺少 neuroserver")
    if len(tuple((source / "models/slp26").glob("blob.*"))) < 45:
        raise StageError("Precise 源缺少 slp26 模型权重")
    temporary = stage.parent / f".{stage.name}-import-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        for name in ("neuroserver", "ffmpeg", "resources", "models"):
            _clone(source / name, temporary / name)
        if not (temporary / "ffmpeg/MacOS/ffprobe").exists():
            _clone(ffprobe_source, temporary / "ffmpeg/MacOS/ffprobe")
        _audit_links(temporary)
        engine_hash = _sha256(temporary / "neuroserver/neuroserver")
        blob_sizes = {path.name: path.stat().st_size for path in (temporary / "models/slp26").glob("blob.*")}
        (temporary / MANIFEST).write_text(json.dumps({"schema": 1, "kind": "precise",
            "engine_sha256": engine_hash, "model": "slp26", "model_file_sizes": blob_sizes}, indent=2) + "\n")
        check = inspect_precise(temporary)
        if not check["ready"]:
            raise StageError("Precise 导入不完整：" + "; ".join(check["errors"]))
        os.replace(temporary, stage)
        return inspect_precise(stage)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def install_conventional(source_contents: Path, stage: Path) -> dict:
    """Import selected CoreML model weights, metadata and FFmpeg, not the GUI."""
    source, stage = _prepare_destination(Path(source_contents), Path(stage))
    models = source / "Resources/models"
    all_files = _conventional_files(models)
    missing = [name for name in all_files if not _check_file(models / name)]
    if missing:
        raise StageError("常规增强源缺少模型文件：" + ", ".join(missing))
    temporary = stage.parent / f".{stage.name}-import-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        (temporary / "MacOS").mkdir()
        for name in ("ffmpeg", "ffprobe"):
            _clone(source / "MacOS" / name, temporary / "MacOS" / name)
        if _check_file(source / "MacOS/oiiotool"):
            _clone(source / "MacOS/oiiotool", temporary / "MacOS/oiiotool")
        _clone(source / "Frameworks", temporary / "Frameworks")
        destination_models = temporary / "Resources/models"
        destination_models.mkdir(parents=True)
        for name in all_files:
            _clone(models / name, destination_models / name)
        cache = destination_models / "coreMLCache"
        cache.mkdir()
        cache_names = set(_cache_names(all_files))
        for path in (models / "coreMLCache").iterdir() if (models / "coreMLCache").is_dir() else ():
            if path.is_dir() and path.name in cache_names:
                _clone(path, cache / path.name)
        _audit_links(temporary)
        _write_conventional_manifest(temporary)
        check = inspect_conventional(temporary)
        if not check["ready"] or not all(check["models"].values()):
            raise StageError("常规增强导入不完整：" + "; ".join(check["errors"]))
        os.replace(temporary, stage)
        return inspect_conventional(stage)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def sync_conventional(source_contents: Path, stage: Path) -> dict:
    """Atomically add downloaded conventional model bundles to an idle stage.

    The engine/framework tree is left untouched.  Only the allow-listed model
    descriptors, weights, matching CoreML warm caches and the optional bundled
    colour-conversion helper are copied. A local
    validation record is deliberately invalidated because its manifest hash no
    longer describes the stage; each newly exposed model still reports
    ``verified=false`` until a bounded export is accepted.
    """
    source = Path(source_contents).expanduser().resolve(strict=True)
    stage = Path(stage).expanduser().resolve(strict=True)
    if stage.is_relative_to(source) or source.is_relative_to(stage):
        raise ValueError("运行资源来源与目标不得重叠")
    checked = inspect_conventional(stage)
    if not checked["ready"]:
        raise StageError("常规增强 stage 尚未就绪：" + "; ".join(checked["errors"]))
    source_models = source / "Resources/models"
    destination_models = stage / "Resources/models"
    files = _conventional_files(source_models)
    missing = [name for name in files if not _check_file(source_models / name)]
    if missing:
        raise StageError("常规增强源缺少模型文件：" + ", ".join(missing))

    changed: list[str] = []
    temporary_paths: list[Path] = []
    try:
        helper = source / "MacOS/oiiotool"
        if _check_file(helper):
            destination = stage / "MacOS/oiiotool"
            if not _check_file(destination) or _sha256(destination) != _sha256(helper):
                temporary = destination.with_name(f".oiiotool.{uuid.uuid4().hex}.sync")
                temporary_paths.append(temporary)
                _clone(helper, temporary)
                os.replace(temporary, destination)
                changed.append("MacOS/oiiotool")
        for name in files:
            source_path = source_models / name
            destination = destination_models / name
            if (_check_file(destination)
                    and destination.stat().st_size == source_path.stat().st_size
                    and _sha256(destination) == _sha256(source_path)):
                continue
            temporary = destination_models / f".{name}.{uuid.uuid4().hex}.sync"
            temporary_paths.append(temporary)
            _clone(source_path, temporary)
            if _sha256(temporary) != _sha256(source_path):
                raise StageError(f"模型复制校验失败：{name}")
            os.replace(temporary, destination)
            changed.append(name)

        destination_cache = destination_models / "coreMLCache"
        destination_cache.mkdir(exist_ok=True)
        source_cache = source_models / "coreMLCache"
        if source_cache.is_dir():
            for name in _cache_names(files):
                source_path = source_cache / name
                destination = destination_cache / name
                if not source_path.is_dir() or destination.exists() or destination.is_symlink():
                    continue
                temporary = destination_cache / f".{name}.{uuid.uuid4().hex}.sync"
                temporary_paths.append(temporary)
                _clone(source_path, temporary)
                os.replace(temporary, destination)
                changed.append("coreMLCache/" + name)

        _audit_links(stage)
        _write_conventional_manifest(stage)
        (stage / VALIDATION).unlink(missing_ok=True)
        result = inspect_conventional(stage)
        if not result["ready"] or not all(result["models"].values()):
            raise StageError("常规增强同步不完整：" + "; ".join(result["errors"]))
        return {**result, "changed": changed}
    finally:
        for path in temporary_paths:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)


def sync_neuro_models(source_contents: Path, precise_stage: Path) -> dict:
    """Clone downloaded Neuroserver packages beside the staged Precise model.

    This operation only provisions data.  It does not claim that a package is
    supported by the current Mac engine or expose it through the task catalog.
    """
    source = Path(source_contents).expanduser().resolve(strict=True)
    stage = Path(precise_stage).expanduser().resolve(strict=True)
    if stage.is_relative_to(source) or source.is_relative_to(stage):
        raise ValueError("运行资源来源与目标不得重叠")
    checked = inspect_precise(stage)
    if not checked["ready"]:
        raise StageError("Precise stage 尚未就绪：" + "; ".join(checked["errors"]))
    source_models = source / "Resources/models"
    destination_models = stage / "models"
    changed: list[str] = []
    temporary_paths: list[Path] = []
    package_sizes: dict[str, dict[str, int]] = {}
    try:
        for model, minimum_blobs in NEURO_MODEL_PACKAGES.items():
            descriptor = source_models / f"{model}.json"
            package = source_models / "models" / model
            blobs = tuple(sorted(package.glob("blob.*"))) if package.is_dir() else ()
            if not _check_file(descriptor) or len(blobs) < minimum_blobs or not all(_check_file(path) for path in blobs):
                raise StageError(f"Neuroserver 源缺少完整 {model} 权重")

            destination_descriptor = destination_models / f"{model}.json"
            if (not _check_file(destination_descriptor)
                    or _sha256(destination_descriptor) != _sha256(descriptor)):
                temporary = destination_models / f".{model}.json.{uuid.uuid4().hex}.sync"
                temporary_paths.append(temporary)
                _clone(descriptor, temporary)
                os.replace(temporary, destination_descriptor)
                changed.append(f"models/{model}.json")

            destination_package = destination_models / model
            destination_blobs = tuple(destination_package.glob("blob.*")) if destination_package.is_dir() else ()
            source_sizes = {path.name: path.stat().st_size for path in blobs}
            destination_sizes = {path.name: path.stat().st_size for path in destination_blobs
                                 if _check_file(path)}
            if destination_sizes != source_sizes:
                temporary = destination_models / f".{model}.{uuid.uuid4().hex}.sync"
                temporary_paths.append(temporary)
                _clone(package, temporary)
                copied = tuple(temporary.glob("blob.*"))
                if ({path.name: path.stat().st_size for path in copied} != source_sizes
                        or not all(_check_file(path) for path in copied)):
                    raise StageError(f"Neuroserver 模型复制校验失败：{model}")
                backup = destination_models / f".{model}.{uuid.uuid4().hex}.old"
                if destination_package.exists():
                    os.replace(destination_package, backup)
                    temporary_paths.append(backup)
                os.replace(temporary, destination_package)
                changed.append(f"models/{model}")
            package_sizes[model] = source_sizes

        manifest_path = stage / MANIFEST
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["neuro_models"] = sorted(NEURO_MODEL_PACKAGES)
        manifest["neuro_model_file_sizes"] = package_sizes
        temporary = stage / f".{MANIFEST}.{uuid.uuid4().hex}.tmp"
        temporary_paths.append(temporary)
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, manifest_path)
        _audit_links(stage)
        result = inspect_precise(stage)
        if not result["ready"]:
            raise StageError("Neuroserver 模型同步后 stage 不完整：" + "; ".join(result["errors"]))
        return {**result, "neuro_models": sorted(package_sizes), "changed": changed}
    finally:
        for path in temporary_paths:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="离线导入 Topaz Video 独立运行资源")
    sub = parser.add_subparsers(dest="kind", required=True)
    precise = sub.add_parser("precise")
    precise.add_argument("--source", type=Path, required=True, help="已隔离验证的 Precise stage")
    precise.add_argument("--stage", type=Path, required=True)
    precise.add_argument("--ffprobe-source", type=Path, required=True)
    conventional = sub.add_parser("conventional")
    conventional.add_argument("--source", type=Path, required=True, help="本机已安装 Contents；仅用于一次性导入")
    conventional.add_argument("--stage", type=Path, required=True)
    sync = sub.add_parser("sync-conventional")
    sync.add_argument("--source", type=Path, required=True, help="本机已安装 Contents；仅复制已声明模型资源")
    sync.add_argument("--stage", type=Path, required=True, help="现有常规增强 Contents stage")
    neuro = sub.add_parser("sync-neuro")
    neuro.add_argument("--source", type=Path, required=True, help="本机已安装 Contents；复制 Neuroserver 模型包")
    neuro.add_argument("--stage", type=Path, required=True, help="现有 Precise stage")
    validate = sub.add_parser("validate-conventional")
    validate.add_argument("--stage", type=Path, required=True)
    validate.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if args.kind == "precise":
        value = install_precise(args.source, args.stage, ffprobe_source=args.ffprobe_source)
    elif args.kind == "conventional":
        value = install_conventional(args.source, args.stage)
    elif args.kind == "sync-conventional":
        value = sync_conventional(args.source, args.stage)
    elif args.kind == "sync-neuro":
        value = sync_neuro_models(args.source, args.stage)
    else:
        value = record_conventional_validation(args.stage, args.evidence)
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

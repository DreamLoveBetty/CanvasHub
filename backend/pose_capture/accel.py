"""CoreML acceleration for video recognition (install step and worker; never the HTTP process).

VitPose runs as a fixed-batch (16), constant-folded copy of GEM-X's ONNX on CoreML with the CPU+GPU
compute units: with the Neural Engine, ONNX Runtime 1.30 recompiles on every load (~20 min), while
CPU+GPU compiles once (~13.5 min, done at install) and then loads in ~4 s. YOLOX uses all units.
ONNX Runtime names its CoreML cache directory after the model path only, so each cache lives under a
key of model SHA, compute units and runtime version; changing any of them compiles afresh instead of
silently reusing a stale cache. Measurements: tests/local/pose_gem_spike/VIDEO_SPEED.md.
"""
from pathlib import Path

VITPOSE_BATCH = 16
VITPOSE_SOURCE = 'gemx/inputs/onnx/vitpose.onnx'
VITPOSE_FIXED = 'gemx/inputs/onnx/vitpose_b16.onnx'           # graph only; weights stay in vitpose.onnx.data
VITPOSE_FOLDED = 'gemx/inputs/onnx/vitpose_b16_folded.onnx'   # + vitpose_b16_folded.onnx.data
CACHE_ROOT = 'coreml-cache'
UNITS = {'vitpose': 'CPUAndGPU', 'yolox': 'ALL'}


def coreml_available():
    import onnxruntime as ort
    return 'CoreMLExecutionProvider' in ort.get_available_providers()


def runtime_version():
    import importlib.metadata
    return importlib.metadata.version('onnxruntime')


def cache_dir(component, name, model_sha, ort_version):
    return Path(component) / CACHE_ROOT / f'{name}-{model_sha[:16]}-{UNITS[name]}-ort{ort_version}'


def build_vitpose_batch(component):
    """Write the fixed-batch copy (inputs and outputs pinned to 16; GEM-X traced the output with batch 1),
    then let ONNX Runtime constant-fold the per-block Shape and RoPE Sin/Cos arithmetic (~40% faster)."""
    import onnx
    import onnxruntime as ort
    component = Path(component)
    source, fixed, folded = component / VITPOSE_SOURCE, component / VITPOSE_FIXED, component / VITPOSE_FOLDED
    model = onnx.load(str(source), load_external_data=False)
    for value in list(model.graph.input) + list(model.graph.output):
        dim = value.type.tensor_type.shape.dim[0]
        dim.ClearField('dim_param')
        dim.dim_value = VITPOSE_BATCH
    del model.graph.value_info[:]  # intermediate shapes recorded for batch 1 would contradict the new batch
    onnx.save(model, str(fixed))   # next to the source so the external weight reference stays valid
    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    pending = folded.with_name(folded.stem + '.building.onnx')
    options.optimized_model_filepath = str(pending)
    options.add_session_config_entry('session.optimized_model_external_initializers_file_name', folded.name + '.data')
    options.add_session_config_entry('session.optimized_model_external_initializers_min_size_in_bytes', '1024')
    ort.InferenceSession(str(fixed), sess_options=options, providers=['CPUExecutionProvider'])
    pending.replace(folded)
    fixed.unlink()
    return folded


def session(path, cache, units):
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.log_severity_level = 3
    cache.mkdir(parents=True, exist_ok=True)
    provider = {'ModelFormat': 'MLProgram', 'MLComputeUnits': units, 'RequireStaticInputShapes': '1',
                'ModelCacheDirectory': str(cache)}
    return ort.InferenceSession(str(path), sess_options=options,
                                providers=[('CoreMLExecutionProvider', provider), 'CPUExecutionProvider'])


def sessions(component, video):
    """(yolox, vitpose) CoreML sessions for an installed `video` receipt entry."""
    component = Path(component)
    from .contracts import YOLOX_ONNX
    yolox = session(component / YOLOX_ONNX, cache_dir(component, 'yolox', video['yolox_sha256'], video['ort']), UNITS['yolox'])
    vitpose = session(component / VITPOSE_FOLDED, cache_dir(component, 'vitpose', video['vitpose_sha256'], video['ort']),
                      UNITS['vitpose'])
    return yolox, vitpose


def ready(component, video):
    """Whether a receipt's video entry still matches the files and runtime (no imports of inference packages)."""
    if not isinstance(video, dict):
        return False
    if video.get('backend') == 'cpu':
        return True
    component = Path(component)
    try:
        ort_version = runtime_version()
    except Exception:
        return False
    if video.get('ort') != ort_version or not (component / VITPOSE_FOLDED).is_file():
        return False
    return all(any(cache_dir(component, name, video.get(f'{name}_sha256', ''), ort_version).glob('*'))
               for name in ('yolox', 'vitpose'))

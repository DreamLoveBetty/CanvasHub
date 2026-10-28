"""Resident GEM-X photo and video worker. The only CanvasHub process that imports GEM-X, torch or onnxruntime
for pose capture. JSON-lines protocol on stdin/stdout (backend/local_image/runtime.py).

usage: worker.py COMPONENT_DIR
"""
import argparse
import json
import os
from pathlib import Path
import sys
import traceback

PREFIX = 'POSE_CAPTURE_EVENT '


def emit(event, **payload):
    print(PREFIX + json.dumps({'event': event, **payload}, ensure_ascii=False), flush=True)


class Cancelled(Exception):
    pass


def load_image(path, max_side=2048):
    """RGB uint8 array, EXIF-orientation applied, longest side capped (box coordinates follow)."""
    import numpy as np
    from PIL import Image, ImageOps
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert('RGB')
        if max(image.size) > max_side:
            image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        return np.asarray(image).copy()


def add_bodies(people, options, component, builders):
    """Give each person a content-addressed mannequin of their recognised shape. A failure only costs the
    shape (the canvas falls back to the neutral body), never the recognition."""
    from backend.pose_capture.bodies import MHR_DIR, BodyBuilder, BodyStore, body_id
    store = BodyStore(options['dir'])
    builder = builders.get(options['soma_assets'])
    if builder is None:
        builder = builders[options['soma_assets']] = BodyBuilder(options['soma_assets'], component / MHR_DIR)
    for person in people:
        try:
            shape = person.get('body_shape')
            identity = person['incam']['identity_coeffs'] if shape is None else shape  # image evidence's build when there is one
            ident = body_id(identity, person['incam']['scale_params'])
            if not store.target(ident).is_file():
                store.write(ident, builder.build(identity, person['incam']['scale_params']))
            person['body_id'] = ident
        except Exception as exc:
            print(f'识别体型生成失败：{type(exc).__name__}: {exc}', file=sys.stderr, flush=True)


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from backend.local_image.parent_watch import start_parent_watch
    from backend.pose_capture.contracts import ENGINE, GEMX_COMMIT, YOLOX_ONNX
    from backend.pose_capture.scene import build_sequence, build_snapshot
    start_parent_watch()
    parser = argparse.ArgumentParser()
    parser.add_argument('component', type=Path)
    args = parser.parse_args()
    component = args.component.resolve()
    from backend.pose_capture.engine import PhotoEngine
    engine = PhotoEngine(component / 'gemx', component / YOLOX_ONNX)
    joint_names = engine.joint_names
    builders = {}  # SOMA assets dir -> BodyBuilder, loaded on first use
    videos = []    # the VideoEngine (CoreML sessions), created by the first video job
    evidences = []  # SAM 3D Body image evidence, loaded by the first video job that asks for it (or None after a failure)
    comotions = []  # CoMotion tracking, loaded by the first video job that has it (or None after a failure)

    def video_engine():
        if not videos:
            from backend.pose_capture.video import VideoEngine
            receipt = json.loads((component / 'installed.json').read_text())
            videos.append(VideoEngine(engine, component, receipt.get('video') or {'backend': 'cpu'}))
        return videos[0]

    def evidence_engine():
        if not evidences:
            try:
                from backend.pose_capture.evidence import Evidence
                evidences.append(Evidence(component))
            except Exception as exc:  # optional: recognition goes on without image evidence
                print(f'影像证据载入失败：{type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
                evidences.append(None)
        return evidences[0]

    def comotion_engine():
        if not comotions:
            try:
                from backend.pose_capture.comotion import Comotion
                comotions.append(Comotion(component, engine))
            except Exception as exc:  # optional: the detector tracks people instead
                print(f'CoMotion 载入失败：{type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
                comotions.append(None)
        return comotions[0]
    emit('ready', pid=os.getpid())
    for raw in sys.stdin:
        request = {}
        try:
            request = json.loads(raw)
            if request.get('command') == 'shutdown':
                break
            if request.get('command') != 'generate':
                raise ValueError('未知 worker 指令')
            spec, job_dir = request['spec'], Path(request['job_dir'])
            cancel_file = Path(request['cancel_file'])

            def progress(stage, ratio=None):
                if cancel_file.exists():
                    raise Cancelled('任务已取消')
                emit('progress', job_id=request.get('job_id'), stage=stage, ratio=ratio or 0)

            video = spec.get('mode') == 'video'
            if video:
                progress('准备视频识别', 0.01)
                engine_video = video_engine()
                if spec.get('evidence'):
                    progress('载入影像证据', 0.015)
                evidence = evidence_engine() if spec.get('evidence') else None
                if spec.get('comotion'):
                    progress('载入多人追踪', 0.02)
                comotion = comotion_engine() if spec.get('comotion') else None
                result = engine_video.recognize(Path(spec['image']), max_people=int(spec['max_people']), progress=progress,
                                                evidence=evidence, comotion=comotion)
            else:
                progress('读取图片', 0.05)
                image = load_image(spec['image'])
                result = engine.recognize(image, max_people=int(spec['max_people']), progress=lambda s: progress(s, 0.5))
            if spec.get('bodies'):
                progress('生成体型', 0.9)
                add_bodies(result['people'], spec['bodies'], component, builders)
            progress('生成场景', 0.95)
            build = build_sequence if video else build_snapshot
            snapshot = build(result, joint_names=joint_names, asset_id=spec.get('asset_id'),
                             engine_version=f'{ENGINE}@{GEMX_COMMIT[:12]}', updated_at=int(spec.get('submitted_at') or 0))
            path = job_dir / 'result.json'
            pending = path.with_suffix('.json.writing')
            pending.write_text(json.dumps(snapshot, ensure_ascii=False))
            pending.replace(path)
            emit('result', job_id=request.get('job_id'), paths=[str(path)], people=len(snapshot['people']))
        except Cancelled as exc:
            emit('cancelled', job_id=(request or {}).get('job_id'), message=str(exc))
        except Exception as exc:
            emit('error', job_id=(request or {}).get('job_id'), message=str(exc)[:2000],
                 exception=type(exc).__name__, traceback=traceback.format_exc(limit=12)[-12000:])
    for builder in builders.values():
        builder.close()


if __name__ == '__main__':
    main()

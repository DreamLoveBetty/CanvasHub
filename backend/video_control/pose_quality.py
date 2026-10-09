"""Worker-only validation of rendered pose coverage, not pose accuracy or recovery."""
import json
from pathlib import Path

MIN_COVERAGE = 0.10


def coverage_summary(total, visible):
    if total <= 0 or not 0 <= visible <= total:
        raise ValueError('无法检查骨骼视频帧')
    return {'frames': total, 'visible_frames': visible, 'coverage': visible / total,
            'minimum_coverage': MIN_COVERAGE, 'usable': visible / total >= MIN_COVERAGE}


def validate_pose_video(path, reporter):
    # Import only in the isolated worker; no inference deps enter the HTTP process.
    import cv2
    import numpy as np

    path = Path(path)
    capture = cv2.VideoCapture(str(path))
    total = visible = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            total += 1
            # Ignore near-black encoding noise and isolated tiny specks. This measures
            # visible output, not the detector's candidate-person count.
            lit = np.count_nonzero(np.max(frame, axis=2) > 32)
            if lit >= max(20, frame.shape[0] * frame.shape[1] * 0.0001):
                visible += 1
    finally:
        capture.release()
    summary = coverage_summary(total, visible)
    metrics_path = path.with_name('metrics.json')
    metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else {}
    metrics['pose_coverage'] = summary
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
    message = f'骨骼有效画面 {visible}/{total} 帧（{summary["coverage"]:.1%}）'
    reporter.step('check', message)
    if not summary['usable']:
        path.unlink(missing_ok=True)
        raise ValueError(message + '，未能持续识别人物，已拒绝输出近乎全黑的视频。'
                         '请使用人体清晰可见的片段；机甲、强遮挡和局部特写可能无法识别。')
    if summary['coverage'] < 0.8:
        reporter.step('warn', message + '，部分画面未识别到人物，可能出现黑帧')
    return summary

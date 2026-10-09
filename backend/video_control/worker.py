"""ReShot subprocess entrypoint. Inference dependencies never enter the HTTP process."""
import json
import os
from pathlib import Path
import sys
import signal
import threading
import time


def main():
    parent, request, source, output, models = sys.argv[1:]
    def watch_parent():
        while True:
            time.sleep(1)
            if os.getppid() != int(parent):
                os.killpg(os.getpgrp(), signal.SIGTERM)
                os._exit(130)
    threading.Thread(target=watch_parent, daemon=True).start()
    import reshot
    from reshot import RunConfig, run
    if reshot.__version__ != '0.5.0': raise RuntimeError('ReShot 版本与固定配置不一致')
    spec = json.loads(Path(request).read_text())
    output, models = Path(output), Path(models)
    output.mkdir(exist_ok=True)
    class Reporter:
        def step(self, tag, message):
            print('CANVAS_PROGRESS ' + json.dumps({'stage': str(tag), 'message': str(message)[:1000]}), flush=True)
    # Normalise/limit decoding before ReShot reads a clip into RAM. No audio is
    # retained in control videos; source assets remain untouched.
    import subprocess
    Reporter().step('prepare', '准备视频片段')
    clip = output.parent / 'prepared.mp4'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-protocol_whitelist', 'file,pipe', '-i', source,
        '-t', str(spec['max_seconds']), '-an', '-vf',
        f"scale='min({spec['max_res']},iw)':'min({spec['max_res']},ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,fps=24",
        '-frames:v', str(spec['max_seconds'] * 24), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(clip)],
        check=True, timeout=180)
    options = {key: spec[key] for key in ('control', 'quality', 'max_res', 'canny_low', 'canny_high', 'pose_hands', 'pose_face', 'invert')}
    if spec['control'] == 'depth': options['checkpoint'] = models / 'depth/video_depth_anything_vits.pth'
    if spec['control'] == 'pose': options['checkpoint_dir'] = models / 'pose'
    try:
        result = run(RunConfig(input=clip, output=output / 'control.mp4', target='h3',
            max_frames=spec['max_seconds'] * 24, metrics=output / 'metrics.json', **options), reporter=Reporter())
        if spec['control'] == 'pose':
            # Script entrypoint resolves sibling module without importing HTTP/runtime state.
            from pose_quality import validate_pose_video
            validate_pose_video(output / 'control.mp4', Reporter())
        (output / 'result.json').write_text(json.dumps(dict(width=result.width, height=result.height, fps=result.fps)))
    finally:
        clip.unlink(missing_ok=True)


if __name__ == '__main__': main()

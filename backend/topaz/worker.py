"""One native operation per child. JSON events, bounded inputs, atomic image output."""
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time


def report(payload):
    print('TOPAZ_EVENT ' + json.dumps(payload, ensure_ascii=False), flush=True)


def main():
    parent, app, models, source, work, model = sys.argv[1:]
    def watch_parent():
        while True:
            time.sleep(.5)
            if os.getppid() != int(parent):
                os.killpg(os.getpgrp(), signal.SIGTERM)
                os._exit(130)
    threading.Thread(target=watch_parent, daemon=True).start()
    from PIL import Image, ImageOps
    from catalog import request_for, MODELS
    from native import run
    work = Path(work)
    from parameters import normalize, dimensions, grain_stack
    options = normalize(json.loads((work / 'options.json').read_text()))
    with Image.open(source) as image:
        width, height = image.size
        request_for(model, width, height, options)  # Bound decoded size before allocation.
        image = ImageOps.exif_transpose(image)
        if image.mode in ('RGBA', 'LA') or 'transparency' in image.info:
            image = image.convert('RGBA')
            alpha = image.getchannel('A')
        else:
            alpha = None
        source_image = image.convert('RGB')
    width, height = source_image.size
    spec = request_for(model, width, height, options)
    (work / 'request.json').write_text(json.dumps(spec), encoding='utf-8')
    out_size = dimensions(width, height, options)
    meta = MODELS[model]
    if meta['protocol'] == 'neuro':
        from neuro import run as run_neuro
        source_image.save(work / 'input.png')
        pixel_output = work / 'output.tiff'
        run_neuro(app, work / 'input.png', pixel_output, spec, (width,height), out_size, work, report)
        if options['grain']:
            with Image.open(pixel_output) as pixels: pixels.convert('RGB').save(work / 'input.bmp')
            (work / 'post.json').write_text(json.dumps(grain_stack(options)))
            pixel_output = work / 'output.bmp'
            run(app, models, work / 'input.bmp', pixel_output, work / 'post.json', report, protocol='stack')
    else:
        from evidence import ModelEvidence
        evidence = ModelEvidence(meta['evidence'])
        def receive(event):
            evidence.observe(event)
            report(event)
        source_image.save(work / 'input.bmp')
        pixel_output = work / 'output.bmp'
        run(app, models, work / 'input.bmp', pixel_output, work / 'request.json', receive,
            protocol=meta['protocol'])
        evidence.validate()
    with Image.open(pixel_output) as image:
        image.load()
        if image.size != out_size:
            raise RuntimeError('Topaz 输出尺寸与请求不符')
        image = image.convert('RGB')
        if alpha is not None:
            image.putalpha(alpha.resize(image.size, Image.Resampling.LANCZOS))
        fmt = options['output_format']
        if fmt == 'jpg': image = image.convert('RGB')
        save = dict(dpi=(options['ppi'], options['ppi']))
        if fmt == 'jpg': save.update(quality=options['jpeg_quality'], subsampling=0)
        if fmt == 'tiff': save.update(compression='tiff_deflate')
        image.save(work / 'result.tmp', format={'jpg':'JPEG','png':'PNG','tiff':'TIFF'}[fmt], **save)
    os.replace(work / 'result.tmp', work / ('result.' + fmt))
    report(dict(event='result', input_width=width, input_height=height,
                output_width=out_size[0], output_height=out_size[1], scale=out_size[0]/width, model=model,
                device='MPS' if meta['protocol'] == 'neuro' else 'CoreML'))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        report(dict(event='error', message=str(exc)[:2000]))
        raise SystemExit(1)

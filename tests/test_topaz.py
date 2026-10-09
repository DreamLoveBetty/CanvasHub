"""Portable contract/supervision tests. No installed Topaz, GPU or credentials needed."""
import io
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from datetime import datetime

from backend.topaz import catalog
from backend.topaz.runtime import Runtime, TopazCancelled, TopazError
from backend.services import upscale_backends
from backend.topaz import routes, service, parameters, provision
from backend.services.upscale_generation import process_upscale_task, _coerce_upscale_tile
from backend.topaz.runtime import Result


class ContractTest(unittest.TestCase):
    def test_production_runtime_uses_owned_contents_and_repoints_legacy_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = (Path(tmp) / 'topaz').resolve()
            runtime = Runtime(root)
            self.assertEqual(runtime.app, root / 'vendor' / 'Contents')
            source = runtime.app / 'Resources' / 'models'
            source.mkdir(parents=True)
            (source / 'example.json').write_text('owned')
            target = root / 'models'
            target.mkdir()
            (target / 'coreMLCache').mkdir()
            legacy = catalog.APP / 'Resources' / 'models'
            (target / 'example.json').symlink_to(legacy / 'example.json')
            (target / 'obsolete.tz').symlink_to(legacy / 'obsolete.tz')
            models = runtime._models()
            self.assertEqual((models / 'example.json').read_text(), 'owned')
            self.assertEqual((models / 'example.json').resolve(), source / 'example.json')
            self.assertFalse((models / 'obsolete.tz').exists())
            self.assertTrue((models / 'coreMLCache').is_dir())

    def test_provision_clones_inside_app_data_and_rejects_external_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); source = base / 'source'; source.mkdir()
            (source / 'file').write_text('owned')
            (source / 'internal').symlink_to('file')
            def clone(command, *, check):
                self.assertEqual(command[:3], ['cp', '-c', '-R'])
                shutil.copytree(command[3], command[4], symlinks=True)
            with patch.object(provision, 'require_complete'), patch.object(provision.subprocess, 'run', side_effect=clone):
                destination = provision.install(source, base / 'data' / 'components' / 'topaz')
            self.assertEqual((destination / 'internal').read_text(), 'owned')
            self.assertEqual((destination / 'internal').resolve(), destination / 'file')
            self.assertTrue((destination.parent / 'runtime.json').is_file())
            (source / 'external').symlink_to(base / 'outside')
            with self.assertRaisesRegex(RuntimeError, '外部或断开'):
                provision.audit_links(source)

    def test_requests_are_distinct_and_not_cli_units(self):
        std = catalog.request_for('topaz-standard-v2', 256, 128)
        hf = catalog.request_for('topaz-high-fidelity-v3', 256, 128)
        self.assertEqual((std['output_width'], std['output_height']), (512, 256))
        self.assertEqual(std['denoise'], '0.2')
        self.assertIs(std['face_enhancement'], False)
        self.assertEqual(hf['strength'], '0.75')
        self.assertNotIn('denoise', hf)
        self.assertNotIn('key', std)

    def test_bounds_and_unknown_models(self):
        for model, w, h in [('topaz-standard-v2', 8, 16), ('topaz-standard-v2', 5000, 5000), ('unknown', 256, 256)]:
            with self.assertRaises(ValueError): catalog.request_for(model, w, h)
        with self.assertRaises(ValueError): upscale_backends.normalize_model('topaz-unknown')
        self.assertEqual(upscale_backends.normalize_model('anime'), '4x-AnimeSharp')

    def test_missing_installation_and_version_gate(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(catalog.sys, 'platform', 'darwin'), \
                patch.object(catalog.platform, 'machine', return_value='arm64'), \
                patch.object(catalog.shutil, 'which', return_value='/usr/bin/nm'):
            app = Path(tmp)
            self.assertIn('安装', catalog.check_installation(app))
            (app / 'Frameworks').mkdir()
            for name in catalog.LIBRARIES: (app / 'Frameworks' / name).write_bytes(b'not a vendor library')
            self.assertIn('版本', catalog.check_installation(app))
            self.assertTrue(all(not m['available'] for m in catalog.capabilities(app)))

    def test_wonder1_requires_all_exact_weights_and_auxiliary_embeddings(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(catalog, 'check_installation', return_value=''):
            app = Path(tmp); source = app / 'Resources/models'; source.mkdir(parents=True)
            for name in catalog.MODELS['topaz-wonder-1']['weights']:
                (source / name).write_bytes(b'synthetic weight')
            entry = lambda: next(m for m in catalog.capabilities(app) if m['id'] == 'topaz-wonder-1')
            self.assertTrue(entry()['available'])
            runtime = Runtime(app / 'canvas', app=app)
            linked = runtime._models() / 'tpn_embeds.bin'
            self.assertTrue(linked.is_symlink())
            self.assertEqual(linked.read_bytes(), b'synthetic weight')
            (source / 'tpn_embeds.bin').unlink()
            self.assertFalse(entry()['available'])
            (source / 'tpn_embeds.bin').write_bytes(b'synthetic weight')
            (source / 'tpn_unet-v1-fp16-64x64-new-mlc.tz').unlink()
            (source / 'tpn_unet-v1-fp16-64x64-mlc.tz').write_bytes(b'older variant')
            self.assertFalse(entry()['available'])

    def test_redefine_declares_and_links_required_embed_sidecars(self):
        sidecars = ('rxl_vocab.txt', 'rxl_merges.txt', 'neg_emb.yaml')
        for model in ('topaz-redefine-realistic', 'topaz-redefine-creative'):
            self.assertTrue(set(sidecars).issubset(catalog.MODELS[model]['weights']))
        self.assertTrue({'ggn_ap-v2-fp16-512x512-rev2-mlc.tz',
                         'apnb-v2-fp16-512x512-rev2-mlc.tz',
                         'slsp_ap-v2-fp16-512x512-rev2-mlc.tz'}.issubset(
                            catalog.MODELS['topaz-redefine-creative']['weights']))
        with tempfile.TemporaryDirectory() as tmp, patch.object(catalog, 'check_installation', return_value=''):
            app = Path(tmp)
            source = app / 'Resources/models'
            source.mkdir(parents=True)
            for pattern in catalog.MODELS['topaz-redefine-realistic']['weights']:
                (source / pattern.replace('*', 'v1')).write_bytes(b'synthetic model data')
            (source / 'license.lic').write_bytes(b'not a model sidecar')
            entry = lambda: next(m for m in catalog.capabilities(app) if m['id'] == 'topaz-redefine-realistic')
            self.assertTrue(entry()['available'])
            target = Runtime(app / 'canvas', app=app)._models()
            for name in sidecars:
                self.assertTrue((target / name).is_symlink())
                self.assertEqual((target / name).read_bytes(), b'synthetic model data')
            self.assertFalse((target / 'license.lic').exists())
            (source / 'neg_emb.yaml').unlink()
            self.assertFalse(entry()['available'])

    def test_topaz_is_not_a_spandrel_backend(self):
        runtime = Mock()
        engine = service.engine(runtime, {'topaz': {'scale': 6}})
        with patch.object(upscale_backends.spandrel, 'upscale_image_file') as legacy:
            engine.execute('in', 'out', model_name='topaz-standard-v2',
                           cancelled=lambda: False, progress=None, tile_size=256)
            self.assertEqual(runtime.execute.call_args.kwargs['options']['scale'], 6)
            legacy.assert_not_called()
            with self.assertRaises(ValueError):
                upscale_backends.execute('in', 'out', model_name='topaz-standard-v2')
        with patch.object(upscale_backends.spandrel, 'upscale_image_file') as legacy:
            upscale_backends.execute('in', 'out', model_name='4x-UltraSharp', model_dir='models')
            legacy.assert_called_once_with('in', 'out', model_name='4x-UltraSharp', model_dir='models')
        self.assertFalse(any(key.startswith('topaz-') for key in upscale_backends.MODELS))


class Handler:
    def __init__(self, model):
        body = json.dumps(dict(model=model, images=['data:image/png;base64,AA=='], telegram_enabled=False)).encode()
        self.headers = {'Content-Length': str(len(body))}
        self.rfile = io.BytesIO(body)
        self.send_json = Mock()
        self.start_generation_task = Mock(return_value=True)

    def read_json_body(self, **kwargs): return json.load(self.rfile)


class ServiceLifecycleTest(unittest.TestCase):
    def test_native_result_and_cancellation_share_existing_lifecycle(self):
        for phase in ('success', 'worker', 'after-worker', 'after-sidecar'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                flag = threading.Event()
                deps = {name: Mock() for name, param in inspect.signature(process_upscale_task).parameters.items()
                        if param.kind == inspect.Parameter.KEYWORD_ONLY}
                meta = Result(256, 256, 512, 512, 2, 'topaz-standard-v2', 'CoreML')
                def execute(source, output, **options):
                    self.assertFalse(options['cancelled']())
                    if phase in ('worker', 'after-worker'): flag.set()
                    if phase == 'worker': raise TopazCancelled('已取消')
                    return meta
                def sidecar(*args):
                    if phase == 'after-sidecar': flag.set()
                deps.update(Path=Path, UPSCALE_MODELS=upscale_backends.MODELS,
                    UPSCALE_MODEL_DIR=Path(tmp), UpscaleRuntimeError=RuntimeError,
                    _coerce_bool=lambda value, default: value,
                    _coerce_upscale_tile=_coerce_upscale_tile,
                    _decode_data_uri_image=lambda data: (b'synthetic', 'image/png', '.png'),
                    _start_generation_audit=Mock(return_value='run'),
                    _write_upscale_sidecar=Mock(side_effect=sidecar),
                    daily_output_dir=lambda now: Path(tmp), datetime=datetime, os=os, re=re,
                    tempfile=tempfile, normalize_upscale_model=upscale_backends.normalize_model,
                    random=Mock(randint=lambda a,b: 1234), is_task_canceled=lambda task_id: flag.is_set(),
                    upscale_image_file=Mock(),
                    engine=service.EnhancementEngine('topaz', 'topaz', catalog.MODELS, service.normalize_model, execute))
                process_upscale_task('task', 'synthetic', 'data',
                    dict(model='topaz-standard-v2', telegram_enabled=True), **deps)
                call = deps['_finalize_generation_task'].call_args
                self.assertEqual(call.args[1], 'succeeded' if phase == 'success' else 'canceled')
                self.assertEqual(call.kwargs['route'], 'topaz_native')
                if phase == 'success':
                    self.assertEqual(call.kwargs['extra']['scale'], 2)
                    deps['send_tg_document'].assert_called_once()
                else:
                    deps['send_tg_document'].assert_not_called()
                    self.assertNotIn('result_file', call.kwargs)


class RouteTest(unittest.TestCase):
    def invoke(self, available=True, body=None):
        handler = Handler('topaz-standard-v2')
        if body is not None: handler.rfile = io.BytesIO(json.dumps(body).encode())
        create = Mock()
        runtime = Mock(catalog=lambda: [dict(id='topaz-standard-v2', available=available,
                                            error='原生库版本待验证')])
        routes.submit(handler, runtime=runtime, create_task=create, process_task=Mock(), attach_lineage=Mock())
        return handler, create

    def test_submit_uses_existing_task_contract_but_own_type(self):
        handler, create = self.invoke()
        self.assertEqual(handler.send_json.call_args.args[1], 202)
        self.assertEqual(create.call_args.args[2]['topaz']['scale'], 2)
        self.assertEqual(create.call_args.kwargs['task_type'], 'topaz')
        self.assertTrue(create.call_args.args[0].startswith('topaz_'))
        handler.start_generation_task.assert_called_once()

    def test_unavailable_never_submits(self):
        handler, create = self.invoke(False)
        self.assertEqual(handler.send_json.call_args.args[1], 409)
        create.assert_not_called()

    def test_invalid_requests_never_queue(self):
        good = dict(model='topaz-standard-v2', images=['data:image/png;base64,AA=='])
        for body in ([], {}, {**good,'images':['file:///private']}, {**good,'model':[]},
                     {**good,'options':{'scale':0}}, {**good,'options':{'context':'secret'}}):
            with self.subTest(body=body):
                handler, create = self.invoke(body=body)
                self.assertEqual(handler.send_json.call_args.args[1], 400)
                create.assert_not_called()


class ParameterTest(unittest.TestCase):
    def test_expanded_profiles_build_the_verified_protocol_not_alias_guesses(self):
        old = catalog.request_for('topaz-standard-v1',128,128,{'grain':True})
        self.assertEqual(old[0]['params']['model'], 'Standard')
        self.assertEqual(old[1]['category'], 'Grain')
        self.assertEqual(old[1]['params']['noiseSize'], 1)
        maximum = catalog.request_for('topaz-standard-max',128,128)
        self.assertEqual(maximum[0]['params']['model'], 'Standard Max')
        recover = catalog.request_for('topaz-recover-v3',128,128)
        self.assertEqual(recover[0]['category'], 'Wonder')
        wonder = catalog.request_for('topaz-wonder-35',128,128,{'enhancement_strength':1.3})
        self.assertEqual(wonder, {'model':'Wonder 3.5','upscale_factor':2,'enhancement_strength':1.3})
        self.assertNotIn('enhancement_strength', catalog.request_for('topaz-wonder-2',128,128))
        creative = catalog.request_for('topaz-redefine-creative',128,128,{'creativity':5,'description':'shapes'})
        self.assertEqual(creative[0]['params']['creativity'],5)
        self.assertEqual(creative[0]['params']['prompt'],'shapes')
        realistic = catalog.request_for('topaz-redefine-realistic',128,128,{'realistic_detail':1,'description':'ignored'})
        self.assertEqual(realistic[0]['params']['creativity'],1)
        self.assertEqual(realistic[0]['params']['prompt'],'')
        for option in ({'creativity':0},{'creativity':6},{'realistic_detail':2},
                       {'seed':.5},{'enhancement_strength':.9},{'description':[]}, {'description':'x'*2001}):
            with self.subTest(option=option), self.assertRaises(ValueError): parameters.normalize(option)
        with self.assertRaises(ValueError): catalog.request_for('topaz-wonder-3',2048,2048)

    def test_catalog_frontend_ids_and_profiles_are_in_sync(self):
        path=Path(__file__).resolve().parents[1]/'frontend/scripts/desktop-topaz-model.js'
        text=path.read_text()
        entries=json.loads(text.split('const MODELS = ',1)[1].split(';',1)[0])
        self.assertEqual({m['value'] for m in entries},set(catalog.MODELS))
        for entry in entries:
            for field in ('label','profile','protocol','verified'):
                self.assertEqual(entry[field],catalog.MODELS[entry['value']][field])

    def test_presets_custom_downscale_and_physical_dimensions(self):
        for scale in (1,2,4,6,.2,.5,1.5):
            with self.subTest(scale=scale):
                self.assertEqual(parameters.dimensions(200,100,{'scale':scale}), (round(200*scale),round(100*scale)))
        self.assertEqual(parameters.dimensions(200,100,dict(resize_mode='width',dimension=321)), (321,161))
        self.assertEqual(parameters.dimensions(100,200,dict(resize_mode='longest',dimension=300)), (150,300))
        self.assertEqual(parameters.dimensions(200,100,dict(resize_mode='height',dimension=2,unit='in',ppi=300)), (1200,600))
        self.assertEqual(parameters.dimensions(200,100,dict(resize_mode='width',dimension=2.54,unit='cm',ppi=300)), (300,150))
        with self.assertRaises(ValueError): parameters.dimensions(4000,4000,{'scale':6})
        with self.assertRaises(ValueError): parameters.dimensions(16,16,dict(resize_mode='width',dimension=32000,unit='in'))

    def test_validation_and_no_native_json_passthrough(self):
        for option in ({'scale':float('nan')},{'scale':float('inf')},{'scale':True},{'scale':0},{'scale':7},
                       {'face_creativity':2},{'face_creativity':.5},{'jpeg_quality':99.5},
                       {'gamma_correction':'false'},{'output_format':'exe'},{'raw_json':{}}, {'unit':[]}):
            with self.subTest(option=option), self.assertRaises(ValueError): parameters.normalize(option)
        with self.assertRaises(ValueError): parameters.normalize([])

    def test_model_specific_native_units(self):
        std=parameters.native_options({'auto':True},standard=True)
        self.assertNotIn('denoise',std);self.assertNotIn('strength',std)
        hf=parameters.native_options(dict(strength=25,sharpen=100,face_enhancement=True,face_strength=40,
            face_creativity=1,grain=True,grain_strength=12,grain_intensity=30,grain_size=2),standard=False)
        self.assertEqual(hf['strength'],'0.25');self.assertNotIn('sharpen',hf)
        self.assertEqual(hf['face_enhancement_creativity'],1)
        self.assertEqual(hf['face_enhancement_strength'],.4)
        self.assertEqual(hf['grain_strength'],'0.12')
        self.assertNotIn('output_format',hf)


class PreviewTest(unittest.TestCase):
    def test_tiff_preview_preserves_original_and_dimensions(self):
        from PIL import Image
        from backend.services.image_preview import preview_png, image_url, preview_url
        from backend.routes.media_routes import handle_image, handle_archive_image
        import mimetypes
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.tiff'
            Image.new('RGBA',(32,48),(40,60,80,100)).save(path)
            original=path.read_bytes()
            preview=Image.open(io.BytesIO(preview_png(path)))
            self.assertEqual(preview.size,(32,48));self.assertEqual(preview.mode,'RGBA')
            self.assertEqual(path.read_bytes(),original)
            self.assertEqual(image_url(str(path)), '/image/test.tiff?preview=1')
            self.assertEqual(image_url('normal.png'),'/image/normal.png')
            self.assertEqual(preview_url('/archive_image/a/test.tiff'), '/archive_image/a/test.tiff?preview=1')
            for query, mime, expected in [('?preview=1','image/png',b'\x89PNG'),('','image/tiff',original[:4])]:
                handler=Mock(path='/image/test.tiff'+query,wfile=io.BytesIO())
                handle_image(handler,path.name,_resolve_download_file=lambda f:path,mimetypes=mimetypes,os=os)
                handler.send_response.assert_called_once_with(200)
                handler.send_header.assert_any_call('Content-Type',mime)
                self.assertTrue(handler.wfile.getvalue().startswith(expected))
                archive=Mock(path='/archive_image/a/test.tiff'+query,wfile=io.BytesIO())
                handle_archive_image(archive,'a/test.tiff',_resolve_archive_image_file=lambda f:path,mimetypes=mimetypes)
                archive.send_header.assert_any_call('Content-Type',mime)
                self.assertTrue(archive.wfile.getvalue().startswith(expected))


class RunnerContractTest(unittest.TestCase):
    def test_silent_model_fallback_is_rejected_even_when_pixels_exist(self):
        from backend.topaz.evidence import ModelEvidence
        evidence=ModelEvidence(('stdmax','stdmax_noee'))
        evidence.observe({'event':'log','message':'Model: ggn_noee Device: 0'})
        with self.assertRaises(RuntimeError): evidence.validate()
        evidence.observe({'event':'log','message':'Model: stdmax_noee Device: 0'})
        evidence.validate()

    def test_wonder_progress_uses_actual_phase_boundaries(self):
        from backend.topaz.neuro import phase_event, check_runtime
        self.assertIsNone(phase_event('Model still loading'))
        values=[phase_event(f'Phase {i}: work')['percent'] for i in range(1,5)]
        self.assertEqual(values,[10,25,75,90])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn('未安装',check_runtime(tmp))

    def test_neuro_runner_checks_model_success_and_inherits_process_group(self):
        from backend.topaz import neuro
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);output=root/'output.tiff';output.write_bytes(b'pixels')
            for valid in (False,True):
                process=Mock()
                process.stdout=io.StringIO('Getting model for request: Wonder 3.5\nPhase 2: DiT\n'+
                    ('single_shot_process status: TopServingErrorCode.OK\n' if valid else 'failed\n'))
                process.wait.return_value=0;process.poll.return_value=0
                with patch.object(neuro,'check_runtime',return_value=''),patch.object(neuro.subprocess,'Popen',return_value=process) as popen:
                    args=(root,root/'source.png',output,{'model':'Wonder 3.5','upscale_factor':2},(128,128),(256,256),root,Mock())
                    if valid: neuro.run(*args)
                    else:
                        with self.assertRaises(RuntimeError): neuro.run(*args)
                    self.assertNotIn('start_new_session',popen.call_args.kwargs)
                    self.assertEqual(popen.call_args.kwargs['env']['HF_HUB_OFFLINE'],'1')


@unittest.skipUnless(os.name == 'posix', 'Process group contract is POSIX-only')
class SupervisorTest(unittest.TestCase):
    def test_cancel_timeout_and_partial_result_cleanup(self):
        # Synthetic worker emits real process events but never loads native code.
        for mode in ('cancel', 'timeout', 'callback-error', 'download'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                fake = root / 'worker.py'
                fake.write_text("import json,time,sys\nfrom pathlib import Path\n"
                    "work=Path(sys.argv[1]);(work/'output.bmp').write_bytes(b'partial')\n" +
                    ("print('TOPAZ_EVENT '+json.dumps({'event':'log','message':'Waiting for download of missing.tz'}),flush=True)\n" if mode=='download' else
                     "print('TOPAZ_EVENT '+json.dumps({'event':'progress','percent':25}),flush=True)\n") +
                    "time.sleep(30)\n")
                runtime = Runtime(root / 'component', timeout=.3 if mode=='timeout' else 5)
                flag = threading.Event()
                processes = []
                real_popen = subprocess.Popen
                def popen(command, **kwargs):
                    process = real_popen([sys.executable, str(fake), command[-2]], **kwargs)
                    processes.append(process)
                    return process
                def progress(ratio, text):
                    if '推理' in text:
                        if mode == 'cancel': flag.set()
                        if mode == 'callback-error': raise ValueError('callback failed')
                with patch.object(runtime, 'catalog', return_value=[dict(id='topaz-standard-v2', available=True)]), \
                        patch.object(runtime, '_models', return_value=root), \
                        patch('backend.topaz.runtime.subprocess.Popen', side_effect=popen):
                    expected = TopazCancelled if mode=='cancel' else (TopazError if mode in ('timeout','download') else ValueError)
                    with self.assertRaises(expected):
                        runtime.execute(root/'input.png', root/'output.png', model='topaz-standard-v2',
                                        cancelled=flag.is_set, progress=progress)
                self.assertIsNotNone(processes[0].poll())
                self.assertFalse((root/'output.png').exists())
                self.assertFalse(list((root/'component/jobs').glob('*/output.bmp')))


if __name__ == '__main__': unittest.main()

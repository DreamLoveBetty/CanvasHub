"""Portable Qwen domain regressions; no real weights, credentials or MLX."""
import hashlib
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

from PIL import Image

from backend.asset_index import _provider_group, _provider_label
from backend.local_image.runtime import JsonLineRuntime, LocalImageCancelled, LocalImageError
from backend.local_image.uploads import ImageUploads
from backend.qwen21.contracts import DEFAULT_MODEL_ID, ENGINE, TASK_TYPE, normalize_job
from backend.qwen21.conversion_service import ConversionService
from backend.qwen21.install import prepare_source
from backend.qwen21.lora_store import LoRAStore, canonical_lora_key
from backend.qwen21.model_store import BaseModelStore
from backend.qwen21.profiles import RAW_SIGMAS, dimensions, edit_noise_seed, viggle_sigmas
from backend.qwen21.profiles import ADAPTERS, DEFAULT_PRESET, PRESETS, raw_viggle_sigmas
from backend.qwen21.environment import turbo_path, turbo_ready
from backend.qwen21.service import Service
from backend.qwen21.source_adapter import TARGETS, apply, expected_files, recognized, ready
from backend.qwen21.weight_schema import expected_shapes, match_header, mlx_name
from backend.routes.qwen21_routes import create_router
from backend.runtime_resources import IdleWorkerCoordinator


def lora_fixture(target='transformer_blocks.0.attn.to_q', prefix='transformer.', rank=1, out=4096, inp=4096):
    tensors = {}; payload = bytearray()
    for side, shape in [('A', [rank, inp]), ('B', [out, rank])]:
        start = len(payload); payload.extend(b'\0' * (2 * shape[0] * shape[1]))
        tensors[prefix + target + '.lora_' + side + '.weight'] = {
            'dtype': 'F16', 'shape': shape, 'data_offsets': [start, len(payload)]}
    header = json.dumps(tensors).encode()
    return struct.pack('<Q', len(header)) + header + payload


def image_fixture(color='red'):
    stream = io.BytesIO(); Image.new('RGBA', (16, 16), color).save(stream, format='PNG'); return stream.getvalue()


class ContractTests(unittest.TestCase):
    def test_defaults_and_standard_preserve_parameters(self):
        spec = normalize_job({'prompt': '  a teapot  ', 'seed': 42})
        self.assertEqual((spec['prompt'], spec['preset'], spec['steps'], spec['guidance']), ('a teapot', DEFAULT_PRESET, 6, 1))
        self.assertEqual(spec['base_model_id'], DEFAULT_MODEL_ID)
        std = normalize_job({'prompt': 'x', 'preset': 'standard', 'steps': 37, 'guidance': 4.5,
                             'negative_prompt': 'blur', 'base_model_id': 'portrait-8bit'})
        self.assertEqual((std['steps'], std['guidance'], std['negative_prompt']), (37, 4.5, 'blur'))
        self.assertEqual(std['base_model_id'], 'portrait-8bit')

    def test_turbo_accepts_custom_steps_but_retains_cfg_and_negative_constraints(self):
        for fields in ({'steps': 4}, {'steps': 61}, {'guidance': 2}, {'negative_prompt': 'blur'}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                normalize_job({'prompt': 'x', **fields})
        self.assertEqual(normalize_job({'prompt': 'x', 'preset': 'viggle-8'})['steps'], 8)
        self.assertEqual(normalize_job({'prompt': 'x', 'preset': 'viggle-6'})['preset'], DEFAULT_PRESET)
        for preset in ADAPTERS:
            for steps in (5,7,8,10,30,60):
                with self.subTest(preset=preset,steps=steps):
                    result=normalize_job({'prompt':'x','preset':preset,'steps':steps})
                    self.assertEqual((result['preset'],result['steps']),(preset,steps))

    def test_reference_order_limits_and_modes(self):
        tokens = ['a' * 32, 'b' * 32]
        self.assertEqual(normalize_job({'prompt': 'edit', 'mode': 'edit', 'reference_upload_tokens': tokens})['reference_upload_tokens'], tokens)
        for fields in ({'mode': 'edit'}, {'reference_upload_tokens': tokens},
                       {'mode': 'edit', 'reference_upload_tokens': ['a' * 32] * 4},
                       {'mode': 'edit', 'reference_upload_tokens': ['../../x']}):
            with self.subTest(fields=fields), self.assertRaises(ValueError): normalize_job({'prompt': 'x', **fields})
        self.assertEqual(len(normalize_job({'prompt': 'edit', 'mode': 'edit', 'preset': 'standard',
                                           'reference_upload_tokens': ['a' * 32] * 10})['reference_upload_tokens']), 10)

    def test_dimension_seed_and_lora_guards(self):
        for fields in ({'width': 513}, {'height': True}, {'seed': 2**32}, {'width': float('nan')},
                       {'guidance': float('inf')}, {'image_count': 5}, {'base_model_id': '../../model'}):
            with self.subTest(fields=fields), self.assertRaises(ValueError): normalize_job({'prompt': 'x', **fields})
        loras = [{'asset_id': char * 64, 'scale': .8} for char in 'abcd']
        self.assertEqual(normalize_job({'prompt': 'x', 'loras': loras})['loras'], loras)
        with self.assertRaisesRegex(ValueError, '重复'): normalize_job({'prompt': 'x', 'loras': loras[:1] * 2})
        with self.assertRaises(ValueError): normalize_job({'prompt': 'x', 'loras': loras + [{'asset_id': 'e'*64}]})

    def test_shifted_profiles_and_independent_reference_noise(self):
        for steps in (5,6,7,8,9,12,60):
            sigma = viggle_sigmas(steps, 1024, 1024)
            self.assertEqual(len(sigma), steps + 1)
            self.assertEqual((sigma[0], sigma[-1]), (1, 0))
            self.assertTrue(all(a > b for a, b in zip(sigma, sigma[1:])))
            nodes=raw_viggle_sigmas(steps)
            self.assertNotEqual(tuple(sigma[:-1]), nodes)
            self.assertEqual(nodes[-4:],(.875,.75,.5,.25))
        self.assertEqual(RAW_SIGMAS[6],(1,.9375,.875,.75,.5,.25))
        for steps in (4,61,True,6.5):
            with self.assertRaises(ValueError): viggle_sigmas(steps, 512, 512)
        a, b = Image.new('RGBA', (8, 8), 'red'), Image.new('RGBA', (8, 8), 'blue')
        self.assertEqual(edit_noise_seed(42, [a, b]), edit_noise_seed(42, [a.copy(), b.copy()]))
        self.assertNotEqual(edit_noise_seed(42, [a, b]), edit_noise_seed(42, [b, a]))
        self.assertEqual(edit_noise_seed(42, []), 42)
        for ratio in ['1:1', '9:16', '16:9', '2:3']:
            self.assertTrue(all(value % 32 == 0 for value in dimensions(ratio)))

    def test_exact_297_schema_and_wrappers(self):
        shapes = expected_shapes(); self.assertEqual(len(shapes), 297)
        self.assertEqual(shapes['norm_out.linear.weight'], (4096, 4096))
        self.assertEqual(mlx_name('modulation.1.weight'), 'modulation.layers.1.weight')
        for prefix in ('', 'transformer.', 'model.diffusion_model.'):
            tensors = {prefix + key: {'shape': list(shape)} for key, shape in shapes.items()}
            self.assertEqual(match_header(tensors), prefix)
            tensors[prefix + 'transformer_blocks.32.attn.to_q.weight'] = {'shape': [4096,4096]}
            with self.assertRaises(ValueError): match_header(tensors)
        missing = {key: {'shape': list(shape)} for key, shape in shapes.items()}; missing.pop('img_in.weight')
        with self.assertRaises(ValueError): match_header(missing)
        missing['img_in.weight'] = {'shape': [4096, 128]}
        with self.assertRaises(ValueError): match_header(missing)

    def test_provider_is_qwen_not_google(self):
        for item in ({'type': TASK_TYPE}, {'type': 'image', 'params': {'provider': ENGINE}}, {'provider': ENGINE}):
            self.assertEqual(_provider_group(item), 'qwen21')
        self.assertEqual(_provider_label('qwen21'), 'Qwen 2.1')


class StorageTests(unittest.TestCase):
    def test_adapter_readiness_is_per_version_rank_not_other_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch('backend.qwen21.environment.Path.stat') as stat:
                stat.return_value.st_size=ADAPTERS['viggle-v021-r128']['size']
                with mock.patch('backend.qwen21.environment.Path.is_file',return_value=True), \
                     mock.patch('backend.qwen21.environment.Path.is_symlink',return_value=False):
                    self.assertTrue(turbo_ready(temp,'viggle-v021-r128'))
                    self.assertFalse(turbo_ready(temp,'viggle-v03-r256'))
            self.assertIn('v0.3-6step-lora-r256',str(turbo_path(temp,'viggle-v03-r256')))
            self.assertIn('v0.3-6step-lora-r256',str(turbo_path(temp,'viggle-8')))

    def test_lora_direct_scan_peft_names_shapes_and_unsupported_targets(self):
        with tempfile.TemporaryDirectory() as temp:
            store = LoRAStore(temp); store.directory.mkdir()
            data = lora_fixture(prefix='diffusion_model.')
            file = store.directory/'style.safetensors'; file.write_bytes(data)
            item = store.list()[0]
            self.assertEqual(item['name'], 'style')
            self.assertEqual(store.resolve(item['asset_id'])[0], file.resolve())
            (store.directory/'wrong.safetensors').write_bytes(lora_fixture(out=32))
            self.assertEqual(len(store.list()), 1); self.assertTrue(store.scan_errors())
            self.assertEqual(canonical_lora_key('base_model.model.transformer_blocks.1.attn.to_q.lora_A.default.weight'),
                             ('transformer_blocks.1.attn.to_q','A'))
            with self.assertRaises(ValueError): canonical_lora_key('transformer.img_in.lora_A.weight')
            with self.assertRaises(ValueError): canonical_lora_key('transformer.transformer_blocks.32.attn.to_q.lora_A.weight')
            file.unlink(); self.assertEqual(store.list(), [])

    def test_publish_validated_model_and_reject_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); store = BaseModelStore(root/'assets', root/'component'); store.paths()
            stage = store.staging/'probe'; (stage/'transformer').mkdir(parents=True)
            file = stage/'transformer/0.safetensors'; file.write_bytes(b'synthetic worker output')
            (stage/'transformer/config.json').write_text('{}'); (stage/'transformer/model.safetensors.index.json').write_text('{}')
            result = {'source_sha256': 'a'*64, 'output_sha256': 'b'*64, 'strict_load': True, 'strict_reload': True,
                      'quantized_linear_count': 228, 'source_tensor_count': 297, 'source_format': 'comfy-scaled-fp8-e4m3fn'}
            with self.assertRaisesRegex(RuntimeError, '校验失败'): store.publish(stage, result, name='Portrait', source_name='x.safetensors')
            self.assertTrue(stage.is_dir()); self.assertEqual(len(store.list()), 1)
            result['output_sha256'] = hashlib.sha256(file.read_bytes()).hexdigest()
            item = store.publish(stage, result, name='Portrait', source_name='x.safetensors')
            self.assertEqual(item['name'], 'Portrait'); self.assertTrue(item['requantized']); self.assertFalse(item['ready'])
            self.assertNotIn('path', item); self.assertFalse(stage.exists())
            self.assertTrue((store.directory/item['id']/'text_encoder').is_symlink())
            with self.assertRaises(ValueError): store.delete(DEFAULT_MODEL_ID)
            store.delete(item['id']); self.assertEqual(len(store.list()), 1)

    def test_import_path_and_wrong_architecture_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            store = BaseModelStore(Path(temp)/'assets', Path(temp)/'components'); store.paths()
            with self.assertRaises(ValueError): store.inspect_source('../x.safetensors')
            (store.import_directory/'lora.safetensors').write_bytes(lora_fixture())
            with self.assertRaisesRegex(ValueError, 'LoRA'): store.inspect_source('lora.safetensors')
            self.assertEqual(len(store.list_imports()), 1)

    def test_uploads_copy_original_rgba_with_opaque_tokens(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); uploads = ImageUploads(root/'uploads'); job = root/'job'; job.mkdir()
            original = image_fixture(); item = uploads.upload(original, '../../ref.png')
            self.assertRegex(item['upload_token'], r'^[a-f0-9]{32}$')
            self.assertEqual(item['filename'], 'ref.png')
            path = Path(uploads.copy(item['upload_token'], job, 'reference_1'))
            self.assertEqual(path.read_bytes(), original)
            with self.assertRaises(ValueError): uploads.copy('f'*32, job, 'missing')
            with self.assertRaises(ValueError): uploads.upload(b'not an image')

    def test_exact_source_adapter_idempotent_and_rejects_user_edit(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            for target, (original, patched) in expected_files().items():
                file = source/target; file.parent.mkdir(parents=True, exist_ok=True); file.write_bytes(original)
            self.assertTrue(recognized(source)); self.assertFalse(ready(source))
            digest = apply(source); self.assertEqual(apply(source), digest); self.assertTrue(ready(source))
            file = source/TARGETS[0]; file.write_bytes(file.read_bytes()+b'\n# user edit\n')
            with self.assertRaises(RuntimeError): apply(source)
            self.assertFalse(ready(source))

    def test_fresh_clone_materializes_pin_before_dirty_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            component = Path(temp); source = component/'source/mflux'
            seen = []
            def run(command, **kwargs):
                seen.append(command)
                if command[1] == 'clone': (source/'.git').mkdir(parents=True)
            from backend.qwen21.contracts import REVISION
            def output(command, **kwargs):
                if 'get-url' in command: return 'https://github.com/mflux-community/mflux.git\n'
                if 'rev-parse' in command: return REVISION+'\n'
                if 'status' in command:
                    self.assertTrue(any('checkout' in call for call in seen))
                    return ''
                raise AssertionError(command)
            with mock.patch('backend.qwen21.install.subprocess.run', side_effect=run), \
                 mock.patch('backend.qwen21.install.subprocess.check_output', side_effect=output), \
                 mock.patch('backend.qwen21.install.apply_source_adapter', return_value='patch-hash'):
                self.assertEqual(prepare_source(component), 'patch-hash')


class RuntimeTests(unittest.TestCase):
    def test_orphaned_resident_child_stops_when_owning_parent_exits(self):
        from backend.local_image.parent_watch import start_parent_watch
        with mock.patch.dict(os.environ, {'CANVASHUB_IMAGE_PARENT_PID':'123'}), \
             mock.patch('backend.local_image.parent_watch.os.getppid', side_effect=[123,999]), \
             mock.patch('backend.local_image.parent_watch.time.sleep'), \
             mock.patch('backend.local_image.parent_watch.os._exit') as stop, \
             mock.patch('backend.local_image.parent_watch.threading.Thread') as thread:
            start_parent_watch()
            thread.call_args.kwargs['target']()
            stop.assert_called_once_with(0)

    def test_interleaved_progress_warm_reuse_and_guarded_unload(self):
        worker = '''import json,sys,time\nfrom pathlib import Path\nfor line in sys.stdin:\n r=json.loads(line)\n if r['command']=='shutdown':break\n print('tqdm [====] TEST_EVENT '+json.dumps({'event':'progress','ratio':.5,'stage':'step 1'}),flush=True)\n p=Path(r['job_dir'])/'out.png';p.write_bytes(b'pixels')\n print('TEST_EVENT '+json.dumps({'event':'result','job_id':r['job_id'],'paths':[str(p)]}),flush=True)\n'''
        class Runtime(JsonLineRuntime):
            @property
            def python(self): return Path(sys.executable)
            def child_environment(self): return dict(os.environ)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); file=root/'fake.py'; file.write_text(worker)
            hooks=[]; runtime=Runtime(root/'components/fake',worker=file,label='Test',prefix='TEST_EVENT ',idle_seconds=1,
                                      before_load=lambda:hooks.append('load'))
            self.addCleanup(runtime.close)
            results=[]
            for name in ('one','two'):
                directory=root/name;directory.mkdir()
                result=runtime.execute({},directory,threading.Event(),lambda r,t:results.append((r,t)))
                self.assertTrue(result['paths'][0].is_file())
            self.assertEqual(results,[(.5,'step 1')]*2); self.assertEqual(hooks,['load']*2)
            with mock.patch.object(runtime,'_request_lock') as lock:
                lock.acquire.return_value=False
                with self.assertRaises(LocalImageError): runtime.close_idle()
            runtime.close_idle()

    def test_cancelled_before_lease_does_not_unload_any_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime=JsonLineRuntime(Path(temp)/'components/fake', worker=__file__, label='Test',prefix='X')
            canceled=threading.Event(); canceled.set(); hook=mock.Mock();runtime.before_load=hook
            with self.assertRaises(LocalImageCancelled): runtime.execute({},temp,canceled,lambda r,t:None)
        hook.assert_not_called()

    def test_coordinator_explicit_idle_ports(self):
        a,b=mock.Mock(),mock.Mock(); coordinator=IdleWorkerCoordinator({'krea2':a,'qwen21':b})
        coordinator.release_other('qwen21');a.assert_called_once();b.assert_not_called()
        coordinator.release_all();self.assertEqual(a.call_count,2);b.assert_called_once()


class ServiceTests(unittest.TestCase):
    def test_conversion_waiting_cancel_preserves_other_worker_and_removes_staging(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);shared=root/'assets/shared';(shared/'transformer').mkdir(parents=True)
            (shared/'transformer/config.json').write_text('{}')
            stage=root/'assets/.staging';stage.mkdir()
            store=types.SimpleNamespace(shared=shared,staging=stage,directory=root/'assets',paths=lambda:None,
                inspect_source=lambda source:{'source_path':str(root/'source.safetensors'),'source_name':source,
                    'source_format':'comfy-scaled-fp8-e4m3fn','suggested_name':'Portrait'})
            runtime=types.SimpleNamespace(release_accelerator_memory=mock.Mock())
            waiting=threading.Event()
            @contextmanager
            def lease(path,cancel,progress):
                progress({'message':'等待其他本地任务'});waiting.set();cancel.wait(3)
                yield types.SimpleNamespace(fileno=lambda:1)
            service=ConversionService(root/'data',root/'components/qwen21',runtime,store)
            self.addCleanup(service.close)
            with mock.patch('backend.qwen21.conversion_service.local_accelerator',lease), \
                 mock.patch('backend.qwen21.conversion_service.shutil.disk_usage',return_value=types.SimpleNamespace(free=100*1024**3)), \
                 mock.patch.object(service,'_execute') as execute:
                reply=service.start({'source_path':'Portrait.safetensors','model_name':'Portrait'})
                self.assertTrue(waiting.wait(2));self.assertEqual(service.status()['status'],'waiting')
                service.cancel();service._thread.join(timeout=3)
                self.assertEqual(service.status()['status'],'canceled')
                self.assertFalse((stage/reply['job_id']).exists());execute.assert_not_called()
                runtime.release_accelerator_memory.assert_not_called()

    def test_ordered_references_archive_task_timing_and_document_port(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); tasks={}; sent=[]; captured=[]
            class Runtime:
                def status(self): return {'environment_ready':True,'source_ready':True,'turbo_ready':True}
                def execute(self,spec,directory,cancel,progress):
                    captured.append(spec);progress(.5,'synthetic denoise'); paths=[]
                    for i in range(spec['image_count']):
                        path=directory/f'{i}.png';path.write_bytes(image_fixture('blue'));paths.append(path)
                    return {'paths':paths,'base_model_id':DEFAULT_MODEL_ID,'base_model_name':'Synthetic Qwen Base',
                            'seed':spec['seed'],'precision':'8bit','generation_timing':{
                                'schema_version':1,'local_inference':True,'model_load_seconds':1,
                                'inference_seconds':2,'denoise_seconds':3,'save_seconds':.5,'total_seconds':6.5}}
                def close(self): pass
            class Store:
                def selection(self): return {'default_model_id':DEFAULT_MODEL_ID,'model_replacements':{}}
                def resolve(self,model_id): return {'id':DEFAULT_MODEL_ID,'name':'Synthetic Qwen Base','precision':'8bit','path':root/'model','ready':True}
                def list(self): return [{key:value for key,value in self.resolve(DEFAULT_MODEL_ID).items() if key!='path'}]
            conversion=types.SimpleNamespace(close=lambda:None,status=lambda:{'status':'idle'})
            def fields(task_id,**values):
                for key in ('params','result_files'):
                    if isinstance(values.get(key),str):values[key]=json.loads(values[key])
                tasks[task_id].update(values)
            def create(task_id,prompt,params,status,task_type):
                tasks[task_id]={'task_id':task_id,'prompt':prompt,'params':params,'status':status,'type':task_type}
            service=Service(root/'data',root/'components/qwen21',Runtime(),create_task=create,
                get_task=tasks.get,get_all_tasks=lambda limit=50:list(tasks.values()),
                update_task=lambda id,status,**kw:fields(id,status=status,**kw),
                update_task_status=lambda id,status,message=None,**kw:fields(id,status=status,progress_text=message,**kw),
                update_task_fields=fields,daily_output_dir=lambda:root/'archive/2026-01-01',
                write_prompt_sidecar=lambda image,prompt,txt_path=None:image.with_suffix('.md').write_text(prompt),
                send_document=lambda path,caption:sent.append(path.read_bytes()),model_store=Store(),conversion_service=conversion)
            self.addCleanup(service.close)
            tokens=[service.upload_image(image_fixture(color))['upload_token'] for color in ('red','blue')]
            reply=service.submit({'prompt':'combine Image 1 and Image 2','mode':'edit','reference_upload_tokens':tokens[::-1],
                                  'telegram_enabled':True,'image_count':2,'seed':42})
            deadline=time.monotonic()+4
            while tasks[reply['task_id']]['status'] not in {'succeeded','failed'} and time.monotonic()<deadline:time.sleep(.02)
            task=tasks[reply['task_id']];self.assertEqual(task['status'],'succeeded');self.assertEqual(task['type'],TASK_TYPE)
            self.assertEqual(len(sent),2);self.assertEqual(task['params']['reference_count'],2)
            self.assertNotIn(str(root),json.dumps(task['params']));self.assertNotIn('reference_upload_tokens',task['params'])
            with Image.open(captured[0]['references'][0]) as image:self.assertEqual(image.getpixel((0,0)),(0,0,255,255))
            self.assertEqual(task['params']['generation_timing']['model_load_seconds'],1)
            self.assertEqual(captured[0]['vae']['id'], 'builtin')
            self.assertEqual(task['params']['vae_id'], 'builtin')
            self.assertGreaterEqual(task['params']['duration_seconds'],6.5)
            for name in task['result_files']:
                path=root/'archive/2026-01-01'/name
                self.assertTrue(path.with_suffix('.txt').is_file());self.assertTrue(path.with_suffix('.md').is_file())
                self.assertEqual(json.loads(path.with_suffix('.qwen21.json').read_text())['generation_timing'],task['params']['generation_timing'])
                self.assertEqual(path.read_bytes(),image_fixture('blue'))

    def test_queued_vae_choice_is_snapshotted_and_private_path_stays_in_worker_spec(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);tasks={};queued=[]
            runtime=mock.Mock();runtime.status.return_value={'environment_ready':True,'source_ready':True,'turbo_ready':True}
            store=mock.Mock();store.resolve.return_value={'id':DEFAULT_MODEL_ID,'name':'Synthetic','precision':'8bit','path':root/'base'}
            store.selection.return_value={'default_model_id':DEFAULT_MODEL_ID,'model_replacements':{}}
            def create(task_id,prompt,params,**kw):tasks[task_id]={'params':params,**kw}
            with mock.patch('backend.qwen21.service.ImageTaskQueue') as Queue:
                Queue.return_value.enqueue.side_effect=lambda task_id,spec,create:(create(),queued.append(spec))
                service=Service(root/'data',root/'components/qwen21',runtime,create_task=create,get_task=tasks.get,
                    get_all_tasks=lambda **kw:[],update_task=mock.Mock(),update_task_status=mock.Mock(),update_task_fields=mock.Mock(),
                    daily_output_dir=lambda:root/'archive',write_prompt_sidecar=mock.Mock(),send_document=mock.Mock(),
                    model_store=store,conversion_service=mock.Mock())
                self.addCleanup(service.close)
                custom={'id':'a'*64,'name':'Community VAE','sha256':'a'*64,'format':'diffusers','path':str(root/'private/vae')}
                with mock.patch.object(service.vaes,'resolve',side_effect=[custom,{'id':'builtin','name':'Original','sha256':'b'*64,'format':'mflux'}]):
                    first=service.submit({'prompt':'teapot'})
                    service.submit({'prompt':'teapot'})
                self.assertEqual([x['vae']['id'] for x in queued],['a'*64,'builtin'])
                self.assertEqual(tasks[first['task_id']]['params']['vae_sha256'],'a'*64)
                self.assertNotIn(str(root),json.dumps(tasks))

    def test_routes_require_auth_and_do_not_touch_other_domains(self):
        service=mock.Mock();service.status.return_value={'ok':True,'ready':True};service.submit.return_value={'task_id':'qwen21_'+'a'*32}
        router=create_router(service)
        handler=types.SimpleNamespace(path='/api/qwen21/status',require_auth=mock.Mock(return_value=False),send_json=mock.Mock())
        self.assertTrue(router.dispatch(handler,'GET','/api/qwen21/status'));service.status.assert_not_called()
        handler.require_auth.return_value=True;router.dispatch(handler,'GET','/api/qwen21/status');service.status.assert_called_once()
        handler.read_json_body=lambda **kwargs:{'prompt':'teapot'}
        router.dispatch(handler,'POST','/api/qwen21/generate');self.assertEqual(handler.send_json.call_args.args[1],202)
        self.assertFalse(router.dispatch(handler,'GET','/api/krea2/status'))


if __name__=='__main__':unittest.main()

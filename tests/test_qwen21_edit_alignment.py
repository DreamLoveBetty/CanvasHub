"""Zero-offset Qwen edit alignment: geometry, contract and submission."""
import json
from pathlib import Path
import tempfile
import time
import types
import unittest

from PIL import Image

from backend.qwen21.contracts import DEFAULT_MODEL_ID, normalize_job
from backend.qwen21.edit_alignment import align_reference, crop_box, fixed_point_size
from backend.qwen21.profiles import dimensions
from backend.qwen21.service import Service


def service_for(root, tasks, captured):
    class Runtime:
        def status(self): return {'environment_ready': True, 'source_ready': True, 'turbo_ready': True}
        def execute(self, spec, directory, cancel, progress):
            captured.append(spec)
            path = directory / 'out.png'
            Image.new('RGBA', (spec['width'], spec['height']), 'blue').save(path)
            return {'paths': [path], 'base_model_id': DEFAULT_MODEL_ID, 'base_model_name': 'Synthetic',
                    'seed': spec['seed'], 'precision': '8bit'}
        def close(self): pass

    class Store:
        def selection(self): return {'default_model_id': DEFAULT_MODEL_ID, 'model_replacements': {}}
        def resolve(self, model_id): return {'id': DEFAULT_MODEL_ID, 'name': 'Synthetic', 'precision': '8bit',
                                             'path': root / 'model', 'ready': True}
        def list(self): return []

    def fields(task_id, **values):
        for key in ('params', 'result_files'):
            if isinstance(values.get(key), str):
                values[key] = json.loads(values[key])
        tasks[task_id].update(values)

    def create(task_id, prompt, params, status, task_type):
        tasks[task_id] = {'task_id': task_id, 'prompt': prompt, 'params': params, 'status': status, 'type': task_type}

    return Service(root / 'data', root / 'components/qwen21', Runtime(), create_task=create, get_task=tasks.get,
                   get_all_tasks=lambda limit=50: list(tasks.values()),
                   update_task=lambda id, status, **kw: fields(id, status=status, **kw),
                   update_task_status=lambda id, status, message=None, **kw: fields(id, status=status, **kw),
                   update_task_fields=fields, daily_output_dir=lambda: root / 'archive',
                   write_prompt_sidecar=lambda image, prompt, txt_path=None: None,
                   send_document=lambda path, caption: None, model_store=Store(),
                   conversion_service=types.SimpleNamespace(close=lambda: None, status=lambda: {'status': 'idle'}))


def png_bytes(size):
    path = Path(tempfile.mkstemp(suffix='.png')[1])
    Image.new('RGB', size, 'red').save(path)
    data = path.read_bytes()
    path.unlink()
    return data


class GeometryTests(unittest.TestCase):
    def test_sizes_survive_the_pipeline_resize_and_stay_near_the_source_ratio(self):
        for source in ((1000, 1500), (1440, 1080), (1920, 1080), (1080, 1920), (777, 1313), (1024, 1024), (3000, 1000)):
            with self.subTest(source=source):
                width, height = fixed_point_size(*source)
                self.assertEqual(dimensions(f'{width}:{height}', 1024), (width, height))
                self.assertEqual((width % 32, height % 32), (0, 0))
                self.assertLess(abs(width / height - source[0] / source[1]) / (source[0] / source[1]), .04)

    def test_exact_ratio_needs_no_crop(self):
        self.assertEqual(fixed_point_size(1000, 1500), (832, 1248))
        self.assertEqual(crop_box(1000, 1500, 832, 1248), (0.0, 0.0, 1000.0, 1500.0))

    def test_crop_box_is_centered_and_keeps_target_ratio(self):
        left, top, right, bottom = crop_box(1440, 1080, 1184, 896)
        self.assertAlmostEqual(left, 1440 - right)
        self.assertEqual((top, bottom), (0.0, 1080.0))
        self.assertAlmostEqual((right - left) / bottom, 1184 / 896)

    def test_aligned_file_has_target_size_alpha_and_exif_orientation(self):
        with tempfile.TemporaryDirectory() as temp:
            source, output = Path(temp) / 'source.jpg', Path(temp) / 'aligned.png'
            exif = Image.Exif()
            exif[0x0112] = 6
            Image.new('RGB', (1500, 1000), 'red').save(source, exif=exif)
            alignment = align_reference(source, output)
            self.assertEqual((alignment['source_width'], alignment['source_height']), (1000, 1500))
            self.assertEqual((alignment['width'], alignment['height']), (832, 1248))
            self.assertEqual(alignment['cropped_percent'], 0)
            json.dumps(alignment)
            with Image.open(output) as image:
                self.assertEqual((image.size, image.mode), ((832, 1248), 'RGBA'))


class ContractTests(unittest.TestCase):
    token = 'a' * 32

    def test_off_by_default_and_only_true_enables_it(self):
        self.assertIs(normalize_job({'prompt': 'x'})['align_reference'], False)
        job = {'prompt': 'x', 'mode': 'edit', 'reference_upload_tokens': [self.token]}
        self.assertIs(normalize_job({**job, 'align_reference': 'true'})['align_reference'], False)
        self.assertIs(normalize_job({**job, 'align_reference': True})['align_reference'], True)

    def test_requires_edit_mode_and_one_reference(self):
        for fields in ({}, {'mode': 'edit', 'reference_upload_tokens': [self.token, 'b' * 32]}):
            with self.subTest(fields=fields), self.assertRaisesRegex(ValueError, '零偏移'):
                normalize_job({'prompt': 'x', 'align_reference': True, **fields})


class SubmissionTests(unittest.TestCase):
    def run_job(self, **body):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root, tasks, captured = Path(temp.name), {}, []
        service = service_for(root, tasks, captured)
        self.addCleanup(service.close)
        token = service.upload_image(png_bytes((1440, 1080)))['upload_token']
        reply = service.submit({'prompt': 'edit', 'mode': 'edit', 'reference_upload_tokens': [token],
                                'width': 512, 'height': 512, **body})
        deadline = time.monotonic() + 4
        while tasks[reply['task_id']]['status'] != 'succeeded_no_telegram' and time.monotonic() < deadline:
            time.sleep(.02)
        return root, reply, tasks[reply['task_id']], captured[0]

    def test_aligned_job_overrides_size_and_keeps_original(self):
        root, reply, task, spec = self.run_job(align_reference=True)
        size = (reply['edit_alignment']['width'], reply['edit_alignment']['height'])
        self.assertEqual((spec['width'], spec['height']), size)
        self.assertEqual(dimensions(f'{size[0]}:{size[1]}', 1024), size)
        self.assertNotEqual(size, (512, 512))
        reference = Path(spec['references'][0])
        self.assertEqual(reference.name, 'reference_1_aligned.png')
        with Image.open(reference) as image:
            self.assertEqual(image.size, size)
        with Image.open(reference.with_name('reference_1.png')) as image:
            self.assertEqual(image.size, (1440, 1080))
        self.assertEqual(task['params']['edit_alignment'], reply['edit_alignment'])
        self.assertNotIn(str(root), json.dumps(task['params']))
        with Image.open(root / 'archive' / task['result_files'][0]) as image:
            self.assertEqual(image.size, size)

    def test_unaligned_job_is_unchanged(self):
        _, reply, task, spec = self.run_job()
        self.assertNotIn('edit_alignment', reply)
        self.assertEqual((spec['width'], spec['height']), (512, 512))
        self.assertEqual(Path(spec['references'][0]).name, 'reference_1.png')
        self.assertNotIn('edit_alignment', task['params'])


if __name__ == '__main__':
    unittest.main()

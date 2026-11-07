"""COMBO choices from ComfyUI /object_info turn exported dropdown values back into selects."""
import unittest

from backend.services import comfy_object_info as info
from backend.services import comfy_workflows

RESOLUTION = {'ResolutionSelector': {'input': {
    'required': {
        'aspect_ratio': ['COMBO', {'default': '1:1 (Square)', 'options': ['1:1 (Square)', '9:16 (Portrait Widescreen)']}],
        'megapixels': ['FLOAT', {'default': 1.0, 'min': 0.1}],
    },
    'optional': {'mode': [['fast', 'slow'], {}], 'preview': ['RESOLUTION_PREVIEW', {}]},
}}}


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, owner):
        self.owner = owner

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, timeout):
        self.owner.calls.append((url, timeout))
        if self.owner.fail:
            raise ConnectionError('offline')
        return FakeResponse(RESOLUTION)


class Harness:
    def __init__(self, fail=False):
        self.calls, self.fail, self.now = [], fail, 100.0
        self.lookup = info.ComfyOptionLookup(lambda: FakeSession(self),
                                             lambda: {'base_url': 'http://comfy:8188/', 'timeout_seconds': 30},
                                             clock=lambda: self.now)


class ComboChoicesTests(unittest.TestCase):
    def test_reads_new_and_legacy_combo_specs(self):
        self.assertEqual(info.class_combo_choices(RESOLUTION, 'ResolutionSelector'),
                         {'aspect_ratio': ['1:1 (Square)', '9:16 (Portrait Widescreen)'], 'mode': ['fast', 'slow']})
        self.assertIsNone(info.combo_choices(['INT', {'min': 1}]))
        self.assertEqual(info.class_combo_choices({}, 'Missing'), {})

    def test_lookup_caches_per_class_and_bounds_timeout(self):
        h = Harness()
        self.assertEqual(h.lookup('ResolutionSelector', 'aspect_ratio'), ['1:1 (Square)', '9:16 (Portrait Widescreen)'])
        self.assertIsNone(h.lookup('ResolutionSelector', 'megapixels'))
        self.assertEqual(h.calls, [('http://comfy:8188/object_info/ResolutionSelector', info.LOOKUP_TIMEOUT)])
        h.now += info.SUCCESS_TTL + 1
        h.lookup('ResolutionSelector', 'aspect_ratio')
        self.assertEqual(len(h.calls), 2)

    def test_offline_host_is_skipped_until_failure_ttl(self):
        h = Harness(fail=True)
        self.assertIsNone(h.lookup('ResolutionSelector', 'aspect_ratio'))
        self.assertIsNone(h.lookup('OtherNode', 'mode'))
        self.assertEqual(len(h.calls), 1)
        h.now += info.FAILURE_TTL + 1
        h.fail = False
        self.assertEqual(h.lookup('ResolutionSelector', 'mode'), ['fast', 'slow'])


class ExtractionTests(unittest.TestCase):
    WORKFLOW = {
        '115': {'class_type': 'ResolutionSelector', '_meta': {'title': '[参数]画幅质量'},
                'inputs': {'aspect_ratio': '9:16 (Portrait Widescreen)', 'megapixels': 0.5}},
        '9': {'class_type': 'SaveImage', '_meta': {'title': '[输出]'}, 'inputs': {'images': ['115', 0]}},
    }

    def extract(self, combo_options):
        return {p['id']: p for p in comfy_workflows._extract_comfy_workflow_parameters(
            self.WORKFLOW, COMFY_PARAMETER_EXCLUDED_INPUTS=set(), COMFY_PARAMETER_OPTIONS={},
            _comfy_parameter_label=lambda name: name,
            _comfy_parameter_number_bounds=lambda name, value: (0, 10, 0.01), combo_options=combo_options)}

    def test_combo_choices_make_a_select_and_offline_stays_text(self):
        params = self.extract(lambda class_type, name: ['1:1 (Square)', '9:16 (Portrait Widescreen)']
                              if (class_type, name) == ('ResolutionSelector', 'aspect_ratio') else None)
        self.assertEqual(params['115:aspect_ratio']['type'], 'select')
        self.assertEqual(params['115:aspect_ratio']['options'], ['1:1 (Square)', '9:16 (Portrait Widescreen)'])
        self.assertEqual(params['115:megapixels']['type'], 'number')
        self.assertEqual(self.extract(lambda *_: None)['115:aspect_ratio']['type'], 'text')
        self.assertEqual(self.extract(None)['115:aspect_ratio']['type'], 'text')

    def test_unlisted_current_value_is_kept_as_first_choice(self):
        params = self.extract(lambda *_: ['1:1 (Square)'])
        self.assertEqual(params['115:aspect_ratio']['options'], ['9:16 (Portrait Widescreen)', '1:1 (Square)'])


class RepairTests(unittest.TestCase):
    SPECS = {
        'CreateVideo': {'chroma_subsampling': info.combo_spec(['COMBO', {'default': 'auto', 'options': ['auto', '444', '420']}]),
                        'codec': info.combo_spec(['COMBO', {'default': 'none', 'options': ['none', 'h264']}])},
        'LoadImage': {'image': info.combo_spec([['a.png', 'b.png'], {'image_upload': True}])},
        'UNETLoader': {'unet_name': info.combo_spec([['H3\\model.safetensors'], {}])},
    }

    def test_combo_spec_flags_file_pickers_and_falls_back_to_first_choice(self):
        self.assertTrue(self.SPECS['LoadImage']['image']['files'])
        self.assertTrue(self.SPECS['UNETLoader']['unet_name']['files'])
        self.assertFalse(self.SPECS['CreateVideo']['codec']['files'])
        self.assertEqual(info.combo_spec(['COMBO', {'default': 'gone', 'options': ['x', 'y']}])['default'], 'x')
        self.assertIsNone(info.combo_spec(['FLOAT', {'default': 1.0}]))

    def test_repairs_only_rejected_enum_strings(self):
        workflow = {
            '272': {'class_type': 'CreateVideo', '_meta': {'title': '创建视频'},
                    'inputs': {'chroma_subsampling': 'none', 'codec': 'none', 'images': ['557', 0]}},
            '236': {'class_type': 'LoadImage', 'inputs': {'image': 'miniapp_upload.png'}},
            '461': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'H3\\new.safetensors'}},
            '9': {'class_type': 'Unknown', 'inputs': {'mode': 'whatever'}},
        }
        repairs = info.repair_invalid_choices(workflow, self.SPECS.get)
        self.assertEqual(repairs, [{'node_id': '272', 'title': '创建视频', 'class_type': 'CreateVideo',
                                    'input': 'chroma_subsampling', 'value': 'none', 'replacement': 'auto'}])
        self.assertEqual(workflow['272']['inputs'], {'chroma_subsampling': 'auto', 'codec': 'none', 'images': ['557', 0]})
        self.assertEqual(workflow['236']['inputs']['image'], 'miniapp_upload.png')
        self.assertEqual(workflow['461']['inputs']['unet_name'], 'H3\\new.safetensors')

    def test_offline_lookup_leaves_the_workflow_alone(self):
        workflow = {'272': {'class_type': 'CreateVideo', 'inputs': {'chroma_subsampling': 'none'}}}
        self.assertEqual(info.repair_invalid_choices(workflow, lambda _class: None), [])
        self.assertEqual(workflow['272']['inputs']['chroma_subsampling'], 'none')

    def test_run_route_repairs_before_submit_and_records_changes(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        route = (root / 'backend/routes/runtime_generation_routes.py').read_text(encoding='utf-8')
        self.assertIn('input_repairs = _repair_comfy_choices(prepared_prompt) if _repair_comfy_choices else []', route)
        self.assertLess(route.index('input_repairs = _repair_comfy_choices'), route.index("'/prompt',"))
        self.assertIn("'comfy_input_repairs': input_repairs,", route)
        server = (root / 'backend/server.py').read_text(encoding='utf-8')
        self.assertIn('repair_invalid_choices(workflow, _COMFY_OPTION_LOOKUP.class_specs)', server)
        self.assertIn('_repair_comfy_choices=_repair_comfy_choices', server)


if __name__ == '__main__':
    unittest.main()

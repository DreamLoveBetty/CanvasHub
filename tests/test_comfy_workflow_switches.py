#!/usr/bin/env python3
"""Switchable ComfyUI workflows: branch / toggle / option title tags prune the API graph per run,
audio slots, per-run seeds and unknown-tag warnings."""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import server
from backend.routes import comfy_video_routes, runtime_generation_routes
from backend.services import comfy_audio
from backend.services import comfy_workflow_switches as switches_module
from tests.test_comfy_video import FakeHandler


def _node(class_type, inputs, title=''):
    node = {'class_type': class_type, 'inputs': inputs}
    if title:
        node['_meta'] = {'title': title}
    return node


def _switchable():
    """A miniature of the H3 二采 workflow: two first-stage branches merged by rgthree Any Switch,
    an optional second pass with a step-count option group, and a first-pass fallback output."""
    any_switch = 'Any Switch (rgthree)'
    return {
        '1': _node('PrimitiveStringMultiline', {'value': 'default prompt'}, '[提示词]'),
        '2': _node('RandomNoise', {'noise_seed': 42}, '随机噪波'),
        '3': _node('Int', {'value': 8}, '[参数]步数'),
        '10': _node('MiniMaxH3ImageToVideo', {'prompt': ['1', 0]}, '[分支：文生]文生视频'),
        '11': _node('SamplerCustomAdvanced', {'noise': ['2', 0], 'latent_image': ['10', 1], 'steps': ['3', 0]}),
        '12': _node('VAEDecode', {'samples': ['11', 0]}),
        '20': _node('LoadImage', {'image': 'default_a.png'}, '[参考图1]'),
        '21': _node('LoadImage', {'image': 'default_b.png'}, '[参考图2]'),
        '22': _node('LoadAudio', {'audio': 'default.mp3'}, '[参考音频1]'),
        '23': _node('MiniMaxH3ReferenceToVideo', {'prompt': ['1', 0], 'ref_images.ref_image_0': ['20', 0],
                                                   'ref_images.ref_image_1': ['21', 0], 'ref_audios.ref_audio_0': ['22', 0]},
                    '[分支:图生]多参视频'),
        '24': _node('SamplerCustomAdvanced', {'noise': ['2', 0], 'latent_image': ['23', 1], 'steps': ['3', 0]}),
        '25': _node('VAEDecode', {'samples': ['24', 0]}),
        '30': _node(any_switch, {'any_01': ['11', 1], 'any_02': ['24', 1]}),
        '31': _node(any_switch, {'any_01': ['12', 0], 'any_02': ['25', 0]}),
        '40': _node('ManualSigmas', {'sigmas': '0.9, 0.3, 0'}, '[选项：二采步数]3步'),
        '41': _node('ManualSigmas', {'sigmas': '0.9, 0.6, 0.3, 0'}, '[选项：二采步数]4步'),
        '42': _node(any_switch, {'any_01': ['40', 0], 'any_02': ['41', 0]}),
        '43': _node('SamplerCustomAdvanced', {'noise': ['2', 0], 'sigmas': ['42', 0], 'latent_image': ['30', 0]}),
        '44': _node('SaveVideo', {'filename_prefix': 'video/final', 'video': ['43', 0]}, '[开关：二采][输出]保存视频'),
        '50': _node('VHS_VideoCombine', {'images': ['31', 0], 'filename_prefix': 'first'}),
    }


def _prepare(workflow, params=None, images=(), audios=(), report=None):
    return server._prepare_comfy_workflow(workflow, 'p', '9:16', uploaded_image_names=list(images),
                                          uploaded_audio_names=list(audios), workflow_parameters=params or {},
                                          report=report if report is not None else {})


class SwitchParsingTest(unittest.TestCase):
    def test_branches_toggles_options_and_outputs(self) -> None:
        switches = switches_module.collect_workflow_switches(_switchable())
        self.assertEqual([(item['name'], item['node_ids']) for item in switches['branches']], [('文生', ['10']), ('图生', ['23'])])
        self.assertEqual([(item['name'], item['node_ids']) for item in switches['toggles']], [('二采', ['44'])])
        self.assertEqual([choice['label'] for choice in switches['options'][0]['choices']], ['3步', '4步'])
        self.assertEqual(switches['outputs'], ['44'])
        self.assertEqual(switches['warnings'], [])

    def test_switches_are_parameters_with_defaults(self) -> None:
        parameters = {item['id']: item for item in server._extract_comfy_workflow_parameters(_switchable())}
        self.assertEqual(parameters['switch:branch']['options'], ['自动', '文生', '图生'])
        self.assertEqual(parameters['switch:toggle:二采']['type'], 'boolean')
        self.assertIs(parameters['switch:toggle:二采']['default'], True)
        self.assertEqual(parameters['switch:option:二采步数']['options'], ['3步', '4步'])
        self.assertIn('3:value', parameters, '[参数]名称 without a space is still a parameter')

    def test_lonely_branch_and_unknown_tags_warn(self) -> None:
        workflow = {'1': _node('Int', {'value': 1}, '[分支:文生]'), '2': _node('Int', {'value': 2}, '[画幅质量]'),
                    '3': _node('Int', {'value': 3}, '[参数] 时长 [输出]')}
        self.assertTrue(switches_module.collect_workflow_switches(workflow)['warnings'])
        warnings = switches_module.unknown_title_tags(workflow)
        self.assertEqual(len(warnings), 1)
        self.assertIn('[画幅质量]', warnings[0])


class SwitchPruneTest(unittest.TestCase):
    def test_auto_text_branch_with_second_pass_drops_first_pass_output(self) -> None:
        report = {}
        prepared = _prepare(_switchable(), report=report)
        self.assertEqual(sorted(prepared, key=int), ['1', '2', '3', '10', '11', '30', '40', '42', '43', '44'])
        self.assertEqual(prepared['30']['inputs'], {'any_01': ['11', 1]})
        self.assertEqual(prepared['42']['inputs'], {'any_01': ['40', 0]})
        self.assertEqual(report['switches']['switch:branch'], '自动')

    def test_auto_picks_media_branch_and_detaches_empty_slots(self) -> None:
        prepared = _prepare(_switchable(), images=['', 'up.png'], audios=['clip.mp3'])
        self.assertNotIn('10', prepared)
        self.assertNotIn('20', prepared, 'an empty slot never sends the workflow default image')
        self.assertEqual(prepared['21']['inputs']['image'], 'up.png')
        self.assertEqual(prepared['22']['inputs']['audio'], 'clip.mp3')
        self.assertEqual(sorted(key for key in prepared['23']['inputs'] if key.startswith('ref_')),
                         ['ref_audios.ref_audio_0', 'ref_images.ref_image_1'])
        self.assertEqual(prepared['30']['inputs'], {'any_02': ['24', 1]})

    def test_second_pass_off_keeps_first_pass_output_and_option_choice(self) -> None:
        prepared = _prepare(_switchable(), {'switch:toggle:二采': False, 'switch:option:二采步数': '4步'})
        self.assertIn('50', prepared)
        for node_id in ('43', '44', '40', '41', '42'):
            self.assertNotIn(node_id, prepared)
        prepared = _prepare(_switchable(), {'switch:option:二采步数': '4步'})
        self.assertEqual(prepared['42']['inputs'], {'any_02': ['41', 0]})

    def test_forced_branch_ignores_connected_media(self) -> None:
        prepared = _prepare(_switchable(), {'switch:branch': '文生'}, images=['up.png'])
        self.assertIn('10', prepared)
        self.assertNotIn('23', prepared)
        self.assertNotIn('20', prepared)

    def test_invalid_choices_fall_back_and_no_output_raises(self) -> None:
        prepared = _prepare(_switchable(), {'switch:branch': '不存在', 'switch:option:二采步数': '9步'})
        self.assertIn('10', prepared)
        self.assertEqual(prepared['42']['inputs'], {'any_01': ['40', 0]})
        workflow = {'1': _node('Int', {'value': 1}, '[参数]'), '2': _node('SaveImage', {'images': ['1', 0]}, '[开关:保存]')}
        with self.assertRaises(ValueError):
            _prepare(workflow, {'switch:toggle:保存': 'false'})

    def test_workflow_without_switches_keeps_empty_slot_defaults(self) -> None:
        workflow = {'1': _node('LoadImage', {'image': 'default.png'}, '[参考图1]'),
                    '2': _node('SaveImage', {'images': ['1', 0]})}
        self.assertEqual(_prepare(workflow)['1']['inputs']['image'], 'default.png')


class SeedTest(unittest.TestCase):
    def test_tagged_runs_draw_fresh_seeds_unless_fixed_by_parameter(self) -> None:
        report = {}
        with patch.object(server, 'random', random.Random(7)):
            prepared = _prepare(_switchable(), report=report)
        self.assertNotEqual(prepared['2']['inputs']['noise_seed'], 42)
        self.assertEqual(report['seeds'], {'2:noise_seed': prepared['2']['inputs']['noise_seed']})
        fixed = {'1': _node('KSampler', {'seed': 7, 'steps': 4}, '[参数] 采样'), '2': _node('SaveImage', {})}
        self.assertEqual(_prepare(fixed)['1']['inputs']['seed'], 7)
        fixed['1']['inputs']['seed'] = -1
        self.assertNotEqual(_prepare(fixed)['1']['inputs']['seed'], -1)
        untagged = {'1': _node('KSampler', {'seed': 7}), '2': _node('SaveImage', {})}
        self.assertEqual(_prepare(untagged)['1']['inputs']['seed'], 7, 'untagged workflows keep their seeds')


class SwitchCatalogAndRouteTest(unittest.TestCase):
    def test_catalog_reports_audio_switches_and_nine_slots(self) -> None:
        workflow = _switchable()
        for index in range(3, 10):
            workflow[str(60 + index)] = _node('LoadImage', {'image': 'x.png'}, f'[参考图{index}]')
            workflow['23']['inputs'][f'ref_images.ref_image_{index - 1}'] = [str(60 + index), 0]
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'h3.json').write_text(json.dumps(workflow, ensure_ascii=False), encoding='utf-8')
            with patch.object(server, 'COMFY_WORKFLOW_DIR', Path(tmp)), \
                    patch.object(server, '_comfy_workflow_catalog_settings', lambda: {}):
                item = server._collect_comfy_workflows(include_disabled=True)['items'][0]
        self.assertEqual(item['max_images'], 9)
        self.assertTrue(item['accepts_audio'])
        self.assertEqual(item['max_audios'], 1)
        self.assertTrue(item['switchable'])
        self.assertEqual(item['summary'], '文生 / 图生 · 可切换')
        self.assertEqual([slot['key'] for slot in item['input_slots']][-1], 'audio:1')

    def test_route_passes_audios_and_records_switches_and_seeds(self) -> None:
        created, submitted = [], []
        item = {'id': 'h3.json', 'enabled': True, 'tag_mode': 'tags', 'accepts_text': True, 'accepts_image': True,
                'max_images': 2, 'accepts_video': False, 'accepts_audio': True, 'max_audios': 1,
                'output_kind': 'video', 'output_count': 1}
        handler = FakeHandler({'workflow': 'h3.json', 'prompt': 'p', 'images': ['', ''], 'audios': ['miniapp_1_a.mp3'],
                               'workflow_parameters': {'switch:toggle:二采': False}})
        runtime_generation_routes.handle_comfy_run(
            handler,
            COMFY_CLIENT_ID='test', COMFY_RESOLUTION_LONG_EDGES={'1k': 1024},
            _apply_comfy_parameter_overrides=server._apply_comfy_parameter_overrides,
            _coerce_bool=server._coerce_bool,
            _collect_comfy_workflows=lambda include_disabled=False: {'items': [item]},
            _comfy_ratio_from_size=lambda w, h: '1:1',
            _load_comfy_workflow=lambda name: (_switchable(), name),
            _normalize_comfy_dimension=server._normalize_comfy_dimension,
            _prepare_comfy_workflow=server._prepare_comfy_workflow,
            _proxy_comfy_json=lambda method, path, payload=None: submitted.append(payload) or {'prompt_id': 'pid-1'},
            _resolve_comfy_size=lambda ratio, resolution: (1024, 1024),
            _upload_comfy_image=lambda data: 'unused.png',
            create_task=lambda *args, **kwargs: created.append((args, kwargs)),
            json=json, process_comfy_task=lambda *args: None, uuid=__import__('uuid'),
        )
        self.assertEqual(handler.responses[0][0], 200, handler.responses)
        workflow = submitted[0]['prompt']
        self.assertEqual(workflow['22']['inputs']['audio'], 'miniapp_1_a.mp3')
        self.assertIn('50', workflow)
        self.assertNotIn('44', workflow)
        params = created[0][0][2]
        self.assertEqual(params['comfy_uploaded_audios'], ['miniapp_1_a.mp3'])
        self.assertIs(params['workflow_parameters']['switch:toggle:二采'], False)
        self.assertIn('2:noise_seed', params['workflow_parameters'])

    def test_route_rejects_audio_names_not_from_upload(self) -> None:
        with self.assertRaises(ValueError):
            comfy_audio.normalize_audio_input_names(['../secret.mp3'], 1)
        with self.assertRaises(ValueError):
            comfy_audio.normalize_audio_input_names(['clip.exe'], 1)
        self.assertEqual(comfy_audio.normalize_audio_input_names(['', 'a.wav'], 1), [''])


class AudioUploadTest(unittest.TestCase):
    def test_container_is_sniffed_from_header(self) -> None:
        self.assertEqual(comfy_audio.audio_suffix(b'ID3\x04' + b'\0' * 20), '.mp3')
        self.assertEqual(comfy_audio.audio_suffix(b'\xff\xfb\x90\x00' + b'\0' * 20), '.mp3')
        self.assertEqual(comfy_audio.audio_suffix(b'RIFF\0\0\0\0WAVEfmt '), '.wav')
        self.assertEqual(comfy_audio.audio_suffix(b'fLaC' + b'\0' * 8), '.flac')
        self.assertEqual(comfy_audio.audio_suffix(b'OggS' + b'\0' * 8), '.ogg')
        self.assertEqual(comfy_audio.audio_suffix(b'\0\0\0\x20ftypM4A '), '.m4a')
        with self.assertRaises(ValueError):
            comfy_audio.audio_suffix(b'<html>not audio')

    def test_upload_route_is_registered_and_protected(self) -> None:
        class Uploads:
            def upload(self, data, name=''):
                return {'name': f'stored_{name}'}
        router = comfy_video_routes.create_router(Uploads(), Uploads())
        self.assertIn(('POST', '/api/comfy/upload_audio'), router._routes)
        self.assertIn(('POST', '/api/comfy/upload_video'), router._routes)
        self.assertNotIn(('POST', '/api/comfy/upload_audio'), comfy_video_routes.create_router(Uploads())._routes)


if __name__ == '__main__':
    unittest.main()

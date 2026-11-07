#!/usr/bin/env python3
"""ComfyUI title tags: authors declare canvas inputs in node titles; tagged workflows are strict."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend import agent_runtime, server
from backend.routes import runtime_generation_routes
from backend.services import comfy_workflow_tags as tags_module
from tests.test_comfy_video import FakeHandler


def setUpModule():
    # Parameter extraction asks ComfyUI for dropdown choices; keep these tests off the network.
    patcher = patch.object(server, '_COMFY_OPTION_LOOKUP', Mock(return_value=None, **{'class_specs.return_value': None}))
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def _node(class_type, inputs, title=''):
    node = {'class_type': class_type, 'inputs': inputs}
    if title:
        node['_meta'] = {'title': title}
    return node


TAGGED = {
    '1': _node('CLIPTextEncode', {'text': 'a quiet harbor at dawn', 'clip': ['9', 0]}, '[提示词] 正向'),
    '2': _node('CLIPTextEncode', {'text': 'blurry, watermark', 'clip': ['9', 0]}, '【負面】'),
    '3': _node('EmptyLatentImage', {'width': 832, 'height': 1216, 'batch_size': 1}, '[尺寸] Latent'),
    '4': _node('KSampler', {'steps': 28, 'cfg': 4.5, 'seed': 7, 'model': ['9', 0]}, '[參數] 採樣'),
    '5': _node('LoadImage', {'image': 'second.png'}, '[参考图2]'),
    '6': _node('LoadImage', {'image': 'first.png'}, '[image1] main'),
    '7': _node('LoadImage', {'image': 'fixed_mask.png'}, '遮罩'),
    '8': _node('ImageScale', {'width': 512, 'height': 512, 'upscale_method': 'lanczos'}),
    '10': _node('EditTextEncode', {'prompt': 'keep me'}),
    '11': _node('SaveImage', {'filename_prefix': 'out'}),
}


class TitleTagParsingTest(unittest.TestCase):
    def test_aliases_brackets_and_indexes(self) -> None:
        self.assertEqual(tags_module.title_tags('[提示词] 正向'), [('prompt', None)])
        self.assertEqual(tags_module.title_tags('【負面】'), [('negative', None)])
        self.assertEqual(tags_module.title_tags('[Size][param] latent'), [('size', None), ('param', None)])
        self.assertEqual(tags_module.title_tags('[参考图2]'), [('image', 2)])
        self.assertEqual(tags_module.title_tags('KSampler [steps]'), [])
        self.assertEqual(tags_module.strip_title_tags('[參數]  採樣 [尺寸]'), '採樣')

    def test_reference_video_alias_and_index_order(self) -> None:
        self.assertEqual(tags_module.title_tags('[参考视频1]'), [('video', 1)])
        self.assertEqual(tags_module.title_tags('【參考視頻2】 側面'), [('video', 2)])
        workflow = {
            '7': _node('VHS_LoadVideo', {'video': 'b.mp4', 'frame_load_cap': 0}, '[参考视频2] 背面'),
            '9': _node('VHS_LoadVideo', {'video': 'a.mp4', 'frame_load_cap': 0}, '[参考视频1]'),
        }
        summary, tags = tags_module.workflow_tag_summary(workflow)
        self.assertEqual(summary['tag_mode'], 'tags')
        self.assertEqual(tags['videos'], ['9', '7'])
        self.assertEqual(summary['input_slots'], [{'key': 'video:1', 'kind': 'video', 'label': '视频1'},
                                                  {'key': 'video:2', 'kind': 'video', 'label': '视频2 · 背面'}])

    def test_targets_order_and_warnings(self) -> None:
        tags = tags_module.collect_workflow_tags(TAGGED)
        self.assertTrue(tags['tagged'])
        self.assertEqual([item['node_id'] for item in tags['prompt']], ['1'])
        self.assertEqual(tags['size'], ['3'])
        self.assertEqual(tags['images'], ['6', '5'])
        self.assertEqual(tags['params'], ['4'])
        self.assertEqual(len(tags['warnings']), 1)
        self.assertIn('#7', tags['warnings'][0])

    def test_unusable_targets_warn(self) -> None:
        workflow = {
            '1': _node('CLIPTextEncode', {'text': ['5', 0]}, '[提示词]'),
            '2': _node('EmptyLTXVLatentVideo', {'width': ['5', 0], 'height': ['5', 1]}, '[尺寸]'),
            '3': _node('KSampler', {'steps': 4}, '[视频]'),
        }
        tags = tags_module.collect_workflow_tags(workflow)
        self.assertEqual((tags['prompt'], tags['size'], tags['videos']), ([], [], []))
        self.assertEqual(len(tags['warnings']), 3)

    def test_untagged_workflow_stays_auto(self) -> None:
        summary, tags = tags_module.workflow_tag_summary({'1': _node('KSampler', {'steps': 4}, 'KSampler')})
        self.assertFalse(tags['tagged'])
        self.assertEqual(summary, {'tag_mode': 'auto', 'default_prompt': '', 'size_editable': True, 'tag_warnings': [],
                                   'accepts_negative': False, 'input_slots': []})

    def test_slots_are_ordered_and_labelled(self) -> None:
        summary, _tags = tags_module.workflow_tag_summary(TAGGED)
        self.assertTrue(summary['accepts_negative'])
        self.assertEqual(summary['input_slots'], [
            {'key': 'image:1', 'kind': 'image', 'label': '参考图1 · main'},
            {'key': 'image:2', 'kind': 'image', 'label': '参考图2'},
        ])
        video = {'1': _node('LoadVideo', {'file': 'a.mp4'}, '[视频] 源')}
        self.assertEqual(tags_module.workflow_tag_summary(video)[0]['input_slots'],
                         [{'key': 'video:1', 'kind': 'video', 'label': '视频 · 源'}])


class TaggedPrepareTest(unittest.TestCase):
    def test_only_tagged_nodes_are_written(self) -> None:
        prepared = server._prepare_comfy_workflow(TAGGED, 'neon street', '1:1', uploaded_image_names=['a.png', 'b.png'],
                                                  width=1024, height=768)
        self.assertEqual(prepared['1']['inputs']['text'], 'neon street')
        self.assertEqual(prepared['2']['inputs']['text'], 'blurry, watermark')
        self.assertEqual((prepared['3']['inputs']['width'], prepared['3']['inputs']['height']), (1024, 768))
        self.assertEqual(prepared['8']['inputs']['width'], 512, 'untagged size inputs are fixed')
        self.assertEqual(prepared['10']['inputs']['prompt'], 'keep me', 'untagged prompt fields are fixed')
        self.assertEqual(prepared['6']['inputs']['image'], 'a.png')
        self.assertEqual(prepared['5']['inputs']['image'], 'b.png')
        self.assertEqual(prepared['7']['inputs']['image'], 'fixed_mask.png')

    def test_empty_prompt_keeps_default_and_tokens_compose(self) -> None:
        prepared = server._prepare_comfy_workflow(TAGGED, '', '1:1')
        self.assertEqual(prepared['1']['inputs']['text'], 'a quiet harbor at dawn')
        composed = {'1': _node('CLIPTextEncode', {'text': 'masterpiece, {{PROMPT}}'}, '[提示词]')}
        self.assertEqual(server._prepare_comfy_workflow(composed, 'cat', '1:1')['1']['inputs']['text'], 'masterpiece, cat')

    def test_negative_prompt_and_empty_slots(self) -> None:
        prepared = server._prepare_comfy_workflow(TAGGED, 'p', '1:1', uploaded_image_names=['', 'b.png'],
                                                  negative_prompt='lowres')
        self.assertEqual(prepared['2']['inputs']['text'], 'lowres')
        self.assertEqual(prepared['6']['inputs']['image'], 'first.png', 'an empty slot keeps the workflow value')
        self.assertEqual(prepared['5']['inputs']['image'], 'b.png')
        kept = server._prepare_comfy_workflow(TAGGED, 'p', '1:1', uploaded_image_names=['a.png'])
        self.assertEqual(kept['5']['inputs']['image'], 'second.png', 'missing slots are not filled by repetition')
        self.assertEqual(server._prepare_comfy_workflow(TAGGED, 'p', '1:1')['2']['inputs']['text'], 'blurry, watermark')

    def test_tagged_video_loader_only(self) -> None:
        workflow = {
            '1': _node('VHS_LoadVideo', {'video': 'src.mp4'}, '[视频]'),
            '2': _node('LoadVideo', {'file': 'guide.mp4'}),
            '3': _node('SaveVideo', {'filename_prefix': 'v'}),
        }
        prepared = server._prepare_comfy_workflow(workflow, 'p', '1:1', uploaded_video_names=['up.mp4'])
        self.assertEqual(prepared['1']['inputs']['video'], 'up.mp4')
        self.assertEqual(prepared['2']['inputs']['file'], 'guide.mp4')

    def test_untagged_workflow_keeps_auto_fill(self) -> None:
        workflow = {'1': _node('EmptyLatentImage', {'width': 512, 'height': 512}),
                    '2': _node('Edit', {'prompt': 'x'}), '3': _node('LoadImage', {'image': 'p.png'})}
        prepared = server._prepare_comfy_workflow(workflow, 'cat', '1:1', uploaded_image_names=['u.png'], width=640, height=640)
        self.assertEqual(prepared['1']['inputs']['width'], 640)
        self.assertEqual(prepared['2']['inputs']['prompt'], 'cat')
        self.assertEqual(prepared['3']['inputs']['image'], 'u.png')


class TaggedCatalogTest(unittest.TestCase):
    def _items(self, workflows, meta=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, workflow in workflows.items():
                (root / name).write_text(json.dumps(workflow, ensure_ascii=False), encoding='utf-8')
            with patch.object(server, 'COMFY_WORKFLOW_DIR', root), \
                    patch.object(server, '_comfy_workflow_catalog_settings', return_value=meta or {}):
                return {item['id']: item for item in server._collect_comfy_workflows(include_disabled=True)['items']}

    def test_catalog_fields_parameters_and_size(self) -> None:
        item = self._items({'tagged.json': TAGGED})['tagged.json']
        self.assertEqual(item['tag_mode'], 'tags')
        self.assertEqual(item['default_prompt'], 'a quiet harbor at dawn')
        self.assertTrue(item['size_editable'])
        self.assertEqual((item['default_width'], item['default_height']), (832, 1216))
        self.assertTrue(item['accepts_text'] and item['accepts_image'])
        self.assertEqual(item['max_images'], 2)
        self.assertEqual(len(item['tag_warnings']), 1)
        params = {parameter['id']: parameter for parameter in item['parameters']}
        self.assertEqual(set(params), {'2:text', '4:steps', '4:cfg', '4:seed'})
        self.assertEqual(params['2:text']['label'], '负面提示词')
        self.assertEqual(params['4:steps']['node_title'], '採樣')

    def test_ui_format_workflow_is_flagged_and_refused(self) -> None:
        ui = {'id': 'x', 'nodes': [{'id': 93, 'type': 'CLIPTextEncode', 'title': '[提示词]', 'widgets_values': ['p']}],
              'links': []}
        items = self._items({'ui.json': ui, 'tagged.json': TAGGED})
        self.assertIn('导出 (API)', items['ui.json']['format_error'])
        self.assertTrue(items['ui.json']['summary'].startswith('UI 格式'))
        self.assertEqual((items['ui.json']['parameters'], items['ui.json']['input_slots']), ([], []))
        self.assertEqual(items['tagged.json']['format_error'], '')
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'ui.json').write_text(json.dumps(ui), encoding='utf-8')
            with patch.object(server, 'COMFY_WORKFLOW_DIR', Path(tmp)), self.assertRaisesRegex(ValueError, '导出 \\(API\\)'):
                server._load_comfy_workflow('ui.json')

    def test_negative_override_applies_through_tagged_schema(self) -> None:
        workflow, applied = server._apply_comfy_parameter_overrides(json.loads(json.dumps(TAGGED)),
                                                                    {'2:text': 'lowres', '8:width': 99})
        self.assertEqual(applied, {'2:text': 'lowres'})
        self.assertEqual(workflow['2']['inputs']['text'], 'lowres')

    def test_size_locked_and_text_optional_when_untagged(self) -> None:
        workflow = {
            '1': _node('VHS_LoadVideo', {'video': 'src.mp4'}, '[视频]'),
            '2': _node('EmptyLTXVLatentVideo', {'width': ['1', 0], 'height': ['1', 1]}),
            '3': _node('SaveVideo', {'filename_prefix': 'v'}),
        }
        item = self._items({'ltx.json': workflow}, {'ltx.json': {'default_ratio': '1:1'}})['ltx.json']
        self.assertFalse(item['size_editable'])
        self.assertFalse(item['accepts_text'])
        self.assertTrue(item['accepts_video'])
        self.assertEqual(item['default_prompt'], '')

    def test_catalog_reports_slots_and_negative(self) -> None:
        item = self._items({'tagged.json': TAGGED})['tagged.json']
        self.assertTrue(item['accepts_negative'])
        self.assertEqual([slot['key'] for slot in item['input_slots']], ['image:1', 'image:2'])
        auto = self._items({'auto.json': {'1': _node('KSampler', {'steps': 4})}})['auto.json']
        self.assertFalse(auto['accepts_negative'])
        self.assertEqual(auto['input_slots'], [])

    def test_settings_override_still_wins(self) -> None:
        item = self._items({'t.json': TAGGED}, {'t.json': {'accepts_text': False, 'max_images': 1}})['t.json']
        self.assertFalse(item['accepts_text'])
        self.assertEqual(item['max_images'], 1)


class TaggedRunRouteTest(unittest.TestCase):
    def run_route(self, body, item, workflow=TAGGED):
        created, submitted, uploads = [], [], []
        handler = FakeHandler(body)
        runtime_generation_routes.handle_comfy_run(
            handler,
            COMFY_CLIENT_ID='test', COMFY_RESOLUTION_LONG_EDGES={'1k': 1024},
            _apply_comfy_parameter_overrides=lambda wf, overrides: (wf, {}),
            _coerce_bool=server._coerce_bool,
            _collect_comfy_workflows=lambda include_disabled=False: {'items': [item]},
            _comfy_ratio_from_size=lambda w, h: '1:1',
            _load_comfy_workflow=lambda name: (json.loads(json.dumps(workflow)), name),
            _normalize_comfy_dimension=server._normalize_comfy_dimension,
            _prepare_comfy_workflow=server._prepare_comfy_workflow,
            _proxy_comfy_json=lambda method, path, payload=None: submitted.append(payload) or {'prompt_id': 'pid-1'},
            _resolve_comfy_size=lambda ratio, resolution: (1024, 1024),
            _upload_comfy_image=lambda data: uploads.append(data) or f'up{len(uploads)}.png',
            create_task=lambda *args, **kwargs: created.append((args, kwargs)),
            json=json, process_comfy_task=lambda *args: None, uuid=__import__('uuid'),
        )
        return handler, created, submitted, uploads

    ITEM = {'id': 'tagged.json', 'enabled': True, 'tag_mode': 'tags', 'accepts_text': True, 'accepts_image': True,
            'max_images': 2, 'accepts_video': False, 'accepts_negative': True, 'output_kind': 'image', 'output_count': 1}

    def test_slots_keep_positions_and_negative_is_recorded(self) -> None:
        _handler, created, submitted, uploads = self.run_route(
            {'workflow': 'tagged.json', 'prompt': 'p', 'images': ['', 'data:b'], 'negative_prompt': ' lowres '}, self.ITEM)
        self.assertEqual(uploads, ['data:b'])
        workflow = submitted[0]['prompt']
        self.assertEqual(workflow['6']['inputs']['image'], 'first.png')
        self.assertEqual(workflow['5']['inputs']['image'], 'up1.png')
        self.assertEqual(workflow['2']['inputs']['text'], 'lowres')
        params = created[0][0][2]
        self.assertEqual(params['negative_prompt'], 'lowres')
        self.assertEqual(params['comfy_uploaded_images'], ['', 'up1.png'])

    def test_tagged_workflow_runs_without_any_slot_filled(self) -> None:
        handler, created, _submitted, uploads = self.run_route({'workflow': 'tagged.json', 'prompt': 'p'}, self.ITEM)
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(uploads, [])
        self.assertEqual(len(created), 1)

    def test_negative_is_dropped_without_negative_tag(self) -> None:
        item = {**self.ITEM, 'accepts_negative': False}
        _handler, created, submitted, _uploads = self.run_route(
            {'workflow': 'tagged.json', 'prompt': 'p', 'negative_prompt': 'x'}, item)
        self.assertEqual(created[0][0][2]['negative_prompt'], '')
        self.assertEqual(submitted[0]['prompt']['2']['inputs']['text'], 'blurry, watermark')


class PromptAgentRoleTest(unittest.TestCase):
    def test_negative_text_nodes_are_not_the_agent_prompt(self) -> None:
        canvas = {
            'nodes': {
                'input': {'id': 'input', 'type': 'input'},
                'neg': {'id': 'neg', 'type': 'text', 'text': 'blurry', 'promptRole': 'negative'},
                'pos': {'id': 'pos', 'type': 'text', 'text': 'harbor at dawn'},
            },
            'edges': [{'from': 'neg', 'to': 'input'}, {'from': 'pos', 'to': 'input'}],
        }
        summary = agent_runtime.summarize_context({'canvas': canvas, 'result_node_id': 'input'})
        self.assertEqual(summary['connected_text_node_id'], 'pos')
        self.assertEqual(summary['current_prompt'], 'harbor at dawn')


if __name__ == '__main__':
    unittest.main()

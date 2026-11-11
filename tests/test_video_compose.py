"""Video compose (phases 2–3b): recipe contract, pure planning, subtitles, durable jobs, real renders, HTTP routes.

Synthetic fixtures only: clips and music are rendered by the local FFmpeg into a temp directory;
sources, the audio archive and the sidecar writer are fakes. FFmpeg-dependent cases skip without it.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from backend import asset_index
from backend.routes.video_edit_routes import create_router
from backend.video_edit import contracts, media, plan, subtitles
from backend.video_edit.compose import ComposeService
from backend.video_edit.service import VideoEditService
from backend.video_edit.sources import AudioSourceResolver, UnsupportedSource
from backend.video_edit.storage import ComposeStore

FFMPEG, FFPROBE = media.locate('ffmpeg'), media.locate('ffprobe')
HAS_FFMPEG = bool(FFMPEG and FFPROBE)


def system_font():
    try:
        return subtitles.font_path(None)
    except RuntimeError:
        return None


FONT = system_font()


def render(target: Path, *args):
    subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-v', 'error', *args, '-y', str(target)], check=True)
    return target


def streams(path: Path) -> dict:
    raw = subprocess.run([FFPROBE, '-v', 'error', '-show_entries', 'stream=codec_type,width,height,nb_frames,duration',
                          '-of', 'json', str(path)], check=True, capture_output=True).stdout
    return {item['codec_type']: item for item in json.loads(raw)['streams']}


def frame_colours(path: Path, crop: str) -> list[tuple[int, int, int]]:
    raw = subprocess.run([FFMPEG, '-v', 'error', '-i', str(path), '-vf', f'crop={crop},scale=1:1', '-f', 'rawvideo',
                          '-pix_fmt', 'rgb24', '-'], check=True, capture_output=True).stdout
    return [tuple(raw[index:index + 3]) for index in range(0, len(raw), 3)]


def info(count=60, fps=30.0, offset=0.0, audio=True):
    times = [round(index / fps, 6) for index in range(count)]
    return {'width': 320, 'height': 240, 'fps': fps, 'duration_seconds': count / fps, 'frame_count': count,
            'frame_times': times, 'pts': [value + offset for value in times],
            'audio': {'codec': 'aac'} if audio else None}


def clip(url='/video/a.mp4', **extra):
    return {'source_url': url, **extra}


class ContractTests(unittest.TestCase):
    def test_defaults_and_normalised_fields(self):
        request = contracts.compose_request({'clips': [clip(start_frame=3, end_frame=-1, audio=False)],
                                             'output': {'resolution': 720.0, 'fps': 24}, 'title': 'x' * 200})
        self.assertEqual(request['clips'], [{'source_url': '/video/a.mp4', 'source_name': '', 'start_frame': 3,
                                             'end_frame': -1, 'audio': False, 'speed': 1.0,
                                             'transition': {'type': 'none', 'duration': 0.5}}])
        self.assertEqual(request['output'], {'aspect': 'source', 'resolution': 720, 'fps': 24, 'fit': 'crop',
                                             'encoder': 'quality'})
        self.assertEqual((request['clip_volume'], request['music'], len(request['title'])), (1, None, 80))

    def test_rejects_bad_recipes(self):
        bad = [
            {}, {'clips': []}, {'clips': [clip()] * (contracts.MAX_CLIPS + 1)}, {'clips': ['x']},
            {'clips': [clip(start_frame=-1)]}, {'clips': [clip(start_frame=1.5)]}, {'clips': [clip(end_frame=True)]},
            {'clips': [clip()], 'output': {'aspect': '21:9'}}, {'clips': [clip()], 'output': {'resolution': 4000}},
            {'clips': [clip()], 'output': {'fit': 'stretch'}}, {'clips': [clip()], 'clip_volume': 3},
            {'clips': [clip()], 'music': {'source_url': '/a.m4a', 'asset_id': 'a' * 64 + '.wav'}},
            {'clips': [clip()], 'music': {}}, {'clips': [clip()], 'music': {'asset_id': '../x.wav'}},
            {'clips': [clip()], 'music': {'asset_id': 'a' * 64 + '.wav', 'fade_in': 11}}, {'clips': [clip(source_url='')]},
        ]
        for body in bad:
            with self.subTest(body=body):
                if body.get('music') == {}:
                    self.assertIsNone(contracts.compose_request(body)['music'])
                    continue
                with self.assertRaises(ValueError):
                    contracts.compose_request(body)

    def test_speed_and_transition_choices(self):
        request = contracts.compose_request({'clips': [clip(speed=2, transition={'type': 'fadeblack', 'duration': 1}),
                                                       clip(speed=0.75, transition={'type': 'fade'})]})
        first, last = request['clips']
        self.assertEqual((first['speed'], first['transition']), (2.0, {'type': 'fadeblack', 'duration': 1.0}))
        self.assertEqual((last['speed'], last['transition']), (0.75, {'type': 'none', 'duration': 0.5}),
                         'the last clip has no next clip to transition into')
        for bad in ({'speed': 3}, {'speed': True}, {'speed': '2'}, {'transition': {'type': 'spin'}},
                    {'transition': {'type': 'fade', 'duration': 0.7}}, {'transition': 'fade'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                contracts.compose_request({'clips': [clip(**bad), clip()]})

    def test_music_defaults(self):
        music = contracts.compose_request({'clips': [clip()], 'music': {'asset_id': 'a' * 64 + '.m4a'}})['music']
        self.assertEqual(music, {'source_url': '', 'asset_id': 'a' * 64 + '.m4a', 'source_name': '', 'volume': 0.8,
                                 'fade_in': 0, 'fade_out': 1.5})


class SubtitleContractTests(unittest.TestCase):
    def test_cues_are_trimmed_sorted_and_styled(self):
        self.assertIsNone(contracts.subtitles_request(None))
        self.assertIsNone(contracts.subtitles_request({'cues': [], 'style': {'size': 'large'}}))
        parsed = contracts.subtitles_request({'cues': [{'start': 2, 'end': 3.25, 'text': ' 第二句 \r\n second '},
                                                       {'start': 0, 'end': 1.5, 'text': '第一句'}],
                                              'style': {'size': 'large', 'position': 'top', 'look': 'box', 'font': '思源宋体.ttc'}})
        self.assertEqual(parsed['cues'], [{'start': 0.0, 'end': 1.5, 'text': '第一句'},
                                          {'start': 2.0, 'end': 3.25, 'text': '第二句\nsecond'}])
        self.assertEqual(parsed['style'], {'size': 'large', 'position': 'top', 'look': 'box', 'font': '思源宋体.ttc'})
        self.assertEqual(contracts.subtitles_request({'cues': [{'start': 0, 'end': 1, 'text': 'a'}]})['style'],
                         contracts.SUBTITLE_DEFAULTS)
        self.assertIsNone(contracts.compose_request({'clips': [clip()]})['subtitles'])

    def test_rejects_bad_cues_and_fonts(self):
        cue = {'start': 0, 'end': 1, 'text': '字幕'}
        bad = [{'cues': 'x'}, {'cues': [cue] * 101}, {'cues': [dict(cue, text='  ')]},
               {'cues': [dict(cue, text='字' * 81)]}, {'cues': [dict(cue, end=0.2)]},
               {'cues': [dict(cue, start=-1)]}, {'cues': [dict(cue, start=True)]}, {'cues': [dict(cue, end=181)]},
               {'cues': [cue, dict(cue, start=0.5, end=2)]}, {'cues': [cue], 'style': {'look': 'glow'}},
               {'cues': [cue], 'style': {'font': '../secret.ttf'}}, {'cues': [cue], 'style': {'font': 'a.woff2'}}]
        for value in bad:
            with self.subTest(value=str(value)[:60]), self.assertRaises(ValueError):
                contracts.subtitles_request(value)
        self.assertEqual(len(contracts.subtitles_request({'cues': [cue, dict(cue, start=1, end=2)]})['cues']), 2,
                         'touching cues do not overlap')


class SubtitleLayoutTests(unittest.TestCase):
    def test_wrap_breaks_cjk_anywhere_and_latin_between_words(self):
        measure = len  # one unit per character
        self.assertEqual(subtitles.wrap('一二三四五六七', measure, 3), ['一二三', '四五六', '七'])
        self.assertEqual(subtitles.wrap('hello big world', measure, 9), ['hello big', 'world'])
        self.assertEqual(subtitles.wrap('上\n下', measure, 9), ['上', '下'])
        self.assertEqual(subtitles.wrap('abcdefghij', measure, 4), ['abcd', 'efgh', 'ij'])
        self.assertEqual(subtitles.wrap('中文 and English', measure, 6), ['中文 and', 'Englis', 'h'])
        self.assertEqual(subtitles.wrap('一二三，四', measure, 3), ['一二三，', '四'], 'punctuation never starts a line')

    def test_metrics_follow_the_short_side(self):
        portrait = subtitles.metrics({'size': 'medium'}, 1080, 1920)
        self.assertEqual((portrait['size'], portrait['margin'], portrait['wrap']), (59, 154, 929))
        self.assertEqual(subtitles.metrics({'size': 'large'}, 1280, 720)['size'], 50)

    def test_catalog_lists_native_fonts_with_a_web_preview(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('B.ttf', 'a.ttc', 'a.woff2', 'web-only.woff2', 'notes.txt'):
                (root / name).write_bytes(b'x')
            (root / 'sub').mkdir()
            self.assertEqual(subtitles.catalog(root), [{'file': 'a.ttc', 'label': 'a', 'url': '/font/a.woff2'},
                                                       {'file': 'B.ttf', 'label': 'B', 'url': '/font/B.ttf'}])
            self.assertEqual(subtitles.font_path(root, 'B.ttf'), (root / 'B.ttf').resolve())
            for name in ('missing.ttf', '../B.ttf', 'a.woff2', 'notes.txt'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    subtitles.font_path(root, name)
        self.assertEqual(subtitles.catalog(None), [])

    def test_srt_sidecar_format(self):
        self.assertEqual(subtitles.srt([{'start': 0, 'end': 1.5, 'text': '你好'}, {'start': 61.25, 'end': 3725.004, 'text': 'a\nb'}]),
                         '1\n00:00:00,000 --> 00:00:01,500\n你好\n\n2\n00:01:01,250 --> 01:02:05,004\na\nb\n')

    @unittest.skipUnless(FONT, 'no CJK font on this machine')
    def test_layout_rejects_long_cues_and_renders_centred_pngs(self):
        style = {'size': 'medium', 'position': 'bottom', 'look': 'box'}
        with self.assertRaisesRegex(ValueError, '第 1 条字幕太长'):
            subtitles.Layout([{'start': 0, 'end': 1, 'text': '很长的字幕' * 16}], style, width=720, height=720, font_file=FONT)
        layout = subtitles.Layout([{'start': 0, 'end': 1, 'text': '你好 world'}], dict(style, position='top'),
                                  width=720, height=1280, font_file=FONT)
        with tempfile.TemporaryDirectory() as folder:
            from PIL import Image
            [item] = layout.render(Path(folder))
            image = Image.open(item['path'])
            self.assertEqual(image.mode, 'RGBA')
            self.assertEqual(item['y'], round(1280 * subtitles.MARGIN))
            self.assertLessEqual(abs(item['x'] * 2 + image.width - 720), 1, 'horizontally centred')
            self.assertEqual(image.getpixel((2, image.height // 2))[3], subtitles.BOX_ALPHA, 'box fill')


class PlanTests(unittest.TestCase):
    def test_output_size_keeps_short_side_and_even_dimensions(self):
        self.assertEqual(plan.output_size('16:9', 1080, 1, 1), (1920, 1080))
        self.assertEqual(plan.output_size('9:16', 720, 1, 1), (720, 1280))
        self.assertEqual(plan.output_size('4:5', 1080, 1, 1), (1080, 1350))
        self.assertEqual(plan.output_size('1:1', 720, 1, 1), (720, 720))
        self.assertEqual(plan.output_size('source', 720, 736, 1280), (720, 1252))
        self.assertEqual(plan.output_size('source', 1080, 4000, 500), (3840, 480))

    def test_clip_window_is_frame_exact(self):
        source = info(offset=1.5)
        window = plan.clip_window(source, 30, 44)
        self.assertEqual((window['frames'], window['seconds'], window['start_time']), (15, 0.5, 1.0))
        midpoint = (source['pts'][29] + source['pts'][30]) / 2
        self.assertEqual(window['seek'], ['-seek_timestamp', '1', '-ss', f'{midpoint:.6f}'])
        last = plan.clip_window(info(), 0, -1)
        self.assertEqual((last['end_frame'], last['frames'], last['seek']), (59, 60, []))
        self.assertAlmostEqual(last['seconds'], 2.0, places=5)
        for start, end in ((10, 5), (0, 60), (60, -1), (0, 10)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                plan.clip_window(info(), start, end)

    def test_filter_graph_fits_pads_silence_and_music(self):
        clips = [{'frames': 30, 'seconds': 1.0, 'audio': True}, {'frames': 48, 'seconds': 2.0, 'audio': False}]
        graph, total = plan.filter_graph(clips, None, width=720, height=1280, fps=30, fit='crop', clip_volume=1)
        self.assertEqual(total, 3.0)
        self.assertIn('[0:v:0]trim=end_frame=30,setpts=PTS-STARTPTS,scale=720:1280:force_original_aspect_ratio=increase,'
                      'crop=720:1280[vf0]', graph)
        self.assertIn('apad,atrim=duration=1.000000[a0]', graph)
        self.assertIn('anullsrc=r=48000:cl=stereo,atrim=duration=2.000000', graph)
        self.assertIn('[v0][a0][v1][a1]concat=n=2:v=1:a=1[vout][acat]', graph)
        self.assertTrue(graph.endswith('[acat]anull[aout]'))
        padded, _ = plan.filter_graph(clips[:1], None, width=720, height=720, fps=24, fit='pad', clip_volume=1.5)
        self.assertIn('pad=720:720:(ow-iw)/2:(oh-ih)/2:color=black', padded)
        self.assertIn('volume=1.5[a0]', padded)
        self.assertTrue(padded.endswith('[acat]alimiter=limit=0.97:level=0[aout]'))
        blurred, _ = plan.filter_graph(clips[:1], None, width=1080, height=1920, fps=30, fit='blur', clip_volume=1)
        self.assertIn('split=2[bg0][fg0]', blurred)
        self.assertIn('boxblur=8:2,scale=1080:1920[bgs0]', blurred)
        music = {'input': 2, 'volume': 0.5, 'fade_in': 1, 'fade_out': 2, 'duration': 2.5}
        mixed, _ = plan.filter_graph(clips, music, width=720, height=1280, fps=30, fit='crop', clip_volume=1)
        self.assertIn('[2:a:0]aresample=48000', mixed)
        self.assertIn('atrim=duration=3.000000,asetpts=PTS-STARTPTS,volume=0.5,afade=t=in:st=0:d=1,'
                      'afade=t=out:st=0.500:d=2[music]', mixed)
        self.assertIn('amix=inputs=2:duration=first:dropout_transition=0:normalize=0', mixed)

    def test_speed_retimes_video_and_audio(self):
        clips = [{'frames': 60, 'seconds': 2.0, 'audio': True, 'speed': 2.0}, {'frames': 30, 'seconds': 1.0, 'audio': True, 'speed': 0.5}]
        graph, total = plan.filter_graph(clips, None, width=720, height=720, fps=30, fit='crop', clip_volume=1)
        self.assertEqual(total, 3.0)
        self.assertIn('[0:v:0]trim=end_frame=60,setpts=(PTS-STARTPTS)/2,', graph)
        self.assertIn('asetpts=PTS-STARTPTS,atempo=2,apad,atrim=duration=1.000000[a0]', graph)
        self.assertIn('setpts=(PTS-STARTPTS)/0.5,', graph)
        self.assertIn('trim=duration=2.000000[v1]', graph)
        self.assertIn('concat=n=2:v=1:a=1[vout][acat]', graph)

    def test_transitions_overlap_clips_and_are_capped_at_half_a_clip(self):
        fade = {'type': 'fade', 'duration': 1.0}
        clips = [{'frames': 90, 'seconds': 3.0, 'audio': True, 'transition': fade},
                 {'frames': 30, 'seconds': 1.0, 'audio': False, 'transition': {'type': 'none', 'duration': 0.5}},
                 {'frames': 60, 'seconds': 2.0, 'audio': True, 'transition': {'type': 'none', 'duration': 0.5}}]
        self.assertEqual(plan.transition_cuts(clips), [0.5, 0.0], 'a 1 s clip allows at most 0.5 s on each side')
        self.assertEqual(plan.total_seconds(clips), 5.5)
        graph, total = plan.filter_graph(clips, None, width=720, height=720, fps=30, fit='crop', clip_volume=1)
        self.assertEqual(total, 5.5)
        self.assertIn('[v0][v1]xfade=transition=fade:duration=0.500000:offset=2.500000[vj1]', graph)
        self.assertIn('[a0][a1]acrossfade=d=0.500000:c1=tri:c2=tri[aj1]', graph)
        self.assertIn('[vj1][v2]concat=n=2:v=1:a=0[vout]', graph)
        self.assertIn('[aj1][a2]concat=n=2:v=0:a=1[acat]', graph)
        self.assertNotIn('concat=n=3', graph)

    def test_subtitle_overlays_follow_the_joined_picture(self):
        clips = [{'frames': 30, 'seconds': 1.0, 'audio': False}, {'frames': 30, 'seconds': 1.0, 'audio': False,
                                                                 'transition': {'type': 'none', 'duration': 0.5}}]
        overlays = [{'input': 2, 'x': 10, 'y': 600, 'start': 0.0, 'end': 0.75}, {'input': 3, 'x': 12, 'y': 600, 'start': 1.0, 'end': 2.0}]
        graph, total = plan.filter_graph(clips, None, width=720, height=720, fps=30, fit='crop', clip_volume=1, overlays=overlays)
        self.assertEqual(total, 2.0)
        self.assertIn('concat=n=2:v=1:a=1[vmain][acat]', graph)
        self.assertIn("[vmain][2:v:0]overlay=x=10:y=600:enable='gte(t,0.000)*lt(t,0.750)'[vs0]", graph)
        self.assertIn("[vs0][3:v:0]overlay=x=12:y=600:enable='gte(t,1.000)*lt(t,2.000)'[vout]", graph)
        plain, _ = plan.filter_graph(clips, None, width=720, height=720, fps=30, fit='crop', clip_volume=1)
        self.assertNotIn('vmain', plain)
        argv, _ = plan.command('ffmpeg', [dict(clips[0], path='/a.mp4', seek=[])], {'path': '/m.m4a', 'volume': 1,
                               'fade_in': 0, 'fade_out': 0, 'duration': 5}, {'fps': 30, 'fit': 'crop', 'encoder': 'quality',
                               'resolution': 720}, width=720, height=720, clip_volume=1, target='/o.mp4',
                               overlays=[{'path': '/cue_001.png', 'x': 1, 'y': 2, 'start': 0, 'end': 0.5}])
        self.assertEqual([argv[i + 1] for i, value in enumerate(argv) if value == '-i'], ['/a.mp4', '/m.m4a', '/cue_001.png'])
        self.assertIn('[vmain][2:v:0]overlay', argv[argv.index('-filter_complex') + 1])

    def test_command_and_progress(self):
        clips = [{'path': '/a.mp4', 'seek': ['-ss', '1'], 'frames': 30, 'seconds': 1.0, 'audio': True}]
        argv, total = plan.command('ffmpeg', clips, None, {'fps': 30, 'fit': 'crop', 'encoder': 'fast', 'resolution': 720},
                                   width=1280, height=720, clip_volume=1, target='/out.mp4')
        self.assertEqual(total, 1.0)
        self.assertEqual(argv[argv.index('-i') - 2:argv.index('-i') + 2], ['-ss', '1', '-i', '/a.mp4'])
        self.assertIn('h264_videotoolbox', argv)
        self.assertEqual(argv[-4:], ['-f', 'mp4', '-y', '/out.mp4'])
        self.assertIn('libx264', plan.encoder_args('quality', 1080))
        self.assertEqual(plan.progress_share('out_time_us=500000', 1.0), 0.5)
        self.assertEqual(plan.progress_share('out_time_ms=3000000', 1.0), 1.0)
        self.assertIsNone(plan.progress_share('out_time_us=N/A', 1.0))
        self.assertIsNone(plan.progress_share('frame=12', 1.0))


class SourceAndStoreTests(unittest.TestCase):
    def test_music_sources_are_resolved_by_their_owners_only(self):
        with tempfile.TemporaryDirectory() as folder:
            assets = Path(folder)
            asset = 'a' * 64 + '.m4a'
            (assets / asset).write_bytes(b'x')

            class Store:
                def artifact(self, ident, name):
                    return Path(f'/jobs/{ident}/{name}')

            resolver = AudioSourceResolver(archive=lambda rel: Path('/archive') / rel, store=Store, assets_dir=assets)
            self.assertEqual(resolver.resolve(asset_id=asset), assets / asset)
            self.assertEqual(resolver.resolve('/api/assets/audio/file?path=2026-11-10%2Fa.m4a'), Path('/archive/2026-11-10/a.m4a'))
            self.assertEqual(resolver.resolve('http://127.0.0.1:18463/api/audio/artifact?id=1&name=a.wav'), Path('/jobs/1/a.wav'))
            with self.assertRaises(FileNotFoundError):
                resolver.resolve(asset_id='b' * 64 + '.m4a')
            for bad in ('/video/a.mp4', 'file:///etc/passwd', '/api/assets/audio/list'):
                with self.subTest(bad=bad), self.assertRaises(UnsupportedSource):
                    resolver.resolve(bad)
            with self.assertRaises(UnsupportedSource):
                resolver.resolve(asset_id='../../x.m4a')

    def test_store_persists_and_recovers_interrupted_jobs(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ComposeStore(folder)
            queued = store.create({'clips': []}, {'clip_count': 0})
            running = store.create({'clips': []}, {})
            store.update(running['id'], status='running')
            done = store.create({'clips': []}, {})
            store.update(done['id'], status='succeeded')
            self.assertTrue(store.has(queued['id']))
            self.assertFalse(store.has('x'))
            self.assertEqual(sorted(ComposeStore(folder).recover()), sorted([queued['id'], running['id']]))
            again = ComposeStore(folder)
            self.assertEqual(again.get(running['id'])['status'], 'interrupted')
            self.assertEqual(again.get(running['id'])['spec'], {'clips': []})
            self.assertEqual(again.get(done['id'])['status'], 'succeeded')
            with self.assertRaises(FileNotFoundError):
                again.get('../x')

    def test_compose_outputs_are_filed_as_video_compose(self):
        self.assertEqual(asset_index._infer_archive_provider(Path('/x/video_compose_120000_abc.mp4')), 'video_compose')
        self.assertEqual(asset_index._provider_label('video_compose'), '视频合成')


class LimitTests(unittest.TestCase):
    def test_total_length_and_queue_are_bounded(self):
        class Sources:
            def source(self, url):
                return Path('/' + url.rsplit('/', 1)[-1]), info(count=30 * 100)

        class Tools:
            def require(self):
                return 'ffmpeg', 'ffprobe'

        with tempfile.TemporaryDirectory() as folder:
            service = ComposeService(store=ComposeStore(folder), sources=Sources(), audio_resolver=None,
                                     output_dir=lambda: Path(folder), write_sidecar=lambda *a, **k: None, tools=Tools())
            self.assertEqual(service.check({'clips': [clip(end_frame=2999)]})['duration_seconds'], 100.0)
            with self.assertRaisesRegex(ValueError, '超过 3 分钟'):
                service.check({'clips': [clip(), clip()]})
            with self.assertRaisesRegex(ValueError, '第 1 段'):
                service.check({'clips': [clip(start_frame=10, end_frame=5)]})
            service.close()


class RecipeTests(unittest.TestCase):
    """Reopening a rendered output reads its `.json` recipe back through the same request contract."""
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = self.root = Path(self.folder.name)

        class Sources:
            def locate(self, url):
                return root / url.rsplit('/', 1)[-1]

        self.service = ComposeService(store=ComposeStore(root / 'db'), sources=Sources(), audio_resolver=None,
                                      output_dir=lambda: root, write_sidecar=lambda *a, **k: None)

    def tearDown(self):
        self.service.close()
        self.folder.cleanup()

    def write(self, name, recipe):
        (self.root / name).write_bytes(b'mp4')
        (self.root / name).with_suffix('.json').write_text(json.dumps(recipe), encoding='utf-8')

    def test_recipe_round_trips_spec_and_result(self):
        spec = {'clips': [clip('/video/a.mp4', start_frame=3, end_frame=40, audio=False, source_name='a.mp4')],
                'clip_volume': 0.5, 'music': {'source_url': '/api/assets/audio/file?path=m.wav', 'volume': 0.6, 'fade_in': 1},
                'output': {'aspect': '9:16', 'resolution': 720, 'fps': 24, 'fit': 'blur'}, 'title': '旧片'}
        self.write('video_compose_010203_abcdef123456.mp4', {'kind': 'video_compose', 'spec': spec,
                                                             'summary': {'duration_seconds': 1.6, 'width': 720, 'height': 1280}})
        reopened = self.service.recipe('/video/video_compose_010203_abcdef123456.mp4')
        self.assertEqual(reopened['spec'], contracts.compose_request(spec))
        self.assertEqual(reopened['result'], {'url': '/video/video_compose_010203_abcdef123456.mp4',
                                              'filename': 'video_compose_010203_abcdef123456.mp4', 'file_size': 3,
                                              'duration_seconds': 1.6, 'width': 720, 'height': 1280, 'fps': 24})

    def test_recipe_rejects_other_videos_missing_and_foreign_sidecars(self):
        with self.assertRaisesRegex(ValueError, '不是合成成片'):
            self.service.recipe('/video/comfy_00001.mp4')
        with self.assertRaises(FileNotFoundError):
            self.service.recipe('/video/video_compose_000000_000000000000.mp4')
        self.write('video_compose_1.mp4', {'kind': 'image', 'spec': {}})
        with self.assertRaisesRegex(ValueError, '配方格式无效'):
            self.service.recipe('/video/video_compose_1.mp4')
        self.write('video_compose_2.mp4', {'kind': 'video_compose', 'spec': {'clips': []}})
        with self.assertRaisesRegex(ValueError, '至少连接一段'):
            self.service.recipe('/video/video_compose_2.mp4')


@unittest.skipUnless(HAS_FFMPEG, 'FFmpeg not installed')
class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        # 30 fps, B-frames: red 0–29, green 30–59, blue 60–89; a 440 Hz tone throughout.
        render(root / 'rgb.mp4', '-f', 'lavfi', '-i', 'color=red:s=320x240:r=30:d=1', '-f', 'lavfi',
               '-i', 'color=green:s=320x240:r=30:d=1', '-f', 'lavfi', '-i', 'color=blue:s=320x240:r=30:d=1',
               '-f', 'lavfi', '-i', 'sine=f=440:d=3', '-filter_complex', '[0][1][2]concat=n=3:v=1:a=0[v]',
               '-map', '[v]', '-map', '3:a', '-c:v', 'libx264', '-bf', '2', '-c:a', 'aac', '-shortest')
        render(root / 'silent.mp4', '-f', 'lavfi', '-i', 'color=white:s=240x320:r=24:d=2', '-c:v', 'libx264')
        render(root / 'music.m4a', '-f', 'lavfi', '-i', 'sine=f=220:d=10', '-c:a', 'aac')
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        root = self.root

        class Resolver:
            def resolve(self, url):
                return root / url.rsplit('/', 1)[-1]

        self.out = Path(tempfile.mkdtemp(dir=root))
        self.notes = []
        self.edit = VideoEditService(resolver=Resolver(), frame_dir=lambda: self.out,
                                     write_sidecar=lambda *a, **k: None, audio_archive=None)
        self.service = ComposeService(
            store=ComposeStore(self.out / 'db'), sources=self.edit,
            audio_resolver=AudioSourceResolver(archive=lambda rel: root / rel), output_dir=lambda: self.out,
            write_sidecar=lambda target, prompt, txt_path=None: self.notes.append((Path(target).name, prompt)))

    def tearDown(self):
        self.service.close()
        self.edit.close()

    def wait(self, receipt, timeout=120):
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.service.job(receipt['id'])
            if job['status'] not in ('queued', 'running'):
                return job
            time.sleep(0.05)
        raise AssertionError('compose did not finish')

    def test_render_is_frame_exact_mixes_music_and_reuses_the_recipe(self):
        body = {'clips': [clip('/video/rgb.mp4', start_frame=30, end_frame=59, source_name='彩色.mp4'),
                          clip('/video/silent.mp4')],
                'music': {'source_url': '/api/assets/audio/file?path=music.m4a', 'volume': 0.5, 'fade_out': 1},
                'output': {'aspect': '9:16', 'resolution': 720, 'fit': 'pad', 'fps': 30}, 'title': '测试'}
        job = self.wait(self.service.submit(body))
        self.assertEqual(job['status'], 'succeeded', job['error'])
        result = job['result']
        target = self.out / result['filename']
        self.assertTrue(result['filename'].startswith('video_compose_') and result['url'] == '/video/' + target.name)
        self.assertEqual((result['width'], result['height'], result['duration_seconds']), (720, 1280, 3.0))
        facts = streams(target)
        self.assertEqual((facts['video']['width'], facts['video']['height'], facts['video']['nb_frames']), (720, 1280, '90'))
        self.assertAlmostEqual(float(facts['audio']['duration']), 3.0, delta=0.05)
        colours = frame_colours(target, '8:8:356:636')
        self.assertEqual(len(colours), 90)
        self.assertTrue(all(c[1] > 100 and c[0] < 40 and c[2] < 40 for c in colours[:30]), 'clip 1 is exactly the green frames')
        self.assertTrue(all(min(c) > 200 for c in colours[30:]), 'clip 2 follows immediately')
        recipe = json.loads(target.with_suffix('.json').read_text(encoding='utf-8'))
        self.assertEqual((recipe['kind'], recipe['spec']['clips'][0]['start_frame']), ('video_compose', 30))
        self.assertIn('彩色.mp4 帧 31–60', target.with_suffix('.txt').read_text(encoding='utf-8'))
        self.assertEqual(self.notes[0][0], target.name)
        again = self.wait(self.service.submit(body))
        self.assertEqual((again['result']['filename'], again['result']['reused']), (target.name, True))
        changed = self.wait(self.service.submit({**body, 'clip_volume': 0.5}))
        self.assertNotEqual(changed['result']['filename'], target.name)

    def test_speed_and_transition_render_to_the_planned_length(self):
        fast = self.wait(self.service.submit({'clips': [clip('/video/rgb.mp4', speed=2)],
                                              'output': {'aspect': '1:1', 'resolution': 720, 'fps': 30}}))
        self.assertEqual(fast['status'], 'succeeded', fast['error'])
        target = self.out / fast['result']['filename']
        facts = streams(target)
        self.assertEqual((fast['result']['duration_seconds'], facts['video']['nb_frames']), (1.5, '45'))
        self.assertAlmostEqual(float(facts['audio']['duration']), 1.5, delta=0.05)
        colours = frame_colours(target, '8:8:356:356')
        self.assertTrue(all(c[0] > 200 and c[1] < 40 for c in colours[:15]), 'red covers the first half second')
        self.assertTrue(all(c[1] > 100 and c[0] < 40 for c in colours[15:30]), 'green follows at double speed')
        self.assertTrue(all(c[2] > 200 and c[0] < 40 for c in colours[30:]), 'then blue')

        joined = self.wait(self.service.submit({
            'clips': [clip('/video/rgb.mp4', end_frame=29, transition={'type': 'fadeblack', 'duration': 0.5}),
                      clip('/video/silent.mp4')],
            'output': {'aspect': '1:1', 'resolution': 720, 'fps': 30, 'fit': 'pad'}}))
        self.assertEqual(joined['status'], 'succeeded', joined['error'])
        target = self.out / joined['result']['filename']
        facts = streams(target)
        self.assertEqual((joined['result']['duration_seconds'], facts['video']['nb_frames']), (2.5, '75'))
        self.assertAlmostEqual(float(facts['audio']['duration']), 2.5, delta=0.05)
        colours = frame_colours(target, '8:8:356:356')
        self.assertTrue(colours[0][0] > 200 and colours[0][1] < 40, 'starts red')
        self.assertTrue(all(c[0] > 200 for c in colours[:15]), 'red until the transition starts at 0.5 s')
        self.assertLess(min(max(c) for c in colours[15:30]), 20, 'dips to black inside the 0.5 s transition')
        self.assertTrue(all(min(c) > 200 for c in colours[30:]), 'white once the transition ends')
        self.assertTrue(min(colours[-1]) > 200, 'ends on the white clip')
        self.assertIn('→ 黑场 0.5s', target.with_suffix('.txt').read_text(encoding='utf-8'))

    def test_default_speed_and_no_transition_keep_phase_two_file_names(self):
        plain = self.wait(self.service.submit({'clips': [clip('/video/silent.mp4', end_frame=11)], 'output': {'resolution': 720}}))
        explicit = self.wait(self.service.submit({'clips': [clip('/video/silent.mp4', end_frame=11, speed=1,
                                                                 transition={'type': 'none', 'duration': 1})],
                                                  'output': {'resolution': 720}}))
        self.assertEqual((explicit['result']['filename'], explicit['result']['reused']), (plain['result']['filename'], True))

    @unittest.skipUnless(FONT, 'no CJK font on this machine')
    def test_subtitles_burn_in_for_their_cue_only_and_write_an_srt(self):
        output = {'aspect': '1:1', 'resolution': 720, 'fps': 30}
        cues = [{'start': 0.5, 'end': 1.5, 'text': '字幕 Subtitle'}]
        body = {'clips': [clip('/video/rgb.mp4', end_frame=59)], 'output': output,
                'subtitles': {'cues': cues, 'style': {'look': 'box', 'position': 'bottom'}}}
        with self.assertRaisesRegex(ValueError, '成片结束之后'):
            self.service.submit({**body, 'subtitles': {'cues': [{'start': 1.8, 'end': 3, 'text': '晚了'}]}})
        job = self.wait(self.service.submit(body))
        self.assertEqual(job['status'], 'succeeded', job['error'])
        target = self.out / job['result']['filename']
        self.assertEqual(streams(target)['video']['nb_frames'], '60')
        # Where the box's left padding lands: darkened only while the cue is on (frames 15–44).
        layout = subtitles.Layout(cues, {'size': 'medium', 'position': 'bottom', 'look': 'box'}, width=720, height=720, font_file=FONT)
        with tempfile.TemporaryDirectory() as folder:
            [item] = layout.render(Path(folder))
        colours = frame_colours(target, f'2:2:{item["x"] + 3}:{item["y"] + 8}')
        reference = frame_colours(target, '2:2:8:8')
        lit = [index for index, (colour, plain) in enumerate(zip(colours, reference)) if max(colour) < max(plain) * 0.7]
        self.assertEqual((lit[0], lit[-1], len(lit)), (15, 44, 30))
        self.assertEqual(target.with_suffix('.srt').read_text(encoding='utf-8'),
                         '1\n00:00:00,500 --> 00:00:01,500\n字幕 Subtitle\n')
        self.assertIn('字幕：1 条', target.with_suffix('.txt').read_text(encoding='utf-8'))
        recipe = json.loads(target.with_suffix('.json').read_text(encoding='utf-8'))
        self.assertEqual((recipe['spec']['subtitles']['cues'], recipe['summary']['subtitle_count']), (cues, 1))
        plain = self.wait(self.service.submit({**body, 'subtitles': None}))
        self.assertNotEqual(plain['result']['filename'], target.name, 'subtitles change the file name')
        self.assertFalse(list(Path(tempfile.gettempdir()).glob('video-compose-*/cue_001.png')), 'scratch PNGs removed')

    def test_crop_and_blur_fill_the_frame_and_cancel_stops_a_render(self):
        job = self.wait(self.service.submit({'clips': [clip('/video/silent.mp4', end_frame=11)],
                                             'output': {'aspect': '16:9', 'resolution': 720, 'fit': 'blur'}}))
        self.assertEqual(job['status'], 'succeeded', job['error'])
        self.assertEqual(streams(self.out / job['result']['filename'])['video']['width'], 1280)
        self.assertIn('audio', streams(self.out / job['result']['filename']))
        receipt = self.service.submit({'clips': [clip('/video/rgb.mp4')] * 6, 'output': {'resolution': 1080}})
        self.service.cancel(receipt['id'])
        self.assertEqual(self.wait(receipt)['status'], 'cancelled')
        self.assertFalse(list(self.out.glob('.*.writing.mp4')))


class FakeHandler:
    def __init__(self, path, body=None):
        self.path = path
        data = json.dumps(body).encode() if body is not None else b''
        self.headers = {'Content-Length': str(len(data))}
        self.rfile = io.BytesIO(data)
        self.wfile = io.BytesIO()
        self.sent = self.status = None

    def require_auth(self):
        return True

    def send_json(self, payload, status=200, headers=None):
        self.sent, self.status = payload, status


class FilmstripTests(unittest.TestCase):
    def test_tiles_snap_and_pick_the_middle_frame_of_each_share(self):
        self.assertEqual([contracts.filmstrip_tiles(v) for v in (None, 'x', 1, 15, 30, 999)], [40, 40, 8, 16, 24, 40])
        self.assertEqual(media.filmstrip_frames(90, 3), [15, 45, 75])
        self.assertEqual(media.filmstrip_frames(2, 8)[-1], 1)

    def test_filmstrip_is_one_row_in_frame_order_and_cached(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        render(root / 'rgb.mp4', '-f', 'lavfi', '-i', 'color=red:s=320x240:r=30:d=1', '-f', 'lavfi',
               '-i', 'color=green:s=320x240:r=30:d=1', '-f', 'lavfi', '-i', 'color=blue:s=320x240:r=30:d=1',
               '-filter_complex', '[0][1][2]concat=n=3:v=1:a=0[v]', '-map', '[v]', '-c:v', 'libx264', '-bf', '2')

        class Resolver:
            def resolve(self, url):
                return root / url.rsplit('/', 1)[-1]

        edit = VideoEditService(resolver=Resolver(), frame_dir=lambda: root, write_sidecar=lambda *a, **k: None,
                                audio_archive=None)
        self.addCleanup(edit.close)
        data = edit.filmstrip('/video/rgb.mp4', 24)
        self.assertIs(edit.filmstrip('/video/rgb.mp4', 24), data)
        path = Path(self.temp.name) / 'strip.jpg'
        path.write_bytes(data)
        size = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=width,height', '-of', 'csv=p=0',
                               str(path)], capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(size, f'{128 * 24},96')
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-vf', 'scale=24:1', '-f', 'rawvideo',
                              '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True).stdout
        tiles = [tuple(raw[i * 3:i * 3 + 3]) for i in range(24)]
        self.assertGreater(tiles[0][0], 180)  # red first
        self.assertGreater(tiles[12][1], 90)  # green in the middle
        self.assertGreater(tiles[-1][2], 180)  # blue last


class RouteTests(unittest.TestCase):
    class Edit:
        def status(self):
            return {'available': True}

        def job(self, ident):
            return {'id': ident, 'kind': 'frames'}

        def cancel(self, ident):
            return {'id': ident, 'kind': 'frames', 'status': 'cancelled'}

    class Compose:
        def limits(self):
            return {'max_clips': 20}

        def owns(self, ident):
            return ident == 'c' * 32

        def submit(self, body):
            if not body.get('clips'):
                raise ValueError('请至少连接一段视频')
            return {'id': 'c' * 32, 'kind': 'compose', 'status': 'queued'}

        def check(self, body):
            return {'duration_seconds': 3.0}

        def recipe(self, url):
            return {'spec': {'clips': [clip(url)]}}

        def subtitle_fonts(self):
            return {'fonts': [{'file': 'a.ttf', 'label': 'a', 'url': '/font/a.ttf'}], 'default': 'a.ttf'}

        def job(self, ident):
            return {'id': ident, 'kind': 'compose'}

        def cancel(self, ident):
            return {'id': ident, 'kind': 'compose', 'status': 'cancelled'}

    def call(self, method, path, body=None):
        handler = FakeHandler(path, body)
        self.assertTrue(create_router(self.Edit(), self.Compose()).dispatch(handler, method, path.split('?')[0]))
        return handler

    def test_compose_routes_and_job_dispatch(self):
        self.assertEqual(self.call('GET', '/api/video_edit/status').sent['compose'], {'max_clips': 20})
        submitted = self.call('POST', '/api/video_edit/compose', {'clips': [clip()]})
        self.assertEqual((submitted.status, submitted.sent['kind']), (202, 'compose'))
        self.assertEqual(self.call('POST', '/api/video_edit/compose', {'clips': []}).status, 400)
        self.assertEqual(self.call('POST', '/api/video_edit/compose_check', {'clips': [clip()]}).sent, {'duration_seconds': 3.0})
        self.assertEqual(self.call('GET', '/api/video_edit/compose_recipe?source_url=/video/x.mp4').sent['spec']['clips'][0]['source_url'],
                         '/video/x.mp4')
        self.assertEqual(self.call('GET', '/api/video_edit/subtitle_fonts').sent['default'], 'a.ttf')
        self.assertEqual(self.call('GET', '/api/video_edit/job?id=' + 'c' * 32).sent['kind'], 'compose')
        self.assertEqual(self.call('GET', '/api/video_edit/job?id=x').sent['kind'], 'frames')
        self.assertEqual(self.call('POST', '/api/video_edit/cancel', {'id': 'c' * 32}).sent['kind'], 'compose')

    def test_compose_outputs_are_never_sent_to_telegram(self):
        # Maintainer decision (2026-11-10): compose renders stay in the archive only, whatever their size.
        root = Path(__file__).resolve().parents[1]
        for file in ('backend/video_edit/compose.py', 'backend/video_edit/plan.py', 'backend/video_edit/storage.py',
                     'backend/routes/video_edit_routes.py', 'frontend/scripts/desktop-canvas-video-compose.js'):
            source = (root / file).read_text(encoding='utf-8').lower()
            self.assertNotIn('telegram', source, file)
            self.assertNotIn('senddocument', source, file)

    def test_server_wires_compose_with_resolvers_and_durable_store(self):
        server = (Path(__file__).resolve().parents[1] / 'backend' / 'server.py').read_text(encoding='utf-8')
        self.assertIn("store=VideoComposeStore(APP_DATA_DIR / 'data' / 'video-edit'), sources=_VIDEO_EDIT_SERVICE", server)
        self.assertIn("VideoComposeMusic(archive=_AUDIO_ARCHIVE.resolve, store=lambda: _AUDIO_SERVICE.store", server)
        self.assertIn('create_video_edit_router(_VIDEO_EDIT_SERVICE, _VIDEO_COMPOSE_SERVICE, _VIDEO_TRANSCRIBE_SERVICE)', server)
        self.assertIn('output_dir=daily_output_dir', server)
        self.assertIn("font_dir=PROJECT_ROOT / 'font'", server)


if __name__ == '__main__':
    unittest.main()

"""Portable processing-chain regressions: no credentials, downloads or inference."""
import json
from pathlib import Path
import tempfile
import unittest
import threading
from unittest import mock

from backend.topaz_video.contracts import normalize
from backend.topaz_video.features import inspect_features, validate_capabilities, encoding_args
from backend.topaz_video.pipeline import audio_filter, build_plan, output_timing
from backend.topaz_video.runtime import build_audio_mux_command
from backend.topaz_video.runtime import TopazVideoRuntime, VideoRuntimeError
from backend.topaz_video.storage import Store


def request(**kwargs):
    return normalize({"asset_id": "a" * 32, "model": "proteus-v4", "scale": 1, **kwargs})


class ProcessingContracts(unittest.TestCase):
    def test_legacy_payload_is_unchanged(self):
        self.assertNotIn("filters", request())

    def test_composable_filters_have_separate_model_and_output_contracts(self):
        spec = request(enhancement=False, filters={"interpolation": {"model": "apo-8", "fps": 60, "slowmo": 2},
            "motion_deblur": {}, "stabilization": {}, "hdr": {}}, encoding={"codec": "hevc10"})
        self.assertFalse(spec["enhancement"])
        self.assertEqual(spec["filters"]["hdr"], {"model": "hyp-2", "strength": 1})
        self.assertEqual(spec["encoding"]["audio"], "aac")

    def test_filters_cannot_inject_paths_arguments_or_extra_private_fields(self):
        for extra in ({"path": "/private/video"}, {"filename": "injected"}, {"model": "../../x"}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                request(filters={"interpolation": extra})
        for filters in ([], {"unknown": {}}, {"motion_deblur": {"command": "echo"}}, {"hdr": {"strength": True}}):
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                request(filters=filters)

    def test_nonfinite_boolean_and_out_of_range_numbers_rejected(self):
        for field, value in (("fps", float("nan")), ("fps", .5), ("fps", 121), ("slowmo", True),
                             ("slowmo", 17), ("rdt", .21)):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                request(filters={"interpolation": {field: value}})
        with self.assertRaises(ValueError):
            request(filters={"stabilization": {"reduce_jitter": .5}})

    def test_hdr_requires_real_ten_bit_encoding(self):
        with self.assertRaisesRegex(ValueError, "10-bit"):
            request(filters={"hdr": {}})
        with self.assertRaises(ValueError):
            request(encoding={"codec": "libx264;rm"})
        with self.assertRaises(ValueError):
            request(encoding={"bitrate_mbps": float("inf")})
        with self.assertRaises(ValueError):
            request(encoding={"codec": []})
        with self.assertRaises(ValueError):
            request(encoding={"bitrate_mbps": 10 ** 400})
        self.assertIn("p010le", encoding_args(request(encoding={"codec": "hevc10"})["encoding"]))

    def test_unavailable_features_rejected_before_queueing(self):
        status = {"models": [{"id": "proteus-v4", "available": True}], "capabilities": {}}
        with self.assertRaisesRegex(ValueError, "资源"):
            validate_capabilities(request(filters={"interpolation": {}}), status)
        status["capabilities"] = {"stabilization": {"available": True, "full_frame": False, "jitter": False}}
        with self.assertRaisesRegex(ValueError, "Refine"):
            validate_capabilities(request(filters={"stabilization": {"mode": "full_frame"}}), status)
        with self.assertRaisesRegex(ValueError, "修复"):
            validate_capabilities(request(filters={"stabilization": {"rolling_shutter": True}}), status)

    def test_disabled_enhancement_does_not_need_a_loaded_enhancement_model(self):
        spec = request(enhancement=False)
        validate_capabilities(spec, {"models": [], "processing_ready": True})
        with self.assertRaises(ValueError):
            validate_capabilities(spec, {"models": [], "processing_ready": False})


class OfflinePlan(unittest.TestCase):
    def plan(self, **kwargs):
        spec = request(enhancement=False, start_seconds=12.5, max_seconds=.5, **kwargs)
        return build_plan(Path("/stage"), Path("/job/work"), spec, Path("/asset"), Path("/job/result.mp4"),
                          width=256, height=256, frames=12, fps=24)

    def test_selected_clip_is_prepared_before_camera_analysis(self):
        plan = self.plan(filters={"stabilization": {}})
        self.assertIn("12.50000000", plan.passes[0].command)
        self.assertIn("12", plan.passes[0].command)
        self.assertIn("/job/work/clip.mov", plan.passes[1].command)
        self.assertIn("scale=256:256", " ".join(plan.passes[2].command))

    def test_every_ai_filter_stays_offline_and_no_app_path_enters_commands(self):
        plan = self.plan(filters={"stabilization": {}, "motion_deblur": {}, "interpolation": {}, "hdr": {}}, encoding={"codec": "hevc10"})
        for step in plan.passes:
            for value in step.command:
                self.assertNotIn("/Applications", value)
                if "tvai_" in value:
                    for item in value.split(","):
                        if "tvai_" in item: self.assertIn("download=0", item)

    def test_interpolation_pads_the_last_sample_without_extending_final_duration(self):
        plan = self.plan(filters={"interpolation": {"fps": 60, "slowmo": 2}})
        self.assertEqual((plan.frames, plan.fps, plan.slowmo), (60, 60, 2))
        cmd = plan.passes[-1].command
        self.assertIn("tpad=stop_mode=clone", cmd[cmd.index("-vf") + 1])
        self.assertEqual(cmd[cmd.index("-frames:v") + 1], "60")
        self.assertEqual(output_timing({}, 24, 12), (12, 24, 1))

    def test_hdr_uses_aces_linear_frames_and_color_conversion_not_just_tags(self):
        plan = self.plan(filters={"hdr": {}}, encoding={"codec": "hevc10"})
        text = "\n".join(" ".join(step.command) for step in plan.passes)
        self.assertIn("--output-codec exr", text)
        self.assertIn("ACES2065-1", text)
        self.assertIn("ACES 2.0 - HDR 1000 nits (Rec.2020)", text)
        self.assertIn("frame_%06d.exr", text)
        self.assertNotIn("frame_######", text)
        self.assertIn("-color_trc smpte2084", text)

    def test_slowmo_restores_pitch_preserved_audio_with_padded_tail(self):
        self.assertEqual(audio_filter(1), "apad")
        self.assertEqual(audio_filter(4), "atempo=0.5,atempo=0.5,apad")
        command = build_audio_mux_command(Path("ffmpeg"), Path("rendered"), Path("source"), Path("out"),
                                          start_seconds=12.5, duration_seconds=.5, slowmo=2)
        self.assertEqual(command[command.index("-af") + 1], "atempo=0.5,apad")
        self.assertLess(command.index("-af"), command.index("-shortest"))


class FeatureReadiness(unittest.TestCase):
    def test_hdr_needs_an_intact_executable_color_transform_helper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); stage = root / "conventional/Contents"
            (stage / 'MacOS').mkdir(parents=True)
            (root / 'precise/models/hyp-2').mkdir(parents=True)
            blobs = {f'blob.{index}': 4 for index in range(43)}
            for name in blobs: (root / 'precise/models/hyp-2' / name).write_bytes(b'test')
            (root / 'precise/topaz-video-stage.json').write_text(json.dumps({'neuro_model_file_sizes': {'hyp-2': blobs}}))
            (stage / 'topaz-video-stage.json').write_text(json.dumps({'helper_file_sizes': {'oiiotool': 4}}))
            helper = stage / 'MacOS/oiiotool'; helper.write_bytes(b'test'); helper.chmod(0o755)
            def status(): return inspect_features(root, conventional_ready=True, precise_ready=True, licensed=True)['hdr']
            self.assertTrue(status()['available'])
            self.assertFalse(inspect_features(root, conventional_ready=False, precise_ready=True, licensed=True)['hdr']['available'])
            helper.chmod(0o644)
            self.assertFalse(status()['available'])
            helper.chmod(0o755); helper.write_bytes(b'truncated')
            self.assertFalse(status()['available'])

    def test_descriptor_without_recorded_weights_is_not_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); stage = root / "conventional/Contents"; models = stage / "Resources/models"
            models.mkdir(parents=True); (models / "chf-3.json").write_text("{}")
            def status(): return inspect_features(root, conventional_ready=True, precise_ready=False, licensed=True)
            self.assertFalse(status()["interpolation"]["available"])
            weight = "chf-v3-fp16-384x672-ml.tz3"
            (models / weight).write_bytes(b"synthetic")
            (stage / "topaz-video-stage.json").write_text(json.dumps({"model_file_sizes": {"chf-3.json": 2, weight: 9}}))
            self.assertTrue(status()["interpolation"]["available"])
            (models / weight).write_bytes(b"broken")
            self.assertFalse(status()["interpolation"]["available"])

    def test_filter_only_export_never_promotes_an_unrun_enhancement_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(temporary); job = store.create(request(enhancement=False))
            store.update(job["id"], status="succeeded", watermark_verified=True, export_provenance="licensed_topaz_checkout")
            self.assertEqual(store.verified_model_scales(), {})


class PipelineLifecycle(unittest.TestCase):
    source = {"width": 256, "height": 256, "fps": 24, "frames": 12, "has_audio": True}

    def test_native_precise_dimension_error_does_not_publish_an_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); runtime = TopazVideoRuntime(root)
            def run(command, **kwargs): return 1, ('ValueError: [broadcast_shapes] incompatible shapes',)
            with mock.patch('backend.topaz_video.runtime._probe', return_value=self.source), \
                    mock.patch('backend.topaz_video.runtime._run_process', side_effect=run):
                with self.assertRaisesRegex(VideoRuntimeError, '不兼容当前素材尺寸'):
                    runtime._execute(normalize({'asset_id':'a'*32, 'model':'precise-26','scale':2}), root,
                                     root/'source', threading.Event(), lambda _: None)
            self.assertFalse((root/'result/enhanced.mp4').exists())

    def test_cancellation_stops_the_remaining_passes_and_cleans_intermediates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); event = threading.Event(); runtime = TopazVideoRuntime(root)
            def run(command, **kwargs):
                event.set()
                return -15, ()
            with mock.patch('backend.topaz_video.runtime._probe', return_value=self.source), \
                    mock.patch.object(runtime, 'license_model_dir', return_value=root), \
                    mock.patch('backend.topaz_video.runtime._run_process', side_effect=run) as process:
                runtime._execute(request(filters={"motion_deblur": {}}), root, root/'source', event, lambda _: None)
            self.assertEqual(process.call_count, 1)
            self.assertFalse(list(root.glob('.pipeline-*')))
            self.assertFalse((root/'result/enhanced.mp4').exists())

    def test_every_ai_pass_has_its_own_license_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); runtime = TopazVideoRuntime(root); calls = []
            def run(command, **kwargs):
                calls.append(command)
                # Preparation succeeded. The next AI process doesn't accept
                # the license: success from an earlier pass is not sufficient.
                return 0, ()
            with mock.patch('backend.topaz_video.runtime._probe', return_value=self.source), \
                    mock.patch.object(runtime, 'license_model_dir', return_value=root), \
                    mock.patch('backend.topaz_video.runtime._run_process', side_effect=run):
                with self.assertRaisesRegex(VideoRuntimeError, '授权'):
                    runtime._execute(request(filters={"motion_deblur": {}, "hdr": {}}, encoding={"codec": "hevc10"}),
                                     root, root/'source', threading.Event(), lambda _: None)
            self.assertEqual(len(calls), 2)
            self.assertFalse((root/'result/enhanced.mp4').exists())
            self.assertFalse(list(root.glob('.pipeline-*')))

    def test_independent_denoise_is_a_real_pass_not_model_selection(self):
        spec = request(filters={"denoise": {"noise": .4}}, enhancement=True)
        plan = build_plan(Path('/stage'), Path('/work'), spec, Path('/input'), Path('/output'), width=256, height=256, frames=12, fps=24)
        command = ' '.join(plan.passes[1].command)
        self.assertIn('model=nyx-3', command)
        self.assertIn('model=prob-4', command)
        self.assertLess(command.index('model=nyx-3'), command.index('model=prob-4'))

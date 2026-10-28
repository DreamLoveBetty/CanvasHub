"""GEM-X lite photo recognition (worker process only; never imported by the HTTP process).

Pipeline per photo, CPU only (no CoreML compile, no SAM-3D-Body image features):
  YOLOX person boxes -> VitPose 77 keypoints per person (flip test, RGB input as in GEM-X PR #21)
  -> the keypoints repeated over a short static clip -> GEM denoiser with 50-step DDIM
  -> SOMA 77-joint pose of the middle frame, in camera and gravity-aligned world frames
  -> a short fit of the joint rotations back onto the keypoints (refine.py).

GEM-X is used from a pinned upstream checkout (`gemx/`). GEM-X hard-codes CUDA on its PyTorch
paths; `_prepare_runtime` redirects those calls to the CPU explicitly and keeps py-soma-x 0.3.x on
the legacy 77-joint rig GEM-X was trained with. Render-only modules are stubbed.
"""
import os
from pathlib import Path
import sys
import types

import numpy as np

VITPOSE_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
VITPOSE_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
CLIP_FRAMES = 32
_PREPARED = False


def _prepare_runtime(root):
    """Import-time environment for GEM-X on a Mac CPU. Idempotent."""
    global _PREPARED
    if _PREPARED:
        return
    import torch

    cpu = torch.device('cpu')

    def fix(device):
        if isinstance(device, str) and device.startswith('cuda'):
            return cpu
        if isinstance(device, torch.device) and device.type == 'cuda':
            return cpu
        return device

    def fix_args(args, kwargs):
        if 'device' in kwargs:
            kwargs['device'] = fix(kwargs['device'])
        return tuple(fix(a) for a in args), kwargs

    tensor_to, module_to = torch.Tensor.to, torch.nn.Module.to

    def tensor_to_cpu(self, *args, **kwargs):
        args, kwargs = fix_args(args, kwargs)
        return tensor_to(self, *args, **kwargs)

    def module_to_cpu(self, *args, **kwargs):
        args, kwargs = fix_args(args, kwargs)
        return module_to(self, *args, **kwargs)

    torch.Tensor.to, torch.nn.Module.to = tensor_to_cpu, module_to_cpu
    torch.Tensor.cuda = lambda self, *a, **k: tensor_to(self, cpu)
    torch.nn.Module.cuda = lambda self, *a, **k: module_to(self, cpu)
    torch.cuda.empty_cache = lambda: None
    torch.cuda.synchronize = lambda *a, **k: None
    from lightning_fabric.utilities.device_dtype_mixin import _DeviceDtypeModuleMixin
    _DeviceDtypeModuleMixin.cuda = lambda self, *a, **k: module_to(self, cpu)

    import soma
    soma_init = soma.SOMALayer.__init__

    def legacy_init(self, *args, **kwargs):
        # GEM-X was trained on the SOMA 0.1.3 rig: no procedural twist joints, no correctives.
        kwargs['device'] = fix(kwargs.get('device', 'cpu'))
        kwargs.setdefault('enable_procedural_transforms', False)
        kwargs.setdefault('load_correctives_model', False)
        soma_init(self, *args, **kwargs)
    soma.SOMALayer.__init__ = legacy_init
    soma_pose = soma.SOMALayer.pose
    soma.SOMALayer.pose = lambda self, *args, **kwargs: soma_pose(self, *args, **{'apply_correctives': False, **kwargs})

    # Render-only / logging-only modules imported at module level by GEM-X.
    o3d = types.ModuleType('gem.utils.vis.o3d_render')
    o3d.Settings = o3d.create_meshes = o3d.get_ground = None
    sys.modules.setdefault('gem.utils.vis.o3d_render', o3d)
    sys.modules.setdefault('wandb', types.ModuleType('wandb'))
    os.chdir(root)  # GEM-X resolves inputs/ relative to its checkout
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    _PREPARED = True


def crop(image_rgb, bbx_xys):
    """VitPose input for one person box (cx, cy, size): 256x256 affine crop, normalised, centre 192 columns."""
    import cv2
    cx, cy, s = (float(v) for v in bbx_xys)
    src = np.array([[cx - s / 2, cy - s / 2], [cx + s / 2, cy - s / 2], [cx, cy]], dtype=np.float32)
    dst = np.array([[0, 0], [255, 0], [127.5, 127.5]], dtype=np.float32)
    patch = cv2.warpAffine(image_rgb, cv2.getAffineTransform(src, dst), (256, 256), flags=cv2.INTER_LINEAR)
    return ((patch.astype(np.float32) / 255.0 - VITPOSE_MEAN) / VITPOSE_STD).transpose(2, 0, 1)[:, :, 32:224]


def decode(heatmaps, flipped, bbx_xys):
    """(N, 77, 3) keypoints from VitPose heatmaps; `flipped` (heatmaps of the mirrored crops) or None."""
    from gem.utils.vitpose_extractor import flip_heatmap_soma77, keypoints_from_heatmaps
    import torch
    if flipped is not None:  # flip test, as GEM-X's extractor does
        heatmaps = (heatmaps + flip_heatmap_soma77(torch.from_numpy(np.ascontiguousarray(flipped))).numpy()) * 0.5
    bbx_xys = np.asarray(bbx_xys, dtype=np.float32).reshape(-1, 3)
    scale = np.stack([bbx_xys[:, 2] * 24 / 32, bbx_xys[:, 2]], 1) / 200
    preds, maxvals = keypoints_from_heatmaps(heatmaps=heatmaps, center=bbx_xys[:, :2], scale=scale, use_udp=True)
    return np.concatenate((preds, maxvals), axis=-1)


def _cpu_session(path):
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(str(path), sess_options=options, providers=['CPUExecutionProvider'])


class PhotoEngine:
    def __init__(self, gemx_root, yolox_onnx, frames=CLIP_FRAMES, score_threshold=0.5):
        import torch

        self.root = Path(gemx_root)
        _prepare_runtime(self.root)
        torch.set_grad_enabled(False)
        from gem.utils.yolox_detector import YOLOXDetector
        from hydra import compose, initialize_config_dir
        import hydra

        # YOLOX: reuse GEM-X pre/post-processing, but on a CPU-only session.
        self.detector = YOLOXDetector.__new__(YOLOXDetector)
        self.detector.sess = _cpu_session(yolox_onnx)
        self.detector.input_size, self.detector.score_thr, self.detector.nms_thr = (640, 640), score_threshold, 0.45
        self.vitpose = _cpu_session(self.root / 'inputs/onnx/vitpose.onnx')
        with initialize_config_dir(version_base='1.3', config_dir=str(self.root / 'configs')):
            cfg = compose(config_name='demo_soma', overrides=[
                'exp=gem_soma_regression', 'video_name=photo', 'video_path=photo.jpg', 'output_root=/dev/null',
                'static_cam=true', 'render_mhr=false', 'use_wandb=false', 'task=test'])
        model = hydra.utils.instantiate(cfg.model, _recursive_=False)
        model.load_pretrained_model(str(self.root / 'inputs/pretrained/gem_soma.ckpt'))
        self.model = model.eval()
        self.frames = frames
        names = [str(n) for n in self.model.body_model.soma.public_joint_names]
        self.joint_names = names[1:] if len(names) == 78 else names  # 77, Hips first

    def _keypoints(self, image_rgb, bbx_xys):
        patch = crop(image_rgb, bbx_xys)[None]
        name = self.vitpose.get_inputs()[0].name
        heat = self.vitpose.run(None, {name: np.ascontiguousarray(patch)})[0]
        flipped = self.vitpose.run(None, {name: np.ascontiguousarray(patch[..., ::-1])})[0]
        return decode(heat, flipped, bbx_xys)[0]  # (77, 3)

    def predict(self, keypoints, bbx_xys, width, height, features=None, pred_cam=None):
        """GEM denoiser over a static-camera clip: keypoints (L, 77, 3), boxes (L, 3).
        Returns the GEM-X prediction with per-frame SOMA parameters in camera and world frames.
        features (L, 1024) SAM 3D Body body tokens and pred_cam (L, 3) its weak-perspective camera give GEM-X's full
        model; without them it is the lite engine (no image condition)."""
        import torch
        from gem.utils.cam_utils import estimate_K
        from gem.utils.geo_transform import compute_cam_angvel, compute_cam_tvel

        L = len(keypoints)
        T_w2c = torch.eye(4).unsqueeze(0).repeat(L, 1, 1)
        data = {
            'meta': [{'vid': 'clip'}], 'length': torch.tensor(L),
            'bbx_xys': torch.as_tensor(np.asarray(bbx_xys), dtype=torch.float32),
            'kp2d': torch.as_tensor(np.asarray(keypoints), dtype=torch.float32),
            'K_fullimg': estimate_K(width, height).repeat(L, 1, 1),
            'cam_angvel': compute_cam_angvel(T_w2c[:, :3, :3]), 'cam_tvel': compute_cam_tvel(T_w2c[:, :3, 3]),
            'R_w2c': T_w2c[:, :3, :3], 'T_w2c': T_w2c,
            'f_imgseq': torch.zeros(L, 1024) if features is None else torch.as_tensor(np.asarray(features), dtype=torch.float32),
            'noisy_pred_cam': None if pred_cam is None else torch.as_tensor(np.asarray(pred_cam), dtype=torch.float32),
            'has_text': torch.tensor([False]),
            'mask': {'valid': torch.ones(L).bool(), 'has_img_mask': torch.full((L,), features is not None), 'has_2d_mask': torch.ones(L).bool(),
                     'has_cam_mask': torch.ones(L).bool(), 'has_audio_mask': torch.zeros(L).bool(), 'has_music_mask': torch.zeros(L).bool()},
        }
        torch.manual_seed(0)  # DDIM is deterministic for a given seed
        # The sampler switch is the denoiser's: the pipeline's own regression_only attribute is never read (the
        # engine set that one for months, so it always ran the checkpoint's regression). Under validation:
        # POSE_CAPTURE_SAMPLER=ddim samples 50 DDIM steps instead.
        self.model.pipeline.denoiser3d.regression_only = os.environ.get('POSE_CAPTURE_SAMPLER', 'regression') != 'ddim'
        return self.model.predict(data, static_cam=True, postproc=True)

    def rest_height(self, identity_coeffs, scale_params):
        """Body height in metres: rest-pose HeadEnd above the lowest joint (same measure as the mannequin)."""
        import torch
        identity = torch.as_tensor(np.asarray(identity_coeffs), dtype=torch.float32)[None]
        scale = torch.as_tensor(np.asarray(scale_params), dtype=torch.float32)[None]
        rest = self.model.body_model.get_skeleton(identity, scale)[0].numpy()
        return float(rest[7, 1] - rest[:, 1].min())

    def _solve(self, keypoints, bbx_xys, width, height):
        import torch
        L = self.frames  # a photo is a short static clip; the middle frame is the answer
        pred = self.predict(np.repeat(np.asarray(keypoints)[None], L, 0), np.repeat(np.asarray(bbx_xys)[None], L, 0), width, height)
        mid = L // 2
        out = {}
        for frame in ('incam', 'global'):
            params = {k: v.detach().cpu() for k, v in pred[f'body_params_{frame}'].items() if torch.is_tensor(v)}
            out[frame] = {k: v[mid].numpy().astype(np.float64) for k, v in params.items()}
            joints = self.model.body_model(**{k: v[mid:mid + 1].float() for k, v in params.items()})['joints']
            out[frame]['joints'] = joints.reshape(77, 3).numpy().astype(np.float64)
        out['K'] = pred['K_fullimg'][mid].numpy().astype(np.float64)
        out['rest_height'] = self.rest_height(out['incam']['identity_coeffs'], out['incam']['scale_params'])
        return out

    def _fit(self, solved, keypoints, bbx_xys):
        """Pull the GEM-X pose onto the person's own keypoints; joints are recomputed in both frames."""
        import torch
        from .refine import carry_world, fit_pose, keypoint_weights

        incam, world = solved['incam'], solved['global']
        shape = {k: torch.as_tensor(v, dtype=torch.float32)[None] for k, v in incam.items() if k not in ('joints', 'global_orient', 'body_pose')}

        def forward(global_orient, body_pose):
            return self.model.body_model(**shape, global_orient=global_orient, body_pose=body_pose)['joints'].reshape(-1, 3)

        orient, pose, info = fit_pose(forward, incam['global_orient'], incam['body_pose'], keypoints, solved['K'],
                                      bbx_xys[2], keypoint_weights(keypoints, self.joint_names))
        solved['fit'] = info
        if not info['accepted']:
            return
        world['global_orient'] = carry_world(world['global_orient'], incam['global_orient'], orient)
        incam['global_orient'], incam['body_pose'], world['body_pose'] = orient, pose, pose.copy()
        for frame in (incam, world):
            params = {k: torch.as_tensor(v, dtype=torch.float32)[None] for k, v in frame.items() if k != 'joints'}
            frame['joints'] = self.model.body_model(**params)['joints'].reshape(77, 3).numpy().astype(np.float64)

    def recognize(self, image_rgb, max_people=6, progress=None):
        from gem.utils.geo_transform import get_bbx_xys_from_xyxy
        import torch

        report = progress or (lambda stage: None)
        height, width = image_rgb.shape[:2]
        report('检测人物')
        boxes, scores = self.detector.detect(np.ascontiguousarray(image_rgb[..., ::-1]))
        order = np.argsort(-(boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1]))[:max_people] if len(boxes) else []
        people = []
        for rank, i in enumerate(order):
            box = boxes[i].astype(np.float64)
            box[[0, 2]] = box[[0, 2]].clip(0, width - 1)
            box[[1, 3]] = box[[1, 3]].clip(0, height - 1)
            bbx_xys = get_bbx_xys_from_xyxy(torch.as_tensor(box, dtype=torch.float32)[None], base_enlarge=1.2)[0].numpy()
            report(f'识别姿势 {rank + 1}/{len(order)}')
            keypoints = self._keypoints(image_rgb, bbx_xys)
            solved = self._solve(keypoints, bbx_xys, width, height)
            report(f'贴合关键点 {rank + 1}/{len(order)}')
            self._fit(solved, keypoints, bbx_xys)
            people.append({'box_xyxy': box, 'score': float(scores[i]), 'bbx_xys': bbx_xys.astype(np.float64),
                           'keypoints': keypoints.astype(np.float64), **solved})
        return {'width': width, 'height': height, 'people': people}

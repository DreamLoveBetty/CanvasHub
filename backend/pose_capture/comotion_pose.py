"""CoMotion's bodies as GEM-X's starting pose (worker only; docs/POSE_REFERENCE_REBUILD_PLAN.md §31–32).

GEM-X lite reads keypoints only, so a back view, a body half out of frame or legs seen alone could come out folded
(an arm over the head, a head folded down onto the legs). CoMotion reads the image; with its body as the start,
out-of-frame leg folding fell from 9 % to 5 % of frames on the 29-clip evaluation (full-body dance 50 % -> 3 %) and
jitter from 206 to 176 m/s^3. The product's keypoint fit, image evidence, leg hold and placement follow unchanged.

Per CoMotion track id: the SMPL meshes are inverted to SOMA rotations (py-soma-x PoseInversion on an SMPL identity,
SOMA's SMPL wrap in gemx/inputs/soma_assets/SMPL), turned from absolute local rotations into GEM-X's T-pose-relative
convention, and written over GEM-X's body joints; fingers keep GEM-X's. Then:
  * CoMotion's poses are raw per frame (two to three times GEM-X's jerk): rotations and Hips get the product's local
    linear smoothing over SMOOTH_SECONDS first;
  * GEM-X's skeleton is a different height from the SMPL body (1.91 vs 1.54 m on one walker; left as it was, limbs
    missed VitPose by 6.6 % of the box instead of 2.4 %), so the Hips position scales by that height ratio, and the
    depth by f_gem / f_comotion for GEM-X's focal length: the figure keeps its image position and size;
  * the world orientation follows through GEM-X's own camera-to-world rotation of each frame, so the gravity
    estimate (scene.camera_to_world) is unchanged.
Frames inside the track without a CoMotion row are interpolated from its neighbours (ends hold).
"""
import numpy as np

from .contracts import COMOTION_SMPL

SMOOTH_SECONDS = 0.06


class StartPose:
    def __init__(self, photo, component):
        import torch
        from soma import SOMALayer
        from soma.fitting.pose_inversion import PoseInversion
        from soma.geometry.rig_utils import precompute_joint_orient
        self.torch, self.PoseInversion, self.photo = torch, PoseInversion, photo
        self.layer = SOMALayer(data_root=component / 'gemx' / 'inputs' / 'soma_assets', device='cpu', identity_model_type='smpl',
                               mode='dense', lod='low', enable_procedural_transforms=False, correctives_model_path=None,
                               identity_model_kwargs={'num_betas': 10, 'model_path': component / COMOTION_SMPL})
        soma = photo.model.body_model.soma
        orient, orient_parent_t = precompute_joint_orient(soma.t_pose_world[soma.public_transform_joint_indices], soma.public_joint_parent_ids)
        self.orient, self.orient_parent_t = orient[1:], orient_parent_t[1:]   # without the virtual Root
        names = list(photo.joint_names)
        self.body = np.array([not ('Hand' in n and n not in ('LeftHand', 'RightHand')) for n in names])
        self.head_end = names.index('HeadEnd')

    def _invert(self, verts, betas):
        """SMPL meshes of one identity -> (T-pose-relative rotation vectors (F, 77, 3), Hips (F, 3), rest height)."""
        from scipy.spatial.transform import Rotation
        from soma.geometry.rig_utils import remove_joint_orient_local
        torch = self.torch
        inv = self.PoseInversion(self.layer, low_lod=False)
        inv.prepare_identity(torch.as_tensor(betas, dtype=torch.float32)[None])
        res = inv.fit(torch.as_tensor(verts, dtype=torch.float32), batch_size=64)
        rel = remove_joint_orient_local(res['rotations'][:, 1:], self.orient, self.orient_parent_t).detach().numpy()
        rotvec = Rotation.from_matrix(rel.reshape(-1, 3, 3)).as_rotvec().reshape(len(rel), -1, 3)
        rest = self.layer.pose(torch.zeros(1, 77, 3), apply_correctives=False)['joints'][0].detach().numpy()
        return rotvec, res['root_translation'].detach().numpy().astype(np.float64), float(rest[self.head_end, 1] - rest[:, 1].min())

    def start(self, pred, bodies, mesh, length, width, height, fps):
        """GEM-X's prediction for one track (L = length frames) with its CoMotion bodies as the pose, in place."""
        from scipy.spatial.transform import Rotation
        from .video import interpolate_quats, interpolate_rows, smooth_series
        torch = self.torch
        incam, world = pred['body_params_incam'], pred['body_params_global']
        gem_height = self.photo.rest_height(np.median(incam['identity_coeffs'].detach().cpu().numpy().reshape(length, -1), 0),
                                            np.median(incam['scale_params'].detach().cpu().numpy().reshape(length, -1), 0))
        rotvec, hips = np.zeros((len(bodies['offset']), 77, 3)), np.zeros((len(bodies['offset']), 3))
        for tid in np.unique(bodies['id']):   # a stitched track can hold several CoMotion ids, each its own build
            rows = bodies['id'] == tid
            verts = mesh(bodies['betas'][rows], bodies['pose'][rows], bodies['trans'][rows])
            rotvec[rows], hips[rows], smpl_height = self._invert(verts, bodies['betas'][rows].mean(0))
            hips[rows] *= gem_height / smpl_height
        f_gem = float(pred['K_fullimg'][0][0, 0])
        hips[:, 2] *= f_gem / (2.0 * max(width, height))
        keys = bodies['offset']
        if len(keys) < 2:
            return pred
        quats = Rotation.from_rotvec(rotvec.reshape(-1, 3)).as_quat().reshape(len(keys), -1, 4)
        for k in range(1, len(quats)):
            quats[k, np.sum(quats[k] * quats[k - 1], -1) < 0] *= -1
        quats = smooth_series(quats, keys, fps, SMOOTH_SECONDS)
        new = Rotation.from_quat(interpolate_quats(quats, keys, length).reshape(-1, 4)).as_rotvec().reshape(length, -1, 3)
        hips = interpolate_rows(smooth_series(hips, keys, fps, SMOOTH_SECONDS), keys, length)
        pose = np.concatenate([incam['global_orient'].detach().cpu().numpy().reshape(length, 1, 3),
                               incam['body_pose'].detach().cpu().numpy().reshape(length, -1, 3)], 1)
        pose[:, self.body] = new[:, self.body]
        world_from_cam = Rotation.from_rotvec(world['global_orient'].detach().cpu().numpy().reshape(length, 3)) * \
            Rotation.from_rotvec(incam['global_orient'].detach().cpu().numpy().reshape(length, 3)).inv()
        world_orient = (world_from_cam * Rotation.from_rotvec(pose[:, 0])).as_rotvec()

        def put(params, name, value):
            old = params[name]
            params[name] = torch.as_tensor(value, dtype=old.dtype, device=old.device).reshape(old.shape)
        put(incam, 'global_orient', pose[:, 0]); put(incam, 'body_pose', pose[:, 1:]); put(incam, 'transl', hips)
        put(world, 'global_orient', world_orient); put(world, 'body_pose', pose[:, 1:])
        return pred

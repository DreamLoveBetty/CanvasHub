"""Pose capture contracts: pinned GEM-X source and models, bounded uploads and requests.

Clients send photo or video bytes and a person limit only; never paths, URLs or model choices.
"""
import re

ENGINE = 'gem-x-lite-photo-1'
GEMX_REPO = 'https://github.com/NVlabs/GEM-X.git'
GEMX_COMMIT = '32992550dba114c62243fb55e361311972dce8f9'
HF = 'https://huggingface.co/nvidia/GEM-X/resolve/5b9a69d5ed4713ac4ba2a63b335e66db87279a3e/'
# SOMA 0.1.3 rig assets GEM-X was trained with (NVlabs/SOMA-X, Git LFS); py-soma-x 0.3.4 runs them
# on its legacy path. They differ from the mannequin's 0.3.4 assets in components/pose-soma.
SOMA_LFS = 'https://media.githubusercontent.com/media/NVlabs/SOMA-X/e0f8ff0ecfa3edbbb6058b1e0f08822ee2f84ee5/assets/'
YOLOX_ZIP = {'url': 'https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/yolox_x_8xb8-300e_humanart-a39d44ed.zip',
             'size': 368200375, 'sha256': '1c6fccc5cd450eb563b1fe4eba13c9bdf9ea8263b6ae1cb3ada765aa4ebea2c7',
             'member': '20230928/yolox_onnx/yolox_x_8xb8-300e_humanart-a39d44ed/end2end.onnx'}
YOLOX_ONNX = 'models/yolox_x_humanart.onnx'
# Paths are relative to the component directory; GEM-X reads gemx/inputs/ relative to its checkout.
MODEL_FILES = {
    'gemx/inputs/pretrained/gem_soma.ckpt': (HF + 'gem_soma.ckpt', 541758499,
                                             '4c1f85ca8c1e11e6588aead49fbc024bf660708def670043e0b537c101ee298e'),
    'gemx/inputs/onnx/vitpose.onnx': (HF + 'onnx/vitpose.onnx', 4279801,
                                      '0982dbf4f1e8a48446a6fe35329711522b60210cce2a7499ca6ab93458c87f34'),
    'gemx/inputs/onnx/vitpose.onnx.data': (HF + 'onnx/vitpose.onnx.data', 3389390848,
                                           'b20ba3077ba2341d76c16dde3e58d3b37c66c3b0ec8346901a8bac14319e20fe'),
    'gemx/inputs/soma_data/scale_mean.pth': (HF + 'scale_mean.pth', 1451,
                                             'f696a0793217f27fcf23fa1fd63e8a34aa74ef64580078698fb9ea7322ce2891'),
    'gemx/inputs/soma_data/scale_comps.pth': (HF + 'scale_comps.pth', 8816,
                                              '4c4861384b176fbe3d3bd7480e87ff8161f19553bf6ec1b718bc9b6bbb559cd6'),
    'gemx/inputs/soma_assets/SOMA_neutral.npz': (SOMA_LFS + 'SOMA_neutral.npz', 27488638,
                                                 '515f7d5bb74be4e370e9adf5e779760ec3581556374c0b33212a32d13ab3b53f'),
    'gemx/inputs/soma_assets/MHR/SOMA_wrap_lod1.obj': (SOMA_LFS + 'MHR/SOMA_wrap_lod1.obj', 1816801,
                                                       '9ab7a2328d5b026c17ef1d09ed692ffeb68f96d3fc74970cba72e667dbe0f728'),
    'gemx/inputs/soma_assets/MHR/base_body_lod6.obj': (SOMA_LFS + 'MHR/base_body_lod6.obj', 39006,
                                                       'cd46620ec46e968658527f25e2b54b8f2292bfd486eac59c596f8b5d5229b9e0'),
    'gemx/inputs/soma_assets/MHR/mhr_model_lod6.pt': (SOMA_LFS + 'MHR/mhr_model_lod6.pt', 2080751,
                                                     '28839b7ee0eb38eb3943cf26cff61a306de78f86227a0f17bb044252c7bc06ac'),
    YOLOX_ONNX: (None, 396283264, '8e9ea96a176bd48501eaaa77216e49ee30794d2f8ba80c7b9862beca4ea972da'),
}
# Image evidence for video (docs/POSE_REFERENCE_REBUILD_PLAN.md §22): SAM 3D Body reads the frames and supplies
# arm depth and finger shape. Its code is GEM-X's pinned submodule; its DINOv3 backbone architecture is
# fetched by torch.hub from GitHub main upstream, so a fixed DINOv3 commit is checked out and loaded locally.
SAM3DB_REPO = 'https://github.com/facebookresearch/sam-3d-body.git'
SAM3DB_COMMIT = 'b5c765a0d89d789985e186d396315e7590887b94'   # gemx third_party/sam-3d-body gitlink
SAM3DB_DIR = 'gemx/third_party/sam-3d-body'
DINOV3_REPO = 'https://github.com/facebookresearch/dinov3.git'
DINOV3_COMMIT = '6876159a11b4df116f30f667f8c9888617df0751'
DINOV3_DIR = 'dinov3'
EVIDENCE_CHECKPOINT = 'gemx/inputs/checkpoints/sam-3d-body-dinov3/sam3d_body.ckpt'
EVIDENCE_MHR = 'gemx/inputs/mhr_data/mhr_model.pt'
EVIDENCE_FILES = {
    EVIDENCE_CHECKPOINT: (HF + 'sam3d_body.ckpt', 2109129346, 'b5a2f9d305dd02626b967aa2e86021fba07065df66ce7a7e00ffb9664f150abf'),
    'gemx/inputs/checkpoints/sam-3d-body-dinov3/model_config.yaml': (HF + 'model_config.yaml', 1488,
                                                                     '1012fc3f39cb5e90e3f8fbadf7bded31604bfafdce0321d17a7c1a2d3f08b88d'),
    EVIDENCE_MHR: (HF + 'mhr_model.pt', 696110248, '352e271a6c42729c68554ceaea0c955e866970160c31e35506d782dc0f7377bc'),
}
EVIDENCE_ENGINE = 'sam-3d-body@' + SAM3DB_COMMIT[:7]
# CoMotion multi-person tracking for video (docs/POSE_REFERENCE_REBUILD_PLAN.md §32): Apple's code at a fixed commit,
# the two PyTorch modules of its demo checkpoint archive (the archive's CoreML detector is not used: coremltools has
# no stable Python 3.14 build, and the PyTorch detector on MPS gives the same tracks), the neutral SMPL model it reads
# (a SMPLer-X Space mirror at a fixed revision; the pickle was inspected before pinning), and SOMA's SMPL wrap, which
# turns its bodies into SOMA rotations for GEM-X.
COMOTION_REPO = 'https://github.com/apple-aiml-research/ml-comotion.git'
COMOTION_COMMIT = '04b035af79a68267f6bb722b61bf5f13cb2b0068'
COMOTION_DIR = 'comotion'
COMOTION_DATA = COMOTION_DIR + '/src/comotion_demo/data/'
COMOTION_ARCHIVE = {'url': 'https://ml-site.cdn-apple.com/models/comotion/demo_checkpoints.tar.gz', 'size': 2340177311,
                    'sha256': 'ccf5a8f71a70dcf0e16478ea8bf95b26bea896ce3390e86d1dfefefbbdbedc9c'}
COMOTION_SMPL = COMOTION_DATA + 'smpl/SMPL_NEUTRAL.pkl'
COMOTION_FILES = {
    COMOTION_DATA + 'comotion_detection_checkpoint.pt': (None, 1076106274,
                                                         '519b7f8f2a649c3847b100f439c8d4cf63e47705a6c4597d4faaea7c58ad36cb'),
    COMOTION_DATA + 'comotion_refine_checkpoint.pt': (None, 385542209,
                                                      '50da0d13462886b4b79319d06bbca0c293ca528b1a341bdc108a93df234ff6c4'),
    COMOTION_SMPL: ('https://huggingface.co/spaces/caizhongang/SMPLer-X/resolve/7b2c5056aeb68064f18827069483135e0ed827c3/'
                    'common/utils/human_model_files/smpl/SMPL_NEUTRAL.pkl', 247186228,
                    '4924f235e63f7c5d5b690acedf736419c2edb846a2d69fc0956169615fa75688'),
    'gemx/inputs/soma_assets/SMPL/base_body.obj': (SOMA_LFS + 'SMPL/base_body.obj', 457369,
                                                   '08996c762b0adfe45aeb4d6297c9b93d460484b09815674d36a3a544d64e0c43'),
    'gemx/inputs/soma_assets/SMPL/SOMA_wrap.obj': (SOMA_LFS + 'SMPL/SOMA_wrap.obj', 2731479,
                                                   'd56c7d1452a57b3f1950cfe9b81fec483b3a8e7a9a85bdc4ea83f2996e1a58da'),
}
COMOTION_ENGINE = 'comotion@' + COMOTION_COMMIT[:7]

ACTIVE = {'queued', 'running', 'cancelling'}
MAX_UPLOAD = 20 * 1024 * 1024
MAX_VIDEO_UPLOAD = 200 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_PEOPLE = 6
# Video: the first MAX_SECONDS are recognised (15 s takes ~50 s for one person, ~3 min for four);
# MAX_VIDEO_PEOPLE keeps four-person clips inside that budget (docs/POSE_REFERENCE_REBUILD_PLAN.md §20).
MAX_SECONDS = 30
MAX_VIDEO_PEOPLE = 4
# Container signatures accepted as video: ISO BMFF (mp4 / mov / m4v) and Matroska / WebM.
VIDEO_SIGNATURES = (('.mp4', lambda d: d[4:8] == b'ftyp' and d[8:12] not in (b'qt  ',)),
                    ('.mov', lambda d: d[4:8] == b'ftyp' and d[8:12] == b'qt  '),
                    ('.webm', lambda d: d[:4] == b'\x1a\x45\xdf\xa3'))


def video_suffix(data):
    """File suffix for an accepted video container, or None when the bytes are not a video."""
    head = bytes(data[:16])
    return next((suffix for suffix, test in VIDEO_SIGNATURES if len(head) >= 12 and test(head)), None)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
        raise ValueError('无效识别任务标识')
    return value


def normalize(body, kind='photo'):
    """Validate a submit request; `kind` is the stored asset's kind (photo | video), never the client's word."""
    if not isinstance(body, dict):
        raise ValueError('请求必须为对象')
    if set(body) - {'asset_id', 'max_people', 'evidence'}:
        raise ValueError('包含不支持的识别参数')
    evidence = body.get('evidence', True)
    if not isinstance(evidence, bool):
        raise ValueError('影像证据开关须为布尔值')
    limit = MAX_VIDEO_PEOPLE if kind == 'video' else MAX_PEOPLE
    people = body.get('max_people', limit)
    if isinstance(people, bool) or not isinstance(people, int) or people < 1:
        raise ValueError(f'人数上限须为 1–{limit}')
    return {'asset_id': identifier(body.get('asset_id')), 'max_people': min(people, limit), 'mode': kind,
            **({'evidence': evidence} if kind == 'video' else {})}

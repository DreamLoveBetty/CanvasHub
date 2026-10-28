"""SOMA rig arrays -> skinned glTF binary (numpy only; no SOMA/torch import).

Input rig (meters, Y up):
  names (J,), parents (J,) with -1 for roots, bind_world (J,4,4), orient (J,3,3) T-pose world
  orientation, rest (V,3), faces (F,3), weights (V,J).
Output: one skinned mesh, top-4 influences (the three.js limit), a node hierarchy in joint order and
scene extras `soma` with what the editor needs to pose it:
  bone_local = conj(O[parent]) * R_rel * O[joint], Hips translated to `hips_translation`;
  `body`, `head_end` and `height_ratio` (rest height / neutral rest height) for height scaling.
"""
import json
import struct

import numpy as np

GLTF_FLOAT, GLTF_USHORT, GLTF_UINT = 5126, 5123, 5125
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963


def quat_xyzw(matrix):
    """Rotation matrix -> unit quaternion (x, y, z, w), Shepperd's method."""
    m = np.asarray(matrix, dtype=np.float64)
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0:
        s = 2.0 * np.sqrt(trace + 1.0)
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
        q = [0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
    elif m[1, 1] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
        q = [(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
    else:
        s = 2.0 * np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
        q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]
    q = np.asarray(q)
    q /= np.linalg.norm(q)
    return q if q[3] >= 0 else -q


def local_from_world(world, parents):
    local = np.empty_like(world)
    for j, p in enumerate(parents):
        local[j] = world[j] if p < 0 else np.linalg.inv(world[p]) @ world[j]
    return local


def top4(weights):
    joints = weights.shape[1]
    if joints < 4:  # glTF VEC4 influences: pad small rigs with zero-weight slots
        weights = np.pad(weights, ((0, 0), (0, 4 - joints)))
    idx = np.argsort(-weights, axis=1, kind='stable')[:, :4]
    w = np.take_along_axis(weights, idx, axis=1)
    idx[idx >= joints] = 0  # padded slots carry zero weight; keep their index in range
    w = w / w.sum(axis=1, keepdims=True)
    return idx.astype(np.uint16), w.astype(np.float32)


def vertex_normals(vertices, faces):
    normals = np.zeros_like(vertices)
    face_normals = np.cross(vertices[faces[:, 1]] - vertices[faces[:, 0]], vertices[faces[:, 2]] - vertices[faces[:, 0]])
    for k in range(3):
        np.add.at(normals, faces[:, k], face_normals)
    return normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)


def validate_rig(rig):
    names, parents = list(rig['names']), np.asarray(rig['parents'])
    joints = len(names)
    if joints < 2 or names[1] != 'Hips' or len(set(names)) != joints:
        raise ValueError('骨架关节名称无效')
    if parents.shape != (joints,) or any(not -1 <= p < j for j, p in enumerate(parents)):
        raise ValueError('骨架父关节必须按拓扑顺序排列')
    for key, shape in (('bind_world', (joints, 4, 4)), ('orient', (joints, 3, 3))):
        if np.asarray(rig[key]).shape != shape:
            raise ValueError(f'{key} 形状无效')
    rest, faces, weights = (np.asarray(rig[k]) for k in ('rest', 'faces', 'weights'))
    if rest.ndim != 2 or rest.shape[1] != 3 or faces.ndim != 2 or faces.shape[1] != 3 or weights.shape != (len(rest), joints):
        raise ValueError('网格或权重形状无效')
    if faces.min() < 0 or faces.max() >= len(rest) or not np.all(weights.sum(axis=1) > 0):
        raise ValueError('网格索引或权重无效')


def build_glb(rig, generator='canvashub-pose-scene'):
    validate_rig(rig)
    names = [str(n) for n in rig['names']]
    parents = np.asarray(rig['parents'], dtype=np.int64)
    bind_world = np.asarray(rig['bind_world'], dtype=np.float64)
    local = local_from_world(bind_world, parents)
    rest = np.asarray(rig['rest'], dtype=np.float64)
    faces = np.asarray(rig['faces'], dtype=np.int64)
    joints4, weights4 = top4(np.asarray(rig['weights'], dtype=np.float64))
    # glTF matrices are column-major.
    inverse_bind = np.stack([np.linalg.inv(m).T for m in bind_world]).astype(np.float32)

    blobs, views, accessors = [], [], []

    def add(data, component, kind, target=None, minmax=False):
        raw = np.ascontiguousarray(data).tobytes()
        offset = sum(len(b) for b in blobs)
        blobs.append(raw + b'\0' * ((-len(raw)) % 4))
        view = {'buffer': 0, 'byteOffset': offset, 'byteLength': len(raw)}
        if target: view['target'] = target
        views.append(view)
        accessor = {'bufferView': len(views) - 1, 'componentType': component, 'count': int(data.shape[0]), 'type': kind}
        if minmax:
            accessor['min'] = data.min(axis=0).astype(float).tolist()
            accessor['max'] = data.max(axis=0).astype(float).tolist()
        accessors.append(accessor)
        return len(accessors) - 1

    position = add(rest.astype(np.float32), GLTF_FLOAT, 'VEC3', ARRAY_BUFFER, minmax=True)
    normal = add(vertex_normals(rest, faces).astype(np.float32), GLTF_FLOAT, 'VEC3', ARRAY_BUFFER)
    joint_index = add(joints4, GLTF_USHORT, 'VEC4', ARRAY_BUFFER)
    joint_weight = add(weights4, GLTF_FLOAT, 'VEC4', ARRAY_BUFFER)
    indices = add(faces.reshape(-1).astype(np.uint32), GLTF_UINT, 'SCALAR', ELEMENT_ARRAY_BUFFER)
    inverse = add(inverse_bind.reshape(len(names), 16), GLTF_FLOAT, 'MAT4')

    nodes = []
    for j, name in enumerate(names):
        node = {'name': name, 'translation': local[j][:3, 3].tolist(), 'rotation': quat_xyzw(local[j][:3, :3]).tolist()}
        children = [int(c) for c in np.where(parents == j)[0]]
        if children: node['children'] = children
        nodes.append(node)
    mesh_node = len(nodes)
    nodes.append({'name': 'soma_body', 'mesh': 0, 'skin': 0})
    roots = [int(j) for j in np.where(parents < 0)[0]]
    soma = {
        'glb_version': int(rig.get('glb_version', 1)), 'release': str(rig.get('release', '')), 'lod': str(rig.get('lod', '')),
        'joint_names': names, 'parents': parents.tolist(),
        'orient_xyzw': [quat_xyzw(m).tolist() for m in np.asarray(rig['orient'], dtype=np.float64)],
        'hips_translation': bind_world[1][:3, 3].tolist(),
        # Body preset or recognised identity, and its rest height relative to the neutral mannequin:
        # the editor scales a figure by height_cm / 175 / height_ratio so height_cm means the same for every body.
        'body': str(rig.get('body', 'neutral')), 'head_end': float(rig.get('head_end', 0.0)),
        'height_ratio': float(rig.get('height_ratio', 1.0)),
    }
    document = {
        'asset': {'version': '2.0', 'generator': generator},
        'scene': 0,
        'scenes': [{'nodes': roots + [mesh_node], 'extras': {'soma': soma}}],
        'nodes': nodes,
        'meshes': [{'name': 'soma_body', 'primitives': [{
            'attributes': {'POSITION': position, 'NORMAL': normal, 'JOINTS_0': joint_index, 'WEIGHTS_0': joint_weight},
            'indices': indices, 'material': 0}]}],
        'materials': [{'name': 'clay', 'pbrMetallicRoughness': {'baseColorFactor': [0.72, 0.72, 0.74, 1.0], 'metallicFactor': 0.0, 'roughnessFactor': 0.85}}],
        'skins': [{'name': 'soma', 'joints': list(range(len(names))), 'skeleton': roots[0], 'inverseBindMatrices': inverse}],
        'accessors': accessors,
        'bufferViews': views,
        'buffers': [{'byteLength': sum(len(b) for b in blobs)}],
    }
    json_chunk = json.dumps(document, separators=(',', ':')).encode()
    json_chunk += b' ' * ((-len(json_chunk)) % 4)
    bin_chunk = b''.join(blobs)
    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    return b''.join([struct.pack('<4sII', b'glTF', 2, total), struct.pack('<I4s', len(json_chunk), b'JSON'), json_chunk,
                     struct.pack('<I4s', len(bin_chunk), b'BIN\0'), bin_chunk])


def read_glb(data):
    """Parse a GLB written by build_glb: (document, binary chunk). Used by tests and status checks."""
    magic, version, total = struct.unpack_from('<4sII', data, 0)
    if magic != b'glTF' or version != 2 or total != len(data):
        raise ValueError('不是有效的 GLB 文件')
    json_length, json_type = struct.unpack_from('<I4s', data, 12)
    if json_type != b'JSON':
        raise ValueError('GLB 缺少 JSON 区块')
    document = json.loads(data[20:20 + json_length])
    offset = 20 + json_length
    binary = b''
    if offset < len(data):
        bin_length, bin_type = struct.unpack_from('<I4s', data, offset)
        if bin_type != b'BIN\0':
            raise ValueError('GLB 二进制区块无效')
        binary = data[offset + 8: offset + 8 + bin_length]
    return document, binary

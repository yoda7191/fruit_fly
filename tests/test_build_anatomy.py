"""The anatomy builder: PLY reading, skeleton simplification and the morphology file."""

import importlib.util
import io
import json
import struct
import zipfile
from pathlib import Path

import numpy as np

_spec = importlib.util.spec_from_file_location(
    "build_anatomy", Path(__file__).resolve().parents[1] / "scripts" / "build_anatomy.py")
ba = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ba)


def decode(body: bytes) -> list[tuple[str, np.ndarray, np.ndarray]]:
    """Reference reader of mb_morphology.bin (the viewer's decodeMorphology does the
    same): per neuron its root id, vertex positions (nm) and parents (-1: root)."""
    assert body[:8] == ba.MAGIC
    (h,) = struct.unpack_from("<I", body, 8)
    head = json.loads(body[12:12 + h])
    v = sum(head["vertices"])
    off = 12 + h
    d = np.frombuffer(body, "<i2", 3 * v, off).reshape(3, v).T.astype(np.int64)
    up = np.frombuffer(body, "<u2", v, off + 6 * v).astype(np.int64)
    roots = np.frombuffer(body, "<u2", 3 * head["roots"], off + 8 * v).reshape(-1, 3).astype(np.int64)
    q = np.zeros((v, 3), np.int64)
    r = 0
    for i in range(v):
        if up[i] == 0:
            q[i] = roots[r]
            r += 1
        else:
            q[i] = q[i - up[i]] + d[i]
    pos = np.asarray(head["origin"]) + q * head["step_nm"]
    out, start = [], 0
    for rid, n in zip(head["root_id"], head["vertices"]):
        local = np.arange(n)
        parent = np.where(up[start:start + n] > 0, local - up[start:start + n], -1)
        out.append((rid, pos[start:start + n], parent))
        start += n
    return out


def skeleton_bytes(verts, edges) -> bytes:
    verts = np.asarray(verts, "<f4")
    edges = np.asarray(edges, "<u4")
    radius = np.ones(len(verts), "<f4")
    return struct.pack("<II", len(verts), len(edges)) + verts.tobytes() + edges.tobytes() + radius.tobytes()


def y_shape():
    """A trunk of 11 points 1 µm apart along x, branching at its end into two arms of
    6 points (1 µm apart, along +y and -y), plus a 1 µm twig halfway along the trunk."""
    verts = [(i * 1000.0, 0, 0) for i in range(11)]
    edges = [(i, i + 1) for i in range(10)]
    for sign in (1, -1):
        prev = 10
        for k in range(1, 7):
            verts.append((10000.0, sign * k * 1000.0, 0))
            edges.append((prev, len(verts) - 1))
            prev = len(verts) - 1
    verts.append((5000.0, 0, 1000.0))                        # the twig, off trunk point 5
    edges.append((5, len(verts) - 1))
    return np.array(verts, np.float32), np.array(edges)


def test_simplify_keeps_shape_points_and_resamples():
    verts, edges = y_shape()
    v, parent = ba.simplify(verts, edges, step_nm=3000, min_twig_nm=0)
    kept = {tuple(p) for p in v.tolist()}
    assert (0, 0, 0) in kept and (10000, 0, 0) in kept               # root and branch point
    assert (10000, 6000, 0) in kept and (10000, -6000, 0) in kept    # tips
    assert (5000, 0, 1000) in kept and (5000, 0, 0) in kept          # twig tip and its branch point
    assert len(v) < len(verts)
    assert (parent < 0).sum() == 1                                   # one tree
    assert all(parent[i] < i for i in range(len(v)) if parent[i] >= 0)   # parents come first
    # no kept segment is longer than the step plus one raw segment
    seg = np.linalg.norm(v[parent >= 0] - v[parent[parent >= 0]], axis=1)
    assert seg.max() <= 3000 + 1000


def test_simplify_drops_short_twigs():
    verts, edges = y_shape()
    v, _ = ba.simplify(verts, edges, step_nm=3000, min_twig_nm=1500)
    kept = {tuple(p) for p in v.tolist()}
    assert (5000, 0, 1000) not in kept                               # the 1 µm twig
    assert (10000, 6000, 0) in kept and (10000, -6000, 0) in kept    # 6 µm arms stay


def test_morphology_round_trip(tmp_path):
    verts, edges = y_shape()
    (tmp_path / "111").write_bytes(skeleton_bytes(verts, edges))
    (tmp_path / "222").write_bytes(skeleton_bytes([(500000, 200000, 100000), (501000, 200000, 100000)], [(0, 1)]))
    body, report = ba.build_morphology(["111", "222", "333"], tmp_path, step_nm=3000, min_twig_nm=0)
    assert report["missing"] == 1
    neurons = decode(body)
    assert [n[0] for n in neurons] == ["111", "222", "333"]
    assert len(neurons[2][1]) == 0                                   # no skeleton: no vertices
    expect, parent = ba.simplify(verts, edges, 3000, 0)
    got = neurons[0]
    step = json.loads(body[12:12 + struct.unpack_from("<I", body, 8)[0]])["step_nm"]
    assert np.abs(got[1] - expect).max() <= step                    # quantised to step_nm
    assert (got[2] == parent).all()
    assert np.allclose(neurons[1][1], [(500000, 200000, 100000), (501000, 200000, 100000)], atol=step)


def test_read_ply_and_regions():
    verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], "<f4")
    header = b"ply\nformat binary_little_endian 1.0\nelement vertex 3\nproperty float x\n" \
             b"property float y\nproperty float z\nelement face 1\nproperty list int int vertex_indices\nend_header\n"
    ply = header + verts.tobytes() + np.array([3, 0, 1, 2], "<i4").tobytes()
    v, f = ba.read_ply(ply)
    assert v.shape == (3, 3) and f.tolist() == [[0, 1, 2]]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("MB_CA_L.ply", ply)
        z.writestr("EB.ply", ply)
        z.writestr("__MACOSX/._EB.ply", b"junk")
    regions = {r["name"]: r for r in ba.build_regions(buf.getvalue())["regions"]}
    assert set(regions) == {"MB_CA_L", "EB"}
    assert regions["MB_CA_L"]["side"] == "left" and regions["MB_CA_L"]["olfactory"]
    assert regions["MB_CA_L"]["label"] == "mushroom body calyx"
    assert regions["EB"]["side"] == "center" and not regions["EB"]["olfactory"]
    assert regions["EB"]["triangles"] == [0, 1, 2]

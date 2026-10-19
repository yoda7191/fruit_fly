"""Build the anatomy files the 3D viewer draws for a FlyWire circuit.

Writes into the circuit folder (next to mb_neurons.csv):

    brain_regions.json   the brain's neuropils (antennal lobe, mushroom body calyx,
                         peduncle and lobes, lateral horn, ...) as triangle meshes
    mb_morphology.bin    every neuron's shape: its skeleton, simplified

and a gzip-compressed copy of each (.gz), which the server sends as is to browsers
that accept gzip instead of compressing 15 MB on every request.

Both are in FlyWire's coordinate space (nanometres), the space of the x, y, z
columns of mb_neurons.csv, so the viewer can draw them together. A circuit
without them (the synthetic one) is drawn as one dot per neuron.

Sources
    Neuropil meshes: FlyWire's region meshes (the JFRC2 neuropil standard of Ito et
    al. 2014, transformed into FlyWire space; Dorkenwald et al. 2024), as packaged
    by the fafbseg-py project.
    Skeletons: scripts/download_skeletons.py (FlyWire v783, Schlegel et al. 2024).

Simplification
    A raw skeleton has a point every few hundred nanometres (~2,000 per neuron, 17
    million for the whole circuit, too many for a browser). Keep the points where
    the shape matters (branch points, tips, and the root), and along each unbranched
    stretch between them only one point every --step-nm of path length. Twigs (tips)
    shorter than --min-twig-nm are dropped first (three passes, as removing
    twigs turns some branches into new twigs).

File format of mb_morphology.bin (little-endian)
    8 bytes   b"FFMORPH2"
    uint32    length H of the JSON header
    H bytes   JSON {"origin": [x, y, z], "step_nm": s, "root_id": [str, ...],
                    "vertices": [count per neuron, ...], "roots": R},
              padded with spaces to a multiple of 4
    then, for all V vertices of all neurons one after another (each neuron's
    vertices depth-first, so a vertex's parent is usually the one before it):
    int16     dx[V], dy[V], dz[V]   offset from the parent, in units of step_nm (0 at roots)
    uint16    up[V]                 steps back to the parent (0: a root, no parent)
    uint16    xyz[R*3]              position of each root in order: nm = origin + q * step_nm
    Positions follow by adding offsets in order. Storing offsets, not positions,
    roughly halves the size once gzip-compressed.

Usage:
    python scripts/download_skeletons.py
    python scripts/build_anatomy.py                       # data/processed
    python scripts/build_anatomy.py --circuit data/processed-aplregional
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import struct
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

NEUROPIL_URL = ("https://raw.githubusercontent.com/navis-org/fafbseg-py/master/"
                "fafbseg/data/JFRC2NP.surf.fw.zip")
NO_PARENT = 0xFFFF
TWIG_PASSES = 3
MAGIC = b"FFMORPH2"

# Plain-language names of the neuropils the olfactory circuit runs through; the
# viewer labels these and draws them more strongly than the rest of the brain.
OLFACTORY_REGIONS = {
    "AL": "antennal lobe",
    "MB_CA": "mushroom body calyx",
    "MB_PED": "mushroom body peduncle",
    "MB_VL": "mushroom body vertical lobe",
    "MB_ML": "mushroom body medial lobe",
    "LH": "lateral horn",
}


# ------------------------------------------------------------------ neuropils
def read_ply(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    """Vertices (V x 3 float32) and triangles (F x 3 int32) of a binary little-endian PLY
    whose faces are "list int int" (the format of the FlyWire neuropil files)."""
    end = data.index(b"end_header\n") + len(b"end_header\n")
    header = data[:end].decode("ascii").splitlines()
    if "format binary_little_endian 1.0" not in header:
        raise ValueError("expected a binary little-endian PLY")
    nv = next(int(h.split()[2]) for h in header if h.startswith("element vertex"))
    nf = next(int(h.split()[2]) for h in header if h.startswith("element face"))
    verts = np.frombuffer(data, "<f4", nv * 3, end).reshape(nv, 3)
    # each face: int32 count (always 3) followed by 3 int32 indices
    faces = np.frombuffer(data, "<i4", nf * 4, end + nv * 12).reshape(nf, 4)
    if not (faces[:, 0] == 3).all():
        raise ValueError("expected triangles only")
    return verts, faces[:, 1:].copy()


def build_regions(zip_bytes: bytes) -> dict:
    """{"units": "nm", "regions": [{name, side, label, olfactory, vertices, triangles}]}.
    Vertices are rounded to whole nanometres (flat lists, to keep the JSON small)."""
    regions = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for info in sorted(z.infolist(), key=lambda i: i.filename):
            name = Path(info.filename).name
            if info.filename.startswith("__MACOSX") or not name.endswith(".ply"):
                continue
            verts, tris = read_ply(z.read(info))
            stem = name[:-4]
            base, _, side = stem.rpartition("_")
            if side not in ("L", "R"):
                base, side = stem, ""                       # midline regions (EB, FB, GNG, ...)
            regions.append({
                "name": stem,
                "region": base,
                "side": {"L": "left", "R": "right"}.get(side, "center"),
                "label": OLFACTORY_REGIONS.get(base, base),
                "olfactory": base in OLFACTORY_REGIONS,
                "vertices": np.rint(verts).astype(np.int64).ravel().tolist(),
                "triangles": tris.ravel().tolist(),
            })
    return {"units": "nm", "source": "FlyWire neuropil meshes (JFRC2 regions)", "regions": regions}


# ------------------------------------------------------------------ skeletons
def read_skeleton(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    """Vertices (V x 3, nm) and edges (E x 2) of a neuroglancer precomputed skeleton."""
    nv, ne = struct.unpack_from("<II", data)
    verts = np.frombuffer(data, "<f4", nv * 3, 8).reshape(nv, 3)
    edges = np.frombuffer(data, "<u4", ne * 2, 8 + nv * 12).reshape(ne, 2).astype(np.int64)
    return verts, edges


def simplify(verts: np.ndarray, edges: np.ndarray, step_nm: float,
             min_twig_nm: float) -> tuple[np.ndarray, np.ndarray]:
    """Simplified skeleton: kept vertices and each one's parent (index into the kept
    vertices, -1 for a root). See the module docstring for the rule."""
    n = len(verts)
    if n == 0:
        return np.zeros((0, 3), np.float32), np.zeros(0, np.int64)
    nbrs: list[list[int]] = [[] for _ in range(n)]
    for a, b in edges.tolist():
        if a != b:
            nbrs[a].append(b)
            nbrs[b].append(a)

    # Orient each connected piece as a tree from a root (breadth-first; a skeleton
    # can have several pieces, and rarely a loop, which this simply cuts).
    parent = np.full(n, -1, np.int64)
    order: list[int] = []
    seen = np.zeros(n, bool)
    for start in range(n):
        if seen[start]:
            continue
        seen[start] = True
        queue = [start]
        while queue:
            v = queue.pop()
            order.append(v)
            for w in nbrs[v]:
                if not seen[w]:
                    seen[w] = True
                    parent[w] = v
                    queue.append(w)

    children = np.zeros(n, np.int64)
    np.add.at(children, parent[parent >= 0], 1)
    seglen = np.zeros(n)
    has_p = parent >= 0
    seglen[has_p] = np.linalg.norm(verts[has_p] - verts[parent[has_p]], axis=1)

    # Drop short twigs: walk up from each tip until a branch point; if that path is
    # shorter than min_twig_nm, remove it (once, so long branches stay intact).
    # Repeated a few times: removing twigs turns some branches into new twigs.
    alive = np.ones(n, bool)
    for _ in range(TWIG_PASSES if min_twig_nm > 0 else 0):
        removed = False
        for tip in np.flatnonzero((children == 0) & alive):
            path, length, v = [], 0.0, int(tip)
            while parent[v] >= 0 and children[v] <= 1:
                path.append(v)
                length += seglen[v]
                v = int(parent[v])
            if path and children[v] > 1 and length < min_twig_nm:
                alive[path] = False
                children[v] -= 1
                removed = True
        if not removed:
            break

    # Keep roots, tips and branch points; along the stretches between them keep one
    # point per step_nm of path length. `order` lists parents before children.
    keep = np.zeros(n, bool)
    since = np.zeros(n)                     # path length since the last kept ancestor
    kept_parent = np.full(n, -1, np.int64)  # nearest kept ancestor (original index)
    for v in order:
        if not alive[v]:
            continue
        p = int(parent[v])
        if p < 0:
            keep[v] = True
            continue
        anc = p if keep[p] else int(kept_parent[p])
        dist = (0.0 if keep[p] else since[p]) + seglen[v]
        if children[v] != 1 or dist >= step_nm:
            keep[v] = True
            kept_parent[v] = anc
        else:
            since[v] = dist
            kept_parent[v] = anc

    # Number the kept vertices depth-first, so a vertex's parent is usually the one just
    # before it: the file stores offsets to the parent, which then compress well.
    kids: dict[int, list[int]] = {}
    roots: list[int] = []
    for v in np.flatnonzero(keep).tolist():
        p = int(kept_parent[v]) if parent[v] >= 0 else -1
        (roots if p < 0 else kids.setdefault(p, [])).append(v)
    dfs: list[int] = []
    stack = roots[::-1]
    while stack:
        v = stack.pop()
        dfs.append(v)
        stack.extend(kids.get(v, [])[::-1])
    new_index = np.full(n, -1, np.int64)
    new_index[dfs] = np.arange(len(dfs))
    out_parent = np.array([new_index[kept_parent[v]] if parent[v] >= 0 else -1 for v in dfs], np.int64)
    return verts[dfs], out_parent


def build_morphology(root_ids: list[str], skeleton_dir: Path, step_nm: float,
                     min_twig_nm: float) -> tuple[bytes, dict]:
    """The mb_morphology.bin bytes, and counts for the report. Neurons without a
    skeleton get 0 vertices (the viewer draws them as a dot)."""
    shapes: list[tuple[np.ndarray, np.ndarray]] = []
    missing = 0
    for rid in root_ids:
        path = skeleton_dir / rid
        if not path.exists():
            shapes.append((np.zeros((0, 3), np.float32), np.zeros(0, np.int64)))
            missing += 1
            continue
        v, p = simplify(*read_skeleton(path.read_bytes()), step_nm, min_twig_nm)
        if len(v) >= NO_PARENT:
            raise ValueError(f"neuron {rid}: {len(v)} vertices after simplifying; raise --step-nm")
        shapes.append((v, p))

    allv = np.concatenate([v for v, _ in shapes]) if shapes else np.zeros((0, 3), np.float32)
    origin = allv.min(axis=0) if len(allv) else np.zeros(3)
    extent = float((allv.max(axis=0) - origin).max()) if len(allv) else 1.0
    q_step = max(1.0, float(np.ceil(extent / 65000)))          # nm per stored unit
    q = np.rint((allv - origin) / q_step).astype(np.int64)

    # per vertex: steps back to its parent (0 = a root) and its offset from the parent
    up_parts, start = [], 0
    for v, p in shapes:
        local = np.arange(len(v))
        up_parts.append(np.where(p >= 0, local - p, 0))
        start += len(v)
    up = np.concatenate(up_parts) if up_parts else np.zeros(0, np.int64)
    gidx = np.arange(len(q))
    parent_global = np.where(up > 0, gidx - up, gidx)
    delta = q - q[parent_global]                                 # 0 at roots
    if len(delta) and np.abs(delta).max() > 32767:
        raise ValueError("a skeleton segment is too long for the int16 offsets")
    root_xyz = q[up == 0]

    header = json.dumps({
        "origin": [float(x) for x in origin], "step_nm": q_step,
        "root_id": root_ids, "vertices": [len(v) for v, _ in shapes], "roots": int(len(root_xyz)),
    }, separators=(",", ":")).encode()
    header += b" " * (-len(header) % 4)
    body = (MAGIC + struct.pack("<I", len(header)) + header
            + delta.T.astype("<i2").tobytes()                   # all dx, then all dy, then all dz
            + up.astype("<u2").tobytes()
            + root_xyz.astype("<u2").tobytes())
    return body, {"neurons": len(root_ids), "missing": missing, "vertices": len(allv), "bytes": len(body)}


# ------------------------------------------------------------------ main
def write_with_gzip(path: Path, data: bytes) -> None:
    """Write `data` to path and a gzip copy to path.gz (mtime 0: reproducible bytes)."""
    path.write_bytes(data)
    Path(f"{path}.gz").write_bytes(gzip.compress(data, compresslevel=9, mtime=0))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--circuit", type=Path, default=Path("data/processed"))
    ap.add_argument("--skeletons", type=Path, default=Path("data/raw/skeletons"))
    ap.add_argument("--neuropils", type=Path, default=Path("data/raw/neuropils.zip"),
                    help="downloaded on first use")
    ap.add_argument("--step-nm", type=float, default=4000, help="spacing of points along unbranched stretches")
    ap.add_argument("--min-twig-nm", type=float, default=4000, help="drop tips shorter than this")
    ap.add_argument("--no-skeletons", action="store_true", help="only the neuropil meshes")
    args = ap.parse_args()

    if not args.neuropils.exists():
        print(f"fetch neuropil meshes -> {args.neuropils}")
        args.neuropils.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(NEUROPIL_URL, timeout=120) as r:
            args.neuropils.write_bytes(r.read())
    regions = build_regions(args.neuropils.read_bytes())
    out = args.circuit / "brain_regions.json"
    write_with_gzip(out, json.dumps(regions, separators=(",", ":")).encode())
    print(f"wrote {out} ({len(regions['regions'])} regions, {out.stat().st_size / 1e6:.1f} MB)")

    if args.no_skeletons:
        return
    with (args.circuit / "mb_neurons.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    # model units that stand for part of a neuron (regional APL) carry its real id
    ids = list(dict.fromkeys(r.get("flywire_id") or r["root_id"] for r in rows))
    body, report = build_morphology(ids, args.skeletons, args.step_nm, args.min_twig_nm)
    out = args.circuit / "mb_morphology.bin"
    write_with_gzip(out, body)
    print(f"wrote {out}: {report['neurons']} neurons ({report['missing']} without a skeleton), "
          f"{report['vertices']:,} points, {report['bytes'] / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

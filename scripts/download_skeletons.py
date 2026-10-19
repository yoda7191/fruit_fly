"""Download the FlyWire v783 skeleton of every neuron in the extracted circuit.

Skeletons are the neurons' real branching shapes (centre lines with a radius per
point), made by the Cambridge FlyConnectome group from the FlyWire meshes
(Dorkenwald et al. 2024; Schlegel et al. 2024) and served in neuroglancer's
precomputed skeleton format:

    uint32 vertex count V, uint32 edge count E,
    float32[V*3] vertex xyz (nm, FlyWire space), uint32[E*2] edges (vertex pairs),
    float32[V] radius (nm)

The download is resumable: files already present are skipped. Neurons with no
skeleton on the server are listed in missing.txt.

Usage:
    python scripts/download_skeletons.py                       # data/processed -> data/raw/skeletons
    python scripts/download_skeletons.py --neurons data/processed-min3/mb_neurons.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

URL = "https://flyem.mrc-lmb.cam.ac.uk/flyconnectome/flywire_skeletons_783/{}"


def fetch(root_id: str, dest: Path, retries: int = 4) -> str:
    """Download one skeleton to dest/<root_id>. Returns "ok", "skip" or "missing"."""
    path = dest / root_id
    if path.exists():
        return "skip"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(URL.format(root_id), timeout=60) as r:
                body = r.read()
            tmp = path.with_suffix(".part")
            tmp.write_bytes(body)
            tmp.rename(path)                     # never leave a half-written file under the real name
            return "ok"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return "missing"
            if attempt == retries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
        time.sleep(2 ** attempt)
    return "missing"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--neurons", type=Path, default=Path("data/processed/mb_neurons.csv"))
    ap.add_argument("--out", type=Path, default=Path("data/raw/skeletons"))
    ap.add_argument("--workers", type=int, default=8, help="parallel downloads (be polite to the server)")
    args = ap.parse_args()

    with args.neurons.open() as f:
        ids = [row["root_id"] for row in csv.DictReader(f)]
    args.out.mkdir(parents=True, exist_ok=True)

    counts = {"ok": 0, "skip": 0, "missing": 0}
    missing: list[str] = []
    with ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(fetch, i, args.out): i for i in ids}
        for n, fut in enumerate(as_completed(futures), 1):
            result = fut.result()
            counts[result] += 1
            if result == "missing":
                missing.append(futures[fut])
            if n % 200 == 0 or n == len(ids):
                print(f"{n}/{len(ids)}  " + "  ".join(f"{k} {v}" for k, v in counts.items()), flush=True)
    (args.out / "missing.txt").write_text("".join(f"{m}\n" for m in sorted(missing)))
    if missing:
        print(f"{len(missing)} neurons have no skeleton (listed in {args.out / 'missing.txt'})", file=sys.stderr)


if __name__ == "__main__":
    main()

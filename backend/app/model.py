"""The loaded model: circuit, odour library and precomputed payloads.

Loaded once at startup and shared by every request. Everything here is
read-only after __init__, so it is safe to use from several worker threads
at once (each experiment builds its own Simulator on top of it).
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

import fruit_fly

from .config import Settings


# DoOR's "Class" column spells some classes several ways; one name each, in plain words.
ODOUR_CLASSES = {
    "ester": "esters", "esters": "esters", "alcohol": "alcohols", "arom": "aromatics",
    "aromatics": "aromatics", "terpene": "terpenes", "terpenes": "terpenes", "acid": "acids",
    "acids": "acids", "ketone": "ketones", "aldehyde": "aldehydes", "amine": "amines",
    "O ring": "oxygen rings (furans, lactones)", "N ring": "nitrogen rings (pyrazines, pyrroles)",
    "sulfid": "sulfur compounds", "sulfide": "sulfur compounds", "other": "other",
}


def odour_classes(odor_csv: Path) -> dict[str, str]:
    """Odour name -> chemical class, from DoOR's odor.csv (names as the C++ library
    gives them: the Name column, first one wins). Missing file: {}."""
    if not odor_csv.exists():
        return {}
    with odor_csv.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f, delimiter=";"))
    header = rows[0]
    if len(rows) > 1 and len(rows[1]) == len(header) + 1:
        header = ["", *header]                  # R-style file: rows start with a row name
    c_class, c_name, c_key = header.index("Class"), header.index("Name"), header.index("InChIKey")
    out: dict[str, str] = {}
    for r in rows[1:]:
        name = r[c_name] if r[c_name] not in ("", "NA") else r[c_key]
        out.setdefault(name, ODOUR_CLASSES.get(r[c_class], "unclassified"))
    return out


class ModelStore:
    def __init__(self, settings: Settings):
        neurons_csv = settings.circuit_dir / "mb_neurons.csv"
        edges_csv = settings.circuit_dir / "mb_edges.csv"
        for f in (neurons_csv, edges_csv):
            if not f.exists():
                raise FileNotFoundError(
                    f"{f} not found. Run scripts/make_synthetic_mb.py or "
                    "scripts/extract_mb_circuit.py, or set FRUIT_FLY_CIRCUIT_DIR.")

        # Default parameters for every experiment (e.g. calibrated); requests override them.
        self.default_params: dict = {}
        self.params = fruit_fly.Params()            # circuit-level settings apply when loading
        if settings.params_file is not None:
            from .schemas import ServerParams
            raw = json.loads(settings.params_file.read_text())
            self.default_params = ServerParams.model_validate(raw).model_dump(exclude_none=True)
            if "kc_dan" in self.default_params:
                self.params.kc_dan = self.default_params.pop("kc_dan")

        self.circuit_dir: Path = settings.circuit_dir
        self.network = fruit_fly.Network.load(str(neurons_csv), str(edges_csv), self.params)
        # Optional columns (FlyWire extractor): the real FlyWire id of model units that
        # stand for part of a neuron (regional APL), and that part's region.
        with neurons_csv.open(newline="") as f:
            rows = list(csv.DictReader(f))
        self.flywire_id = [r.get("flywire_id") or r["root_id"] for r in rows]
        self.region = [r.get("region") or "" for r in rows]

        # Odours are optional: without DoOR the API still works with random odours.
        self.library: fruit_fly.OdourLibrary | None = None
        self.stimulus: fruit_fly.OdourStimulus | None = None
        if (settings.door_dir / "door_response_matrix.csv").exists():
            self.library = fruit_fly.OdourLibrary.load(str(settings.door_dir))
            self.stimulus = fruit_fly.OdourStimulus(self.library, self.network)

        self.group = np.array(self.network.group)
        self.cell_type = np.array(self.network.cell_type)
        # fast connections as flat arrays, for per-neuron partner lists
        row_ptr = np.asarray(self.network.row_ptr)
        self._pre = np.repeat(np.arange(len(self.network), dtype=np.int32), np.diff(row_ptr))
        self._post = np.asarray(self.network.col)
        self._syn = np.asarray(self.network.syn_count)
        self._sign = np.sign(np.asarray(self.network.weight)).astype(np.int8)
        self.group_counts = dict(sorted(Counter(self.network.group).items()))
        # Dopamine reaches MBONs through the plasticity rule, not as fast synapses, so it
        # isn't in the arrays above. For the connection explorer: each DAN's target MBONs.
        dans = [int(i) for i in np.flatnonzero(np.char.startswith(self.group.astype(str), "DAN"))]
        self._dopamine_out = {d: np.flatnonzero(fruit_fly.dopamine_targets(self.network, [d])).astype(np.int32)
                              for d in dans}
        self._group_connectivity = self._build_group_connectivity()
        # Drawing aids for the 3D view (scripts/build_anatomy.py); optional.
        self.regions_file = self.circuit_dir / "brain_regions.json"
        self.morphology_file = self.circuit_dir / "mb_morphology.bin"
        self._neuron_payload = self._build_neuron_payload()
        self._odour_coverage = (
            {name: self.library.coverage(name) for name in self.library.names()}
            if self.library else {})
        self._odour_class = odour_classes(settings.door_dir / "odor.csv") if self.library else {}
        self.fingerprint = self._fingerprint(settings, [neurons_csv, edges_csv])

    @staticmethod
    def _fingerprint(settings: Settings, circuit_files: list[Path]) -> str:
        """Hash of everything besides the request that decides a result: the
        compiled simulator, the code turning its output into a result, the
        circuit, the odour data and the server's default parameters. Part of
        each experiment's reuse key, so a stored result is only reused by a
        server that would compute exactly the same one."""
        h = hashlib.sha256()
        files = [Path(sys.modules[fruit_fly.Network.__module__].__file__),
                 Path(__file__).with_name("runner.py"), *circuit_files]
        if settings.params_file is not None:
            files.append(settings.params_file)
        files += sorted(settings.door_dir.glob("*.csv")) if settings.door_dir.is_dir() else []
        for f in files:
            h.update(f.name.encode())
            with f.open("rb") as fh:
                for block in iter(lambda: fh.read(1 << 20), b""):
                    h.update(block)
        return h.hexdigest()

    def request_key(self, request) -> str:
        """Identical requests on an identical model give identical results (the
        simulator is deterministic for a given seed), so this key identifies a result."""
        body = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(f"{self.fingerprint}\n{body}".encode()).hexdigest()

    # ------------------------------------------------------------------ circuit
    @property
    def has_odours(self) -> bool:
        return self.library is not None

    def summary(self) -> dict:
        net = self.network
        ppl1 = fruit_fly.dopamine_targets(net, net.indices_in_group("DAN_PPL1"))
        pam = fruit_fly.dopamine_targets(net, net.indices_in_group("DAN_PAM"))
        mbon = self.group == "MBON"
        return {
            "circuit_dir": str(self.circuit_dir),
            "neurons": len(net),
            "fast_synapses": int(net.n_synapses),
            "plastic_synapses": len(net.plastic_pre),
            "groups": self.group_counts,
            "mbons_with_ppl1_dopamine": int((ppl1 & mbon).sum()),
            "mbons_with_pam_dopamine": int((pam & mbon).sum()),
            "odours_loaded": self.has_odours,
            "default_params": self.default_params,
            "anatomy": {"regions": self.regions_file.exists(), "morphology": self.morphology_file.exists()},
        }

    def neuron_payload(self) -> dict:
        return self._neuron_payload

    def _build_neuron_payload(self) -> dict:
        """Column-oriented neuron table for the 3D viewer.

        Array position = neuron index, the same index spike data uses.
        root_id is sent as a string: FlyWire IDs exceed 2**53, the largest
        integer a JavaScript number can hold exactly.
        """
        net = self.network
        pos = net.positions
        finite = np.isfinite(pos).all(axis=1)
        if finite.any():
            lo, hi = pos[finite].min(axis=0), pos[finite].max(axis=0)
            bounds = {"min": lo.tolist(), "max": hi.tolist()}
        else:
            bounds = None

        def column(values: np.ndarray) -> list:
            return [float(v) if math.isfinite(v) else None for v in values]

        return {
            "count": len(net),
            "root_id": [str(r) for r in net.root_id],
            "flywire_id": self.flywire_id,
            "group": list(net.group),
            "cell_type": list(net.cell_type),
            "x": column(pos[:, 0]),
            "y": column(pos[:, 1]),
            "z": column(pos[:, 2]),
            "bounds": bounds,
            "groups": list(self.group_counts),
        }

    # ------------------------------------------------------------------ odours
    def neuron_detail(self, index: int, limit: int = 8) -> dict:
        """Identity and the largest input and output partners of one neuron (by cell type)."""
        net = self.network
        sign_name = {1: "excitatory", -1: "inhibitory", 0: "modulatory"}

        def partners(sel: np.ndarray, other: np.ndarray) -> tuple[int, list[dict]]:
            if not sel.any():
                return 0, []
            idx, syn, sgn = other[sel], self._syn[sel], self._sign[sel]
            by_type: dict[str, dict] = {}
            for j, s, g in zip(idx.tolist(), syn.tolist(), sgn.tolist()):
                t = str(self.cell_type[j] or self.group[j])
                p = by_type.setdefault(t, {"cell_type": t, "group": str(self.group[j]), "neurons": set(),
                                           "synapses": 0, "sign": sign_name[int(g)]})
                p["neurons"].add(j)
                p["synapses"] += int(s)
            top = sorted(by_type.values(), key=lambda p: -p["synapses"])[:limit]
            return int(syn.sum()), [{**p, "neurons": len(p["neurons"])} for p in top]

        n_in, inputs = partners(self._post == index, self._pre)
        n_out, outputs = partners(self._pre == index, self._post)
        return {"index": index, "root_id": str(int(net.root_id[index])), "flywire_id": self.flywire_id[index],
                "region": self.region[index], "group": str(self.group[index]),
                "cell_type": str(self.cell_type[index]), "side": str(net.side[index]),
                "transmitter": str(net.transmitter[index]), "graded": bool(net.graded[index]),
                "input_synapses": n_in, "output_synapses": n_out, "inputs": inputs, "outputs": outputs}

    def connections(self, index: int, min_synapses: int = 1, limit: int = 200) -> dict:
        """Every partner neuron of one neuron, for drawing its connections: fast synapses
        in both directions (strongest first) and, for a DAN, the MBONs its dopamine
        reaches (no synapse count: the model couples them by compartment)."""
        sign_name = {1: "excitatory", -1: "inhibitory", 0: "modulatory"}

        def side(sel: np.ndarray, other: np.ndarray) -> tuple[int, list[dict]]:
            idx, syn, sgn = other[sel], self._syn[sel], self._sign[sel]
            keep = syn >= min_synapses
            order = np.argsort(-syn[keep], kind="stable")
            items = [{"index": int(i), "synapses": int(n), "sign": sign_name[int(g)]}
                     for i, n, g in zip(idx[keep][order][:limit], syn[keep][order][:limit],
                                        sgn[keep][order][:limit])]
            return int(keep.sum()), items

        n_in, inputs = side(self._post == index, self._pre)
        n_out, outputs = side(self._pre == index, self._post)
        dopamine_to = self._dopamine_out.get(index, np.zeros(0, np.int32))
        dopamine_from = [d for d, targets in self._dopamine_out.items() if index in targets]
        return {"index": index, "min_synapses": min_synapses,
                "total_inputs": n_in, "total_outputs": n_out, "inputs": inputs, "outputs": outputs,
                "dopamine_to": dopamine_to.tolist(), "dopamine_from": dopamine_from}

    def _build_group_connectivity(self) -> list[dict]:
        """Synapses between every pair of neuron groups (fast synapses, plus dopamine
        coupling counted in DAN -> MBON pairs)."""
        names = sorted(self.group_counts)
        code = {g: k for k, g in enumerate(names)}
        gi = np.array([code[str(g)] for g in self.group], np.int64)
        m = len(names)
        pair = gi[self._pre] * m + gi[self._post]
        syn = np.bincount(pair, weights=self._syn, minlength=m * m)
        conns = np.bincount(pair, minlength=m * m)
        signed = np.bincount(pair, weights=self._syn * self._sign, minlength=m * m)
        out = []
        for k in np.flatnonzero(conns):
            a, b = divmod(int(k), m)
            # the sign carrying most of the synapses (mixed groups, e.g. MBONs, can be either)
            net = signed[k] / syn[k] if syn[k] else 0.0
            out.append({"pre": names[a], "post": names[b], "synapses": int(syn[k]), "connections": int(conns[k]),
                        "sign": "excitatory" if net > 0.5 else "inhibitory" if net < -0.5
                        else "modulatory" if abs(net) < 1e-9 and syn[k] else "mixed"})
        dop: dict[tuple[str, str], int] = {}
        for d, targets in self._dopamine_out.items():
            for t in targets.tolist():
                key = (str(self.group[d]), str(self.group[t]))
                dop[key] = dop.get(key, 0) + 1
        for (a, b), n in sorted(dop.items()):
            out.append({"pre": a, "post": b, "synapses": 0, "connections": n, "sign": "dopamine"})
        return sorted(out, key=lambda c: -c["synapses"])

    def group_connectivity(self) -> list[dict]:
        return self._group_connectivity

    def odour_names(self) -> list[str]:
        return list(self._odour_coverage)

    def odour_coverage(self, name: str) -> float:
        return self._odour_coverage[name]

    def lesion_indices(self, lesions) -> list[int]:
        """Neuron indices silenced by a list of Lesion specs. Raises KeyError
        naming the first spec that matches no neuron."""
        silenced: set[int] = set()
        for spec in lesions:
            mask = self.group == spec.group if spec.group is not None else self.cell_type == spec.cell_type
            hits = np.flatnonzero(mask)
            if hits.size == 0:
                what = f"group '{spec.group}'" if spec.group is not None else f"cell type '{spec.cell_type}'"
                raise KeyError(f"lesion matches no neurons: {what}")
            silenced.update(int(i) for i in hits)
        return sorted(silenced)

    def lesion_options(self) -> dict[str, list[str]]:
        """Groups and cell types that can be lesioned (cell types of the small groups only)."""
        types = sorted({t for g, t in zip(self.group, self.cell_type)
                        if g in ("APL", "DPM", "MBON", "DAN_PAM", "DAN_PPL1") and t})
        return {"groups": list(self.group_counts), "cell_types": types}

    def resolve_odour(self, name: str) -> str:
        """Canonical DoOR name (lookup is case-insensitive). Raises KeyError
        with up to five suggestions if the odour is unknown."""
        if self.library is None:
            raise LookupError("odour data not loaded")
        try:
            return self.library.names()[self.library.odour_index(name)]
        except IndexError:
            raise KeyError(self.library.search(name)[:5]) from None

    def odour_catalog(self) -> list[dict]:
        """Every odour with its chemical class and how much of it DoOR measured."""
        return [{"name": n, "chemical_class": self._odour_class.get(n, "unclassified"), "coverage": c}
                for n, c in sorted(self._odour_coverage.items(), key=lambda kv: kv[0].lower())]

    def odour_search(self, text: str) -> list[str]:
        if self.library is None:
            return []
        return self.library.search(text) if text else self.odour_names()
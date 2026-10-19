"""Rules of the FlyWire circuit extractor that don't need the FlyWire data."""

import importlib.util
from pathlib import Path

import pandas as pd

_spec = importlib.util.spec_from_file_location(
    "extract_mb_circuit", Path(__file__).resolve().parents[1] / "scripts" / "extract_mb_circuit.py")
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)

APL, KC1, KC2, MBON = 100, 1, 2, 50


def test_mb_region():
    assert ex.mb_region("MB_ML_L") == "ML" and ex.mb_region("MB_CA_R") == "CA"
    assert ex.mb_region("MB_PED_L") == "PED" and ex.mb_region("MB_VL_R") == "VL"
    assert ex.mb_region("CRE_L") is None and ex.mb_region("MB_MLX") is None


def test_split_apl_by_region():
    mb = pd.DataFrame({"root_id": [APL, KC1, KC2, MBON], "group": ["APL", "KC", "KC", "MBON"],
                       "label": ["APL", "KCg", "KCab", "MBON01"], "flywire_id": [APL, KC1, KC2, MBON]})
    edges = pd.DataFrame([
        # pre, post, neuropil, synapses
        (KC1, APL, "MB_CA_L", 5), (KC1, APL, "MB_ML_L", 9), (KC1, APL, "CRE_L", 2),   # CRE: KC1's main region
        (KC2, APL, "MB_PED_L", 4), (KC2, APL, "PLP_L", 1),
        (APL, MBON, "MB_ML_L", 7), (APL, KC1, "MB_CA_L", 3),
        (KC1, MBON, "MB_ML_L", 20),                                                  # untouched
    ], columns=["pre_root_id", "post_root_id", "neuropil", "syn_count"])
    units, out = ex.split_apl(mb, edges)

    apl = units[units.group.eq("APL")].set_index("region")
    assert set(apl.index) == {"CA", "PED", "ML"}                     # only regions with synapses
    assert (apl.flywire_id == APL).all() and (apl.label == "APL").all()
    assert (apl.root_id >= ex.UNIT_ID_BASE).all() and APL not in set(units.root_id)
    uid = apl.root_id.to_dict()
    syn = out.groupby(["pre_root_id", "post_root_id"]).syn_count.sum()
    assert syn[(KC1, uid["CA"])] == 5
    assert syn[(KC1, uid["ML"])] == 9 + 2                            # the CRE synapses follow KC1's majority
    assert syn[(KC2, uid["PED"])] == 4 + 1
    assert syn[(uid["ML"], MBON)] == 7 and syn[(uid["CA"], KC1)] == 3
    assert syn[(KC1, MBON)] == 20
    assert out.syn_count.sum() == edges.syn_count.sum()              # nothing lost or duplicated


def test_split_apl_without_apl_is_a_no_op():
    mb = pd.DataFrame({"root_id": [KC1], "group": ["KC"], "label": ["KCg"]})
    edges = pd.DataFrame(columns=["pre_root_id", "post_root_id", "neuropil", "syn_count"])
    assert ex.split_apl(mb, edges)[0] is mb

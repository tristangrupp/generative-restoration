"""Print the energy breakdown of hand-built reference plans against a sampled one.

Calibration by inspection rather than by guessing: if a term dominates, it shows up
here as the biggest column.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import design_graph as dg  # noqa: E402
import generative as gen  # noqa: E402
from config import CONTEXT_DIR, DATA, OUT, SITES_INDEX  # noqa: E402

SID = sys.argv[1] if len(sys.argv) > 1 else "PILOT_sorriso"


def main():
    rec = [r for r in json.loads(SITES_INDEX.read_text(encoding="utf-8"))
           if r["site_id"] == SID][0]
    ctx = dict(np.load(CONTEXT_DIR / f"{SID}_context.npz", allow_pickle=False))
    con = {k: v.astype(bool) for k, v in
           np.load(CONTEXT_DIR / f"{SID}_constraints.npz", allow_pickle=False).items()}
    ledger = json.loads((CONTEXT_DIR / f"{SID}_ledger.json").read_text(encoding="utf-8"))

    g = dg.build_design_graph(ctx, con)
    con["_app_deficit_blocks"] = (
        dg._block_reduce(con["app_deficit"].astype("float32"), dg.BLOCK)[g.rows, g.cols]
        > 0.4)
    prof = json.loads((DATA / "machinery.json").read_text(encoding="utf-8"))
    machine = dict(prof["profiles"][prof["default_profile"]])
    machine["block_m"] = dg.BLOCK * float(ctx["cell_m"])
    se = gen.prepare(g, ctx, con, ledger, machine)

    plans = {}
    base = np.full(se.g.n, gen.CROP, dtype="int8")
    base[se.already_native] = gen.REGEN
    plans["do_nothing"] = base.copy()

    app_only = base.copy()
    app_only[se.app_deficit] = gen.PLANT
    plans["app_only_buy_CRA"] = app_only

    everything = base.copy()
    everything[:] = gen.PLANT
    everything[se.already_native] = gen.REGEN
    plans["restore_everything"] = everything

    site_out = OUT / SID
    for tag in ("01_compliance_minimum_s1", "07_corridor_network_s1",
                "10_productive_mosaic_s1"):
        p = site_out / f"{tag}_labels.npy"
        if p.exists():
            plans[f"sampled_{tag[:2]}"] = np.load(p)

    arch = {a.name: a for a in gen.ARCHETYPES}
    for wname in ("compliance_minimum", "corridor_network"):
        w = arch[wname]
        print(f"\n=========== weights: {wname} ===========")
        keys = None
        for name, x in plans.items():
            e, t = gen.energy(se, x, w)
            if keys is None:
                keys = [k for k in t if k not in
                        ("restored_ha", "eca", "aggregation", "rl_credit_ha",
                         "compensation_ha", "edge_anisotropy")]
                print(f"{'plan':24s} {'TOTAL':>9s} " +
                      " ".join(f"{k:>9s}" for k in keys) +
                      f" {'onfarm_ha':>10s} {'CRA_ha':>8s}")
            print(f"{name:24s} {e:9.0f} " +
                  " ".join(f"{t[k]:9.0f}" for k in keys) +
                  f" {t['restored_ha']:10.0f} {t['compensation_ha']:8.0f}")


if __name__ == "__main__":
    main()

"""Stage 6 - show what the `linearity` knob actually does.

Same site, same seed, same archetype, same obligation - only the morphology setting
changes. This is the honest test of a tunable: if the panels look alike, the knob is
decoration.

    python s06_linearity_sweep.py primavera_cerrado
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import design_graph as dg  # noqa: E402
import generative as gen  # noqa: E402
import sampler  # noqa: E402
from config import CONTEXT_DIR, DATA, OUT, SITES_INDEX  # noqa: E402
from s05_report import PLAN_CMAP, PLAN_COLORS, PRETTY  # noqa: E402

LEVELS = [0.0, 0.35, 0.7, 1.0]
SEED = 4242
N_ITER = 9000


def main() -> None:
    sid = sys.argv[1] if len(sys.argv) > 1 else "primavera_cerrado"
    rec = [r for r in json.loads(SITES_INDEX.read_text(encoding="utf-8"))
           if r["site_id"] == sid][0]

    ctx = dict(np.load(CONTEXT_DIR / f"{sid}_context.npz", allow_pickle=False))
    con = {k: v.astype(bool) for k, v in
           np.load(CONTEXT_DIR / f"{sid}_constraints.npz", allow_pickle=False).items()}
    ledger = json.loads((CONTEXT_DIR / f"{sid}_ledger.json").read_text(encoding="utf-8"))

    machinery = json.loads((DATA / "machinery.json").read_text(encoding="utf-8"))
    prof = machinery["profiles"][machinery["default_profile"]]
    design = json.loads((DATA / "design.json").read_text(encoding="utf-8"))

    g = dg.build_design_graph(ctx, con)
    con["_app_deficit_blocks"] = (
        dg._block_reduce(con["app_deficit"].astype("float32"), dg.BLOCK)[g.rows, g.cols]
        > 0.4)
    machine = dict(prof)
    machine["block_m"] = dg.BLOCK * float(ctx["cell_m"])
    se = gen.prepare(g, ctx, con, ledger, machine, design)
    print(f"{sid}: {len(se.lines)} contour lines at {se.lines.interval_m:.1f} m")

    # Hold everything except morphology fixed.
    base = [a for a in gen.ARCHETYPES if a.name == "water_first"][0]

    prop = ctx["property_mask"].astype(bool)
    fig, axes = plt.subplots(1, len(LEVELS), figsize=(5.2 * len(LEVELS), 6.8))
    fig.suptitle(f"{rec['label']} - the same plan at four settings of `linearity`\n"
                 f"archetype water_first, seed {SEED}, obligation "
                 f"{ledger['total_restoration_obligation_ha']:.0f} ha, "
                 f"mean slope {np.nanmean(ctx['slope_deg'][prop]):.1f} deg",
                 fontsize=13, y=0.99)

    rows = []
    for ax, lin in zip(np.atleast_1d(axes), LEVELS):
        w = replace(base, linearity=lin)
        x, e, terms, _ = sampler.anneal(se, w, SEED, n_iter=N_ITER)
        new = (x != gen.CROP) & ~se.already_native
        align = (2.5 - terms["edge_anisotropy"]) / 1.5
        veg = gen.vegetated_lattice(se, x)
        n_comp, largest, _ = dg.component_stats(veg, se.px_ha)
        rows.append(dict(linearity=lin, restored_ha=round(terms["restored_ha"], 1),
                         contour_alignment=round(float(align), 3),
                         aggregation=round(terms["aggregation"], 3),
                         patches=int(n_comp), energy=round(e, 1)))

        grid = dg.rasterise(g, x.astype("int16"), fill=-1)
        ax.imshow(np.ma.masked_where(grid < 0, grid), cmap=PLAN_CMAP,
                  vmin=-0.5, vmax=gen.N_LABELS - 0.5, interpolation="nearest")
        ax.imshow(np.ma.masked_where(~ctx["stream"].astype(bool), ctx["stream"]),
                  cmap=ListedColormap(["#2a6fb0"]), alpha=0.6)
        ax.contour(prop, levels=[0.5], colors="k", linewidths=0.8)
        ax.set_title(f"linearity = {lin:.2f}\n{terms['restored_ha']:.0f} ha | "
                     f"contour alignment {align:.2f} | {n_comp} patches", fontsize=10)
        ax.set_xticks([]); ax.set_yticks([])
        print(f"  linearity {lin:.2f}  restored {terms['restored_ha']:7.1f} ha  "
              f"alignment {align:.3f}  patches {n_comp}")

    handles = [Patch(facecolor=PLAN_COLORS[k], label=PRETTY[k])
               for k in range(gen.N_LABELS)]
    fig.legend(handles=handles, loc="lower center", ncol=5, frameon=False, fontsize=10)
    fig.tight_layout(rect=(0, 0.06, 1, 0.90))

    out = OUT / sid / "02_linearity_sweep.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    (OUT / sid / "02_linearity_sweep.json").write_text(
        json.dumps(rows, indent=2), encoding="utf-8")
    print(f"-> {out}")


if __name__ == "__main__":
    main()

"""Stage 4 - generate 12 restoration scenarios per site.

Twelve = four design archetypes x three seeds. The archetypes fix what the plan is
trying to be (bare compliance, water-led, corridor-led, productive mosaic); the
seeds give three genuinely different realisations of each, because the sampler's
proposals are stochastic and the energy landscape is multi-modal.

Each scenario is written out as labels, a metrics record, and a GeoPackage of
dissolved intervention polygons that can be opened straight in QGIS.
"""
from __future__ import annotations

import json
import os
import sys
import time
import zlib
from dataclasses import replace
from pathlib import Path

import geopandas as gpd
import numpy as np
from rasterio.features import shapes
from rasterio.transform import Affine
from shapely.geometry import shape

sys.path.insert(0, str(Path(__file__).parent))
import design_graph as dg  # noqa: E402
import generative as gen  # noqa: E402
import sampler  # noqa: E402
from config import CONTEXT_DIR, DATA, METRIC_CRS, OUT, SITES_DIR, SITES_INDEX  # noqa: E402

N_SEEDS = 3
N_ITER = 9000

# SCENARIOS=11,12 reruns only those scenario numbers and reuses the metrics already
# on disk for the rest. A site takes over two hours end to end, so a run that dies
# partway through should not have to redo the scenarios that survived it.
_WANT = os.environ.get("SCENARIOS", "").strip()
ONLY_SCENARIOS = {int(v) for v in _WANT.replace(" ", "").split(",") if v} or None


def load(sid: str):
    ctx = dict(np.load(CONTEXT_DIR / f"{sid}_context.npz", allow_pickle=False))
    con = dict(np.load(CONTEXT_DIR / f"{sid}_constraints.npz", allow_pickle=False))
    ledger = json.loads((CONTEXT_DIR / f"{sid}_ledger.json").read_text(encoding="utf-8"))
    return ctx, {k: v.astype(bool) for k, v in con.items()}, ledger


def scenario_metrics(se, x, terms, ledger, machine) -> dict:
    px_ha = se.px_ha
    counts = np.isin(x, gen.COUNTS_AS_NATIVE)
    # Existing vegetation is held at REGEN by the sampler, so the per-intervention
    # areas must exclude it or every plan looks like it planted the remnants.
    new = (x != gen.CROP) & ~se.already_native
    by_label = {gen.LABEL_NAMES[k]: round(float((se.area_ha * (new & (x == k))).sum()), 1)
                for k in range(gen.N_LABELS)}
    by_label["existing_native_retained"] = round(
        float((se.area_ha * se.already_native).sum()), 1)

    app_unmet_ha = float((se.area_ha * (se.app_deficit & ~counts)).sum())
    rl_credit = terms["rl_credit_ha"]

    veg = gen.vegetated_lattice(se, x)
    n_comp, largest, _ = dg.component_stats(veg, px_ha)

    crop_ha = float((se.area_ha * (x == gen.CROP)).sum())
    lost_ha = float((se.area_ha * (se.croppable & new)).sum())

    return dict(
        area_by_intervention_ha=by_label,
        restored_ha=round(terms["restored_ha"], 1),
        cropland_retained_ha=round(crop_ha, 1),
        cropland_converted_ha=round(lost_ha, 1),
        app_obligation_ha=ledger["app_deficit_ha"],
        app_unmet_ha=round(app_unmet_ha, 1),
        app_compliant=bool(app_unmet_ha < 0.5),
        rl_deficit_ha=ledger["rl_deficit_ha"],
        rl_recomposed_on_farm_ha=round(rl_credit, 1),
        rl_compensated_off_farm_ha=round(terms["compensation_ha"], 1),
        rl_compliant=True,   # settled either on the property or by Art. 66 par. 5
        rl_fully_on_farm=bool(terms["compensation_ha"] < 0.5),
        connectivity_eca_ha=round(terms["eca"], 1),
        aggregation=round(terms["aggregation"], 3),
        # 1.0 = the restored edges run along the contour; 0.0 = straight downhill.
        # Edge weights run 1.0 (edge parallel to slope, cheap to cut, so cutting it
        # leaves a contour-following boundary) to 2.5 (the reverse).
        contour_alignment=round(float((2.5 - terms["edge_anisotropy"]) / 1.5), 3),
        # Two archetypes can restore the same hectares with the same technique and
        # still be different plans. These say where the hectares went.
        mean_dist_to_stream_m=round(
            float(se.g.feat["dist_stream"][new].mean()) if new.any() else 0.0, 1),
        mean_dist_to_existing_native_m=round(
            float(se.g.feat["dist_native"][new].mean()) if new.any() else 0.0, 1),
        share_within_100m_of_stream=round(
            float((se.g.feat["dist_stream"][new] <= 100).mean()) if new.any() else 0.0, 3),
        vegetation_patches=int(n_comp),
        largest_patch_ha=round(largest, 1),
        saf_share_of_restored=round(
            by_label["agroforestry_saf"] / max(terms["restored_ha"], 1e-9), 3),
        art66_exotic_cap_ok=bool(
            by_label["agroforestry_saf"] <= 0.5 * max(terms["restored_ha"], 1e-9) + 0.5),
        machinery_profile=machine["label"],
        energy_terms={k: round(float(v), 1) for k, v in terms.items()
                      if k not in ("restored_ha", "eca", "rl_credit_ha",
                                   "aggregation", "compensation_ha",
                                   "edge_anisotropy")},
    )


def to_polygons(se, x, ctx, transform) -> gpd.GeoDataFrame:
    grid = dg.rasterise(se.g, x.astype("int16"), fill=-1)
    recs = []
    for geom, val in shapes(grid.astype("int32"), mask=grid >= 0, transform=transform):
        v = int(val)
        if v == gen.CROP:
            continue
        recs.append(dict(intervention=gen.LABEL_NAMES[v], label_id=v,
                         geometry=shape(geom)))
    if not recs:
        return gpd.GeoDataFrame(columns=["intervention", "label_id", "geometry"],
                                geometry="geometry", crs=METRIC_CRS)
    gdf = gpd.GeoDataFrame(recs, crs=METRIC_CRS)
    gdf = gdf.dissolve(by="intervention", as_index=False, aggfunc="first")
    gdf["area_ha"] = gdf.geometry.area / 1e4
    return gdf


def archetypes_with_design(design: dict) -> list:
    """Apply the user's morphology settings to the archetype weight vectors."""
    lin = design.get("linearity", {})
    default = float(lin.get("value", 0.5))
    per = lin.get("per_archetype", {})
    out = []
    for a in gen.ARCHETYPES:
        a = replace(a, linearity=float(per.get(a.name, default)))
        out.append(a)
    return out


def main() -> None:
    machinery = json.loads((DATA / "machinery.json").read_text(encoding="utf-8"))
    profile_key = machinery["default_profile"]
    prof = machinery["profiles"][profile_key]
    design = json.loads((DATA / "design.json").read_text(encoding="utf-8"))
    archetypes = archetypes_with_design(design)

    sites = json.loads((SITES_INDEX).read_text(encoding="utf-8"))
    only = sys.argv[1:] or None
    for rec in sites:
        sid = rec["site_id"]
        if only and sid not in only:
            continue
        print(f"\n================ {sid} ================")
        ctx, con, ledger = load(sid)
        transform = Affine.from_gdal(*ctx["transform"])

        g = dg.build_design_graph(ctx, con)
        print(f"  design graph: {g.n:,} blocks, {len(g.edges):,} edges")

        con["_app_deficit_blocks"] = (
            dg._block_reduce(con["app_deficit"].astype("float32"), dg.BLOCK)[g.rows, g.cols]
            > 0.4)

        machine = dict(prof)
        machine["block_m"] = dg.BLOCK * float(ctx["cell_m"])
        se = gen.prepare(g, ctx, con, ledger, machine, design)
        print(f"  obligation: APP {ledger['app_deficit_ha']} ha + RL "
              f"{ledger['rl_deficit_ha']} ha")
        if se.lines is not None:
            print(f"  drivable contour lines: {len(se.lines)} at "
                  f"{se.lines.interval_m:.1f} m interval "
                  f"(turn radius {machine['turning_radius_m']:.0f} m x safety)")

        site_out = OUT / sid
        site_out.mkdir(parents=True, exist_ok=True)
        summary = []

        n = 0
        for arch in archetypes:
            for s in range(N_SEEDS):
                n += 1
                tag = f"{n:02d}_{arch.name}_s{s + 1}"
                cached = site_out / f"{tag}_metrics.json"
                if ONLY_SCENARIOS and n not in ONLY_SCENARIOS and cached.exists():
                    m = json.loads(cached.read_text(encoding="utf-8"))
                    summary.append(m)
                    print(f"  {tag:34s} kept from disk "
                          f"({m['restored_ha']:.1f} ha on-farm)")
                    continue

                t0 = time.time()
                # crc32 rather than hash(): Python randomises str hashes per process,
                # so hash() gave a different seed on every run and no plan could be
                # reproduced. Plans generated before this change record their seed
                # in the metrics JSON, which is the only way back to them.
                seed = 1000 * (s + 1) + zlib.crc32(arch.name.encode()) % 997
                x, e, terms, _ = sampler.anneal(se, arch, seed, n_iter=N_ITER)
                m = scenario_metrics(se, x, terms, ledger, machine)
                m.update(scenario=f"{n:02d}_{arch.name}_s{s + 1}",
                         archetype=arch.name, seed=seed, energy=round(e, 1),
                         seconds=round(time.time() - t0, 1))

                tag = m["scenario"]
                np.save(site_out / f"{tag}_labels.npy", x)
                (site_out / f"{tag}_metrics.json").write_text(
                    json.dumps(m, indent=2), encoding="utf-8")
                gdf = to_polygons(se, x, ctx, transform)
                if len(gdf):
                    gdf.to_file(site_out / f"{tag}.gpkg", layer="plan", driver="GPKG")
                summary.append(m)

                print(f"  {tag:34s} lin {arch.linearity:.2f}  "
                      f"on-farm {m['restored_ha']:7.1f} ha  "
                      f"CRA {m['rl_compensated_off_farm_ha']:7.1f} ha  "
                      f"crop {m['cropland_retained_ha']:7.1f} ha  "
                      f"APP {'ok ' if m['app_compliant'] else 'SHORT'}  "
                      f"contour {m['contour_alignment']:.2f}  {m['seconds']:5.1f}s")

        (site_out / "scenarios.json").write_text(
            json.dumps(dict(site=rec, ledger=ledger, machinery=machine,
                            scenarios=summary), indent=2), encoding="utf-8")
        print(f"  -> {site_out}")


if __name__ == "__main__":
    main()

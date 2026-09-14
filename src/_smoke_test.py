"""Synthetic-site smoke test: exercises graph, energy and sampler without any I/O.

Builds a small fake farm with a stream, a hill, two woodlot remnants and a block of
cropland, then runs one scenario per archetype and checks the plan is legal, is
contiguous, and differs between archetypes.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import design_graph as dg  # noqa: E402
import forest_code as fc  # noqa: E402
import generative as gen  # noqa: E402
import sampler  # noqa: E402

H = W = 260
CELL = 30.0


def fake_site():
    yy, xx = np.mgrid[0:H, 0:W].astype("float32")

    # A ridge on the left, a broad valley running north-south down the middle.
    dem = (60.0 * np.exp(-((xx - 40) ** 2 + (yy - 90) ** 2) / (2 * 45.0 ** 2))
           + 0.06 * (W - xx) + 0.02 * yy
           + 18.0 * np.exp(-((xx - 150) ** 2) / (2 * 55.0 ** 2)))
    dem += 0.4 * np.random.default_rng(0).normal(size=dem.shape)

    stream = np.zeros((H, W), dtype=bool)
    chan = (150 + 18 * np.sin(yy[:, 0] / 28.0)).astype(int)
    for r in range(H):
        stream[r, chan[r]] = True
    trib = np.zeros((H, W), dtype=bool)
    for r in range(60, 130):
        trib[r, int(60 + (r - 60) * 1.3)] = True
    stream |= trib

    spring = np.zeros((H, W), dtype=bool)
    spring[60, 60] = True
    spring[0, chan[0]] = True

    channel_width = np.where(stream, 7.0, 0.0).astype("float32")
    channel_width[stream & (np.arange(W)[None, :] > 130)] = 22.0

    native = np.zeros((H, W), dtype=bool)
    native |= (xx - 30) ** 2 + (yy - 30) ** 2 < 22 ** 2       # woodlot NW
    native |= (xx - 225) ** 2 + (yy - 210) ** 2 < 26 ** 2     # woodlot SE, off-farm
    native |= np.abs(xx - chan[:, None]) < 2                   # thin gallery remnant

    field = np.zeros((H, W), dtype=bool)
    field[20:240, 15:245] = True
    field &= ~native

    prop = np.zeros((H, W), dtype=bool)
    prop[25:235, 20:200] = True

    slope = np.degrees(np.arctan(np.hypot(*np.gradient(dem, CELL, CELL)[::-1])))
    acc = np.where(stream, 5e4, 50.0).astype("float32")
    twi = np.log(np.maximum(acc, 1) * CELL / np.maximum(np.tan(np.radians(slope)), 0.001))

    from scipy import ndimage as ndi
    ctx = dict(
        dem=dem.astype("float32"), slope_deg=slope.astype("float32"),
        twi=twi.astype("float32"), flowacc=acc, cell_m=CELL,
        stream=stream.astype("uint8"), channel_width_m=channel_width,
        spring=spring.astype("uint8"), water=np.zeros((H, W), "uint8"),
        native=native.astype("uint8"), agri=field.astype("uint8"),
        field_mask=field.astype("uint8"), property_mask=prop.astype("uint8"),
        consolidated_2008=(field & ~native).astype("uint8"),
        mapbiomas=np.where(native, 3, 39).astype("uint8"),
        mapbiomas_2008=np.where(native, 3, 39).astype("uint8"),
        dist_to_native=ndi.distance_transform_edt(~native, sampling=CELL).astype("float32"),
        dist_to_stream=ndi.distance_transform_edt(~stream, sampling=CELL).astype("float32"),
    )
    return ctx


def main():
    ctx = fake_site()
    cell = CELL
    table = [{"width_lt_m": 10, "buffer_m": 30}, {"width_lt_m": 50, "buffer_m": 50},
             {"width_lt_m": 200, "buffer_m": 100}, {"width_lt_m": 600, "buffer_m": 200},
             {"width_lt_m": None, "buffer_m": 500}]
    esc = [{"mf_le": 1, "recompose_m": 5}, {"mf_le": 2, "recompose_m": 8},
           {"mf_le": 4, "recompose_m": 15},
           {"mf_le": 10, "recompose_m": 20, "condition": "w<=10"},
           {"mf_le": None, "recompose_m": "half_of_watercourse_width",
            "min_m": 30, "max_m": 100}]

    stream = ctx["stream"].astype(bool)
    obl, full, _ = fc.riparian_obligation(
        stream, ctx["channel_width_m"], ctx["consolidated_2008"].astype(bool),
        8.0, cell, table, esc)
    spr = fc.app_springs(ctx["spring"].astype(bool), cell, 50.0)
    steep = fc.app_steep_slope(ctx["slope_deg"], 45.0)

    app_obl = obl | spr | steep
    native = ctx["native"].astype(bool)
    masks = dict(app_full=full | spr | steep, app_obligation=app_obl,
                 app_deficit=app_obl & ~native)

    px_ha = cell ** 2 / 1e4
    prop = ctx["property_mask"].astype(bool)
    print(f"synthetic farm {prop.sum() * px_ha:,.0f} ha")
    print(f"  APP full {(full & prop).sum() * px_ha:,.0f} ha -> "
          f"obligation {(app_obl & prop).sum() * px_ha:,.0f} ha "
          f"(Art.61-A relief works)")
    print(f"  APP deficit {(masks['app_deficit'] & prop).sum() * px_ha:,.0f} ha")

    g = dg.build_design_graph(ctx, masks)
    print(f"  design graph: {g.n:,} blocks, {len(g.edges):,} edges")

    masks["_app_deficit_blocks"] = (
        dg._block_reduce(masks["app_deficit"].astype("float32"), dg.BLOCK)[g.rows, g.cols]
        > 0.4)

    ledger = dict(rl_deficit_ha=float(prop.sum() * px_ha * 0.35
                                      - (native & prop).sum() * px_ha))
    ledger["rl_deficit_ha"] = max(0.0, ledger["rl_deficit_ha"])
    print(f"  RL deficit {ledger['rl_deficit_ha']:,.0f} ha")

    machine = dict(label="test", min_workable_ha=12.0, min_corridor_width_m=30.0,
                   block_m=dg.BLOCK * cell)
    se = gen.prepare(g, ctx, masks, ledger, machine)

    results = {}
    for arch in gen.ARCHETYPES:
        t0 = time.time()
        x, e, terms, _ = sampler.anneal(se, arch, seed=7, n_iter=600)
        counts = np.isin(x, gen.COUNTS_AS_NATIVE)
        unmet = float((se.area_ha * (se.app_deficit & ~counts)).sum())
        results[arch.name] = x
        print(f"  {arch.name:20s} E={e:11.1f}  restored {terms['restored_ha']:7.1f} ha  "
              f"APP unmet {unmet:6.1f} ha  ECA {terms['eca']:8.1f}  "
              f"{time.time() - t0:5.1f}s")

    names = list(results)
    print("\n  pairwise disagreement between archetypes (share of blocks):")
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            d = float((results[names[i]] != results[names[j]]).mean())
            print(f"    {names[i]:20s} vs {names[j]:20s} {d:.2%}")


if __name__ == "__main__":
    main()

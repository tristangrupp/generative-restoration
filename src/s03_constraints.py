"""Stage 3 - turn the context stack into the legal obligation surface per site.

Produces, on the same 30 m grid:
    app_full          every Art. 4 APP, ignoring consolidation
    app_obligation    what must actually carry native vegetation once Art. 61-A
                      escadinha relief is applied to pre-2008 consolidated land
    app_deficit       app_obligation that is currently NOT native vegetation
    plus one mask per article, so each contribution stays auditable

and a per-site ledger with the Reserva Legal arithmetic.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import forest_code as fc  # noqa: E402
from config import CONTEXT_DIR, RULES_JSON, SITES_DIR, SITES_INDEX  # noqa: E402


def load_context(sid: str) -> dict:
    z = np.load(CONTEXT_DIR / f"{sid}_context.npz", allow_pickle=False)
    return {k: z[k] for k in z.files}


def solve(ctx: dict, rec: dict, rules: dict) -> tuple[dict, dict]:
    cell_m = float(ctx["cell_m"])
    px_ha = (cell_m ** 2) / 1e4
    full_rules = rules["app_full"]
    esc_rules = rules["app_consolidated"]

    stream = ctx["stream"].astype(bool)
    spring = ctx["spring"].astype(bool)
    water = ctx["water"].astype(bool)
    native = ctx["native"].astype(bool)
    prop = ctx["property_mask"].astype(bool)
    consolidated = ctx["consolidated_2008"].astype(bool)
    dem = ctx["dem"].astype("float64")
    slope = ctx["slope_deg"]
    chan_w = ctx["channel_width_m"]
    mod_fiscal = float(rec["mod_fiscal"])

    obligation_rip, full_rip, esc_rip = fc.riparian_obligation(
        stream, chan_w, consolidated, mod_fiscal, cell_m,
        full_rules["watercourse_buffer_m"], esc_rules["watercourse_by_fiscal_modules"],
    )

    spring_full = fc.app_springs(spring, cell_m, full_rules["spring_radius_m"]["value"])
    spring_esc = fc._dilate_m(
        spring, fc.escadinha_width_m(mod_fiscal, esc_rules["spring_radius_by_fiscal_modules"]),
        cell_m)
    obligation_spring = np.where(consolidated, spring_esc, spring_full)

    lake_full, _ = fc.app_lakes(water, stream, cell_m,
                                full_rules["natural_lake_buffer_m"]["rural_gt_20ha"],
                                full_rules["natural_lake_buffer_m"]["rural_le_20ha"])
    lake_esc = fc._dilate_m(
        water & ~stream,
        fc.escadinha_width_m(mod_fiscal, esc_rules["lake_by_fiscal_modules"]), cell_m)
    obligation_lake = np.where(consolidated, lake_esc, lake_full)

    steep = fc.app_steep_slope(slope, full_rules["steep_slope_deg"]["gt_deg"])
    hill = fc.app_hilltops(dem, slope, cell_m,
                           full_rules["hilltop"]["min_height_m"],
                           full_rules["hilltop"]["min_mean_slope_deg"],
                           full_rules["hilltop"]["from_contour_fraction_of_height"])
    plateau = fc.app_plateau_edges(slope, cell_m, full_rules["plateau_edge_m"]["buffer_m"])

    if rec["biome"] == "Cerrado":
        vereda, vereda_core = fc.app_veredas(
            ctx["mapbiomas"], cell_m, buffer_m=full_rules["vereda_buffer_m"]["value"])
    else:
        vereda = np.zeros(stream.shape, dtype=bool)
        vereda_core = vereda

    # Art. 61-A relief covers watercourses, springs and lakes only. Slope, hilltop,
    # plateau-edge and vereda APPs carry no escadinha and are always full width.
    app_full = (full_rip | spring_full | lake_full | steep | hill | plateau | vereda)
    app_obligation = (obligation_rip | obligation_spring | obligation_lake
                      | steep | hill | plateau | vereda)
    app_deficit = app_obligation & ~native

    native_2008 = np.isin(ctx["mapbiomas_2008"],
                          np.array(rules["mapbiomas_class_roles"]["native_vegetation"],
                                   dtype="uint8"))
    ledger = fc.reserva_legal_ledger(prop, native, app_obligation, rec["rl_pct"],
                                     cell_m, mod_fiscal, native_2008)

    def ha(m):
        return round(float((m & prop).sum()) * px_ha, 1)

    ledger.update(
        site_id=rec["site_id"], cod_imovel=rec["cod_imovel"],
        municipio=rec["municipio"], mod_fiscal=mod_fiscal, biome=rec["biome"],
        app_full_ha=ha(app_full),
        app_obligation_ha=ha(app_obligation),
        app_deficit_ha=ha(app_deficit),
        app_relief_from_art61a_ha=round(ha(app_full) - ha(app_obligation), 1),
        by_article={
            "art4_I_watercourse": ha(full_rip),
            "art4_II_lake": ha(lake_full),
            "art4_IV_spring": ha(spring_full),
            "art4_V_slope_gt_45deg": ha(steep),
            "art4_VIII_plateau_edge_PROXY": ha(plateau),
            "art4_IX_hilltop_PROXY": ha(hill),
            "art4_XI_vereda_PROXY": ha(vereda),
        },
        total_restoration_obligation_ha=round(
            ha(app_deficit) + ledger["rl_deficit_ha"], 1),
        caveats=[
            "Reserva Legal share is taken from the site's biome window, not from an "
            "official IBGE biome overlay of the parcel.",
            "Art. 4 VIII / IX / XI masks are terrain and MapBiomas proxies; see "
            "forest_code.py docstrings.",
            "Consolidation is inferred from MapBiomas 2008 land use, not from the "
            "property's CAR declaration of area consolidada.",
            "APP counted toward RL under Art. 15 requires the owner to have "
            "requested it in CAR; assumed granted here.",
        ],
    )

    masks = dict(
        app_full=app_full, app_obligation=app_obligation, app_deficit=app_deficit,
        rip_full=full_rip, rip_obligation=obligation_rip,
        spring_full=spring_full, spring_obligation=obligation_spring,
        lake_full=lake_full, lake_obligation=obligation_lake,
        steep=steep, hilltop=hill, plateau_edge=plateau, vereda=vereda,
        vereda_core=vereda_core, native_2008=native_2008,
    )
    return masks, ledger


def main() -> None:
    rules = json.loads(RULES_JSON.read_text(encoding="utf-8"))
    sites = json.loads((SITES_INDEX).read_text(encoding="utf-8"))

    all_ledgers = []
    only = sys.argv[1:] or None
    for rec in sites:
        sid = rec["site_id"]
        if only and sid not in only:
            continue
        print(f"\n=== {sid} ===")
        ctx = load_context(sid)
        masks, ledger = solve(ctx, rec, rules)

        out = CONTEXT_DIR / f"{sid}_constraints.npz"
        np.savez_compressed(out, **{k: v.astype("uint8") for k, v in masks.items()})
        (CONTEXT_DIR / f"{sid}_ledger.json").write_text(
            json.dumps(ledger, indent=2), encoding="utf-8")
        all_ledgers.append(ledger)

        print(f"  property {ledger['property_ha']} ha, {ledger['mod_fiscal']:.1f} MF")
        print(f"  APP  full {ledger['app_full_ha']} ha  ->  obligation "
              f"{ledger['app_obligation_ha']} ha  (Art.61-A relief "
              f"{ledger['app_relief_from_art61a_ha']} ha)")
        print(f"  APP  deficit {ledger['app_deficit_ha']} ha")
        print(f"  RL   required {ledger['rl_required_ha']} ha, existing "
              f"{ledger['rl_existing_native_ha']} ha, deficit {ledger['rl_deficit_ha']} ha")
        print(f"  TOTAL restoration obligation {ledger['total_restoration_obligation_ha']} ha")
        print(f"  -> {out.name}")

    (CONTEXT_DIR / "ledgers.json").write_text(
        json.dumps(all_ledgers, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

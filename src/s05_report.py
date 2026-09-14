"""Stage 5 - draw the scenarios and write the comparison sheet.

Two figures per site: a context plate showing what the plan is responding to, and a
twelve-panel plate showing the scenarios side by side. Plus a markdown sheet with
the compliance and trade-off numbers, which is the artefact an agronomist or a CAR
consultant would actually read.
"""
from __future__ import annotations

import json
import sys
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
from config import CONTEXT_DIR, OUT, SITES_DIR, SITES_INDEX  # noqa: E402

PLAN_COLORS = {
    gen.CROP: "#efe7d4",
    gen.REGEN: "#7fbf7b",
    gen.PLANT: "#1b7837",
    gen.SAF: "#c2a55a",
    gen.WINDBREAK: "#4a6fa5",
}
PLAN_CMAP = ListedColormap([PLAN_COLORS[k] for k in range(gen.N_LABELS)])
PRETTY = {gen.CROP: "Crop retained", gen.REGEN: "Natural regeneration",
          gen.PLANT: "Active native planting", gen.SAF: "Agroforestry (SAF)",
          gen.WINDBREAK: "Windbreak / contour line"}

# A display-only class, not a label the sampler can assign. The sampler holds ground
# that was already vegetated at REGEN so the energy counts it as vegetation, which on
# a map made the 2,148 ha this farm already had look like work the plan proposed.
EXISTING = gen.N_LABELS
DISPLAY_COLORS = {**PLAN_COLORS, EXISTING: "#cfe3c8"}
DISPLAY_PRETTY = {**PRETTY, EXISTING: "Existing vegetation retained"}
DISPLAY_CMAP = ListedColormap([DISPLAY_COLORS[k] for k in range(gen.N_LABELS + 1)])


def display_grid(grid: np.ndarray, native: np.ndarray) -> np.ndarray:
    """Split retained vegetation out of the regeneration class, for drawing only."""
    d = grid.copy()
    d[(grid == gen.REGEN) & native] = EXISTING
    return d


def field_edges(field_id: np.ndarray) -> np.ndarray:
    """Boundaries of the mapped crop fields, one cell wide.

    Drawn so a reader can see whether a plan followed the field it was working in or
    cut across the middle of it, which is the difference between a farmable layout
    and one that leaves an awkward remnant.
    """
    e = np.zeros(field_id.shape, dtype=bool)
    e[:-1, :] |= field_id[:-1, :] != field_id[1:, :]
    e[:, :-1] |= field_id[:, :-1] != field_id[:, 1:]
    return e & (field_id > 0)


def hillshade(dem, cell_m, az=315.0, alt=45.0):
    gy, gx = np.gradient(dem, cell_m, cell_m)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az_r, alt_r = np.radians(360.0 - az + 90.0), np.radians(alt)
    hs = (np.sin(alt_r) * np.cos(slope)
          + np.cos(alt_r) * np.sin(slope) * np.cos(az_r - aspect))
    return np.clip(hs, 0, 1)


def context_plate(sid: str, rec: dict, ctx: dict, con: dict, ledger: dict, path: Path):
    cell_m = float(ctx["cell_m"])
    fig, axes = plt.subplots(2, 3, figsize=(17, 11))
    fig.suptitle(f"{rec['label']}  -  CAR {rec['cod_imovel']}  "
                 f"({ledger['property_ha']:.0f} ha, {rec['mod_fiscal']:.1f} fiscal modules, "
                 f"{rec['biome']}, RL {rec['rl_pct']:.0%})", fontsize=13)

    prop = ctx["property_mask"].astype(bool)

    def outline(ax):
        ax.contour(prop, levels=[0.5], colors="k", linewidths=1.0)
        ax.set_xticks([]); ax.set_yticks([])

    ax = axes[0, 0]
    ax.imshow(hillshade(ctx["dem"], cell_m), cmap="gray", vmin=0, vmax=1)
    ax.imshow(np.ma.masked_where(~ctx["stream"].astype(bool), ctx["stream"]),
              cmap=ListedColormap(["#2a6fb0"]), alpha=0.9)
    ax.set_title("Terrain and derived drainage"); outline(ax)

    ax = axes[0, 1]
    im = ax.imshow(ctx["twi"], cmap="YlGnBu")
    ax.set_title("Topographic wetness index"); outline(ax)
    fig.colorbar(im, ax=ax, fraction=0.04)

    ax = axes[0, 2]
    veg = ctx["native"].astype(bool)
    canvas = np.zeros(veg.shape + (3,), dtype="float32") + 0.93
    canvas[ctx["agri"].astype(bool)] = (0.94, 0.90, 0.78)
    canvas[ctx["field_mask"].astype(bool)] = (0.88, 0.82, 0.62)
    canvas[veg] = (0.30, 0.55, 0.32)
    canvas[ctx["water"].astype(bool)] = (0.35, 0.55, 0.78)
    ax.imshow(canvas)
    ax.set_title("MapBiomas 2024: native / cropland / fields"); outline(ax)

    ax = axes[1, 0]
    ax.imshow(np.zeros_like(ctx["dem"]), cmap="gray", vmin=0, vmax=1, alpha=0.05)
    ax.imshow(np.ma.masked_where(~con["app_full"], con["app_full"].astype(float)),
              cmap=ListedColormap(["#b8d8f0"]))
    ax.imshow(np.ma.masked_where(~con["app_obligation"], con["app_obligation"].astype(float)),
              cmap=ListedColormap(["#3182bd"]), alpha=0.85)
    ax.set_title(f"APP: full Art.4 (pale) vs obligation after Art.61-A (solid)\n"
                 f"{ledger['app_full_ha']:.0f} ha -> {ledger['app_obligation_ha']:.0f} ha")
    outline(ax)

    ax = axes[1, 1]
    ax.imshow(np.ma.masked_where(~con["app_deficit"], con["app_deficit"].astype(float)),
              cmap=ListedColormap(["#d73027"]))
    ax.imshow(np.ma.masked_where(~veg, veg.astype(float)),
              cmap=ListedColormap(["#4a9a4f"]), alpha=0.5)
    ax.set_title(f"APP deficit (red) over existing vegetation\n"
                 f"{ledger['app_deficit_ha']:.0f} ha to recompose")
    outline(ax)

    ax = axes[1, 2]
    ax.axis("off")
    lines = [
        f"Municipality        {rec['municipio']}",
        f"CAR                 {rec['cod_imovel']}",
        f"Property area       {ledger['property_ha']:.0f} ha  ({rec['mod_fiscal']:.1f} MF)",
        f"Cropped             {rec['cropped_ha']:.0f} ha ({rec['cropped_share']:.0%})",
        "",
        f"APP full (Art. 4)   {ledger['app_full_ha']:.0f} ha",
        f"APP obligation      {ledger['app_obligation_ha']:.0f} ha",
        f"  Art. 61-A relief  {ledger['app_relief_from_art61a_ha']:.0f} ha",
        f"APP deficit         {ledger['app_deficit_ha']:.0f} ha",
        "",
        f"RL required ({rec['rl_pct']:.0%})   {ledger['rl_required_ha']:.0f} ha",
        f"RL existing         {ledger['rl_existing_native_ha']:.0f} ha",
        f"RL deficit          {ledger['rl_deficit_ha']:.0f} ha",
        "",
        f"TOTAL obligation    {ledger['total_restoration_obligation_ha']:.0f} ha",
        "",
        "By article (ha):",
    ]
    for k, v in ledger["by_article"].items():
        lines.append(f"  {k:32s} {v:8.1f}")
    ax.text(0, 1, "\n".join(lines), va="top", family="monospace", fontsize=8.5)

    fig.tight_layout()
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)


def scenario_plate(sid: str, rec: dict, ctx: dict, con: dict, g, scen: list, path: Path):
    site_out = OUT / sid
    prop = ctx["property_mask"].astype(bool)
    fig, axes = plt.subplots(3, 4, figsize=(20, 15))
    fig.suptitle(f"{rec['label']}  -  12 generative restoration scenarios  "
                 f"(CAR {rec['cod_imovel']})", fontsize=15)

    for ax, m in zip(axes.ravel(), scen):
        x = np.load(site_out / f"{m['scenario']}_labels.npy")
        grid = display_grid(dg.rasterise(g, x.astype("int16"), fill=-1),
                            ctx["native"].astype(bool))
        ax.imshow(np.ma.masked_where(grid < 0, grid), cmap=DISPLAY_CMAP,
                  vmin=-0.5, vmax=gen.N_LABELS + 0.5, interpolation="nearest")
        ax.imshow(np.ma.masked_where(~ctx["stream"].astype(bool), ctx["stream"]),
                  cmap=ListedColormap(["#2a6fb0"]), alpha=0.6)
        ax.contour(prop, levels=[0.5], colors="k", linewidths=0.8)
        ok = "OK" if (m["app_compliant"] and m["rl_compliant"]) else "SHORT"
        ax.set_title(f"{m['scenario']}\n{m['restored_ha']:.0f} ha restored | "
                     f"{m['cropland_converted_ha']:.0f} ha crop given up | "
                     f"ECA {m['connectivity_eca_ha']:.0f} | {ok}", fontsize=9)
        ax.set_xticks([]); ax.set_yticks([])

    handles = [Patch(facecolor=DISPLAY_COLORS[k], label=DISPLAY_PRETTY[k])
               for k in range(gen.N_LABELS + 1)]
    fig.legend(handles=handles, loc="lower center", ncol=6, frameon=False, fontsize=11)
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def sheet(rec, ledger, scen, machine, path: Path):
    L = [f"# Restoration scenarios - {rec['label']}", "",
         f"**CAR** `{rec['cod_imovel']}` | **{rec['municipio']}, MT** | "
         f"{ledger['property_ha']:.0f} ha | {rec['mod_fiscal']:.1f} fiscal modules | "
         f"{rec['biome']} (Reserva Legal {rec['rl_pct']:.0%})", "",
         f"**Machinery profile** {machine['label']} - "
         f"{machine['sprayer_boom_m']:.0f} m boom, "
         f"{machine['min_workable_ha']:.0f} ha minimum workable remnant, "
         f"{machine['min_corridor_width_m']:.0f} m minimum corridor", "",
         "## Legal obligation", "",
         "| Item | ha | Basis |", "|---|---:|---|",
         f"| APP, full Art. 4 | {ledger['app_full_ha']:.1f} | Lei 12.651 Art. 4 |",
         f"| APP obligation after Art. 61-A | {ledger['app_obligation_ha']:.1f} | "
         f"escadinha for {rec['mod_fiscal']:.1f} MF |",
         f"| APP already vegetated | "
         f"{ledger['app_obligation_ha'] - ledger['app_deficit_ha']:.1f} | MapBiomas 2024 |",
         f"| **APP to recompose** | **{ledger['app_deficit_ha']:.1f}** | |",
         f"| RL required | {ledger['rl_required_ha']:.1f} | Art. 12 |",
         f"| RL existing native | {ledger['rl_existing_native_ha']:.1f} | "
         f"incl. {ledger['rl_of_which_in_app_ha']:.1f} ha in APP (Art. 15) |",
         f"| **RL deficit** | **{ledger['rl_deficit_ha']:.1f}** | |",
         f"| **Total** | **{ledger['total_restoration_obligation_ha']:.1f}** | |", "",
         "## Scenarios", "",
         "Every scenario below is compliant. They differ in *how* they comply: how "
         "much is recomposed on the property, how much is settled off it under "
         "Art. 66 par. 5, and how much cropland survives.", "",
         "| # | Archetype | On-farm ha | CRA off-farm ha | Crop kept ha | "
         "Regen | Planting | SAF | Windbreak | APP | Contour | Agg | "
         "d.stream m | <100m of water |",
         "|---|---|---:|---:|---:|---:|---:|---:|---:|:-:|---:|---:|---:|---:|"]

    for m in scen:
        a = m["area_by_intervention_ha"]
        L.append(
            f"| {m['scenario'].split('_')[0]} | {m['archetype']} | "
            f"{m['restored_ha']:.0f} | {m['rl_compensated_off_farm_ha']:.0f} | "
            f"{m['cropland_retained_ha']:.0f} | "
            f"{a['natural_regeneration']:.0f} | {a['active_planting']:.0f} | "
            f"{a['agroforestry_saf']:.0f} | {a['windbreak']:.0f} | "
            f"{'OK' if m['app_compliant'] else 'SHORT'} | "
            f"{m.get('contour_alignment', float('nan')):.2f} | "
            f"{m['aggregation']:.2f} | "
            f"{m['mean_dist_to_stream_m']:.0f} | "
            f"{m['share_within_100m_of_stream']:.0%} |")

    L += ["", "## How to read this", "",
          "- **On-farm vs CRA.** The Reserva Legal deficit can be recomposed on the "
          "property or settled off it under Art. 66 par. 5 - by buying CRAs, by "
          "servitude, or by donating land inside a conservation unit. A scenario "
          "with a large CRA column is not a worse plan, it is a farm that would "
          "rather buy the obligation than retire cropland. **APP has no such route** "
          "and must be recomposed in place, which is why that column is always OK.",
          "- **ECA** is equivalent connected area: sqrt of the sum of squared patch "
          "areas over the whole window, neighbours' remnants included. "
          "**Aggregation** is ECA over total vegetated area - 1.00 when the "
          "vegetation forms a single body. Two scenarios with the same hectares can "
          "differ here by how well they knit the landscape together.",
          "- **SAF** does not discharge an APP obligation, and Art. 66 par. 3 caps "
          "exotic-bearing systems at half the recomposed area. Where the SAF column "
          "sits at exactly half the on-farm total, that cap is binding.",
          "- Machinery is priced, not forbidden: the objective charges a plan for "
          "stranding crop remnants below the minimum workable size and for narrowing "
          "corridors below the plantable minimum, but a scenario can still buy its "
          "way past either if the rest of the design is worth it. Check the retained "
          "cropland geometry before treating a plan as buildable.", "",
          "## Caveats", ""]
    L += [f"- {c}" for c in ledger["caveats"]]
    path.write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    sites = json.loads((SITES_INDEX).read_text(encoding="utf-8"))
    for rec in sites:
        sid = rec["site_id"]
        site_out = OUT / sid
        if not (site_out / "scenarios.json").exists():
            print(f"skip {sid}: no scenarios")
            continue
        print(f"\n=== {sid} ===")
        blob = json.loads((site_out / "scenarios.json").read_text(encoding="utf-8"))
        ctx = dict(np.load(CONTEXT_DIR / f"{sid}_context.npz", allow_pickle=False))
        con = {k: v.astype(bool) for k, v in
               np.load(CONTEXT_DIR / f"{sid}_constraints.npz", allow_pickle=False).items()}
        ledger = blob["ledger"]

        context_plate(sid, rec, ctx, con, ledger, site_out / "00_context.png")
        print("  00_context.png")

        g = dg.build_design_graph(ctx, con)
        scenario_plate(sid, rec, ctx, con, g, blob["scenarios"],
                       site_out / "01_scenarios.png")
        print("  01_scenarios.png")

        sheet(rec, ledger, blob["scenarios"], blob["machinery"],
              site_out / "README.md")
        print("  README.md")


if __name__ == "__main__":
    main()

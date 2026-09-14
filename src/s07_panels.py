"""Stage 7 - break the twelve-panel plate into one figure per scenario.

The comparison plate is for choosing between plans; these are for looking at one.
Each scenario gets its own PNG in outputs/<site>/panels/, at full size, with a
written description of what the plan actually does underneath it, plus a matching
markdown file so the text can be lifted into a report.

    python s07_panels.py                    # every site
    python s07_panels.py primavera_cerrado  # one
"""
from __future__ import annotations

import json
import sys
import textwrap
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
import landcover as lc  # noqa: E402
from config import CONTEXT_DIR, OUT, SITES_INDEX  # noqa: E402
from s05_report import (DISPLAY_CMAP, DISPLAY_COLORS, DISPLAY_PRETTY,  # noqa: E402
                        display_grid, field_edges)

ARCHETYPE_INTENT = {
    "compliance_minimum":
        "meet the law for the least money. Let land come back on its own where that "
        "will work, pay for vegetation elsewhere to settle the rest, and keep as "
        "much of the farm in crops as the law allows",
    "water_first":
        "look after the water and the soil. Put the strips along the streams in "
        "first and plant them so they close fast, then take the wet ground and the "
        "steep ground out of the rotation",
    "corridor_network":
        "join things up. Place the new vegetation where it links this farm's "
        "woodland to the woodland across the fence, and plant rather than wait, "
        "because a corridor does nothing until it runs unbroken",
    "productive_mosaic":
        "keep the land earning while it complies. Agroforestry up to the legal "
        "limit, windbreaks along the field edges",
}


def field_outcomes(g, x, native_blk) -> dict:
    """How the plan treated each mapped field.

    A farmer decides field by field, so the useful question about a plan is not how
    many hectares it took but which fields it took them from.
    """
    fid = g.feat.get("field_id")
    if fid is None or fid.max() == 0:
        return {}
    fid = fid.astype("int64")
    n = int(fid.max())
    new = (x != gen.CROP) & ~native_blk
    counts = np.bincount(fid, minlength=n + 1)[1:].astype("float64")
    conv = np.bincount(fid, weights=new.astype("float64"), minlength=n + 1)[1:]
    frac = np.divide(conv, counts, out=np.zeros_like(conv), where=counts > 0)
    return dict(total=n,
                untouched=int((frac <= 0.02).sum()),
                margin=int(((frac > 0.02) & (frac < 0.40)).sum()),
                split=int(((frac >= 0.40) & (frac < 0.90)).sum()),
                retired=int((frac >= 0.90).sum()))


def describe(m: dict, rec: dict, ledger: dict, fields: dict | None = None) -> str:
    return "\n\n".join(describe_parts(m, rec, ledger, fields))


def describe_parts(m: dict, rec: dict, ledger: dict,
                   fields: dict | None = None) -> list[str]:
    """Plain-language account of one scenario, built from its own metrics."""
    a = m["area_by_intervention_ha"]
    intent = ARCHETYPE_INTENT.get(m["archetype"], "")
    para = []

    para.append(
        f"**{m['archetype'].replace('_', ' ').title()}**, version "
        f"{m['scenario'].rsplit('_s', 1)[1]} of 3. The aim: {intent}.")

    cra = m["rl_compensated_off_farm_ha"]
    oblig = ledger["total_restoration_obligation_ha"]
    if cra > 0.5:
        settle = (
            f"The law asks this property for {oblig:.0f} ha. The plan grows "
            f"{m['restored_ha']:.0f} ha of that on the farm and settles the other "
            f"{cra:.0f} ha somewhere else, which Art. 66 par. 5 allows: buy a CRA "
            f"certificate, place a servitude on other land, or donate land to a "
            f"conservation unit.")
    else:
        over = m["restored_ha"] - oblig
        tail = (f", which is {over:.0f} ha more than required"
                if over > 5 else ", close to the legal minimum")
        settle = (f"The law asks this property for {oblig:.0f} ha. The plan does all "
                  f"of it on the farm and buys nothing elsewhere, restoring "
                  f"{m['restored_ha']:.0f} ha in total{tail}.")
    para.append(f"{settle} {m['cropland_retained_ha']:.0f} ha stays in crops and "
                f"{m['cropland_converted_ha']:.0f} ha comes out.")

    mix = [(a["natural_regeneration"], "left to grow back on its own"),
           (a["active_planting"], "planted with native seedlings"),
           (a["agroforestry_saf"], "agroforestry, trees grown with a crop"),
           (a["windbreak"], "windbreaks and contour tree lines")]
    mix = sorted([(v, n) for v, n in mix if v >= 1.0], reverse=True)
    if mix:
        para.append("The work: " + ", ".join(f"{v:.0f} ha {n}" for v, n in mix) + ".")
    if a.get("existing_native_retained", 0) >= 1.0:
        para.append(
            f"{a['existing_native_retained']:.0f} ha of vegetation was already "
            f"standing, in pale green. The plan keeps it and claims no credit for "
            f"putting it there.")
    if m.get("saf_share_of_restored", 0) > 0.48:
        para.append("Agroforestry is at its ceiling here. Art. 66 par. 3 caps it at "
                    "half the area being restored.")

    if fields:
        parts = [(fields["untouched"], "left whole"),
                 (fields["margin"], "gave up a strip along one edge"),
                 (fields["split"], "lost a large part"),
                 (fields["retired"], "went out of production entirely")]
        para.append(
            f"Fields: of the {fields['total']} mapped fields, "
            + ", ".join(f"{n} {label}" for n, label in parts if n) + ".")

    para.append(
        f"Where it sits: {m['share_within_100m_of_stream']:.0%} within 100 m of a "
        f"stream, averaging {m['mean_dist_to_stream_m']:.0f} m from water and "
        f"{m['mean_dist_to_existing_native_m']:.0f} m from vegetation that was "
        f"already there. The edges score "
        f"{m.get('contour_alignment', float('nan')):.2f} for running along the "
        f"contour, against 1.0 for dead on it and 0.64 for ignoring the ground.")

    para.append(
        f"The area ends up with {m['vegetation_patches']} separate patches, the "
        f"largest {m['largest_patch_ha']:.0f} ha. Scored as one joined-up habitat "
        f"they come to {m['connectivity_eca_ha']:.0f} ha, and that number climbs as "
        f"the patches touch.")

    app = ("APP is fully met."
           if m["app_compliant"] else
           f"WARNING: {m['app_unmet_ha']:.0f} ha of APP is unmet.")
    para.append(app + " Reserva Legal is met "
                + ("on the farm." if m["rl_fully_on_farm"]
                   else "partly by paying for vegetation elsewhere."))
    para.append("Faded colours outside the boundary are the surrounding land cover, "
                "off the same MapBiomas map as the current-state panel. Thin brown "
                "lines are the edges of the mapped fields.")
    return para


def crop_to_property(prop: np.ndarray, margin_frac: float = 0.10) -> tuple:
    """Slices framing the property with a margin, so it fills the panel.

    The context window runs 3 km past the farm for connectivity, which leaves the
    subject about a third of the frame if drawn whole.
    """
    rr, cc = np.nonzero(prop)
    h, w = prop.shape
    mr = int((rr.max() - rr.min()) * margin_frac) + 5
    mc = int((cc.max() - cc.min()) * margin_frac) + 5
    return (slice(max(rr.min() - mr, 0), min(rr.max() + mr + 1, h)),
            slice(max(cc.min() - mc, 0), min(cc.max() + mc + 1, w)))


def panel(sid, rec, ledger, m, ctx, g, out_dir: Path) -> None:
    prop = ctx["property_mask"].astype(bool)
    win = crop_to_property(prop)
    x = np.load(OUT / sid / f"{m['scenario']}_labels.npy")
    grid = display_grid(dg.rasterise(g, x.astype("int16"), fill=-1),
                        ctx["native"].astype(bool))[win]
    stream = ctx["stream"].astype(bool)[win]
    fid = ctx.get("field_id")
    edges = field_edges(fid)[win] if fid is not None else None
    fields = field_outcomes(g, x, g.feat["native"] > 0.5)

    # Size the map band to the parcel's own proportions. Sorriso is a long diagonal
    # strip and Poxoreu is a blocky polygon; a fixed frame gives one of them a page
    # of white space.
    h_px, w_px = grid.shape
    map_w_in = 10.1
    map_h_in = float(np.clip(map_w_in * h_px / max(w_px, 1), 2.6, 9.0))
    # Size the text band to the text. The description runs long on farms with a big
    # obligation, and a fixed band either clipped those or left the short ones with
    # half a page of white.
    body = "\n\n".join(
        "\n".join(textwrap.wrap(p.replace("**", ""), 112))
        for p in describe_parts(m, rec, ledger, fields))
    header_in = 1.15
    # 9.5 pt at 1.5 line spacing is 0.198 in a line; the rest is the legend above
    # and the facts strip below.
    text_in = 1.55 + 0.20 * (body.count("\n") + 1) + 0.70
    fig_h = header_in + map_h_in + text_in
    fig = plt.figure(figsize=(11, fig_h))

    fig.add_axes([0.04, text_in / fig_h, 0.92, map_h_in / fig_h])
    ax = fig.axes[-1]
    # Land cover underneath, faded. The plan only covers the property, so without
    # this the neighbours are blank white and there is no way to see that a corridor
    # runs toward the woodland next door.
    ax.imshow(lc.washed(ctx["mapbiomas"])[win], interpolation="nearest")
    ax.imshow(np.ma.masked_where(grid < 0, grid), cmap=DISPLAY_CMAP,
              vmin=-0.5, vmax=gen.N_LABELS + 0.5, interpolation="nearest")
    if edges is not None and edges.any():
        ax.imshow(np.ma.masked_where(~edges, edges),
                  cmap=ListedColormap(["#4a3f33"]), alpha=0.75)
    ax.imshow(np.ma.masked_where(~stream, stream),
              cmap=ListedColormap(["#2a6fb0"]), alpha=0.55)
    ax.contour(prop[win], levels=[0.5], colors="k", linewidths=1.0)
    ax.set_xticks([]); ax.set_yticks([])

    fig.text(0.04, 1 - 0.30 / fig_h, f"{m['scenario']}",
             fontsize=15, weight="bold", va="top")
    fig.text(0.04, 1 - 0.58 / fig_h,
             f"{rec['label']}  |  {rec['municipio']}, MT  |  "
             f"{ledger['property_ha']:.0f} ha, {rec['mod_fiscal']:.1f} fiscal modules  |  "
             f"{rec['biome']}, Reserva Legal {rec['rl_pct']:.0%}",
             fontsize=9.5, color="#333", va="top")
    fig.text(0.04, 1 - 0.80 / fig_h, f"CAR {rec['cod_imovel']}",
             fontsize=8, color="#777", va="top", family="monospace")

    handles = [Patch(facecolor=DISPLAY_COLORS[k], label=DISPLAY_PRETTY[k])
               for k in range(gen.N_LABELS + 1)]
    if edges is not None and edges.any():
        handles.append(Patch(facecolor="#4a3f33", alpha=0.75,
                             label="Mapped field boundary"))
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.02),
              ncol=4, frameon=False, fontsize=9)

    fig.text(0.04, (text_in - 1.10) / fig_h, body,
             fontsize=9.5, va="top", linespacing=1.5)

    facts = (f"obligation  APP {ledger['app_deficit_ha']:.0f} ha + "
             f"RL {ledger['rl_deficit_ha']:.0f} ha     "
             f"on-farm {m['restored_ha']:.0f} ha     "
             f"CRA {m['rl_compensated_off_farm_ha']:.0f} ha     "
             f"crop kept {m['cropland_retained_ha']:.0f} ha     "
             f"ECA {m['connectivity_eca_ha']:.0f} ha     "
             f"linearity {m.get('contour_alignment', 0):.2f} alignment")
    fig.text(0.04, 0.30 / fig_h, facts, fontsize=8, family="monospace", color="#333")

    out = out_dir / f"{m['scenario']}.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)

    (out_dir / f"{m['scenario']}.md").write_text(
        f"# {m['scenario']}\n\n"
        f"**{rec['label']}** | CAR `{rec['cod_imovel']}` | {rec['municipio']}, MT | "
        f"{ledger['property_ha']:.0f} ha | {rec['mod_fiscal']:.1f} fiscal modules | "
        f"{rec['biome']}, Reserva Legal {rec['rl_pct']:.0%}\n\n"
        f"{describe(m, rec, ledger, fields)}\n",
        encoding="utf-8")


def main() -> None:
    only = sys.argv[1:] or None
    for rec in json.loads(SITES_INDEX.read_text(encoding="utf-8")):
        sid = rec["site_id"]
        if only and sid not in only:
            continue
        blob_path = OUT / sid / "scenarios.json"
        if not blob_path.exists():
            print(f"skip {sid}: no scenarios")
            continue
        print(f"\n=== {sid} ===")
        blob = json.loads(blob_path.read_text(encoding="utf-8"))
        ledger = blob["ledger"]
        ctx = dict(np.load(CONTEXT_DIR / f"{sid}_context.npz", allow_pickle=False))
        con = {k: v.astype(bool) for k, v in
               np.load(CONTEXT_DIR / f"{sid}_constraints.npz", allow_pickle=False).items()}
        g = dg.build_design_graph(ctx, con)

        out_dir = OUT / sid / "panels"
        out_dir.mkdir(parents=True, exist_ok=True)
        index = [f"# {rec['label']} - scenario panels", "",
                 f"CAR `{rec['cod_imovel']}` | {rec['municipio']}, MT | "
                 f"{ledger['property_ha']:.0f} ha | obligation "
                 f"{ledger['total_restoration_obligation_ha']:.0f} ha", ""]
        for m in blob["scenarios"]:
            panel(sid, rec, ledger, m, ctx, g, out_dir)
            index.append(f"- [{m['scenario']}]({m['scenario']}.png) — "
                         f"{m['archetype'].replace('_', ' ')}, "
                         f"{m['restored_ha']:.0f} ha on-farm, "
                         f"{m['cropland_retained_ha']:.0f} ha crop kept")
            print(f"  {m['scenario']}.png")
        (out_dir / "README.md").write_text("\n".join(index) + "\n", encoding="utf-8")
        print(f"  -> {out_dir}")


if __name__ == "__main__":
    main()

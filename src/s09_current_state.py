"""Stage 9 - one panel per site showing the farm as it stands today.

Every scenario panel shows a proposal. This one shows the starting point, so a
reader can tell which of the green on a scenario map was already there and which
the plan put there. Two maps side by side:

    left    land cover from MapBiomas, the stream network, the property boundary
    right   the mapped crop fields, coloured by what grew on them in 2024

    python s09_current_state.py                    # every site
    python s09_current_state.py primavera_cerrado  # one
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from rasterio.features import rasterize  # noqa: E402
from rasterio.transform import Affine  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import landcover as lc  # noqa: E402
from config import CONTEXT_DIR, METRIC_CRS, OUT, SITES_INDEX, site_gpkg  # noqa: E402
from s05_report import field_edges  # noqa: E402
from s07_panels import crop_to_property  # noqa: E402


def crop_raster(rec, shape, transform) -> np.ndarray:
    """Burn each field with the MapBiomas class that covered most of it in 2024."""
    f = gpd.read_file(site_gpkg(rec), layer="fields").to_crs(METRIC_CRS)
    col = "mbmode24" if "mbmode24" in f.columns else None
    if col is None:
        return np.zeros(shape, dtype="uint8")
    pairs = [(g, int(v)) for g, v in zip(f.geometry, f[col].fillna(0))
             if np.isfinite(v)]
    return rasterize(pairs, out_shape=shape, transform=transform,
                     dtype="uint8", fill=0)


def panel(sid: str, rec: dict, ledger: dict, out: Path) -> None:
    ctx = dict(np.load(CONTEXT_DIR / f"{sid}_context.npz", allow_pickle=False))
    transform = Affine.from_gdal(*ctx["transform"])
    prop = ctx["property_mask"].astype(bool)
    win = crop_to_property(prop)

    mb = ctx["mapbiomas"]
    crops = crop_raster(rec, mb.shape, transform)
    stream = ctx["stream"].astype(bool)
    spring = ctx["spring"].astype(bool)
    edges = field_edges(ctx["field_id"])

    h_px, w_px = mb[win].shape
    map_w_in = 5.6
    map_h_in = float(np.clip(map_w_in * h_px / max(w_px, 1), 2.4, 7.5))
    header_in, text_in = 1.15, 2.35
    fig_h = header_in + map_h_in + text_in
    fig = plt.figure(figsize=(12.4, fig_h))

    for i, kind in enumerate(("cover", "fields")):
        ax = fig.add_axes([0.035 + i * 0.485, text_in / fig_h, 0.455,
                           map_h_in / fig_h])
        if kind == "cover":
            ax.imshow(lc.rgb(mb)[win], interpolation="nearest")
        else:
            ax.imshow(np.ones(mb[win].shape), cmap=ListedColormap(["#f7f7f5"]),
                      vmin=0, vmax=1)
            ax.imshow(lc.washed(mb, 0.16)[win], interpolation="nearest")
            shown = [c for c in lc.CROP_CLASSES if (crops == c).sum() > 100]
            for c in shown:
                m = crops[win] == c
                ax.imshow(np.ma.masked_where(~m, m),
                          cmap=ListedColormap([lc.COLORS.get(c, lc.FALLBACK)]),
                          vmin=0, vmax=1, interpolation="nearest")
            ax.imshow(np.ma.masked_where(~edges[win], edges[win]),
                      cmap=ListedColormap(["#2b2b2b"]), alpha=0.85)

        ax.imshow(np.ma.masked_where(~stream[win], stream[win]),
                  cmap=ListedColormap(["#2532e4"]), alpha=0.75)
        sp = spring[win]
        if sp.any():
            rr, cc = np.nonzero(sp)
            ax.plot(cc, rr, ".", color="#0b2f8f", markersize=1.1, alpha=0.6)
        ax.contour(prop[win], levels=[0.5], colors="k", linewidths=1.4)
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title("Land cover today (MapBiomas 2024)" if kind == "cover"
                     else "Crop fields, by what grew on them in 2024",
                     fontsize=10.5, pad=6)

    fig.text(0.035, 1 - 0.30 / fig_h, f"{rec['label']} - the farm as it stands",
             fontsize=15, weight="bold", va="top")
    fig.text(0.035, 1 - 0.58 / fig_h,
             f"{rec['municipio']}, MT  |  {ledger['property_ha']:.0f} ha, "
             f"{rec['mod_fiscal']:.1f} fiscal modules  |  {rec['biome']}, "
             f"Reserva Legal {rec['rl_pct']:.0%}",
             fontsize=9.5, color="#333", va="top")
    fig.text(0.035, 1 - 0.80 / fig_h, f"CAR {rec['cod_imovel']}",
             fontsize=8, color="#777", va="top", family="monospace")

    cover = [Patch(facecolor=lc.COLORS.get(k, lc.FALLBACK), label=lc.NAMES[k])
             for k in lc.present(mb[win])]
    cover.append(Patch(facecolor="#2532e4", label="Streams and rivers"))
    # Both blocks hang off the bottom of the map. Anchoring them to the bottom of
    # the page instead leaves a hole under short wide parcels like Sorriso, which is
    # a 12 km strip and only fills a band of the frame.
    fig.legend(handles=cover, loc="upper left",
               bbox_to_anchor=(0.035, (text_in - 0.25) / fig_h),
               ncol=5, frameon=False, fontsize=8.5)

    fig.text(0.035, (text_in - 1.20) / fig_h, summary(ctx, crops, ledger, rec),
             fontsize=9.5, va="top", linespacing=1.5)
    fig.savefig(out, dpi=130)
    plt.close(fig)


def summary(ctx, crops, ledger, rec) -> str:
    px_ha = float(ctx["cell_m"]) ** 2 / 1e4
    prop = ctx["property_mask"].astype(bool)
    inside = lambda m: float((m & prop).sum() * px_ha)  # noqa: E731

    n_fields = int(ctx["field_id"].max())
    field_ha = inside(ctx["field_mask"].astype(bool))
    native_ha = inside(ctx["native"].astype(bool))

    mix = [(inside(crops == c), lc.NAMES[c]) for c in lc.CROP_CLASSES]
    mix = sorted([(v, n) for v, n in mix if v >= 1.0], reverse=True)[:4]
    crop_txt = ", ".join(f"{n.lower()} {v:.0f} ha" for v, n in mix)

    lines = [
        f"The property covers {ledger['property_ha']:.0f} ha. It holds "
        f"{n_fields} mapped crop fields totalling {field_ha:.0f} ha, and "
        f"{native_ha:.0f} ha of native vegetation.",
        f"What grew there in 2024: {crop_txt}." if crop_txt else "",
        f"The law asks for {ledger['app_deficit_ha']:.0f} ha of riparian and other "
        f"protected strips (APP) and {ledger['rl_deficit_ha']:.0f} ha toward the "
        f"Reserva Legal, {ledger['total_restoration_obligation_ha']:.0f} ha in all.",
        "The scenario panels start from this map. Anything green on those maps "
        "that is also green here was already standing.",
    ]
    return "\n".join(x for x in lines if x)


def main() -> None:
    only = sys.argv[1:] or None
    for rec in json.loads(SITES_INDEX.read_text(encoding="utf-8")):
        sid = rec["site_id"]
        if only and sid not in only:
            continue
        ledger_path = CONTEXT_DIR / f"{sid}_ledger.json"
        if not ledger_path.exists():
            print(f"skip {sid}: no ledger")
            continue
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        out = OUT / sid / "00_current_state.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        panel(sid, rec, ledger, out)
        print(f"  {out}")


if __name__ == "__main__":
    main()

"""Stage 10 - an animated walk through every scenario on a site.

The still panels let you study one plan. This shows where the plans came from. Each
archetype gets one group:

    1. the farm as it is now
    2. the key layers for that kind of plan, one at a time
    3. the three plans they produced, run together so the differences show

The driver frames are drawn dark, on a shared colour ramp, so they read as inputs to
the model rather than as proposals for the land. The plan frames stay light and use
the same palette as the still panels.

Frames cross-fade, and every frame is the same size, because a GIF cannot change
canvas mid-stream.

    python s10_animation.py                    # every site
    python s10_animation.py primavera_cerrado  # one
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
from PIL import Image  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import design_graph as dg  # noqa: E402
import generative as gen  # noqa: E402
import landcover as lc  # noqa: E402
from config import CONTEXT_DIR, OUT, SITES_INDEX  # noqa: E402
from s05_report import (DISPLAY_CMAP, DISPLAY_COLORS, DISPLAY_PRETTY,  # noqa: E402
                        EXISTING, display_grid, field_edges)
from s07_panels import crop_to_property  # noqa: E402

# How long each beat holds, in milliseconds, plus the cross-fade between beats.
HOLD_BASE = 2600
HOLD_DRIVER = 3400
HOLD_PLAN = 4200
FADE_STEPS = 1
FADE_MS = 90

# Frames are written at 0.85 scale. A GIF carries every frame whole, so the fades
# multiply the file size, and a 60 MB animation is no use to anyone.
FRAME_SCALE = 0.85
GIF_COLORS = 150

# Every driver uses one ramp, so the eye learns it once. Dark ground, cool where the
# layer is quiet, hot where it pulls hardest.
DRIVER_CMAP = "magma"
INK, PAPER = "#e8e6e3", "#17181c"
VEG_DARK = "#2f4034"

# What each group of frames is called. The archetype keys are code names; these are
# what a reader sees.
ARCH_NAME = {
    "compliance_minimum": "Minimum legal compliance",
    "water_first": "Water and soil first",
    "corridor_network": "Network connectivity",
    "productive_mosaic": "Productive mosaic",
}
DRIVER_TITLE = {
    "compliance_minimum": "Generative land use based on Brazil's regulations",
    "water_first": "Key layers for water and soil protection",
    "corridor_network": "Key layers to network connectivity plans",
    "productive_mosaic": "Key layers for a productive mosaic",
}


def _d(layer, why, low=None, high=None, invert=False, categorical=False):
    return dict(layer=layer, why=why, low=low, high=high, invert=invert,
                categorical=categorical)


DRIVERS = {
    "compliance_minimum": [
        _d("app_deficit",
           "The law puts a strip of vegetation along every stream, spring and steep "
           "face. Here is where that strip is missing."),
        _d("dist_to_native",
           "Distance to vegetation already standing. Seed has to get there. Beside a "
           "remnant a field comes back on its own; in the middle of a soy block it "
           "does not.",
           "far from any", "beside existing vegetation", invert=True),
        _d("field_mask",
           "Land in crops. Taking any of it costs a harvest every year from now on."),
    ],
    "water_first": [
        _d("dist_to_stream",
           "Distance to running water. Trees on a bank hold it together and catch "
           "what washes off the field above.",
           "far from water", "on the stream", invert=True),
        _d("twi",
           "Where water collects, read off the shape of the ground. Wet spots grow a "
           "poor crop.", "sheds water", "collects water"),
        _d("slope_deg",
           "Slope. Ploughed steep ground loses its soil, and the steepest of it is "
           "protected outright.", "flat", "steep"),
    ],
    "corridor_network": [
        _d("native",
           "What is standing now, on this farm and across the fence."),
        _d("dist_to_native",
           "Size of the gap. Closing a short gap joins two patches into one; the "
           "same hectares planted on their own join nothing.",
           "a long way off", "touching a patch", invert=True),
        _d("slope_deg",
           "Slope, which sets where a corridor can run and still be crossed by a "
           "tractor.", "flat", "steep"),
    ],
    "productive_mosaic": [
        _d("field_id",
           "Every field in its own colour. A farm gets managed one field at a time, "
           "so the plan works to these lines.", categorical=True),
        _d("dist_to_stream",
           "Distance to water. The strips the law requires get placed from this "
           "before anything optional is considered.",
           "far from water", "on the stream", invert=True),
        _d("dist_to_native",
           "Distance to standing vegetation. This is what decides between letting a "
           "hectare come back and paying to plant it.",
           "far from any", "beside existing vegetation", invert=True),
    ],
}

MAP_MAX_W, MAP_MAX_H = 9.6, 6.8
# Querencia is a tall narrow strip. Sizing purely from its shape gave a 330 px wide
# frame, too narrow for a caption, so the frame never goes below this and the map
# letterboxes inside it against the page colour.
MAP_MIN_W = 6.4
MARGIN_IN = 0.40
# Both bands are fixed, so a two-line title on one frame and a one-line title on the
# next still produce the same canvas.
HEADER_IN = 1.55
BAND_IN = 2.05


def wrap_to(text: str, width_in: float, chars_per_in: float) -> str:
    n = max(int(width_in * chars_per_in), 24)
    return "\n".join("\n".join(textwrap.wrap(line, n)) or ""
                     for line in text.split("\n"))


def frame_canvas(shape, site_line: str, title: str, dark: bool = False) -> tuple:
    """A canvas sized to the parcel, with the map filling it edge to edge."""
    h_px, w_px = shape
    aspect = h_px / max(w_px, 1)
    if aspect > MAP_MAX_H / MAP_MAX_W:
        map_h_in, map_w_in = MAP_MAX_H, max(MAP_MAX_H / aspect, MAP_MIN_W)
    else:
        map_w_in, map_h_in = MAP_MAX_W, MAP_MAX_W * aspect
    fig_w = map_w_in + 2 * MARGIN_IN
    fig_h = HEADER_IN + map_h_in + BAND_IN

    bg = PAPER if dark else "white"
    fg = INK if dark else "black"
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor=bg)
    left = MARGIN_IN / fig_w
    ax = fig.add_axes([left, BAND_IN / fig_h, map_w_in / fig_w, map_h_in / fig_h])
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_facecolor(bg)

    head = wrap_to(title, map_w_in, 12.5)
    fig.text(left, 1 - 0.30 / fig_h, head, fontsize=13.5, weight="bold",
             color=fg, va="top", linespacing=1.3)
    sub_y = 0.34 + 0.25 * (head.count("\n") + 1) + 0.10
    fig.text(left, 1 - sub_y / fig_h, wrap_to(site_line, map_w_in, 14),
             fontsize=8.5, color="#9a9691" if dark else "#666", va="top")
    return fig, ax, fig_h, left, map_w_in


def caption(fig, fig_h, left, map_w_in, text: str, dark: bool = False) -> None:
    fig.text(left, (BAND_IN - 0.28) / fig_h, wrap_to(text, map_w_in, 11.5),
             fontsize=10, va="top", linespacing=1.45,
             color=INK if dark else "black")


def render(fig) -> Image.Image:
    fig.canvas.draw()
    # buffer_rgba rather than tostring_rgb, which matplotlib 3.10 removed.
    img = Image.frombytes("RGBA", fig.canvas.get_width_height(),
                          bytes(fig.canvas.buffer_rgba())).convert("RGB")
    plt.close(fig)
    if FRAME_SCALE != 1.0:
        w, h = img.size
        img = img.resize((int(w * FRAME_SCALE), int(h * FRAME_SCALE)),
                         Image.LANCZOS)
    return img


# --------------------------------------------------------------------------
# the three kinds of frame
# --------------------------------------------------------------------------

def frame_base(ctx, prop, win, edges, site_line, ledger) -> Image.Image:
    """Today, drawn in the same colours the plans use.

    Drawn in raw MapBiomas colours it looked like a different kind of map, and the
    eye had to translate before it could see what a plan had changed. Here it is the
    same picture with nothing added: cropland cream, standing vegetation pale green.
    """
    fig, ax, fig_h, left, mw = frame_canvas(prop[win].shape, site_line,
                                            "The farm currently")
    ax.imshow(lc.washed(ctx["mapbiomas"])[win], interpolation="nearest")

    native = ctx["native"].astype(bool)
    grid = np.full(prop.shape, -1, dtype="int16")
    grid[prop] = gen.CROP
    grid[prop & native] = EXISTING
    ax.imshow(np.ma.masked_where(grid[win] < 0, grid[win]), cmap=DISPLAY_CMAP,
              vmin=-0.5, vmax=gen.N_LABELS + 0.5, interpolation="nearest")

    if edges is not None and edges.any():
        ax.imshow(np.ma.masked_where(~edges[win], edges[win]),
                  cmap=ListedColormap(["#4a3f33"]), alpha=0.7)
    stream = ctx["stream"].astype(bool)[win]
    ax.imshow(np.ma.masked_where(~stream, stream),
              cmap=ListedColormap(["#2a6fb0"]), alpha=0.55)
    ax.contour(prop[win], levels=[0.5], colors="k", linewidths=1.3)

    px_ha = float(ctx["cell_m"]) ** 2 / 1e4
    native_ha = (native & prop).sum() * px_ha
    crop_ha = (ctx["field_mask"].astype(bool) & prop).sum() * px_ha
    caption(fig, fig_h, left, mw,
            f"{ledger['property_ha']:.0f} ha. "
            f"{int(ctx['field_id'].max())} fields, {crop_ha:.0f} ha of them worked. "
            f"{native_ha:.0f} ha already under native vegetation.\n"
            f"The law wants another "
            f"{ledger['total_restoration_obligation_ha']:.0f} ha.")
    handles = [Patch(facecolor=DISPLAY_COLORS[k], label=DISPLAY_PRETTY[k])
               for k in (gen.CROP, EXISTING)]
    fig.legend(handles=handles, loc="lower left",
               bbox_to_anchor=(left - 0.008, 0.012), ncol=3, frameon=False,
               fontsize=8.5)
    return render(fig)


def _normalise(a: np.ndarray, invert: bool) -> tuple:
    """Scale a driver layer to 0..1 so every one of them reads on the same ramp."""
    finite = np.isfinite(a)
    if a[finite].max() <= 1.001:                     # already a mask
        return np.clip(a, 0, 1), finite & (a > 0)
    lo, hi = np.percentile(a[finite], [2, 98])
    v = np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1)
    return (1.0 - v if invert else v), finite


def frame_driver(ctx, con, prop, win, site_line, d: dict, n: int,
                 of: int, arch: str) -> Image.Image:
    fig, ax, fig_h, left, mw = frame_canvas(
        prop[win].shape, site_line,
        f"{DRIVER_TITLE.get(arch, arch)}  ({n} of {of})", dark=True)

    # A dark silhouette of the standing vegetation, so the driver has somewhere to
    # sit without the land cover competing with it.
    ax.imshow(np.zeros(prop[win].shape), cmap=ListedColormap([PAPER]),
              vmin=0, vmax=1, interpolation="nearest")
    veg = ctx["native"].astype(bool)[win]
    ax.imshow(np.ma.masked_where(~veg, veg), cmap=ListedColormap([VEG_DARK]),
              vmin=0, vmax=1, interpolation="nearest")

    layer = d["layer"]
    a = np.asarray(con[layer] if layer in con else ctx[layer], dtype="float32")[win]
    if d["categorical"]:
        rng = np.random.default_rng(7)
        n_f = int(a.max())
        shuf = np.concatenate([[0.0], rng.random(n_f) * 0.75 + 0.2])
        v = shuf[a.astype("int32")]
        ax.imshow(np.ma.masked_where(a == 0, v), cmap=DRIVER_CMAP, vmin=0, vmax=1,
                  interpolation="nearest")
    else:
        v, m = _normalise(a, d["invert"])
        ax.imshow(np.ma.masked_where(~m, v), cmap=DRIVER_CMAP, vmin=0, vmax=1,
                  interpolation="nearest", alpha=0.92)

    stream = ctx["stream"].astype(bool)[win]
    ax.imshow(np.ma.masked_where(~stream, stream),
              cmap=ListedColormap(["#5b8fd6"]), alpha=0.45)
    # The ramp runs from near-black to near-white, so a single-colour boundary
    # disappears over one end of it or the other. Dark stroke, light core.
    ax.contour(prop[win], levels=[0.5], colors="#0d0d10", linewidths=3.0)
    ax.contour(prop[win], levels=[0.5], colors=INK, linewidths=1.1)

    caption(fig, fig_h, left, mw, d["why"], dark=True)
    if d["low"]:
        w = ax.get_position().width * 0.46
        cax = fig.add_axes([left, 0.62 / fig_h, w, 0.11 / fig_h])
        cax.imshow(np.linspace(0, 1, 256)[None, :], aspect="auto",
                   cmap=DRIVER_CMAP)
        cax.set_xticks([]); cax.set_yticks([])
        for s in cax.spines.values():
            s.set_edgecolor("#555")
        fig.text(left, 0.50 / fig_h, d["low"], fontsize=8, color="#9a9691",
                 va="top")
        fig.text(left + w, 0.50 / fig_h, d["high"], fontsize=8, color="#9a9691",
                 va="top", ha="right")
    return render(fig)


def frame_plan(sid, ctx, prop, win, edges, site_line, m, g,
               version: int) -> Image.Image:
    fig, ax, fig_h, left, mw = frame_canvas(
        prop[win].shape, site_line,
        f"{ARCH_NAME.get(m['archetype'], m['archetype'])} - version "
        f"{version} of 3")
    ax.imshow(lc.washed(ctx["mapbiomas"])[win], interpolation="nearest")
    x = np.load(OUT / sid / f"{m['scenario']}_labels.npy")
    grid = display_grid(dg.rasterise(g, x.astype("int16"), fill=-1),
                        ctx["native"].astype(bool))[win]
    ax.imshow(np.ma.masked_where(grid < 0, grid), cmap=DISPLAY_CMAP,
              vmin=-0.5, vmax=gen.N_LABELS + 0.5, interpolation="nearest")
    if edges is not None and edges.any():
        ax.imshow(np.ma.masked_where(~edges[win], edges[win]),
                  cmap=ListedColormap(["#4a3f33"]), alpha=0.7)
    stream = ctx["stream"].astype(bool)[win]
    ax.imshow(np.ma.masked_where(~stream, stream),
              cmap=ListedColormap(["#2a6fb0"]), alpha=0.55)
    ax.contour(prop[win], levels=[0.5], colors="k", linewidths=1.3)

    a = m["area_by_intervention_ha"]
    caption(fig, fig_h, left, mw,
            f"{m['restored_ha']:.0f} ha restored on the farm, "
            f"{m['rl_compensated_off_farm_ha']:.0f} ha settled elsewhere, "
            f"{m['cropland_retained_ha']:.0f} ha still in crops.\n"
            f"{a['natural_regeneration']:.0f} ha left to grow back, "
            f"{a['active_planting']:.0f} ha planted, "
            f"{a['agroforestry_saf']:.0f} ha agroforestry, "
            f"{a['windbreak']:.0f} ha windbreaks.")
    handles = [Patch(facecolor=DISPLAY_COLORS[k], label=DISPLAY_PRETTY[k])
               for k in range(gen.N_LABELS + 1)]
    fig.legend(handles=handles, loc="lower left",
               bbox_to_anchor=(left - 0.008, 0.012),
               ncol=3 if mw < 8.4 else 4, frameon=False, fontsize=8.5)
    return render(fig)


# --------------------------------------------------------------------------

def _solid(like: Image.Image, colour: str) -> Image.Image:
    return Image.new("RGB", like.size, colour)


def with_fades(keys: list) -> tuple:
    """Insert blended frames between each pair, wrapping round to the start.

    Blending a dark frame straight into a light one leaves both captions legible at
    once, which reads as a printing error. Where the background changes, the fade
    dips through flat colour so one caption is gone before the next arrives.
    """
    frames, holds = [], []
    for i, (img, hold, dark) in enumerate(keys):
        frames.append(img)
        holds.append(hold)
        nxt, _, nxt_dark = keys[(i + 1) % len(keys)]
        if dark == nxt_dark:
            for s in range(1, FADE_STEPS + 1):
                frames.append(Image.blend(img, nxt, s / (FADE_STEPS + 1)))
                holds.append(FADE_MS)
        else:
            frames.append(_solid(img, PAPER if dark else "white"))
            holds.append(FADE_MS)
    return frames, holds


def animate(sid: str, rec: dict) -> Path | None:
    blob_path = OUT / sid / "scenarios.json"
    if not blob_path.exists():
        print(f"skip {sid}: no scenarios")
        return None
    blob = json.loads(blob_path.read_text(encoding="utf-8"))
    ledger = blob["ledger"]
    ctx = dict(np.load(CONTEXT_DIR / f"{sid}_context.npz", allow_pickle=False))
    con = {k: v.astype("float32") for k, v in
           np.load(CONTEXT_DIR / f"{sid}_constraints.npz", allow_pickle=False).items()}
    g = dg.build_design_graph(ctx, {k: v.astype(bool) for k, v in con.items()})

    prop = ctx["property_mask"].astype(bool)
    win = crop_to_property(prop)
    edges = field_edges(ctx["field_id"])
    site_line = (f"{rec['label']}  |  {rec['municipio']}, MT  |  "
                 f"{rec['biome']}, Reserva Legal {rec['rl_pct']:.0%}")

    by_arch: dict[str, list] = {}
    for m in blob["scenarios"]:
        by_arch.setdefault(m["archetype"], []).append(m)

    base = frame_base(ctx, prop, win, edges, site_line, ledger)
    keys = []
    for arch, scens in by_arch.items():
        drivers = DRIVERS.get(arch, [])
        keys.append((base, HOLD_BASE, False))
        for i, d in enumerate(drivers):
            keys.append((frame_driver(ctx, con, prop, win, site_line, d,
                                      i + 1, len(drivers), arch),
                         HOLD_DRIVER, True))
        for v, m in enumerate(scens, start=1):
            keys.append((frame_plan(sid, ctx, prop, win, edges, site_line, m, g, v),
                         HOLD_PLAN, False))
        print(f"  {arch}: {len(drivers)} layers, {len(scens)} versions")

    frames, holds = with_fades(keys)
    out = OUT / sid / "03_walkthrough.gif"
    quant = [f.quantize(colors=GIF_COLORS, method=Image.MEDIANCUT) for f in frames]
    quant[0].save(out, save_all=True, append_images=quant[1:], duration=holds,
                  loop=0, optimize=True, disposal=2)
    print(f"  -> {out.name}  {len(frames)} frames, {sum(holds) / 1000:.0f} s, "
          f"{out.stat().st_size / 1e6:.1f} MB, {quant[0].size[0]}x{quant[0].size[1]}")
    return out


def main() -> None:
    only = sys.argv[1:] or None
    for rec in json.loads(SITES_INDEX.read_text(encoding="utf-8")):
        sid = rec["site_id"]
        if only and sid not in only:
            continue
        print(f"\n=== {sid} ===")
        animate(sid, rec)


if __name__ == "__main__":
    main()

"""Parametric design lines: contours, stream bands and field edges.

The sampler's original proposals painted discs, so every plan came out as blobs no
matter how the objective was weighted. A blob is a legitimate restoration form —
thickening an existing remnant is often the best thing to do — but it is not the
only one, and it is not what a farmer sees when they look at a slope.

This module supplies the other vocabulary: real polylines traced along the land's
own contours, resampled, curvature-limited so a tractor can follow them, and
rasterised to a strip of a stated width. Which vocabulary the sampler reaches for
is set by `linearity` in data/design.json, so the same site can be planned as
contour agriculture or as consolidated blocks without touching the code.

Drivability is enforced here, at construction, rather than paid for in the
objective: a centreline whose radius falls below the machine's turning radius is
split, and the pieces too short to be worth entering are dropped. A strip that
exists is therefore already drivable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage as ndi


@dataclass
class LineLibrary:
    """Design lines for one site, in block-lattice coordinates."""
    contours: list = field(default_factory=list)      # list of (N,2) float arrays
    contour_level: list = field(default_factory=list)  # elevation of each
    block_m: float = 60.0
    shape: tuple = (0, 0)
    interval_m: float = 0.0    # the interval actually used after adaptation

    def __len__(self):
        return len(self.contours)


def _resample(line: np.ndarray, step: float) -> np.ndarray:
    """Resample a polyline to roughly constant spacing."""
    seg = np.diff(line, axis=0)
    d = np.hypot(seg[:, 0], seg[:, 1])
    s = np.concatenate([[0.0], np.cumsum(d)])
    total = s[-1]
    if total < step:
        return line
    n = max(int(total / step) + 1, 2)
    t = np.linspace(0, total, n)
    return np.stack([np.interp(t, s, line[:, 0]), np.interp(t, s, line[:, 1])], axis=1)


def _curvature_radius(line: np.ndarray) -> np.ndarray:
    """Radius of the circle through each consecutive triple, in the line's units.

    Straight runs give inf. Used to cut a contour where it doubles back tighter
    than the machinery can follow.
    """
    if len(line) < 3:
        return np.full(len(line), np.inf)
    a, b, c = line[:-2], line[1:-1], line[2:]
    ab = np.hypot(*(b - a).T)
    bc = np.hypot(*(c - b).T)
    ca = np.hypot(*(a - c).T)
    # Twice the triangle area via the cross product.
    cross = np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
                   - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))
    with np.errstate(divide="ignore", invalid="ignore"):
        r = (ab * bc * ca) / (2.0 * cross)
    r[~np.isfinite(r)] = np.inf
    return np.concatenate([[np.inf], r, [np.inf]])


def _split_on_curvature(line: np.ndarray, min_radius: float,
                        min_len: float) -> list[np.ndarray]:
    """Cut a polyline wherever it turns tighter than the machine can, drop stubs."""
    r = _curvature_radius(line)
    ok = r >= min_radius
    pieces, start = [], None
    for i, good in enumerate(ok):
        if good and start is None:
            start = i
        elif not good and start is not None:
            if i - start >= 3:
                pieces.append(line[start:i])
            start = None
    if start is not None and len(line) - start >= 3:
        pieces.append(line[start:])

    out = []
    for p in pieces:
        seg = np.diff(p, axis=0)
        if np.hypot(seg[:, 0], seg[:, 1]).sum() >= min_len:
            out.append(p)
    return out


def build_contour_library(dem_blocks: np.ndarray, inside: np.ndarray, block_m: float,
                          interval_m: float, min_turn_radius_m: float,
                          min_strip_length_m: float,
                          smooth_blocks: float = 1.5) -> LineLibrary:
    """Trace drivable contour lines across the property.

    `dem_blocks` and `inside` are on the block lattice. Elevations are metres; all
    lengths are metres and converted to lattice units internally.
    """
    import contourpy

    lib = LineLibrary(block_m=block_m, shape=dem_blocks.shape)
    if not inside.any():
        return lib

    z = dem_blocks.astype("float64").copy()
    # Contours of a raw 30 m DEM are ragged; a light smooth gives lines a tractor
    # could actually follow without changing where the slope is.
    z = ndi.gaussian_filter(z, smooth_blocks)
    lo, hi = np.percentile(z[inside], [1, 99])
    if not np.isfinite([lo, hi]).all() or hi - lo < interval_m:
        return lib

    gen = contourpy.contour_generator(z=z)
    min_r_blocks = min_turn_radius_m / block_m
    min_len_blocks = min_strip_length_m / block_m

    # On the Mato Grosso chapadas the relief across a whole farm can be under 30 m,
    # so a fixed interval yields a handful of lines and the sampler has almost
    # nothing to work with. Tighten the interval until there is a usable family, or
    # until the lines are closer together than a single strip is wide.
    target_lines = 60
    while True:
        lib.contours.clear()
        lib.contour_level.clear()
        _trace(gen, lib, lo, hi, interval_m, inside, z.shape,
               min_r_blocks, min_len_blocks)
        if len(lib.contours) >= target_lines or interval_m <= 2.0:
            break
        interval_m /= 2.0
    lib.interval_m = interval_m
    return lib


def _trace(gen, lib, lo, hi, interval_m, inside, shape,
           min_r_blocks, min_len_blocks) -> None:
    levels = np.arange(np.floor(lo / interval_m) * interval_m, hi, interval_m)
    for lev in levels:
        try:
            lines = gen.lines(float(lev))
        except Exception:
            continue
        for ln in lines:
            if len(ln) < 4:
                continue
            # contourpy returns (x, y) = (col, row); keep (row, col) throughout.
            rc = np.stack([ln[:, 1], ln[:, 0]], axis=1)
            rc = _resample(rc, 1.0)
            for piece in _split_on_curvature(rc, min_r_blocks, min_len_blocks):
                # Keep only the part that lies on the property.
                rr = np.clip(np.round(piece[:, 0]).astype(int), 0, shape[0] - 1)
                cc = np.clip(np.round(piece[:, 1]).astype(int), 0, shape[1] - 1)
                if inside[rr, cc].mean() < 0.5:
                    continue
                lib.contours.append(piece)
                lib.contour_level.append(float(lev))


def rasterise_strip(line: np.ndarray, shape: tuple, width_m: float,
                    block_m: float) -> np.ndarray:
    """Boolean lattice mask for a strip of the given width along a polyline.

    The distance transform runs on a bounding box around the line, not the whole
    lattice. At the 10 m grid the lattice is millions of cells and a strip touches a
    few thousand of them; transforming the lot on every proposal was the single
    biggest cost in the sampler.
    """
    mask = np.zeros(shape, dtype=bool)
    rr = np.clip(np.round(line[:, 0]).astype(int), 0, shape[0] - 1)
    cc = np.clip(np.round(line[:, 1]).astype(int), 0, shape[1] - 1)
    half = max(width_m / 2.0 / block_m, 0.5)
    if half <= 0.5:
        mask[rr, cc] = True
        return mask

    pad = int(np.ceil(half)) + 2
    r0, r1 = max(rr.min() - pad, 0), min(rr.max() + pad + 1, shape[0])
    c0, c1 = max(cc.min() - pad, 0), min(cc.max() + pad + 1, shape[1])
    sub = np.zeros((r1 - r0, c1 - c0), dtype=bool)
    sub[rr - r0, cc - c0] = True
    mask[r0:r1, c0:c1] = ndi.distance_transform_edt(~sub) <= half
    return mask


def snap_width(width_m: float, implement_m: float, min_width_m: float) -> float:
    """Round a strip width to a whole number of machine passes.

    A 33 m strip beside a 36 m boom wastes a pass; a 36 m strip does not. Snapping
    here is what makes the plan's geometry match the equipment that has to build
    and maintain it.
    """
    if implement_m <= 0:
        return max(width_m, min_width_m)
    n = max(1, int(round(width_m / implement_m)))
    return max(n * implement_m, min_width_m)


def band_along_mask(mask: np.ndarray, width_m: float, block_m: float,
                    window: tuple | None = None) -> np.ndarray:
    """A band of the given total width centred on a linear feature (stream, edge).

    Pass `window` (a pair of slices) to confine the distance transform to a
    sub-rectangle; the caller usually only wants the band inside one anyway, and on
    the 10 m grid the full-lattice transform is the expensive part.
    """
    out = np.zeros(mask.shape, dtype=bool)
    if not mask.any():
        return out
    if window is None:
        out[:] = (ndi.distance_transform_edt(~mask) * block_m) <= width_m / 2.0
        return out

    pad = int(np.ceil(width_m / block_m)) + 2
    rs, cs = window
    r0, r1 = max(rs.start - pad, 0), min(rs.stop + pad, mask.shape[0])
    c0, c1 = max(cs.start - pad, 0), min(cs.stop + pad, mask.shape[1])
    sub = mask[r0:r1, c0:c1]
    if not sub.any():
        return out
    band = (ndi.distance_transform_edt(~sub) * block_m) <= width_m / 2.0
    out[r0:r1, c0:c1] = band
    return out


def field_edge_mask(field_blocks: np.ndarray) -> np.ndarray:
    """The outline of the cropped area - where a windbreak costs least to work around."""
    er = ndi.binary_erosion(field_blocks, structure=np.ones((3, 3)))
    return field_blocks & ~er

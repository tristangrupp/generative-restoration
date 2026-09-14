"""Minimal pure-numpy terrain hydrology: depression fill, D8 flow, accumulation.

Written because richdem/pysheds are not installed in the `crop` env. Grids here are
small (a few hundred cells per side), so clarity beats micro-optimisation.
"""
from __future__ import annotations

import heapq

import numpy as np

# D8 neighbour offsets, clockwise from east.
D8 = [(0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1)]


def fill_depressions(dem: np.ndarray, nodata_mask: np.ndarray | None = None,
                     epsilon: float = 1e-3) -> np.ndarray:
    """Priority-flood depression filling with a small gradient imposed (Barnes 2014).

    The epsilon slope guarantees every filled cell drains, so D8 never deadlocks.
    """
    nrow, ncol = dem.shape
    filled = np.full_like(dem, np.inf, dtype="float64")
    closed = np.zeros(dem.shape, dtype=bool)
    if nodata_mask is None:
        nodata_mask = ~np.isfinite(dem)

    heap: list[tuple[float, int, int]] = []
    # Seed with the grid edge and with any cell touching nodata.
    edge = np.zeros(dem.shape, dtype=bool)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    seed = edge & ~nodata_mask
    for r, c in zip(*np.where(seed)):
        filled[r, c] = dem[r, c]
        closed[r, c] = True
        heapq.heappush(heap, (float(dem[r, c]), int(r), int(c)))
    closed |= nodata_mask

    while heap:
        z, r, c = heapq.heappop(heap)
        for dr, dc in D8:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < nrow and 0 <= cc < ncol) or closed[rr, cc]:
                continue
            zz = max(float(dem[rr, cc]), z + epsilon)
            filled[rr, cc] = zz
            closed[rr, cc] = True
            heapq.heappush(heap, (zz, rr, cc))

    filled[nodata_mask] = np.nan
    return filled


def d8_flowdir(filled: np.ndarray, cell_m: float) -> np.ndarray:
    """Index into D8 of the steepest descent neighbour; -1 where undefined."""
    nrow, ncol = filled.shape
    best_slope = np.full(filled.shape, -np.inf)
    flowdir = np.full(filled.shape, -1, dtype="int8")

    for k, (dr, dc) in enumerate(D8):
        shifted = np.full(filled.shape, np.nan)
        r0, r1 = max(0, -dr), min(nrow, nrow - dr)
        c0, c1 = max(0, -dc), min(ncol, ncol - dc)
        shifted[r0:r1, c0:c1] = filled[r0 + dr:r1 + dr, c0 + dc:c1 + dc]
        dist = cell_m * (np.hypot(dr, dc))
        slope = (filled - shifted) / dist
        better = np.isfinite(slope) & (slope > best_slope)
        best_slope[better] = slope[better]
        flowdir[better] = k

    flowdir[~np.isfinite(filled)] = -1
    return flowdir


def flow_accumulation(flowdir: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Number of upslope cells draining through each cell, itself included."""
    nrow, ncol = flowdir.shape
    indeg = np.zeros(flowdir.shape, dtype="int32")
    tgt_r = np.full(flowdir.shape, -1, dtype="int32")
    tgt_c = np.full(flowdir.shape, -1, dtype="int32")

    rr, cc = np.where(flowdir >= 0)
    for r, c in zip(rr, cc):
        dr, dc = D8[flowdir[r, c]]
        r2, c2 = r + dr, c + dc
        if 0 <= r2 < nrow and 0 <= c2 < ncol and valid[r2, c2]:
            tgt_r[r, c], tgt_c[r, c] = r2, c2
            indeg[r2, c2] += 1

    acc = np.where(valid, 1.0, 0.0)
    queue = [(int(r), int(c)) for r, c in zip(*np.where(valid & (indeg == 0)))]
    while queue:
        r, c = queue.pop()
        r2, c2 = tgt_r[r, c], tgt_c[r, c]
        if r2 < 0:
            continue
        acc[r2, c2] += acc[r, c]
        indeg[r2, c2] -= 1
        if indeg[r2, c2] == 0:
            queue.append((int(r2), int(c2)))

    acc[~valid] = np.nan
    return acc


def slope_degrees(dem: np.ndarray, cell_m: float) -> np.ndarray:
    """Horn (1981) 3x3 slope, the same estimator ArcGIS and GDAL use."""
    gy, gx = np.gradient(dem, cell_m, cell_m)
    return np.degrees(np.arctan(np.hypot(gx, gy)))


def topographic_wetness_index(acc: np.ndarray, slope_deg: np.ndarray,
                              cell_m: float) -> np.ndarray:
    """ln(a / tan(beta)); high where water concentrates on flat ground."""
    a = np.maximum(acc, 1.0) * cell_m
    tanb = np.maximum(np.tan(np.radians(slope_deg)), 0.001)
    return np.log(a / tanb)


def estimate_channel_width_m(acc_cells: np.ndarray, cell_m: float) -> np.ndarray:
    """Downstream hydraulic geometry: w = a * A^b with A the drainage area in km2.

    a=2.5, b=0.45 are mid-range values for humid tropical basins. Only used to bin
    a channel into the Art. 4 width classes (<10, 10-50, 50-200, 200-600, >600 m),
    so the class boundaries matter far more than the exact coefficients.
    """
    area_km2 = acc_cells * (cell_m ** 2) / 1e6
    return 2.5 * np.power(np.maximum(area_km2, 1e-6), 0.45)

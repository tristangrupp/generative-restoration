"""The landscape graph a restoration plan is sampled on.

Two graphs, built once per site and reused by every scenario:

  * the DESIGN graph - one node per plannable block inside the property. Its edges
    carry an anisotropic smoothing weight that biases contiguous design moves along
    the contour rather than across it, which is what makes sampled plans read as
    strips and swales instead of speckle.

  * the PATCH graph - one node per existing native-vegetation patch within the
    context window, INCLUDING patches on neighbouring properties. Edges are
    least-cost links between patches. Restoration is scored by how much it improves
    connectivity on this graph, so a plan is rewarded for finishing a corridor the
    neighbours already started.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage as ndi
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

# Design-block side, in grid cells. At the 10 m analysis grid this makes each block
# 10 m / 0.01 ha, so a 15 m hedgerow is a real object the sampler can place rather
# than something that rounds away. It also multiplies the block count by ~36 against
# the old 60 m blocks, which is why the energy's lattice operations are cropped to
# the property (see generative.SiteEnergy.win) instead of running over the whole
# context window.
BLOCK = 1


@dataclass
class DesignGraph:
    """Blocks inside the property that a plan may act on."""
    n: int
    rows: np.ndarray            # block row index
    cols: np.ndarray            # block col index
    cell_index: list            # per block, the flat cell indices it covers
    area_ha: np.ndarray
    edges: np.ndarray           # (m, 2) block indices
    edge_w: np.ndarray          # (m,) smoothing weight
    feat: dict                  # per-block feature arrays
    shape: tuple                # source grid shape
    block_id: np.ndarray        # grid-shaped map cell -> block index, -1 outside


def _block_reduce(arr: np.ndarray, block: int, how: str = "mean") -> np.ndarray:
    h, w = arr.shape
    hh, ww = h // block * block, w // block * block
    a = arr[:hh, :ww].reshape(hh // block, block, ww // block, block)
    if how == "mean":
        return a.mean(axis=(1, 3))
    if how == "max":
        return a.max(axis=(1, 3))
    if how == "any":
        return a.any(axis=(1, 3))
    if how == "first":
        return a[:, 0, :, 0]
    raise ValueError(how)


def build_design_graph(ctx: dict, masks: dict, block: int = BLOCK) -> DesignGraph:
    cell_m = float(ctx["cell_m"])
    shape = ctx["dem"].shape
    prop = ctx["property_mask"].astype(bool)

    # Aggregate every layer the energy needs onto the block lattice.
    b = {
        "prop": _block_reduce(prop.astype("float32"), block) > 0.5,
        "native": _block_reduce(ctx["native"].astype("float32"), block),
        "field": _block_reduce(ctx["field_mask"].astype("float32"), block),
        "agri": _block_reduce(ctx["agri"].astype("float32"), block),
        "slope": _block_reduce(ctx["slope_deg"], block),
        "twi": _block_reduce(ctx["twi"], block),
        "dist_stream": _block_reduce(ctx["dist_to_stream"], block),
        "dist_native": _block_reduce(ctx["dist_to_native"], block),
        "dem": _block_reduce(ctx["dem"], block),
        "app_obl": _block_reduce(masks["app_obligation"].astype("float32"), block),
        "app_def": _block_reduce(masks["app_deficit"].astype("float32"), block),
        "stream": _block_reduce(ctx["stream"].astype("float32"), block),
        "consolidated": _block_reduce(ctx["consolidated_2008"].astype("float32"), block),
    }

    inside = b["prop"]
    rows, cols = np.nonzero(inside)
    n = rows.size
    block_id = np.full(b["prop"].shape, -1, dtype="int32")
    block_id[rows, cols] = np.arange(n)

    feat = {k: v[rows, cols].astype("float32") for k, v in b.items() if k != "prop"}

    # Which mapped crop field each block belongs to, 0 for none. Kept as an integer
    # label rather than a fraction because it identifies a management unit.
    fid = ctx.get("field_id")
    if fid is None:
        feat["field_id"] = np.zeros(n, dtype="int32")
    else:
        feat["field_id"] = _block_reduce(fid.astype("float32"), block,
                                         "first")[rows, cols].astype("int32")
    area_ha = np.full(n, (block * cell_m) ** 2 / 1e4, dtype="float32")

    # Aspect of the block lattice; used to make smoothing anisotropic.
    gy, gx = np.gradient(b["dem"], block * cell_m, block * cell_m)
    feat["grad_x"], feat["grad_y"] = gx[rows, cols], gy[rows, cols]

    edges, weights = [], []
    nbrs = [(0, 1), (1, 0), (1, 1), (1, -1)]
    for dr, dc in nbrs:
        rr, cc = rows + dr, cols + dc
        ok = ((rr >= 0) & (rr < block_id.shape[0]) & (cc >= 0) & (cc < block_id.shape[1]))
        j = np.full(n, -1, dtype="int32")
        j[ok] = block_id[rr[ok], cc[ok]]
        ok &= j >= 0
        i = np.nonzero(ok)[0]
        if i.size == 0:
            continue

        # A link across the slope (parallel to the contour) is cheap to keep
        # together; a link running downhill is not. Restored ground therefore
        # prefers to spread along contours, which is also where it does most for
        # runoff interception.
        gxm = 0.5 * (feat["grad_x"][i] + feat["grad_x"][j[i]])
        gym = 0.5 * (feat["grad_y"][i] + feat["grad_y"][j[i]])
        gn = np.hypot(gxm, gym) + 1e-6
        dirn = np.array([dc, dr], dtype="float32")
        dirn = dirn / np.linalg.norm(dirn)
        # |cos| between the edge direction and the slope direction: 0 along contour.
        align = np.abs((gxm * dirn[0] + gym * dirn[1]) / gn)
        w = 1.0 + 1.5 * (1.0 - align)          # contour-parallel edges weigh ~2.5x
        w /= np.hypot(dr, dc)                   # diagonals count less
        edges.append(np.stack([i, j[i]], axis=1))
        weights.append(w.astype("float32"))

    cell_index = []  # kept lazy; filled on demand by rasterise()
    return DesignGraph(
        n=n, rows=rows, cols=cols, cell_index=cell_index, area_ha=area_ha,
        edges=np.concatenate(edges), edge_w=np.concatenate(weights),
        feat=feat, shape=shape, block_id=block_id,
    )


def rasterise(g: DesignGraph, values: np.ndarray, block: int = BLOCK,
              fill=0) -> np.ndarray:
    """Expand a per-block vector back onto the original 30 m grid."""
    small = np.full(g.block_id.shape, fill, dtype=values.dtype)
    small[g.rows, g.cols] = values
    out = np.kron(small, np.ones((block, block), dtype=values.dtype))
    h, w = g.shape
    padded = np.full((h, w), fill, dtype=values.dtype)
    padded[:out.shape[0], :out.shape[1]] = out[:h, :w]
    return padded


# --------------------------------------------------------------------------
# Patch graph - the "network sense" of the plan
# --------------------------------------------------------------------------

@dataclass
class PatchGraph:
    """Existing native patches in the whole context window, neighbours included."""
    labels: np.ndarray          # grid-shaped patch id, 0 = none
    area_ha: np.ndarray         # per patch (index 0 unused)
    total_area_ha: float
    cost: np.ndarray            # movement resistance surface, grid-shaped
    links: list = field(default_factory=list)   # (a, b, least_cost_distance)


def resistance_surface(ctx: dict) -> np.ndarray:
    """Cost of a hectare of ground to a dispersing forest organism.

    Native vegetation is free to cross; cropland is expensive; open water and very
    steep ground are intermediate. The absolute scale is arbitrary - only ratios
    matter for the least-cost links.
    """
    cost = np.full(ctx["dem"].shape, 10.0, dtype="float32")
    cost[ctx["agri"].astype(bool)] = 25.0
    cost[ctx["field_mask"].astype(bool)] = 30.0
    cost[ctx["native"].astype(bool)] = 1.0
    cost[ctx["stream"].astype(bool)] = 2.0      # riparian ground is the natural route
    cost[ctx["water"].astype(bool)] = 8.0
    return cost


def build_patch_graph(ctx: dict, min_patch_ha: float = 1.0) -> PatchGraph:
    cell_m = float(ctx["cell_m"])
    px_ha = (cell_m ** 2) / 1e4
    native = ctx["native"].astype(bool)

    lab, n = ndi.label(native, structure=np.ones((3, 3)))
    if n == 0:
        return PatchGraph(labels=lab, area_ha=np.zeros(1), total_area_ha=0.0,
                          cost=resistance_surface(ctx))
    sizes = np.bincount(lab.ravel(), minlength=n + 1).astype("float32") * px_ha
    drop = np.nonzero(sizes[1:] < min_patch_ha)[0] + 1
    if drop.size:
        lab[np.isin(lab, drop)] = 0
        sizes[drop] = 0.0

    return PatchGraph(labels=lab, area_ha=sizes,
                      total_area_ha=float(sizes[1:].sum()),
                      cost=resistance_surface(ctx))


def component_stats(binary: np.ndarray, px_ha: float) -> tuple[int, float, float]:
    """Component count, largest component (ha), and area-weighted mean size."""
    lab, n = ndi.label(binary, structure=np.ones((3, 3)))
    if n == 0:
        return 0, 0.0, 0.0
    sizes = np.bincount(lab.ravel(), minlength=n + 1)[1:].astype("float64") * px_ha
    return n, float(sizes.max()), float((sizes ** 2).sum() / max(sizes.sum(), 1e-9))


def equivalent_connected_area(binary: np.ndarray, px_ha: float) -> float:
    """sqrt(sum of squared component areas) - the ECA / IIC family shortcut.

    Equals the total area when everything is one patch, and collapses toward the
    largest patch as the habitat fragments, so a plan that links two 100 ha
    remnants scores far above one that adds 20 ha of isolated blocks.
    """
    lab, n = ndi.label(binary, structure=np.ones((3, 3)))
    if n == 0:
        return 0.0
    sizes = np.bincount(lab.ravel(), minlength=n + 1)[1:].astype("float64") * px_ha
    return float(np.sqrt((sizes ** 2).sum()))

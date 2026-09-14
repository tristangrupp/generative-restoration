"""Simulated-annealing sampler whose proposals are landscape design moves.

A pixel-flip sampler on this energy would spend its whole budget discovering that
restoration wants to be contiguous. These proposals start from that knowledge: each
one is a gesture a landscape architect would make - line the stream, thicken a
remnant, run a corridor between two woodlots, follow a contour, trim an awkward
corner - so the chain explores the space of plans rather than the space of pixels.

The corridor move is a shortest-path query on the resistance graph, which is where
the "graph network" in the brief does real work: the route a corridor takes is the
cheapest ecological path between two patches, and it is allowed to aim at patches
on the NEIGHBOURS' land, so plans knit into the surrounding network.
"""
from __future__ import annotations

import heapq

import numpy as np
from scipy import ndimage as ndi
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra

import generative as gen
import morphology


class MoveSet:
    """Precomputed structures the proposals need."""

    def __init__(self, se, rng: np.random.Generator, linearity: float = 0.5):
        self.se = se
        self.rng = rng
        self.linearity = float(np.clip(linearity, 0.0, 1.0))
        f = se.g.feat

        strips = (se.design or {}).get("strips", {})
        m = se.machine
        implement = m.get("sprayer_boom_m", m.get("planter_width_m", 18.0))
        self.strip_width_m = morphology.snap_width(
            implement * float(strips.get("target_width_passes", 2)),
            implement, m.get("min_corridor_width_m", 30.0))
        self.riparian_width_m = float(strips.get("riparian_band_width_m", 60.0))
        self.edge_width_m = float(strips.get("field_edge_band_width_m", 40.0))

        self.near_stream = np.nonzero(f["dist_stream"] <= 200.0)[0]
        self.app_blocks = np.nonzero(se.app_deficit)[0]
        self.wet = np.nonzero(f["twi"] > np.percentile(f["twi"], 75))[0]
        self.steep = np.nonzero(f["slope"] > np.percentile(f["slope"], 80))[0]
        self.near_veg = np.nonzero(f["dist_native"] <= 300.0)[0]
        self.all_blocks = np.arange(se.g.n)

        # Block adjacency as a sparse graph, weighted by ecological resistance, for
        # the corridor move.
        a, b = se.edges[:, 0], se.edges[:, 1]
        resist = (1.0
                  + 2.5 * se.croppable
                  + 1.5 * gen._norm(f["slope"])
                  - 0.8 * se.adj_score
                  - 0.6 * se.water_score)
        wgt = 0.5 * (resist[a] + resist[b])
        wgt = np.clip(wgt, 0.05, None)
        n = se.g.n
        self.graph = coo_matrix((np.concatenate([wgt, wgt]),
                                 (np.concatenate([a, b]), np.concatenate([b, a]))),
                                shape=(n, n)).tocsr()

        # Anchors for corridors: blocks that already touch native vegetation, and
        # blocks on the property edge that face a neighbour's remnant.
        self.anchors = np.nonzero(se.already_native | (f["dist_native"] <= 60.0))[0]
        if self.anchors.size < 2:
            self.anchors = self.near_veg if self.near_veg.size >= 2 else self.all_blocks

        self._trees = None
        self.lattice_of = np.full(se.block_shape, -1, dtype="int32")
        self.lattice_of[se.rows, se.cols] = np.arange(n)

        # Neighbour lists in compressed form, with a per-edge cost that makes patch
        # growth follow the ground. Cheap to enter: damp hollows, stream margins,
        # ground beside existing woodland. Dear: steep exposed cropland. Growing a
        # patch against this surface is what replaces the old stamped circles.
        grow_cost = (1.0
                     + 2.0 * gen._norm(f["slope"])
                     - 0.9 * se.water_score
                     - 0.7 * se.adj_score
                     + 0.8 * se.croppable)
        grow_cost = np.clip(grow_cost, 0.08, None).astype("float32")
        ew = 0.5 * (grow_cost[a] + grow_cost[b])
        both = np.concatenate([a, b])
        other = np.concatenate([b, a])
        cost_both = np.concatenate([ew, ew])
        order = np.argsort(both, kind="stable")
        self.adj_indices = other[order].astype("int32")
        self.adj_cost = cost_both[order].astype("float32")
        self.adj_indptr = np.zeros(n + 1, dtype="int64")
        np.cumsum(np.bincount(both, minlength=n), out=self.adj_indptr[1:])
        self._grow_mark = np.zeros(n, dtype="int64")
        self._grow_stamp = 0

        # Blocks of each mapped crop field, for the field-scale moves.
        self.field_slices = se.field_slices
        self.n_fields = len(self.field_slices)

        # Linear features the strip moves run along.
        self.stream_lat = np.zeros(se.block_shape, dtype=bool)
        self.stream_lat[se.rows, se.cols] = f["stream"] > 0.2
        field_lat = np.zeros(se.block_shape, dtype=bool)
        field_lat[se.rows, se.cols] = se.croppable
        self.edge_lat = morphology.field_edge_mask(field_lat)
        self.n_contours = len(se.lines) if se.lines is not None else 0

    # -- helpers -------------------------------------------------------
    def _rb(self, metres: float) -> int:
        """Metres to blocks. Move sizes are stated in metres so that changing the
        analysis resolution does not silently change what a move does - at 10 m a
        radius of '5 blocks' is 50 m, where on the old 60 m grid it was 300 m."""
        return max(1, int(round(metres / self.se.machine["block_m"])))

    def _disc(self, centre: int, radius_blocks: int) -> np.ndarray:
        """Grow a patch outward from a seed, following the ground rather than a circle.

        The earlier version stamped a Euclidean disc, which is why plans came out
        covered in obvious circles that ignored slope, drainage and existing
        vegetation. This grows instead: starting at the seed it repeatedly absorbs
        whichever neighbouring block is cheapest to reach, where cheapness comes from
        the terrain. Wet ground, ground near a stream and ground beside existing
        woodland are cheap, steep exposed cropland is dear.

        The result is a patch whose outline is shaped by the landscape - it runs down
        a damp hollow, wraps around a remnant, and stops where the ground changes -
        for the same cost as drawing a circle.
        """
        # Match the area the old disc would have covered, capped so one move never
        # tries to grow half the farm. The cap costs nothing in expressiveness
        # because the annealer composes large areas from repeated moves anyway.
        budget = min(int(np.pi * radius_blocks ** 2), 2500)
        return self._grow(centre, budget)

    def _grow(self, seed: int, budget: int) -> np.ndarray:
        """Cheapest-first region growing on the block graph."""
        if budget <= 1:
            return np.array([seed], dtype="int32")
        indptr, indices, w = self.adj_indptr, self.adj_indices, self.adj_cost
        visited = self._grow_mark
        stamp = self._grow_stamp = self._grow_stamp + 1

        out = np.empty(budget, dtype="int32")
        n_out = 0
        heap = [(0.0, int(seed))]
        visited[seed] = stamp
        while heap and n_out < budget:
            d, u = heapq.heappop(heap)
            out[n_out] = u
            n_out += 1
            for p in range(indptr[u], indptr[u + 1]):
                v = indices[p]
                if visited[v] != stamp:
                    visited[v] = stamp
                    heapq.heappush(heap, (d + w[p], int(v)))
        return out[:n_out]

    # -- proposals -----------------------------------------------------
    def propose(self, x: np.ndarray) -> np.ndarray | None:
        """Pick a design move, with the line/blob mix set by `linearity`.

        At linearity 0 the sampler only knows how to grow bodies outward from what
        is already there. At 1 it works almost entirely in strips along contours,
        stream margins and field edges. The tidy-up and erase moves are always
        available, because a plan needs to be able to take things back.
        """
        lin = self.linearity
        line_moves = ["contour_strip", "riparian_band", "field_edge_strip"]
        blob_moves = ["thicken", "corridor", "wet", "steep", "saf_patch"]
        always = ["riparian", "trim", "relabel", "smooth"]
        # Field-scale moves belong in both vocabularies. Retiring a whole field is a
        # blocky outcome and taking a margin is a linear one, and both follow lines
        # that already exist on the ground.
        if self.n_fields:
            line_moves = line_moves + ["field_margin"]
            blob_moves = blob_moves + ["field_retire"]

        if self.n_contours == 0:
            line_moves = [m for m in line_moves if m != "contour_strip"]

        names = line_moves + blob_moves + always
        # The smoothing move is a majority filter, so it eats exactly the thin
        # linear features the strip moves are trying to lay down. It has to fade out
        # as linearity rises or the two moves simply undo each other.
        smooth_p = 0.18 * (1.0 - 0.75 * lin)
        p = np.concatenate([
            np.full(len(line_moves), 0.55 * lin / len(line_moves)),
            np.full(len(blob_moves), 0.55 * (1.0 - lin) / len(blob_moves)),
            np.array([0.10, 0.12, 0.05, smooth_p]),
        ])
        p = p / p.sum()
        return getattr(self, f"_m_{self.rng.choice(names, p=p)}")(x)

    # -- line moves ----------------------------------------------------
    def _blocks_from_lattice(self, mask: np.ndarray) -> np.ndarray:
        idx = self.lattice_of[mask]
        return idx[idx >= 0]

    def _m_contour_strip(self, x):
        """Lay a strip of restoration along one of the site's drivable contours."""
        se = self.se
        if self.n_contours == 0:
            return None
        k = int(self.rng.integers(0, self.n_contours))
        line = se.lines.contours[k]

        # Use a run of the contour rather than all of it, so a plan can take part
        # of a slope without committing to the whole hillside.
        n = len(line)
        span = int(self.rng.integers(max(n // 4, 3), n + 1))
        start = int(self.rng.integers(0, max(n - span, 1)))
        piece = line[start:start + span]

        width = self.strip_width_m * float(self.rng.choice([0.5, 1.0, 1.0, 1.5]))
        mask = morphology.rasterise_strip(piece, se.block_shape, width,
                                          se.machine["block_m"])
        idx = self._blocks_from_lattice(mask)
        if idx.size == 0:
            return None
        y = x.copy()
        y[idx] = self.rng.choice([gen.PLANT, gen.REGEN, gen.SAF, gen.WINDBREAK],
                                 p=[0.35, 0.25, 0.25, 0.15])
        return y

    def _m_field_retire(self, x):
        """Take a whole mapped field out of production.

        The unit a farmer actually decides about. Retiring one field leaves every
        other field intact and every existing boundary where it was, which is why
        this scores far better than a patch of the same area cut across three fields.
        """
        if self.n_fields == 0:
            return None
        k = int(self.rng.integers(0, self.n_fields))
        idx = self.field_slices[k]
        if idx.size == 0:
            return None
        y = x.copy()
        y[idx] = self.rng.choice([gen.REGEN, gen.PLANT, gen.SAF], p=[0.45, 0.35, 0.20])
        return y

    def _m_field_margin(self, x):
        """Take a margin off the inside edge of one field, leaving the rest croppable.

        A headland strip is the cheapest land on a farm to give up, because the
        machinery already turns there and the loss comes off the least productive
        part of the field.
        """
        se = self.se
        if self.n_fields == 0:
            return None
        k = int(self.rng.integers(0, self.n_fields))
        idx = self.field_slices[k]
        if idx.size < 20:
            return None

        lat = np.zeros(se.block_shape, dtype=bool)
        lat[se.rows[idx], se.cols[idx]] = True
        width_m = float(self.rng.choice([20.0, 30.0, 40.0, 60.0]))
        k_er = max(1, int(round(width_m / se.machine["block_m"])))
        inner = ndi.binary_erosion(lat, structure=np.ones((2 * k_er + 1, 2 * k_er + 1)))
        margin = lat & ~inner
        sel = self._blocks_from_lattice(margin)
        if sel.size == 0:
            return None
        y = x.copy()
        y[sel] = self.rng.choice([gen.WINDBREAK, gen.SAF, gen.PLANT, gen.REGEN],
                                 p=[0.30, 0.30, 0.25, 0.15])
        return y

    def _m_riparian_band(self, x):
        """A band of fixed width along a reach of stream - the classic APP strip."""
        se = self.se
        if not self.stream_lat.any():
            return None
        rr, cc = np.nonzero(self.stream_lat)
        j = int(self.rng.integers(0, rr.size))
        r0, c0 = rr[j], cc[j]
        reach = self._rb(self.rng.integers(400, 1500))

        win = np.zeros(se.block_shape, dtype=bool)
        r1, r2 = max(0, r0 - reach), min(se.block_shape[0], r0 + reach + 1)
        c1, c2 = max(0, c0 - reach), min(se.block_shape[1], c0 + reach + 1)
        win[r1:r2, c1:c2] = True

        band = morphology.band_along_mask(
            self.stream_lat, self.riparian_width_m, se.machine["block_m"],
            window=(slice(r1, r2), slice(c1, c2))) & win
        idx = self._blocks_from_lattice(band)
        if idx.size == 0:
            return None
        y = x.copy()
        y[idx] = self.rng.choice([gen.PLANT, gen.REGEN], p=[0.6, 0.4])
        return y

    def _m_field_edge_strip(self, x):
        """A strip along the edge of a field - the cheapest metre to give up."""
        se = self.se
        if not self.edge_lat.any():
            return None
        rr, cc = np.nonzero(self.edge_lat)
        j = int(self.rng.integers(0, rr.size))
        r0, c0 = rr[j], cc[j]
        reach = self._rb(self.rng.integers(300, 1100))

        win = np.zeros(se.block_shape, dtype=bool)
        r1, r2 = max(0, r0 - reach), min(se.block_shape[0], r0 + reach + 1)
        c1, c2 = max(0, c0 - reach), min(se.block_shape[1], c0 + reach + 1)
        win[r1:r2, c1:c2] = True

        band = morphology.band_along_mask(
            self.edge_lat, self.edge_width_m, se.machine["block_m"],
            window=(slice(r1, r2), slice(c1, c2))) & win
        idx = self._blocks_from_lattice(band)
        if idx.size == 0:
            return None
        y = x.copy()
        y[idx] = self.rng.choice([gen.WINDBREAK, gen.SAF, gen.PLANT],
                                 p=[0.45, 0.35, 0.20])
        return y

    def _m_smooth(self, x):
        """Majority-filter a window: removes speckle at near-constant area.

        Contiguity is in the objective, but a proposal set made only of paint and
        erase strokes reaches a ragged optimum and anneals out of it very slowly.
        This move is the one that tidies, and it is why the plans read as fields
        rather than as static.
        """
        se = self.se
        seed = self.rng.choice(self.all_blocks)
        r = self._rb(self.rng.integers(180, 720))
        idx = self._disc(seed, r)
        if idx.size < 9:
            return None

        # Filter only the neighbourhood the move touches. On the 10 m grid the
        # lattice runs to millions of cells and a uniform filter over the lot, on a
        # move chosen ~15% of the time, dominated the whole sampler.
        sel_r, sel_c = se.rows[idx], se.cols[idx]
        k = int(self.rng.integers(1, 3))
        pad = k + 1
        r0, r1 = max(sel_r.min() - pad, 0), min(sel_r.max() + pad + 1, se.block_shape[0])
        c0, c1 = max(sel_c.min() - pad, 0), min(sel_c.max() + pad + 1, se.block_shape[1])

        rest = np.zeros((r1 - r0, c1 - c0), dtype="float32")
        keep = ((se.rows >= r0) & (se.rows < r1) & (se.cols >= c0) & (se.cols < c1))
        rest[se.rows[keep] - r0, se.cols[keep] - c0] = (x[keep] != gen.CROP)
        want_rest = ndi.uniform_filter(rest, size=2 * k + 1, mode="nearest") >= 0.5

        y = x.copy()
        target = want_rest[sel_r - r0, sel_c - c0]

        # Turn isolated restored blocks back to crop, and fill isolated crop holes
        # with whichever intervention dominates their neighbourhood.
        turn_off = idx[(x[idx] != gen.CROP) & ~target & ~se.app_deficit[idx]]
        turn_on = idx[(x[idx] == gen.CROP) & target]
        y[turn_off] = gen.CROP
        if turn_on.size:
            neigh = x[x != gen.CROP]
            fill = (np.bincount(neigh, minlength=gen.N_LABELS).argmax()
                    if neigh.size else gen.PLANT)
            y[turn_on] = fill
        return y if (y != x).any() else None

    def _m_riparian(self, x):
        """Line a reach of stream, or a piece of unmet APP, with native cover."""
        pool = self.app_blocks if self.app_blocks.size else self.near_stream
        if pool.size == 0:
            return None
        seed = self.rng.choice(pool)
        idx = self._disc(seed, self._rb(self.rng.integers(150, 600)))
        idx = idx[self.se.app_obl[idx] | (self.se.g.feat["dist_stream"][idx] < 120)]
        if idx.size == 0:
            return None
        y = x.copy()
        y[idx] = self.rng.choice([gen.REGEN, gen.PLANT], p=[0.45, 0.55])
        return y

    def _corridor_trees(self, k: int = 10):
        """Least-cost predecessor trees from a few anchors, computed once.

        A single-source Dijkstra over 330k nodes costs a few hundred milliseconds; at
        one per proposal it was the largest single cost in the sampler. The routes
        only depend on the resistance surface, which does not change during a run, so
        a handful of trees can be built once and reused - the corridor endpoints vary,
        the network they traverse does not.
        """
        if getattr(self, "_trees", None) is not None:
            return self._trees
        pool = self.anchors
        k = min(k, pool.size)
        sources = self.rng.choice(pool, size=k, replace=False)
        dist, pred = dijkstra(self.graph, indices=sources, return_predecessors=True)
        self._trees = (np.atleast_2d(dist), np.atleast_2d(pred), np.atleast_1d(sources))
        return self._trees

    def _m_corridor(self, x):
        """Run a corridor along the least-cost route between two vegetation anchors."""
        if self.anchors.size < 2:
            return None
        dist, pred, sources = self._corridor_trees()
        i = int(self.rng.integers(0, len(sources)))
        s = int(sources[i])
        t = int(self.rng.choice(self.anchors))
        if t == s or not np.isfinite(dist[i, t]):
            return None
        path = []
        node = t
        while node != s and node >= 0 and len(path) < 20000:
            path.append(node)
            node = pred[i, node]
        path.append(s)
        path = np.array(path, dtype="int32")
        # At 10 m a route holds thousands of nodes; painting a disc at every one is
        # wasted work when neighbouring discs overlap almost entirely.
        stride = max(1, len(path) // 400)
        path = path[::stride]

        width = self._rb(self.rng.integers(40, 160))   # half-width of the corridor
        idx = np.unique(np.concatenate([self._disc(p, width) for p in path]))
        y = x.copy()
        y[idx] = self.rng.choice([gen.REGEN, gen.PLANT], p=[0.5, 0.5])
        return y

    def _m_thicken(self, x):
        """Grow the buffer around an existing remnant or an existing restored blob."""
        veg = self.se.already_native | (x != gen.CROP)
        cand = np.nonzero(veg)[0]
        if cand.size == 0:
            return None
        seed = self.rng.choice(cand)
        idx = self._disc(seed, self._rb(self.rng.integers(120, 480)))
        y = x.copy()
        lab = self.rng.choice([gen.REGEN, gen.PLANT, gen.SAF], p=[0.4, 0.4, 0.2])
        y[idx] = lab
        return y

    def _m_wet(self, x):
        if self.wet.size == 0:
            return None
        seed = self.rng.choice(self.wet)
        idx = self._disc(seed, self._rb(self.rng.integers(120, 420)))
        idx = idx[self.se.g.feat["twi"][idx] > np.percentile(self.se.g.feat["twi"], 60)]
        if idx.size == 0:
            return None
        y = x.copy()
        y[idx] = gen.REGEN
        return y

    def _m_steep(self, x):
        if self.steep.size == 0:
            return None
        seed = self.rng.choice(self.steep)
        idx = self._disc(seed, self._rb(self.rng.integers(120, 360)))
        y = x.copy()
        y[idx] = gen.PLANT
        return y

    def _m_saf_patch(self, x):
        """Convert a block of restoration to agroforestry, or open new SAF next to fields."""
        cand = np.nonzero(self.se.croppable & ~self.se.app_obl)[0]
        if cand.size == 0:
            return None
        seed = self.rng.choice(cand)
        idx = self._disc(seed, self._rb(self.rng.integers(120, 360)))
        idx = idx[~self.se.app_obl[idx]]     # SAF cannot discharge an APP obligation
        if idx.size == 0:
            return None
        y = x.copy()
        y[idx] = gen.SAF
        return y

    def _m_trim(self, x):
        """Give a patch of restoration back to the crop - the shrink direction."""
        cand = np.nonzero((x != gen.CROP) & ~self.se.app_deficit)[0]
        if cand.size == 0:
            return None
        seed = self.rng.choice(cand)
        idx = self._disc(seed, self._rb(self.rng.integers(60, 360)))
        idx = idx[~self.se.app_deficit[idx]]
        if idx.size == 0:
            return None
        y = x.copy()
        y[idx] = gen.CROP
        return y

    def _m_relabel(self, x):
        """Swap the intervention type over one contiguous restored component."""
        rest = x != gen.CROP
        if not rest.any():
            return None
        lat = np.zeros(self.se.block_shape, dtype=bool)
        lat[self.se.rows[rest], self.se.cols[rest]] = True
        lab, n = ndi.label(lat, structure=np.ones((3, 3)))
        if n == 0:
            return None
        pick = int(self.rng.integers(1, n + 1))
        sel = lab[self.se.rows, self.se.cols] == pick
        y = x.copy()
        y[sel] = self.rng.choice([gen.REGEN, gen.PLANT, gen.SAF, gen.WINDBREAK])
        y[sel & self.se.app_deficit] = self.rng.choice([gen.REGEN, gen.PLANT])
        return y


def anneal(se, weights: gen.Weights, seed: int, n_iter: int = 2500,
           t0: float = 60.0, t1: float = 0.6, verbose: bool = False):
    """Sample one plan. Returns (labels, energy, term breakdown, trace)."""
    rng = np.random.default_rng(seed)
    moves = MoveSet(se, rng, linearity=weights.linearity)

    x = np.full(se.g.n, gen.CROP, dtype="int8")
    x[se.already_native] = gen.REGEN          # existing vegetation is kept
    e, terms = gen.energy(se, x, weights)

    best_x, best_e, best_terms = x.copy(), e, terms
    trace = []
    for it in range(n_iter):
        T = t0 * (t1 / t0) ** (it / max(n_iter - 1, 1))
        y = moves.propose(x)
        if y is None:
            continue
        y[se.already_native] = np.where(y[se.already_native] == gen.CROP,
                                        gen.REGEN, y[se.already_native])
        ey, ty = gen.energy(se, y, weights)
        if ey < e or rng.random() < np.exp(-(ey - e) / max(T, 1e-6)):
            x, e, terms = y, ey, ty
            if e < best_e:
                best_x, best_e, best_terms = x.copy(), e, terms
        if verbose and it % 250 == 0:
            trace.append((it, round(e, 1), round(terms["restored_ha"], 1)))

    best_x, best_e, best_terms = _close_app(se, best_x, weights, best_e, best_terms)
    return best_x, best_e, best_terms, trace


def _close_app(se, x, weights, e, terms):
    """Plant any APP cell the anneal left in crop.

    APP is not a term to trade against the others - Art. 4 puts those strips where it
    puts them, and a plan that leaves 2 of 432 ha bare is unlawful rather than
    slightly worse. The anneal gets within a hectare or two on hard sites, so the
    remainder is closed deterministically. Active planting, because a strip the
    sampler declined to touch is one it found no regeneration case for.
    """
    gap = se.app_deficit & (x == gen.CROP)
    if not gap.any():
        return x, e, terms
    y = x.copy()
    y[gap] = gen.PLANT
    ey, ty = gen.energy(se, y, weights)
    return y, ey, ty

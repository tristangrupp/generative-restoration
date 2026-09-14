"""Forest Code (Lei 12.651/2012) as computable constraints on a raster grid.

Every function here maps one article to one mask. Nothing is inferred silently:
where the geometry of the law needs a proxy (chapada rupture lines, vereda extent,
the 2008 consolidation cutoff), the proxy is named in the docstring and the result
is reported separately so a technician can check it.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi


def _dilate_m(mask: np.ndarray, radius_m: float, cell_m: float) -> np.ndarray:
    """Euclidean dilation by a metric distance."""
    if radius_m <= 0 or not mask.any():
        return np.zeros_like(mask, dtype=bool)
    dist = ndi.distance_transform_edt(~mask, sampling=cell_m)
    return dist <= radius_m


def buffer_class_m(width_m: float, table: list[dict]) -> float:
    """Art. 4 I - APP width for a channel of the given surface width."""
    for row in table:
        lim = row["width_lt_m"]
        if lim is None or width_m < lim:
            return float(row["buffer_m"])
    return float(table[-1]["buffer_m"])


def app_watercourses(stream, channel_width_m, cell_m, table) -> np.ndarray:
    """Art. 4 I - marginal strips, width stepped by the channel's own width."""
    out = np.zeros(stream.shape, dtype=bool)
    edges = [row["width_lt_m"] for row in table]
    lo = 0.0
    for lim in edges:
        hi = np.inf if lim is None else float(lim)
        band = stream & (channel_width_m >= lo) & (channel_width_m < hi)
        if band.any():
            out |= _dilate_m(band, buffer_class_m((lo + 1e-6), table), cell_m)
        lo = hi
    return out


def app_springs(spring, cell_m, radius_m=50.0) -> np.ndarray:
    """Art. 4 IV - 50 m radius around perennial springs and seeps."""
    return _dilate_m(spring, radius_m, cell_m)


def app_lakes(water, stream, cell_m, rural_gt_20ha=100.0, rural_le_20ha=50.0):
    """Art. 4 II - strips around natural lakes, stepped at 20 ha of surface.

    Lakes are the water bodies that are not part of the channel network. Artificial
    reservoirs are NOT separated out here (Art. 4 III sets their width by licence);
    the caller gets `is_lake` so those can be excluded manually.
    """
    lakes = water & ~stream
    lab, n = ndi.label(lakes)
    out = np.zeros(water.shape, dtype=bool)
    if n == 0:
        return out, lab
    px_ha = (cell_m ** 2) / 1e4
    sizes = ndi.sum_labels(np.ones_like(lab, dtype="float32"), lab, range(1, n + 1)) * px_ha
    for band, radius in ((sizes > 20.0, rural_gt_20ha), (sizes <= 20.0, rural_le_20ha)):
        ids = np.nonzero(band)[0] + 1
        if ids.size:
            out |= _dilate_m(np.isin(lab, ids), radius, cell_m)
    return out, lab


def app_steep_slope(slope_deg, threshold_deg=45.0) -> np.ndarray:
    """Art. 4 V - slopes above 45 deg (100% along the line of steepest descent)."""
    return slope_deg > threshold_deg


def app_hilltops(dem, slope_deg, cell_m, min_height_m=100.0, min_mean_slope_deg=25.0,
                 frac=2.0 / 3.0, search_radius_m=1500.0) -> np.ndarray:
    """Art. 4 IX - upper third of hills at least 100 m high with mean slope > 25 deg.

    PROXY: the article defines the base by the adjacent plain or the nearest saddle.
    Here the base is the minimum elevation inside a moving window of
    `search_radius_m`, which is the standard raster approximation. Verify against a
    hydrologically-derived saddle analysis before any filing.
    """
    r = max(1, int(round(search_radius_m / cell_m)))
    size = 2 * r + 1
    zmin = ndi.minimum_filter(dem, size=size, mode="nearest")
    zmax = ndi.maximum_filter(dem, size=size, mode="nearest")
    relief = zmax - zmin
    mean_slope = ndi.uniform_filter(slope_deg, size=size, mode="nearest")
    qualifies = (relief >= min_height_m) & (mean_slope > min_mean_slope_deg)
    return qualifies & (dem >= zmin + frac * relief)


def app_plateau_edges(slope_deg, cell_m, buffer_m=100.0, break_slope_deg=10.0,
                      flat_slope_deg=3.0, flat_radius_m=300.0) -> np.ndarray:
    """Art. 4 VIII - 100 m in from the rupture line of tabuleiros / chapadas.

    PROXY: the rupture line is taken as the boundary between terrain that is flat
    over a `flat_radius_m` neighbourhood and terrain steeper than
    `break_slope_deg`. On the Cerrado chapadas this tracks the scarp edge well; in
    dissected terrain it over-triggers and should be reviewed.
    """
    r = max(1, int(round(flat_radius_m / cell_m)))
    size = 2 * r + 1
    locally_flat = ndi.maximum_filter(slope_deg, size=size, mode="nearest") < flat_slope_deg
    scarp = slope_deg >= break_slope_deg
    rupture = scarp & ndi.binary_dilation(locally_flat, iterations=1)
    return _dilate_m(rupture, buffer_m, cell_m)


def app_veredas(mapbiomas, cell_m, wetland_class=11, buffer_m=50.0):
    """Art. 4 XI - 50 m from the permanently waterlogged ground of a vereda.

    PROXY: MapBiomas wetland (class 11) stands in for the boggy core. Outside the
    Cerrado this class is floodplain rather than vereda, so the caller should only
    apply this where the biome is Cerrado.
    """
    core = mapbiomas == wetland_class
    return _dilate_m(core, buffer_m, cell_m), core


def escadinha_width_m(mod_fiscal: float, table: list[dict],
                      channel_width_m: float | None = None) -> float:
    """Art. 61-A - required recomposition strip on land consolidated before 2008.

    The last row of the watercourse table is conditional on the channel's own width
    (half of it, clamped to 30-100 m), so `channel_width_m` is needed there.
    """
    for row in table:
        lim = row["mf_le"]
        if lim is None or mod_fiscal <= lim:
            val = row["recompose_m"]
            if val == "half_of_watercourse_width":
                w = 0.0 if channel_width_m is None else channel_width_m / 2.0
                return float(np.clip(w, row.get("min_m", 30), row.get("max_m", 100)))
            if row.get("condition") and channel_width_m is not None and channel_width_m > 10:
                continue  # the 20 m row only applies to channels up to 10 m wide
            return float(val)
    return float(table[-1].get("max_m", 100))


def riparian_obligation(stream, channel_width_m, consolidated, mod_fiscal, cell_m,
                        full_table, esc_table):
    """Combine Art. 4 I and Art. 61-A into the strip that must actually be replanted.

    Full Art. 4 width applies wherever the land was NOT in agrosilvopastoral use at
    the 2008 cutoff; the reduced escadinha strip applies where it was.
    """
    full = app_watercourses(stream, channel_width_m, cell_m, full_table)

    esc = np.zeros(stream.shape, dtype=bool)
    edges = [0.0, 10.0, 50.0, 200.0, 600.0, np.inf]
    for lo, hi in zip(edges[:-1], edges[1:]):
        band = stream & (channel_width_m >= lo) & (channel_width_m < hi)
        if not band.any():
            continue
        rep = float(np.median(channel_width_m[band]))
        esc |= _dilate_m(band, escadinha_width_m(mod_fiscal, esc_table, rep), cell_m)

    return np.where(consolidated, esc, full), full, esc


def reserva_legal_ledger(property_mask, native, app_obligation, rl_pct, cell_m,
                         mod_fiscal, native_2008=None):
    """Art. 12, 15, 66, 67 - Reserva Legal accounting for one property."""
    px_ha = (cell_m ** 2) / 1e4
    prop_ha = float(property_mask.sum()) * px_ha
    required_ha = rl_pct * prop_ha

    inside = property_mask
    existing_ha = float((native & inside).sum()) * px_ha
    # Art. 15: APP that is vegetated or under recomposition may be counted toward RL.
    app_native_ha = float((native & inside & app_obligation).sum()) * px_ha

    small = mod_fiscal <= 4.0
    if small and native_2008 is not None:
        # Art. 67: for <= 4 fiscal modules the RL is whatever stood on 2008-07-22.
        required_ha = float((native_2008 & inside).sum()) * px_ha
    deficit_ha = max(0.0, required_ha - existing_ha)

    return dict(
        property_ha=round(prop_ha, 1),
        rl_pct=rl_pct,
        rl_required_ha=round(required_ha, 1),
        rl_existing_native_ha=round(existing_ha, 1),
        rl_of_which_in_app_ha=round(app_native_ha, 1),
        rl_deficit_ha=round(deficit_ha, 1),
        art67_small_property=bool(small),
        art15_app_counted_toward_rl=True,
        recomposition_pace="at least 1/10 of the deficit every 2 years (Art. 66 par. 2)",
        max_exotic_intercrop_share=0.50,
    )

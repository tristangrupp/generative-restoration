"""Generative model over restoration plans.

The model is a conditional energy-based model (a Markov random field) on the design
graph. A plan is an assignment of one intervention label to every block inside the
property; its probability is p(x | site) proportional to exp(-E(x)), with

    E(x) = legal(x) + cost(x) + suitability(x) + form(x) + connectivity(x)
           + machinery(x)

Sampling is simulated annealing whose proposals are *design moves*, not pixel
flips: paint a riparian strip, drive a corridor between two remnants along the
least-cost route, thicken an existing block of regeneration, follow a contour.
That proposal set is what makes the samples read as landscape design rather than
as noise, and it is the reason a graph is used at all - two of the moves are
shortest-path queries on the patch graph.

Scenario diversity comes from sampling the weight vector, not from re-running the
same objective: four archetypes fix the emphasis, and seeds vary the realisation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage as ndi

# Intervention labels.
CROP = 0        # stays in production
REGEN = 1       # fenced off, natural regeneration (Art. 66 II)
PLANT = 2       # active planting of natives (Art. 66 I)
SAF = 3         # agroforestry / consortium, exotics allowed up to 50% (Art. 66 par.3)
WINDBREAK = 4   # narrow tree line, native species, on field edges and contours

N_LABELS = 5
RESTORED = (REGEN, PLANT, SAF, WINDBREAK)
COUNTS_AS_NATIVE = (REGEN, PLANT, WINDBREAK)   # SAF is capped globally instead

LABEL_NAMES = {CROP: "crop", REGEN: "natural_regeneration", PLANT: "active_planting",
               SAF: "agroforestry_saf", WINDBREAK: "windbreak"}

# Establishment cost, relative to fencing a hectare and letting it come back on its
# own (= 1.0). Roughly proportional to Brazilian restoration budgets: assisted
# natural regeneration is the cheap option, seedling planting at ~1,600 stems/ha is
# several times dearer, and a SAF costs more still to put in even though it later
# earns. Without this term every plan maxes out agroforestry against the Art. 66
# par. 3 cap, because land rent alone makes SAF look like free compliance.
ESTABLISHMENT = {CROP: 0.0, REGEN: 1.0, PLANT: 6.0, SAF: 8.0, WINDBREAK: 6.0}


@dataclass
class Weights:
    """Objective weights. One archetype = one of these."""
    name: str
    legal_app: float = 60.0        # pressure to close the APP deficit
    legal_rl: float = 30.0         # pressure to close the Reserva Legal deficit
    opportunity: float = 1.0       # value of the crop given up
    water: float = 1.0             # pull toward wet ground, swales, stream margins
    slope: float = 1.0             # pull toward erodible ground
    adjacency: float = 1.0         # pull toward existing vegetation
    form: float = 1.0             # contiguity / contour-following smoothing
    connectivity: float = 1.0      # gain in equivalent connected area
    machinery: float = 1.0         # workability of what is left in production
    overshoot: float = 0.15        # penalty for restoring beyond the obligation
    establishment: float = 0.10    # what it costs to put the vegetation there
    # Art. 66 par. 5 lets a Reserva Legal deficit be settled off the property - by
    # CRA, by leasing servitude, or by donating land in a conservation unit - so the
    # RL shortfall is not illegal, it is a purchase. APP has no such route under the
    # PRA, which is why legal_app stays a hard penalty and this does not apply to it.
    # A low price is a farm that would rather buy CRAs than retire cropland; a high
    # one is a farm that wants the vegetation on its own land.
    compensation: float = 2.0      # price per ha of discharging RL off-property
    # Preference for each intervention, as a DISCOUNT on its establishment cost:
    # effective cost = ESTABLISHMENT[label] / (1 + palette[label]).
    #
    # It has to be a discount rather than a bonus. Written as a per-hectare bonus -
    # which is how it was first written - preferring planting pays the plan 1.1/ha
    # for every hectare it plants, so the cheapest way to collect is to plant the
    # whole farm, and an already-compliant property ends up restoring fourteen times
    # its obligation. As a discount the palette can only shift WHICH technique is
    # used, never how much land is taken.
    palette: dict = field(default_factory=dict)
    # 0 = grow compact bodies off existing vegetation; 1 = lay strips along the
    # land's contours. Blends two things at once: how much the form term cares
    # about compactness versus about the ORIENTATION of the restored edges, and
    # how often the sampler reaches for a line move rather than a blob move.
    # Set per archetype in data/design.json.
    linearity: float = 0.5
    # How strongly the plan should respect existing field boundaries. A farm is
    # worked field by field, so a boundary that follows a line already on the ground
    # costs the operator nothing, while one cutting through the middle of a field
    # splits a management unit in two. Charges new edges drawn inside a field, and
    # charges leaving a field half-converted.
    field_respect: float = 1.0


ARCHETYPES = [
    # Cheapest route to compliance: regenerate what regenerates itself, buy the rest.
    Weights("compliance_minimum", legal_app=80, opportunity=2.5,
            water=0.4, slope=0.4, adjacency=0.6, form=1.2, connectivity=0.2,
            machinery=1.6, overshoot=1.5, compensation=0.9,
            establishment=0.30, palette={REGEN: 0.4}),
    # Water quality and erosion: plant the riparian strips so they close fast,
    # regenerate the wider catchment.
    Weights("water_first", legal_app=80, opportunity=1.0,
            water=3.0, slope=1.8, adjacency=0.8, form=1.4, connectivity=0.8,
            machinery=0.9, overshoot=0.35, compensation=3.0,
            establishment=0.10, palette={PLANT: 0.9, REGEN: 0.3, WINDBREAK: 0.5}),
    # Habitat network: corridors have to function on a schedule, so they are planted.
    Weights("corridor_network", legal_app=80, opportunity=1.0,
            water=1.0, slope=0.6, adjacency=2.0, form=1.6, connectivity=3.0,
            machinery=0.8, overshoot=0.30, compensation=3.0,
            establishment=0.10, palette={PLANT: 1.1, REGEN: 0.25}),
    # Keep the land earning: agroforestry to the Art. 66 par. 3 cap, windbreaks on
    # the field edges.
    Weights("productive_mosaic", legal_app=80, opportunity=0.6,
            water=0.9, slope=0.8, adjacency=1.0, form=1.0, connectivity=0.9,
            machinery=1.4, overshoot=0.25, compensation=1.8,
            establishment=0.08, palette={SAF: 1.0, WINDBREAK: 0.8, REGEN: 0.2}),
]


@dataclass
class SiteEnergy:
    """Everything the energy needs, precomputed once per site."""
    g: object                      # DesignGraph
    area_ha: np.ndarray
    app_deficit: np.ndarray        # bool per block - must end up vegetated
    app_obl: np.ndarray            # bool per block - inside an APP of any kind
    already_native: np.ndarray     # bool per block
    croppable: np.ndarray          # bool per block - currently a working field
    yield_value: np.ndarray        # relative opportunity cost per ha
    water_score: np.ndarray        # 0..1 pull toward wet / riparian ground
    slope_score: np.ndarray        # 0..1 pull toward erodible ground
    adj_score: np.ndarray          # 0..1 pull toward existing vegetation
    regen_difficulty: np.ndarray   # 0 beside a seed source, 1 far from one
    rl_deficit_ha: float
    px_ha: float
    edges: np.ndarray
    edge_w: np.ndarray
    block_shape: tuple
    rows: np.ndarray
    cols: np.ndarray
    native_ctx: np.ndarray         # block lattice: native anywhere in the window
    machine: dict
    # Shape terms are scored as changes from the do-nothing plan. Without this the
    # farm's existing fragmentation is charged to every plan, and the cheapest way
    # to stop paying for it is to restore the whole property - which is how the
    # first calibration degenerated.
    base_form_raw: float = 0.0
    base_aniso: float = 0.0
    base_mach: float = 0.0
    base_aggregation: float = 0.0
    plannable_ha: float = 0.0      # land not already carrying native vegetation
    lines: object = None           # morphology.LineLibrary, built once per site
    design: dict = field(default_factory=dict)
    # Union of every place a strip may legitimately sit: on a drivable contour, in a
    # riparian band, or along a field edge. At high linearity, restoration outside
    # this mask is charged - which is what turns the knob from a preference into a
    # constraint on the geometry.
    strip_mask: np.ndarray | None = None
    strip_capacity_ha: float = 0.0   # restorable area the strip mask can actually hold
    # Active window: the property's bounding box plus a margin, as slices into the
    # block lattice. Every labelling and morphology operation in the energy runs
    # inside this, not over the whole context window. At 10 m the context buffer is
    # ~90% of the cells and none of it can change, so scoring it every iteration was
    # pure waste - this is what keeps a 10 m run tractable.
    win: tuple = ()
    win_native: np.ndarray | None = None   # context vegetation cropped to the window
    outside_eca_sq: float = 0.0            # sum of squared patch areas beyond it
    # Labelling and morphology run on a decimated copy of the window. Patch topology
    # and machinery geometry do not need 10 m precision - they were computed at 30 m
    # for the whole earlier build - but the energy pays for that resolution on every
    # iteration. Decimating by 3 restores the old cost while the PLAN itself, and
    # everything written out, stays at 10 m.
    lat_step: int = 3
    dec_shape: tuple = ()
    dec_rows: np.ndarray | None = None
    dec_cols: np.ndarray | None = None
    dec_native: np.ndarray | None = None
    dec_px_ha: float = 0.0
    # Field identity per block, 0 where no mapped field, plus the block indices of
    # each field so per-field conversion fractions can be scored without a groupby
    # on every energy evaluation.
    field_id: np.ndarray | None = None
    field_slices: list = field(default_factory=list)
    field_area_ha: np.ndarray | None = None
    same_field_edge: np.ndarray | None = None   # edges with both ends in one field


def _norm(x: np.ndarray) -> np.ndarray:
    lo, hi = np.nanpercentile(x, [2, 98])
    if hi - lo < 1e-9:
        return np.zeros_like(x, dtype="float32")
    return np.clip((x - lo) / (hi - lo), 0, 1).astype("float32")


def prepare(g, ctx, masks, ledger, machine: dict, design: dict | None = None) -> SiteEnergy:
    f = g.feat
    px_ha = float(g.area_ha[0])

    already_native = f["native"] > 0.5
    croppable = (f["field"] > 0.4) & ~already_native

    # Opportunity cost proxy. A block that is an actual detected crop field is the
    # most valuable; pasture and mosaic uses are cheaper to retire; steep or wet
    # ground is worth less to keep farming.
    yield_value = np.where(f["field"] > 0.4, 1.0, 0.45).astype("float32")
    yield_value *= np.clip(1.15 - 0.035 * f["slope"], 0.35, 1.15)
    yield_value *= np.clip(1.10 - 0.03 * np.maximum(f["twi"] - 8.0, 0), 0.5, 1.10)

    # These are PREFERENCES between blocks, not reasons to restore more land, so
    # each is centred on its own mean. Without centring the fit term is a per-hectare
    # bounty and the optimum degenerates to restoring the entire property.
    def centred(v):
        return (v - float(np.mean(v))).astype("float32")

    water_score = centred(0.6 * _norm(f["twi"])
                          + 0.4 * (1.0 - _norm(np.log1p(f["dist_stream"]))))
    slope_score = centred(_norm(f["slope"]))
    adj_score = centred(1.0 - _norm(np.log1p(f["dist_native"])))

    # Native vegetation across the whole window, on the block lattice, so
    # connectivity can see the neighbours' remnants.
    from design_graph import _block_reduce, BLOCK
    native_ctx = _block_reduce(ctx["native"].astype("float32"), BLOCK) > 0.5

    se = SiteEnergy(
        g=g, area_ha=g.area_ha, app_deficit=masks["_app_deficit_blocks"],
        app_obl=f["app_obl"] > 0.4, already_native=already_native,
        croppable=croppable, yield_value=yield_value.astype("float32"),
        water_score=water_score, slope_score=slope_score, adj_score=adj_score,
        # Natural regeneration only works where seed and dispersers can reach: next
        # to a remnant it is nearly free, out in the middle of a 400 ha soy block it
        # fails and the money is wasted. Distance to existing native is the proxy.
        regen_difficulty=_norm(np.log1p(f["dist_native"])),
        rl_deficit_ha=float(ledger["rl_deficit_ha"]), px_ha=px_ha,
        edges=g.edges, edge_w=g.edge_w, block_shape=g.block_id.shape,
        rows=g.rows, cols=g.cols, native_ctx=native_ctx, machine=machine,
    )

    se.win, se.win_native, se.outside_eca_sq = _active_window(se, native_ctx)

    step = max(1, int(se.lat_step))
    r0, c0 = se.win[0].start, se.win[1].start
    se.dec_rows = (se.rows - r0) // step
    se.dec_cols = (se.cols - c0) // step
    se.dec_shape = (-(-se.win_native.shape[0] // step),
                    -(-se.win_native.shape[1] // step))
    se.dec_native = se.win_native[::step, ::step].copy()
    se.dec_px_ha = px_ha * (step ** 2)

    # Baseline = the farm as it stands: nothing restored, remnants kept.
    base = np.full(g.n, CROP, dtype="int8")
    base[already_native] = REGEN
    se.base_form_raw, _ = _raw_form(se, base != CROP)
    # A plan that does nothing creates no edges, so there is no meaningful baseline
    # orientation to compare against. The neutral reference is the mean edge weight:
    # what a plan would score if it ignored the terrain entirely.
    se.base_aniso = float(g.edge_w.mean())
    se.base_mach = machinery_penalty(se, base)
    se.base_aggregation = _aggregation(se, base)[1]
    se.plannable_ha = float((g.area_ha * ~already_native).sum())
    se.design = design or {}
    _prepare_fields(se, g)

    if se.design:
        se.lines = _build_lines(se, g, machine, se.design)
        se.strip_mask = _build_strip_mask(se, g, machine, se.design)
        se.strip_capacity_ha = float(
            (g.area_ha * (se.strip_mask & ~already_native)).sum())
    return se


def _build_strip_mask(se: SiteEnergy, g, machine: dict, design: dict) -> np.ndarray:
    """Per-block: may a strip sit here? Union of contours, stream and field bands."""
    import morphology

    strips = design.get("strips", {})
    block_m = machine["block_m"]
    implement = machine.get("sprayer_boom_m", machine.get("planter_width_m", 18.0))
    width = morphology.snap_width(
        implement * float(strips.get("target_width_passes", 2)),
        implement, machine.get("min_corridor_width_m", 30.0))

    lat = np.zeros(se.block_shape, dtype=bool)
    if se.lines is not None:
        for line in se.lines.contours:
            lat |= morphology.rasterise_strip(line, se.block_shape, width, block_m)

    stream_lat = np.zeros(se.block_shape, dtype=bool)
    stream_lat[se.rows, se.cols] = g.feat["stream"] > 0.2
    lat |= morphology.band_along_mask(
        stream_lat, float(strips.get("riparian_band_width_m", 60.0)), block_m)

    field_lat = np.zeros(se.block_shape, dtype=bool)
    field_lat[se.rows, se.cols] = se.croppable
    lat |= morphology.band_along_mask(
        morphology.field_edge_mask(field_lat),
        float(strips.get("field_edge_band_width_m", 40.0)), block_m)

    return lat[se.rows, se.cols]


def _build_lines(se: SiteEnergy, g, machine: dict, design: dict):
    """Trace the site's drivable contour lines once, for all scenarios to share."""
    import morphology

    strips = design.get("strips", {})
    drive = design.get("drivability", {})
    block_m = machine["block_m"]

    dem_lat = _to_lattice(se, g.feat["dem"], fill=np.nan)
    inside = np.zeros(se.block_shape, dtype=bool)
    inside[se.rows, se.cols] = True
    dem_lat = np.where(np.isfinite(dem_lat), dem_lat,
                       np.nanmedian(dem_lat[inside]) if inside.any() else 0.0)

    turn_r = machine.get("turning_radius_m", 12.0)
    if drive.get("use_machinery_turning_radius", True):
        turn_r *= float(drive.get("turning_radius_safety_factor", 1.5))

    return morphology.build_contour_library(
        dem_lat, inside, block_m,
        interval_m=float(strips.get("contour_interval_m", 12.0)),
        min_turn_radius_m=turn_r,
        min_strip_length_m=float(strips.get("min_strip_length_m", 400.0)),
    )


def _prepare_fields(se: SiteEnergy, g) -> None:
    """Index the mapped crop fields so per-field conversion can be scored cheaply."""
    fid = g.feat.get("field_id")
    if fid is None:
        se.field_id = np.zeros(g.n, dtype="int32")
        se.field_slices, se.same_field_edge = [], np.zeros(len(g.edges), dtype=bool)
        se.field_area_ha = np.zeros(1, dtype="float32")
        return

    fid = fid.astype("int32")
    se.field_id = fid
    n_fields = int(fid.max())

    order = np.argsort(fid, kind="stable")
    sorted_fid = fid[order]
    starts = np.searchsorted(sorted_fid, np.arange(1, n_fields + 2))
    se.field_slices = [order[starts[k]:starts[k + 1]] for k in range(n_fields)]
    se.field_area_ha = np.array(
        [float(se.area_ha[idx].sum()) for idx in se.field_slices], dtype="float32")

    a, b = g.edges[:, 0], g.edges[:, 1]
    # An edge inside one field. Cutting it draws a new line across a management
    # unit; cutting an edge between two fields follows a line that already exists.
    se.same_field_edge = (fid[a] == fid[b]) & (fid[a] > 0)


def _active_window(se: SiteEnergy, native_ctx: np.ndarray, margin_blocks: int = 60):
    """Crop the lattice work to the property plus a margin.

    Returns the window slices, the context vegetation inside it, and the squared-area
    contribution of the vegetation patches that fall entirely outside. Those outside
    patches never change, so their ECA contribution is a constant that can be added
    back rather than recomputed on every energy evaluation.
    """
    r0 = max(int(se.rows.min()) - margin_blocks, 0)
    r1 = min(int(se.rows.max()) + margin_blocks + 1, se.block_shape[0])
    c0 = max(int(se.cols.min()) - margin_blocks, 0)
    c1 = min(int(se.cols.max()) + margin_blocks + 1, se.block_shape[1])
    win = (slice(r0, r1), slice(c0, c1))

    lab, n = ndi.label(native_ctx, structure=np.ones((3, 3)))
    outside_sq = 0.0
    if n:
        inside_ids = set(np.unique(lab[win]).tolist()) - {0}
        sizes = np.bincount(lab.ravel(), minlength=n + 1).astype("float64") * se.px_ha
        for pid in range(1, n + 1):
            if pid not in inside_ids:
                outside_sq += sizes[pid] ** 2
    return win, native_ctx[win].copy(), outside_sq


def _raw_form(se: SiteEnergy, vegetated: np.ndarray,
              new: np.ndarray | None = None) -> tuple[float, float]:
    """(compactness, mean edge anisotropy) for the vegetated set.

    Two separate things that the single old term conflated:

    * compactness - boundary length over sqrt(area). Scale-free for a fixed shape,
      falls as scattered patches merge into one body. This is what makes blobs.
    * anisotropy  - the MEAN weight of the boundary edges, which depends only on
      which way the boundary runs, not how long it is. An edge running downhill is
      cheap to cut, so cutting it (leaving a boundary that runs along the contour)
      is rewarded. This is what makes contour strips, and because it is a mean it
      cannot be gamed by restoring more land.

    Anisotropy is measured ONLY over edges the plan actually creates. On a property
    that already carries 2,000 ha of native vegetation the existing boundary dwarfs
    a 200 ha plan, and a whole-boundary measure reports the same number whatever the
    plan does - which is exactly what it did before this was restricted.
    """
    a, b = se.edges[:, 0], se.edges[:, 1]
    cut = vegetated[a] != vegetated[b]
    n_veg = max(int(vegetated.sum()), 1)
    compact = float(cut.sum()) / np.sqrt(n_veg)

    if new is None:
        sel = cut
    else:
        sel = cut & (new[a] | new[b])
    n_sel = int(sel.sum())
    aniso = float((se.edge_w * sel).sum()) / n_sel if n_sel else float(se.edge_w.mean())
    return compact, aniso


def _aggregation(se: SiteEnergy, x: np.ndarray) -> tuple[float, float]:
    """(equivalent connected area, aggregation ratio).

    Patches inside the active window are relabelled each call; the ones entirely
    outside it are a constant, folded back in from `outside_eca_sq`.
    """
    veg = vegetated_lattice(se, x)
    lab, n = ndi.label(veg, structure=np.ones((3, 3)))
    if n == 0:
        return 0.0, 0.0
    sizes = np.bincount(lab.ravel(), minlength=n + 1)[1:].astype("float64") * se.dec_px_ha
    total_sq = (sizes ** 2).sum() + se.outside_eca_sq
    eca = float(np.sqrt(total_sq))
    total_area = float(sizes.sum()) + float(np.sqrt(se.outside_eca_sq))
    return eca, eca / max(total_area, 1e-9)


def _to_lattice(se: SiteEnergy, values, fill=0, window: bool = False):
    """Expand a per-block vector onto the lattice, optionally cropped to the window."""
    if window and se.win:
        out = np.full((se.win[0].stop - se.win[0].start,
                       se.win[1].stop - se.win[1].start), fill, dtype=values.dtype)
        out[se.rows - se.win[0].start, se.cols - se.win[1].start] = values
        return out
    out = np.full(se.block_shape, fill, dtype=values.dtype)
    out[se.rows, se.cols] = values
    return out


def vegetated_lattice(se: SiteEnergy, x: np.ndarray) -> np.ndarray:
    """Native cover after the plan, on the decimated active window."""
    veg = se.dec_native.copy()
    counts = np.isin(x, COUNTS_AS_NATIVE) | (x == SAF)
    veg[se.dec_rows[counts], se.dec_cols[counts]] = True
    return veg


def _dec_lattice(se: SiteEnergy, sel: np.ndarray) -> np.ndarray:
    """Boolean mask of the selected blocks, on the decimated window."""
    out = np.zeros(se.dec_shape, dtype=bool)
    out[se.dec_rows[sel], se.dec_cols[sel]] = True
    return out


def energy(se: SiteEnergy, x: np.ndarray, w: Weights) -> tuple[float, dict]:
    # `vegetated` is every block that carries native cover after the plan; `new`
    # is only the part the plan actually creates. The distinction matters: the RL
    # deficit in the ledger already has the existing vegetation subtracted from it,
    # so crediting that same vegetation again would let a plan discharge a deficit
    # by doing nothing.
    vegetated = x != CROP
    new = vegetated & ~se.already_native
    counts = np.isin(x, COUNTS_AS_NATIVE)
    restored_ha = float((se.area_ha * new).sum())

    # ---- legal ---------------------------------------------------------
    # APP: every block owing recomposition must end up as native vegetation.
    # SAF and windbreaks do not discharge an APP obligation.
    app_unmet = se.app_deficit & ~counts
    e_app = w.legal_app * float((se.area_ha * app_unmet).sum())

    # Reserva Legal: only NEW area OUTSIDE the APP obligation adds to the balance,
    # because APP already counted toward RL in the ledger under Art. 15.
    rl_credit_ha = float(
        (se.area_ha * (new & (counts | (x == SAF)) & ~se.app_obl)).sum())
    # Whatever the plan does not recompose on the property is settled off it under
    # Art. 66 par. 5, at a price. It is a cost, not a violation.
    compensation_ha = max(0.0, se.rl_deficit_ha - rl_credit_ha)
    e_rl = w.compensation * compensation_ha

    # Art. 66 par. 3: exotic-bearing systems may not exceed half the recomposed area.
    saf_ha = float((se.area_ha * (new & (x == SAF))).sum())
    saf_excess = max(0.0, saf_ha - 0.5 * max(restored_ha, 1e-9))
    e_saf_cap = 40.0 * saf_excess

    # ---- opportunity cost ----------------------------------------------
    # Charged on every hectare taken out of production, not only on the hectares
    # inside a detected crop field: pasture and mosaic ground has a rent too.
    # A windbreak takes the ground it stands on; what it returns is a yield benefit
    # to the crop beside it, which is worth far less than the strip itself. The
    # earlier 0.85 credit made "label the whole farm a windbreak" the cheapest way
    # to comply, which is how the term got calibrated honestly.
    lost = se.area_ha * se.yield_value
    keeps_producing = np.where(x == SAF, 0.40, np.where(x == WINDBREAK, 0.15, 0.0))
    e_cost = w.opportunity * float((lost * new * (1.0 - keeps_producing)).sum())

    # Windbreaks must also actually be linear. Any block in the interior of a
    # windbreak body more than two blocks across is a woodlot wearing the wrong
    # label, and is charged as one.
    e_wb = 0.0
    if (x == WINDBREAK).any():
        wb = _dec_lattice(se, x == WINDBREAK)
        interior = ndi.binary_erosion(wb, structure=np.ones((3, 3)))
        e_wb = 25.0 * float(interior.sum()) * se.dec_px_ha

    # ---- establishment ---------------------------------------------------
    pal = w.palette or {}
    estab = np.zeros(x.shape, dtype="float32")
    for lab, unit in ESTABLISHMENT.items():
        if unit:
            estab[x == lab] = unit / (1.0 + pal.get(lab, 0.0))
    # Regeneration far from a seed source needs enrichment planting anyway, so its
    # cost ramps from regeneration's toward planting's as the seed source recedes.
    #
    # Both ends must carry their OWN palette discount. Ramping toward planting's
    # undiscounted 6.0 and then dividing by regeneration's discount made hard-ground
    # regeneration dearer than planting the same hectare - under water_first, 4.6/ha
    # against planting's 3.16 - so the model planted 2,720 ha and regenerated 31 on
    # ground averaging 317 m from a remnant.
    is_regen = (x == REGEN)
    c_regen = ESTABLISHMENT[REGEN] / (1.0 + pal.get(REGEN, 0.0))
    c_plant = ESTABLISHMENT[PLANT] / (1.0 + pal.get(PLANT, 0.0))
    estab[is_regen] = (c_regen + (c_plant - c_regen)
                       * se.regen_difficulty[is_regen])
    e_estab = w.establishment * float((se.area_ha * estab * new).sum())

    # Restoring past the obligation is not free, and the penalty is relative to how
    # big the obligation was. A fixed per-hectare charge is meaningless across
    # sites: 300 ha of excess is a rounding error against a 2,700 ha obligation and
    # an absurdity against an 84 ha one. The quadratic term makes the same weight
    # behave correctly at both ends.
    obligation_ha = float((se.area_ha * se.app_deficit).sum()) + se.rl_deficit_ha
    excess = max(0.0, restored_ha - obligation_ha)
    # The reference for "how much is a lot" is the obligation where there is one,
    # and otherwise a fifth of the land that could physically be restored. Keying it
    # to the obligation alone divides by nearly zero on an already-compliant
    # property and collapses every archetype onto the same minimal answer.
    scale = max(obligation_ha, 0.2 * se.plannable_ha, 100.0)
    e_over = w.overshoot * excess * (1.0 + excess / scale)

    # ---- response to natural features -----------------------------------
    fit = (w.water * se.water_score + w.slope * se.slope_score
           + w.adjacency * se.adj_score)
    e_fit = -float((se.area_ha * fit * new).sum())

    # ---- form: contiguity, anisotropic along the contour ------------------
    # Raw boundary length is minimised by restoring the whole property, which is not
    # a design. What is charged is boundary per unit of sqrt(area) - compactness -
    # so the term shapes the restored set without arguing about its size. The edge
    # weights make a boundary running downhill dearer than one along the contour,
    # which is what bends the sampled forms into contour strips and swales.
    compact, aniso = _raw_form(se, vegetated, new)
    lin = float(np.clip(w.linearity, 0.0, 1.0))
    # The orientation coefficient has to be large because the quantity it multiplies
    # is a mean edge weight - it moves over a range of about 1.5 in total, while the
    # cost and establishment terms run to hundreds. At 120 the term contributed
    # single-digit energy and the knob did nothing; the contour-following that showed
    # up in the output was coming from the sampler's line moves alone.
    e_form = w.form * (
        5.0 * (1.0 - lin) * (compact - se.base_form_raw)
        + 2000.0 * lin * (aniso - se.base_aniso)
    )

    # Off-strip charge. Biasing the sampler toward line moves was not enough on its
    # own: the strips got absorbed into larger bodies by the other terms and the
    # output looked the same at every setting. Charging restoration that sits
    # outside the strip mask is what actually makes the geometry snap to lines. APP
    # blocks are exempt - the law says where those go, not the morphology setting.
    if se.strip_mask is not None and lin > 0.0:
        off_ha = float((se.area_ha * (new & ~se.strip_mask & ~se.app_deficit)).sum())
        # A plan cannot be charged for going off-strip when the obligation is larger
        # than every strip on the property put together. On the Amazon-biome sites
        # the 80% Reserva Legal demands more land than the strip mask holds, and
        # without this the morphology setting would quietly push the farm into
        # buying CRAs rather than restoring - a display preference overruling the
        # intent of the plan.
        chargeable = max(0.0, off_ha - max(0.0, obligation_ha - se.strip_capacity_ha))
        e_form += w.form * 6.0 * lin * chargeable

    # ---- connectivity on the patch graph ---------------------------------
    # ECA rises with area, so scoring it raw is another per-hectare bounty. What is
    # scored is the AGGREGATION RATIO, ECA divided by total vegetated area: 1.0 when
    # everything forms one patch, low when the same hectares are scattered. That
    # rewards a plan for where it puts the restoration, not for how much it puts.
    eca, aggregation = _aggregation(se, x)
    e_conn = -w.connectivity * (aggregation - se.base_aggregation) * 1200.0

    # ---- machinery -------------------------------------------------------
    # Only the workability the plan DESTROYS is charged. A plan does not earn
    # credit for making the machinery problem disappear by ending the farming.
    e_mach = w.machinery * max(0.0, machinery_penalty(se, x) - se.base_mach)

    # ---- respect for existing field boundaries ---------------------------
    # Two charges. The first is for every new edge drawn inside a field, because
    # that splits a management unit where following the field's own boundary would
    # not. The second is for leaving a field part-converted: f*(1-f) peaks at half
    # and vanishes at nought or one, so a plan is pushed toward taking a whole field
    # or taking a clean margin off it. APP blocks are exempt from both, because the
    # law puts those strips where it puts them regardless of the farm's layout.
    e_field = 0.0
    if w.field_respect and se.same_field_edge is not None and se.same_field_edge.any():
        free = new & ~se.app_deficit
        ea, eb = se.edges[:, 0], se.edges[:, 1]
        # Only edges the PLAN draws. Vegetation already standing inside a mapped
        # field creates internal edges too, and charging those would bill every plan
        # for the farm as it was found - the same mistake the shape terms made.
        cut_inside = ((vegetated[ea] != vegetated[eb]) & se.same_field_edge
                      & (free[ea] | free[eb]))
        e_field = w.field_respect * 0.35 * float(cut_inside.sum())

        # Converted fraction of every field at once. A loop over fields runs tens of
        # thousands of times per scenario and showed up in the profile.
        n_f = se.field_area_ha.size
        if n_f:
            counts = np.bincount(se.field_id, minlength=n_f + 1)[1:]
            conv = np.bincount(se.field_id, weights=free, minlength=n_f + 1)[1:]
            with np.errstate(invalid="ignore", divide="ignore"):
                frac = np.where(counts > 0, conv / np.maximum(counts, 1), 0.0)
            partial = (frac > 0.02) & (frac < 0.98)
            e_field += w.field_respect * 4.0 * float(
                (se.field_area_ha[partial] * frac[partial] * (1.0 - frac[partial])).sum())

    # ---- palette ---------------------------------------------------------
    # The palette is applied as an establishment discount above; nothing here may
    # scale with area, or it becomes a bounty for restoring more land.
    e_taste = 0.0

    total = (e_app + e_rl + e_saf_cap + e_cost + e_estab + e_over + e_fit + e_form
             + e_conn + e_mach + e_taste + e_wb + e_field)
    return total, dict(app=e_app, rl_compensation=e_rl, saf_cap=e_saf_cap,
                       cost=e_cost, establishment=e_estab,
                       overshoot=e_over, fit=e_fit, form=e_form,
                       conn=e_conn, machinery=e_mach, taste=e_taste,
                       windbreak_shape=e_wb, field_respect=e_field,
                       restored_ha=restored_ha, eca=eca,
                       aggregation=aggregation, rl_credit_ha=rl_credit_ha,
                       compensation_ha=compensation_ha, edge_anisotropy=aniso)


def machinery_penalty(se: SiteEnergy, x: np.ndarray) -> float:
    """What the plan costs the person who has to drive the machine.

    Three things are charged for: crop remnants too small to be worth entering,
    crop shapes with more edge than area (every metre of edge is a turn), and
    restored strips narrower than the plantable minimum.
    """
    m = se.machine
    crop_lat = _dec_lattice(se, x == CROP)
    rest_lat = _dec_lattice(se, x != CROP)

    pen = 0.0
    lab, n = ndi.label(crop_lat, structure=np.ones((3, 3)))
    if n:
        sizes = np.bincount(lab.ravel(), minlength=n + 1)[1:].astype("float64") * se.dec_px_ha
        pen += float(np.clip(m["min_workable_ha"] - sizes, 0, None).sum()) * 2.0

    # Perimeter-to-area of the cropped area: a proxy for headland and turning time.
    er = ndi.binary_erosion(crop_lat, structure=np.ones((3, 3)))
    perim_cells = float((crop_lat & ~er).sum())
    area_cells = float(crop_lat.sum())
    if area_cells > 0:
        pen += 20.0 * (perim_cells / np.sqrt(area_cells))

    # Restored strips must be plantable and maintainable: erode by half the minimum
    # corridor width and see what survives.
    block_m = m["block_m"] * se.lat_step
    k = max(1, int(round((m["min_corridor_width_m"] / 2.0) / block_m)))
    core = ndi.binary_erosion(rest_lat, structure=np.ones((2 * k + 1, 2 * k + 1)))
    thin = rest_lat & ~ndi.binary_dilation(core, structure=np.ones((2 * k + 1, 2 * k + 1)))
    pen += float(thin.sum()) * se.dec_px_ha * 1.5

    return pen

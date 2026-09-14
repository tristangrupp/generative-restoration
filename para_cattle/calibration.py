"""Pará cattle calibration of the generative restoration planner.

The core planner was calibrated on soy farms in Mato Grosso, where every mapped field
is a soy field worth the same to keep. Pará's restoration land is cattle pasture, and
what a paddock is worth to keep depends on how productive it still is. This module
changes four things and nothing else in the objective:

1. Opportunity cost comes from pasture biomass and degradation (MapBiomas Collection
   10 pasture products, summarised per field by Restoration Explorer · Pará), so a
   plan retires exhausted pasture before productive pasture.
2. Soy-suitable pasture - high vigor, flat, big enough to mechanise, and never cleared
   after July 2008 (the Amazon Soy Moratorium cutoff) - is priced at soy's higher
   value, so plans avoid retiring it and the explorer can show it as an
   intensification option.
3. Natural regeneration is harder on degraded or frequently burnt pasture, which has
   lost the seed bank and stumps that let cleared Amazon land regrow.
4. Machinery weights are 0.4x the soy values, because pasture is fenced and grazed,
   not driven every season. productive_mosaic discounts tree lines as much as
   agroforestry, because on a ranch those lines are silvopasture.

All four are costs or discounts, never rewards for restored area (the core's rule 1),
and regeneration's cost ramp keeps its own discount (rule 3).
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

PASTURE_MEDIAN_BIOMASS_T_HA = 25.0   # Pará pasture fields, MapBiomas C10 2024
SOY_VALUE = 1.6                       # relative to a median pasture paddock = 1.0
NON_FIELD_VALUE = 0.35                # in use but not a mapped pasture field
MACHINERY_SCALE = 0.4

SOY_MIN_HIGH_VIGOR_SHARE = 0.5
SOY_MAX_SLOPE_DEG = 5.0
SOY_MIN_AREA_HA = 10.0
SOY_MAX_CLEARED_SHARE = 0.05

CURRENT = None   # field attributes of the site being generated, set by run.py


def cattle_archetypes(gen) -> list:
    out = []
    for a in gen.ARCHETYPES:
        palette = dict(a.palette)
        if a.name == "productive_mosaic":
            palette[gen.WINDBREAK] = 1.0
        out.append(replace(a, machinery=round(a.machinery * MACHINERY_SCALE, 3), palette=palette))
    return out


def _col(attrs, name, default):
    if name not in attrs:
        return np.full(len(attrs), default, dtype="float32")
    return attrs[name].astype("float64").fillna(default).to_numpy(dtype="float32")


def soy_suitable_fields(attrs) -> np.ndarray:
    """Per field: could this pasture intensify into soy instead of being retired?"""
    area = _col(attrs, "area_ha", 0.0)
    return ((_col(attrs, "vigor_high_share", 0.0) >= SOY_MIN_HIGH_VIGOR_SHARE)
            & (_col(attrs, "slope_deg", 99.0) <= SOY_MAX_SLOPE_DEG)
            & (area >= SOY_MIN_AREA_HA)
            & (_col(attrs, "cleared_ha", 0.0) <= SOY_MAX_CLEARED_SHARE * np.maximum(area, 1e-6)))


def apply(se, attrs) -> None:
    """Overwrite the soy-calibrated opportunity cost and regeneration difficulty."""
    f = se.g.feat
    if attrs is None or len(attrs) == 0:
        return
    idx = np.clip(np.rint(np.asarray(f["field_id"], dtype="float64")).astype(int), 0, len(attrs))

    def per_block(values, default):
        return np.concatenate([[default], values]).astype("float32")[idx]

    in_field = (idx > 0) & (f["field"] > 0.4)
    biomass = per_block(_col(attrs, "biomass_t_ha", PASTURE_MEDIAN_BIOMASS_T_HA), PASTURE_MEDIAN_BIOMASS_T_HA)
    degradation = per_block(_col(attrs, "degradation", 0.0), 0.0)
    fire = per_block(_col(attrs, "fire_months_per_yr", 0.0), 0.0)
    soy = per_block(soy_suitable_fields(attrs).astype("float32"), 0.0) > 0.5
    soy &= in_field & (f["app_obl"] <= 0.4)

    productivity = np.clip(biomass / PASTURE_MEDIAN_BIOMASS_T_HA, 0.5, 1.5) * (1.0 - 0.5 * degradation)
    value = np.where(in_field, productivity, NON_FIELD_VALUE)
    value = np.where(soy, SOY_VALUE, value)
    value *= np.clip(1.15 - 0.035 * f["slope"], 0.35, 1.15)
    value *= np.clip(1.10 - 0.03 * np.maximum(f["twi"] - 8.0, 0), 0.5, 1.10)
    se.yield_value = value.astype("float32")

    extra = 0.3 * degradation + 0.3 * np.clip(fire / 0.3, 0, 1)
    se.regen_difficulty = np.clip(se.regen_difficulty + np.where(in_field, extra, 0.0), 0, 1).astype("float32")
    se.soy_suitable = soy

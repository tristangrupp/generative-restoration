"""Export Pará cattle plans for Restoration Explorer's generative restoration view.

Writes, into the target folder:
  index.json                 every site with its ledger and each plan's headline numbers
  <site>/context.geojson     property, existing native vegetation, APP to recompose,
                             streams, and pasture fields (vigor, soy-suitable), EPSG:4326
  <site>/<scenario>.geojson  the plan's intervention polygons, EPSG:4326

Technique codes match the explorer's Solutions view: 1 natural regeneration,
2 active planting, 3 agroforestry, 4 tree lines / silvopasture, 5 soy-suitable.
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
from rasterio.features import shapes
from rasterio.transform import Affine
from shapely.geometry import shape

import calibration as cal
from config import CONTEXT_DIR, METRIC_CRS, OUT, SITES_DIR, SITES_INDEX

TECH_CODE = {"natural_regeneration": 1, "active_planting": 2, "agroforestry_saf": 3, "windbreak": 4}
INTENTION_LABEL = {"compliance_minimum": "Minimum compliance", "water_first": "Water first",
                   "corridor_network": "Corridor network", "productive_mosaic": "Productive mosaic"}
SIMPLIFY_M = 6.0


def _vectorise(mask, transform, window, layer, min_ha=0.05):
    r0, r1, c0, c1 = window
    sub = mask[r0:r1, c0:c1].astype("uint8")
    t = transform * Affine.translation(c0, r0)
    geoms = [shape(g) for g, v in shapes(sub, mask=sub > 0, transform=t) if v == 1]
    if not geoms:
        return gpd.GeoDataFrame(columns=["layer", "geometry"], geometry="geometry", crs=METRIC_CRS)
    gdf = gpd.GeoDataFrame({"layer": layer}, geometry=geoms, crs=METRIC_CRS)
    gdf = gdf[gdf.area >= min_ha * 1e4]
    gdf["geometry"] = gdf.simplify(SIMPLIFY_M)
    return gdf


def _write(gdf, path):
    gdf = gdf.to_crs(4326)
    path.write_text(gdf.to_json(drop_id=True, to_wgs84=False), encoding="utf-8")


def main(out_dir: str | None, only=None) -> None:
    if not out_dir:
        raise SystemExit("export needs --out <folder>")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sites = json.loads(SITES_INDEX.read_text(encoding="utf-8"))
    index = []
    for rec in sites:
        sid = rec["site_id"]
        if only and sid not in only:
            continue
        summary_path = OUT / sid / "scenarios.json"
        if not summary_path.exists():
            print(f"{sid}: no plans yet, skipped")
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        ctx = np.load(CONTEXT_DIR / f"{sid}_context.npz")
        con = np.load(CONTEXT_DIR / f"{sid}_constraints.npz")
        transform = Affine.from_gdal(*ctx["transform"])
        prop_mask = ctx["property_mask"] > 0
        rows, cols = np.where(prop_mask)
        pad = 30
        window = (max(rows.min() - pad, 0), min(rows.max() + pad + 1, prop_mask.shape[0]),
                  max(cols.min() - pad, 0), min(cols.max() + pad + 1, prop_mask.shape[1]))

        prop = gpd.read_file(SITES_DIR / f"{sid}.gpkg", layer="property").to_crs(METRIC_CRS)
        fields = gpd.read_file(SITES_DIR / f"{sid}.gpkg", layer="fields").to_crs(METRIC_CRS)
        soy = cal.soy_suitable_fields(fields)
        fields_out = gpd.GeoDataFrame({
            "layer": "field",
            "fid": fields.get("fid"),
            "area_ha": fields.area / 1e4,
            "vigor_class": fields.get("vigor_class"),
            "vigor_low_share": fields.get("vigor_low_share"),
            "biomass_t_ha": fields.get("biomass_t_ha"),
            "degradation": fields.get("degradation"),
            "soy_suitable": soy.astype(int),
        }, geometry=fields.geometry.simplify(SIMPLIFY_M), crs=METRIC_CRS)

        layers = [
            gpd.GeoDataFrame({"layer": ["property"]}, geometry=[prop.geometry.union_all()], crs=METRIC_CRS),
            _vectorise(ctx["native"] > 0, transform, window, "native"),
            _vectorise(con["app_obligation"] > 0, transform, window, "app", min_ha=0.01),
            _vectorise(ctx["stream"] > 0, transform, window, "stream", min_ha=0.005),
            fields_out,
        ]
        context = gpd.GeoDataFrame(
            gpd.pd.concat(layers, ignore_index=True), geometry="geometry", crs=METRIC_CRS)
        site_dir = out / sid
        site_dir.mkdir(exist_ok=True)
        _write(context, site_dir / "context.geojson")

        soy_geom = fields_out[fields_out.soy_suitable == 1].geometry.union_all() if soy.any() else None
        scenarios = []
        for m in summary["scenarios"]:
            tag = m["scenario"]
            gpkg = OUT / sid / f"{tag}.gpkg"
            plan = gpd.read_file(gpkg, layer="plan") if gpkg.exists() else gpd.GeoDataFrame(
                columns=["intervention", "geometry"], geometry="geometry", crs=METRIC_CRS)
            plan = plan.to_crs(METRIC_CRS)
            plan["tech"] = plan.intervention.map(TECH_CODE).fillna(0).astype(int)
            plan["area_ha"] = plan.area / 1e4
            plan["geometry"] = plan.simplify(SIMPLIFY_M)
            _write(plan[["intervention", "tech", "area_ha", "geometry"]], site_dir / f"{tag}.geojson")
            soy_kept = 0.0
            if soy_geom is not None:
                restored = plan.geometry.union_all() if len(plan) else None
                kept = soy_geom.difference(restored) if restored is not None else soy_geom
                soy_kept = kept.area / 1e4
            by = m["area_by_intervention_ha"]
            scenarios.append({
                "key": tag, "archetype": m["archetype"], "label": INTENTION_LABEL.get(m["archetype"], m["archetype"]),
                "file": f"{sid}/{tag}.geojson", "seed": m.get("seed"),
                "restored_ha": m["restored_ha"], "pasture_retained_ha": m["cropland_retained_ha"],
                "pasture_converted_ha": m["cropland_converted_ha"],
                "rl_on_farm_ha": m["rl_recomposed_on_farm_ha"], "rl_offset_ha": m["rl_compensated_off_farm_ha"],
                "app_obligation_ha": m["app_obligation_ha"], "app_compliant": m["app_compliant"],
                "by_technique_ha": {"1": by.get("natural_regeneration", 0), "2": by.get("active_planting", 0),
                                    "3": by.get("agroforestry_saf", 0), "4": by.get("windbreak", 0)},
                "existing_native_ha": by.get("existing_native_retained", 0),
                "connectivity_eca_ha": m["connectivity_eca_ha"], "patches": m["vegetation_patches"],
                "largest_patch_ha": m["largest_patch_ha"], "saf_share": m["saf_share_of_restored"],
                "soy_suitable_kept_ha": round(soy_kept, 1),
            })

        led = summary["ledger"]
        w, s, e, n = prop.to_crs(4326).total_bounds
        index.append({
            "site_id": sid, "label": rec["label"], "municipio": rec["municipio"],
            "cod_imovel": rec["cod_imovel"], "car_id": rec.get("car_id"),
            "area_ha": led["property_ha"], "mod_fiscal": rec["mod_fiscal"], "bbox": [w, s, e, n],
            "machinery": summary["machinery"]["label"], "note": rec.get("note"),
            "pasture_fields": int(len(fields)), "soy_suitable_ha": round(float(fields_out.area_ha[soy].sum()), 1),
            "ledger": {k: led.get(k) for k in ["rl_pct", "rl_required_ha", "rl_existing_native_ha", "rl_deficit_ha",
                                               "app_obligation_ha", "app_deficit_ha", "app_relief_from_art61a_ha",
                                               "total_restoration_obligation_ha"]},
            "context": f"{sid}/context.geojson",
            "scenarios": scenarios,
        })
        print(f"{sid}: {len(scenarios)} plans exported")
    (out / "index.json").write_text(json.dumps({"sites": index}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"-> {out / 'index.json'}")

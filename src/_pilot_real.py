"""End-to-end pilot on real Mato Grosso data, without waiting for the CAR scan.

Uses the field cluster produced by the first pass of s01 as a provisional property
so that the DEM fetch, the derived hydrology, the MapBiomas reads, the Forest Code
solver, the sampler and the plotting are all exercised against real terrain. The
site id is prefixed PILOT_ so it never collides with the CAR-based sites.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
os.environ.setdefault("VSI_CACHE", "TRUE")
os.environ.setdefault("VSI_CACHE_SIZE", "268435456")

import geopandas as gpd  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from config import METRIC_CRS, SITES_DIR  # noqa: E402

SOURCE = SITES_DIR / "sorriso_amazonia.gpkg"
PILOT_ID = "PILOT_sorriso"


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"{SOURCE} not found")
    layers = [n for n, _ in gpd.list_layers(SOURCE).values]
    print("layers:", layers)
    if "property" in layers:
        print("CAR-based site already present; run the real pipeline instead")
        return

    fields = gpd.read_file(SOURCE, layer="fields").to_crs(METRIC_CRS)
    # Provisional holding: the fields plus the land they enclose.
    hull = fields.geometry.union_all().convex_hull
    prop = gpd.GeoDataFrame(
        dict(cod_imovel=["PILOT-PROVISIONAL"], municipio=["Sorriso (provisional)"],
             mod_fiscal=[8.0], num_area=[hull.area / 1e4], ind_tipo=["IRU"],
             ind_status=["PILOT"], des_condic=["PILOT"], cod_estado=["MT"],
             dat_atuali=["2026-07-27"]),
        geometry=[hull], crs=METRIC_CRS)

    out = SITES_DIR / f"{PILOT_ID}.gpkg"
    prop.to_file(out, layer="property", driver="GPKG")
    fields.to_file(out, layer="fields", driver="GPKG")

    rec = dict(
        site_id=PILOT_ID, label="Sorriso / Lucas do Rio Verde (PILOT)",
        biome="Amazonia", rl_pct=0.80,
        note="Provisional holding: convex hull of a Trazo field cluster. Fiscal "
             "modules assumed 8.0. Replaced by the CAR property once available.",
        cod_imovel="PILOT-PROVISIONAL", municipio="Sorriso (provisional)",
        mod_fiscal=8.0, declared_area_ha=round(hull.area / 1e4, 1),
        geom_area_ha=round(hull.area / 1e4, 1),
        cropped_ha=round(float(fields.geometry.area.sum() / 1e4), 1),
        cropped_share=round(float(fields.geometry.area.sum() / hull.area), 3),
        n_fields=int(len(fields)),
        bbox_wgs84=[round(v, 5) for v in
                    gpd.GeoSeries([hull], crs=METRIC_CRS).to_crs(4326).total_bounds],
        gpkg=str(out),
    )
    path = SITES_DIR / "sites_pilot.json"
    path.write_text(json.dumps([rec], indent=2), encoding="utf-8")
    print(f"wrote {path}")
    print(f"  {rec['geom_area_ha']} ha holding, {rec['n_fields']} fields, "
          f"cropped {rec['cropped_share']:.0%}")


if __name__ == "__main__":
    main()

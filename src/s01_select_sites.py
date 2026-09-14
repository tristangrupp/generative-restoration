"""Stage 1 - pick example planning sites in Mato Grosso.

A *site* is one real CAR rural property (imovel) plus the Trazo v2 crop fields that
fall inside it. Using CAR rather than a field-cluster proxy matters because the
Forest Code sets Reserva Legal as a share of the property and scales the Art. 61-A
consolidated-area recomposition strips by the property's size in fiscal modules -
and CAR carries `mod_fiscal` directly.

Writes one GeoPackage per site (layers: property, fields) into data/sites/, plus a
sites index. The CAR window extract is cached because each remote query is a full
3.7 GB scan.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd

sys.path.insert(0, str(Path(__file__).parent))
import car  # noqa: E402
from config import MT_FIELDS, MT_LAYER, METRIC_CRS, SITES_DIR  # noqa: E402

# Candidate search windows, chosen to span Mato Grosso's biome / Reserva Legal
# regimes. Each is ~0.5 deg (~55 km) wide.
WINDOWS = [
    dict(
        key="sorriso_amazonia",
        label="Sorriso / Lucas do Rio Verde",
        biome="Amazonia",
        rl_pct=0.80,
        bbox=(-55.95, -13.05, -55.45, -12.55),
        note="Soy frontier on the Amazon-biome side of MT. RL 80% -> large deficits.",
    ),
    dict(
        key="querencia_transicao",
        label="Querencia / Xingu headwaters",
        biome="Amazonia",
        rl_pct=0.80,
        bbox=(-52.60, -12.90, -52.10, -12.40),
        note="Xingu headwater catchments; dense small-stream network, riparian APP heavy.",
    ),
    dict(
        key="primavera_cerrado",
        label="Primavera do Leste / Campo Verde",
        biome="Cerrado",
        rl_pct=0.35,
        bbox=(-54.55, -15.60, -54.05, -15.10),
        note="Chapada Cerrado cropland. RL 35%, plateau-edge and vereda APPs matter.",
    ),
]

CAR_CACHE = SITES_DIR / "car_windows.gpkg"

PROP_MIN_HA = 500.0
PROP_MAX_HA = 6000.0
MIN_CROPPED_SHARE = 0.25   # must be a working farm, not a forest block
MAX_CROPPED_SHARE = 0.90   # must have room left to design in


def fetch_car() -> gpd.GeoDataFrame:
    if CAR_CACHE.exists():
        print(f"CAR: using cache {CAR_CACHE.name}")
        return gpd.read_file(CAR_CACHE, layer="car")

    print("CAR: one full remote scan for all windows. The parquet has no bbox")
    print("     covering column, so nothing prunes on geometry and the whole")
    print("     3.7 GB is read. Expect ~1-2 hours. DuckDB writes the GeoPackage")
    print("     directly, so the result is on disk the instant the scan ends.")
    car.extract_bboxes([w["bbox"] for w in WINDOWS], CAR_CACHE, states=["MT"])
    gdf = gpd.read_file(CAR_CACHE, layer="car")
    print(f"CAR: {len(gdf):,} properties written to {CAR_CACHE.name}")
    return gdf


def choose_property(props: gpd.GeoDataFrame, fields: gpd.GeoDataFrame) -> dict | None:
    """Pick the property with the most restoration design space.

    Design space = property area that is neither already cropped nor already
    native-vegetated, i.e. where a plan actually has choices to make.
    """
    props = props.copy()
    props["ha"] = props.geometry.area / 1e4
    props = props[(props.ha >= PROP_MIN_HA) & (props.ha <= PROP_MAX_HA)]
    props = props[props.ind_tipo == "IRU"]
    if props.empty:
        return None

    joined = gpd.overlay(fields[["geometry"]], props[["cod_imovel", "geometry"]],
                         how="intersection", keep_geom_type=True)
    if joined.empty:
        return None
    joined["ha"] = joined.geometry.area / 1e4
    cropped = joined.groupby("cod_imovel")["ha"].sum()

    props = props.set_index("cod_imovel")
    props["cropped_ha"] = cropped.reindex(props.index).fillna(0.0)
    props["cropped_share"] = props.cropped_ha / props.ha
    cand = props[(props.cropped_share >= MIN_CROPPED_SHARE)
                 & (props.cropped_share <= MAX_CROPPED_SHARE)]
    if cand.empty:
        return None

    # Largest absolute uncropped area inside a property that is genuinely farmed.
    cand = cand.assign(design_ha=cand.ha - cand.cropped_ha)
    best = cand.design_ha.idxmax()
    return dict(cod_imovel=best, row=props.loc[[best]].reset_index())


def main() -> None:
    car_all = fetch_car().to_crs(METRIC_CRS)

    index = []
    for win in WINDOWS:
        print(f"\n=== {win['label']} ===")
        fields = gpd.read_file(MT_FIELDS, layer=MT_LAYER, bbox=win["bbox"],
                               engine="pyogrio").to_crs(METRIC_CRS)
        fields = fields[fields.geometry.notna() & ~fields.geometry.is_empty]
        print(f"  fields in window: {len(fields):,}")

        win_box = gpd.GeoDataFrame(
            geometry=gpd.GeoSeries.from_wkt(
                [f"POLYGON(({win['bbox'][0]} {win['bbox'][1]}, {win['bbox'][2]} {win['bbox'][1]}, "
                 f"{win['bbox'][2]} {win['bbox'][3]}, {win['bbox'][0]} {win['bbox'][3]}, "
                 f"{win['bbox'][0]} {win['bbox'][1]}))"]),
            crs=4326).to_crs(METRIC_CRS)
        props = car_all[car_all.intersects(win_box.geometry.iloc[0])]
        print(f"  CAR properties in window: {len(props):,}")

        pick = choose_property(props, fields)
        if pick is None:
            print("  no property met the size / cropped-share criteria, skipping")
            continue

        prop = pick["row"].set_geometry("geometry").set_crs(METRIC_CRS, allow_override=True)
        geom = prop.geometry.iloc[0]
        site_fields = gpd.clip(fields, geom).reset_index(drop=True)
        site_fields = site_fields[site_fields.geometry.area > 1e4]  # drop <1 ha slivers

        sid = win["key"]
        out = SITES_DIR / f"{sid}.gpkg"
        prop.to_file(out, layer="property", driver="GPKG")
        site_fields.to_file(out, layer="fields", driver="GPKG")

        r = prop.iloc[0]
        bbox_wgs = list(gpd.GeoSeries([geom], crs=METRIC_CRS).to_crs(4326).total_bounds)
        rec = dict(
            site_id=sid, label=win["label"], biome=win["biome"], rl_pct=win["rl_pct"],
            note=win["note"],
            cod_imovel=str(r.cod_imovel), municipio=str(r.municipio),
            mod_fiscal=float(r.mod_fiscal), declared_area_ha=float(r.num_area),
            geom_area_ha=round(float(r.ha), 1),
            cropped_ha=round(float(r.cropped_ha), 1),
            cropped_share=round(float(r.cropped_share), 3),
            n_fields=int(len(site_fields)),
            bbox_wgs84=[round(v, 5) for v in bbox_wgs],
            gpkg=str(out),
        )
        index.append(rec)
        print(f"  -> {rec['cod_imovel']}  {rec['municipio']}  {rec['geom_area_ha']} ha  "
              f"{rec['mod_fiscal']:.1f} MF  {rec['n_fields']} fields  "
              f"cropped {rec['cropped_share']:.0%}")

    (SITES_DIR / "sites.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"\nWrote {len(index)} sites to {SITES_DIR / 'sites.json'}")


if __name__ == "__main__":
    main()

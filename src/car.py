"""Read CAR (Cadastro Ambiental Rural) property polygons from Source Cooperative.

Brazil_CAR_AREA_IMOVEL.parquet is ~3.7 GB and has no GeoParquet bbox covering
column, so a spatial predicate cannot prune row groups: every query is a full
remote scan. Fetch all windows you need in ONE call and cache the result locally.

Geometry is stored as DuckDB GEOMETRY declared in EPSG:4674 (SIRGAS 2000
geographic), which is the CAR/SICAR standard - close enough to EPSG:4326 to
overlay, but it is labelled correctly here rather than assumed away.

Useful columns:
    cod_imovel   CAR registration id
    mod_fiscal   size of the property in fiscal modules  <- drives Art. 61-A
    num_area     declared area (ha)
    ind_tipo     IRU (rural property) / AST (settlement) / PCT (traditional people)
    ind_status   registration status
    municipio, cod_estado
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd

CAR_URL = "https://data.source.coop/tristangruppwri/cadastral/Brazil_CAR_AREA_IMOVEL.parquet"
CAR_CRS = "EPSG:4674"

ATTRS = ["cod_imovel", "mod_fiscal", "num_area", "ind_status", "ind_tipo",
         "des_condic", "municipio", "cod_estado", "dat_atuali"]

_CONN = None


def connect():
    global _CONN
    if _CONN is None:
        import duckdb

        con = duckdb.connect()
        con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
        con.execute("SET enable_progress_bar = false;")
        _CONN = con
    return _CONN


def schema(url: str = CAR_URL) -> list[tuple[str, str]]:
    con = connect()
    return [(r[0], r[1]) for r in
            con.execute(f"SELECT name, type FROM parquet_schema('{url}')").fetchall()]


def extract_bboxes(bboxes: list[tuple[float, float, float, float]],
                   dest: Path, states: list[str] | None = None,
                   url: str = CAR_URL) -> Path:
    """Write every property intersecting any of the boxes to a local GeoPackage.

    DuckDB writes the file itself rather than handing rows back through pandas.
    That is not a style preference: the geometry column comes back as `bytearray`,
    which shapely.from_wkb rejects, and discovering that after a two-hour scan is
    expensive. COPY TO also means the result is on disk the moment the scan ends.

    `states` is worth passing. The parquet has no bbox covering column, so the
    spatial predicate cannot prune anything, but `cod_estado` is a plain string
    column with row-group statistics and may prune a great deal.
    """
    con = connect()
    sel = ", ".join(f'"{n}"' for n in ATTRS)
    spatial = " OR ".join(
        f"ST_Intersects(geometry, ST_MakeEnvelope({a}, {b}, {c}, {d}))"
        for a, b, c, d in bboxes
    )
    where = f"({spatial})"
    if states:
        lst = ", ".join(f"'{s}'" for s in states)
        where = f"cod_estado IN ({lst}) AND {where}"

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    con.execute(
        f"COPY (SELECT {sel}, geometry FROM read_parquet('{url}') WHERE {where}) "
        f"TO '{dest.as_posix()}' WITH (FORMAT GDAL, DRIVER 'GPKG', "
        f"LAYER_NAME 'car', SRS 'EPSG:4674')"
    )
    return dest


def read_bboxes(bboxes, url: str = CAR_URL, states=None) -> gpd.GeoDataFrame:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        p = extract_bboxes(bboxes, Path(td) / "car.gpkg", states=states, url=url)
        return gpd.read_file(p, layer="car")


def read_bbox(minx, miny, maxx, maxy, url: str = CAR_URL) -> gpd.GeoDataFrame:
    return read_bboxes([(minx, miny, maxx, maxy)], url=url)

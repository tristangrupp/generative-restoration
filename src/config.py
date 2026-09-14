"""Shared paths and constants for the generative restoration project."""
import os
from pathlib import Path

# Repo root. Defaults to the folder above this file, so a fresh clone runs without
# edits; GR_ROOT overrides it.
ROOT = Path(os.environ.get("GR_ROOT", Path(__file__).resolve().parents[1]))
DATA = ROOT / "data"
SRC = ROOT / "src"
OUT = ROOT / "outputs"

# Inputs too large to ship with the repo. Only stage 1 reads the field boundaries;
# stage 2 reads MapBiomas. Override either with an environment variable.
FIELDS_GPKG_DIR = Path(os.environ.get(
    "GR_FIELDS_DIR", r"F:\Trazo Fields v2\field boundaries"))
MAPBIOMAS_DIR = Path(os.environ.get(
    "GR_MAPBIOMAS_DIR", r"D:\WRI\Field Boundaries\Trazo Fields\extract data\mapbiomas"))

RULES_JSON = DATA / "forest_code" / "forest_code_rules.json"
SITES_DIR = DATA / "sites"
CONTEXT_DIR = DATA / "context"

for _d in (DATA, OUT, SITES_DIR, CONTEXT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Which site index the downstream stages read. Set SITES_INDEX=sites_pilot.json to
# run the pipeline over a provisional holding while the CAR extract is still going.
SITES_INDEX = SITES_DIR / os.environ.get("SITES_INDEX", "sites.json")

# Trazo v2 field boundaries: 1 polygon per detected crop field, EPSG:4326.
MT_FIELDS = FIELDS_GPKG_DIR / "Brazil_Mato_Grosso_2024.gpkg"
MT_LAYER = "Brazil_Mato_Grosso_2024"
MAPBIOMAS_BR = MAPBIOMAS_DIR / "brazil_coverage_2024.tif"

# Art. 61-A keys the reduced recomposition strips to occupation consolidated by
# 2008-07-22. MapBiomas 2008 is the closest annual layer to that cutoff. The GCS
# copy is a 256 px tiled LZW COG, so a site window costs a few hundred KB of range
# reads rather than the 750 MB the whole mosaic would.
MAPBIOMAS_2008_LOCAL = MAPBIOMAS_DIR / "brazil_coverage_2008.tif"
MAPBIOMAS_2008_URL = (
    "/vsicurl/https://storage.googleapis.com/mapbiomas-public/initiatives/"
    "brasil/collection_10/lulc/coverage/brazil_coverage_2008.tif"
)


def mapbiomas_2008() -> str:
    return (str(MAPBIOMAS_2008_LOCAL) if MAPBIOMAS_2008_LOCAL.exists()
            else MAPBIOMAS_2008_URL)


def site_gpkg(rec: dict) -> Path:
    """The site GeoPackage, wherever the repo is checked out.

    sites.json once stored absolute D:\\ paths, which broke on any other machine.
    A relative path resolves against ROOT, and a stale absolute path falls back to
    the copy in SITES_DIR.
    """
    p = Path(rec.get("gpkg", ""))
    if not p.is_absolute():
        p = ROOT / p
    return p if p.exists() else SITES_DIR / f"{rec['site_id']}.gpkg"


# Working projection for anything measured in metres. MT spans 21S/22S; SIRGAS 2000
# Brazil Polyconic keeps the whole state in one CRS with acceptable area error.
METRIC_CRS = "EPSG:5880"

# Analysis grid. 10 m so a plan can carry hedgerow-scale geometry: a 15 m tree line
# is a real object here, where on the old 30 m grid it was a rounding error.
CELL_M = 10

# Terrain grid. Copernicus GLO-30 is 30 m native and there is no free 10 m DEM for
# Brazil, so flow accumulation is derived at 30 m and the results resampled up.
# Running the priority-flood on an upsampled DEM would cost nine times as much and
# add no information that was not already interpolated.
TERRAIN_CELL_M = 30

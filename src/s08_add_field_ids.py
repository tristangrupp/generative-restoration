"""Add per-field identity to context stacks that were built before it existed.

Rasterising the field polygons costs seconds. Rebuilding a context stack costs the
DEM fetch and the flow routing, which is tens of minutes a site, so this patches the
existing files in place rather than re-running stage 2.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
from rasterio.features import rasterize
from rasterio.transform import Affine

sys.path.insert(0, str(Path(__file__).parent))
from config import CONTEXT_DIR, METRIC_CRS, SITES_INDEX, site_gpkg  # noqa: E402


def main() -> None:
    only = sys.argv[1:] or None
    for rec in json.loads(SITES_INDEX.read_text(encoding="utf-8")):
        sid = rec["site_id"]
        if only and sid not in only:
            continue
        path = CONTEXT_DIR / f"{sid}_context.npz"
        if not path.exists():
            print(f"skip {sid}: no context")
            continue

        data = dict(np.load(path, allow_pickle=False))
        if "field_id" in data:
            print(f"{sid}: already has field_id ({data['field_id'].max()} fields)")
            continue

        transform = Affine.from_gdal(*data["transform"])
        shape = data["field_mask"].shape
        site = gpd.read_file(site_gpkg(rec), layer="fields").to_crs(METRIC_CRS)

        data["field_id"] = rasterize(
            [(g, i + 1) for i, g in enumerate(site.geometry)],
            out_shape=shape, transform=transform, dtype="int32", fill=0,
        )
        np.savez_compressed(path, **data)
        n = int(data["field_id"].max())
        cov = float((data["field_id"] > 0).mean() * 100)
        print(f"{sid}: {n} fields rasterised, {cov:.1f}% of window -> {path.name}")


if __name__ == "__main__":
    main()

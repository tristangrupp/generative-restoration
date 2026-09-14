"""Stage 2 - assemble the biophysical context stack for each site.

Per site, on a common 30 m grid in EPSG:5880, buffered well beyond the farm so the
plan can respond to neighbouring vegetation:

    dem, slope_deg, twi, flowacc, stream, channel_width_m, spring,
    mapbiomas, native, water, agri, field_mask, dist_to_native, dist_to_stream

Copernicus DEM GLO-30 comes from the Planetary Computer STAC; MapBiomas comes from
the local Brazil coverage mosaic.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Keep /vsicurl from listing the whole bucket on every open, and give it a cache
# big enough that the overlapping tile reads are not re-fetched.
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
os.environ.setdefault("GDAL_CACHEMAX", "1024")
os.environ.setdefault("VSI_CACHE", "TRUE")
os.environ.setdefault("VSI_CACHE_SIZE", "268435456")

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import reproject
from scipy import ndimage as ndi

sys.path.insert(0, str(Path(__file__).parent))
import hydro  # noqa: E402
from config import (CELL_M, CONTEXT_DIR, MAPBIOMAS_BR, METRIC_CRS,  # noqa: E402
                    RULES_JSON, SITES_INDEX, TERRAIN_CELL_M, mapbiomas_2008,
                    site_gpkg)

# How far past the farm to model. The Forest Code is a property-scale instrument but
# connectivity is not, so the graph needs to see the neighbours' remnants. Trimmed
# from 6 km when the analysis grid went to 10 m: at that resolution the buffer, not
# the farm, dominates the cell count, and 3 km still reaches the adjacent holdings.
CONTEXT_BUFFER_M = 3000.0

# A cell is treated as channel once this much area drains through it. 25 ha is about
# the smallest headwater a 30 m DEM resolves honestly.
STREAM_MIN_AREA_HA = 25.0


def site_grid(site: gpd.GeoDataFrame, buffer_m: float, cell_m: float):
    minx, miny, maxx, maxy = site.total_bounds
    minx, miny = np.floor((minx - buffer_m) / cell_m) * cell_m, np.floor((miny - buffer_m) / cell_m) * cell_m
    maxx, maxy = np.ceil((maxx + buffer_m) / cell_m) * cell_m, np.ceil((maxy + buffer_m) / cell_m) * cell_m
    width = int(round((maxx - minx) / cell_m))
    height = int(round((maxy - miny) / cell_m))
    return from_origin(minx, maxy, cell_m, cell_m), width, height


def fetch_copernicus_dem(transform, width, height, crs) -> np.ndarray:
    """Mosaic Copernicus DEM GLO-30 tiles covering the grid, warped onto it."""
    import planetary_computer
    import pystac_client
    from rasterio.warp import transform_bounds

    left = transform.c
    top = transform.f
    right = left + width * transform.a
    bottom = top + height * transform.e
    bounds_wgs = transform_bounds(crs, "EPSG:4326", left, bottom, right, top)

    cat = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )
    items = list(cat.search(collections=["cop-dem-glo-30"], bbox=bounds_wgs).items())
    if not items:
        raise RuntimeError(f"no Copernicus DEM tiles for bbox {bounds_wgs}")

    dem = np.full((height, width), np.nan, dtype="float32")
    for item in items:
        href = item.assets["data"].href
        with rasterio.open(href) as src:
            tile = np.full((height, width), np.nan, dtype="float32")
            reproject(
                source=rasterio.band(src, 1),
                destination=tile,
                dst_transform=transform,
                dst_crs=crs,
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
            )
        np.copyto(dem, tile, where=np.isfinite(tile))
    print(f"    DEM from {len(items)} GLO-30 tile(s); "
          f"{np.isfinite(dem).mean() * 100:.1f}% covered")
    return dem


def read_mapbiomas(transform, width, height, crs, path=None) -> np.ndarray:
    with rasterio.open(path or MAPBIOMAS_BR) as src:
        out = np.zeros((height, width), dtype="uint8")
        reproject(
            source=rasterio.band(src, 1),
            destination=out,
            dst_transform=transform,
            dst_crs=crs,
            dst_nodata=0,
            resampling=Resampling.nearest,
        )
    return out


def upsample(arr, src_transform, src_shape, dst_transform, dst_shape, order=1):
    """Move a coarse-grid array onto the fine analysis grid.

    order=1 for continuous surfaces (elevation, slope, TWI), order=0 for anything
    categorical or mask-like, where interpolating would invent half-streams.
    """
    out = np.zeros(dst_shape, dtype="float32")
    reproject(
        source=np.ascontiguousarray(arr.astype("float32")),
        destination=out,
        src_transform=src_transform, src_crs=METRIC_CRS,
        dst_transform=dst_transform, dst_crs=METRIC_CRS,
        resampling=Resampling.bilinear if order else Resampling.nearest,
    )
    return out


def derive_hydrology(dem, cell_m):
    valid = np.isfinite(dem)
    filled = hydro.fill_depressions(dem.astype("float64"), ~valid)
    flowdir = hydro.d8_flowdir(filled, cell_m)
    acc = hydro.flow_accumulation(flowdir, valid)

    min_cells = STREAM_MIN_AREA_HA * 1e4 / (cell_m ** 2)
    stream = np.nan_to_num(acc, nan=0.0) >= min_cells

    width_m = hydro.estimate_channel_width_m(np.nan_to_num(acc, nan=0.0), cell_m)
    width_m[~stream] = 0.0

    # A spring (nascente) is a channel head: a stream cell with no stream cell
    # draining into it.
    nbr_stream_in = np.zeros(stream.shape, dtype=bool)
    nrow, ncol = stream.shape
    rr, cc = np.where(stream & (flowdir >= 0))
    for r, c in zip(rr, cc):
        dr, dc = hydro.D8[flowdir[r, c]]
        r2, c2 = r + dr, c + dc
        if 0 <= r2 < nrow and 0 <= c2 < ncol:
            nbr_stream_in[r2, c2] = True
    spring = stream & ~nbr_stream_in

    slope = hydro.slope_degrees(np.where(valid, dem, np.nan), cell_m)
    twi = hydro.topographic_wetness_index(np.nan_to_num(acc, nan=1.0), slope, cell_m)
    return dict(filled=filled.astype("float32"), flowacc=acc.astype("float32"),
                stream=stream, channel_width_m=width_m.astype("float32"),
                spring=spring, slope_deg=slope.astype("float32"),
                twi=twi.astype("float32"))


def main() -> None:
    rules = json.loads(RULES_JSON.read_text(encoding="utf-8"))
    roles = rules["mapbiomas_class_roles"]
    native_ids = np.array(roles["native_vegetation"], dtype="uint8")
    agri_ids = np.array(roles["agriculture"], dtype="uint8")

    sites = json.loads((SITES_INDEX).read_text(encoding="utf-8"))
    only = sys.argv[1:] or None
    for rec in sites:
        sid = rec["site_id"]
        if only and sid not in only:
            continue
        print(f"\n=== {sid} ===")
        site = gpd.read_file(site_gpkg(rec), layer="fields").to_crs(METRIC_CRS)
        prop = gpd.read_file(site_gpkg(rec), layer="property").to_crs(METRIC_CRS)

        # Two grids. Terrain and its derived hydrology are computed on the coarse
        # one, because the DEM is 30 m native and a priority-flood on an upsampled
        # copy costs nine times as much for interpolated detail. Everything is then
        # resampled onto the fine grid, where the vector layers - fields, property
        # boundary, and later the design strips - are rasterised at full accuracy.
        t_coarse, w_coarse, h_coarse = site_grid(prop, CONTEXT_BUFFER_M, TERRAIN_CELL_M)
        transform, width, height = site_grid(prop, CONTEXT_BUFFER_M, CELL_M)
        print(f"    terrain grid {h_coarse} x {w_coarse} @ {TERRAIN_CELL_M} m")
        print(f"    analysis grid {height} x {width} @ {CELL_M} m "
              f"({height * width / 1e6:.1f} M cells)")

        dem_c = fetch_copernicus_dem(t_coarse, w_coarse, h_coarse, METRIC_CRS)
        hyd_c = derive_hydrology(dem_c, TERRAIN_CELL_M)

        def up(a, order=1):
            return upsample(a, t_coarse, (h_coarse, w_coarse),
                            transform, (height, width), order)

        dem = up(dem_c)
        hyd = {
            "slope_deg": up(hyd_c["slope_deg"]),
            "twi": up(hyd_c["twi"]),
            "flowacc": up(hyd_c["flowacc"]),
            "channel_width_m": up(hyd_c["channel_width_m"], order=0),
            "stream": up(hyd_c["stream"].astype("uint8"), order=0).astype(bool),
            "spring": up(hyd_c["spring"].astype("uint8"), order=0).astype(bool),
        }

        mb = read_mapbiomas(transform, width, height, METRIC_CRS)
        native = np.isin(mb, native_ids)
        agri = np.isin(mb, agri_ids)

        # Art. 61-A cutoff. Absent MapBiomas 2008 the escadinha cannot be claimed,
        # so the solver would fall back to full Art. 4 APP - the conservative reading.
        try:
            mb08 = read_mapbiomas(transform, width, height, METRIC_CRS, mapbiomas_2008())
            consolidated_2008 = np.isin(mb08, agri_ids)
            print(f"    2008 baseline: {consolidated_2008.mean() * 100:.1f}% in agri use")
        except Exception as exc:
            mb08 = np.zeros_like(mb)
            consolidated_2008 = np.zeros(mb.shape, dtype=bool)
            print(f"    2008 baseline UNAVAILABLE ({exc}) -> full Art.4 APP assumed")
        water = mb == roles["water"][0]
        # MapBiomas water is the observed channel; the DEM gives the full network.
        stream = hyd["stream"] | water

        fields = rasterize(
            [(g, 1) for g in site.geometry], out_shape=(height, width),
            transform=transform, dtype="uint8", fill=0,
        ).astype(bool)
        # Individual field identity, not just "is cropped". A farm is managed field
        # by field: an owner retires a whole field or takes a margin off one, and
        # never a blob through the middle of three. Carrying the id lets the plan
        # align to lines that already exist on the ground.
        field_id = rasterize(
            [(g, i + 1) for i, g in enumerate(site.geometry)],
            out_shape=(height, width), transform=transform, dtype="int32", fill=0,
        )
        prop_mask = rasterize(
            [(g, 1) for g in prop.geometry], out_shape=(height, width),
            transform=transform, dtype="uint8", fill=0,
        ).astype(bool)

        dist_native = ndi.distance_transform_edt(~native, sampling=CELL_M).astype("float32")
        dist_stream = ndi.distance_transform_edt(~stream, sampling=CELL_M).astype("float32")

        layers = dict(
            dem=dem, slope_deg=hyd["slope_deg"], twi=hyd["twi"], flowacc=hyd["flowacc"],
            stream=stream.astype("uint8"), channel_width_m=hyd["channel_width_m"],
            spring=hyd["spring"].astype("uint8"), mapbiomas=mb,
            mapbiomas_2008=mb08, consolidated_2008=consolidated_2008.astype("uint8"),
            native=native.astype("uint8"), water=water.astype("uint8"),
            agri=agri.astype("uint8"), field_mask=fields.astype("uint8"),
            field_id=field_id,
            property_mask=prop_mask.astype("uint8"),
            dist_to_native=dist_native, dist_to_stream=dist_stream,
        )

        out = CONTEXT_DIR / f"{sid}_context.npz"
        np.savez_compressed(
            out, transform=np.array(transform.to_gdal()), crs=str(METRIC_CRS),
            cell_m=CELL_M, **layers,
        )
        print(f"    native {native.mean() * 100:.1f}%  agri {agri.mean() * 100:.1f}%  "
              f"stream cells {stream.sum():,}  springs {hyd['spring'].sum():,}")
        print(f"    -> {out.name}")


if __name__ == "__main__":
    main()

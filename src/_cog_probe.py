import os

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")

import rasterio

URL = ("/vsicurl/https://storage.googleapis.com/mapbiomas-public/initiatives/"
       "brasil/collection_10/lulc/coverage/brazil_coverage_2008.tif")

with rasterio.open(URL) as src:
    print("size      ", src.width, "x", src.height)
    print("crs       ", src.crs)
    print("dtype     ", src.dtypes)
    print("blocks    ", src.block_shapes)
    print("tiled     ", src.profile.get("tiled"))
    print("compress  ", src.profile.get("compress"))
    print("overviews ", src.overviews(1)[:6])
    # A small windowed read is the real test of whether range reads work.
    w = rasterio.windows.Window(20000, 20000, 512, 512)
    a = src.read(1, window=w)
    print("window read ok:", a.shape, "classes:", sorted(set(a.ravel().tolist()))[:12])

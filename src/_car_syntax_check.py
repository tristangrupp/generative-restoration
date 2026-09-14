"""Cheap pre-flight before committing to another full 3.7 GB scan.

Everything here is wrapped in a LIMIT so only the first row group is touched:
seconds, not hours. It validates the two things that would otherwise fail at the
END of a long scan - the cod_estado literal and the COPY TO GDAL syntax.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import car  # noqa: E402

con = car.connect()
url = car.CAR_URL

print("-- cod_estado values (first 2000 rows only) --")
print(con.execute(
    f"SELECT cod_estado, count(*) AS n FROM "
    f"(SELECT cod_estado FROM read_parquet('{url}') LIMIT 2000) GROUP BY 1 "
    f"ORDER BY n DESC"
).df().to_string(index=False))

sel = ", ".join(f'"{n}"' for n in car.ATTRS)
with tempfile.TemporaryDirectory() as td:
    dest = Path(td) / "probe.gpkg"
    con.execute(
        f"COPY (SELECT {sel}, geometry FROM read_parquet('{url}') LIMIT 50) "
        f"TO '{dest.as_posix()}' WITH (FORMAT GDAL, DRIVER 'GPKG', "
        f"LAYER_NAME 'car', SRS 'EPSG:4674')"
    )
    import geopandas as gpd

    g = gpd.read_file(dest, layer="car")
    print(f"\n-- COPY TO GPKG works: {len(g)} rows, crs={g.crs} --")
    print(g.drop(columns="geometry").head(3).to_string(index=False))

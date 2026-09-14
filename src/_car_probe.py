import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import car  # noqa: E402

print("--- schema ---")
for n, t in car.schema():
    print(f"  {n:28s} {t}")

print("\n--- Sorriso test window ---")
gdf = car.read_bbox(-55.95, -13.05, -55.45, -12.55)
print(f"  {len(gdf)} properties")
if len(gdf):
    print(gdf.drop(columns="geometry").head(5).to_string())

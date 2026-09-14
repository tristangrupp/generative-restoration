import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from config import CONTEXT_DIR, SITES_INDEX

for rec in json.loads(SITES_INDEX.read_text(encoding="utf-8")):
    sid = rec["site_id"]
    z = np.load(CONTEXT_DIR / f"{sid}_context.npz", allow_pickle=False)
    prop = z["property_mask"].astype(bool)
    dem = z["dem"][prop]
    slope = z["slope_deg"][prop]
    print(f"{sid:22s} relief {np.nanmax(dem) - np.nanmin(dem):6.1f} m   "
          f"slope mean {np.nanmean(slope):4.1f} deg  p90 {np.nanpercentile(slope, 90):4.1f}  "
          f"max {np.nanmax(slope):5.1f}")

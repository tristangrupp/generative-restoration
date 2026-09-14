"""MapBiomas colours and names, shared by every figure in the project.

MapBiomas ships an official palette. Reusing it means anyone who has looked at a
MapBiomas map before can read these figures without consulting a legend, and a
soybean field is the same pink here as it is there.
"""
from __future__ import annotations

import numpy as np
from matplotlib.colors import ListedColormap, to_rgb

# Only the classes that turn up in Mato Grosso. Anything else falls back to grey.
COLORS = {
    3: "#1f8d49",    4: "#7dc975",    5: "#04381d",    6: "#007785",
    9: "#7a5900",    11: "#519799",   12: "#d6bc74",   13: "#d89f5c",
    15: "#edde8e",   20: "#db7093",   21: "#ffefc3",   22: "#d4271e",
    23: "#ffa07a",   24: "#d4271e",   25: "#db4d4f",   29: "#ffaa5f",
    30: "#9c0027",   31: "#091077",   32: "#fc8114",   33: "#2532e4",
    35: "#9065d0",   39: "#f5b3c8",   40: "#c71585",   41: "#f54ca9",
    46: "#d68fe2",   47: "#9932cc",   48: "#e6ccff",   49: "#02d659",
    50: "#ad5100",   62: "#ff69b4",
}
NAMES = {
    3: "Forest", 4: "Savanna (cerrado)", 5: "Mangrove", 6: "Flooded forest",
    9: "Planted forestry", 11: "Wetland", 12: "Native grassland",
    13: "Other natural", 15: "Pasture", 20: "Sugar cane", 21: "Mixed farm uses",
    22: "Bare ground", 23: "Sand", 24: "Built up", 25: "Other bare",
    29: "Rocky outcrop", 30: "Mining", 31: "Aquaculture", 32: "Salt flat",
    33: "River or lake", 35: "Oil palm", 39: "Soybean", 40: "Rice",
    41: "Other annual crop", 46: "Coffee", 47: "Citrus",
    48: "Other perennial crop", 49: "Wooded sandbank", 50: "Sandbank grass",
    62: "Cotton",
}
FALLBACK = "#cccccc"

# Classes a farmer plants and harvests, used to label fields by what grows on them.
CROP_CLASSES = (39, 41, 62, 40, 20, 15, 21, 9, 46, 47, 48, 35)


def _lut(max_id: int = 63) -> np.ndarray:
    lut = np.array([to_rgb(FALLBACK)] * (max_id + 1), dtype="float32")
    for k, c in COLORS.items():
        if k <= max_id:
            lut[k] = to_rgb(c)
    return lut


def rgb(mb: np.ndarray) -> np.ndarray:
    """Land-cover classes as an RGB image."""
    lut = _lut(int(max(mb.max(), 62)))
    return lut[np.clip(mb, 0, len(lut) - 1)]


def washed(mb: np.ndarray, strength: float = 0.30) -> np.ndarray:
    """The same image faded toward white, for use as a backdrop.

    Full-strength land cover under a restoration plan competes with it for
    attention. Fading it lets the surroundings stay legible while the plan reads
    as the subject.
    """
    return 1.0 - (1.0 - rgb(mb)) * strength


def present(mb: np.ndarray, min_cells: int = 200) -> list[int]:
    """Classes worth putting in a legend, commonest first."""
    v, c = np.unique(mb, return_counts=True)
    keep = [(int(n), int(k)) for k, n in zip(v, c) if k in NAMES and n >= min_cells]
    keep.sort(reverse=True)
    return [k for _, k in keep]


def cmap_for(classes) -> ListedColormap:
    return ListedColormap([COLORS.get(k, FALLBACK) for k in classes])

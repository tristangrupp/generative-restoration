for m in ("contourpy", "matplotlib", "shapely", "scipy"):
    try:
        mod = __import__(m)
        print("OK  ", m, getattr(mod, "__version__", "?"))
    except Exception as e:
        print("MISS", m, e)

import contourpy
import numpy as np

z = np.add.outer(np.linspace(0, 10, 50), np.linspace(0, 3, 60))
gen = contourpy.contour_generator(z=z)
lines = gen.lines(5.0)
print("contour lines at level 5:", len(lines), "first shape", lines[0].shape)

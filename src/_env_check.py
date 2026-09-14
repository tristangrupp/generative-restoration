mods = ['matplotlib', 'skimage', 'sklearn', 'torch', 'torch_geometric', 'richdem',
        'pysheds', 'xarray', 'stackstac', 'contextily', 'rasterstats', 'fiona', 'numba']
for m in mods:
    try:
        mod = __import__(m)
        print('OK   ', m, getattr(mod, '__version__', '?'))
    except Exception:
        print('MISS ', m)

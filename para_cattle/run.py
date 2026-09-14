"""Run the generative restoration planner on Pará cattle properties.

Reuses the core pipeline in ../src unchanged. This runner points it at the module's
own data (sites, context, outputs, cattle machinery profile), then swaps in the
cattle archetypes and the pasture calibration from calibration.py.

    python para_cattle/run.py context     [site ...]   # core s02, tens of minutes a site
    python para_cattle/run.py constraints [site ...]   # core s03
    python para_cattle/run.py generate    [site ...] [--seeds 1]
    python para_cattle/run.py export --out <dir>       # plans -> Restoration Explorer files

Run it through the ESRI conda env `crop`, like the core pipeline.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
os.environ["GR_ROOT"] = str(HERE)          # data/, outputs/ resolve inside the module
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))

import config  # noqa: E402

# The law is shared with the core project; only the sites and calibration differ.
config.RULES_JSON = REPO / "data" / "forest_code" / "forest_code_rules.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["context", "constraints", "generate", "export"])
    ap.add_argument("sites", nargs="*")
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--out", default=None, help="export: target folder, e.g. web/public/para/plans")
    args = ap.parse_args()

    if args.stage == "export":
        import export_explorer
        export_explorer.main(args.out, args.sites or None)
        return

    sys.argv = [sys.argv[0]] + args.sites
    if args.stage == "context":
        import s02_build_context
        s02_build_context.main()
    elif args.stage == "constraints":
        import s03_constraints
        s03_constraints.main()
    else:
        import calibration as cal
        import generative as gen
        import s04_generate as s4

        gen.ARCHETYPES = cal.cattle_archetypes(gen)
        s4.N_SEEDS = args.seeds
        core_load, core_prepare = s4.load, gen.prepare

        def load(sid):
            import geopandas as gpd
            cal.CURRENT = gpd.read_file(config.SITES_DIR / f"{sid}.gpkg", layer="fields",
                                        ignore_geometry=True)
            return core_load(sid)

        def prepare(*a, **k):
            se = core_prepare(*a, **k)
            cal.apply(se, cal.CURRENT)
            return se

        s4.load = load
        gen.prepare = prepare
        s4.main()


if __name__ == "__main__":
    main()

# Generative restoration resources

A handoff for an agent picking up this project. Read this first, then
[METHODOLOGY.md](METHODOLOGY.md) for the method and the code for anything this leaves
out.

## What exists

The project lives at `D:\generative restoration` and on GitHub at
<https://github.com/tristangrupp/generative-restoration>, which is public. This file
exists twice: as `REPLICATION.md` in the repo and as
`C:\Users\grupp\Desktop\generative restoration resources.md`. Edit the repo copy and
recopy it, or the two will drift.

As of 14 September 2026 the work is complete for three Mato Grosso properties. All 36
scenarios (3 properties, 4 intentions, 3 seeds each) came from the current energy
function and sampler, and every one meets its APP requirement. Each property has
per-scenario panels, a 12-panel comparison plate, a current-state panel and an
animated walkthrough.

The model is an energy-based generative model: a Markov random field over a graph of
the property, sampled with simulated annealing. It learns nothing from data, and every term sits
hand-written in `src/generative.py`.

## Data sources

**CAR rural property boundaries.** GeoParquet on Source Cooperative, 3.7 GB, EPSG:4674:
`https://data.source.coop/tristangruppwri/cadastral/Brazil_CAR_AREA_IMOVEL.parquet`.
Stage 1 reads it remotely with DuckDB `httpfs`. Filter on `cod_estado = 'MT'` so DuckDB
skips row groups; an unfiltered bounding-box scan takes about two hours. The committed
`data/sites/car_windows.gpkg` holds the extract stage 1 selected from, so a rerun of
site selection does not need the remote scan.

**Crop field boundaries.** Trazo Fields v2, Mato Grosso 2024, at
`F:\Trazo Fields v2\field boundaries\Brazil_Mato_Grosso_2024.gpkg`, layer
`Brazil_Mato_Grosso_2024`. It holds 1.30 million polygons in EPSG:4326, and the
`mbmode24` attribute gives the modal MapBiomas class for 2024, which is how the model
knows what grows on each field. Only stage 1 reads this file. The three committed site
GeoPackages carry `property` and `fields` layers already, so stages 2 onward run
without it.

**Land cover.** MapBiomas Collection 10. Stage 2 reads 2024 from
`D:\WRI\Field Boundaries\Trazo Fields\extract data\mapbiomas\brazil_coverage_2024.tif`.
For 2008 it uses a local copy if one exists and otherwise reads the public
cloud-optimised GeoTIFF over `/vsicurl`, at a few hundred KB per site. The URL sits in
`src/config.py`.

**Elevation.** Copernicus DEM GLO-30 from the Microsoft Planetary Computer STAC API,
collection `cop-dem-glo-30`, signed anonymously. Stage 2 fetches it per site.

**Law.** `data/forest_code/` holds the compiled federal texts (Lei 12.651/2012, Lei
12.727/2012, Decreto 7.830/2012, Decreto 8.235/2014, Lei 14.285/2021) as HTML and plain
text, plus `forest_code_rules.json`, the machine-readable distillation the code uses.

## Environment

Run everything in the ESRI conda env `crop` at
`C:\Users\grupp\AppData\Local\ESRI\conda\envs\crop`, Python 3.11.15. Package versions
sit in `requirements.txt`.

Launch from PowerShell:

```
Set-Location 'D:\generative restoration'
conda run -p C:\Users\grupp\AppData\Local\ESRI\conda\envs\crop --no-capture-output python src\s04_generate.py primavera_cerrado
```

Four environment facts will cost time if you learn them the hard way.

1. The Git Bash tool has no `conda` on PATH and fails with `conda: command not found`,
   exit 127. Use the PowerShell tool.
2. Warnings such as `Cannot find gdalvrt.xsd (GDAL_DATA is not defined)` are harmless.
3. The `crop` env has a broken LAPACK as of August 2026: any call into `numpy.linalg`
   or `scipy.linalg` dies with `0xc06d007f` and exit 127, with no traceback. This
   pipeline uses only `scipy.ndimage` and `scipy.sparse.csgraph`, which is why it runs
   there. New code that needs linear algebra will crash the same way.
4. The machine has no ffmpeg, so the animations are GIFs.

Paths default to this machine. On another machine set `GR_ROOT`, `GR_FIELDS_DIR` and
`GR_MAPBIOMAS_DIR`, or leave `GR_ROOT` unset and it resolves to the folder above
`src/`. Site GeoPackage paths in `data/sites/sites.json` are relative to the repo root.

## The pipeline

```
s01_select_sites.py       CAR property + crop fields -> data/sites/
s02_build_context.py      elevation, hydrology, MapBiomas -> data/context/<site>_context.npz
s03_constraints.py        Forest Code masks and ledger -> <site>_constraints.npz, <site>_ledger.json
s04_generate.py           12 scenarios per site -> outputs/<site>/
s05_report.py             context plate and 12-panel comparison plate
s06_linearity_sweep.py    one scenario at four linearity settings
s07_panels.py             one figure and markdown description per scenario
s08_add_field_ids.py      patches field ids into context rasters built before they existed
s09_current_state.py      current-state panel per site
s10_animation.py          walkthrough GIF per site
```

Stages 2 to 4 and 7 to 10 take site ids to run a subset. Stage 5 ignores its arguments
and renders every site. Stage 8 only matters for context files older than the field-id
change; a fresh stage 2 run already writes `field_id`.

Stage 2 takes tens of minutes a site, most of it the elevation fetch and the flow
routing. Stage 4 takes 530 to 1,050 seconds a scenario, about 9 hours for all 36.

A stage 4 run that dies partway does not have to start over. `SCENARIOS` reruns only
the scenario numbers you list and reuses the metrics already on disk for the rest:

```
$env:SCENARIOS='11,12'; conda run -p ... python src\s04_generate.py primavera_cerrado
```

Clear it afterwards with `$env:SCENARIOS=''`. A background run on this machine once
died mid-site because another agent session stopped it, which is why the flag exists.

To rebuild from a fresh clone:

```
python src\s02_build_context.py
python src\s03_constraints.py
python src\s04_generate.py
python src\s05_report.py
python src\s07_panels.py
python src\s09_current_state.py
python src\s10_animation.py
```

## What the repo holds

Committed: all code, the law texts and rules, the three site GeoPackages, the CAR
window extract, the legal ledgers, the machinery and design configs, every figure and
animation, each scenario's metrics JSON, GeoPackage of plan polygons and markdown
description.

Not committed: the context rasters (27 to 46 MB each), the constraint rasters, and the
per-scenario label arrays. Rendering figures needs both the context rasters and the
label arrays, so a fresh clone has to run stages 2 to 4 before stages 5 to 10 work.

## Checking a run

Stage 3 should reproduce these ledgers exactly, and they sit in
`data/context/<site>_ledger.json`:

| Site | Property | APP deficit | Reserva Legal deficit | Total owed | Art. 61-A relief |
|---|---:|---:|---:|---:|---:|
| sorriso_amazonia | 5,187.0 ha | 431.9 ha | 2,323.5 ha | 2,755.4 ha | 21.4 ha |
| querencia_transicao | 4,988.4 ha | 576.1 ha | 2,517.1 ha | 3,093.2 ha | 26.4 ha |
| primavera_cerrado | 3,315.1 ha | 102.3 ha | 0.0 ha | 102.3 ha | 8.4 ha |

Poxoréu carries 2,148.3 ha of native vegetation against 1,160.3 ha required, which is
why its Reserva Legal deficit is zero.

Stage 4 results will not match the committed plans exactly. Those plans drew their
seeds from Python's `hash()`, which changes from one process to the next. The code now
uses `zlib.crc32`, so new runs repeat, and each committed plan records the seed it used
under `"seed"` in its metrics JSON. What should hold is the shape of the results:

- On the two Amazon properties, every intention except minimum compliance restores
  close to the full obligation on the farm: 2,730 to 2,750 ha at Sorriso and 2,850 to
  3,280 ha at Querência.
- Minimum compliance buys 1,120 to 1,660 ha of CRAs on those two properties and keeps
  far more cropland.
- At Poxoréu, minimum compliance, water first and productive mosaic restore 170 to
  260 ha, and network connectivity restores 395 to 502 ha.
- Every plan meets APP, because `sampler._close_app` plants any strip the annealer
  missed.

Check compliance across all sites with:

```
foreach ($s in 'sorriso_amazonia','querencia_transicao','primavera_cerrado') {
  $j = Get-Content "outputs\$s\scenarios.json" -Raw | ConvertFrom-Json
  $bad = $j.scenarios | Where-Object { -not $_.app_compliant -or -not $_.art66_exotic_cap_ok }
  "$s  non-compliant: $(if ($bad) { ($bad.scenario) -join ', ' } else { 'none' })"
}
```

Before changing any weight, run `src\_energy_diag.py <site_id>`. It prices four
reference plans side by side (do nothing, APP only plus CRAs, restore everything, and
sampled plans) term by term, and a term that dominates shows up as the biggest column.
It reads label arrays for scenarios 01, 07 and 10, so it needs a stage 4 run first.

## Where things live in the code

- `generative.py` holds the five labels, the establishment costs (`ESTABLISHMENT`),
  the `Weights` dataclass, the four intentions (`ARCHETYPES`), `prepare()`, which
  builds the per-site energy inputs, and `energy()`, which sums the terms.
- `sampler.py` holds the design moves (`MoveSet`), terrain-following patch growth
  (`_grow`), corridor routing by Dijkstra, the annealing loop (`anneal`), and the
  deterministic APP closure (`_close_app`).
- `design_graph.py` builds the 10 m node graph with contour-weighted edges, the patch
  graph of existing vegetation, and the connectivity measures.
- `morphology.py` traces contour lines with `contourpy`, cuts them where they curve
  tighter than the machinery can turn, and snaps strip widths to whole machine passes.
- `forest_code.py` maps one Forest Code article to one mask.
- `hydro.py` holds priority-flood depression filling, D8 flow routing, flow
  accumulation, slope, wetness index and channel width.
- `car.py` reads CAR remotely.
- `landcover.py` holds the MapBiomas palette and class names.
- `config.py` holds paths, grid constants and `site_gpkg()`.
- `data/design.json` sets `linearity` per intention; `data/machinery.json` holds three
  equipment profiles, with `large_soy_ctf` the default.

## Rules the model depends on

Each of these cost at least one full run to learn.

1. **A reward that grows with restored area is a bug.** Written as a payment per
   hectare, a reward for good placement is maximised by restoring the whole farm. Ten
   runs collapsed that way. Write such terms as a preference among places, as a change
   from doing nothing, or as a cost.
2. **Preferences between techniques are discounts on establishment cost.** A
   per-hectare bonus for a preferred technique pays the plan to use more land.
3. **When one technique's cost ramps toward another's, each end keeps its own
   discount.** Regeneration far from a seed source ramps toward the cost of planting.
   Dividing the whole ramp by regeneration's discount made hard-ground regeneration
   dearer than planting the same hectare, and the model planted 2,720 ha while
   regenerating 31. After the fix, the same site and weights gave 320 ha planted and
   2,308 regenerated.
4. **APP is not a quantity to trade.** Close any gap after annealing. Raising the APP
   weight instead distorts every other trade-off on the farm.
5. **The overshoot penalty scales with the obligation**, with a floor of 100 ha or 20%
   of plannable area. A flat per-hectare charge means nothing across a 102 ha and a
   2,755 ha obligation.
6. **The grid must be several times finer than the narrowest legal buffer.** At 30 m
   the model understated APP by 11 to 22%.
7. **The off-strip charge is capped by the capacity of the strips.** On the Amazon
   properties the obligation exceeds every strip on the farm combined, and an uncapped
   charge pushes the plan into buying CRAs to satisfy a display setting.
8. **The field-boundary term charges only edges the plan draws**, and exempts APP.
   Charging existing vegetation inside fields billed the do-nothing plan 7,409; charging
   APP strips billed the APP-only plan 1,627.

## Traps already hit

- DuckDB returns geometry as `bytearray`, and `shapely.from_wkb` rejects it with
  `TypeError: Expected bytes or string, got bytearray`. That failure landed after a
  two-hour scan. `car.py` now has DuckDB write the GeoPackage directly with
  `COPY ... (FORMAT GDAL, DRIVER 'GPKG')`.
- `a * (b | c) & ~d` fails with `TypeError: ufunc 'bitwise_and' not supported`.
  Python evaluates `*` before `&`, so a float array meets `& ~d`. Parenthesise the
  boolean part.
- Matplotlib 3.10 removed `FigureCanvasAgg.tostring_rgb`. Use `buffer_rgba`.
- Python's `hash()` of a string changes between processes. Never seed from it.
- `contour_alignment` sat at 0.81 to 0.83 whatever the linearity, because it measured
  the whole vegetated boundary, most of it pre-existing forest. It now measures only
  edges the plan creates.
- An early patch move stamped Euclidean discs, which left visible circles on the maps.
  Patches now grow cheapest-first over a terrain cost.
- GIF frames must all share one canvas size. `s10_animation.py` fixes the header and
  caption bands and sets a 6.4 in minimum width, because Querência's narrow parcel
  once produced a 330 px frame.
- Blending a dark frame into a light one leaves both captions legible at once. The
  animation cuts through a single flat frame where the page colour changes.

## Open problems, most important first

1. **The technique mix swung too far toward regeneration.** After the cost-ramp fix,
   Querência's network connectivity plans plant 0 ha and its water-first plans plant 0
   to 1 ha; Sorriso's water-first plans plant 1 to 2 ha. Both intentions promise
   planting. Their planting discounts (0.9 and 1.1) cannot overcome a six-to-one cost
   ratio wherever regeneration is easy. Candidate fixes: raise the planting discount
   for those two intentions, reward planting specifically inside riparian strips, or
   charge regeneration for the years a corridor takes to close. Each fix means a
   9-hour rerun, and the project owner has not chosen one yet.
2. **Poxoréu's network connectivity plans restore 395 to 502 ha against 102 ha owed.**
   The plans are lawful, but at four to five times the obligation it is worth checking
   the connectivity term against rule 1.
3. **The vereda approximation supplies 151.6 ha of Poxoréu's mapped APP**, the largest
   contribution from any approximated article on the three sites. A technician should
   review it.
4. **Legal simplifications.** The Reserva Legal share comes from the biome window, not
   an official biome map. Pre-2008 farming comes from MapBiomas, not the CAR
   declaration. Fiscal-module size comes from CAR. The Article 15 credit of APP toward
   Reserva Legal is assumed granted.
5. **Costs are ratios, not reais.**
6. **`s04_generate.py` cannot take explicit seeds**, so replaying a committed plan
   means editing the seed line.
7. **No learned component yet.** The sampler's accepted plans could train a graph VAE
   or a discrete diffusion model over the same node set.

## Working with the project owner

- Write in plain prose. Use "because". Avoid "it's not X, it's Y" constructions and
  anything that reads like marketing copy. Explain a technical term the first time it
  appears. The owner's reference style guide is
  <https://raw.githubusercontent.com/dbreunig/scaffold-docs-skill/refs/heads/main/references/prose-style.md>,
  and Vale lints markdown on this machine.
- The owner often works over Chrome Remote Desktop and cannot scroll the terminal.
  Put long answers in a file and link it.
- Tie every design choice to a real driver: the law, the terrain, or the farm's
  equipment.
- Figure titles stay plain: "The farm currently", "Key layers for a productive
  mosaic".
- Say how long a rerun will take before starting one.

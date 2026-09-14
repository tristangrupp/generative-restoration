# Pará cattle module

This module runs the generative restoration planner on cattle ranches in Pará. It
uses the same Forest Code, energy function, and sampler as the Mato Grosso work in
`../src`, and changes only what cattle pasture changes. The Mato Grosso code and
results stay as they were.

## Why a separate calibration

The core planner took its calibration from soy farms, where every mapped field is a soy
field worth the same to keep in production. On a Pará ranch every mapped field is pasture, and a
paddock's worth depends on how much grass it still grows. A plan tuned for soy retires
good and exhausted pasture at the same price, which misses the cheapest restoration on
the ranch.

`calibration.py` makes four changes, each a cost or a discount:

1. **Pasture value from productivity.** The cost of retiring a field is its 2024 pasture
   biomass relative to the Pará median (25 t/ha), discounted by its degradation score.
   Both come from the MapBiomas Collection 10 pasture products, summarised per field by
   Restoration Explorer · Pará.
2. **Soy-suitable pasture.** A field with at least half its area in high vigor, a mean
   slope of 5° or less, at least 10 ha, and no clearing after July 2008 costs 1.6 times
   a median paddock to retire, soy's higher value. July 2008 is the Amazon Soy
   Moratorium cutoff: traders refuse soy from land cleared after it. Plans avoid
   retiring these fields, and the explorer shows them as an intensification option.
3. **Harder regeneration on worn-out pasture.** Degradation and fire frequency each add
   up to 0.3 to regeneration difficulty, because exhausted, burnt pasture has lost the
   seed bank and stumps that let cleared Amazon land regrow.
4. **Ranch machinery.** Machinery weights are 0.4 times the soy values, and the default
   equipment profile is `para_cattle_ranch`, because ranchers fence and graze pasture
   rather than drive it every season. In productive mosaic, tree lines get the same discount as
   agroforestry, because on a ranch they are silvopasture.

None of these pays a plan for restoring more land, which keeps the core's first rule.
Regeneration's cost ramp keeps its own discount at each end, which keeps the third.

## Where the sites come from

Restoration Explorer · Pará scores every pasture field in the state and computes a
Forest Code ledger for every CAR property. Its `pipeline/para/s06_planner_sites.py`
picks one cattle property per frontier region: a registered, uncancelled rural
property of 500 to 6,000 ha, 25–90 % pasture, owing restoration on the farm, with the
most low-vigor pasture. It writes each one in this planner's site format, with every
explorer field attribute on the `fields` layer.

| Site | Municipality | Area | Fiscal modules |
|---|---|---:|---:|
| `para_paragominas` | Paragominas | 4,267 ha | 77.3 |
| `para_sao_felix_xingu` | Bannach | 2,426 ha | 32.3 |
| `para_novo_progresso` | Altamira | 2,348 ha | 31.3 |

## Running

Use the ESRI conda env `crop`, as for the core pipeline. The runner sets `GR_ROOT` to
this folder, so sites, context rasters, and outputs stay inside it.

```
python para_cattle/run.py context                # core stage 2, tens of minutes a site
python para_cattle/run.py constraints            # core stage 3
python para_cattle/run.py generate --seeds 1     # 4 plans a site, about 20 min each
python para_cattle/run.py export --out <folder>  # files for Restoration Explorer
```

`generate` takes site ids to run a subset. With `--seeds 3` it produces the core's full
12 plans a site, three times the time.

## Output for Restoration Explorer

`export` writes `index.json`, a `context.geojson` per site (property, existing native
vegetation, APP to recompose, streams, and pasture fields with vigor and the soy flag),
and one GeoJSON per plan. Technique codes match the explorer's Solutions view.

## Limitations

The core project's limitations all apply, plus these:

- The soy test uses vigor, slope, size, and clearing date only. It knows nothing of
  soil, rainfall timing, logistics, or land tenure.
- Pasture value is relative. It ranks paddocks within the model and is not a price.
- The three sites make a demonstration, not a representative set of Pará ranches.

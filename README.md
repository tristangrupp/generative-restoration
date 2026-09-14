# Generative restoration planning under Brazil's Forest Code

A generative model that designs restoration plans for Brazilian rural properties.
Each plan brings a property into line with the Forest Code (Lei 12.651/2012), follows
the terrain, the streams and the vegetation already standing, works with the farm's
mapped crop fields, and stays workable with the farm's own machinery.

The model produces twelve plans per property, because the law fixes how much land a
farm owes and leaves open where that land goes.

[METHODOLOGY.md](METHODOLOGY.md) explains the method in full.
[REPLICATION.md](REPLICATION.md) is the handoff for anyone rerunning or extending the
work.

## The regulation

Brazil's Forest Code requires every rural property to keep protected strips of native
vegetation along its streams and springs (called APP) and to keep a fixed share of its
area under native vegetation (Reserva Legal, 80% in the Amazon biome and 35% in the
Cerrado). The rules apply to cadastral land holdings. A holding that falls short must
restore the deficit. An owner has to restore APP where the law puts it, but can settle
a Reserva Legal shortfall off the property instead, by buying a tradable certificate
called a CRA (Cota de Reserva Ambiental).

## How the model works

The model is an energy-based generative model: a Markov random field over a graph of
the property, sampled with simulated annealing. Every 10 m pixel inside the property
boundary becomes a node carrying one of five labels (keep cropping, let it regenerate,
plant natives, agroforestry, windbreak). Edges join neighbouring pixels with weights
that favour boundaries running along the contour.

An energy function scores a complete plan by adding about fifteen terms. The legal
terms charge for unmet APP and price unmet Reserva Legal at the cost of a CRA. The
economic terms charge for foregone yield and for establishing each technique. The
design terms judge compactness, contour alignment, machinery workability, respect for
field boundaries, and gain in connectivity, measured on a second graph of the
vegetation patches already standing on this farm and its neighbours.

The annealer proposes whole design moves (lay a strip along a contour, grow a patch
outward following the terrain, connect two remnants, retire a field, take a margin off
a field edge) and accepts or rejects each against a cooling temperature. Three random
seeds give three different lawful plans for each of four intentions. After annealing,
any APP strip still in crops gets planted outright, because the law does not let that
requirement trade against anything else.

## Results on three Mato Grosso properties

| Site | Municipality | Area | Biome | Fiscal modules | APP owed | Reserva Legal owed |
|---|---|---:|---|---:|---:|---:|
| `sorriso_amazonia` | Sorriso | 5,187 ha | Amazon, 80% | 57.6 | 432 ha | 2,324 ha |
| `querencia_transicao` | Querência | 4,988 ha | Amazon, 80% | 62.3 | 576 ha | 2,517 ha |
| `primavera_cerrado` | Poxoréu | 3,315 ha | Cerrado, 35% | 55.3 | 102 ha | 0 ha |

All 36 plans meet their APP requirement and the Article 66 §3 cap on agroforestry.

Three findings came out of running this on real farms.

Grid resolution changes the legal answer. Moving from a 30 m to a 10 m grid raised the
measured APP obligation by 11.5% at Sorriso, 12.4% at Querência and 21.9% at Poxoréu,
while Reserva Legal barely moved. A 30 m riparian strip is one pixel wide on a 30 m
grid, so the coarse grid rounds the strip away at its edges.

The Article 61-A relief for land farmed before 2008 saved only 21, 26 and 8 ha on these
properties. Above ten fiscal modules the relief bottoms out at the same 30 m the full
rule demands on small streams, so in practice it helps smallholders.

Poxoréu already carries 2,148 ha of native vegetation against a 1,160 ha Reserva Legal
requirement. Its whole obligation is 102 ha of riverbank, which makes it the site where
the four intentions have to differ on placement and technique rather than on how much
land they take.

## Repository layout

```
src/                  pipeline stages s01-s10 and the model modules
data/forest_code/     Forest Code texts and forest_code_rules.json
data/sites/           the three properties (CAR boundary and crop-field layers)
                      and car_windows.gpkg, the CAR extract stage 1 selected from
data/context/         legal ledgers per property; rasters are rebuilt, not committed
data/machinery.json   equipment profiles
data/design.json      form settings, including linearity per intention
outputs/<site>/       figures, animation, and per-scenario metrics and polygons
```

## Data sources

- **CAR** rural property boundaries, published on Source Cooperative as GeoParquet:
  `https://data.source.coop/tristangruppwri/cadastral/Brazil_CAR_AREA_IMOVEL.parquet`
- **Crop field boundaries** from Trazo Fields v2, Mato Grosso 2024. Only stage 1 reads
  these, and the committed site files already carry the fields for all three
  properties.
- **Land cover** from MapBiomas Collection 10, 2024 and 2008. Stage 2 reads 2024 from
  a local GeoTIFF and falls back to the public cloud copy of 2008.
- **Elevation** from Copernicus DEM GLO-30 through the Microsoft Planetary Computer
  STAC API, which needs no key.

## Setup

The published outputs come from Python 3.11 with the versions in `requirements.txt`.
Paths default to the author's machine. Point them elsewhere with environment
variables:

```
GR_ROOT            repo root (defaults to the folder above src/)
GR_FIELDS_DIR      folder holding Brazil_Mato_Grosso_2024.gpkg (stage 1)
GR_MAPBIOMAS_DIR   folder holding brazil_coverage_2024.tif (stage 2)
```

## Running

```
python src/s01_select_sites.py          CAR property and crop fields -> data/sites/
python src/s02_build_context.py         elevation, hydrology, land cover -> data/context/
python src/s03_constraints.py           Forest Code masks and legal ledger
python src/s04_generate.py              12 scenarios per property -> outputs/<site>/
python src/s05_report.py                context plate and 12-panel comparison plate
python src/s06_linearity_sweep.py SITE  one plan at four linearity settings
python src/s07_panels.py                one figure and description per scenario
python src/s09_current_state.py         current-state panel per property
python src/s10_animation.py             walkthrough animation per property
```

Most stages take site ids to run a subset, as in `python src/s04_generate.py
primavera_cerrado`. Stage 5 renders every site regardless.

Stage 4 is the slow one: 9 to 18 minutes a scenario, about 9 hours for all 36. Setting
`SCENARIOS=11,12` reruns only those scenario numbers and reuses the metrics already on
disk for the rest, so a run that dies partway does not start over.

`src/_energy_diag.py SITE` prices reference plans (do nothing, APP only, restore
everything) against sampled ones term by term. Run it before changing any weight.

## Limitations

The Reserva Legal share comes from the property's biome window rather than an
official biome map clipped to the parcel. Pre-2008 farming is inferred from satellite
land cover rather than the owner's CAR declaration. Hilltops, tableland edges and
veredas use terrain and land-cover approximations. Establishment costs are ratios
rather than currency. State rules for Mato Grosso are not modelled.

This is a planning tool for comparing options, and nothing here can be filed with an
environmental agency.

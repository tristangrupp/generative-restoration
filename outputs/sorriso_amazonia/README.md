# Restoration scenarios - Sorriso / Lucas do Rio Verde

**CAR** `MT-5107925-3BAF91A5F735426F9224DCFAF1BF3913` | **Sorriso, MT** | 5187 ha | 57.6 fiscal modules | Amazonia (Reserva Legal 80%)

**Machinery profile** Large soy operation, controlled traffic - 36 m boom, 12 ha minimum workable remnant, 30 m minimum corridor

## Legal obligation

| Item | ha | Basis |
|---|---:|---|
| APP, full Art. 4 | 755.0 | Lei 12.651 Art. 4 |
| APP obligation after Art. 61-A | 733.6 | escadinha for 57.6 MF |
| APP already vegetated | 301.7 | MapBiomas 2024 |
| **APP to recompose** | **431.9** | |
| RL required | 4149.6 | Art. 12 |
| RL existing native | 1826.1 | incl. 301.8 ha in APP (Art. 15) |
| **RL deficit** | **2323.5** | |
| **Total** | **2755.4** | |

## Scenarios

Every scenario below is compliant. They differ in *how* they comply: how much is recomposed on the property, how much is settled off it under Art. 66 par. 5, and how much cropland survives.

| # | Archetype | On-farm ha | CRA off-farm ha | Crop kept ha | Regen | Planting | SAF | Windbreak | APP | Contour | Agg | d.stream m | <100m of water |
|---|---|---:|---:|---:|---:|---:|---:|---:|:-:|---:|---:|---:|---:|
| 01 | compliance_minimum | 1603 | 1153 | 1758 | 819 | 14 | 760 | 9 | OK | 0.85 | 0.96 | 185 | 48% |
| 02 | compliance_minimum | 1093 | 1662 | 2268 | 795 | 51 | 242 | 5 | OK | 0.84 | 0.96 | 162 | 61% |
| 03 | compliance_minimum | 1109 | 1647 | 2252 | 790 | 37 | 280 | 1 | OK | 0.84 | 0.96 | 118 | 63% |
| 04 | water_first | 2744 | 11 | 616 | 2743 | 2 | 0 | 0 | OK | 0.85 | 0.97 | 263 | 35% |
| 05 | water_first | 2747 | 9 | 614 | 2745 | 1 | 0 | 0 | OK | 0.86 | 0.97 | 267 | 35% |
| 06 | water_first | 2748 | 8 | 613 | 2746 | 2 | 0 | 0 | OK | 0.86 | 0.97 | 267 | 35% |
| 07 | corridor_network | 2733 | 22 | 628 | 2686 | 25 | 14 | 8 | OK | 0.84 | 0.97 | 261 | 35% |
| 08 | corridor_network | 2732 | 23 | 629 | 2526 | 181 | 23 | 2 | OK | 0.84 | 0.97 | 262 | 35% |
| 09 | corridor_network | 2739 | 16 | 622 | 2453 | 248 | 38 | 0 | OK | 0.85 | 0.97 | 261 | 36% |
| 10 | productive_mosaic | 2745 | 10 | 616 | 1513 | 281 | 903 | 48 | OK | 0.85 | 0.97 | 263 | 36% |
| 11 | productive_mosaic | 2741 | 14 | 620 | 1410 | 438 | 860 | 33 | OK | 0.86 | 0.97 | 262 | 36% |
| 12 | productive_mosaic | 2745 | 10 | 616 | 1334 | 431 | 939 | 41 | OK | 0.86 | 0.97 | 265 | 35% |

## How to read this

- **On-farm vs CRA.** The Reserva Legal deficit can be recomposed on the property or settled off it under Art. 66 par. 5 - by buying CRAs, by servitude, or by donating land inside a conservation unit. A scenario with a large CRA column is not a worse plan, it is a farm that would rather buy the obligation than retire cropland. **APP has no such route** and must be recomposed in place, which is why that column is always OK.
- **ECA** is equivalent connected area: sqrt of the sum of squared patch areas over the whole window, neighbours' remnants included. **Aggregation** is ECA over total vegetated area - 1.00 when the vegetation forms a single body. Two scenarios with the same hectares can differ here by how well they knit the landscape together.
- **SAF** does not discharge an APP obligation, and Art. 66 par. 3 caps exotic-bearing systems at half the recomposed area. Where the SAF column sits at exactly half the on-farm total, that cap is binding.
- Machinery is priced, not forbidden: the objective charges a plan for stranding crop remnants below the minimum workable size and for narrowing corridors below the plantable minimum, but a scenario can still buy its way past either if the rest of the design is worth it. Check the retained cropland geometry before treating a plan as buildable.

## Caveats

- Reserva Legal share is taken from the site's biome window, not from an official IBGE biome overlay of the parcel.
- Art. 4 VIII / IX / XI masks are terrain and MapBiomas proxies; see forest_code.py docstrings.
- Consolidation is inferred from MapBiomas 2008 land use, not from the property's CAR declaration of area consolidada.
- APP counted toward RL under Art. 15 requires the owner to have requested it in CAR; assumed granted here.
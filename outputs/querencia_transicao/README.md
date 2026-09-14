# Restoration scenarios - Querencia / Xingu headwaters

**CAR** `MT-5107065-0ADD539B82204ADD923C937474D48855` | **Querencia, MT** | 4988 ha | 62.3 fiscal modules | Amazonia (Reserva Legal 80%)

**Machinery profile** Large soy operation, controlled traffic - 36 m boom, 12 ha minimum workable remnant, 30 m minimum corridor

## Legal obligation

| Item | ha | Basis |
|---|---:|---|
| APP, full Art. 4 | 810.3 | Lei 12.651 Art. 4 |
| APP obligation after Art. 61-A | 783.9 | escadinha for 62.3 MF |
| APP already vegetated | 207.8 | MapBiomas 2024 |
| **APP to recompose** | **576.1** | |
| RL required | 3990.7 | Art. 12 |
| RL existing native | 1473.6 | incl. 207.8 ha in APP (Art. 15) |
| **RL deficit** | **2517.1** | |
| **Total** | **3093.2** | |

## Scenarios

Every scenario below is compliant. They differ in *how* they comply: how much is recomposed on the property, how much is settled off it under Art. 66 par. 5, and how much cropland survives.

| # | Archetype | On-farm ha | CRA off-farm ha | Crop kept ha | Regen | Planting | SAF | Windbreak | APP | Contour | Agg | d.stream m | <100m of water |
|---|---|---:|---:|---:|---:|---:|---:|---:|:-:|---:|---:|---:|---:|
| 01 | compliance_minimum | 1971 | 1122 | 1544 | 1392 | 28 | 540 | 11 | OK | 0.79 | 0.96 | 146 | 53% |
| 02 | compliance_minimum | 1765 | 1328 | 1750 | 1286 | 28 | 445 | 6 | OK | 0.81 | 0.96 | 101 | 62% |
| 03 | compliance_minimum | 1941 | 1153 | 1574 | 1228 | 60 | 645 | 7 | OK | 0.81 | 0.96 | 133 | 56% |
| 04 | water_first | 3026 | 68 | 489 | 3023 | 1 | 2 | 0 | OK | 0.83 | 0.97 | 220 | 41% |
| 05 | water_first | 3084 | 9 | 431 | 3084 | 0 | 0 | 0 | OK | 0.83 | 0.97 | 233 | 40% |
| 06 | water_first | 3083 | 11 | 432 | 3083 | 0 | 0 | 0 | OK | 0.83 | 0.97 | 220 | 41% |
| 07 | corridor_network | 3136 | 0 | 378 | 3136 | 0 | 0 | 0 | OK | 0.82 | 0.97 | 217 | 40% |
| 08 | corridor_network | 3277 | 0 | 238 | 3277 | 0 | 0 | 0 | OK | 0.82 | 0.97 | 219 | 39% |
| 09 | corridor_network | 3157 | 0 | 358 | 3156 | 0 | 0 | 0 | OK | 0.81 | 0.97 | 231 | 39% |
| 10 | productive_mosaic | 3088 | 5 | 427 | 1903 | 315 | 748 | 122 | OK | 0.83 | 0.97 | 228 | 40% |
| 11 | productive_mosaic | 2847 | 246 | 668 | 1674 | 267 | 842 | 64 | OK | 0.82 | 0.97 | 229 | 42% |
| 12 | productive_mosaic | 3059 | 34 | 456 | 1723 | 277 | 1015 | 44 | OK | 0.81 | 0.97 | 240 | 39% |

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
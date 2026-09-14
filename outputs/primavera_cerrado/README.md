# Restoration scenarios - Primavera do Leste / Campo Verde

**CAR** `MT-5107008-68B11B47FD234311B4ACF75DADE4C752` | **Poxoreu, MT** | 3315 ha | 55.3 fiscal modules | Cerrado (Reserva Legal 35%)

**Machinery profile** Large soy operation, controlled traffic - 36 m boom, 12 ha minimum workable remnant, 30 m minimum corridor

## Legal obligation

| Item | ha | Basis |
|---|---:|---|
| APP, full Art. 4 | 587.7 | Lei 12.651 Art. 4 |
| APP obligation after Art. 61-A | 579.3 | escadinha for 55.3 MF |
| APP already vegetated | 477.0 | MapBiomas 2024 |
| **APP to recompose** | **102.3** | |
| RL required | 1160.3 | Art. 12 |
| RL existing native | 2148.3 | incl. 477.0 ha in APP (Art. 15) |
| **RL deficit** | **0.0** | |
| **Total** | **102.3** | |

## Scenarios

Every scenario below is compliant. They differ in *how* they comply: how much is recomposed on the property, how much is settled off it under Art. 66 par. 5, and how much cropland survives.

| # | Archetype | On-farm ha | CRA off-farm ha | Crop kept ha | Regen | Planting | SAF | Windbreak | APP | Contour | Agg | d.stream m | <100m of water |
|---|---|---:|---:|---:|---:|---:|---:|---:|:-:|---:|---:|---:|---:|
| 01 | compliance_minimum | 216 | 0 | 950 | 191 | 11 | 15 | 0 | OK | 0.85 | 0.92 | 118 | 58% |
| 02 | compliance_minimum | 185 | 0 | 982 | 159 | 22 | 2 | 2 | OK | 0.85 | 0.91 | 101 | 65% |
| 03 | compliance_minimum | 170 | 0 | 996 | 158 | 9 | 4 | 0 | OK | 0.85 | 0.92 | 92 | 69% |
| 04 | water_first | 177 | 0 | 990 | 143 | 30 | 4 | 0 | OK | 0.85 | 0.91 | 112 | 62% |
| 05 | water_first | 188 | 0 | 979 | 142 | 39 | 6 | 0 | OK | 0.85 | 0.91 | 122 | 61% |
| 06 | water_first | 219 | 0 | 948 | 160 | 51 | 5 | 2 | OK | 0.85 | 0.92 | 117 | 60% |
| 07 | corridor_network | 395 | 0 | 771 | 218 | 165 | 13 | 0 | OK | 0.84 | 0.92 | 188 | 38% |
| 08 | corridor_network | 485 | 0 | 682 | 380 | 104 | 0 | 1 | OK | 0.84 | 0.92 | 171 | 36% |
| 09 | corridor_network | 502 | 0 | 665 | 358 | 142 | 3 | 0 | OK | 0.84 | 0.92 | 174 | 35% |
| 10 | productive_mosaic | 182 | 0 | 984 | 144 | 33 | 3 | 2 | OK | 0.86 | 0.92 | 105 | 65% |
| 11 | productive_mosaic | 257 | 0 | 909 | 152 | 66 | 38 | 1 | OK | 0.85 | 0.92 | 160 | 47% |
| 12 | productive_mosaic | 207 | 0 | 960 | 10 | 99 | 96 | 2 | OK | 0.86 | 0.92 | 123 | 61% |

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
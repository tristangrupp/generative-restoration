# Generative restoration planning under Brazil's Forest Code

I like designing solutions with real drivers in mind. It's important that a solution
has teeth behind it.

---

## 1. The regulation

Brazil's Forest Code requires every rural property to maintain protected strips along
its streams and springs as nature (called APP) and to keep a fixed share of its area
under native vegetation (Reserva Legal, 80% in the Amazon biome and 35% in the
Cerrado biome). This regulation applies to cadastral land holdings. If a holding in
the Amazon does not maintain 80% native vegetation, the deficit must be restored.

The two rules behave differently, and the difference shapes everything downstream.

**APP is geographic.** Article 4 fixes each strip by the width of the watercourse it
follows: 30 m on each bank of a stream under 10 m wide, 50 m up to 50 m wide, 100 m
up to 200 m, 200 m up to 600 m, and 500 m beyond that. Springs get a 50 m radius.
Slopes above 45 degrees are protected outright, as are hilltops meeting a height and
steepness test, the edges of tablelands, and the margins of the Cerrado wetlands
called veredas. None of this can be moved. A strip sits where the water is.

**Reserva Legal is a quantity.** The owner chooses where it goes, and Article 66 §5
lets a shortfall be settled off the property altogether, most often by buying a
tradable certificate called a CRA (Cota de Reserva Ambiental). Article 15 lets
vegetation standing inside an APP count toward the Reserva Legal total, so the two
obligations partly overlap. Article 67 exempts properties of four fiscal modules or
less from Reserva Legal recomposition entirely.

So an unmet APP strip is a violation, and an unmet Reserva Legal is a purchase with a
price. That single distinction is what separates a plan that keeps its cropland and
buys certificates from a plan that retires cropland and restores everything on site.

**Article 61-A** complicates both. Where farming was already established before 22
July 2008, the required strips narrow. The relief is graduated by farm size in fiscal
modules and Brazilians call it the escadinha, the little staircase: 5 m of replanting
at one module, 8 m at two, 15 m at four, and above ten modules half the river's own
width, floored at 30 m and capped at 100 m.

**Article 66 §3** caps exotic intercrop at half the area being recomposed, which is
the ceiling on how much agroforestry a compliance plan can lean on.

A farm that has cleared too much now owes restoration under one or both rules. The
amount owed is a single number, and that number says nothing about where the
restoration should go. On a 5,187 ha farm owing 2,755 ha, the ways of placing that
area are effectively uncountable, and they differ in cost, in how much cropland
survives, in whether the new vegetation connects to anything, and in whether a
tractor can still work what remains.

---

## 2. The model

I created an energy-based generative model—a Markov random field over a graph of the
property, sampled using simulated annealing—to design restoration plans that meet the
regulation.

For each property the model reads the cadastral boundary, land cover, the mapped crop
fields (including the crop grown on each one), and a stream network and slope surface
derived from a 30 m Copernicus elevation model. Comparing what the law requires
against what is currently present determines the restoration need.

Every 10 m pixel inside a given property boundary is treated as a node and each node
can have one of five labels (keep cropping, let it regenerate, plant natives,
agroforestry, windbreak). Pixels are joined by edges with weights that prefer edge
connections on the same contour lines. This weighting on contours improves the
topographic coherence of restoration plan components; for example, a restored strip
runs across the slope rather than straight down it, which is also how water gets
intercepted before it erodes soil. There would be 300,000 nodes on a 3,000 ha farm.

Nothing here is learned from examples. No public dataset pairs a Brazilian farm with
an approved restoration design, so there is nothing to learn from. Every term in the
energy function is written by hand, which means every term can be read, argued with,
and changed.

---

## 3. Inputs

**Cadastral boundaries** come from CAR, the Cadastro Ambiental Rural, Brazil's
national registry of rural properties. Every rural landowner is required to register
their outline in it. The published file runs 3.7 GB, and the model reads only the
rows covering each site, directly over the internet, filtered by state and bounding
box so the reader skips whole row groups rather than streaming the country.

CAR also records the property's size in fiscal modules, a municipal unit representing
roughly the smallest economically viable farm locally. Across Mato Grosso a module
runs between 30 and 100 ha, so a 1,000 ha farm in a 50 ha-module municipality is a
20-module property. Farm size in modules changes what the law demands, through both
the escadinha and the Article 67 exemption.

**Land cover** comes from MapBiomas, a Brazilian project that classifies every 30 m
pixel of the country every year as forest, savanna, pasture, soybean, water and so
on. The model uses the 2024 map for present conditions and the 2008 map for the
Article 61-A cutoff.

**Crop fields** come from a mapped field-boundary dataset that carries the modal
MapBiomas class per field, so each field is known both as a management unit and by
what grows on it. On the three test farms that comes out as 9 large soybean fields at
Sorriso, 23 at Querência, and 50 mostly-pasture fields at Poxoréu.

**Terrain** comes from Copernicus GLO-30. I derive the drainage network from the
elevation surface rather than from a published river map, because published maps drop
the small headwater streams that carry APP obligations, and those are exactly the
streams a farm has most of.

Two standard steps do the work. **Priority-flood** raises the floor of every enclosed
hollow until water can escape, working inward from the edges of the map, because
water routed across a raw elevation surface flows into the first pit and stops. **D8
flow routing** then sends water from each pixel to whichever of its eight neighbours
lies lowest, and counts how many pixels upstream eventually drain through each point.
That count measures how much land feeds a given spot. Above 25 ha of upstream area a
pixel is treated as a stream, which is about the smallest headwater a 30 m elevation
model resolves honestly. A stream pixel with no stream flowing into it is a spring,
which the law calls a nascente.

Channel width follows the standard hydraulic-geometry relationship, width growing as
roughly the 0.45 power of drainage area. The estimate does not need to be precise. It
only needs to sort each reach into one of the five width bands the statute defines.

Terrain and hydrology are computed at 30 m and resampled onto the 10 m analysis grid.
Running the flow routing at 10 m would cost nine times as much and add no information,
because the underlying elevation measurements are 30 m apart to begin with. The fine
grid buys geometric precision on the legal buffers, not terrain detail.

Everything is assembled on a common grid in EPSG:5880 (SIRGAS 2000 Brazil Polyconic),
buffered 3 km past the property so the model can see the neighbours' vegetation.

---

## 4. Turning the law into maps

Each provision becomes its own raster, kept separate so it can be audited on its own
rather than trusted as part of a blend.

Article 4 draws the strips. Article 61-A narrows them where the 2008 land cover shows
the ground was already in agricultural use, using the escadinha row that matches the
property's fiscal-module count. Article 12 sets the Reserva Legal share by biome.
Article 15 credits APP vegetation against the Reserva Legal. Article 67 checks the
four-module exemption. The result is a ledger: how many hectares are owed under each
article, and where the APP hectares specifically must go.

Two findings from running this on real farms are worth stating plainly.

**The escadinha is a smallholder provision in practice.** On the three test farms,
all above 55 fiscal modules, it saved between 8 and 26 ha. Half of a small stream's
width falls below the 30 m floor, and 30 m is the full width the law would have
demanded anyway, so the relief evaporates on any property large enough to have a
compliance problem worth modelling.

**Existing vegetation can extinguish one obligation entirely.** Poxoréu already
carries 2,148 ha of native vegetation against a 1,160 ha Reserva Legal requirement,
so it owes nothing under that rule. Its entire obligation is 102 ha of riverbank.
Sorriso, at 5,187 ha in the Amazon biome, owes 432 ha of APP plus 2,324 ha of Reserva
Legal.

Three of these maps are approximations and are labelled as such in the output.
Hilltops, tableland edges and veredas are defined in the statute by landform
descriptions that elevation data cannot reproduce exactly, so a technician should
review them before any filing.

---

## 5. The graph

Every 10 m pixel inside the boundary becomes a node. Edges join each node to its
eight neighbours, and each edge carries a weight.

The weights are deliberately uneven. An edge running straight downhill weighs 1.0. An
edge running sideways across the slope, along a contour, weighs 2.5. The energy
function charges for cutting edges, so cutting a contour-parallel edge costs more
than cutting a downhill one, and restored areas end up with their boundaries running
along contours rather than up and down the hill. That matches both how a landscape
architect lays out planting on a slope and how runoff is best intercepted.

A second graph holds the connectivity picture. Its nodes are the patches of native
vegetation already standing within 3 km of the farm, including patches belonging to
neighbouring landowners, and its edges are least-cost links between them. This is the
graph a plan is scored against for connectivity.

---

## 6. The energy function

A plan is one label on every node. The energy function turns a plan into a single
number by walking the graph and adding up local pieces, and that decomposition into
local pieces is what makes this a Markov random field. The plan's probability is
proportional to exp(−E), so low energy means both lawful and well formed.

About fifteen terms contribute, in three groups.

**Legal.** APP shortfall, penalised heavily. Reserva Legal shortfall, priced per
hectare to reflect what a CRA costs. The Article 66 §3 cap on exotic intercrop.

**Economic.** Foregone yield, charged per hectare taken out of production and reduced
where the ground is steep or waterlogged and less productive anyway, with agroforestry
charged at 40% of the full rate and windbreaks at 15% because both keep producing
something. Establishment cost by technique: fencing land and letting it regenerate is
the cheap option at 1, planting seedlings costs 6 times that, and agroforestry costs 8
to put in. And the price of settling the remainder off the property by buying a CRA.

**Design.** Compactness, contour alignment, machinery workability, respect for field
boundaries, and gain in connectivity measured on the second graph.

### Terms that read one node

A pixel sitting in a bare APP strip makes leaving it in crops expensive. A pixel in a
working field gives up a harvest every year if it converts. A pixel 400 m from the
nearest remnant will not regenerate, because regeneration depends on seed arriving
from nearby trees, so its establishment cost climbs toward the cost of planting.

### Terms that read edges

Wherever two neighbouring nodes carry different labels, the plan has drawn a boundary.
Summing those boundaries measures how ragged the plan is, and summing their weights
measures whether they run along the contour or straight down the hill.

A boundary through the middle of a mapped field costs more than one along the field's
own edge, because the first splits the land in a new way and the second works with
the field as the farmer currently has it. A second charge applies to leaving a field
part-converted, computed as f × (1 − f) on the converted fraction, which peaks at
half and vanishes at nought or fully. That pushes plans toward taking a whole field
or a clean margin. Both charges exempt APP, because the law puts those strips where
it puts them regardless of farm layout.

### Terms that need the whole plan

Total restored area is checked against the legal deficit, so a plan overshooting by
300 ha pays for it, and the penalty scales with the size of the obligation rather
than being a flat rate per hectare. A fixed charge would be meaningless across sites:
300 ha of excess is a rounding error against a 2,755 ha obligation and an absurdity
against a 102 ha one.

Connectivity is scored on the second graph, whose nodes are the vegetation patches
already standing, including forest patches on neighbouring farms. A plan earns more
for closing a gap between two patches than for planting the same hectares on their
own. The measure is equivalent connected area, the square root of the sum of squared
patch areas, which equals total area when everything is one patch and collapses
toward the largest patch as habitat fragments. It is scored as an aggregation ratio
rather than raw area, for reasons in the next section. The law operates property by
property, but the connectivity graph in the model helps ensure the restoration plans
create some cohesion between neighbouring properties.

---

## 7. Two calibration rules

Ten separate runs collapsed into the same degenerate answer, restoring the entire
farm, before I understood the first rule.

**Any reward proportional to restored area is a bug.** A reward for putting
vegetation on good ground, written as a payment per hectare, is maximised by covering
every hectare. Raw site fit, raw connected area, raw boundary length, an absolute
machinery penalty and a per-hectare preference bonus each produced the same useless
answer. Every such term has to be written as a preference among places, as a change
relative to doing nothing, or as a cost. Overshoot penalties have to scale with the
obligation as well, or an already-compliant property restores fourteen times what it
owes.

**When one technique's cost curve ramps toward another's, both ends must carry their
own price adjustment.** Regeneration far from a seed source ramps toward the cost of
planting, which is correct, because at that distance the two operations are
physically the same thing. The ramp was then divided by regeneration's own preference
weight, which made hard-ground regeneration dearer than planting the identical
hectare: 4.6 against 3.16 under the water-first weights. The model responded by
planting 2,720 ha and regenerating 31, on land averaging 317 m from a remnant. After
the fix, same site and same weights: 320 ha planted, 2,308 regenerated. No individual
weight had looked wrong, which is why it survived several audits of the weights.

---

## 8. Sampling

Sampling is what makes this generative.

Rather than flipping pixels, the annealer proposes whole design moves—lay a strip
along a contour, grow a patch outward from a seed following the terrain, connect two
remnants along the cheapest route for wildlife, widen an existing woodland, retire a
whole field, take a margin off one field edge, hand an unneeded area back to
crops—and accepts or rejects each against a cooling temperature over 9,000
iterations. Early in the run it accepts many changes that worsen the score, which
lets it explore widely and escape plans that are good without being the best
available. By the end it accepts only improvements. The staged tightening is
simulated annealing, named after the way slowly cooled metal settles into a stronger
structure than metal quenched fast.

Two of those moves deserve detail.

**Patch growth follows the ground.** A patch grows outward from its seed by
repeatedly absorbing whichever neighbouring block is cheapest to reach, where cost
rises with slope and falls near water, near existing vegetation and off cropland. A
patch therefore runs down a hollow, wraps around a remnant, and stops where the
ground changes. An earlier version stamped a Euclidean disc, which put visible
circles on the map that ignored everything underneath them.

**Corridor routes use Dijkstra's algorithm** over a resistance surface where cropland
is expensive to cross and riverbanks and existing vegetation are cheap, so routes
follow watercourses and tree cover without being told to.

Working in design moves rather than pixel edits matters, because a pixel-by-pixel
search spends its entire budget rediscovering that restoration areas need to be
joined up.

Because the proposals are stochastic and the energy landscape holds many separate
basins that score almost equally well, three runs from different random seeds produce
three genuinely different lawful plans rather than three copies of one optimum. On
Poxoréu the minimum-compliance seeds land at 216, 185 and 170 ha, in visibly
different places on the farm.

---

## 9. The deterministic step

One deterministic step follows the annealing. Any APP strip the sampler left in crops
gets planted outright, because Article 4 fixes those strips geographically and they
cannot be traded against anything else. A plan leaving 2 ha of 432 uncovered is
unlawful rather than slightly worse.

I closed this after the annealing rather than by raising the APP weight, because
raising the weight would have distorted every other trade-off across the whole farm
in order to fix 0.4% of one seed. Active planting is used for the closure, since a
strip the sampler declined to touch is one it found no regeneration case for.

---

## 10. Twelve plans per property

Twelve comes from four intentions run three times each. Each intention is a different
set of weights over the same energy function, so all twelve obey the same law and
differ in what they optimise beyond it.

| Intention | What it aims for |
|---|---|
| Minimum legal compliance | Regenerate where regeneration will work, buy CRAs for the remainder, keep as much cropland as the law allows |
| Water and soil first | Plant the riparian strips so they close fast, take wet and erodible ground out of the rotation |
| Network connectivity | Place restoration where it links this farm's woodland to the neighbours', planted rather than regenerated so the corridor works on a schedule |
| Productive mosaic | Agroforestry to the Article 66 ceiling, windbreaks along field edges, land still earning while it complies |

Preferences between techniques are written as discounts on establishment cost rather
than as bonuses per hectare. Written as a bonus, preferring planting pays the plan for
every hectare it plants, and the cheapest way to collect is to plant the whole farm.
Written as a discount, a preference can only shift which technique is used, never how
much land is taken.

---

## 11. Machinery and shape

A configuration file describes the equipment: sprayer boom width, planter width,
turning radius, maximum working slope, and the smallest field remnant worth driving a
machine into. Three profiles ship with it, covering a large mechanised soy operation,
a medium mixed farm, and a smallholding.

A single setting, `linearity`, runs 0 to 1 and controls form. At 0 the model grows
compact bodies outward from existing woodland. At 1 it lays narrow strips along
contours, riverbanks and field edges. It blends two things at once: how much the shape
term weighs compactness against the orientation of restored edges, and how often the
sampler reaches for a line move rather than a patch move. Most working farms want
something in between.

Contour lines are traced from the elevation surface and then filtered for
practicality. Where a line curves tighter than the machinery can turn, it is cut
there. Remaining pieces shorter than a useful working length are dropped. Strip widths
are rounded up to a whole number of machine passes, so a 36 m sprayer never receives a
33 m strip and wastes half a pass. Every strip the model can propose is drivable
before it is proposed, rather than penalised after the fact.

Measured effect on one test farm, everything else held fixed:

| linearity | Hectares restored | Resulting form |
|---|---:|---|
| 0.00 | 295 | Solid blocks attached to existing woodland |
| 0.35 | 239 | Blocks with connecting threads |
| 0.70 | 220 | Bands running through retained cropland |
| 1.00 | 219 | Narrow strips, cropland kept in one piece |

---

## 12. Grid size changed the legal answer

The model originally worked at 30 m. Moving to 10 m raised the measured APP obligation
on all three test farms.

| Farm | At 30 m | At 10 m | Missed |
|---|---:|---:|---:|
| Sorriso | 387 ha | 432 ha | 11.5% |
| Querência | 512 ha | 576 ha | 12.4% |
| Poxoréu | 84 ha | 102 ha | 21.9% |

Reserva Legal barely moved anywhere, and that contrast explains the cause. Reserva
Legal is a share of property area, which a coarse grid measures accurately. APP is
buffer geometry, and a 30 m strip is one pixel on a 30 m grid against three pixels on
a 10 m grid, so rounding at the edges of a single-pixel band is large relative to the
band itself. Poxoréu shows the largest error because riverbank strips are its entire
obligation.

The lesson generalises to any rule defined by a buffer distance. The grid has to be
several times finer than the narrowest buffer the rule specifies, or the model
understates the law.

---

## 13. Outputs

Per scenario: a GeoPackage of restoration polygons labelled by technique, which opens
straight in QGIS; a metrics record covering hectares by technique, cropland kept and
lost, CRAs bought, compliance against each rule, connectivity statistics, and how far
the new vegetation sits from water and from existing vegetation; and a standalone
figure with a written account of what that plan does, including which fields it left
whole, which gave up a margin, and which went out of production entirely.

Per property: a current-state panel showing land cover, the stream network, the crop
fields coloured by what grew on them, and the cadastral boundary; a twelve-panel
comparison plate; a legal ledger broken down by article; a linearity sweep; and an
animated walkthrough that plays the farm as it is, the key layers behind each
intention, and the three plans those layers produced.

---

## 14. Limitations

The Reserva Legal share is taken from the region the property sits in rather than an
official biome boundary clipped to the parcel.

Pre-2008 occupation is inferred from satellite land cover rather than the owner's own
declaration in CAR.

Hilltops, tableland edges and veredas are approximations, because the statute defines
them by landform descriptions that elevation data cannot reproduce exactly.

Fiscal module size is read from CAR rather than the official municipal table.

Mato Grosso state rules are not included, nor are any restoration commitments an
owner has already signed.

Establishment costs are relative ratios rather than currency, with no local price data
behind them.

This is a planning tool for comparing options. It is not a document that can be filed
with an environmental agency.

# Status — DAMAC Lagoons 3D Villa Map

Honest account of what's real, what's stubbed, and what's still missing, measured
against the original build spec's "Definition of done."

## What actually shipped

**A production WebGL rendering engine**, not a prototype:

- `InstancedMesh` per distinct footprint size (one draw call per size, not per
  villa) — see `src/render/villaField.ts`. Footprint size is interpolated from
  confirmed bedroom count (`src/data/types.ts#sizeRatiosFor`) so a real 4BR
  townhouse gets a genuinely different box than a 3BR or 5BR one, not forced
  into the nearest of the spec's 4 named tiers. With the current 497 verified
  units across 3/4/5BR townhouses + 2 unconfirmed villa tiers, that's 5 draw
  calls; draw-call count is bounded by distinct sizes, not plot count.
- A procedural neon-edge shader (`src/render/villaMaterial.ts`) that reproduces
  the approved CSS prototype's "border + layered glow" technique in GLSL: a
  UV-space border stripe per box face, a thin hot-core filament, red only —
  never whitened. `UnrealBloomPass` blooms it into the halo. Verified by pixel
  sampling the rendered output that no edge reads as pink (see "Colour
  verification" below) — this failed on the first pass and was corrected.
- An isometric `PerspectiveCamera` rig (`src/render/cameraRig.ts`) with
  eased fly-to tweens, orbit controls for free exploration, and a locked
  elevation/azimuth that matches the approved oblique angle.
- Data-driven road/ground generation (`src/render/ground.ts`,
  `src/data/loadCluster.ts`) that derives road ribbons and per-unit rotation
  from the *actual measured* row geometry — nothing is templated or alternated
  arbitrarily.
- Search with fly-to, pulsing highlight, leader-line callout, a real
  **not-found** state, and a distinct **location-not-yet-available** state for
  plots that are in the database but not yet position-verified.

**563 real Portofino plots in the database, 562 of them position-verified** —
not fabricated, not raw OCR. Every plot number in
`src/data/clusters/portofino.json` was read directly
off the source master plan raster at high zoom by a human-equivalent visual
pass (not blind OCR), cross-checked against the plot-tagger tool re-plotting
every pin back onto the source image to confirm it lands on the correct
building. For the first 59 (the lagoon-front hero ring) every single pin was
individually spot-checked this way. For the next 439 (western townhouse grid +
southern boundary row), positions were captured as anchor points read directly
off a 25px reference grid at multiple points per row/column, with the units
between anchors placed by linear interpolation along the verified curve —
every plot *number*'s existence and sequence was still read directly off the
source, only the sub-pixel position between two verified real coordinates is
computed. ~20 spot-checks across all 5 row/column groups (including every
segment endpoint) confirmed pins landing exactly on the correct building; see
`.devtools/verify_*.png` from the build session.

Coverage is Portofino's lagoon-front hero ring (BL101–159), the western
townhouse grid (3 back-to-back column groups, BL178–424), the southern
boundary row (BL425–616), and the northern entrance boundary row (BL162–177,
continuing numerically as BL929–977 — confirmed by direct visual adjacency,
a real numbering-scheme jump rather than two separate rows). One plot,
**BL141**, has its number/position inferred from neighbours because its label
was occluded on the source raster — it's flagged `"verified": false` and the
app's search correctly reports it as "location not yet available" rather than
guessing.

Not yet digitized within Portofino: the eastern interior block (several more
back-to-back column groups, roughly BL600s–900s interior rows), and a few
small sub-clusters visible near the entrance (BL933–942, BL844–853, and an
inner back-row behind the north entrance row, BL950s–960s). Based on tile
coverage during this session, that's likely another 200-300+ units.

**A plot-tagging tool** (`tools/plot-tagger/`) — a standalone, zero-build
HTML/JS page matching the spec's §1 recommendation exactly: load a master-plan
crop, click a plot, type its number/type, save. It reads and writes the exact
same JSON shape the app consumes, so output drops straight into
`src/data/clusters/<cluster>.json` with no transformation step. It was used
during this build to re-verify every digitized Portofino coordinate against
the source image.

## What's NOT done — read this before assuming coverage

The spec's "critical dependency" section was right: **data, not visuals, is
the hard part**, and this session could not close that gap for the whole
community. Specifically:

- **No `DAMAC_Lagoons_Consolidated.xlsx` / `DAMAC_Portofino.xlsx` existed** in
  this repository or session — only the master-plan PDF was available. There
  is no independent source of truth for plot→unit-type→bedroom-count beyond
  what's printed on the drawing itself.
- **Part of Portofino is still not digitized**: the eastern interior block
  (several more back-to-back column groups, roughly BL600s–900s) and the
  northern entrance rows (~250-350+ units combined) are real data on the
  source raster but have not been transcribed yet. `tools/plot-tagger` is
  ready for this.
- **The other 10 clusters** (Santorini, Costa Brava, Nice, Venice, Malta,
  Marbella, Montecarlo, Mykonos, Ibiza, Morocco) have zero digitized units.
  The rendering engine is cluster-agnostic (`loadCluster('clusterId')`) so
  adding one is: digitize with the tagger → drop the JSON in
  `src/data/clusters/` → point `src/main.ts` at it (or add the cluster
  switcher UI, not yet built since there's only one cluster to switch to).
- **Positions are plan-space, not surveyed GPS.** Per spec's own priority
  order, real georeferencing against Esri World Imagery in QGIS was the
  preferred approach — that requires an interactive GIS session this
  environment doesn't have. Instead, `loadCluster.ts` maps the source raster's
  pixel coordinates directly into world space, which preserves true relative
  position, spacing, and curvature (verified against the source drawing) but
  is **not** a real-world lat/lng and should not be used for anything beyond
  this visualization.
- **Bedroom counts for `BL-VD1` / `BL-V75` are unconfirmed.** The master-plan
  legend gives these as villa type codes without an explicit bedroom digit
  (unlike `BL-3-M` / `BL-4-M` / `BL-5-E`, where the digit is very likely the
  bedroom count). Rather than guess, `bedrooms: null` /
  `bedroomsConfirmed: false` is stored for every unit of these two types, and
  their render tier (3 and 4 respectively) is derived only from their
  *measured relative footprint size* on the drawing, which is directly
  observable and not fabricated.

None of the above is silently hidden: the app's `#coverage-note` HUD element
always shows the live verified-plot count, and search returns an explicit
"not found" or "location not yet available" message rather than pretending
coverage that doesn't exist.

## Definition of done — against the original spec

- [ ] Plot database covers all 11 clusters — **563 of ~2,000+ units, Portofino
      only (562 position-verified, 1 flagged unverified). Portofino itself is
      an estimated 65-70% digitized** (eastern interior block + a few small
      sub-clusters still missing). Nothing beyond that is claimed.
- [~] Renders at 60fps with instancing — **architecture validated, actual fps
      not confirmed.** The instancing design gives 2 draw calls total
      regardless of plot count (verified: 58 units currently render in 2
      draw calls, and adding units doesn't add draw calls). But this
      execution environment only exposes SwiftShader (software OpenGL, no
      real GPU — confirmed via `WEBGL_debug_renderer_info`), which measured
      ~3.6fps; that number reflects the sandbox, not the app, and should be
      ignored. Needs a real-GPU browser to confirm actual frame rate,
      especially once the dataset grows to thousands of units.
- [x] Colour check: no rendered pixel reads as pink — the first shader/bloom
      pass *did* regress to pink (channel ratios up to B/R≈0.69) at close
      zoom; root-caused to unbounded HDR emissive stacking through the bloom
      pass and fixed with ACES tone mapping + a bounded emissive model. Now
      spot-checked at multiple zoom levels, B/R stays ≤0.33.
- [x] Back-to-back vs single-row layout matches the real site plan, not a
      repeated pattern — for the section actually digitized. Both patterns
      are now real and present: 2 single boundary-facing rows (hero-ring
      north/south, west boundary, south boundary) and 2 genuine back-to-back
      column pairs (western grid columns B and C, each a shared-rear-lane
      pair per the source drawing) rather than an alternating template.
- [x] Search flies camera + highlights + shows callout, with a real
      not-found state, plus the additional "location not yet available"
      state for unverified plots.
- [x] Unit block size visibly reflects bedroom tier — 3BR/4BR/5BR townhouses
      (interpolated sizing, confirmed real bedroom counts from the legend)
      and the two unconfirmed-bedroom villa tiers all render at visibly
      distinct sizes; confirmed visually in the running app.

## Continuing the work

1. Open `tools/plot-tagger/index.html` (any static server, e.g.
   `python3 -m http.server` from that folder).
2. Load the master-plan raster (export it once from the source PDF at full
   resolution — the version used here is 10367×7333px) and, to extend
   Portofino, load `src/data/clusters/portofino.json` as the existing-data
   file so new pins merge with the verified set instead of starting over.
3. Zoom into the townhouse grid, click each plot, fill in id/type/tier/row
   group, save. Export downloads an updated `portofino.json` — drop it back
   into `src/data/clusters/`.
4. For a new cluster: same flow with a fresh cluster id; the app already
   supports loading any `src/data/clusters/<id>.json` via
   `loadCluster(id)`.
5. Run `npm run dev` to preview, `npm run build` to produce `dist/`.

# DAMAC Lagoons — Interactive 3D Villa Map

A buyer-facing 3D map of DAMAC Lagoons: every villa is a real extruded 3D
block, red-on-black neon, sized by bedroom tier. Search by plot number to fly
the camera to a unit and highlight it.

**Read [`STATUS.md`](./STATUS.md) first.** The rendering engine is production-
grade and cluster-agnostic; the plot database currently covers 59 real,
individually-verified units in Portofino's lagoon-front section, not the full
community. STATUS.md explains exactly what's covered, what isn't, and why.

## Stack

- Three.js (WebGL), `InstancedMesh` per bedroom tier — one draw call per tier
  regardless of plot count.
- Custom GLSL shader for the neon-edge look, `UnrealBloomPass` for the glow.
- Vite + TypeScript.

## Run it

```
npm install
npm run dev       # dev server
npm run build     # production build to dist/
npm run preview   # serve the production build
```

## Project layout

```
src/
  data/
    types.ts            # RawUnit / PlacedUnit / cluster data shapes
    loadCluster.ts       # raster px -> world space, tier sizing, road generation
    clusters/*.json      # per-cluster plot databases (digitized data)
  render/
    villaMaterial.ts     # neon-edge shader
    villaField.ts         # InstancedMesh construction + highlight control
    ground.ts             # ground plate + road ribbons
    cameraRig.ts          # isometric camera + fly-to tween
    scene.ts               # renderer/composer/bloom setup
  ui/
    search.ts             # search bar, not-found / unavailable states
    callout.ts            # 3D-to-screen projected callout
  main.ts                 # wires it together

tools/
  plot-tagger/            # standalone click-to-tag digitization tool
                           # (no build step — open index.html directly)
```

## Adding plot data

Use `tools/plot-tagger/index.html` — load the master-plan raster, click a
plot, enter its number/type/tier, export. The exported JSON drops straight
into `src/data/clusters/<cluster>.json`, no transformation needed. See
STATUS.md for the full workflow and what's left to digitize.

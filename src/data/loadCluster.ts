import type { PlacedCluster, PlacedUnit, RawClusterData, RawUnit, RoadSegment } from './types';
import { sizeRatiosFor } from './types';

const WORLD_TARGET_SPAN = 260;
/** fraction of measured neighbour spacing a building's footprint fills; leaves a gap either side */
const PACKING_FACTOR = 0.78;
const ROAD_WIDTH_FACTOR = 0.85;
const ROAD_OFFSET_GAP = 1.15; // multiplier beyond half-building-depth before the road starts

interface Vec2 {
  x: number;
  z: number;
}

function dist(a: Vec2, b: Vec2): number {
  return Math.hypot(a.x - b.x, a.z - b.z);
}

const clusterModules = import.meta.glob('./clusters/*.json') as Record<
  string,
  () => Promise<{ default: RawClusterData }>
>;

export async function loadCluster(clusterId: string): Promise<PlacedCluster> {
  const key = `./clusters/${clusterId}.json`;
  const loader = clusterModules[key];
  if (!loader) throw new Error(`No cluster data found for "${clusterId}" (expected ${key})`);
  const mod = await loader();
  return placeCluster(mod.default);
}

export function placeCluster(raw: RawClusterData): PlacedCluster {
  const units = raw.units;

  const xs = units.map((u) => u.planPx[0]);
  const ys = units.map((u) => u.planPx[1]);
  const minPxX = Math.min(...xs);
  const maxPxX = Math.max(...xs);
  const minPxY = Math.min(...ys);
  const maxPxY = Math.max(...ys);
  const pxSpan = Math.max(maxPxX - minPxX, maxPxY - minPxY) || 1;
  const scale = WORLD_TARGET_SPAN / pxSpan;
  const centerPxX = (minPxX + maxPxX) / 2;
  const centerPxY = (minPxY + maxPxY) / 2;

  const toWorld = (px: [number, number]): Vec2 => ({
    x: (px[0] - centerPxX) * scale,
    z: (px[1] - centerPxY) * scale,
  });

  // group by rowGroup, preserving source order (already spatially sequential)
  const groups = new Map<string, typeof units>();
  for (const u of units) {
    if (!groups.has(u.rowGroup)) groups.set(u.rowGroup, []);
    groups.get(u.rowGroup)!.push(u);
  }

  const worldPosById = new Map<string, Vec2>();
  for (const u of units) worldPosById.set(u.id, toWorld(u.planPx));

  // --- derive footprint sizes from measured real spacing ---
  // Units are grouped by their size ratio (bedroom-interpolated when confirmed,
  // tier bucket otherwise) rather than raw tier, so a real 4BR townhouse gets
  // its own size between 3BR and 5BR instead of being forced into one bucket.
  const sizeKey = (u: RawUnit) => Math.round(sizeRatiosFor(u).width);

  const spacingsBySize = new Map<number, number[]>();
  for (const group of groups.values()) {
    for (let i = 1; i < group.length; i++) {
      const a = worldPosById.get(group[i - 1].id)!;
      const b = worldPosById.get(group[i].id)!;
      const d = dist(a, b);
      if (d <= 0 || !Number.isFinite(d)) continue;
      const key = sizeKey(group[i]);
      if (!spacingsBySize.has(key)) spacingsBySize.set(key, []);
      spacingsBySize.get(key)!.push(d);
    }
  }

  let anchorKey: number | null = null;
  let anchorSampleCount = -1;
  for (const [key, samples] of spacingsBySize) {
    if (samples.length > anchorSampleCount) {
      anchorKey = key;
      anchorSampleCount = samples.length;
    }
  }
  if (anchorKey === null) anchorKey = sizeKey(units[0]);

  const median = (arr: number[]): number => {
    const sorted = [...arr].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  };

  const anchorSamples = spacingsBySize.get(anchorKey) ?? [20];
  const anchorSpacing = median(anchorSamples);
  const anchorWidth = anchorSpacing * PACKING_FACTOR;

  const footprintCache = new Map<number, { width: number; depth: number; height: number }>();
  function footprintFor(u: RawUnit) {
    const ratios = sizeRatiosFor(u);
    const key = Math.round(ratios.width);
    let fp = footprintCache.get(key);
    if (!fp) {
      const width = anchorWidth * (ratios.width / anchorKey!);
      fp = {
        width,
        depth: width * (ratios.depth / ratios.width),
        height: width * (ratios.height / ratios.width),
      };
      footprintCache.set(key, fp);
    }
    return fp;
  }

  // overall centroid, used to determine "outward" direction for road offset
  let sumX = 0;
  let sumZ = 0;
  for (const p of worldPosById.values()) {
    sumX += p.x;
    sumZ += p.z;
  }
  const overallCenter: Vec2 = { x: sumX / worldPosById.size, z: sumZ / worldPosById.size };

  const placedUnits: PlacedUnit[] = [];
  const roads: RoadSegment[] = [];

  for (const [rowGroup, group] of groups) {
    const positions = group.map((u) => worldPosById.get(u.id)!);

    for (let i = 0; i < group.length; i++) {
      const u = group[i];
      const pos = positions[i];
      const prev = positions[i - 1] ?? pos;
      const next = positions[i + 1] ?? pos;
      const tangent: Vec2 = { x: next.x - prev.x, z: next.z - prev.z };
      const len = Math.hypot(tangent.x, tangent.z) || 1;
      const dir = { x: tangent.x / len, z: tangent.z / len };
      const rotationY = Math.atan2(dir.x, dir.z);

      placedUnits.push({
        ...u,
        position: pos,
        rotationY,
        footprint: footprintFor(u),
      });
    }

    // road: offset polyline on the outward side of the row
    if (positions.length >= 2) {
      const rowCenter: Vec2 = positions.reduce(
        (acc, p) => ({ x: acc.x + p.x / positions.length, z: acc.z + p.z / positions.length }),
        { x: 0, z: 0 },
      );
      const overallDir: Vec2 = { x: rowCenter.x - overallCenter.x, z: rowCenter.z - overallCenter.z };

      const rowFootprint = footprintFor(group[0]);
      const halfDepth = rowFootprint.depth / 2;
      const roadWidth = rowFootprint.width * ROAD_WIDTH_FACTOR;
      const offsetDist = halfDepth * ROAD_OFFSET_GAP + roadWidth / 2;

      const roadPoints: Vec2[] = positions.map((p, i) => {
        const prev = positions[i - 1] ?? p;
        const next = positions[i + 1] ?? p;
        const tangent: Vec2 = { x: next.x - prev.x, z: next.z - prev.z };
        const tlen = Math.hypot(tangent.x, tangent.z) || 1;
        // perpendicular to tangent, two candidate directions
        let nx = -tangent.z / tlen;
        let nz = tangent.x / tlen;
        // orient outward using overall row-to-center direction
        if (nx * overallDir.x + nz * overallDir.z < 0) {
          nx = -nx;
          nz = -nz;
        }
        return { x: p.x + nx * offsetDist, z: p.z + nz * offsetDist };
      });

      roads.push({ points: roadPoints, width: roadWidth, rowGroup });
    }
  }

  const px = placedUnits.map((u) => u.position.x);
  const pz = placedUnits.map((u) => u.position.z);
  const bounds = {
    minX: Math.min(...px),
    maxX: Math.max(...px),
    minZ: Math.min(...pz),
    maxZ: Math.max(...pz),
  };

  return {
    cluster: raw.cluster,
    units: placedUnits,
    roads,
    bounds,
    source: raw.source,
    legend: raw.legend,
  };
}

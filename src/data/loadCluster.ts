import type { PlacedCluster, PlacedUnit, RawClusterData, RoadSegment, TierId } from './types';
import { TIERS } from './types';

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

  // --- derive tier footprint sizes from measured real spacing ---
  const spacingsByTier = new Map<TierId, number[]>();
  for (const group of groups.values()) {
    for (let i = 1; i < group.length; i++) {
      const a = worldPosById.get(group[i - 1].id)!;
      const b = worldPosById.get(group[i].id)!;
      const d = dist(a, b);
      if (d <= 0 || !Number.isFinite(d)) continue;
      const tier = group[i].tier;
      if (!spacingsByTier.has(tier)) spacingsByTier.set(tier, []);
      spacingsByTier.get(tier)!.push(d);
    }
  }

  let anchorTier: TierId | null = null;
  let anchorSampleCount = -1;
  for (const [tier, samples] of spacingsByTier) {
    if (samples.length > anchorSampleCount) {
      anchorTier = tier;
      anchorSampleCount = samples.length;
    }
  }
  if (anchorTier === null) anchorTier = 3;

  const median = (arr: number[]): number => {
    const sorted = [...arr].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  };

  const anchorSamples = spacingsByTier.get(anchorTier) ?? [20];
  const anchorSpacing = median(anchorSamples);
  const anchorWidth = anchorSpacing * PACKING_FACTOR;

  const footprintByTier: Record<TierId, { width: number; depth: number; height: number }> = {
    1: sizeFor(1),
    2: sizeFor(2),
    3: sizeFor(3),
    4: sizeFor(4),
  };
  function sizeFor(tier: TierId) {
    const t = TIERS[tier];
    const anchor = TIERS[anchorTier as TierId];
    const width = anchorWidth * (t.relWidth / anchor.relWidth);
    return {
      width,
      depth: width * (t.relDepth / t.relWidth),
      height: width * (t.relHeight / t.relWidth),
    };
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
        footprint: footprintByTier[u.tier],
      });
    }

    // road: offset polyline on the outward side of the row
    if (positions.length >= 2) {
      const rowCenter: Vec2 = positions.reduce(
        (acc, p) => ({ x: acc.x + p.x / positions.length, z: acc.z + p.z / positions.length }),
        { x: 0, z: 0 },
      );
      const overallDir: Vec2 = { x: rowCenter.x - overallCenter.x, z: rowCenter.z - overallCenter.z };

      const tier = group[0].tier;
      const halfDepth = footprintByTier[tier].depth / 2;
      const roadWidth = footprintByTier[tier].width * ROAD_WIDTH_FACTOR;
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

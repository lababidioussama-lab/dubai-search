export type TierId = 1 | 2 | 3 | 4;

export interface TierSpec {
  tier: TierId;
  label: string;
  /** relative footprint width, matches the confirmed spec proportions */
  relWidth: number;
  relDepth: number;
  relHeight: number;
}

/** Confirmed tier progression (relative proportions from the approved spec). */
export const TIERS: Record<TierId, TierSpec> = {
  1: { tier: 1, label: '3BR Townhouse', relWidth: 64, relDepth: 46, relHeight: 30 },
  2: { tier: 2, label: '5BR Villa', relWidth: 92, relDepth: 64, relHeight: 42 },
  3: { tier: 3, label: '6BR Villa', relWidth: 118, relDepth: 82, relHeight: 52 },
  4: { tier: 4, label: '7BR Signature Villa', relWidth: 148, relDepth: 104, relHeight: 64 },
};

/**
 * The confirmed spec only names 3/5/6/7BR anchor sizes, but real plot data
 * includes bedroom counts the sketch didn't enumerate (e.g. 4BR townhouses).
 * Rather than force those into the nearest existing tier (losing the "size
 * communicates bedroom count" signal), interpolate width/depth/height
 * independently between the confirmed anchors — this keeps the exact spec
 * numbers at 3/5/6/7BR and fills the gaps consistently with the spec's own
 * "~1.4-1.5x step" progression.
 */
const BEDROOM_CURVE: { bedrooms: number; width: number; depth: number; height: number }[] = [
  { bedrooms: 3, width: 64, depth: 46, height: 30 },
  { bedrooms: 5, width: 92, depth: 64, height: 42 },
  { bedrooms: 6, width: 118, depth: 82, height: 52 },
  { bedrooms: 7, width: 148, depth: 104, height: 64 },
];

function interpolateCurve(bedrooms: number, key: 'width' | 'depth' | 'height'): number {
  const pts = BEDROOM_CURVE;
  if (bedrooms <= pts[0].bedrooms) {
    const [a, b] = [pts[0], pts[1]];
    return a[key] + ((b[key] - a[key]) * (bedrooms - a.bedrooms)) / (b.bedrooms - a.bedrooms);
  }
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i];
    const b = pts[i + 1];
    if (bedrooms >= a.bedrooms && bedrooms <= b.bedrooms) {
      return a[key] + ((b[key] - a[key]) * (bedrooms - a.bedrooms)) / (b.bedrooms - a.bedrooms);
    }
  }
  const a = pts[pts.length - 2];
  const b = pts[pts.length - 1];
  return b[key] + ((b[key] - a[key]) * (bedrooms - b.bedrooms)) / (b.bedrooms - a.bedrooms);
}

export interface SizeRatios {
  width: number;
  depth: number;
  height: number;
}

/**
 * Relative footprint ratios for a unit: interpolated from its confirmed
 * bedroom count when known, falling back to its coarse tier bucket when the
 * bedroom count is unconfirmed (e.g. villa codes without a bedroom digit).
 */
export function sizeRatiosFor(unit: {
  tier: TierId;
  bedrooms: number | null;
  bedroomsConfirmed: boolean;
}): SizeRatios {
  if (unit.bedroomsConfirmed && unit.bedrooms != null) {
    return {
      width: interpolateCurve(unit.bedrooms, 'width'),
      depth: interpolateCurve(unit.bedrooms, 'depth'),
      height: interpolateCurve(unit.bedrooms, 'height'),
    };
  }
  const t = TIERS[unit.tier];
  return { width: t.relWidth, depth: t.relDepth, height: t.relHeight };
}

export interface RawUnit {
  id: string;
  cluster: string;
  rowGroup: string;
  typeCode: string;
  tier: TierId;
  bedrooms: number | null;
  bedroomsConfirmed: boolean;
  /** raw pixel coordinates on the source master-plan raster */
  planPx: [number, number];
  verified: boolean;
  notes: string | null;
}

export interface ClusterLegendEntry {
  color: string;
  label: string;
}

export interface RawClusterData {
  cluster: string;
  source: {
    document: string;
    digitizedBy: string;
    digitizedOn: string;
    method: string;
    coverage: string;
  };
  legend: Record<string, ClusterLegendEntry>;
  units: RawUnit[];
}

export interface PlacedUnit extends RawUnit {
  /** world-space position (Three.js: x/z ground plane, y up) */
  position: { x: number; z: number };
  /** rotation around Y axis, radians */
  rotationY: number;
  footprint: { width: number; depth: number; height: number };
}

export interface RoadSegment {
  /** ordered centerline points in world space */
  points: { x: number; z: number }[];
  width: number;
  rowGroup: string;
}

export interface PlacedCluster {
  cluster: string;
  units: PlacedUnit[];
  roads: RoadSegment[];
  bounds: { minX: number; maxX: number; minZ: number; maxZ: number };
  source: RawClusterData['source'];
  legend: RawClusterData['legend'];
}

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

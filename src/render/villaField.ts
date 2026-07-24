import * as THREE from 'three';
import type { PlacedCluster, PlacedUnit } from '../data/types';
import { createVillaMaterial, type VillaMaterialHandle } from './villaMaterial';

interface UnitEntry {
  unit: PlacedUnit;
  sizeKey: string;
  index: number;
}

export interface VillaField {
  group: THREE.Group;
  materialHandle: VillaMaterialHandle;
  getUnit(id: string): PlacedUnit | undefined;
  getTopCenter(id: string): THREE.Vector3 | undefined;
  setHighlight(id: string, value: number): void;
  clearAllHighlights(): void;
  allIds(): string[];
  update(time: number): void;
}

function footprintKey(unit: PlacedUnit): string {
  return `${Math.round(unit.footprint.width)}_${Math.round(unit.footprint.depth)}_${Math.round(unit.footprint.height)}`;
}

/**
 * Builds one InstancedMesh per distinct footprint size (one draw call per
 * size, regardless of how many thousands of villas share it) with a shared
 * neon shader material. Size buckets now come from interpolated bedroom
 * counts, not just the 4 coarse tiers, so a real 4BR townhouse gets a
 * genuinely different box than a 3BR or 5BR one — but two 4BR townhouses
 * anywhere in the cluster still share a single draw call.
 */
export function buildVillaField(cluster: PlacedCluster): VillaField {
  const group = new THREE.Group();
  const materialHandle = createVillaMaterial();

  const bySize = new Map<string, PlacedUnit[]>();
  for (const u of cluster.units) {
    const key = footprintKey(u);
    if (!bySize.has(key)) bySize.set(key, []);
    bySize.get(key)!.push(u);
  }

  const entries = new Map<string, UnitEntry>();
  const highlightAttrs = new Map<string, THREE.InstancedBufferAttribute>();

  const dummy = new THREE.Object3D();

  for (const [sizeKey, units] of bySize) {
    const footprint = units[0].footprint;
    const geometry = new THREE.BoxGeometry(footprint.width, footprint.height, footprint.depth);

    const mesh = new THREE.InstancedMesh(geometry, materialHandle.material, units.length);
    mesh.name = `villas-size-${sizeKey}`;

    const highlightArray = new Float32Array(units.length);
    const highlightAttr = new THREE.InstancedBufferAttribute(highlightArray, 1);
    highlightAttr.setUsage(THREE.DynamicDrawUsage);
    geometry.setAttribute('aHighlight', highlightAttr);
    highlightAttrs.set(sizeKey, highlightAttr);

    units.forEach((unit, index) => {
      dummy.position.set(unit.position.x, unit.footprint.height / 2, unit.position.z);
      dummy.rotation.set(0, unit.rotationY, 0);
      dummy.updateMatrix();
      mesh.setMatrixAt(index, dummy.matrix);
      entries.set(unit.id, { unit, sizeKey, index });
    });
    mesh.instanceMatrix.needsUpdate = true;

    group.add(mesh);
  }

  function setHighlight(id: string, value: number) {
    const entry = entries.get(id);
    if (!entry) return;
    const attr = highlightAttrs.get(entry.sizeKey)!;
    attr.setX(entry.index, value);
    attr.needsUpdate = true;
  }

  function clearAllHighlights() {
    for (const [sizeKey, attr] of highlightAttrs) {
      const units = bySize.get(sizeKey)!;
      for (let i = 0; i < units.length; i++) attr.setX(i, 0);
      attr.needsUpdate = true;
    }
  }

  return {
    group,
    materialHandle,
    getUnit: (id) => entries.get(id)?.unit,
    getTopCenter: (id) => {
      const entry = entries.get(id);
      if (!entry) return undefined;
      return new THREE.Vector3(
        entry.unit.position.x,
        entry.unit.footprint.height,
        entry.unit.position.z,
      );
    },
    setHighlight,
    clearAllHighlights,
    allIds: () => Array.from(entries.keys()),
    update: (time: number) => materialHandle.update(time),
  };
}

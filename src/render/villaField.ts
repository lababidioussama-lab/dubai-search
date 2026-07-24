import * as THREE from 'three';
import type { PlacedCluster, PlacedUnit, TierId } from '../data/types';
import { createVillaMaterial, type VillaMaterialHandle } from './villaMaterial';

interface UnitEntry {
  unit: PlacedUnit;
  tier: TierId;
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

/**
 * Builds one InstancedMesh per tier (one draw call per tier, regardless of how
 * many thousands of villas share that tier) with a shared neon shader material.
 */
export function buildVillaField(cluster: PlacedCluster): VillaField {
  const group = new THREE.Group();
  const materialHandle = createVillaMaterial();

  const byTier = new Map<TierId, PlacedUnit[]>();
  for (const u of cluster.units) {
    if (!byTier.has(u.tier)) byTier.set(u.tier, []);
    byTier.get(u.tier)!.push(u);
  }

  const entries = new Map<string, UnitEntry>();
  const meshes = new Map<TierId, THREE.InstancedMesh>();
  const highlightAttrs = new Map<TierId, THREE.InstancedBufferAttribute>();

  const dummy = new THREE.Object3D();

  for (const [tier, units] of byTier) {
    const footprint = units[0].footprint;
    const geometry = new THREE.BoxGeometry(footprint.width, footprint.height, footprint.depth);

    const mesh = new THREE.InstancedMesh(geometry, materialHandle.material, units.length);
    mesh.name = `villas-tier-${tier}`;

    const highlightArray = new Float32Array(units.length);
    const highlightAttr = new THREE.InstancedBufferAttribute(highlightArray, 1);
    highlightAttr.setUsage(THREE.DynamicDrawUsage);
    geometry.setAttribute('aHighlight', highlightAttr);
    highlightAttrs.set(tier, highlightAttr);

    units.forEach((unit, index) => {
      dummy.position.set(unit.position.x, unit.footprint.height / 2, unit.position.z);
      dummy.rotation.set(0, unit.rotationY, 0);
      dummy.updateMatrix();
      mesh.setMatrixAt(index, dummy.matrix);
      entries.set(unit.id, { unit, tier, index });
    });
    mesh.instanceMatrix.needsUpdate = true;

    meshes.set(tier, mesh);
    group.add(mesh);
  }

  function setHighlight(id: string, value: number) {
    const entry = entries.get(id);
    if (!entry) return;
    const attr = highlightAttrs.get(entry.tier)!;
    attr.setX(entry.index, value);
    attr.needsUpdate = true;
  }

  function clearAllHighlights() {
    for (const [tier, attr] of highlightAttrs) {
      const units = byTier.get(tier)!;
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

import * as THREE from 'three';
import { loadCluster } from './data/loadCluster';
import { TIERS } from './data/types';
import { buildVillaField } from './render/villaField';
import { buildGround } from './render/ground';
import { createSceneRig } from './render/scene';
import { SearchController } from './ui/search';
import { Callout } from './ui/callout';

async function main() {
  const canvas = document.getElementById('scene-canvas') as HTMLCanvasElement;
  const hud = document.getElementById('hud') as HTMLElement;
  const loadingEl = document.getElementById('loading') as HTMLElement;
  const calloutRoot = document.getElementById('callout') as HTMLElement;
  const coverageCount = document.getElementById('coverage-count') as HTMLElement;

  const rig = createSceneRig(canvas);
  const cluster = await loadCluster('portofino');

  const villaField = buildVillaField(cluster);
  rig.scene.add(villaField.group);
  rig.scene.add(buildGround(cluster));

  const verifiedUnits = cluster.units.filter((u) => u.verified);
  coverageCount.textContent = String(verifiedUnits.length);

  // default framing: whole cluster in view
  const center = new THREE.Vector3(
    (cluster.bounds.minX + cluster.bounds.maxX) / 2,
    0,
    (cluster.bounds.minZ + cluster.bounds.maxZ) / 2,
  );
  const spanX = cluster.bounds.maxX - cluster.bounds.minX;
  const spanZ = cluster.bounds.maxZ - cluster.bounds.minZ;
  const overviewDistance = Math.max(spanX, spanZ) * 1.05;
  rig.cameraRig.frame(center, overviewDistance);

  const callout = new Callout(calloutRoot, canvas);

  let activeId: string | null = null;
  function clearSelection() {
    if (activeId) villaField.setHighlight(activeId, 0);
    activeId = null;
    callout.hide();
  }

  function selectUnit(id: string) {
    const unit = villaField.getUnit(id);
    const top = villaField.getTopCenter(id);
    if (!unit || !top) return;
    if (activeId && activeId !== id) villaField.setHighlight(activeId, 0);
    activeId = id;
    villaField.setHighlight(id, 1);

    const tierLabel = TIERS[unit.tier].label;
    callout.show(id, `${unit.typeCode} · ${tierLabel}`, top, rig.cameraRig.camera);

    const focusDistance = Math.max(unit.footprint.width, unit.footprint.depth) * 5.5;
    rig.cameraRig.flyTo(top.clone().setY(unit.footprint.height * 0.3), focusDistance, 1.0);
  }

  const searchableUnits = cluster.units.map((u) => ({
    id: u.id,
    tierLabel: TIERS[u.tier].label,
    verified: u.verified,
  }));

  new SearchController(hud, searchableUnits, {
    onSelect: selectUnit,
    onClear: clearSelection,
  });

  loadingEl.classList.add('hidden');

  const clock = new THREE.Clock();
  function animate() {
    requestAnimationFrame(animate);
    const t = clock.getElapsedTime();
    villaField.update(t);
    rig.cameraRig.update();
    callout.update();
    rig.composer.render();
  }
  animate();
}

main().catch((err) => {
  console.error(err);
  const loadingEl = document.getElementById('loading');
  if (loadingEl) {
    loadingEl.textContent = 'Failed to load map — see console for details.';
  }
});

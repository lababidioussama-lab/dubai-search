import * as THREE from 'three';
import type { PlacedCluster, RoadSegment } from '../data/types';

const GROUND_PADDING = 90;

export function buildGround(cluster: PlacedCluster): THREE.Group {
  const group = new THREE.Group();
  group.name = 'ground';

  const { minX, maxX, minZ, maxZ } = cluster.bounds;
  const width = maxX - minX + GROUND_PADDING * 2;
  const depth = maxZ - minZ + GROUND_PADDING * 2;
  const centerX = (minX + maxX) / 2;
  const centerZ = (minZ + maxZ) / 2;

  const groundGeo = new THREE.PlaneGeometry(width, depth, 1, 1);
  const groundMat = new THREE.MeshStandardMaterial({
    color: new THREE.Color('#0a0a0c'),
    roughness: 1,
    metalness: 0,
  });
  const groundMesh = new THREE.Mesh(groundGeo, groundMat);
  groundMesh.rotation.x = -Math.PI / 2;
  groundMesh.position.set(centerX, -0.5, centerZ);
  groundMesh.receiveShadow = false;
  group.add(groundMesh);

  for (const road of cluster.roads) {
    group.add(buildRoadRibbon(road));
  }

  return group;
}

function buildRoadRibbon(road: RoadSegment): THREE.Group {
  const roadGroup = new THREE.Group();
  roadGroup.name = `road-${road.rowGroup}`;
  const { points, width } = road;
  if (points.length < 2) return roadGroup;

  // build a ribbon strip by offsetting each point perpendicular to its local tangent
  const left: THREE.Vector2[] = [];
  const right: THREE.Vector2[] = [];
  for (let i = 0; i < points.length; i++) {
    const prev = points[Math.max(i - 1, 0)];
    const next = points[Math.min(i + 1, points.length - 1)];
    const tx = next.x - prev.x;
    const tz = next.z - prev.z;
    const len = Math.hypot(tx, tz) || 1;
    const nx = -tz / len;
    const nz = tx / len;
    const p = points[i];
    left.push(new THREE.Vector2(p.x + (nx * width) / 2, p.z + (nz * width) / 2));
    right.push(new THREE.Vector2(p.x - (nx * width) / 2, p.z - (nz * width) / 2));
  }

  const positions: number[] = [];
  const uvs: number[] = [];
  const indices: number[] = [];
  for (let i = 0; i < points.length; i++) {
    positions.push(left[i].x, 0, left[i].y, right[i].x, 0, right[i].y);
    uvs.push(0, i / (points.length - 1), 1, i / (points.length - 1));
  }
  for (let i = 0; i < points.length - 1; i++) {
    const a = i * 2;
    const b = i * 2 + 1;
    const c = i * 2 + 2;
    const d = i * 2 + 3;
    indices.push(a, b, c, b, d, c);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();

  const material = new THREE.MeshStandardMaterial({
    color: new THREE.Color('#1c1c20'),
    roughness: 0.95,
    metalness: 0,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.y = -0.35;
  roadGroup.add(mesh);

  // dashed centerline
  const centerPositions: number[] = [];
  for (const p of points) centerPositions.push(p.x, -0.3, p.z);
  const lineGeo = new THREE.BufferGeometry();
  lineGeo.setAttribute('position', new THREE.Float32BufferAttribute(centerPositions, 3));
  const lineMat = new THREE.LineDashedMaterial({
    color: new THREE.Color('rgb(255, 20, 40)'),
    dashSize: width * 0.35,
    gapSize: width * 0.35,
    linewidth: 1,
  });
  const line = new THREE.Line(lineGeo, lineMat);
  line.computeLineDistances();
  roadGroup.add(line);

  return roadGroup;
}

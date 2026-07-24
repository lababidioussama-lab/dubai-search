import * as THREE from 'three';

/**
 * Procedural neon-edge material for villa blocks.
 *
 * Faithful GPU translation of the approved CSS prototype's "border + multi-layer
 * glow" technique: a UV-space border stripe on every box face is lit with a red
 * core + hotter red-hot filament, left as pure emissive red (never whitened —
 * that's what caused the earlier pink regression) so UnrealBloomPass blooms it
 * into a soft halo. Top/side faces stay neutral charcoal, never colour-tinted by
 * unit type. Instanced: one draw call per tier, driven entirely by per-instance
 * attributes so it scales to thousands of blocks.
 */

const vertexShader = /* glsl */ `
  attribute float aHighlight; // 0 = default, 1 = active/searched
  attribute vec3 aInstanceColor; // unused placeholder for future per-instance tint

  varying vec2 vUv;
  varying float vFaceIsTop;
  varying float vFaceIsSide;
  varying float vHighlight;

  void main() {
    vUv = uv;
    vHighlight = aHighlight;

    vec3 transformed = vec3(position);

    #ifdef USE_INSTANCING
      transformed = (instanceMatrix * vec4(transformed, 1.0)).xyz;
    #endif

    vec3 objectNormal = vec3(normal);
    #ifdef USE_INSTANCING
      mat3 instanceNormalMatrix = mat3(instanceMatrix);
      objectNormal = instanceNormalMatrix * objectNormal;
    #endif
    vec3 worldNormal = normalize(mat3(modelMatrix) * objectNormal);

    vFaceIsTop = step(0.5, worldNormal.y);
    vFaceIsSide = 1.0 - vFaceIsTop;

    vec4 mvPosition = viewMatrix * modelMatrix * vec4(transformed, 1.0);
    gl_Position = projectionMatrix * mvPosition;
  }
`;

const fragmentShader = /* glsl */ `
  precision highp float;

  uniform vec3 uTopColor;
  uniform vec3 uSideColor;
  uniform vec3 uNeonCore;
  uniform vec3 uNeonHot;
  uniform vec3 uActiveFillNear;
  uniform vec3 uActiveFillFar;
  uniform float uBorderWidth;
  uniform float uHotWidth;
  uniform float uTime;

  varying vec2 vUv;
  varying float vFaceIsTop;
  varying float vFaceIsSide;
  varying float vHighlight;

  void main() {
    vec3 base = mix(uSideColor, uTopColor, vFaceIsTop);

    // active fill: deep red gradient across the face instead of neutral charcoal
    vec3 activeFill = mix(uActiveFillFar, uActiveFillNear, vUv.y);
    base = mix(base, activeFill, vHighlight);

    float edgeDist = min(min(vUv.x, 1.0 - vUv.x), min(vUv.y, 1.0 - vUv.y));

    float borderMask = 1.0 - smoothstep(uBorderWidth * 0.7, uBorderWidth, edgeDist);
    float hotMask = 1.0 - smoothstep(uHotWidth * 0.5, uHotWidth, edgeDist);

    vec3 edgeColor = mix(uNeonCore, uNeonHot, hotMask);

    // base edge is a single, bounded saturation (bloom alone gives it the halo);
    // only the highlighted/searched unit gets a small additive HDR kick that pulses
    float pulse = 0.5 + 0.5 * sin(uTime * 4.2);
    float activeBoost = vHighlight * mix(0.12, 0.4, pulse);

    vec3 color = mix(base, edgeColor, borderMask);
    color += edgeColor * borderMask * activeBoost;

    gl_FragColor = vec4(color, 1.0);
  }
`;

export interface VillaMaterialHandle {
  material: THREE.ShaderMaterial;
  update(time: number): void;
}

export function createVillaMaterial(): VillaMaterialHandle {
  const material = new THREE.ShaderMaterial({
    vertexShader,
    fragmentShader,
    uniforms: {
      uTopColor: { value: new THREE.Color('#262626') },
      uSideColor: { value: new THREE.Color('#121216') },
      uNeonCore: { value: new THREE.Color('#ff0033') },
      uNeonHot: { value: new THREE.Color('#ff2020') },
      uActiveFillNear: { value: new THREE.Color('#4a0510') },
      uActiveFillFar: { value: new THREE.Color('#200308') },
      uBorderWidth: { value: 0.07 },
      uHotWidth: { value: 0.018 },
      uTime: { value: 0 },
    },
  });

  return {
    material,
    update(time: number) {
      material.uniforms.uTime.value = time;
    },
  };
}

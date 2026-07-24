import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { CameraRig } from './cameraRig';

export interface SceneRig {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  cameraRig: CameraRig;
  composer: EffectComposer;
  bloomPass: UnrealBloomPass;
  onResize(): void;
}

export function createSceneRig(canvas: HTMLCanvasElement): SceneRig {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setClearColor(new THREE.Color('#050505'), 1);
  // ACES rolloff prevents the additive bloom on near-saturated red edges from
  // hard-clipping per-channel, which is what was shifting the neon toward pink.
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x050505, 400, 1400);

  const cameraRig = new CameraRig(canvas);

  const ambient = new THREE.AmbientLight(0x141416, 0.55);
  scene.add(ambient);
  const key = new THREE.DirectionalLight(0x201819, 0.35);
  key.position.set(120, 260, 120);
  scene.add(key);

  const composer = new EffectComposer(renderer);
  const renderPass = new RenderPass(scene, cameraRig.camera);
  composer.addPass(renderPass);

  const bloomPass = new UnrealBloomPass(
    new THREE.Vector2(window.innerWidth, window.innerHeight),
    0.85, // strength
    0.4, // radius
    0.25, // threshold
  );
  composer.addPass(bloomPass);
  composer.addPass(new OutputPass());

  function onResize() {
    const w = window.innerWidth;
    const h = window.innerHeight;
    renderer.setSize(w, h);
    composer.setSize(w, h);
    cameraRig.resize(w, h);
    bloomPass.setSize(w, h);
  }
  window.addEventListener('resize', onResize);

  return { renderer, scene, cameraRig, composer, bloomPass, onResize };
}

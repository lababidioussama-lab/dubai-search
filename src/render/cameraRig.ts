import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

// Isometric-ish oblique angle: elevation chosen so front faces read as ~80% the
// screen area of top faces (matches the approved CSS rotateX(50)/rotateZ(35) feel).
const AZIMUTH = THREE.MathUtils.degToRad(40);
const ELEVATION = THREE.MathUtils.degToRad(36);

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

export class CameraRig {
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;

  private tweenStart = 0;
  private tweenDuration = 0;
  private fromTarget = new THREE.Vector3();
  private toTarget = new THREE.Vector3();
  private fromDistance = 0;
  private toDistance = 0;
  private tweening = false;

  constructor(canvas: HTMLCanvasElement) {
    this.camera = new THREE.PerspectiveCamera(38, window.innerWidth / window.innerHeight, 1, 5000);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.minPolarAngle = ELEVATION * 0.35;
    this.controls.maxPolarAngle = ELEVATION * 1.7;
    this.controls.minDistance = 20;
    this.controls.maxDistance = 900;
    this.controls.enablePan = true;
    this.controls.screenSpacePanning = false;
  }

  frame(target: THREE.Vector3, distance: number) {
    const dir = new THREE.Vector3(
      Math.cos(ELEVATION) * Math.sin(AZIMUTH),
      Math.sin(ELEVATION),
      Math.cos(ELEVATION) * Math.cos(AZIMUTH),
    );
    this.camera.position.copy(target).addScaledVector(dir, distance);
    this.controls.target.copy(target);
    this.camera.lookAt(target);
    this.controls.update();
  }

  flyTo(target: THREE.Vector3, distance: number, duration = 1.0) {
    this.fromTarget.copy(this.controls.target);
    this.toTarget.copy(target);
    this.fromDistance = this.camera.position.distanceTo(this.controls.target);
    this.toDistance = distance;
    this.tweenStart = performance.now();
    this.tweenDuration = duration * 1000;
    this.tweening = true;
    this.controls.enabled = false;
  }

  update() {
    if (this.tweening) {
      const elapsed = performance.now() - this.tweenStart;
      const t = Math.min(elapsed / this.tweenDuration, 1);
      const eased = easeInOutCubic(t);
      const target = new THREE.Vector3().lerpVectors(this.fromTarget, this.toTarget, eased);
      const distance = THREE.MathUtils.lerp(this.fromDistance, this.toDistance, eased);
      this.frame(target, distance);
      if (t >= 1) {
        this.tweening = false;
        this.controls.enabled = true;
      }
    } else {
      this.controls.update();
    }
  }

  resize(width: number, height: number) {
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }
}

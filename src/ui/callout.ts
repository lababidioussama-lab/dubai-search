import * as THREE from 'three';

export class Callout {
  private el: HTMLElement;
  private idEl: HTMLElement;
  private metaEl: HTMLElement;
  private worldPos: THREE.Vector3 | null = null;
  private camera: THREE.Camera | null = null;
  private domEl: HTMLElement;

  constructor(root: HTMLElement, domEl: HTMLElement) {
    this.el = root;
    this.idEl = root.querySelector('#callout-id')!;
    this.metaEl = root.querySelector('#callout-meta')!;
    this.domEl = domEl;
  }

  show(id: string, meta: string, worldPos: THREE.Vector3, camera: THREE.Camera) {
    this.idEl.textContent = id;
    this.metaEl.textContent = meta;
    this.worldPos = worldPos;
    this.camera = camera;
    this.el.classList.remove('hidden');
  }

  hide() {
    this.el.classList.add('hidden');
    this.worldPos = null;
  }

  update() {
    if (!this.worldPos || !this.camera) return;
    const projected = this.worldPos.clone().project(this.camera);
    const rect = this.domEl.getBoundingClientRect();
    const x = ((projected.x + 1) / 2) * rect.width;
    const y = ((1 - projected.y) / 2) * rect.height;

    if (projected.z > 1) {
      this.el.style.transform = 'translate(-9999px, -9999px)';
      return;
    }
    this.el.style.transform = `translate(${x}px, ${y}px)`;
  }
}

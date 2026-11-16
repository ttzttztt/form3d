import * as THREE from 'three';
export class PartInspection {
  private entries: {
    mesh: THREE.Mesh;
    position: THREE.Vector3;
    center: THREE.Vector3;
    group: string;
  }[] = [];
  private selected = new Set<string>();
  private hidden = new Set<string>();
  private solo = false;
  private amount = 0;
  private center = new THREE.Vector3();
  private radius = 1;
  constructor(
    model: THREE.Object3D,
    private dirty: () => void,
  ) {
    model.updateMatrixWorld(true);
    const whole = new THREE.Box3(),
      groups = new Map<string, THREE.Box3>();
    model.traverse((o) => {
      if (!(o instanceof THREE.Mesh) || !o.userData.formPartId) return;
      const bounds = new THREE.Box3(),
        p = o.geometry.getAttribute('position'),
        idx = o.geometry.index,
        v = new THREE.Vector3();
      for (let i = 0; i < (idx?.count ?? p.count); i++)
        bounds.expandByPoint(
          v.fromBufferAttribute(p, idx ? idx.getX(i) : i).applyMatrix4(o.matrixWorld),
        );
      const group = o.userData.formGroupId || o.userData.formPartId;
      const b = groups.get(group) ?? new THREE.Box3();
      b.union(bounds);
      groups.set(group, b);
      whole.union(bounds);
      this.entries.push({
        mesh: o,
        position: o.position.clone(),
        center: bounds.getCenter(new THREE.Vector3()),
        group,
      });
    });
    for (const e of this.entries) e.center = groups.get(e.group)!.getCenter(new THREE.Vector3());
    whole.getCenter(this.center);
    this.radius = whole.getSize(new THREE.Vector3()).length();
  }
  select(ids: string[]) {
    this.selected = new Set(ids);
    this.apply();
  }
  showAll() {
    this.hidden.clear();
    this.solo = false;
    this.amount = 0;
    this.apply();
  }
  isolate() {
    this.solo = !this.solo;
    this.apply();
  }
  hideSelected() {
    this.selected.forEach((id) => this.hidden.add(id));
    this.apply();
  }
  explode(amount: number) {
    this.amount = amount;
    this.apply();
  }
  private apply() {
    for (const e of this.entries) {
      e.mesh.visible =
        !this.hidden.has(e.mesh.userData.formPartId) &&
        (!this.solo || this.selected.has(e.mesh.userData.formPartId));
      const delta = e.center.clone().sub(this.center);
      if (delta.lengthSq() < 1e-10) delta.set(0, 1, 0);
      delta.normalize().multiplyScalar(this.amount * this.radius * 0.4);
      const parent = e.mesh.parent;
      const local = parent
        ? delta.applyMatrix3(
            new THREE.Matrix3().setFromMatrix4(parent.matrixWorld.clone().invert()),
          )
        : delta;
      e.mesh.position.copy(e.position).add(local);
    }
    this.dirty();
  }
  dispose() {
    this.entries.forEach((e) => {
      e.mesh.visible = true;
      e.mesh.position.copy(e.position);
    });
  }
}

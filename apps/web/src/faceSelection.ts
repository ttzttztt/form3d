import * as THREE from 'three';
import { surfaceVisibility } from './selectionVisibility';
export interface FaceSelection {
  part_id: string;
  faces: number[];
}
export type FaceMap = Record<string, number[]>;

export function screenFaces(
  model: THREE.Object3D,
  camera: THREE.Camera,
  width: number,
  height: number,
  points: { x: number; y: number }[],
  box: boolean,
  radius: number,
  visibleOnly = true,
): FaceMap {
  const result: FaceMap = {},
    a = new THREE.Vector3(),
    b = new THREE.Vector3(),
    c = new THREE.Vector3(),
    world = new THREE.Vector3(),
    center = new THREE.Vector3();
  if (!points.length) return result;
  model.updateMatrixWorld(true);
  camera.updateMatrixWorld(true);
  const visible = visibleOnly ? surfaceVisibility(model, camera) : undefined;
  const first = points[0],
    last = points[points.length - 1];
  const minX = Math.min(...points.map((p) => p.x)) - (box ? 0 : radius),
    maxX = Math.max(...points.map((p) => p.x)) + (box ? 0 : radius);
  const minY = Math.min(...points.map((p) => p.y)) - (box ? 0 : radius),
    maxY = Math.max(...points.map((p) => p.y)) + (box ? 0 : radius);
  model.traverseVisible((child) => {
    if (!(child instanceof THREE.Mesh) || !child.userData.formPartId) return;
    const position = child.geometry.getAttribute('position'),
      index = child.geometry.index,
      faces: number[] = [];
    for (let face = 0; face < Math.floor((index?.count ?? position.count) / 3); face++) {
      a.fromBufferAttribute(position, index ? index.getX(face * 3) : face * 3);
      b.fromBufferAttribute(position, index ? index.getX(face * 3 + 1) : face * 3 + 1);
      c.fromBufferAttribute(position, index ? index.getX(face * 3 + 2) : face * 3 + 2);
      world
        .copy(a)
        .add(b)
        .add(c)
        .multiplyScalar(1 / 3)
        .applyMatrix4(child.matrixWorld);
      center.copy(world).project(camera);
      if (center.z < -1 || center.z > 1) continue;
      const x = ((center.x + 1) * width) / 2,
        y = ((1 - center.y) * height) / 2;
      if (x < minX || x > maxX || y < minY || y > maxY) continue;
      const inside = box
        ? x >= Math.min(first.x, last.x) &&
          x <= Math.max(first.x, last.x) &&
          y >= Math.min(first.y, last.y) &&
          y <= Math.max(first.y, last.y)
        : points.some((p) => (p.x - x) ** 2 + (p.y - y) ** 2 <= radius ** 2);
      if (inside && (!visible || visible(world, center))) faces.push(face);
    }
    if (faces.length) result[child.userData.formPartId] = faces;
  });
  return result;
}

export function combineFaces(old: FaceMap, fresh: FaceMap, subtract: boolean): FaceMap {
  const next: FaceMap = { ...old };
  for (const [id, faces] of Object.entries(fresh)) {
    const set = new Set(next[id] || []);
    for (const face of faces) {
      if (subtract) set.delete(face);
      else set.add(face);
    }
    if (set.size) next[id] = [...set].sort((a, b) => a - b);
    else delete next[id];
  }
  return next;
}

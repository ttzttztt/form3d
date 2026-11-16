import * as THREE from 'three';
import { topology } from './pointSelection';

export function refineSelection(
  mesh: THREE.Mesh,
  input: Uint8Array,
  positive: Set<number>,
  negative: Set<number>,
  evidence: Uint8Array,
) {
  const data = topology(mesh.geometry),
    next = input.slice();
  let removed = 0,
    filled = 0;
  for (let face = 0; face < data.count; face++) {
    if (positive.has(face) || negative.has(face)) continue;
    const neighbors = [0, 1, 2].map((k) => data.adjacent[face * 3 + k]);
    const same = neighbors.filter((n) => n >= 0 && input[n]).length;
    if (input[face] && same <= 1 && neighbors.every((n) => n >= 0)) {
      next[face] = 0;
      removed++;
    } else if (!input[face] && same === 3 && evidence[face] > 0) {
      const normal = new THREE.Vector3().fromArray(data.normals, face * 3);
      if (
        neighbors.every(
          (n) =>
            normal.dot(new THREE.Vector3().fromArray(data.normals, n * 3)) > Math.cos(Math.PI / 4),
        )
      ) {
        next[face] = 1;
        filled++;
      }
    }
  }
  positive.forEach((f) => (next[f] = 1));
  negative.forEach((f) => (next[f] = 0));
  return { mask: next, removed, filled };
}

export function selectionBoundary(mesh: THREE.Mesh, faces: number[]) {
  const data = topology(mesh.geometry),
    selected = new Set(faces),
    p = mesh.geometry.getAttribute('position'),
    idx = mesh.geometry.index,
    lines: number[] = [];
  for (const f of faces)
    for (let k = 0; k < 3; k++)
      if (data.adjacent[f * 3 + k] < 0 || !selected.has(data.adjacent[f * 3 + k])) {
        if (lines.length >= 300000) return lines;
        for (const slot of [k, (k + 1) % 3]) {
          const v = new THREE.Vector3()
            .fromBufferAttribute(p, idx ? idx.getX(f * 3 + slot) : f * 3 + slot)
            .applyMatrix4(mesh.matrixWorld);
          lines.push(v.x, v.y, v.z);
        }
      }
  return lines;
}

const seamCache = new WeakMap<THREE.BufferGeometry, { lines: Float32Array; truncated: boolean }>();
export function uvSeams(geometry: THREE.BufferGeometry) {
  const old = seamCache.get(geometry);
  if (old) return old;
  const p = geometry.getAttribute('position'),
    uv = geometry.getAttribute('uv'),
    index = geometry.index;
  if (!uv) return undefined;
  const box = new THREE.Box3().setFromBufferAttribute(p as THREE.BufferAttribute),
    tolerance = Math.max(box.getSize(new THREE.Vector3()).length() * 1e-7, 1e-10),
    weld = new Uint32Array(p.count),
    ids = new Map<string, number>();
  for (let i = 0; i < p.count; i++) {
    const key = [p.getX(i), p.getY(i), p.getZ(i)].map((v) => Math.round(v / tolerance)).join(',');
    let id = ids.get(key);
    if (id === undefined) {
      id = ids.size;
      ids.set(key, id);
    }
    weld[i] = id;
  }
  const owners = new Map<
    number,
    { a: number; b: number; u: number[]; seam: boolean; count: number }
  >();
  for (let i = 0; i < (index?.count ?? p.count); i += 3)
    for (let k = 0; k < 3; k++) {
      let a = index ? index.getX(i + k) : i + k,
        b = index ? index.getX(i + ((k + 1) % 3)) : i + ((k + 1) % 3);
      if (weld[a] === weld[b]) continue;
      if (weld[a] > weld[b]) [a, b] = [b, a];
      const key = weld[a] * ids.size + weld[b],
        coords = [uv.getX(a), uv.getY(a), uv.getX(b), uv.getY(b)],
        previous = owners.get(key);
      if (previous) {
        previous.count++;
        previous.seam ||= coords.some((v, k) => Math.abs(v - previous.u[k]) > 1e-5);
      } else owners.set(key, { a, b, u: coords, seam: false, count: 1 });
    }
  const lines: number[] = [];
  let truncated = false;
  for (const edge of owners.values())
    if (edge.seam || edge.count === 1) {
      if (lines.length >= 300000) {
        truncated = true;
        break;
      }
      for (const i of [edge.a, edge.b]) lines.push(p.getX(i), p.getY(i), p.getZ(i));
    }
  const result = { lines: new Float32Array(lines), truncated };
  seamCache.set(geometry, result);
  return result;
}

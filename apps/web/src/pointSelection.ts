import * as THREE from 'three';
import type { FaceMap } from './faceSelection';

export type SelectionRange = 'tight' | 'normal' | 'wide';
export interface PointSelection {
  kind: 'component' | 'plane';
  faces: FaceMap;
  count: number;
  message: string;
}
interface Topology {
  adjacent: Int32Array;
  centers: Float64Array;
  normals: Float32Array;
  areas: Float64Array;
  components: Int32Array;
  componentSizes: number[];
  count: number;
}
const cache = new WeakMap<THREE.BufferGeometry, Topology>();
const MAX_FACES = 1_000_000,
  MAX_SELECTION = 500_000;

export function topology(geometry: THREE.BufferGeometry): Topology {
  const cached = cache.get(geometry);
  if (cached) return cached;
  const positions = geometry.getAttribute('position'),
    index = geometry.index;
  const count = Math.floor((index?.count ?? positions.count) / 3);
  if (!count || count > MAX_FACES)
    throw new Error('当前网格太大或没有可用三角面，请先减面或使用涂抹选择。');
  const a = new THREE.Vector3(),
    b = new THREE.Vector3(),
    c = new THREE.Vector3(),
    normal = new THREE.Vector3(),
    bounds = new THREE.Box3();
  // Only referenced vertices affect the weld tolerance after earlier face splits.
  for (let i = 0; i < count * 3; i++)
    bounds.expandByPoint(a.fromBufferAttribute(positions, index ? index.getX(i) : i));
  const tolerance = Math.max(bounds.getSize(a).length() * 1e-7, 1e-10),
    weld = new Uint32Array(positions.count),
    welded = new Map<string, number>();
  for (let i = 0; i < positions.count; i++) {
    a.fromBufferAttribute(positions, i);
    const key = `${Math.round(a.x / tolerance)},${Math.round(a.y / tolerance)},${Math.round(a.z / tolerance)}`;
    let id = welded.get(key);
    if (id === undefined) {
      id = welded.size;
      welded.set(key, id);
    }
    weld[i] = id;
  }
  const vertexCount = welded.size,
    adjacent = new Int32Array(count * 3).fill(-1),
    edges = new Map<number, number>();
  const centers = new Float64Array(count * 3),
    normals = new Float32Array(count * 3),
    areas = new Float64Array(count);
  for (let face = 0; face < count; face++) {
    const ia = index ? index.getX(face * 3) : face * 3,
      ib = index ? index.getX(face * 3 + 1) : face * 3 + 1,
      ic = index ? index.getX(face * 3 + 2) : face * 3 + 2;
    a.fromBufferAttribute(positions, ia);
    b.fromBufferAttribute(positions, ib);
    c.fromBufferAttribute(positions, ic);
    centers.set([(a.x + b.x + c.x) / 3, (a.y + b.y + c.y) / 3, (a.z + b.z + c.z) / 3], face * 3);
    normal.subVectors(b, a).cross(c.sub(a));
    areas[face] = normal.length() / 2;
    normal.normalize();
    normals.set(normal.toArray(), face * 3);
    const vertices = [weld[ia], weld[ib], weld[ic]];
    for (let k = 0; k < 3; k++) {
      const lo = Math.min(vertices[k], vertices[(k + 1) % 3]),
        hi = Math.max(vertices[k], vertices[(k + 1) % 3]);
      if (lo === hi) continue;
      const key = lo * vertexCount + hi,
        owner = edges.get(key),
        slot = face * 3 + k;
      if (owner === undefined) {
        edges.set(key, slot);
        continue;
      }
      if (owner < 0) continue;
      if (adjacent[owner] >= 0) {
        // Non-manifold edges are barriers, not evidence of part membership.
        const partner = adjacent[owner];
        for (let j = 0; j < 3; j++)
          if (adjacent[partner * 3 + j] === Math.floor(owner / 3)) adjacent[partner * 3 + j] = -1;
        adjacent[owner] = -1;
        edges.set(key, -1);
        continue;
      }
      adjacent[slot] = Math.floor(owner / 3);
      adjacent[owner] = face;
    }
  }
  const components = new Int32Array(count).fill(-1),
    componentSizes: number[] = [],
    queue = new Int32Array(count);
  for (let seed = 0; seed < count; seed++) {
    if (components[seed] >= 0) continue;
    const id = componentSizes.length;
    let head = 0,
      tail = 1;
    queue[0] = seed;
    components[seed] = id;
    while (head < tail) {
      const face = queue[head++];
      for (let k = 0; k < 3; k++) {
        const next = adjacent[face * 3 + k];
        if (next >= 0 && components[next] < 0) {
          components[next] = id;
          queue[tail++] = next;
        }
      }
    }
    componentSizes.push(tail);
  }
  const result = { adjacent, centers, normals, areas, components, componentSizes, count };
  cache.set(geometry, result);
  return result;
}

/** Geometric region proposal, explicitly not a semantic part classifier. */
export function pointSelection(
  mesh: THREE.Mesh,
  seed: number,
  range: SelectionRange = 'normal',
): PointSelection {
  const identity = mesh.userData.formPartId;
  if (!identity || !Number.isInteger(seed)) throw new Error('请点击模型表面。');
  mesh.updateWorldMatrix(true, false);
  const data = topology(mesh.geometry);
  if (seed < 0 || seed >= data.count) throw new Error('点击位置已失效，请重新点击模型。');
  const component = data.components[seed],
    componentCount = data.componentSizes[component];
  if (
    componentCount >= 4 &&
    componentCount < data.count * 0.85 &&
    componentCount <= MAX_SELECTION
  ) {
    const faces: number[] = [];
    for (let i = 0; i < data.count; i++) if (data.components[i] === component) faces.push(i);
    return {
      kind: 'component',
      faces: { [identity]: faces },
      count: faces.length,
      message: '选中了一块独立连通区域，包含它的背面。旋转检查后，可命名保存为部件。',
    };
  }
  const normalMatrix = new THREE.Matrix3().getNormalMatrix(mesh.matrixWorld),
    seedNormal = new THREE.Vector3()
      .fromArray(data.normals, seed * 3)
      .applyMatrix3(normalMatrix)
      .normalize();
  if (seedNormal.lengthSq() < 0.5) throw new Error('这个位置的表面退化，请换个位置点击。');
  const origin = new THREE.Vector3()
      .fromArray(data.centers, seed * 3)
      .applyMatrix4(mesh.matrixWorld),
    point = new THREE.Vector3(),
    normal = new THREE.Vector3(),
    bounds = new THREE.Box3();
  let componentArea = 0;
  for (let i = 0; i < data.count; i++)
    if (data.components[i] === component) {
      bounds.expandByPoint(point.fromArray(data.centers, i * 3).applyMatrix4(mesh.matrixWorld));
      componentArea += data.areas[i];
    }
  const diagonal = bounds.getSize(point).length();
  const settings = {
    tight: { angle: 14, distance: 0.002 },
    normal: { angle: 24, distance: 0.004 },
    wide: { angle: 34, distance: 0.008 },
  }[range];
  const cosine = Math.cos((settings.angle * Math.PI) / 180),
    distance = Math.max(diagonal * settings.distance, 1e-9);
  const seen = new Uint8Array(data.count),
    queue = new Int32Array(data.count),
    faces: number[] = [];
  let head = 0,
    tail = 1,
    area = 0;
  queue[0] = seed;
  seen[seed] = 1;
  const chosenBounds = new THREE.Box3();
  while (head < tail) {
    const face = queue[head++];
    normal
      .fromArray(data.normals, face * 3)
      .applyMatrix3(normalMatrix)
      .normalize();
    point.fromArray(data.centers, face * 3).applyMatrix4(mesh.matrixWorld);
    const planeDistance =
      (point.x - origin.x) * seedNormal.x +
      (point.y - origin.y) * seedNormal.y +
      (point.z - origin.z) * seedNormal.z;
    if (normal.dot(seedNormal) < cosine || Math.abs(planeDistance) > distance) continue;
    faces.push(face);
    area += data.areas[face];
    chosenBounds.expandByPoint(point);
    if (faces.length > MAX_SELECTION) throw new Error('选区过大，请缩小点选范围或先减面。');
    for (let k = 0; k < 3; k++) {
      const next = data.adjacent[face * 3 + k];
      if (next >= 0 && !seen[next]) {
        seen[next] = 1;
        queue[tail++] = next;
      }
    }
  }
  const spans = chosenBounds
    .getSize(point)
    .toArray()
    .sort((a, b) => b - a);
  if (
    faces.length < 2 ||
    area < componentArea * 0.012 ||
    spans[0] < diagonal * 0.12 ||
    spans[1] < diagonal * 0.04
  ) {
    throw new Error(
      '这里没有清晰的独立边界或连续平面，暂时无法一键选出完整部件。可换个点，或用涂抹修正。',
    );
  }
  faces.sort((a, b) => a - b);
  return {
    kind: 'plane',
    faces: { [identity]: faces },
    count: faces.length,
    message: '选中了一片连续平面，不保证包含侧边和底面。可涂抹补选，旋转检查后再保存为部件。',
  };
}

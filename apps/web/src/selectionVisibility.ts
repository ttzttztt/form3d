import * as THREE from 'three';
import { MeshBVH } from 'three-mesh-bvh';

const trees = new WeakMap<THREE.BufferGeometry, MeshBVH>();

/** Exact centroid visibility without raster resolution gaps or index reordering. */
export function surfaceVisibility(model: THREE.Object3D, camera: THREE.Camera) {
  model.updateMatrixWorld(true);
  camera.updateMatrixWorld(true);
  const meshes: { mesh: THREE.Mesh; tree: MeshBVH; inverse: THREE.Matrix4 }[] = [];
  model.traverseVisible((child) => {
    if (!(child instanceof THREE.Mesh) || !child.userData.formPartId) return;
    let tree = trees.get(child.geometry);
    if (!tree) {
      // The pinned library's types omit indirect. This flag preserves server face
      // IDs for indexed and non-indexed geometry; do not build a reordered index.
      const options = { maxLeafTris: 8, indirect: true, setBoundingBox: false };
      tree = new MeshBVH(child.geometry, options);
      trees.set(child.geometry, tree);
    }
    meshes.push({ mesh: child, tree, inverse: child.matrixWorld.clone().invert() });
  });
  const raycaster = new THREE.Raycaster(),
    pointer = new THREE.Vector2(),
    ray = new THREE.Ray(),
    point = new THREE.Vector3();
  const size = new THREE.Box3().setFromObject(model).getSize(new THREE.Vector3());
  const epsilon = Math.max(size.length() * 1e-6, 1e-8);
  return (world: THREE.Vector3, projected: THREE.Vector3) => {
    pointer.set(projected.x, projected.y);
    raycaster.setFromCamera(pointer, camera);
    const distance = raycaster.ray.origin.distanceTo(world);
    let closest = Infinity;
    for (const { mesh, tree, inverse } of meshes) {
      ray.copy(raycaster.ray).applyMatrix4(inverse);
      const hit = tree.raycastFirst(ray, THREE.DoubleSide);
      if (!hit) continue;
      point.copy(hit.point).applyMatrix4(mesh.matrixWorld);
      closest = Math.min(closest, raycaster.ray.origin.distanceTo(point));
      if (closest < distance - epsilon) return false;
    }
    return Math.abs(closest - distance) <= epsilon;
  };
}

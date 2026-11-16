import * as THREE from 'three';
import type { MaterialDraft, PreviewStatus } from './materialDraft';

/** Draft appearance only: restore originals on cancel; no GLB or job writes. */
export class MaterialPreview {
  private entries: {
    mesh: THREE.Mesh;
    material: THREE.Material | THREE.Material[];
    geometry: THREE.BufferGeometry;
  }[] = [];
  private materials: THREE.Material[] = [];
  private uvGeometries = new Map<THREE.Mesh, THREE.BufferGeometry>();
  private textures = new Map<string, { texture: THREE.Texture; ready: boolean; error: boolean }>();
  private current?: MaterialDraft;
  private disposed = false;
  private partColours = false;
  showPartColours(value: boolean) {
    this.partColours = value;
    this.apply(this.current);
  }
  constructor(
    model: THREE.Object3D,
    private dirty: () => void,
    private status: (value: PreviewStatus) => void,
  ) {
    model.traverse((child) => {
      if (child instanceof THREE.Mesh && child.userData.formPartId)
        this.entries.push({ mesh: child, material: child.material, geometry: child.geometry });
    });
  }
  private restore() {
    for (const entry of this.entries) {
      entry.mesh.material = entry.material;
      entry.mesh.geometry = entry.geometry;
    }
    this.materials.forEach((m) => m.dispose());
    this.materials = [];
  }
  private texture(slot: string, id: string) {
    const key = slot + ':' + id;
    let item = this.textures.get(key);
    if (!item) {
      const entry = { texture: new THREE.Texture(), ready: false, error: false };
      this.textures.set(key, entry);
      entry.texture = new THREE.TextureLoader().load(
        '/api/images/' + id + '/texture/' + slot,
        () => {
          if (this.disposed) {
            entry.texture.dispose();
            return;
          }
          entry.ready = true;
          this.apply(this.current);
        },
        undefined,
        () => {
          if (!this.disposed) {
            entry.error = true;
            this.apply(this.current);
          }
        },
      );
      entry.texture.flipY = false;
      entry.texture.colorSpace =
        slot === 'base_color_image' ? THREE.SRGBColorSpace : THREE.NoColorSpace;
      entry.texture.wrapS = entry.texture.wrapT = THREE.RepeatWrapping;
      item = entry;
    }
    return item;
  }
  private uv(entry: (typeof this.entries)[number], normalMap: boolean) {
    if (entry.geometry.getAttribute('uv') && (!normalMap || entry.geometry.getAttribute('tangent')))
      return entry.geometry;
    let geometry = this.uvGeometries.get(entry.mesh);
    if (!geometry) {
      geometry = entry.geometry.clone();
      if (!geometry.getAttribute('uv')) {
        const p = geometry.getAttribute('position'),
          low = [Infinity, Infinity, Infinity],
          high = [-Infinity, -Infinity, -Infinity];
        for (let i = 0; i < p.count; i++)
          for (let k = 0; k < 3; k++) {
            const value = p.getComponent(i, k);
            low[k] = Math.min(low[k], value);
            high[k] = Math.max(high[k], value);
          }
        const axes = [0, 1, 2]
          .sort((a, b) => high[a] - low[a] - (high[b] - low[b]) || a - b)
          .slice(-2);
        const uv = new Float32Array(p.count * 2);
        for (let i = 0; i < p.count; i++)
          for (let k = 0; k < 2; k++)
            uv[i * 2 + k] =
              (p.getComponent(i, axes[k]) - low[axes[k]]) /
              Math.max(high[axes[k]] - low[axes[k]], 1e-9);
        geometry.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
      }
      this.uvGeometries.set(entry.mesh, geometry);
    }
    if (normalMap && !geometry.getAttribute('tangent')) {
      // Export supplies vertex tangents; matching them avoids a flipped or
      // rotated derivative basis when the normal map has real surface detail.
      if (!geometry.index)
        geometry.setIndex(
          Array.from({ length: geometry.getAttribute('position').count }, (_, i) => i),
        );
      if (!geometry.getAttribute('normal')) geometry.computeVertexNormals();
      geometry.computeTangents();
    }
    return geometry;
  }
  apply(draft?: MaterialDraft) {
    if (this.disposed) return;
    this.current = draft;
    this.restore();
    if (!draft) {
      // A transient failed request must be retryable after the user cancels.
      for (const [key, entry] of this.textures) {
        if (entry.error) {
          entry.texture.dispose();
          this.textures.delete(key);
        }
      }
      if (this.partColours)
        for (const entry of this.entries) {
          const color = entry.mesh.userData.formSemanticColor as string | undefined;
          if (!color) continue;
          const material = new THREE.MeshStandardMaterial({ color, roughness: 0.8, metalness: 0 });
          this.materials.push(material);
          entry.mesh.material = material;
        }
      this.dirty();
      this.status('idle');
      return;
    }
    const targets = new Set(draft.part_ids),
      maps: Record<string, THREE.Texture> = {};
    let loading = false,
      error = false;
    for (const [slot, id] of Object.entries(draft.textures)) {
      if (!id) continue;
      const item = this.texture(slot, id);
      loading ||= !item.ready;
      error ||= item.error;
      if (item.ready) {
        item.texture.repeat.set(draft.uvScale, draft.uvScale);
        // Match the bundled GLTFLoader's KHR_texture_transform convention.
        item.texture.rotation = (draft.uvRotation * Math.PI) / 180;
        maps[slot] = item.texture;
      }
    }
    for (const entry of this.entries) {
      if (targets.size && !targets.has(entry.mesh.userData.formPartId)) continue;
      const originals = Array.isArray(entry.material) ? entry.material : [entry.material];
      const materials = originals.map((original) => {
        const material =
          draft.mode === 'replace' && original instanceof THREE.MeshStandardMaterial
            ? new THREE.MeshStandardMaterial({
                side: original.side,
                flatShading: original.flatShading,
              })
            : original.clone();
        this.materials.push(material);
        if (material instanceof THREE.MeshStandardMaterial) {
          material.color.set(draft.color);
          material.roughness = draft.roughness;
          material.metalness = draft.metalness;
          material.opacity = draft.opacity;
          material.transparent = draft.opacity < 1;
          material.depthWrite = draft.opacity >= 1;
          material.alphaTest = 0;
          if (draft.mode === 'replace') {
            material.alphaTest = 0;
            material.vertexColors = false;
            material.map = null;
            material.normalMap = null;
            material.roughnessMap = null;
            material.metalnessMap = null;
            material.normalScale.set(1, 1);
          }
          if (maps.base_color_image) material.map = maps.base_color_image;
          if (maps.normal_image) {
            material.normalMap = maps.normal_image;
            material.normalScale.set(1, 1);
            if (!entry.geometry.getAttribute('normal')) material.flatShading = false;
          }
          if (maps.roughness_image) {
            material.roughnessMap = maps.roughness_image;
            material.metalnessMap = null;
          }
          if (draft.opacity < 1) material.side = THREE.DoubleSide;
          material.needsUpdate = true;
        }
        return material;
      });
      entry.mesh.material = Array.isArray(entry.material) ? materials : materials[0];
      if (Object.keys(maps).length) entry.mesh.geometry = this.uv(entry, !!maps.normal_image);
    }
    this.dirty();
    this.status(error ? 'error' : loading ? 'loading' : 'ready');
  }
  dispose() {
    this.disposed = true;
    this.restore();
    this.uvGeometries.forEach((g) => g.dispose());
    this.textures.forEach((t) => t.texture.dispose());
    this.entries = [];
  }
}

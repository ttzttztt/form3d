import { build } from 'esbuild';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const bundle = await build({
  stdin: {
    contents:
      "export { MaterialPreview } from './apps/web/src/materialPreview'; export * as THREE from 'three';",
    resolveDir: process.cwd(),
    loader: 'ts',
  },
  bundle: true,
  platform: 'node',
  format: 'esm',
  write: false,
});
const { MaterialPreview, THREE } = await import(
  'data:text/javascript;base64,' + Buffer.from(bundle.outputFiles[0].text).toString('base64')
);
const scene = new THREE.Group(),
  geometry = new THREE.BoxGeometry(),
  source = new THREE.MeshPhysicalMaterial({
    color: '#ffffff',
    emissive: '#ff0000',
    clearcoat: 1,
    alphaTest: 0.5,
    side: THREE.DoubleSide,
  });
source.map = new THREE.Texture();
source.normalMap = new THREE.Texture();
source.normalScale.set(0.2, 0.3);
const a = new THREE.Mesh(geometry, source),
  b = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: '#00ff00' }));
a.userData.formPartId = 'a';
b.userData.formPartId = 'b';
scene.add(a, b);
const originalB = b.material;
let status;
const preview = new MaterialPreview(
    scene,
    () => {},
    (s) => (status = s),
  ),
  draft = {
    color: '#5588ee',
    roughness: 0.4,
    metalness: 0.2,
    opacity: 1,
    mode: 'replace',
    textures: {},
    uvScale: 1,
    uvRotation: 0,
    part_ids: ['a'],
  };
preview.apply(draft);
assert.equal(status, 'ready');
assert.equal(a.material.type, 'MeshStandardMaterial');
assert.equal(a.material.emissive.getHex(), 0);
assert.equal(a.material.map, null);
assert.equal(a.material.side, THREE.DoubleSide);
assert.equal(b.material, originalB);
assert.equal(a.geometry, geometry);
preview.apply({ ...draft, mode: 'tint' });
assert.equal(a.material.type, 'MeshPhysicalMaterial');
assert.equal(a.material.map, source.map);
assert.equal(a.material.emissive.getHex(), source.emissive.getHex());
assert.equal(a.material.alphaTest, 0);
assert.deepEqual(a.material.normalScale.toArray(), [0.2, 0.3]);
preview.apply({ ...draft, opacity: 0.2, part_ids: [] });
assert.equal(a.material.transparent, true);
assert.equal(b.material.transparent, true);
assert.equal(a.material.depthWrite, false);
preview.apply(undefined);
assert.equal(status, 'idle');
assert.equal(a.material, source);
assert.equal(b.material, originalB);
assert.equal(a.geometry, geometry);
// A logical group may contain an array of distinct original materials.
a.material = [source, originalB];
const arrayOriginal = a.material;
const second = new MaterialPreview(
  scene,
  () => {},
  () => {},
);
second.apply(draft);
assert.equal(a.material.length, 2);
second.apply(undefined);
assert.equal(a.material, arrayOriginal);
second.dispose();
preview.dispose();
assert.equal(source.color.getHexString(), 'ffffff');
assert.equal(source.map instanceof THREE.Texture, true);
assert.equal(source.alphaTest, 0.5);
const results = {
  checks: [
    'replace_clears_physical_emission_and_maps',
    'tint_retains_original_maps_and_extensions',
    'scope_does_not_touch_other_part',
    'opacity_matches_export',
    'cancel_restores_materials_and_geometry',
    'array_materials_restore',
    'source_material_immutable',
  ],
  passed: 7,
};
await fs.writeFile(
  process.env.MATERIAL_PREVIEW_REPORT || 'experiments/furniture_workbench_20261112/material_preview_unit.json',
  JSON.stringify(results, null, 2),
);
console.log(JSON.stringify(results));

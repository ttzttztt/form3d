import * as THREE from 'three';
import { surfaceVisibility } from './selectionVisibility';
import { topology } from './pointSelection';
import type { FaceMap } from './faceSelection';

export function connectedMaskFaces(mesh: THREE.Mesh, seed: number, accepted: Uint8Array): number[] {
  const data = topology(mesh.geometry);
  if (!accepted[seed]) throw new Error('多视角候选没有覆盖点击位置，请换点或涂抹。');
  const visited = new Uint8Array(data.count),
    queue = [seed];
  visited[seed] = 1;
  for (let head = 0; head < queue.length; head++)
    for (let k = 0; k < 3; k++) {
      const next = data.adjacent[queue[head] * 3 + k];
      if (next >= 0 && accepted[next] && !visited[next]) {
        visited[next] = 1;
        queue.push(next);
      }
    }
  if (queue.length > 500000) throw new Error('候选超过 50 万面，请先减面或改用局部涂抹。');
  return queue.sort((a, b) => a - b);
}

export async function proposeRenderedPart(options: {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  model: THREE.Object3D;
  mesh: THREE.Mesh;
  seed: number;
  point: THREE.Vector3;
  target: THREE.Vector3;
  jobId: string;
  version: string;
  signal: AbortSignal;
  helpers: (THREE.Object3D | undefined)[];
}) {
  const { renderer, scene, camera, model, mesh, seed, point, target, jobId, version, signal } =
    options;
  const original = camera.clone(),
    size = renderer.getSize(new THREE.Vector2()),
    pixelRatio = renderer.getPixelRatio();
  const states = options.helpers
    .filter((v): v is THREE.Object3D => !!v)
    .map((o) => ({ o, visible: o.visible }));
  const views: {
    image: string;
    point: { x: number; y: number };
    camera: THREE.PerspectiveCamera;
  }[] = [];
  const offset = camera.position.clone().sub(target);
  const width = 640,
    height = Math.max(64, Math.min(768, Math.round(640 / Math.max(camera.aspect, 0.85))));
  try {
    states.forEach(({ o }) => (o.visible = false));
    renderer.setPixelRatio(1);
    renderer.setSize(width, height, false);
    for (const angle of [0, -0.5, 0.5]) {
      camera.copy(original);
      camera.aspect = width / height;
      camera.clearViewOffset();
      camera.position
        .copy(target)
        .add(offset.clone().applyAxisAngle(new THREE.Vector3(0, 1, 0), angle));
      camera.lookAt(target);
      camera.updateProjectionMatrix();
      camera.updateMatrixWorld(true);
      const projected = point.clone().project(camera);
      if (
        Math.abs(projected.x) > 0.98 ||
        Math.abs(projected.y) > 0.98 ||
        !surfaceVisibility(model, camera)(point, projected)
      )
        continue;
      renderer.render(scene, camera);
      views.push({
        image: renderer.domElement.toDataURL('image/png'),
        point: { x: (projected.x + 1) / 2, y: (1 - projected.y) / 2 },
        camera: camera.clone(),
      });
    }
  } finally {
    camera.copy(original);
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld(true);
    renderer.setPixelRatio(pixelRatio);
    renderer.setSize(size.x, size.y, false);
    states.forEach(({ o, visible }) => (o.visible = visible));
    renderer.render(scene, camera);
  }
  if (!views.length) throw new Error('当前点击点在检查视角中不可见，请重新点击。');
  const response = await fetch(`/api/jobs/${jobId}/asset/part-proposal`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version, views: views.map(({ image, point }) => ({ image, point })) }),
    signal,
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || '辅助分割失败');
  const masks: Uint8ClampedArray[] = [];
  for (const url of result.masks) {
    const image = new Image();
    image.src = url;
    await image.decode();
    if (image.width !== width || image.height !== height) throw new Error('候选掩码尺寸不匹配');
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d')!;
    context.drawImage(image, 0, 0);
    masks.push(context.getImageData(0, 0, width, height).data);
  }
  if (signal.aborted) throw new Error('辅助分割已取消');
  const data = topology(mesh.geometry),
    positive = new Uint8Array(data.count),
    seen = new Uint8Array(data.count),
    world = new THREE.Vector3();
  for (let j = 0; j < views.length; j++) {
    const view = views[j],
      visible = surfaceVisibility(model, view.camera),
      mask = masks[j];
    for (let face = 0; face < data.count; face++) {
      world.fromArray(data.centers, face * 3).applyMatrix4(mesh.matrixWorld);
      const p = world.clone().project(view.camera);
      const x = Math.floor(((p.x + 1) * width) / 2),
        y = Math.floor(((1 - p.y) * height) / 2);
      if (p.z < -1 || p.z > 1 || x < 0 || x >= width || y < 0 || y >= height) continue;
      if (!visible(world, p)) continue;
      seen[face]++;
      if (mask[(y * width + x) * 4] > 127) positive[face]++;
    }
    await new Promise<void>((r) => requestAnimationFrame(() => r()));
    if (signal.aborted) throw new Error('辅助分割已取消');
  }
  const accepted = new Uint8Array(data.count);
  for (let i = 0; i < data.count; i++)
    if (positive[i] > 0 && positive[i] >= Math.min(2, seen[i])) accepted[i] = 1;
  const faces = connectedMaskFaces(mesh, seed, accepted);
  if (faces.length < 8) throw new Error('多视角一致区域过小，请换点或涂抹。');
  const map: FaceMap = { [mesh.userData.formPartId]: faces };
  return {
    faces: map,
    count: faces.length,
    views: views.length,
    proposalId: result.proposal_id,
    coverage: faces.length / data.count,
  };
}

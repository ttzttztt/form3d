import * as THREE from 'three';
import { surfaceVisibility } from './selectionVisibility';
import { topology } from './pointSelection';
import { connectedMaskFaces } from './samPartSelection';
import { refineSelection } from './selectionReview';
import type { FaceMap } from './faceSelection';
export type CandidateRange = 'small' | 'medium' | 'large';
export interface SurfacePrompt {
  mesh: THREE.Mesh;
  local: THREE.Vector3;
  face: number;
  label: 0 | 1;
}
export interface PartCandidates {
  referenceCamera: THREE.PerspectiveCamera;
  proposalId: string;
  views: number;
  evaluate: (
    range: CandidateRange,
    refine: boolean,
  ) => {
    faces: FaceMap;
    count: number;
    coverage: number;
    removed: number;
    filled: number;
    boundaryEdges: number;
  };
}

export async function interactivePartCandidates(options: {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  model: THREE.Object3D;
  mesh: THREE.Mesh;
  seed: number;
  prompts: SurfacePrompt[];
  target: THREE.Vector3;
  jobId: string;
  version: string;
  signal: AbortSignal;
  helpers: (THREE.Object3D | undefined)[];
  referenceCamera?: THREE.PerspectiveCamera;
}): Promise<PartCandidates> {
  const { renderer, scene, camera, model, mesh, seed, prompts, target, jobId, version, signal } =
    options;
  model.updateMatrixWorld(true);
  const worldPrompts = prompts.map((p) => ({
      ...p,
      world: p.local.clone().applyMatrix4(p.mesh.matrixWorld),
    })),
    original = camera.clone(),
    size = renderer.getSize(new THREE.Vector2()),
    ratio = renderer.getPixelRatio(),
    states = options.helpers
      .filter((o): o is THREE.Object3D => !!o)
      .map((o) => ({ o, visible: o.visible }));
  const width = 640,
    height = Math.max(64, Math.min(768, Math.round(640 / Math.max(camera.aspect, 0.85))));
  const cameras: THREE.PerspectiveCamera[] = [];
  if (
    options.referenceCamera &&
    options.referenceCamera.position.distanceTo(original.position) > 1e-4
  )
    cameras.push(options.referenceCamera.clone());
  cameras.push(original.clone());
  const offset = original.position.clone().sub(target);
  for (const angle of [-0.5, 0.5])
    if (cameras.length < 3) {
      const c = original.clone();
      c.position.copy(target).add(offset.clone().applyAxisAngle(new THREE.Vector3(0, 1, 0), angle));
      c.lookAt(target);
      cameras.push(c);
    }
  const views: {
    image: string;
    point: { x: number; y: number };
    points: { x: number; y: number; label: 0 | 1 }[];
    camera: THREE.PerspectiveCamera;
  }[] = [];
  const observedPrompts = new Set<number>();
  try {
    states.forEach(({ o }) => (o.visible = false));
    renderer.setPixelRatio(1);
    renderer.setSize(width, height, false);
    for (const source of cameras) {
      camera.copy(source);
      camera.aspect = width / height;
      camera.clearViewOffset();
      camera.updateProjectionMatrix();
      camera.updateMatrixWorld(true);
      const visible = surfaceVisibility(model, camera),
        points: { x: number; y: number; label: 0 | 1 }[] = [],
        visiblePromptIndices: number[] = [];
      for (let i = 0; i < worldPrompts.length; i++) {
        const p = worldPrompts[i],
          screen = p.world.clone().project(camera);
        if (
          Math.abs(screen.x) > 0.98 ||
          Math.abs(screen.y) > 0.98 ||
          screen.z < -1 ||
          screen.z > 1 ||
          !p.mesh.visible ||
          !visible(p.world, screen)
        )
          continue;
        points.push({ x: (screen.x + 1) / 2, y: (1 - screen.y) / 2, label: p.label });
        visiblePromptIndices.push(i);
      }
      const positive = points.filter((p) => p.label === 1);
      if (!positive.length) continue;
      visiblePromptIndices.forEach((i) => observedPrompts.add(i));
      const sorted = [...positive, ...points.filter((p) => p.label === 0)];
      renderer.render(scene, camera);
      views.push({
        image: renderer.domElement.toDataURL('image/png'),
        point: { x: positive[0].x, y: positive[0].y },
        points: sorted,
        camera: camera.clone(),
      });
    }
  } finally {
    camera.copy(original);
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld(true);
    renderer.setPixelRatio(ratio);
    renderer.setSize(size.x, size.y, false);
    states.forEach(({ o, visible }) => (o.visible = visible));
    renderer.render(scene, camera);
  }
  if (!views.length) throw new Error('保留点不可见，请显示部件或调整视角。');
  if (prompts.some((_, i) => !observedPrompts.has(i)))
    throw new Error('有修正点被遮挡，无法用于本轮判断；请换角度或撤销最后一个点。');
  const response = await fetch(`/api/jobs/${jobId}/asset/part-proposal`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      version,
      views: views.map(({ image, point, points }) => ({ image, point, points })),
    }),
    signal,
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(
      Array.isArray(result.detail)
        ? result.detail.map((v: { msg?: string }) => v.msg || '请求参数无效').join('；')
        : result.detail || '辅助分割失败',
    );
  const variants: Record<CandidateRange, Uint8ClampedArray[]> = {
    small: [],
    medium: [],
    large: [],
  };
  for (const candidate of result.candidates ?? [{ range: 'small', masks: result.masks }])
    for (const url of candidate.masks) {
      const image = new Image();
      image.src = url;
      await image.decode();
      if (image.width !== width || image.height !== height) throw new Error('掩码尺寸不匹配');
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext('2d')!;
      context.drawImage(image, 0, 0);
      variants[candidate.range as CandidateRange].push(
        context.getImageData(0, 0, width, height).data,
      );
    }
  const data = topology(mesh.geometry),
    seen = new Uint8Array(data.count),
    votes = {
      small: new Uint8Array(data.count),
      medium: new Uint8Array(data.count),
      large: new Uint8Array(data.count),
    },
    world = new THREE.Vector3();
  for (let j = 0; j < views.length; j++) {
    const c = views[j].camera,
      visible = surfaceVisibility(model, c);
    for (let face = 0; face < data.count; face++) {
      if (face % 8000 === 0) {
        await new Promise<void>((r) => requestAnimationFrame(() => r()));
        if (signal.aborted) throw new Error('已取消辅助选区');
      }
      world.fromArray(data.centers, face * 3).applyMatrix4(mesh.matrixWorld);
      const p = world.clone().project(c),
        x = Math.floor(((p.x + 1) * width) / 2),
        y = Math.floor(((1 - p.y) * height) / 2);
      if (p.z < -1 || p.z > 1 || x < 0 || x >= width || y < 0 || y >= height || !visible(world, p))
        continue;
      seen[face]++;
      for (const range of ['small', 'medium', 'large'] as CandidateRange[])
        if (variants[range][j]?.[(y * width + x) * 4] > 127) votes[range][face]++;
    }
  }
  const positive = new Set(
      prompts.filter((p) => p.label === 1 && p.mesh === mesh).map((p) => p.face),
    ),
    negative = new Set(prompts.filter((p) => p.label === 0 && p.mesh === mesh).map((p) => p.face));
  const evaluate = (range: CandidateRange, refine: boolean) => {
    const accepted = new Uint8Array(data.count);
    for (let i = 0; i < data.count; i++)
      if (votes[range][i] > 0 && votes[range][i] >= Math.min(2, seen[i])) accepted[i] = 1;
    positive.forEach((f) => (accepted[f] = 1));
    negative.forEach((f) => (accepted[f] = 0));
    const refined = refine
      ? refineSelection(mesh, accepted, positive, negative, votes[range])
      : { mask: accepted, removed: 0, filled: 0 };
    const selected = connectedMaskFaces(mesh, seed, refined.mask),
      set = new Set(selected);
    if ([...positive].some((f) => !set.has(f)))
      throw new Error('保留点之间没有连贯的可观察表面，请换角度、撤销最后一点或分开保存。');
    if (selected.length < Math.min(8, data.count))
      throw new Error('一致选区过小，原选择保留；可换个范围或使用已有部件。');
    let boundaryEdges = 0;
    for (const f of selected)
      for (let k = 0; k < 3; k++)
        if (data.adjacent[f * 3 + k] < 0 || !set.has(data.adjacent[f * 3 + k])) boundaryEdges++;
    return {
      faces: { [mesh.userData.formPartId]: selected },
      count: selected.length,
      coverage: selected.length / data.count,
      removed: refined.removed,
      filled: refined.filled,
      boundaryEdges,
    };
  };
  return {
    referenceCamera: views[0].camera,
    proposalId: result.proposal_id,
    views: views.length,
    evaluate,
  };
}

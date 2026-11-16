import * as THREE from 'three';
export interface FitResult {
  silhouette_iou: number;
  initial_silhouette_iou: number;
  projection_view: THREE.PerspectiveCamera['view'];
  evaluations: number;
  position: number[];
  target: number[];
  fov: number;
  reference_url: string;
  method: string;
  aspect: number;
  near: number;
  far: number;
  model_translation: number[];
  mask_size: number[];
}
// Coarse perspective silhouette search; not calibrated photogrammetry.
export async function fitReference(
  renderer: THREE.WebGLRenderer,
  model: THREE.Object3D,
  camera: THREE.PerspectiveCamera,
  imageUrl: string,
  progress: (text: string) => void,
  signal?: AbortSignal,
): Promise<FitResult> {
  const image = new Image();
  image.src = imageUrl;
  await image.decode();
  if (signal?.aborted) throw new Error('视角拟合已取消');
  const width = 96,
    height = Math.max(32, Math.round(width / camera.aspect));
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d')!;
  const ratio = Math.min(width / image.width, height / image.height);
  ctx.clearRect(0, 0, width, height);
  ctx.drawImage(
    image,
    (width - image.width * ratio) / 2,
    (height - image.height * ratio) / 2,
    image.width * ratio,
    image.height * ratio,
  );
  const pixels = ctx.getImageData(0, 0, width, height).data,
    mask = new Uint8Array(width * height);
  let count = 0;
  // Inspect alpha inside the actual image rectangle, excluding contain-letterboxing.
  const imageLeft = (width - image.width * ratio) / 2,
    imageTop = (height - image.height * ratio) / 2;
  let transparent = false;
  for (let y = Math.ceil(imageTop); y < height - imageTop; y++)
    for (let x = Math.ceil(imageLeft); x < width - imageLeft; x++)
      if (pixels[(y * width + x) * 4 + 3] < 128) transparent = true;
  for (let i = 0; i < mask.length; i++) {
    mask[i] = +(
      pixels[i * 4 + 3] > 128 &&
      (transparent || Math.min(pixels[i * 4], pixels[i * 4 + 1], pixels[i * 4 + 2]) < 238)
    );
    count += mask[i];
  }
  if (count < 20 || count > mask.length * 0.9)
    throw new Error('参考轮廓不可靠，请使用透明背景或已清理的白底图');
  const scene = new THREE.Scene(),
    cloned = model.clone(true);
  scene.add(cloned);
  scene.overrideMaterial = new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide });
  const bounds = new THREE.Box3().setFromObject(model),
    size = bounds.getSize(new THREE.Vector3()),
    center = bounds.getCenter(new THREE.Vector3());
  const radius = Math.max(size.x, size.y, size.z),
    target = new THREE.WebGLRenderTarget(width, height),
    buffer = new Uint8Array(mask.length * 4);
  const previousTarget = renderer.getRenderTarget(),
    previousClear = renderer.getClearColor(new THREE.Color()),
    previousAlpha = renderer.getClearAlpha();
  const originalPosition = camera.position.clone(),
    originalRotation = camera.quaternion.clone();
  const originalView = camera.view ? { ...camera.view } : null;
  const originalAspect = camera.aspect;
  let best = -1,
    bestPosition = originalPosition.clone(),
    evaluations = 0;
  let bestRotation = originalRotation.clone(),
    bestTarget = originalPosition
      .clone()
      .add(
        camera
          .getWorldDirection(new THREE.Vector3())
          .multiplyScalar(originalPosition.distanceTo(center)),
      ),
    bestView = originalView;
  let latestBounds = [width, height, 0, 0];
  const refBounds = [width, height, 0, 0];
  for (let y = 0; y < height; y++)
    for (let x = 0; x < width; x++)
      if (mask[y * width + x]) {
        refBounds[0] = Math.min(refBounds[0], x);
        refBounds[1] = Math.min(refBounds[1], y);
        refBounds[2] = Math.max(refBounds[2], x);
        refBounds[3] = Math.max(refBounds[3], y);
      }
  const renderScore = () => {
    camera.updateMatrixWorld(true);
    renderer.setRenderTarget(target);
    renderer.setClearColor(0, 0);
    renderer.clear();
    renderer.render(scene, camera);
    renderer.readRenderTargetPixels(target, 0, 0, width, height, buffer);
    let intersection = 0,
      union = 0;
    latestBounds = [width, height, 0, 0];
    for (let y = 0; y < height; y++)
      for (let x = 0; x < width; x++) {
        const a = mask[y * width + x],
          b = +(buffer[((height - 1 - y) * width + x) * 4 + 3] > 128);
        intersection += a && b ? 1 : 0;
        union += a || b ? 1 : 0;
        if (b) {
          latestBounds[0] = Math.min(latestBounds[0], x);
          latestBounds[1] = Math.min(latestBounds[1], y);
          latestBounds[2] = Math.max(latestBounds[2], x);
          latestBounds[3] = Math.max(latestBounds[3], y);
        }
      }
    const score = intersection / Math.max(union, 1);
    evaluations++;
    return score;
  };
  const restoreBest = () => {
    camera.position.copy(bestPosition);
    camera.quaternion.copy(bestRotation);
    camera.view = bestView ? { ...bestView } : null;
    camera.aspect = originalAspect;
    camera.updateProjectionMatrix();
  };
  const evaluate = (
    azimuth: number,
    elevation: number,
    distance: number,
    offsetX = 0,
    offsetY = 0,
  ) => {
    if (signal?.aborted) throw new Error('视角拟合已取消');
    elevation = Math.min(1.3, Math.max(0.02, elevation));
    camera.clearViewOffset();
    camera.aspect = originalAspect;
    camera.updateProjectionMatrix();
    if (offsetX || offsetY)
      camera.setViewOffset(
        originalAspect,
        1,
        (offsetX / width) * originalAspect,
        offsetY / height,
        originalAspect,
        1,
      );
    camera.position.set(
      center.x + Math.sin(azimuth) * Math.cos(elevation) * distance,
      center.y + Math.sin(elevation) * distance,
      center.z + Math.cos(azimuth) * Math.cos(elevation) * distance,
    );
    camera.lookAt(center);
    const score = renderScore();
    if (score > best) {
      best = score;
      bestPosition = camera.position.clone();
      bestRotation = camera.quaternion.clone();
      bestTarget = center.clone();
      bestView = camera.view?.enabled ? { ...camera.view } : null;
    }
    return score;
  };
  let initial = -1;
  try {
    initial = renderScore();
    best = initial;
    for (let az = 0; az < 8; az++) {
      for (const elevation of [0, 0.35, 0.7])
        for (const distance of [2, 2.8, 3.8])
          evaluate((az * Math.PI) / 4, elevation, radius * distance);
      renderer.setRenderTarget(previousTarget);
      progress(`轮廓拟合 ${az + 1}/8`);
      await new Promise((r) => setTimeout(r, 0));
    }
    const direction = bestPosition.clone().sub(center),
      baseAz = Math.atan2(direction.x, direction.z),
      baseEl = Math.asin(direction.y / direction.length()),
      baseDistance = direction.length();
    for (const da of [-0.2, 0, 0.2])
      for (const de of [-0.15, 0, 0.15])
        for (const scale of [0.88, 1, 1.12])
          evaluate(baseAz + da, baseEl + de, baseDistance * scale);
    restoreBest();
    renderScore();
    // Refine scale and principal point against the measured foreground bounding boxes.
    const direction2 = bestPosition.clone().sub(center),
      az2 = Math.atan2(direction2.x, direction2.z),
      el2 = Math.asin(direction2.y / direction2.length()),
      dist2 = direction2.length();
    const box = latestBounds,
      scale2 = Math.sqrt(
        ((refBounds[2] - refBounds[0] + 1) * (refBounds[3] - refBounds[1] + 1)) /
          Math.max(1, (box[2] - box[0] + 1) * (box[3] - box[1] + 1)),
      );
    for (const scale of [scale2 * 0.9, scale2, scale2 * 1.1]) {
      const ox =
        ((box[0] + box[2]) / 2 - width / 2) * scale + width / 2 - (refBounds[0] + refBounds[2]) / 2;
      const oy =
        ((box[1] + box[3]) / 2 - height / 2) * scale +
        height / 2 -
        (refBounds[1] + refBounds[3]) / 2;
      for (const dx of [-2, 0, 2])
        for (const dy of [-2, 0, 2]) evaluate(az2, el2, dist2 / scale, ox + dx, oy + dy);
    }
    restoreBest();
    camera.updateMatrixWorld(true);
    return {
      silhouette_iou: best,
      initial_silhouette_iou: initial,
      projection_view: bestView,
      evaluations,
      position: bestPosition.toArray(),
      target: bestTarget.toArray(),
      fov: camera.fov,
      aspect: camera.aspect,
      near: camera.near,
      far: camera.far,
      model_translation: model.position.toArray(),
      mask_size: [width, height],
      reference_url: imageUrl,
      method:
        '96px perspective silhouette search with scale and principal-point refinement; foreground threshold; no calibrated camera or hidden-surface validation',
    };
  } catch (error) {
    camera.position.copy(originalPosition);
    camera.quaternion.copy(originalRotation);
    camera.view = originalView;
    camera.aspect = originalAspect;
    camera.updateProjectionMatrix();
    throw error;
  } finally {
    if (!signal?.aborted) {
      renderer.setRenderTarget(previousTarget);
      renderer.setClearColor(previousClear, previousAlpha);
    }
    target.dispose();
    (scene.overrideMaterial as THREE.Material).dispose();
  }
}

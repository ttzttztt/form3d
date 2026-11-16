import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

function dispose(root: THREE.Object3D) {
  root.traverse((o) => {
    if (!(o instanceof THREE.Mesh)) return;
    o.geometry.dispose();
    for (const m of Array.isArray(o.material) ? o.material : [o.material]) m.dispose();
  });
}

export default function CutPreview({
  url,
  onReady,
  reconstructed = false,
  legend,
  soloHideMaterials = ['preview_body'],
}: {
  url: string;
  onReady: () => void;
  reconstructed?: boolean;
  legend?: string;
  soloHideMaterials?: string[];
}) {
  const host = useRef<HTMLDivElement>(null),
    ready = useRef(onReady);
  ready.current = onReady;
  const action = useRef<(view: string) => void>();
  const [error, setError] = useState(''),
    [loaded, setLoaded] = useState(false),
    [solo, setSolo] = useState(false);
  useEffect(() => {
    const element = host.current!;
    setError('');
    setLoaded(false);
    setSolo(false);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#f1f4f8');
    const camera = new THREE.PerspectiveCamera(38, 1, 0.001, 100);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    element.appendChild(renderer.domElement);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x64748b, 3));
    const light = new THREE.DirectionalLight(0xffffff, 3);
    light.position.set(3, 5, 4);
    scene.add(light);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    let model: THREE.Object3D | undefined,
      cancelled = false,
      frame = 0,
      isolated = false;
    const resize = () => {
      const w = element.clientWidth,
        h = element.clientHeight;
      renderer.setSize(w, h);
      camera.aspect = w / Math.max(h, 1);
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    resize();
    action.current = (view) => {
      if (view === 'solo') {
        isolated = !isolated;
        setSolo(isolated);
        model?.traverse((o) => {
          if (o instanceof THREE.Mesh) {
            const mats = Array.isArray(o.material) ? o.material : [o.material];
            if (mats.some((m) => soloHideMaterials.includes(m.name))) o.visible = !isolated;
          }
        });
        return;
      }
      const directions: Record<string, number[]> = {
        front: [0, 0.18, 2.2],
        side: [2.2, 0.18, 0],
        back: [0, 0.18, -2.2],
        bottom: [0, -2.2, 0.05],
        orbit: [1.5, 1, 1.8],
      };
      camera.position.fromArray(directions[view] ?? directions.orbit);
      camera.up.set(0, 1, 0);
      controls.target.set(0, 0, 0);
      controls.update();
    };
    action.current('orbit');
    new GLTFLoader().load(
      url,
      (gltf) => {
        if (cancelled) {
          dispose(gltf.scene);
          return;
        }
        model = gltf.scene;
        const box = new THREE.Box3().setFromObject(model),
          size = box.getSize(new THREE.Vector3()),
          center = box.getCenter(new THREE.Vector3()),
          scale = 1 / Math.max(size.x, size.y, size.z, 1e-8);
        const group = new THREE.Group();
        group.add(model);
        group.scale.setScalar(scale);
        group.position.copy(center).multiplyScalar(-scale);
        scene.add(group);
        setLoaded(true);
        ready.current();
      },
      undefined,
      () => {
        if (!cancelled) setError('预览加载失败，请重新预览。');
      },
    );
    const render = () => {
      frame = requestAnimationFrame(render);
      controls.update();
      renderer.render(scene, camera);
    };
    render();
    return () => {
      cancelled = true;
      action.current = undefined;
      cancelAnimationFrame(frame);
      observer.disconnect();
      controls.dispose();
      dispose(scene);
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    };
  }, [url]);
  return (
    <div className="cut-preview" role="group" aria-label="实际切分预览">
      <div ref={host} className="cut-preview-canvas" />
      {!loaded && !error && <p role="status">正在加载切分预览…</p>}
      {error && <p role="alert">{error}</p>}
      <div className="selection-actions">
        {(
          [
            ['front', '预览正面'],
            ['side', '预览侧面'],
            ['back', '预览背面'],
            ['bottom', '预览底面'],
          ] as const
        ).map(([v, label]) => (
          <button key={v} disabled={!loaded} onClick={() => action.current?.(v)}>
            {label}
          </button>
        ))}
        <button disabled={!loaded} aria-pressed={solo} onClick={() => action.current?.('solo')}>
          只看拆出部件
        </button>
      </div>
      <p>
        {legend ??
          (reconstructed
            ? '蓝色：重建外表面；橙色：缺少附近源表面支持的推测区域。全部输出面均为重建，闭合不代表真实形状。'
            : '蓝色：保留的源模型表面；橙色：新增的推测接合面；半透明灰色：其余结构。')}
        可拖动旋转。
      </p>
    </div>
  );
}

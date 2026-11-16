import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { Expand, RotateCcw, Grid2X2, Box, LoaderCircle, AlertCircle } from 'lucide-react';
import { screenFaces, combineFaces } from './faceSelection';
import type { FaceMap, FaceSelection } from './faceSelection';
import { fitReference } from './referenceFit';
import { pointSelection } from './pointSelection';
import type { SelectionRange } from './pointSelection';
import { MaterialPreview } from './materialPreview';
import type { MaterialDraft, PreviewStatus } from './materialDraft';
import { PartInspection } from './partInspection';
import { interactivePartCandidates } from './interactivePartSelection';
import type { SurfacePrompt, PartCandidates, CandidateRange } from './interactivePartSelection';
import { selectionBoundary, uvSeams } from './selectionReview';

interface Props {
  url?: string;
  label: string;
  onLoaded?: () => void;
  onPartPick?: (id: string) => void;
  selectedPart?: string;
  onFacesChange?: (faces: FaceSelection[]) => void;
  referenceUrl?: string;
  showReferenceTools?: boolean;
  materialDraft?: MaterialDraft;
  onDraftStatus?: (value: PreviewStatus) => void;
  selectedPartIds?: string[];
  editingDisabled?: boolean;
  jobId?: string;
  onAssistanceBusy?: (value: boolean) => void;
  completionBounds?: number[][];
  inspectionOnly?: boolean;
}

export default function Viewer({
  url,
  label,
  onLoaded,
  onPartPick,
  selectedPart,
  onFacesChange,
  referenceUrl,
  showReferenceTools = false,
  materialDraft,
  onDraftStatus,
  selectedPartIds,
  editingDisabled = false,
  jobId,
  onAssistanceBusy,
  completionBounds,
  inspectionOnly = false,
}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const toolsHost = useRef<HTMLDivElement>(null);
  const disabledRef = useRef(editingDisabled);
  disabledRef.current = editingDisabled;
  const controller = useRef<{
    reset: () => void;
    grid: () => void;
    select: (id: string | string[]) => void;
    undo: () => void;
    redo: () => void;
    clear: () => void;
    fit: () => Promise<void>;
    expandPoint: () => void;
    material: (draft?: MaterialDraft) => void;
    inspect: (action: string, value?: number) => void;
    samRange: () => void;
    samUndo: () => void;
    samClear: () => void;
    review: () => void;
    completionBox: () => void;
    partColours: (value: boolean) => void;
  }>();
  const loaded = useRef(onLoaded);
  loaded.current = onLoaded;
  const pickCallback = useRef(onPartPick);
  pickCallback.current = onPartPick;
  const selectedRef = useRef<string[]>([]);
  selectedRef.current = selectedPartIds?.length
    ? selectedPartIds
    : selectedPart
      ? [selectedPart]
      : [];
  const draftRef = useRef(materialDraft),
    draftStatusRef = useRef(onDraftStatus);
  draftRef.current = materialDraft;
  draftStatusRef.current = onDraftStatus;
  const completionRef=useRef(completionBounds);completionRef.current=completionBounds;
  useEffect(()=>{controller.current?.completionBox();},[completionBounds]);
  useEffect(() => {
    controller.current?.material(materialDraft);
  }, [materialDraft]);
  useEffect(() => {
    controller.current?.select(selectedRef.current);
  }, [selectedPart, selectedPartIds]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [grid, setGrid] = useState(true);
  const [tool, setTool] = useState('orbit'),
    [subtract, setSubtract] = useState(false),
    [faceCount, setFaceCount] = useState(0);
  const [overlay, setOverlay] = useState(false),
    [overlayAlpha, setOverlayAlpha] = useState(0.5),
    [fitMessage, setFitMessage] = useState(''),
    [fitting, setFitting] = useState(false);
  const [gestureBox, setGestureBox] = useState<{
    left: number;
    top: number;
    width: number;
    height: number;
  }>();
  const [through, setThrough] = useState(false),
    [selectionMessage, setSelectionMessage] = useState('');
  const [selectionHistory, setSelectionHistory] = useState({ undo: false, redo: false });
  const [pointRange, setPointRange] = useState<SelectionRange>('normal'),
    [appendPoint, setAppendPoint] = useState(false);
  const [hasPointSeed, setHasPointSeed] = useState(false);
  const [assisting, setAssisting] = useState(false),
    [explosion, setExplosion] = useState(0),
    [solo, setSolo] = useState(false);
  const [promptMode, setPromptMode] = useState<'replace' | 'positive' | 'negative'>('replace'),
    [samRange, setSamRange] = useState<CandidateRange>('medium'),
    [refineBoundary, setRefineBoundary] = useState(true),
    [promptCounts, setPromptCounts] = useState({ positive: 0, negative: 0 }),
    [availableRanges, setAvailableRanges] = useState<CandidateRange[]>([]),
    [showBoundary, setShowBoundary] = useState(true),
    [showSeams, setShowSeams] = useState(false),
    [seamMessage, setSeamMessage] = useState('');
  const [showInferred,setShowInferred]=useState(false),[hasInferred,setHasInferred]=useState(false);
  const [partColours,setPartColours]=useState(false),[hasSemanticParts,setHasSemanticParts]=useState(false);
  const partColoursRef=useRef(partColours);partColoursRef.current=partColours;
  const colourJob=useRef<string>();
  useEffect(()=>{controller.current?.partColours(partColours);},[partColours]);
  useEffect(()=>{if(materialDraft)setPartColours(false);},[materialDraft]);
  const inferredRef=useRef(showInferred);inferredRef.current=showInferred;
  const promptModeRef = useRef(promptMode),
    samRangeRef = useRef(samRange),
    refineBoundaryRef = useRef(refineBoundary),
    showBoundaryRef = useRef(showBoundary),
    showSeamsRef = useRef(showSeams);
  promptModeRef.current = promptMode;
  samRangeRef.current = samRange;
  refineBoundaryRef.current = refineBoundary;
  showBoundaryRef.current = showBoundary;
  showSeamsRef.current = showSeams;
  const assistanceCallback = useRef(onAssistanceBusy);
  assistanceCallback.current = onAssistanceBusy;
  const pointRangeRef = useRef(pointRange),
    appendPointRef = useRef(appendPoint);
  pointRangeRef.current = pointRange;
  appendPointRef.current = appendPoint;
  const throughRef = useRef(through);
  throughRef.current = through;
  useEffect(() => {
    const element = toolsHost.current;
    if (!element) return;
    const observer = new ResizeObserver(() =>
      element.parentElement?.style.setProperty(
        '--selection-tools-height',
        `${element.offsetHeight}px`,
      ),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [!!onFacesChange, url]);
  useEffect(() => {
    if (!showReferenceTools) setOverlay(false);
  }, [showReferenceTools]);
  const toolRef = useRef(tool),
    subtractRef = useRef(subtract),
    facesCallback = useRef(onFacesChange),
    referenceRef = useRef(referenceUrl);
  toolRef.current = tool;
  subtractRef.current = subtract;
  facesCallback.current = onFacesChange;
  referenceRef.current = referenceUrl;
  useEffect(() => {
    setOverlay(false);
    setFitMessage('');
  }, [referenceUrl]);

  useEffect(() => {
    if (!host.current || !url) return;
    const element = host.current;
    let disposed = false;
    const fitAbort = new AbortController();
    let dirty = true;
    setLoading(true);
    setHasInferred(false);
    setError('');
    setGrid(true);
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        preserveDrawingBuffer: true,
      });
    } catch {
      setError('浏览器未启用 WebGL，仍可下载 GLB 后使用其他查看器打开。');
      setLoading(false);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.95;
    element.appendChild(renderer.domElement);
    renderer.domElement.setAttribute('aria-label', label);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, 1, 0.001, 1000);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.addEventListener('change', () => {
      dirty = true;
    });
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.maxPolarAngle = Math.PI - 0.01;
    const pmrem = new THREE.PMREMGenerator(renderer);
    const room = new RoomEnvironment();
    const environment = pmrem.fromScene(room, 0.04);
    scene.environment = environment.texture;
    room.dispose();
    pmrem.dispose();
    scene.add(new THREE.HemisphereLight(0xffffff, 0x9098a4, 0.8));
    const key = new THREE.DirectionalLight(0xffffff, 2);
    key.position.set(3, 5, 4);
    scene.add(key);
    let model: THREE.Object3D | undefined;
    let materialPreview: MaterialPreview | undefined;
    let inspection: PartInspection | undefined;
    let helper: THREE.GridHelper | undefined;
    let selectionHelper: THREE.Box3Helper | undefined;
    let faceHelper: THREE.Mesh | undefined,
      faceMap: FaceMap = {},
      undo: FaceMap[] = [],
      redo: FaceMap[] = [],
      fitActive = false;
    let boundaryHelper: THREE.LineSegments | undefined,
      seamHelper: THREE.LineSegments | undefined,
      promptHelper: THREE.Points | undefined;
    let completionHelper: THREE.Box3Helper | undefined;
    let inferredHelper:THREE.Group|undefined;
    function clearInferred(){if(inferredHelper){scene.remove(inferredHelper);inferredHelper.traverse(o=>{if(o instanceof THREE.Mesh){o.geometry.dispose();(o.material as THREE.Material).dispose();}});inferredHelper=undefined;}}
    function drawCompletionBox(){
      if(completionHelper){scene.remove(completionHelper);completionHelper.geometry.dispose();(completionHelper.material as THREE.Material).dispose();completionHelper=undefined;}
      const b=completionRef.current;
      if(model&&b?.length===2&&b.every(row=>row.length===3&&row.every(Number.isFinite))){
        const box=new THREE.Box3(new THREE.Vector3(...b[0]),new THREE.Vector3(...b[1])).translate(model.position);
        completionHelper=new THREE.Box3Helper(box,0x009e72);scene.add(completionHelper);
      }
      dirty=true;
    }
    type Session = {
      mesh: THREE.Mesh;
      seed: number;
      prompts: SurfacePrompt[];
      cache?: PartCandidates;
      base: FaceMap;
    };
    let samSession: Session | undefined;
    function resetSam() {
      samSession = undefined;
      setPromptCounts({ positive: 0, negative: 0 });
      setAvailableRanges([]);
      drawPrompts();
    }
    function drawPrompts(session = samSession) {
      if (promptHelper) {
        scene.remove(promptHelper);
        promptHelper.geometry.dispose();
        (promptHelper.material as THREE.Material).dispose();
        promptHelper = undefined;
      }
      if (!session) return;
      model?.updateMatrixWorld(true);
      const positions: number[] = [],
        colors: number[] = [];
      for (const p of session.prompts) {
        const world = p.local.clone().applyMatrix4(p.mesh.matrixWorld);
        positions.push(world.x, world.y, world.z);
        colors.push(...(p.label === 1 ? [0.1, 0.8, 0.4] : [1, 0.15, 0.12]));
      }
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
      geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
      promptHelper = new THREE.Points(
        geometry,
        new THREE.PointsMaterial({
          size: 9,
          sizeAttenuation: false,
          vertexColors: true,
          depthWrite: false,
        }),
      );
      promptHelper.renderOrder = 20;
      scene.add(promptHelper);
      dirty = true;
    }
    function reviewOverlays() {
      clearInferred();
      for (const helper of [boundaryHelper, seamHelper])
        if (helper) {
          scene.remove(helper);
          helper.geometry.dispose();
          (helper.material as THREE.Material).dispose();
        }
      boundaryHelper = seamHelper = undefined;
      const boundary: number[] = [],
        seams: number[] = [];
      let foundUV = false,
        truncated = false;
      model?.updateMatrixWorld(true);
      model?.traverseVisible((child) => {
        if (!(child instanceof THREE.Mesh) || !child.userData.formPartId) return;
        if(inferredRef.current&&child.userData.formCompletionRole==='inferred_interface'){
          inferredHelper??=new THREE.Group();const overlay=new THREE.Mesh(child.geometry.clone(),new THREE.MeshBasicMaterial({color:0xf0a044,transparent:true,opacity:.8,side:THREE.DoubleSide,depthWrite:false,polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-1}));overlay.matrixAutoUpdate=false;overlay.matrix.copy(child.matrixWorld);overlay.renderOrder=12;inferredHelper.add(overlay);
        }
        if (showBoundaryRef.current && faceMap[child.userData.formPartId])
          for (const value of selectionBoundary(child, faceMap[child.userData.formPartId]))
            boundary.push(value);
        if (
          showSeamsRef.current &&
          (!selectedRef.current.length || selectedRef.current.includes(child.userData.formPartId))
        ) {
          const result = uvSeams(child.geometry);
          if (result) {
            foundUV = true;
            truncated ||= result.truncated;
            const v = new THREE.Vector3();
            for (let i = 0; i < result.lines.length; i += 3) {
              v.fromArray(result.lines, i).applyMatrix4(child.matrixWorld);
              seams.push(v.x, v.y, v.z);
            }
          }
        }
      });
      const line = (positions: number[], color: number) => {
        if (!positions.length) return undefined;
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        const helper = new THREE.LineSegments(
          geometry,
          new THREE.LineBasicMaterial({ color, depthWrite: false }),
        );
        helper.renderOrder = 15;
        scene.add(helper);
        return helper;
      };
      boundaryHelper = line(boundary, 0xff8c20);
      seamHelper = line(seams, 0x168cdd);
      if(inferredHelper)scene.add(inferredHelper);
      setSeamMessage(
        showSeamsRef.current
          ? foundUV
            ? `蓝线为 UV 接缝或网格开口边界${truncated ? '（数量较多，仅显示部分）' : ''}。`
            : '当前范围没有 UV，请先展开。'
          : '',
      );
      drawPrompts();
      dirty = true;
    }
    function applySam(session: Session, range: CandidateRange) {
      if (!session.cache) return;
      const proposal = session.cache.evaluate(range, refineBoundaryRef.current);
      undo.push(faceMap);
      if(undo.length>20)undo.shift();
      redo = [];
      showFaces(proposal.faces);
      setSelectionMessage(
        `已按${range === 'small' ? '较小' : range === 'medium' ? '适中' : '较大'}范围更新候选，${proposal.count.toLocaleString()} 面。${proposal.coverage > 0.7 ? '范围较大，请检查是否跨越其他部件。' : ''}${proposal.removed ? `已清除 ${proposal.removed} 个边缘突出面。` : ''}请检查橙色边界，未观察面不会自动补齐。`,
      );
    }
    async function runSam(session: Session) {
      if (!model || !jobId) return;
      fitActive = true;
      setAssisting(true);
      assistanceCallback.current?.(true);
      setSelectionMessage('正在根据保留点和排除点计算候选…');
      drawPrompts(session);
      try {
        const cache = await interactivePartCandidates({
          renderer,
          scene,
          camera,
          model,
          mesh: session.mesh,
          seed: session.seed,
          prompts: session.prompts,
          target: controls.target.clone(),
          jobId,
          version: url?.match(/\/assets\/([a-f0-9]{32})\//)?.[1] ?? 'original',
          signal: fitAbort.signal,
          helpers: [helper, selectionHelper, faceHelper, boundaryHelper, seamHelper, promptHelper,completionHelper,inferredHelper],
          referenceCamera: session.cache?.referenceCamera,
        });
        if (disposed) return;
        const next = { ...session, cache },
          valid: CandidateRange[] = [],
          signatures = new Set<string>();
        for (const range of ['small', 'medium', 'large'] as CandidateRange[])
          try {
            const value = cache.evaluate(range, refineBoundaryRef.current);
            const signature = JSON.stringify(value.faces);
            if (!signatures.has(signature)) {
              signatures.add(signature);
              valid.push(range);
            }
          } catch {
            /* A different range may still be usable. */
          }
        if (!valid.length) throw new Error('多视角候选无法同时满足这些点，请换点或撤销修正。');
        let chosen = samRangeRef.current;
        if (!valid.includes(chosen)) chosen = valid[0];
        applySam(next, chosen);
        samSession = next;
        setAvailableRanges(valid);
        setSamRange(chosen);
        samRangeRef.current = chosen;
        setPromptCounts({
          positive: session.prompts.filter((p) => p.label === 1).length,
          negative: session.prompts.filter((p) => p.label === 0).length,
        });
        drawPrompts();
        lastPoint = undefined;
        setHasPointSeed(false);
      } catch (error) {
        if (!disposed) {
          drawPrompts();
          setSelectionMessage(
            (error instanceof Error ? error.message : String(error)) +
              ' 本次修正未生效，原提示与选区保留。',
          );
        }
      } finally {
        fitActive = false;
        dirty = true;
        if (!disposed) {
          setAssisting(false);
          assistanceCallback.current?.(false);
        }
      }
    }
    let lastPoint: { mesh: THREE.Mesh; face: number; base: FaceMap } | undefined;
    resetSam();
    setFaceCount(0);
    setPromptMode('replace');
    promptModeRef.current = 'replace';
    setSelectionHistory({ undo: false, redo: false });
    setHasPointSeed(false);
    setSelectionMessage('');
    setFitting(false);
    facesCallback.current?.([]);
    setFitMessage('');
    setOverlay(false);
    function showFaces(value: FaceMap) {
      dirty = true;
      faceMap = value;
      let count = 0;
      const positions: number[] = [];
      if (faceHelper) {
        scene.remove(faceHelper);
        faceHelper.geometry.dispose();
        (faceHelper.material as THREE.Material).dispose();
        faceHelper = undefined;
      }
      model?.updateMatrixWorld(true);
      model?.traverse((child) => {
        if (!(child instanceof THREE.Mesh)) return;
        const faces = value[child.userData.formPartId];
        if (!faces) return;
        if (!child.visible) {
          count += faces.length;
          return;
        }
        const position = child.geometry.getAttribute('position'),
          index = child.geometry.index,
          v = new THREE.Vector3();
        for (const face of faces) {
          count++;
          for (let i = face * 3; i < face * 3 + 3; i++) {
            v.fromBufferAttribute(position, index ? index.getX(i) : i).applyMatrix4(
              child.matrixWorld,
            );
            positions.push(v.x, v.y, v.z);
          }
        }
      });
      if (positions.length) {
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        faceHelper = new THREE.Mesh(
          geometry,
          new THREE.MeshBasicMaterial({
            color: 0xad68ff,
            transparent: true,
            opacity: 0.55,
            side: THREE.DoubleSide,
            depthTest: !throughRef.current,
            depthWrite: false,
            polygonOffset: true,
            polygonOffsetFactor: -1,
            polygonOffsetUnits: -1,
          }),
        );
        faceHelper.renderOrder = 10;
        scene.add(faceHelper);
      }
      setFaceCount(count);
      setSelectionHistory({ undo: undo.length > 0, redo: redo.length > 0 });
      facesCallback.current?.(
        Object.entries(value).map(([part_id, faces]) => ({ part_id, faces })),
      );
      reviewOverlays();
    }
    function choosePoint(mesh: THREE.Mesh, face: number, base: FaceMap = faceMap) {
      lastPoint = { mesh, face, base };
      setHasPointSeed(true);
      try {
        const proposed = pointSelection(mesh, face, pointRangeRef.current);
        undo.push(faceMap);
        if (undo.length > 20) undo.shift();
        redo = [];
        pickCallback.current?.('');
        const count =
          (mesh.geometry.index?.count ?? mesh.geometry.getAttribute('position').count) / 3;
        if (proposed.count === count) {
          showFaces({});
          pickCallback.current?.(mesh.userData.formPartId);
          setSelectionMessage('已选中这个已有网格，可直接换材质。');
        } else {
          showFaces(
            appendPointRef.current ? combineFaces(base, proposed.faces, false) : proposed.faces,
          );
          setSelectionMessage(proposed.message);
        }
      } catch (error) {
        setSelectionMessage(
          (error instanceof Error ? error.message : String(error)) + ' 原选区保留。',
        );
      }
    }
    const home = new THREE.Vector3();
    const target = new THREE.Vector3();
    let frame = 0;
    const observer = new ResizeObserver(() => {
      dirty = true;
      if (camera.view?.enabled && !fitActive) {
        camera.clearViewOffset();
        setOverlay(false);
        setFitMessage('窗口大小改变，请重新拟合参考视角');
      }
      const width = Math.max(element.clientWidth, 1),
        height = Math.max(element.clientHeight, 1);
      renderer.setSize(width, height);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    });
    observer.observe(element);
    function disposeModel(object: THREE.Object3D) {
      const textures = new Set<THREE.Texture>();
      object.traverse((child) => {
        if (!(child instanceof THREE.Mesh)) return;
        child.geometry.dispose();
        const materials = Array.isArray(child.material) ? child.material : [child.material];
        for (const material of materials) {
          for (const value of Object.values(material))
            if (value instanceof THREE.Texture) textures.add(value);
          material.dispose();
        }
      });
      textures.forEach((texture) => texture.dispose());
    }
    const manager = new THREE.LoadingManager();
    function selectPart(id: string | string[]) {
      dirty = true;
      inspection?.select(Array.isArray(id) ? id : id ? [id] : []);
      if (selectionHelper) {
        scene.remove(selectionHelper);
        selectionHelper.geometry.dispose();
        (selectionHelper.material as THREE.Material).dispose();
        selectionHelper = undefined;
      }
      const identities = new Set(Array.isArray(id) ? id : id ? [id] : []);
      if (!model || !identities.size) {
        reviewOverlays();
        return;
      }
      model.updateMatrixWorld(true);
      const bounds = new THREE.Box3();
      const point = new THREE.Vector3();
      model.traverse((child) => {
        if (
          !(child instanceof THREE.Mesh) ||
          !child.visible ||
          !identities.has(child.userData.formPartId)
        )
          return;
        const position = child.geometry.getAttribute('position');
        const index = child.geometry.getIndex();
        for (let i = 0; i < (index?.count ?? position.count); i++) {
          point
            .fromBufferAttribute(position, index ? index.getX(i) : i)
            .applyMatrix4(child.matrixWorld);
          bounds.expandByPoint(point);
        }
      });
      if (!bounds.isEmpty()) {
        selectionHelper = new THREE.Box3Helper(bounds, 0x8154de);
        scene.add(selectionHelper);
      }
      reviewOverlays();
    }
    // The server only delivers self-contained GLBs. Do not load external resources.
    manager.setURLModifier((resource) => {
      if (resource === url || resource.startsWith('blob:') || resource.startsWith('data:'))
        return resource;
      throw new Error('模型包含外部资源');
    });
    new GLTFLoader(manager).load(
      url,
      (result) => {
        if (disposed) {
          disposeModel(result.scene);
          return;
        }
        model = result.scene;
        model.traverse((child) => {
          if (!(child instanceof THREE.Mesh)) return;
          const association = result.parser.associations.get(child) as
            | { nodes?: number; primitives?: number }
            | undefined;
          let nodeIndex = association?.nodes;
          let parent = child.parent;
          while (nodeIndex === undefined && parent) {
            nodeIndex = (result.parser.associations.get(parent) as { nodes?: number } | undefined)
              ?.nodes;
            parent = parent.parent;
          }
          if (nodeIndex !== undefined) {
            const number = association?.primitives ?? 0;
            child.userData.formPartId =
              result.parser.json.nodes[nodeIndex]?.extras?.form_part_ids?.[String(number)] ??
              `node_${nodeIndex}_primitive_${number}`;
            const meshIndex = result.parser.json.nodes[nodeIndex]?.mesh;
            const extras = result.parser.json.meshes[meshIndex]?.primitives[number]?.extras;
            child.userData.formSelectionRole = extras?.form_selection_role;
            child.userData.formGroupId = extras?.form_logical_group_id;
            child.userData.formCompletionRole=extras?.form_completion_role;
            child.userData.formSemanticColor=extras?.form_semantic_color;
          }
        });
        inspection = new PartInspection(model, () => {
          dirty = true;
        });
        let inferred=false;model.traverse(o=>{if(o.userData.formCompletionRole==='inferred_interface')inferred=true;});setHasInferred(inferred);
        setExplosion(0);
        setSolo(false);
        const box = new THREE.Box3().setFromObject(model);
        if (box.isEmpty()) {
          setError('模型没有可见网格');
          setLoading(false);
          disposeModel(model);
          model = undefined;
          return;
        }
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        model.position.sub(new THREE.Vector3(center.x, box.min.y, center.z));
        scene.add(model);
        materialPreview = new MaterialPreview(
          model,
          () => {
            dirty = true;
          },
          (status) => {
            if (!disposed) draftStatusRef.current?.(status);
          },
        );
        materialPreview.apply(draftRef.current);
        let semantic=false;model.traverse(o=>{if(o.userData.formSemanticColor)semantic=true;});setHasSemanticParts(semantic);
        const enableColours=semantic&&colourJob.current!==(jobId??url);
        if(enableColours){colourJob.current=jobId??url;setPartColours(true);}
        materialPreview.showPartColours(enableColours||partColoursRef.current);
        const radius = Math.max(size.x, size.y, size.z, 0.01);
        helper = new THREE.GridHelper(radius * 3.4, 24, 0xd5dae4, 0xe3e7ef);
        helper.position.y = -0.002;
        scene.add(helper);
        target.set(0, size.y * 0.45, 0);
        home.set(radius * 1.65, size.y * 0.6 + radius * 0.95, radius * 2.15);
        camera.position.copy(home);
        camera.near = radius / 100;
        camera.far = radius * 100;
        camera.updateProjectionMatrix();
        controls.target.copy(target);
        controls.minDistance = radius * 0.4;
        controls.maxDistance = radius * 12;
        controls.update();
        controller.current = {
          reset: () => {
            camera.clearViewOffset();
            camera.updateProjectionMatrix();
            setOverlay(false);
            setFitMessage('');
            camera.position.copy(home);
            controls.target.copy(target);
            controls.update();
          },
          grid: () => {
            if (helper) helper.visible = !helper.visible;
            dirty = true;
          },
          select: selectPart,
          material: (draft) => materialPreview?.apply(draft),
          partColours: (value) => materialPreview?.showPartColours(value),
          samRange: () => {
            if (samSession)
              try {
                applySam(samSession, samRangeRef.current);
              } catch (e) {
                setSelectionMessage((e instanceof Error ? e.message : String(e)) + ' 原选区保留。');
              }
          },
          samUndo: () => {
            if (!samSession) return;
            if (samSession.prompts.length <= 1) {
              undo.push(faceMap);
              redo = [];
              showFaces(samSession.base);
              resetSam();
              return;
            }
            void runSam({ ...samSession, prompts: samSession.prompts.slice(0, -1) });
          },
          samClear: () => {
            resetSam();
            setSelectionMessage('提示点已清空，当前选区保留，可保存或重新选区。');
          },
          review: reviewOverlays,
          completionBox: drawCompletionBox,
          inspect: (action, value) => {
            if (action === 'all') {
              inspection?.showAll();
              setExplosion(0);
              setSolo(false);
            } else if (action === 'solo') {
              inspection?.isolate();
              setSolo((v) => !v);
            } else if (action === 'hide') inspection?.hideSelected();
            else if (action === 'explode') inspection?.explode(value ?? 0);
            else {
              const distance = camera.position.distanceTo(controls.target),
                direction =
                  action === 'back'
                    ? new THREE.Vector3(0, 0.15, -1)
                    : action === 'under'
                      ? new THREE.Vector3(0, -1, 0.01)
                      : new THREE.Vector3(0, 0.15, 1);
              camera.clearViewOffset();
              camera.position
                .copy(controls.target)
                .add(direction.normalize().multiplyScalar(distance));
              camera.updateProjectionMatrix();
              controls.update();
            }
            selectPart(selectedRef.current);
            if (Object.keys(faceMap).length) showFaces(faceMap);
            dirty = true;
          },
          expandPoint: () => {
            if (lastPoint) choosePoint(lastPoint.mesh, lastPoint.face, lastPoint.base);
          },
          clear: () => {
            resetSam();
            undo.push(faceMap);
            if (undo.length > 20) undo.shift();
            redo = [];
            showFaces({});
            lastPoint = undefined;
            setHasPointSeed(false);
            setSelectionMessage('选择已清空。');
          },
          undo: () => {
            resetSam();
            const value = undo.pop();
            if (value) {
              redo.push(faceMap);
              showFaces(value);
              lastPoint = undefined;
              setHasPointSeed(false);
              setSelectionMessage('已撤销上一次选择。');
            }
          },
          redo: () => {
            resetSam();
            const value = redo.pop();
            if (value) {
              undo.push(faceMap);
              showFaces(value);
              lastPoint = undefined;
              setHasPointSeed(false);
              setSelectionMessage('已恢复上一次选择。');
            }
          },
          fit: async () => {
            if (!model || !referenceRef.current || fitActive) return;
            const fitUrl = referenceRef.current;
            fitActive = true;
            setFitting(true);
            controls.enabled = false;
            if (faceHelper) faceHelper.visible = false;
            try {
              const result = await fitReference(
                renderer,
                model,
                camera,
                fitUrl,
                (message) => {
                  if (disposed || referenceRef.current !== fitUrl)
                    throw new Error('参考图已切换，请重新拟合');
                  setFitMessage(message);
                },
                fitAbort.signal,
              );
              if (disposed) return;
              controls.target.fromArray(result.target);
              controls.update();
              setOverlay(true);
              setFitMessage(
                `轮廓 IoU ${(result.initial_silhouette_iou * 100).toFixed(1)}% → ${(result.silhouette_iou * 100).toFixed(1)}% · ${result.silhouette_iou < 0.65 ? '偏差较大，请手动调整 · ' : ''}仅当前视图，不代表模型准确率`,
              );
              const blob = new Blob([JSON.stringify({ ...result, model_url: url }, null, 2)], {
                  type: 'application/json',
                }),
                link = document.createElement('a');
              link.href = URL.createObjectURL(blob);
              link.download = 'reference-fit.json';
              link.click();
              setTimeout(() => URL.revokeObjectURL(link.href), 1000);
            } catch (error) {
              if (!disposed) setFitMessage(error instanceof Error ? error.message : String(error));
            } finally {
              fitActive = false;
              dirty = true;
              if (!disposed) setFitting(false);
              controls.enabled = ['orbit', 'smart'].includes(toolRef.current);
              if (faceHelper) faceHelper.visible = true;
            }
          },
        };
        selectPart(selectedRef.current);
        drawCompletionBox();
        setLoading(false);
        loaded.current?.();
      },
      undefined,
      () => {
        if (!disposed) {
          setError('模型加载失败，请检查文件或重新打开任务。');
          setLoading(false);
        }
      },
    );
    let pointerStart: { x: number; y: number } | undefined;
    let points: { x: number; y: number }[] = [];
    const localPoint = (event: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    };
    const down = (event: PointerEvent) => {
      if (fitActive || disabledRef.current) return;
      pointerStart = { x: event.clientX, y: event.clientY };
      if (['brush', 'box'].includes(toolRef.current)) {
        controls.enabled = false;
        points = [localPoint(event)];
        renderer.domElement.setPointerCapture(event.pointerId);
      }
    };
    const move = (event: PointerEvent) => {
      if (!pointerStart || ['orbit', 'smart', 'sam'].includes(toolRef.current)) return;
      if (!points.length) return;
      const point = localPoint(event);
      if (
        toolRef.current === 'brush' &&
        points.length < 200 &&
        Math.hypot(point.x - points[points.length - 1].x, point.y - points[points.length - 1].y) > 5
      )
        points.push(point);
      if (toolRef.current === 'box')
        setGestureBox({
          left: Math.min(points[0].x, point.x),
          top: Math.min(points[0].y, point.y),
          width: Math.abs(points[0].x - point.x),
          height: Math.abs(points[0].y - point.y),
        });
    };
    const up = async (event: PointerEvent) => {
      const start = pointerStart;
      pointerStart = undefined;
      if (disabledRef.current) {
        setGestureBox(undefined);
        return;
      }
      if (model && start && ['brush', 'box'].includes(toolRef.current) && points.length) {
        resetSam();
        points.push(localPoint(event));
        undo.push(faceMap);
        if (undo.length > 20) undo.shift();
        redo = [];
        const rect = renderer.domElement.getBoundingClientRect();
        try {
          const fresh = screenFaces(
            model,
            camera,
            rect.width,
            rect.height,
            points,
            toolRef.current === 'box',
            24,
            !throughRef.current,
          );
          showFaces(combineFaces(faceMap, fresh, subtractRef.current));
          lastPoint = undefined;
          setHasPointSeed(false);
          setSelectionMessage('');
          dirty = true;
        } catch {
          undo.pop();
          setSelectionMessage('未能完成表面选择，请重试。原选择保留。');
        }
        pointerStart = undefined;
        setGestureBox(undefined);
        return;
      }
      if (!model || !start || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 5)
        return;
      const rect = renderer.domElement.getBoundingClientRect();
      const pointer = new THREE.Vector2(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        (-(event.clientY - rect.top) / rect.height) * 2 + 1,
      );
      const ray = new THREE.Raycaster();
      ray.setFromCamera(pointer, camera);
      const pickable: THREE.Mesh[] = [];
      model.traverseVisible((child) => {
        if (child instanceof THREE.Mesh && child.userData.formPartId) pickable.push(child);
      });
      const hit = ray.intersectObjects(pickable, false)[0];
      pointerStart = undefined;
      if (!hit) {
        if (['smart', 'sam'].includes(toolRef.current)) setSelectionMessage('请点击模型表面。');
        return;
      }
      if (
        toolRef.current === 'sam' &&
        jobId &&
        hit.object instanceof THREE.Mesh &&
        typeof hit.faceIndex === 'number'
      ) {
        const mode = promptModeRef.current;
        if (mode === 'negative' && !samSession) {
          setSelectionMessage('请先点击一个要保留的位置。');
          return;
        }
        const fresh = mode === 'replace' || !samSession;
        const mesh = fresh ? hit.object : samSession!.mesh;
        if (mode === 'positive' && mesh !== hit.object) {
          setSelectionMessage('追加保留点需在同一原始网格内，其他已有部件可直接点选。');
          return;
        }
        if (!fresh && samSession!.prompts.length >= 24) {
          setSelectionMessage('最多支持 24 个提示点，请撤销旧点后继续。');
          return;
        }
        if (mode === 'negative' && hit.object === mesh && samSession!.seed === hit.faceIndex) {
          setSelectionMessage('第一个保留点不能同时排除，请换点或开始新选区。');
          return;
        }
        const prompt: SurfacePrompt = {
          mesh: hit.object,
          local: hit.object.worldToLocal(hit.point.clone()),
          face: hit.faceIndex,
          label: mode === 'negative' ? 0 : 1,
        };
        const next: Session = fresh
          ? { mesh, seed: hit.faceIndex, prompts: [prompt], base: faceMap }
          : { ...samSession!, prompts: [...samSession!.prompts, prompt] };
        await runSam(next);
        return;
      }
      if (
        toolRef.current === 'smart' &&
        hit.object instanceof THREE.Mesh &&
        typeof hit.faceIndex === 'number'
      ) {
        const meshes: THREE.Mesh[] = [];
        model.traverseVisible((child) => {
          if (child instanceof THREE.Mesh && child.userData.formPartId) meshes.push(child);
        });
        if (meshes.length > 1 && hit.object.userData.formSelectionRole !== 'remainder') {
          undo.push(faceMap);
          if (undo.length > 20) undo.shift();
          redo = [];
          showFaces({});
          pickCallback.current?.(hit.object.userData.formPartId);
          setSelectionMessage('已选中已有部件，可直接换材质。');
          lastPoint = undefined;
          setHasPointSeed(false);
        } else choosePoint(hit.object, hit.faceIndex);
      } else pickCallback.current?.(hit.object.userData.formPartId);
    };
    renderer.domElement.addEventListener('pointerdown', down);
    renderer.domElement.addEventListener('pointermove', move);
    renderer.domElement.addEventListener('pointerup', up);
    const cancel = () => {
      pointerStart = undefined;
      points = [];
      setGestureBox(undefined);
    };
    renderer.domElement.addEventListener('pointercancel', cancel);
    function animate() {
      frame = requestAnimationFrame(animate);
      if (!fitActive) {
        controls.enabled = ['orbit', 'smart', 'sam'].includes(toolRef.current);
        const changed = controls.update();
        if (changed || dirty) {
          renderer.render(scene, camera);
          dirty = false;
        }
      }
    }
    animate();
    return () => {
      disposed = true;
      fitAbort.abort();
      cancelAnimationFrame(frame);
      observer.disconnect();
      controls.dispose();
      clearInferred();
      materialPreview?.dispose();
        for (const helper of [boundaryHelper, seamHelper, promptHelper,completionHelper])
        if (helper) {
          helper.geometry.dispose();
          (helper.material as THREE.Material).dispose();
        }
      setPromptCounts({ positive: 0, negative: 0 });
      setAvailableRanges([]);
      inspection?.dispose();
      assistanceCallback.current?.(false);
      renderer.domElement.removeEventListener('pointerdown', down);
      renderer.domElement.removeEventListener('pointermove', move);
      renderer.domElement.removeEventListener('pointerup', up);
      renderer.domElement.removeEventListener('pointercancel', cancel);
      if (faceHelper) {
        faceHelper.geometry.dispose();
        (faceHelper.material as THREE.Material).dispose();
      }
      if (model) disposeModel(model);
      if (selectionHelper) {
        selectionHelper.geometry.dispose();
        (selectionHelper.material as THREE.Material).dispose();
      }
      if (helper) {
        helper.geometry.dispose();
        (Array.isArray(helper.material) ? helper.material : [helper.material]).forEach((m) =>
          m.dispose(),
        );
      }
      environment.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
      controller.current = undefined;
    };
  }, [url, label]);

  return (
    <div className={'viewer' + (onFacesChange||inspectionOnly ? ' has-edit-tools' : '')} data-testid="model-viewer">
      <div className="viewer-canvas" ref={host} />
      {overlay && referenceUrl && (
        <img
          className="reference-overlay"
          src={referenceUrl}
          style={{ opacity: overlayAlpha }}
          alt="参考图叠加"
        />
      )}
      {gestureBox && <div className="face-selection-box" style={gestureBox} />}
      {!url && (
        <div className="viewer-empty">
          <div className="empty-cube">
            <Box size={42} strokeWidth={1.1} />
          </div>
          <strong>下一件作品，在这里呈现</strong>
          <span>上传参考图，选择生成方式后开始</span>
        </div>
      )}
      {loading && (
        <div className="viewer-overlay">
          <LoaderCircle className="spin" size={25} />
          <span>正在加载 3D 模型</span>
        </div>
      )}
      {error && (
        <div className="viewer-overlay viewer-error">
          <AlertCircle size={25} />
          <span>{error}</span>
        </div>
      )}
      {url && (
        <>
          <div className="axis">
            <span className="axis-y">Y</span>
            <span className="axis-x">X</span>
            <span className="axis-z">Z</span>
            <i />
          </div>
          <div className="viewer-tools">
            <button
              title="重置视角"
              aria-label="重置视角"
              onClick={() => controller.current?.reset()}
            >
              <RotateCcw size={17} />
            </button>
            <button
              title="切换网格"
              aria-label="切换网格"
              aria-pressed={grid}
              onClick={() => {
                controller.current?.grid();
                setGrid(!grid);
              }}
            >
              <Grid2X2 size={17} />
            </button>
            <button
              title="全屏查看"
              aria-label="全屏查看"
              onClick={() => {
                const parent = host.current?.parentElement;
                if (document.fullscreenElement) void document.exitFullscreen();
                else
                  void parent
                    ?.requestFullscreen()
                    ?.catch(() => setError('当前浏览器不支持全屏查看'));
              }}
            >
              <Expand size={17} />
            </button>
          </div>
          <span className="viewer-hint">拖动旋转 · 滚轮缩放 · 右键平移</span>
          {inspectionOnly && !onFacesChange && <div className="face-tools" ref={toolsHost}>
            <div className="selection-actions"><button aria-pressed={solo} disabled={!selectedRef.current.length} onClick={()=>controller.current?.inspect('solo')}>仅看选中整体部件</button><button onClick={()=>controller.current?.inspect('all')}>显示所有整体部件</button><button onClick={()=>controller.current?.inspect('back')}>查看背面</button><button onClick={()=>controller.current?.inspect('under')}>查看底面</button></div>
            <p>点击模型或部件名称选中整个候选；拖动旋转检查边界。</p>
          </div>}
          {onFacesChange && (
            <div className="face-tools" ref={toolsHost} data-selected-faces={faceCount}>
              {hasSemanticParts && <label><input type="checkbox" aria-label="显示整体部件分色" disabled={!!materialDraft} checked={partColours} onChange={e=>setPartColours(e.target.checked)}/>显示整体部件分色（不改变材质）</label>}
              <div className="selection-tool-row" role="group" aria-label="模型操作">
                {(
                  [
                    ['orbit', '查看 / 转动'],
                    ['smart', '点选部件'],
                    ...(jobId ? [['sam', 'AI 辅助选区'] as const] : []),
                    ['brush', '涂抹修正'],
                  ] as const
                ).map(([value, name]) => (
                  <button
                    key={value}
                    disabled={fitting || editingDisabled}
                    aria-pressed={tool === value}
                    onClick={() => {
                      setTool(value);
                      setSelectionMessage('');
                    }}
                  >
                    {name}
                  </button>
                ))}
              </div>
              {(['smart', 'sam', 'brush', 'box'].includes(tool) || faceCount > 0) && (
                <div className="selection-actions">
                  {!['smart', 'sam'].includes(tool) && (
                    <>
                      <button
                        disabled={fitting || editingDisabled}
                        aria-pressed={!subtract}
                        onClick={() => setSubtract(false)}
                      >
                        选中
                      </button>
                      <button
                        disabled={fitting || editingDisabled}
                        aria-pressed={subtract}
                        onClick={() => setSubtract(true)}
                      >
                        擦掉多选
                      </button>
                    </>
                  )}
                  <button
                    disabled={fitting || editingDisabled || !selectionHistory.undo}
                    title="撤销上一次选择"
                    onClick={() => controller.current?.undo()}
                  >
                    撤销
                  </button>
                  <button
                    disabled={fitting || editingDisabled || !selectionHistory.redo}
                    title="重做选择"
                    onClick={() => controller.current?.redo()}
                  >
                    重做
                  </button>
                  <button
                    disabled={fitting || editingDisabled || !faceCount}
                    onClick={() => controller.current?.clear()}
                  >
                    清空
                  </button>
                </div>
              )}
              <p className="selection-guidance">
                {tool === 'orbit'
                  ? '拖动旋转，点击选择已有部件。'
                  : tool === 'sam'
                    ? '点击一个部件，本地 SAM 2 从多个可见视角提出候选；不会自动识别或补出隐藏零件。'
                    : tool === 'smart'
                      ? '点击目标位置，尝试选出独立区域或连续平面；拖动仍可转动模型。'
                      : through
                        ? '当前会选择背后的表面，请检查是否误选。'
                        : tool === 'brush'
                          ? '涂抹想编辑的位置，只选择看得见的表面。'
                          : '拖出矩形框，只选择框内看得见的表面。'}
                {faceCount > 0 ? ' 已选中局部，可在部件面板命名并保存。' : ''}
              </p>
              {selectionMessage && <p role="status">{selectionMessage}</p>}
              {tool === 'sam' && (
                <div className="sam-refinement" role="group" aria-label="AI 选区修正">
                  <div className="selection-actions">
                    {(
                      [
                        ['replace', '开始新选区'],
                        ['positive', '保留这里'],
                        ['negative', '不要这里'],
                      ] as const
                    ).map(([value, label]) => (
                      <button
                        key={value}
                        disabled={editingDisabled || assisting}
                        aria-pressed={promptMode === value}
                        onClick={() => setPromptMode(value)}
                      >
                        {label}
                      </button>
                    ))}
                    <button
                      disabled={editingDisabled || assisting || !promptCounts.positive}
                      onClick={() => controller.current?.samUndo()}
                    >
                      撤销提示点
                    </button>
                    <button
                      disabled={editingDisabled || assisting || !promptCounts.positive}
                      onClick={() => controller.current?.samClear()}
                    >
                      清空提示点
                    </button>
                  </div>
                  <p>
                    保留点 {promptCounts.positive} · 排除点 {promptCounts.negative}
                    。修改点会重新计算；范围切换使用本轮缓存，不生成模型版本。
                  </p>
                  <label>
                    候选范围
                    <select
                      aria-label="AI 候选范围"
                      value={samRange}
                      disabled={editingDisabled || assisting || !availableRanges.length}
                      onChange={(e) => {
                        samRangeRef.current = e.target.value as CandidateRange;
                        setSamRange(samRangeRef.current);
                        controller.current?.samRange();
                      }}
                    >
                      {(['small', 'medium', 'large'] as CandidateRange[]).map((range) => (
                        <option
                          key={range}
                          value={range}
                          disabled={!availableRanges.includes(range)}
                        >
                          {range === 'small' ? '较小' : range === 'medium' ? '适中' : '较大'}范围
                        </option>
                      ))}
                    </select>
                  </label>
                  {availableRanges.length > 0 && (
                    <p>
                      本轮有 {availableRanges.length} 种不同候选；不满足提示或重复的范围不提供。
                    </p>
                  )}
                  <label>
                    <input
                      type="checkbox"
                      aria-label="贴合几何边界"
                      checked={refineBoundary}
                      disabled={editingDisabled || assisting}
                      onChange={(e) => {
                        refineBoundaryRef.current = e.target.checked;
                        setRefineBoundary(e.target.checked);
                        controller.current?.samRange();
                      }}
                    />
                    贴合几何边界，清理突出碎面
                  </label>
                </div>
              )}
              {faceCount > 0 && (
                <label>
                  <input
                    type="checkbox"
                    aria-label="显示选区边界"
                    checked={showBoundary}
                    onChange={(e) => {
                      showBoundaryRef.current = e.target.checked;
                      setShowBoundary(e.target.checked);
                      controller.current?.review();
                    }}
                  />
                  显示橙色选区边界
                </label>
              )}
              {assisting && <p role="status">辅助分割进行中，请等待；切换任务会取消当前请求。</p>}
              <details className="inspection-tools">
                <summary>检查部件与拆解展示</summary>
                <label>
                  <input
                    type="checkbox"
                    aria-label="显示 UV 接缝"
                    checked={showSeams}
                    disabled={editingDisabled}
                    onChange={(e) => {
                      showSeamsRef.current = e.target.checked;
                      setShowSeams(e.target.checked);
                      controller.current?.review();
                    }}
                  />
                  显示蓝色 UV 接缝
                </label>
                {seamMessage && <p role="status">{seamMessage}</p>}
                {hasInferred&&<><label><input type="checkbox" aria-label="显示推测接合面" checked={showInferred} disabled={editingDisabled} onChange={e=>{inferredRef.current=e.target.checked;setShowInferred(e.target.checked);controller.current?.review();}}/>显示推测接合面</label>{showInferred&&<p role="status">橙色面为推测的接合面。隔离部件或查看背面、底面可检查，不代表实物隐藏结构。</p>}</>}
                <div className="selection-actions">
                  <button
                    disabled={editingDisabled || !selectedRef.current.length}
                    aria-pressed={solo}
                    onClick={() => controller.current?.inspect('solo')}
                  >
                    仅看选中部件
                  </button>
                  <button
                    disabled={editingDisabled || !selectedRef.current.length}
                    onClick={() => controller.current?.inspect('hide')}
                  >
                    隐藏选中部件
                  </button>
                  <button
                    disabled={editingDisabled}
                    onClick={() => controller.current?.inspect('all')}
                  >
                    显示全部 / 复位拆解
                  </button>
                  <button
                    disabled={editingDisabled}
                    onClick={() => controller.current?.inspect('front')}
                  >
                    查看正面
                  </button>
                  <button
                    disabled={editingDisabled}
                    onClick={() => controller.current?.inspect('back')}
                  >
                    查看背面
                  </button>
                  <button
                    disabled={editingDisabled}
                    onClick={() => controller.current?.inspect('under')}
                  >
                    查看底面
                  </button>
                </div>
                <label>
                  拆解展示距离
                  <input
                    aria-label="拆解展示距离"
                    type="range"
                    min="0"
                    max="1"
                    step=".05"
                    disabled={editingDisabled}
                    value={explosion}
                    onChange={(e) => {
                      setExplosion(+e.target.value);
                      controller.current?.inspect('explode', +e.target.value);
                    }}
                  />
                </label>
                <p>仅改变查看方式。实际移动或单独导出请在“拆分部件”中操作；底面视角可检查漏选。</p>
              </details>
              {tool === 'smart' && (
                <details className="selection-settings">
                  <summary>点选设置</summary>
                  <label>
                    扩展范围
                    <select
                      aria-label="点选范围"
                      disabled={!hasPointSeed || fitting || editingDisabled}
                      title={hasPointSeed ? '调整当前点选区域' : '请先点击模型，再调整范围'}
                      value={pointRange}
                      onChange={(e) => {
                        const value = e.target.value as SelectionRange;
                        pointRangeRef.current = value;
                        setPointRange(value);
                        controller.current?.expandPoint();
                      }}
                    >
                      <option value="tight">少选一点</option>
                      <option value="normal">正常范围</option>
                      <option value="wide">多选一点</option>
                    </select>
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={appendPoint}
                      onChange={(e) => setAppendPoint(e.target.checked)}
                    />
                    追加到已有选区
                  </label>
                  <p>
                    按几何形状扩展，不能保证识别完整坐垫、桌腿等语义部件。曲面或边界不清时，请用涂抹修正。
                  </p>
                </details>
              )}
              {tool !== 'smart' && tool !== 'orbit' && (
                <details className="selection-settings">
                  <summary>选择设置</summary>
                  <button aria-pressed={tool === 'box'} onClick={() => setTool('box')}>
                    框选区域
                  </button>
                  <label>
                    <input
                      aria-label="同时选择背面"
                      type="checkbox"
                      checked={through}
                      onChange={(e) => {
                        setThrough(e.target.checked);
                        controller.current?.clear();
                        setSelectionMessage('选择方式已切换，请重新选择区域。');
                      }}
                    />
                    同时选择背面（穿透）
                  </label>
                  <p>
                    默认不勾选。只有想连背后的部分一起选时才开启。透明材质也按实体表面遮挡；边缘小面可能需要换角度补选。
                  </p>
                  {faceCount > 0 && <small>当前选择 {faceCount.toLocaleString()} 个三角面</small>}
                </details>
              )}
              {referenceUrl && showReferenceTools && (
                <details className="reference-settings">
                  <summary>原图对照设置</summary>
                  <p>把原图叠在模型上检查轮廓；近似匹配视角可能有偏差。</p>
                  <button
                    disabled={fitting || editingDisabled}
                    onClick={() => void controller.current?.fit()}
                  >
                    {fitting ? '正在调整…' : '自动调整到相近视角'}
                  </button>
                  <label>
                    <input
                      type="checkbox"
                      checked={overlay}
                      onChange={(e) => setOverlay(e.target.checked)}
                    />
                    叠加原图
                  </label>
                  {overlay && (
                    <input
                      aria-label="参考图透明度"
                      type="range"
                      min="0"
                      max="1"
                      step=".05"
                      value={overlayAlpha}
                      onChange={(e) => setOverlayAlpha(+e.target.value)}
                    />
                  )}
                  <span role="status">{fitMessage}</span>
                </details>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

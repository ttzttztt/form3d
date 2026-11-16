import { useEffect, useRef, useState } from 'react';
import { api, post } from './types';
import type { FaceSelection } from './faceSelection';
import Viewer from './Viewer';
import ReconstructionCompare from './ReconstructionCompare';
import CompletePartPanel from './CompletePartPanel';
import SemanticPartsPanel from './SemanticPartsPanel';
import ReconstructPartsPanel from './ReconstructPartsPanel';
import PartRegenerationPanel from './PartRegenerationPanel';
import { sameMaterial } from './materialDraft';
import type { MaterialDraft, MaterialSettings, PreviewStatus } from './materialDraft';
const operationNames: Record<string, string> = {
  material: '换材质',
  face_group: '保存选区',
  rename: '部件改名',
  plane_group: '按位置分组',
  connected_components: '按连通片分组',
  decimate: '减小面数',
  optimize_mesh: '保形减面',
  restore_original: '恢复原始模型',
  restore_version: '恢复历史版本',
  auto_parts: '完整分组候选',
  merge_parts: '合并编辑部件',
  assign_faces: '调整面归属',
  repair_geometry: '保守修复',
  unwrap_uv: '曲面 UV 展开',
  translate_parts: '移动部件',
  complete_part: '完整部件重建（含推测接合面）',
  separate_solids: '拆分已有闭合体',
  semantic_parts: 'AI 整体部件识别',
  reconstruct_parts: '生成独立部件候选',
  replace_part: '按原图重生成并替换部件',
};
interface Part {
  id: string;
  name: string;
  triangles: number;
  group_kind: string;
  base_color_factor: number[];
  metalness: number;
  roughness: number;
  material_signature?: string;
  source_part_id?: string;
  selection_role?: string;
  completion_role?: string;
  logical_group_id?: string;
}
interface Catalog {
  manifest?: {
    operation?: {
      part_group_id?: string;
      part_group_ids?: string[];
      faces_after?: number;
      target_reached?: boolean;
    };
  };
  version: string;
  latest_version: string;
  model_url: string;
  original_url: string;
  parts: Part[];
  editor_review_status: string;
  metrics: { parts: number; triangles: number; bytes: number };
  versions: {
    id: string;
    operation: string;
    model_url: string;
    manifest_url: string;
    note?: string;
    archived?: boolean;
  }[];
  reference_views: { id: string; url: string; role: string }[];
  groups?: {
    id: string;
    name: string;
    part_ids: string[];
    triangles: number;
    proposal_status: string;
    material_count: number;
    has_inferred_interfaces?: boolean;
    semantic_color?: string;
    semantic_kind?: string;
  }[];
  object_category?: string;
}
interface Props {
  jobId: string;
  pickedPart?: string;
  onPreview: (url: string, metrics: Catalog['metrics'], reviewStatus: string) => void;
  onSelect: (part: string) => void;
  faces?: FaceSelection[];
  onReference?: (url: string) => void;
  onScope?: (ids: string[]) => void;
  onMaterialDraft?: (draft?: MaterialDraft) => void;
  previewStatus?: PreviewStatus;
  onBusyChange?: (busy: boolean) => void;
  externalBusy?: boolean;
  onCompletionBounds?: (bounds?: number[][]) => void;
}
export default function AssetEditor({
  jobId,
  pickedPart,
  onPreview,
  onSelect,
  faces = [],
  onReference,
  onScope,
  onMaterialDraft,
  previewStatus = 'idle',
  onBusyChange,
  externalBusy = false,
  onCompletionBounds,
}: Props) {
  const [catalog, setCatalog] = useState<Catalog>();
  const [selected, setSelected] = useState('all');
  const [tab, setTab] = useState<'material' | 'parts' | 'more'>('material');
  const [savedSelection, setSavedSelection] = useState<string[]>([]);
  const [checkedGroups, setCheckedGroups] = useState<string[]>([]),
    [category, setCategory] = useState('auto'),
    [targetPart, setTargetPart] = useState('');
  const [repairStrength, setRepairStrength] = useState('gentle'),
    [quality, setQuality] = useState<{
      whole_model: Record<string, number | boolean>;
      limits: string[];
    }>();
  const [draftDirty, setDraftDirty] = useState(false),
    [draftUndo, setDraftUndo] = useState<MaterialSettings[]>([]),
    [draftRedo, setDraftRedo] = useState<MaterialSettings[]>([]);
  const baseline = useRef<MaterialSettings>();
  useEffect(() => {
    if (pickedPart) setTab('material');
  }, [pickedPart]);
  useEffect(() => {
    if (faces.length) {
      setTab('parts');
      setPartName('');
    }
  }, [faces.length > 0]);
  const [color, setColor] = useState('#b79370');
  const [roughness, setRoughness] = useState(0.7);
  const [metalness, setMetalness] = useState(0);
  const [opacity, setOpacity] = useState(1);
  const [mode, setMode] = useState('replace');
  const [axis, setAxis] = useState('y');
  const [position, setPosition] = useState(0.5);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    onBusyChange?.(busy);
  }, [busy, onBusyChange]);
  useEffect(() => () => onBusyChange?.(false), []);
  const [error, setError] = useState('');
  const [unwrapMode, setUnwrapMode] = useState('auto');
  const [translation, setTranslation] = useState([0, 0, 0]),
    [showGenerationCompare, setShowGenerationCompare] = useState(false);
  const [message, setMessage] = useState('');
  const [partName, setPartName] = useState(''),
    [note, setNote] = useState(''),
    [lodRatio, setLodRatio] = useState(0.5);
  const [targetFaces, setTargetFaces] = useState(100000);
  const [textures, setTextures] = useState<Record<string, string>>({}),
    [uvScale, setUvScale] = useState(1),
    [uvRotation, setUvRotation] = useState(0);
  const [showArchived, setShowArchived] = useState(false),
    [compareVersion, setCompareVersion] = useState('original'),
    [diff, setDiff] = useState('');
  const [compareModel, setCompareModel] = useState('');
  const groups: NonNullable<Catalog['groups']> =
    catalog?.groups ??
    catalog?.parts.map((p) => ({
      id: p.id,
      name: p.name,
      part_ids: [p.id],
      triangles: p.triangles,
      proposal_status: 'existing',
      material_count: 1,
      has_inferred_interfaces: false,
    })) ??
    [];
  const scopeIds =
    selected === 'all'
      ? []
      : selected === 'saved_selection'
        ? savedSelection
        : selected.startsWith('g:')
          ? (groups.find((g) => g.id === selected.slice(2))?.part_ids ?? [])
          : [selected];
  const mergeIds = groups.filter((g) => checkedGroups.includes(g.id)).flatMap((g) => g.part_ids);
  const scopeKind = groups.find((g) =>
    g.part_ids.some((id) => scopeIds.includes(id)),
  )?.semantic_kind;
  const scopeMaterialCount = new Set(
    catalog?.parts
      .filter((p) => !scopeIds.length || scopeIds.includes(p.id))
      .map((p) => p.material_signature ?? JSON.stringify(p.base_color_factor)),
  ).size;
  const snapshot = (): MaterialSettings => ({
    color,
    roughness,
    metalness,
    opacity,
    mode,
    textures,
    uvScale,
    uvRotation,
  });
  function setMaterial(value: MaterialSettings) {
    setColor(value.color);
    setRoughness(value.roughness);
    setMetalness(value.metalness);
    setOpacity(value.opacity);
    setMode(value.mode);
    setTextures(value.textures);
    setUvScale(value.uvScale);
    setUvRotation(value.uvRotation);
    setDraftDirty(!baseline.current || !sameMaterial(value, baseline.current));
  }
  function updateMaterial(patch: Partial<MaterialSettings>) {
    setDraftUndo((old) => [...old, snapshot()].slice(-30));
    setDraftRedo([]);
    setMaterial({ ...snapshot(), ...patch });
  }
  const materialScopeKey = jobId + ':' + catalog?.version + ':' + selected;
  const materialScopeRef = useRef(materialScopeKey);
  materialScopeRef.current = materialScopeKey;
  async function exampleMaterial(name: string) {
    const captured = materialScopeKey;
    setBusy(true);
    setError('');
    try {
      const preset = await post<MaterialSettings & { provenance: string }>(
        `/api/material-presets/${name}/prepare`,
      );
      if (materialScopeRef.current !== captured) return;
      updateMaterial({
        color: preset.color,
        roughness: preset.roughness,
        metalness: preset.metalness,
        opacity: preset.opacity,
        mode: preset.mode,
        textures: preset.textures,
        uvScale: preset.uvScale,
        uvRotation: preset.uvRotation,
      });
      setMessage('已预览示例材质；可调整花纹方向和大小，保存后才写入模型。示例不代表原商品面料。');
    } catch (e) {
      if (materialScopeRef.current === captured)
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (materialScopeRef.current === captured) setBusy(false);
    }
  }
  function undoMaterial() {
    const value = draftUndo.at(-1);
    if (!value) return;
    setDraftRedo((old) => [...old, snapshot()]);
    setDraftUndo((old) => old.slice(0, -1));
    setMaterial(value);
  }
  function redoMaterial() {
    const value = draftRedo.at(-1);
    if (!value) return;
    setDraftUndo((old) => [...old, snapshot()]);
    setDraftRedo((old) => old.slice(0, -1));
    setMaterial(value);
  }
  function cancelMaterial() {
    if (baseline.current) setMaterial(baseline.current);
    setDraftUndo([]);
    setDraftRedo([]);
    setDraftDirty(false);
  }
  const validMaterial =
    Number.isFinite(uvScale) &&
    uvScale >= 0.05 &&
    uvScale <= 100 &&
    Number.isFinite(uvRotation) &&
    Math.abs(uvRotation) <= 180;
  useEffect(() => {
    onScope?.(scopeIds);
  }, [selected, catalog?.version, savedSelection]);
  useEffect(() => {
    onMaterialDraft?.(
      draftDirty && validMaterial ? { ...snapshot(), part_ids: scopeIds } : undefined,
    );
  }, [
    draftDirty,
    color,
    roughness,
    metalness,
    opacity,
    mode,
    textures,
    uvScale,
    uvRotation,
    selected,
    catalog?.version,
    savedSelection,
  ]);
  useEffect(() => () => onMaterialDraft?.(undefined), []);
  useEffect(() => {
    setNote(catalog?.versions.find((v) => v.id === catalog.version)?.note || '');
    setDiff('');
    setCompareModel('');
  }, [catalog?.version]);
  useEffect(() => {
    let alive = true;
    setCatalog(undefined);
    setSelected('all');
    setError('');
    api<Catalog>('/api/jobs/' + jobId + '/asset')
      .then((value) => {
        if (alive) {
          setCatalog(value);
          onPreview(value.model_url, value.metrics, value.editor_review_status);
        }
      })
      .catch((reason) => {
        if (alive) setError(String(reason.message));
      });
    return () => {
      alive = false;
    };
  }, [jobId]);
  useEffect(() => {
    if (pickedPart && catalog?.parts.some((part) => part.id === pickedPart)) {
      const group = groups.find((g) => g.part_ids.includes(pickedPart));
      setSelected(group ? 'g:' + group.id : pickedPart);
    }
  }, [pickedPart, catalog]);
  useEffect(() => {
    const part =
      selected === 'all'
        ? catalog?.parts[0]
        : catalog?.parts.find((item) => item.id === scopeIds[0]);
    if (!part) return;
    const channel = (value: number) =>
      Math.round(
        Math.max(
          0,
          Math.min(1, value <= 0.0031308 ? value * 12.92 : 1.055 * value ** (1 / 2.4) - 0.055),
        ) * 255,
      )
        .toString(16)
        .padStart(2, '0');
    const value: MaterialSettings = {
      color: '#' + part.base_color_factor.slice(0, 3).map(channel).join(''),
      roughness: part.roughness,
      metalness: part.metalness,
      opacity: part.base_color_factor[3] ?? 1,
      mode: 'replace',
      textures: {},
      uvScale: 1,
      uvRotation: 0,
    };
    baseline.current = value;
    setMaterial(value);
    setDraftUndo([]);
    setDraftRedo([]);
    setDraftDirty(false);
  }, [catalog, selected]);
  useEffect(() => {
    setQuality(undefined);
    setCheckedGroups([]);
    setTargetPart('');
  }, [catalog?.version]);
  useEffect(() => {
    if (selected !== 'all' && !faces.length) {
      const part = catalog?.parts.find((p) => p.id === scopeIds[0]);
      if (part) setPartName(part.name);
    }
  }, [selected, catalog?.version]);
  async function edit(operation: string, extra: Record<string, unknown> = {}) {
    if (!catalog) return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const result = await post<Catalog>('/api/jobs/' + jobId + '/asset/versions', {
        base_version: operation.startsWith('restore_') ? catalog.latest_version : catalog.version,
        source_version: catalog.version,
        operation,
        part_ids: operation === 'merge_parts' ? mergeIds : scopeIds,
        color,
        roughness,
        metalness,
        opacity,
        mode,
        axis,
        position,
        face_selection: faces,
        name: ['rename', 'face_group', 'assign_faces', 'merge_parts'].includes(operation)
          ? partName
          : '',
        category,
        target_part_id: targetPart,
        repair_strength: repairStrength,
        note,
        ...textures,
        uv_scale: uvScale,
        uv_rotation: uvRotation,
        lod_ratio: lodRatio,
        ...extra,
      });
      setCatalog(result);
      if (operation === 'semantic_parts') {
        setSelected('all');
        setSavedSelection([]);
        setTab('material');
        onSelect('');
      } else if (
        operation === 'complete_part' ||
        operation === 'separate_solids' ||
        operation === 'reconstruct_parts' ||
        operation === 'replace_part'
      ) {
        const op = result.manifest?.operation;
        const groups = op?.part_group_ids ?? (op?.part_group_id ? [op.part_group_id] : []);
        const ids = result.parts
          .filter((p) => p.logical_group_id && groups.includes(p.logical_group_id))
          .map((p) => p.id);
        setSavedSelection(ids);
        setSelected('saved_selection');
        setTab(operation === 'replace_part' ? 'material' : 'parts');
        onCompletionBounds?.(undefined);
      } else if (operation === 'auto_parts') {
        setSelected('all');
        setSavedSelection([]);
        setTab('parts');
      } else if (operation === 'merge_parts') {
        const group = result.groups?.find((g) => mergeIds.every((id) => g.part_ids.includes(id)));
        setSelected(group ? 'g:' + group.id : 'all');
        setSavedSelection([]);
        setTab('parts');
      } else if (operation === 'assign_faces') {
        const ids = result.parts
          .filter(
            (p) =>
              p.selection_role === 'selected' && faces.some((s) => s.part_id === p.source_part_id),
          )
          .map((p) => p.id);
        const group = result.groups?.find((g) =>
          targetPart ? g.part_ids.includes(targetPart) : ids.some((id) => g.part_ids.includes(id)),
        );
        setSelected(group ? 'g:' + group.id : ids.length ? 'saved_selection' : 'all');
        setSavedSelection(ids);
        setTab('material');
      } else if (operation === 'face_group') {
        const ids = result.parts
          .filter(
            (p) =>
              p.selection_role === 'selected' && faces.some((s) => s.part_id === p.source_part_id),
          )
          .map((p) => p.id);
        setSavedSelection(ids);
        setSelected(ids.length ? 'saved_selection' : 'all');
        setTab('material');
      } else if (operation.startsWith('restore_')) {
        setSelected('all');
        setSavedSelection([]);
      } else if (
        selected !== 'saved_selection' &&
        !result.parts.some((p) => p.id === selected) &&
        !result.groups?.some((g) => 'g:' + g.id === selected)
      )
        setSelected('all');
      onSelect('');
      onPreview(result.model_url, result.metrics, result.editor_review_status);
      setMessage(
        ['face_group', 'assign_faces'].includes(operation)
          ? '已保存为局部部件，现在换材质只影响刚保存的选区。'
          : operation === 'auto_parts'
            ? '已生成包含侧面和背面的分组候选，请逐个旋转检查并修正。'
            : operation === 'repair_geometry'
              ? '已生成保守修复版本，请重新检查并对比；为避免开口，部分坏面可能保留。'
              : operation === 'replace_part'
                ? '新部件已保存并选中，现在可整块换材质；形状与隐藏表面仍需确认。'
                : operation === 'optimize_mesh'
                  ? `保形减面后为 ${result.manifest?.operation?.faces_after?.toLocaleString()} 面${result.manifest?.operation?.target_reached ? '，已达到目标。' : '；部分网格因保护保留，尚未达到目标。'}`
                  : '修改已保存，原模型与历史版本保留。',
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      if (
        operation === 'semantic_parts' ||
        operation === 'reconstruct_parts' ||
        operation === 'replace_part'
      )
        throw reason;
    } finally {
      setBusy(false);
    }
  }
  const presets = [
    ['哑光', 0, 0.85, 1],
    ['金属', 1, 0.22, 1],
    ['塑料', 0, 0.32, 1],
    ['织物近似', 0, 1, 1],
    ['透明近似', 0, 0.08, 0.2],
  ] as const;
  const history = !!catalog && catalog.version !== catalog.latest_version;
  const generatedWholeParts =
    !!catalog?.parts.length &&
    catalog.parts.every(
      (part) => part.group_kind === 'planned_native_part' && !!part.logical_group_id,
    );
  async function uploadImage(file: File): Promise<string> {
    const data = new FormData();
    data.append('file', file);
    const value = await api<{ id: string }>('/api/images', { method: 'POST', body: data });
    return value.id;
  }
  function updateReferences(value: Catalog) {
    setCatalog((old) => (old ? { ...old, reference_views: value.reference_views } : value));
  }
  async function uploadMap(slot: string, file?: File) {
    if (!file) return;
    setBusy(true);
    setError('');
    try {
      const id = await uploadImage(file);
      updateMaterial({ textures: { ...textures, [slot]: id } });
    } catch (error) {
      setError(String(error));
    } finally {
      setBusy(false);
    }
  }
  async function annotate(archived: boolean) {
    if (!catalog) return;
    setBusy(true);
    try {
      setCatalog(
        await post<Catalog>(`/api/jobs/${jobId}/assets/${catalog.version}/annotation`, {
          note,
          archived,
        }),
      );
      setMessage('版本备注与归档状态已保存，历史文件保留。');
    } catch (error) {
      setError(String(error));
    } finally {
      setBusy(false);
    }
  }
  async function review(decision: 'accept' | 'reject') {
    if (!catalog) return;
    setBusy(true);
    setError('');
    try {
      const value = await post<Catalog>(
        '/api/jobs/' + jobId + '/assets/' + catalog.version + '/review',
        { decision },
      );
      setCatalog(value);
      onPreview(value.model_url, value.metrics, value.editor_review_status);
      setMessage(
        decision === 'accept'
          ? '当前编辑版本已记录为通过审核。'
          : '当前编辑版本已退回，原版本保留。',
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="asset-editor" aria-label="部件与材质编辑">
      <fieldset className="editor-busy-wrapper" disabled={externalBusy}>
        <strong>部件与材质编辑</strong>
        <div className="editor-tabs" role="group" aria-label="编辑功能">
          {(
            [
              ['material', '换材质'],
              ['parts', '拆分部件'],
              ['more', '更多操作'],
            ] as const
          ).map(([value, label]) => (
            <button key={value} aria-pressed={tab === value} onClick={() => setTab(value)}>
              {label}
            </button>
          ))}
        </div>
        {tab === 'material' && <p>先选要修改的部件，再换颜色或材质。</p>}
        {tab === 'parts' && (
          <p>
            {generatedWholeParts
              ? '已有部件候选，可直接选择、单独导出或移动；分组有误时再修正。'
              : '先生成完整分组候选，再逐个检查；也可涂抹拆出或移动局部。'}
          </p>
        )}
        {tab === 'more' && <p>历史版本、文件优化和原图对照设置。</p>}
        {draftDirty && tab !== 'material' && (
          <p className="draft-status">
            有未保存的材质预览，先保存或取消后再改分组。
            <button onClick={cancelMaterial}>取消预览</button>
          </p>
        )}
        {tab === 'material' && scopeMaterialCount > 1 && (
          <p>当前范围含多种材质，参数显示第一种。保存会统一当前范围；取消预览可恢复原样。</p>
        )}
        {catalog && (
          <>
            {tab !== 'more' && generatedWholeParts && (
              <p role="status">
                已按生成计划分为 {groups.length}{' '}
                个部件候选。点击下方部件即可换材质；形状与隐藏结构仍需核对。
              </p>
            )}
            {((tab !== 'more' && !generatedWholeParts) ||
              (tab === 'more' && generatedWholeParts)) && (
              <SemanticPartsPanel
                jobId={jobId}
                version={catalog.version}
                category={catalog.object_category ?? 'auto'}
                disabled={busy || history || draftDirty || externalBusy}
                onSave={(scanId) =>
                  edit('semantic_parts', {
                    semantic_scan_id: scanId,
                    part_ids: [],
                    face_selection: [],
                    note: 'AI 多视角整体实例分组；分色不改变实际材质，隐藏接口未重建',
                  })
                }
              />
            )}
            {tab === 'more' && (
              <details open>
                <summary>历史版本</summary>
                <label>
                  查看版本
                  <select
                    aria-label="查看编辑版本"
                    value={catalog.version}
                    disabled={busy}
                    onChange={(event) => {
                      setError('');
                      void api<Catalog>(
                        '/api/jobs/' + jobId + '/asset?version=' + event.target.value,
                      )
                        .then((value) => {
                          setCatalog(value);
                          setSelected('all');
                          setSavedSelection([]);
                          onSelect('');
                          onPreview(value.model_url, value.metrics, value.editor_review_status);
                        })
                        .catch((reason) => setError(reason.message));
                    }}
                  >
                    <option value="original">原始生成版本</option>
                    {catalog.versions
                      .filter((v) => showArchived || !v.archived || v.id === catalog.version)
                      .map((version, index) => (
                        <option key={version.id} value={version.id}>
                          {index + 1} · {operationNames[version.operation] || version.operation}{' '}
                          {version.archived ? '· 已归档' : ''}{' '}
                          {version.note ? '· ' + version.note.slice(0, 30) : ''}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={showArchived}
                    onChange={(e) => setShowArchived(e.target.checked)}
                  />
                  显示归档版本
                </label>
              </details>
            )}
            {tab !== 'more' && (
              <>
                <div className="parts-list" role="group" aria-label="部件清单">
                  <div className="parts-list-heading">
                    <strong>部件 · {groups.length}</strong>
                    <button
                      disabled={busy || history || draftDirty}
                      onClick={() => setTab('parts')}
                    >
                      分组 / 修正
                    </button>
                  </div>
                  {groups.map((group, index) => (
                    <div
                      className={
                        'part-row ' +
                        (group.part_ids.some((id) => scopeIds.includes(id)) ? 'selected' : '')
                      }
                      key={group.id}
                    >
                      {tab === 'parts' && (
                        <input
                          aria-label={'合并选择 ' + group.name}
                          type="checkbox"
                          checked={checkedGroups.includes(group.id)}
                          disabled={busy}
                          onChange={(e) =>
                            setCheckedGroups((old) =>
                              e.target.checked
                                ? [...old, group.id]
                                : old.filter((id) => id !== group.id),
                            )
                          }
                        />
                      )}
                      <button
                        disabled={busy}
                        aria-label={'选择部件 ' + group.name}
                        onClick={() => {
                          onSelect('');
                          setSelected('g:' + group.id);
                        }}
                      >
                        <span>
                          {'semantic_color' in group && group.semantic_color && (
                            <i
                              className="semantic-colour"
                              style={{ background: group.semantic_color, marginRight: 6 }}
                            />
                          )}
                          {group.name.startsWith('geometry') ? `其余结构 ${index + 1}` : group.name}
                        </span>
                        {group.proposal_status === 'review_required' && <small>自动建议</small>}
                        {group.material_count > 1 && <small>多材质</small>}
                        {group.has_inferred_interfaces && <small>含推测接合面</small>}
                      </button>
                    </div>
                  ))}
                </div>
                <label>
                  编辑范围
                  <select
                    aria-label="编辑范围"
                    disabled={busy}
                    value={selected}
                    onChange={(event) => {
                      setSelected(event.target.value);
                      onSelect('');
                    }}
                  >
                    <option value="all">整个模型</option>
                    {savedSelection.length > 0 && (
                      <option value="saved_selection">刚保存的部件</option>
                    )}
                    {groups.map((group) => (
                      <option key={group.id} value={'g:' + group.id}>
                        {group.name}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
            {tab === 'parts' && (
              <>
                <PartRegenerationPanel
                  key={JSON.stringify({ jobId, version: catalog.version, partIds: scopeIds })}
                  jobId={jobId}
                  version={catalog.version}
                  partIds={scopeIds}
                  kind={
                    ['seat', 'cushion'].includes(
                      groups.find((g) => g.part_ids.some((id) => scopeIds.includes(id)))
                        ?.semantic_kind ?? '',
                    )
                      ? 'cushion'
                      : groups.find((g) => g.part_ids.some((id) => scopeIds.includes(id)))
                            ?.semantic_kind === 'bolster'
                        ? 'bolster'
                        : 'pillow'
                  }
                  canPreserveSurface={scopeKind === 'seat'}
                  autoSupported={['seat', 'cushion', 'pillow', 'bolster'].includes(scopeKind ?? '')}
                  disabled={
                    busy ||
                    history ||
                    draftDirty ||
                    externalBusy ||
                    faces.length > 0 ||
                    !scopeIds.length
                  }
                  onSave={(id) =>
                    edit('replace_part', {
                      regeneration_preview_id: id,
                      part_ids: scopeIds,
                      face_selection: [],
                      note: '按原图重生成部件；隐藏结构与放置位置含推测，保留原版本',
                    })
                  }
                />
                {groups.length > 1 && (
                  <ReconstructPartsPanel
                    jobId={jobId}
                    version={catalog.version}
                    partIds={scopeIds.length ? scopeIds : catalog.parts.map((p) => p.id)}
                    disabled={busy || history || draftDirty || externalBusy || faces.length > 0}
                    onSave={(previewId) =>
                      edit('reconstruct_parts', {
                        completion_preview_id: previewId,
                        part_ids: scopeIds.length ? scopeIds : catalog.parts.map((p) => p.id),
                        face_selection: [],
                        note: '按已保存整体分组重建；闭合及偏差保护通过不代表语义或真实隐藏结构正确',
                      })
                    }
                  />
                )}
                <CompletePartPanel
                  jobId={jobId}
                  version={catalog.version}
                  partIds={
                    scopeIds.length ? scopeIds : groups.length === 1 ? groups[0].part_ids : []
                  }
                  faces={faces}
                  disabled={busy || history || draftDirty || externalBusy}
                  name={partName}
                  onBounds={onCompletionBounds}
                  onComplete={(bounds, profile, shape, previewId) =>
                    edit('complete_part', {
                      completion_bounds: bounds,
                      completion_profile: profile === 'legs' ? 'support' : profile,
                      completion_shape: shape,
                      completion_preview_id: previewId,
                      detail_level: profile === 'legs' ? 'fine' : 'coarse',
                      part_ids: scopeIds.length
                        ? scopeIds
                        : groups.length === 1
                          ? groups[0].part_ids
                          : [],
                      name: partName.trim(),
                      note: '完整部件候选；保留既有推测面，新增接合面需检查',
                    })
                  }
                />
                <details>
                  <summary>部件移动与单独导出</summary>
                  <p>
                    先选择一个部件。移动量使用模型坐标单位，真实尺寸尚未核准；保存会创建独立版本。
                  </p>
                  <div className="material-fields">
                    {['X', 'Y', 'Z'].map((axis, k) => (
                      <label key={axis}>
                        {axis}
                        <input
                          aria-label={'部件移动 ' + axis}
                          type="number"
                          min="-5"
                          max="5"
                          step=".01"
                          value={translation[k]}
                          onChange={(e) =>
                            setTranslation((old) =>
                              old.map((v, i) => (i === k ? +e.target.value : v)),
                            )
                          }
                        />
                      </label>
                    ))}
                  </div>
                  <button
                    disabled={
                      busy ||
                      history ||
                      draftDirty ||
                      faces.length > 0 ||
                      !scopeIds.length ||
                      !translation.some((v) => v !== 0) ||
                      translation.some((v) => !Number.isFinite(v) || Math.abs(v) > 5)
                    }
                    onClick={() => void edit('translate_parts', { translation })}
                  >
                    保存部件移动
                  </button>
                  <button
                    disabled={busy || draftDirty || !scopeIds.length}
                    onClick={async () => {
                      setBusy(true);
                      setError('');
                      try {
                        const response = await fetch(`/api/jobs/${jobId}/asset/export-parts`, {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ version: catalog.version, part_ids: scopeIds }),
                        });
                        if (!response.ok)
                          throw new Error((await response.json()).detail || '导出失败');
                        const blob = await response.blob(),
                          url = URL.createObjectURL(blob),
                          a = document.createElement('a');
                        a.href = url;
                        a.download = 'selected_parts.glb';
                        a.click();
                        setTimeout(() => URL.revokeObjectURL(url), 1000);
                        setMessage('已导出选中部件，保留原坐标与材质。');
                      } catch (e) {
                        setError(e instanceof Error ? e.message : String(e));
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    单独导出选中部件
                  </button>
                  <button
                    disabled={busy || history || draftDirty || faces.length > 0 || !scopeIds.length}
                    onClick={() =>
                      void edit('separate_solids', { name: partName.trim() || '支撑部件' })
                    }
                  >
                    按闭合连通体拆成独立部件
                  </button>
                </details>
                <details className="complete-parts" open={groups.length <= 1 ? true : undefined}>
                  <summary>完整分组候选</summary>
                  <p>
                    按完整表面划分，包含侧面和背面。名称与边界是编辑建议，需要旋转检查，不代表真实可拆零件。
                  </p>
                  <label>
                    家具品类
                    <select
                      aria-label="完整分组品类"
                      value={category}
                      onChange={(e) => setCategory(e.target.value)}
                    >
                      <option value="auto">
                        按任务品类（{catalog.object_category || '未知'}）
                      </option>
                      <option value="table">桌子 / 茶几</option>
                      <option value="chair">椅子</option>
                      <option value="sofa">沙发</option>
                      <option value="cabinet">柜子 / 架子</option>
                      <option value="lamp">灯具</option>
                      <option value="other">其他</option>
                    </select>
                  </label>
                  <button
                    disabled={busy || history || draftDirty}
                    onClick={() => void edit('auto_parts')}
                  >
                    生成完整分组候选
                  </button>
                  <button
                    disabled={busy || history || draftDirty || selected === 'all'}
                    onClick={() => void edit('auto_parts', { detail_level: 'fine' })}
                  >
                    尝试细分选中底座 / 支撑
                  </button>
                </details>
                <label>
                  {faces.length ? '给选区起个名字' : '部件名称'}
                  <input
                    aria-label="部件名称"
                    placeholder={faces.length ? '例如：桌面' : '输入部件名称'}
                    value={partName}
                    maxLength={60}
                    onChange={(e) => setPartName(e.target.value)}
                  />
                </label>
                {!faces.length && selected !== 'all' && (
                  <button
                    disabled={busy || history || selected === 'all' || !partName.trim()}
                    onClick={() => void edit('rename')}
                  >
                    更新部件名称
                  </button>
                )}
                {checkedGroups.length >= 2 && (
                  <button
                    disabled={busy || history || draftDirty}
                    onClick={() =>
                      void edit('merge_parts', { name: partName.trim() || '合并部件' })
                    }
                  >
                    合并已选的 {checkedGroups.length} 个部件
                  </button>
                )}
                {faces.length > 0 && (
                  <>
                    <label>
                      选区归属
                      <select
                        aria-label="选区接收部件"
                        value={targetPart}
                        onChange={(e) => setTargetPart(e.target.value)}
                      >
                        <option value="">拆出为新部件</option>
                        {groups.map((g) => (
                          <option key={g.id} value={g.part_ids[0]}>
                            {g.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button
                      disabled={
                        busy ||
                        history ||
                        draftDirty ||
                        !faces.length ||
                        (!targetPart && !partName.trim())
                      }
                      onClick={() => void edit('assign_faces')}
                    >
                      {targetPart ? '移入接收部件' : '保存选区为新部件'}
                    </button>
                  </>
                )}
                <p>
                  {faces.length
                    ? '已选中局部。输入名称，例如“桌面”，再保存。'
                    : '还没有选区。请先在模型上涂抹或框选，默认不会选到被挡住的部分。'}
                </p>
              </>
            )}
            {tab === 'material' && (
              <>
                <p className="draft-status">
                  {draftDirty
                    ? previewStatus === 'loading'
                      ? '正在载入纹理预览…'
                      : previewStatus === 'error'
                        ? '预览失败，请取消或重新上传贴图。'
                        : '正在预览，尚未保存。切换部件或版本会取消预览。'
                    : '修改颜色或质感会即时预览，满意后再保存。'}
                </p>
                <div className="material-draft-actions">
                  <button disabled={busy || !draftUndo.length} onClick={undoMaterial}>
                    撤销材质预览
                  </button>
                  <button disabled={busy || !draftRedo.length} onClick={redoMaterial}>
                    重做材质预览
                  </button>
                  <button disabled={busy || !draftDirty} onClick={cancelMaterial}>
                    取消预览
                  </button>
                </div>
                {!validMaterial && (
                  <p role="alert">纹理重复需在 0.05～100 之间，旋转需在 -180～180 度之间。</p>
                )}
                {faces.length > 0 && (
                  <p className="selection-save-note">
                    当前涂抹区域还没保存为部件。
                    <button onClick={() => setTab('parts')}>先保存这个选区</button>
                  </p>
                )}
                <fieldset
                  className="material-inputs"
                  disabled={busy || history || faces.length > 0}
                >
                  <details>
                    <summary>曲面贴图与 UV 展开</summary>
                    <label>
                      展开方式
                      <select
                        aria-label="UV 展开方式"
                        value={unwrapMode}
                        onChange={(e) => setUnwrapMode(e.target.value)}
                      >
                        <option value="auto">自动：对照接缝与拉伸后选择</option>
                        <option value="proxy">代理图集回传（原形状保留）</option>
                        <option value="cylinder">圆形部件：连续环绕展开</option>
                        <option value="atlas">精细图集（最多 6 万面）</option>
                        <option value="box">快速分区（有接缝）</option>
                      </select>
                    </label>
                    {unwrapMode === 'cylinder' && (
                      <label>
                        展开方向
                        <select
                          aria-label="圆形部件展开方向"
                          value={axis}
                          onChange={(e) => setAxis(e.target.value)}
                        >
                          <option value="y">Y 轴（通常为上下）</option>
                          <option value="x">X 轴</option>
                          <option value="z">Z 轴</option>
                        </select>
                      </label>
                    )}
                    <p>
                      高面数先用较小的代理网格展开，再把 UV
                      近似回传到原网格。自动模式会与快速分区对照，仅在接缝减少且拉伸通过检查时采用代理结果；仍需检查花纹。
                    </p>
                    <p>
                      曲面花纹拉伸时，可先展开选中部件的
                      UV，再上传贴图。展开会重新安排贴图接缝并创建版本，原贴图外观可能改变；不改变网格形状。
                    </p>
                    <button
                      disabled={busy || history || draftDirty}
                      onClick={() => void edit('unwrap_uv', { uv_unwrap_mode: unwrapMode })}
                    >
                      展开当前范围 UV
                    </button>
                  </details>
                  <div className="material-presets" aria-label="示例材质套装">
                    {(
                      [
                        ['fabric', '示例布料'],
                        ['leather', '示例皮革'],
                        ['wood', '示例木纹'],
                      ] as const
                    ).map(([name, label]) => (
                      <button
                        key={name}
                        disabled={busy || history}
                        onClick={() => void exampleMaterial(name)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  <p>
                    示例材质可直接预览，也可上传自有面料或花纹替换。新重建部件已准备
                    UV；旧模型花纹拉伸时可先展开 UV。
                  </p>
                  <div className="material-presets">
                    {presets.map(([name, metal, rough, alpha]) => (
                      <button
                        key={name}
                        disabled={busy}
                        onClick={() => {
                          updateMaterial({ metalness: metal, roughness: rough, opacity: alpha });
                        }}
                      >
                        {name}
                      </button>
                    ))}
                  </div>
                  <div className="material-fields">
                    <label>
                      颜色
                      <input
                        aria-label="材质颜色"
                        type="color"
                        value={color}
                        onChange={(event) => updateMaterial({ color: event.target.value })}
                      />
                    </label>
                  </div>
                  <details>
                    <summary>表面效果（可选）</summary>
                    <p>粗糙度控制哑光或光亮，金属度控制金属质感，不透明度控制是否透明。</p>
                    <div className="material-fields">
                      <label>
                        粗糙度
                        <input
                          aria-label="材质粗糙度"
                          type="range"
                          min="0"
                          max="1"
                          step=".01"
                          value={roughness}
                          onChange={(event) => updateMaterial({ roughness: +event.target.value })}
                        />
                      </label>
                      <label>
                        金属度
                        <input
                          aria-label="材质金属度"
                          type="range"
                          min="0"
                          max="1"
                          step=".01"
                          value={metalness}
                          onChange={(event) => updateMaterial({ metalness: +event.target.value })}
                        />
                      </label>
                      <label>
                        不透明度
                        <input
                          aria-label="材质不透明度"
                          type="range"
                          min=".02"
                          max="1"
                          step=".01"
                          value={opacity}
                          onChange={(event) => updateMaterial({ opacity: +event.target.value })}
                        />
                      </label>
                    </div>
                  </details>
                  <details>
                    <summary>替换方式（高级）</summary>
                    <label>
                      替换方式
                      <select
                        aria-label="材质替换方式"
                        value={mode}
                        onChange={(event) => updateMaterial({ mode: event.target.value })}
                      >
                        <option value="replace">替换材质与预测颜色</option>
                        <option value="tint">保留纹理 / 顶点色并染色</option>
                      </select>
                    </label>
                  </details>
                  <details>
                    <summary>上传纹理图片（可选）</summary>
                    <p>
                      只想换木纹或布料花纹，上传色彩贴图即可；法线图用于凹凸细节，粗糙度图用于光泽分布，可以不传。法线图使用
                      OpenGL 格式。缺少 UV 时使用平面投影，曲面可能拉伸；保存后贴图嵌入 GLB。
                    </p>
                    {(
                      [
                        ['base_color_image', '色彩贴图'],
                        ['normal_image', '法线贴图'],
                        ['roughness_image', '粗糙度贴图'],
                      ] as const
                    ).map(([slot, label]) => (
                      <label key={slot}>
                        {label}
                        {textures[slot] ? ' · 已选择' : ''}
                        <input
                          aria-label={label}
                          type="file"
                          accept="image/png,image/jpeg,image/webp"
                          disabled={busy}
                          onChange={(e) => void uploadMap(slot, e.target.files?.[0])}
                        />
                        <button
                          disabled={busy}
                          onClick={() => {
                            const next = { ...textures };
                            delete next[slot];
                            updateMaterial({ textures: next });
                          }}
                        >
                          取消本次{label}
                        </button>
                      </label>
                    ))}
                    <label>
                      纹理重复
                      <input
                        aria-label="纹理重复"
                        type="number"
                        min=".05"
                        max="100"
                        step=".1"
                        value={uvScale}
                        onChange={(e) => updateMaterial({ uvScale: +e.target.value })}
                      />
                    </label>
                    <label>
                      纹理旋转（度）
                      <input
                        aria-label="纹理旋转"
                        type="number"
                        min="-180"
                        max="180"
                        value={uvRotation}
                        onChange={(e) => updateMaterial({ uvRotation: +e.target.value })}
                      />
                    </label>
                    <p>
                      色彩贴图建议搭配白色颜色；颜色参数会与贴图相乘。粗糙度图与粗糙度参数相乘。
                    </p>
                  </details>
                  <button
                    className="button primary"
                    disabled={
                      busy ||
                      history ||
                      faces.length > 0 ||
                      !draftDirty ||
                      !validMaterial ||
                      previewStatus === 'loading' ||
                      previewStatus === 'error'
                    }
                    onClick={() => void edit('material')}
                  >
                    {busy ? '正在保存…' : '保存当前材质效果'}
                  </button>
                </fieldset>
              </>
            )}
            {history && (
              <p>
                正在查看历史版本。恢复为新版本后可继续编辑。
                <button disabled={busy} onClick={() => void edit('restore_version')}>
                  恢复所看版本为新版本
                </button>
              </p>
            )}
            {tab === 'parts' && (
              <details>
                <summary>自动分组（高级）</summary>
                <p>
                  连通片分组保留全部网格；连续网格可按空间区域分组。它们不会自动识别桌腿或坐垫，也不会把实体切开。
                </p>
                <button
                  className="button secondary"
                  disabled={busy || history}
                  onClick={() => void edit('connected_components')}
                >
                  按连通片分组
                </button>
                <label>
                  区域方向
                  <select
                    aria-label="区域方向"
                    value={axis}
                    onChange={(event) => setAxis(event.target.value)}
                  >
                    <option value="y">高度 Y</option>
                    <option value="x">宽度 X</option>
                    <option value="z">深度 Z</option>
                  </select>
                </label>
                <label>
                  分界位置 {Math.round(position * 100)}%
                  <input
                    aria-label="区域分界位置"
                    type="range"
                    min=".05"
                    max=".95"
                    step=".01"
                    value={position}
                    onChange={(event) => setPosition(+event.target.value)}
                  />
                </label>
                <button
                  className="button secondary"
                  disabled={busy || history}
                  onClick={() => void edit('plane_group')}
                >
                  按区域保存分组版本
                </button>
              </details>
            )}
            {tab === 'more' && (
              <>
                <details>
                  <summary>同图本地引擎对照与结构验收</summary>
                  <button
                    disabled={busy || draftDirty}
                    onClick={() => setShowGenerationCompare(true)}
                  >
                    打开生成结果对照
                  </button>
                  {showGenerationCompare && (
                    <ReconstructionCompare
                      jobId={jobId}
                      disabled={busy || draftDirty}
                      onClose={() => setShowGenerationCompare(false)}
                    />
                  )}
                </details>
                <details className="quality-tools">
                  <summary>检查与保守修复模型</summary>
                  <p>
                    可清理重复、退化面，或轻微平滑噪声。为避免新增开口，部分极小面会保留。不能补出缺失部件，也不自动填孔；保留原模型。
                  </p>
                  <button
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      setError('');
                      try {
                        setQuality(
                          await api(`/api/jobs/${jobId}/asset/quality?version=${catalog.version}`),
                        );
                        setMessage('检查完成；开口可能是设计结构，不能据此判为坏模型。');
                      } catch (error) {
                        setError(String(error));
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    检查当前模型
                  </button>
                  {quality && (
                    <div className="quality-facts">
                      <p>
                        重复面：{String(quality.whole_model.duplicate_faces)}；退化面：
                        {String(quality.whole_model.degenerate_faces)}
                      </p>
                      <p>
                        边界边：{String(quality.whole_model.boundary_edges)}；非流形边：
                        {String(quality.whole_model.nonmanifold_edges)}
                      </p>
                      <p>
                        {quality.whole_model.watertight
                          ? '整体网格闭合'
                          : '存在开口，可能是设计开口或网格问题'}
                      </p>
                    </div>
                  )}
                  <label>
                    修复方式
                    <select
                      aria-label="模型修复方式"
                      value={repairStrength}
                      onChange={(e) => setRepairStrength(e.target.value)}
                    >
                      <option value="gentle">轻微降噪 + 坏面清理</option>
                      <option value="cleanup">只清理坏面，不改坐标</option>
                    </select>
                  </label>
                  <button
                    disabled={busy || history || draftDirty}
                    onClick={() => void edit('repair_geometry')}
                  >
                    生成保守修复版本
                  </button>
                </details>
                <details>
                  <summary>减小模型文件（减面）</summary>
                  <p>
                    按目标面数处理，检查表面偏差、轮廓、闭合和 UV
                    拉伸。未通过的网格保留，结果仍需看图检查。
                  </p>
                  <label>
                    目标面数
                    <select
                      aria-label="保形目标面数"
                      value={targetFaces}
                      disabled={busy}
                      onChange={(e) => setTargetFaces(+e.target.value)}
                    >
                      <option value={50000}>约 5 万面</option>
                      <option value={100000}>约 10 万面</option>
                      <option value={200000}>约 20 万面</option>
                    </select>
                  </label>
                  <button
                    disabled={busy || history || draftDirty}
                    onClick={() => void edit('optimize_mesh', { target_faces: targetFaces })}
                  >
                    按目标面数保形减面
                  </button>
                  <details>
                    <summary>按比例减面（高级）</summary>
                    <p>
                      逐部件减面，保留材质分界并检查包围盒与采样顶点距离。含 UV
                      的部件暂时拦截，以保护纹理接缝。结果仍需视觉检查。
                    </p>
                    <label>
                      目标保留比例 {Math.round(lodRatio * 100)}%
                      <input
                        aria-label="LOD保留比例"
                        type="range"
                        min=".1"
                        max=".9"
                        step=".1"
                        value={lodRatio}
                        onChange={(e) => setLodRatio(+e.target.value)}
                      />
                    </label>
                    <button disabled={busy || history} onClick={() => void edit('decimate')}>
                      保存轻量化版本
                    </button>
                  </details>
                </details>
                <details>
                  <summary>补充原图与版本整理</summary>
                  <p>
                    主模型仍用主图生成。可在部件自动优化里补充侧面或背面参与候选筛选；当前未做相机标定或多视图三维融合。
                  </p>
                  <input
                    aria-label="补充参考图"
                    type="file"
                    accept="image/*"
                    multiple
                    disabled={busy}
                    onChange={async (e) => {
                      const files = Array.from(e.target.files || []);
                      setBusy(true);
                      setError('');
                      try {
                        const old = catalog.reference_views
                          .filter((v) => v.role === 'reference_only')
                          .map((v) => v.id);
                        if (old.length + files.length > 8) throw new Error('最多 8 张补充参考图');
                        const ids = [];
                        for (const file of files) ids.push(await uploadImage(file));
                        updateReferences(
                          await post<Catalog>(`/api/jobs/${jobId}/reference-views`, {
                            image_ids: [...old, ...ids],
                          }),
                        );
                        setMessage('补充视图已保存，仅用于对照。');
                      } catch (error) {
                        setError(String(error));
                      } finally {
                        setBusy(false);
                      }
                    }}
                  />
                  <div className="reference-thumbnails">
                    {catalog.reference_views?.map((view) => (
                      <div key={view.id}>
                        <button onClick={() => onReference?.(view.url)}>
                          <img
                            src={view.url}
                            alt={view.role === 'generation_primary' ? '生成主图' : '补充参考图'}
                          />
                          <span>{view.role === 'generation_primary' ? '生成主图' : '对照图'}</span>
                        </button>
                        {view.role === 'reference_only' && (
                          <button
                            disabled={busy}
                            aria-label={'移除补充视图 ' + view.id}
                            onClick={async () => {
                              setBusy(true);
                              setError('');
                              try {
                                const image_ids = catalog.reference_views
                                  .filter((v) => v.role === 'reference_only' && v.id !== view.id)
                                  .map((v) => v.id);
                                updateReferences(
                                  await post<Catalog>(`/api/jobs/${jobId}/reference-views`, {
                                    image_ids,
                                  }),
                                );
                                onReference?.('');
                                setMessage('补充视图已移除，原始图片保留。');
                              } catch (error) {
                                setError(String(error));
                              } finally {
                                setBusy(false);
                              }
                            }}
                          >
                            移除
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                  <label>
                    版本备注
                    <textarea
                      aria-label="版本备注"
                      value={note}
                      maxLength={1000}
                      onChange={(e) => setNote(e.target.value)}
                    />
                  </label>
                  <button
                    disabled={busy || catalog.version === 'original'}
                    onClick={() => void annotate(false)}
                  >
                    保存备注 / 取消归档
                  </button>
                  <button
                    disabled={busy || catalog.version === 'original'}
                    onClick={() => void annotate(true)}
                  >
                    归档当前版本
                  </button>
                  <label>
                    比较基准
                    <select
                      aria-label="比较基准"
                      value={compareVersion}
                      onChange={(e) => setCompareVersion(e.target.value)}
                    >
                      <option value="original">原始版本</option>
                      {catalog.versions.map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.id.slice(0, 8)} · {operationNames[v.operation] || v.operation}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    disabled={busy}
                    onClick={async () => {
                      setError('');
                      try {
                        const result = await api<{
                          left: Catalog;
                          delta: Record<string, number>;
                          added_parts: string[];
                          removed_parts: string[];
                          changed_parts: string[];
                        }>(
                          `/api/jobs/${jobId}/asset/compare?left=${compareVersion}&right=${catalog.version}`,
                        );
                        setDiff(
                          `相对基准：部件 ${result.delta.parts >= 0 ? '+' : ''}${result.delta.parts}，三角面 ${result.delta.triangles}，字节 ${result.delta.bytes}；新增 ${result.added_parts.length}、移除 ${result.removed_parts.length}、元数据变化 ${result.changed_parts.length}。不代表外观相似度。`,
                        );
                        setCompareModel(result.left.model_url);
                      } catch (error) {
                        setError(String(error));
                      }
                    }}
                  >
                    比较版本
                  </button>
                  {diff && <p role="status">{diff}</p>}
                  {compareModel && (
                    <a href={compareModel} target="_blank" rel="noreferrer">
                      下载比较基准 GLB
                    </a>
                  )}
                  {compareModel && (
                    <>
                      <div className="version-comparison">
                        <Viewer url={compareModel} label="比较基准版本" />
                        <Viewer url={catalog.model_url} label="当前编辑版本" />
                      </div>
                      <button onClick={() => setCompareModel('')}>关闭版本对照</button>
                    </>
                  )}
                  <button
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      try {
                        const result = await post<{
                          logical_bytes: number;
                          unique_content_bytes: number;
                          duplicate_content_bytes: number;
                        }>(`/api/jobs/${jobId}/asset/compact-storage`);
                        setMessage(
                          `历史逻辑大小 ${result.logical_bytes} 字节，独立内容 ${result.unique_content_bytes} 字节，重复内容 ${result.duplicate_content_bytes} 字节；原始及历史版本均保留。`,
                        );
                      } catch (error) {
                        setError(String(error));
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    合并重复文件存储
                  </button>
                </details>
              </>
            )}
            {tab === 'more' && (
              <div className="asset-version-actions">
                {tab === 'more' && (
                  <button
                    disabled={busy || catalog.version === 'original'}
                    onClick={() => void edit('restore_original')}
                  >
                    恢复原始模型为新版本
                  </button>
                )}
                <a href={catalog.model_url} download>
                  下载当前模型
                </a>
                {tab === 'more' &&
                  catalog.versions.find((version) => version.id === catalog.version)
                    ?.manifest_url && (
                    <a
                      href={
                        catalog.versions.find((version) => version.id === catalog.version)
                          ?.manifest_url
                      }
                      target="_blank"
                      rel="noreferrer"
                    >
                      下载编辑记录
                    </a>
                  )}
              </div>
            )}
            <p>
              {catalog.version === 'original'
                ? '原始模型'
                : catalog.editor_review_status === 'accepted'
                  ? '当前效果已确认'
                  : catalog.editor_review_status === 'rejected'
                    ? '当前效果需修改'
                    : '当前效果待确认'}{' '}
              {tab === 'more' ? ` · 已保存 ${catalog.versions.length} 个编辑版本。` : ''}
            </p>
            {catalog.version !== 'original' && catalog.editor_review_status === 'unreviewed' && (
              <div className="asset-version-actions">
                <button disabled={busy} onClick={() => void review('reject')}>
                  标记为需修改
                </button>
                <button disabled={busy} onClick={() => void review('accept')}>
                  确认当前效果
                </button>
              </div>
            )}
          </>
        )}
        {message && <p role="status">{message}</p>}
        {error && (
          <p role="alert" className="editor-error">
            {error}
          </p>
        )}
      </fieldset>
    </section>
  );
}

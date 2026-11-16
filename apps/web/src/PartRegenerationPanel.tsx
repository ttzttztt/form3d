import { useEffect, useRef, useState } from 'react';
import { api, post } from './types';
import CutPreview from './CutPreview';
import PartAssessment from './PartAssessment';
import type { QualityDimension } from './PartAssessment';
import './partRegeneration.css';
type Kind = 'pillow' | 'cushion' | 'bolster';
interface Task {
  id: string;
  status: string;
  stage: string;
  error?: string;
  sampling_step?: number;
  sampling_steps?: number;
  candidate_index?: number;
  candidate_total?: number;
  optimization_phase?: string;
  selected_seed?: number;
  candidate_results?: { seed: number; index: number; status: string; eligible: boolean; photo_iou?: number; reason?: string; triangles?: number; comparison_url?: string }[];
  candidates?: { id: string; label: string; preview_url: string }[];
  preview_url?: string;
  generated_url?: string;
  part_url?: string;
  automatic_plan?: {
    route: string;
    reason: string;
    photo_association?: { status: string; reason: string };
    additional_views?: { index: number; role: string; status: string; reason?: string; association_url?: string; before_url?: string; after_url?: string }[];
  };
  photo_checks?: {
    can_adopt: boolean;
    reason: string;
    part_silhouette_iou_before: number;
    part_silhouette_iou_after: number;
    quality_dimensions?: QualityDimension[];
    views?: { index?: number; role: string; part_silhouette_iou_before: number; part_silhouette_iou_after: number; passed: boolean }[];
  };
  association_url?: string;
  comparison_url?: string;
  operation?: {
    surface_repair?: { method?: string; occluded_roof_area_fraction?: number };
    slot?: unknown;
    method?: string;
    placement?: { thickness_constraint?: { method?: string } };
  };
}
interface SessionDraft {
  kind?: Kind;
  refs?: Task;
  task?: Task;
  selected?: string;
  referenceImage?: string;
  uploadName?: string;
  extraViews?: ExtraView[];
  candidateCount?: number;
}
interface ExtraView { image_id: string; name: string; role: 'side' | 'back' | 'front' }
export default function PartRegenerationPanel({
  jobId,
  version,
  partIds,
  kind: initialKind,
  disabled,
  canPreserveSurface = false,
  autoSupported = true,
  onSave,
}: {
  jobId: string;
  version: string;
  partIds: string[];
  kind: Kind;
  disabled: boolean;
  canPreserveSurface?: boolean;
  autoSupported?: boolean;
  onSave: (id: string) => Promise<void>;
}) {
  const storageKey = 'form_part_regeneration:' + JSON.stringify({ jobId, version, partIds });
  const [restored] = useState<SessionDraft>(() => {
    try {
      const value = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
      return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    } catch {
      return {};
    }
  });
  const [kind, setKind] = useState<Kind>(restored.kind ?? initialKind),
    [refs, setRefs] = useState<Task | undefined>(restored.refs),
    [task, setTask] = useState<Task | undefined>(restored.task),
    [selected, setSelected] = useState(restored.selected ?? ''),
    [referenceImage, setReferenceImage] = useState(restored.referenceImage ?? ''),
    [uploadName, setUploadName] = useState(restored.uploadName ?? ''),
    [extraViews, setExtraViews] = useState<ExtraView[]>(restored.extraViews ?? []),
    [candidateCount, setCandidateCount] = useState(restored.candidateCount ?? 3),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [loaded, setLoaded] = useState(false),
    [confirmed, setConfirmed] = useState(false);
  const key = JSON.stringify({ jobId, version, partIds, kind, referenceImage, extraViews, candidateCount }),
    latest = useRef(key),
    previousKey = useRef(key);
  latest.current = key;
  useEffect(() => {
    try {
      sessionStorage.setItem(
        storageKey,
        JSON.stringify({ kind, refs, task, selected, referenceImage, uploadName, extraViews, candidateCount }),
      );
    } catch {
      /* Storage can be disabled; inference and explicit save remain available. */
    }
  }, [storageKey, kind, refs, task, selected, referenceImage, uploadName, extraViews, candidateCount]);
  useEffect(() => {
    latest.current = key;
    if (previousKey.current !== key) {
      setRefs(undefined);
      setTask(undefined);
      setSelected('');
      setError('');
      setLoaded(false);
      setConfirmed(false);
      setBusy(false);
    }
    previousKey.current = key;
    return () => {
      if (latest.current === key) latest.current = '';
    };
  }, [key]);
  const refRunning = !!refs && ['queued', 'running'].includes(refs.status),
    running = !!task && ['queued', 'running'].includes(task.status);
  useEffect(() => {
    const current = running ? task : refRunning ? refs : undefined;
    if (!current) return;
    const captured = key;
    let disposed = false,
      timer: ReturnType<typeof setTimeout>;
    const reference = !running;
    const poll = async () => {
      try {
        const next = await api<Task>(
          `/api/jobs/${jobId}/asset/${reference ? 'part-reference-scans' : 'part-regenerations'}/${current.id}`,
        );
        if (disposed || latest.current !== captured) return;
        setError('');
        if (reference) {
          setRefs(next);
          if (next.status === 'ready') setSelected('');
        } else setTask(next);
        if (['queued', 'running'].includes(next.status)) timer = setTimeout(poll, 1500);
      } catch {
        if (!disposed && latest.current === captured) {
          setError('连接暂时中断，正在重新读取进度…');
          timer = setTimeout(poll, 3000);
        }
      }
    };
    timer = setTimeout(poll, 800);
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [task?.id, refs?.id, running, refRunning, key]);
  async function upload(file: File) {
    const captured = key;
    setBusy(true);
    setError('');
    try {
      const form = new FormData();
      form.append('file', file);
      const result = await api<{ id: string }>('/api/images', { method: 'POST', body: form });
      if (latest.current !== captured) return;
      setReferenceImage(result.id);
      setUploadName(file.name);
    } catch (e) {
      if (latest.current === captured) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (latest.current === captured) setBusy(false);
    }
  }
  async function extract() {
    const captured = key;
    setBusy(true);
    setError('');
    try {
      const result = await post<Task>(`/api/jobs/${jobId}/asset/part-reference-scans`, {
        version,
        part_ids: partIds,
        kind,
        reference_image_id: referenceImage,
      });
      if (latest.current === captured) setRefs(result);
    } catch (e) {
      if (latest.current === captured) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (latest.current === captured) setBusy(false);
    }
  }
  async function generate() {
    if (!refs || !selected) return;
    const captured = key;
    setBusy(true);
    setError('');
    setLoaded(false);
    setConfirmed(false);
    try {
      const result = await post<Task>(`/api/jobs/${jobId}/asset/part-regenerations`, {
        version,
        part_ids: partIds,
        kind,
        reference_image_id: referenceImage,
        reference_scan_id: refs.id,
        reference_candidate_id: selected,
      });
      if (latest.current === captured) setTask(result);
    } catch (e) {
      if (latest.current === captured) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (latest.current === captured) setBusy(false);
    }
  }
  async function repair() {
    const captured = key;
    setBusy(true);
    setError('');
    setLoaded(false);
    setConfirmed(false);
    try {
      const result = await post<Task>(`/api/jobs/${jobId}/asset/part-surface-repairs`, {
        version,
        part_ids: partIds,
      });
      if (latest.current === captured) setTask(result);
    } catch (e) {
      if (latest.current === captured) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (latest.current === captured) setBusy(false);
    }
  }
  async function autoOptimize() {
    const captured = key;
    setBusy(true);
    setError('');
    setLoaded(false);
    setConfirmed(false);
    try {
      const next = await post<Task>(`/api/jobs/${jobId}/asset/part-optimizations`, {
        version,
        part_ids: partIds,
        candidate_count: candidateCount,
        target_faces: 100000,
        reference_views: extraViews.map(({ image_id, role }) => ({ image_id, role })),
      });
      if (latest.current === captured) setTask(next);
    } catch (e) {
      if (latest.current === captured) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (latest.current === captured) setBusy(false);
    }
  }
  async function uploadExtra(files: FileList | null) {
    if (!files?.length) return;
    const captured = key;
    setBusy(true);setError('');
    try {
      const additions: ExtraView[] = [];
      for (const file of Array.from(files).slice(0, 3 - extraViews.length)) {
        const form = new FormData();form.append('file', file);
        const value = await api<{ id: string }>('/api/images', { method: 'POST', body: form });
        if (latest.current !== captured) return;
        additions.push({ image_id: value.id, role: 'side', name: file.name });
      }
      if (latest.current === captured) setExtraViews([...extraViews, ...additions]);
    } catch (e) { if (latest.current === captured) setError(e instanceof Error ? e.message : String(e)); }
    finally { if (latest.current === captured) setBusy(false); }
  }
  async function save() {
    if (!task || !loaded || !confirmed || task.photo_checks?.can_adopt === false) return;
    const captured = key;
    setBusy(true);
    setError('');
    try {
      await onSave(task.id);
    } catch (e) {
      if (latest.current === captured) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (latest.current === captured) setBusy(false);
    }
  }
  const blocked = disabled || busy || refRunning || running,
    stage = running ? task : refRunning ? refs : undefined;
  const optimizationPhases: Record<string, string> = { reading_source: '读取原模型', reading_candidate: '读取候选', simplifying: '保形减面', checking_source_scope: '检查部件范围', aligning: '对齐部件', refining_photo_pose: '微调照片轮廓', checking_storage: '检查闭合与自交', preparing_uv: '准备材质坐标', checking_views_and_neighbors: '检查各视图与相邻部件', writing_preview: '写入预览' };
  return (
    <details className="part-regeneration">
      <summary>修复或重新生成部件</summary>
      <p>先选择一个已保存的部件组。重新生成后先检查预览，原版本保留。</p>
      <button disabled={blocked || !partIds.length || !autoSupported} onClick={() => void autoOptimize()}>
        自动分析并优化部件
      </button>
      <p>{autoSupported ? '自动对应原图、选择保留或修复方式，再显示轮廓和前后对照。' : '自动优化目前支持已识别的坐垫、靠枕和圆柱抱枕。请先识别并选择这类完整部件；柜门、桌腿等可使用分组和材质工具。'}</p>
      <details className="part-extra-views">
        <summary>补充侧面或背面（可选）</summary>
        <p>上传同一件家具的整件照片，参与候选筛选。额外照片不代表隐藏结构已得到实物确认。</p>
        <input type="file" accept="image/*" multiple aria-label="补充部件优化视图" disabled={blocked || extraViews.length >= 3} onChange={(e) => void uploadExtra(e.target.files)} />
        {extraViews.map((view, index) => (
          <div className="part-extra-view" key={view.image_id}>
            <img src={`/api/images/${view.image_id}/preview`} alt={`补充视图 ${index + 1}`} />
            <span>{view.name}</span>
            <select aria-label={`补充视图 ${index + 1} 方向`} value={view.role} disabled={blocked} onChange={(e) => setExtraViews(extraViews.map((v, i) => i === index ? { ...v, role: e.target.value as ExtraView['role'] } : v))}>
              <option value="side">侧面</option><option value="back">背面</option><option value="front">另一正面</option>
            </select>
            <button disabled={blocked} onClick={() => setExtraViews(extraViews.filter((_, i) => i !== index))}>移除视图 {index + 1}</button>
          </div>
        ))}
        <label>形状候选数量<select aria-label="形状候选数量" value={candidateCount} disabled={blocked} onChange={(e) => setCandidateCount(+e.target.value)}><option value={3}>3 个</option><option value={2}>2 个</option><option value={1}>1 个</option></select></label>
      </details>
      <details className="part-manual-options">
        <summary>手动选择参考或修复方式</summary>
      <label>
        部件类型
        <select
          aria-label="重生成部件类型"
          value={kind}
          disabled={blocked}
          onChange={(e) => setKind(e.target.value as Kind)}
        >
          <option value="pillow">靠枕</option>
          <option value="cushion">坐垫</option>
          <option value="bolster">圆柱抱枕</option>
        </select>
      </label>
      {canPreserveSurface && kind === 'cushion' && !task && (
        <div>
          <p>根据已有坐垫形状沿接缝拆分，并补齐遮挡区域和底面。</p>
          <button disabled={blocked} onClick={() => void repair()}>
            沿接缝拆出完整坐垫
          </button>
        </div>
      )}
      <details>
        <summary>使用单独的部件参考图（可选）</summary>
        <p>只上传这一块部件的清晰图片。修补或遮挡部分不能视为真实结构。</p>
        <input
          type="file"
          accept="image/*"
          aria-label="部件参考图片"
          disabled={blocked}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void upload(f);
          }}
        />
        {uploadName && (
          <p>
            {uploadName}
            <button
              disabled={blocked}
              onClick={() => {
                setReferenceImage('');
                setUploadName('');
              }}
            >
              恢复使用原图
            </button>
          </p>
        )}
      </details>
      <button disabled={blocked || !partIds.length} onClick={() => void extract()}>
        寻找部件参考候选
      </button>
      </details>
      {stage && (
        <p role="status">
          {stage.candidate_total ? `候选 ${stage.candidate_index}/${stage.candidate_total} · ` : ''}
          {stage.stage === 'waiting_cpu'
            ? '等待几何处理空闲'
            : stage.stage === 'preparing_candidate'
              ? '正在准备形状候选'
            : stage.stage === 'extracting_additional_view'
              ? '正在识别补充视图中的部件'
            : stage.stage === 'waiting_gpu'
            ? '等待本地显卡'
            : stage.stage === 'extracting_reference'
              ? '正在从原图提取部件'
              : stage.stage === 'preserving_source'
                ? '正在按坐垫原形修复遮挡区域和切口'
                : stage.stage === 'matching_reference'
                  ? '正在对应原图与三维部件'
                  : stage.stage === 'refining_reference'
                    ? '正在用投影位置辅助 AI 精分部件'
                    : stage.stage === 'optimizing_shape'
                      ? `正在优化形状${stage.optimization_phase ? ' · ' + (optimizationPhases[stage.optimization_phase] ?? '处理中') : ''}`
                      : stage.stage === 'checking_comparison'
                        ? '正在检查原图、优化前和优化后'
                        : stage.stage === 'aligning'
                          ? '正在对齐并检查替换范围'
                          : stage.stage === 'reusing_generation'
                            ? '正在复用同一参考的生成部件，重新检查装配'
                          : stage.stage === 'generating'
                            ? `正在生成部件${stage.sampling_step ? ` · ${stage.sampling_step}/${stage.sampling_steps} 步` : ''}`
                            : '正在排队'}
          。完成前不会替换当前模型。
          <button
            onClick={() => {
              const captured = key;
              void post(
                `/api/jobs/${jobId}/asset/${running ? 'part-regenerations' : 'part-reference-scans'}/${stage.id}/cancel`,
              ).catch((e) => {
                if (latest.current === captured)
                  setError(e instanceof Error ? e.message : String(e));
              });
            }}
          >
            取消本次处理
          </button>
        </p>
      )}
      {(error || refs?.error || task?.error) && (
        <p role="alert">{error || task?.error || refs?.error}</p>
      )}
      {task?.automatic_plan && (
        <div className="part-auto-assessment">
          <p>{task.automatic_plan.reason}</p>
          <PartAssessment dimensions={task.photo_checks?.quality_dimensions} />
          {task.automatic_plan.photo_association?.status === 'needs_confirmation' && (
            <p>原图对应仍不确定，未自动指定可靠参考。</p>
          )}
          {task.association_url && (
            <details>
              <summary>查看部件与原图的对应</summary>
              <a href={task.association_url} target="_blank" rel="noreferrer">
                <img src={task.association_url} alt="蓝线为旧模型投影，绿线为原图参考" />
              </a>
              <p>蓝线：旧模型投影；绿线：原图参考。点击图片放大。</p>
            </details>
          )}
          {task.comparison_url && (
            <details open>
              <summary>原图、优化前、优化后</summary>
              <a href={task.comparison_url} target="_blank" rel="noreferrer">
                <img src={task.comparison_url} alt="同一投影下的原图与优化前后对照" />
              </a>
            </details>
          )}
          {task.photo_checks && (
            <p>
              当前视角轮廓重合度：{(task.photo_checks.part_silhouette_iou_before * 100).toFixed(1)}%
              → {(task.photo_checks.part_silhouette_iou_after * 100).toFixed(1)}
              %。这是图像对照指标，不是实物还原准确率。{task.photo_checks.reason}
            </p>
          )}
          {task.automatic_plan.additional_views?.map((view) => (
            <details key={view.index}>
              <summary>补充视图 {view.index + 1} · {view.status === 'matched' ? '已对应' : '对应待确认'}</summary>
              {view.reason && <p>{view.reason}</p>}
              {view.association_url && <a href={view.association_url} target="_blank" rel="noreferrer"><img src={view.association_url} alt={`补充视图 ${view.index + 1} 的照片对应`} /></a>}
              {task.photo_checks?.views?.filter((r) => r.index === view.index).map((r) => <p key={r.index}>该视角轮廓 {(r.part_silhouette_iou_before * 100).toFixed(1)}% → {(r.part_silhouette_iou_after * 100).toFixed(1)}% · {r.passed ? '检查通过' : '未通过'}</p>)}
              {view.before_url && view.after_url && <div className="part-view-pair"><figure><img src={view.before_url} alt={`补充视图 ${view.index + 1} 优化前`} /><figcaption>优化前</figcaption></figure><figure><img src={view.after_url} alt={`补充视图 ${view.index + 1} 优化后`} /><figcaption>优化后</figcaption></figure></div>}
            </details>
          ))}
          {!!task.candidate_results?.length && (
            <details className="part-candidate-list">
              <summary>查看 {task.candidate_results.length} 个候选与未采用原因</summary>
              <p>自动优先选择允许替换的候选，再按照片轮廓与几何检查排序；排序不代表实物准确率。</p>
              {task.candidate_results.map((candidate) => (
                <article key={candidate.seed}>
                  <strong>候选 {candidate.index}{task.selected_seed === candidate.seed ? ' · 当前候选' : ''}</strong>
                  <p>{candidate.status === 'failed' ? '处理未通过' : candidate.eligible ? '允许作为待审候选' : '未允许替换'}{candidate.photo_iou != null ? ` · 当前视角轮廓 ${(candidate.photo_iou * 100).toFixed(1)}%` : ''}</p>
                  <p>{candidate.reason}</p>
                  {candidate.triangles != null && <p>{candidate.triangles.toLocaleString()} 面</p>}
                  {candidate.comparison_url && <a href={candidate.comparison_url} target="_blank" rel="noreferrer"><img src={candidate.comparison_url} alt={`候选 ${candidate.index} 的前后对比`} /></a>}
                </article>
              ))}
            </details>
          )}
        </div>
      )}
      {refs?.status === 'ready' && !task && (
        <>
          <p>选择正确且完整的一块；混入靠枕、扶手或座架的参考不要采用。</p>
          <div className="part-reference-grid">
            {refs.candidates?.map((c) => (
              <button
                key={c.id}
                aria-label={c.label}
                aria-pressed={selected === c.id}
                onClick={() => setSelected(c.id)}
              >
                <img src={c.preview_url} alt={c.label} />
                <span>{c.label}</span>
              </button>
            ))}
          </div>
          <button disabled={blocked || !selected} onClick={() => void generate()}>
            用所选参考生成 3D 预览
          </button>
        </>
      )}
      {task?.status === 'ready' && task.preview_url && (
        <>
          <CutPreview
            url={task.preview_url}
            soloHideMaterials={
              task.operation?.method === 'source_seam'
                ? ['preview_body']
                : ['preview_body', 'preview_source']
            }
            onReady={() => setLoaded(true)}
            legend={
              task.operation?.method === 'keep'
                ? '橙色：保留原形的当前部件；灰色：其他部件。'
                : task.automatic_plan?.route === 'photo_pillow'
                  ? '橙色：按原图轮廓和旧模型表面重建的部件；灰色：其他部件。隐藏形状包含推测。'
                : task.operation?.method === 'source_seam'
                ? task.operation.surface_repair
                  ? '蓝色：有原模型支持的重建表面；橙色：遮挡区域和底面的推测补全；灰色：座架及其他部件。'
                  : '蓝色：保留的坐垫表面；橙色：新增底面；灰色：座架及其他部件。座架切口同时补齐，接缝位置需检查。'
                : '橙色：重新生成的部件；蓝色：调整后的座架；灰色：其他部件。位置和隐藏表面包含推测。'
            }
          />
          {task.automatic_plan?.route === 'ai_regeneration' && (
            <p>部件形状来自本地 Hunyuan3D-2mini。照片不可见的表面属于生成推测。</p>
          )}
          {!!task.operation?.slot && (
            <p>
              {task.operation.method === 'source_seam'
                ? task.operation.surface_repair
                  ? `坐垫按旧模型重建，约 ${((task.operation.surface_repair.occluded_roof_area_fraction ?? 0) * 100).toFixed(1)}% 顶面范围属于遮挡区推测。请检查形状与接缝。`
                  : '坐垫原表面已保留，仅补齐底面与座架切口；请检查接缝位置。'
                : '当前范围包含座架：预览同时调整了坐垫底部和座架接口，请检查切分厚度。'}
            </p>
          )}
          {task.operation?.placement?.thickness_constraint?.method ===
            'paired_opposing_source_surfaces' && (
            <p>
              {task.operation.surface_repair?.method ===
              'paired_observed_height_fields_inside_ai_contour'
                ? '生成的薄壳已按旧模型前后表面重建体积，形状仍需对照实物检查。'
                : '厚度已按旧模型前后表面约束，形状仍需对照实物检查。'}
            </p>
          )}
          {task.operation?.method !== 'keep' && <><label>
            <input
              type="checkbox"
              checked={confirmed}
              disabled={!loaded || blocked || task.photo_checks?.can_adopt === false}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            已检查部件形状、位置和接合处
          </label>
          <button
            disabled={blocked || !loaded || !confirmed || task.photo_checks?.can_adopt === false}
            onClick={() => void save()}
          >
            采用这个替换候选
          </button>
          </>}
          {task.part_url && (
            <a href={task.part_url} download>
              {task.operation?.method === 'keep' ? '单独下载当前部件' : '单独下载新部件'}
            </a>
          )}
        </>
      )}
      {task?.status === 'failed' && task.generated_url && (
        <p>
          部件已生成，但装回检查未通过。
          <a href={task.generated_url} download>
            下载未装配的生成部件
          </a>
        </p>
      )}
      {task && !running && (
        <button
          disabled={busy || disabled}
          onClick={() => {
            setTask(undefined);
            setLoaded(false);
            setConfirmed(false);
            setError('');
          }}
        >
          重新选择参考
        </button>
      )}
    </details>
  );
}

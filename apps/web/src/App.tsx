import { useEffect, useRef, useState } from 'react';
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Box,
  Boxes,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Cloud,
  FileImage,
  History,
  ImagePlus,
  Layers3,
  LoaderCircle,
  MoreHorizontal,
  Plus,
  Settings2,
  ShieldCheck,
  Sparkles,
  WandSparkles,
  X,
  XCircle,
} from 'lucide-react';
import Viewer from './Viewer';
import AssetEditor from './AssetEditor';
import type { MaterialDraft, PreviewStatus } from './materialDraft';
import type { FaceSelection } from './faceSelection';
import ImageEditor from './ImageEditor';
import DetectedTargets from './DetectedTargets';
import { api, post, statusLabels } from './types';
import type {
  Configuration,
  DetectedObject,
  Job,
  Sample,
  Stroke,
  Target,
  UploadedImage,
} from './types';

const wholeImage = { x: 0, y: 0, width: 1, height: 1 };
const templateNames: Record<string, string> = {
  shelf: '开放置物架',
  table: '简约桌 / 边几',
  cabinet: '规则双门柜',
};
const colors = ['#b79370', '#dfd1bd', '#f3f0e9', '#707d6a', '#41434b', '#b66c52'];
const routeNames = {
  local: '本地自动生成',
  assistant: '对话看图建模',
  template: '手动结构工具',
  meshy: '云端图生 3D',
};
type Panel = 'history' | 'assets' | 'help' | 'settings' | 'report' | null;

export default function App() {
  const [config, setConfig] = useState<Configuration>();
  const [samples, setSamples] = useState<Sample[]>([]);
  const [sample, setSample] = useState<Sample>();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [job, setJob] = useState<Job>();
  const [image, setImage] = useState<UploadedImage>();
  const [inputReferences, setInputReferences] = useState<UploadedImage[]>([]);
  const [target, setTarget] = useState<Target>(wholeImage);
  const [strokes, setStrokes] = useState<Stroke[]>([]);
  const [name, setName] = useState('');
  const [route, setRoute] = useState<'local' | 'assistant' | 'template' | 'meshy'>('local');
  const [removeBackground, setRemoveBackground] = useState(true);
  const [localEngine, setLocalEngine] = useState<'triposr' | 'hunyuan-mini'>('triposr');
  const [localSegmentation, setLocalSegmentation] = useState<'auto' | 'sam2' | 'basic'>('auto');
  const [objectCategory, setObjectCategory] = useState('');
  const [autoRetry, setAutoRetry] = useState(true);
  const [editedPreview, setEditedPreview] = useState<{
    jobId: string;
    url: string;
    metrics: { parts: number; triangles: number; bytes: number };
    reviewStatus: string;
  }>();
  const [pickedPart, setPickedPart] = useState('');
  const [completionBounds,setCompletionBounds]=useState<number[][]>();
  const [selectedPartIds, setSelectedPartIds] = useState<string[]>([]),
    [materialDraft, setMaterialDraft] = useState<MaterialDraft>();
  const [draftStatus, setDraftStatus] = useState<PreviewStatus>('idle');
  const [editorBusy, setEditorBusy] = useState(false);
  const [assistanceBusy, setAssistanceBusy] = useState(false);
  useEffect(() => {
    setSelectedPartIds([]);
    setCompletionBounds(undefined);
    setMaterialDraft(undefined);
    setDraftStatus('idle');
  }, [job?.id]);
  const [faceSelection, setFaceSelection] = useState<FaceSelection[]>([]);
  const [referenceOverride, setReferenceOverride] = useState('');
  useEffect(() => {
    setReferenceOverride('');
    setFaceSelection([]);
  }, [job?.id]);
  const [objects, setObjects] = useState<DetectedObject[]>([]);
  const [selectedObject, setSelectedObject] = useState('');
  const [objectLabel, setObjectLabel] = useState('');
  const selectionTouched = useRef(false);
  const [template, setTemplate] = useState('shelf');
  const [width, setWidth] = useState(80),
    [depth, setDepth] = useState(40),
    [height, setHeight] = useState(80);
  const [confirmed, setConfirmed] = useState(false);
  const [color, setColor] = useState(colors[0]);
  const [levels, setLevels] = useState(3);
  const [consent, setConsent] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [acting, setActing] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [panel, setPanel] = useState<Panel>(null);
  const [toast, setToast] = useState('');
  const [connected, setConnected] = useState(false);
  const [modelLoaded, setModelLoaded] = useState(false);
  const [comparison, setComparison] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const modelEditing = !!job?.model_url && !preparing;
  useEffect(() => {
    setPreparing(false);
  }, [job?.id]);
  const fileInput = useRef<HTMLInputElement>(null);
  const creationKey = useRef<string>();
  const busy = submitting || uploading || job?.status === 'running' || job?.status === 'queued';
  const active = job && ['queued', 'running'].includes(job.status);
  const remoteNeedsAttention = job?.status === 'awaiting_input' && route === 'meshy';
  const assistantWaiting = job?.status === 'awaiting_assistant' && route === 'assistant';
  const localReady =
    config?.providers.local.engines?.[localEngine]?.available ??
    (localEngine === 'triposr' && !!config?.providers.local.available);
  const progress = !image ? 0 : !job ? 1 : job.model_url ? 3 : 2;
  const previewUrl =
    job && editedPreview && job.id === editedPreview.jobId
      ? editedPreview.url
      : job?.model_url || (!image ? sample?.model_url : undefined);
  const viewingEdit = !!(
    job &&
    editedPreview &&
    job.id === editedPreview.jobId &&
    editedPreview.url !== job.model_url
  );
  const displayedMetrics =
    job && editedPreview?.jobId === job.id ? editedPreview.metrics : job?.metrics;
  useEffect(() => {
    setPickedPart('');
    setEditedPreview(undefined);
  }, [job?.id]);

  function notify(message: string) {
    setToast(message);
  }
  const handleError = (error: unknown) =>
    notify(error instanceof Error ? error.message : '操作失败，请重试');

  useEffect(() => {
    let mounted = true;
    Promise.all([
      api<Configuration>('/api/config'),
      api<Sample[]>('/api/samples'),
      api<Job[]>('/api/jobs'),
    ])
      .then(([configuration, examples, tasks]) => {
        if (!mounted) return;
        setConfig(configuration);
        setSamples(examples);
        setSample(examples[1] || examples[0]);
        setJobs(tasks);
        setConnected(true);
        const saved =
          new URLSearchParams(window.location.search).get('job') ||
          localStorage.getItem('form_active_job');
        const existing = tasks.find((task) => task.id === saved);
        const revised =
          existing?.request.route === 'template'
            ? tasks.find(
                (task) =>
                  task.request.image_id === existing.request.image_id &&
                  task.request.route === 'assistant' &&
                  task.model_url,
              )
            : undefined;
        if (revised || existing) void openJob((revised || existing)!);
      })
      .catch((error) => {
        if (mounted) handleError(error);
      });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(''), 7000);
    return () => clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (!job || !['queued', 'running', 'awaiting_assistant'].includes(job.status)) return;
    let stopped = false;
    const timer = setInterval(() => {
      api<Job>('/api/jobs/' + job.id)
        .then((value) => {
          if (!stopped) {
            setJob(value);
            setConnected(true);
            setJobs((previous) => [value, ...previous.filter((item) => item.id !== value.id)]);
          }
        })
        .catch(() => {
          if (!stopped) setConnected(false);
        });
    }, 1200);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [job?.id, job?.status]);

  useEffect(() => {
    setModelLoaded(false);
  }, [previewUrl]);
  useEffect(() => {
    if (!panel) return;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
    const elements = () =>
      Array.from(
        dialog?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled)',
        ) || [],
      ).filter((element) => element.offsetParent !== null);
    elements()[0]?.focus();
    function close(event: KeyboardEvent) {
      if (event.key === 'Escape') setPanel(null);
      if (event.key === 'Tab') {
        const focusable = elements();
        const first = focusable[0],
          last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    }
    document.addEventListener('keydown', close);
    return () => {
      document.removeEventListener('keydown', close);
      document.body.style.overflow = overflow;
      previous?.focus({ preventScroll: true });
    };
  }, [panel]);

  async function upload(file?: File) {
    if (!file || busy) return;
    if (file.size > 12 * 1024 * 1024) return notify('图片不能超过 12 MB');
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type))
      return notify('请选择 JPG、PNG 或 WebP 图片');
    setUploading(true);
    try {
      const body = new FormData();
      body.append('file', file);
      const result = await api<UploadedImage>('/api/images', { method: 'POST', body });
      setImage(result);
      setInputReferences([]);
      setName(file.name.replace(/\.[^.]+$/, ''));
      setTarget(wholeImage);
      setStrokes([]);
      setJob(undefined);
      setObjects([]);
      setSelectedObject('');
      setObjectLabel('');
      selectionTouched.current = false;
      setComparison(false);
      setRoute('local');
      setRemoveBackground(true);
      setLocalEngine('triposr');
      setLocalSegmentation('auto');
      setObjectCategory('');
      setAutoRetry(true);
      localStorage.removeItem('form_active_job');
      creationKey.current = undefined;
    } catch (error) {
      handleError(error);
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  }

  function reset() {
    if (busy) return notify('请等待当前处理完成，或先取消任务');
    setImage(undefined);
    setInputReferences([]);
    setJob(undefined);
    setName('');
    setTarget(wholeImage);
    setStrokes([]);
    setComparison(false);
    setConfirmed(false);
    setRoute('local');
    setRemoveBackground(true);
    setLocalEngine('triposr');
    setLocalSegmentation('auto');
    setObjectCategory('');
    setAutoRetry(true);
    setObjects([]);
    setSelectedObject('');
    setObjectLabel('');
    selectionTouched.current = false;
    setPanel(null);
    localStorage.removeItem('form_active_job');
    history.replaceState({}, '', window.location.pathname);
    creationKey.current = undefined;
  }

  async function openJob(task: Job) {
    try {
      const [source, references] = await Promise.all([
        api<UploadedImage>('/api/images/' + task.request.image_id),
        Promise.all(
          (task.reference_image_ids ?? task.request.reference_image_ids ?? []).map((id) =>
            api<UploadedImage>('/api/images/' + id),
          ),
        ),
      ]);
      setJob(task);
      setImage(source);
      setInputReferences(references);
      setTarget(task.request.target);
      setStrokes(task.request.strokes);
      setName(task.name);
      setRoute(task.request.route);
      setRemoveBackground(task.request.local_remove_background ?? true);
      setLocalEngine(task.request.local_engine || 'triposr');
      setLocalSegmentation(task.request.local_segmentation || 'auto');
      setObjectCategory(task.request.object_category || '');
      setAutoRetry(task.request.local_auto_retry ?? true);
      setObjects([]);
      setSelectedObject(task.request.object_id || '');
      setObjectLabel(task.request.object_label || '');
      selectionTouched.current = true;
      setTemplate(task.request.template);
      setWidth(task.request.dimensions.width * 100);
      setDepth(task.request.dimensions.depth * 100);
      setHeight(task.request.dimensions.height * 100);
      setConfirmed(task.request.dimensions.confirmed);
      setComparison(false);
      setColor(task.request.color);
      setLevels(task.request.levels);
      creationKey.current = undefined;
      setPanel(null);
      localStorage.setItem('form_active_job', task.id);
      history.replaceState({}, '', '?job=' + task.id);
    } catch (error) {
      handleError(error);
    }
  }

  async function generate() {
    if (!image || busy || remoteNeedsAttention || assistantWaiting) return;
    if (
      route === 'template' &&
      [width, depth, height].some((value) => !Number.isFinite(value) || value < 10 || value > 500)
    )
      return notify('长、深、高均须在 10～500 cm 之间');
    if (route === 'meshy' && !consent) return notify('请先确认第三方图片处理与计费说明');
    if (route === 'local' && !localReady)
      return notify('所选本地模型尚未完成运行验证，请查看服务状态');
    setSubmitting(true);
    // Keep a stable key if the browser loses the creation response.
    creationKey.current ||= crypto.randomUUID();
    try {
      const task = await post<Job>(
        '/api/jobs',
        {
          image_id: image.id,
          reference_image_ids: inputReferences.map((v) => v.id),
          name: name.trim() || '未命名商品',
          target,
          strokes,
          route,
          local_remove_background: removeBackground,
          local_engine: localEngine,
          local_segmentation: localSegmentation,
          object_category: objectCategory,
          local_auto_retry: autoRetry,
          object_label: objectLabel,
          object_id: selectedObject,
          template,
          dimensions: { width: width / 100, depth: depth / 100, height: height / 100, confirmed },
          color,
          levels,
          allow_external: consent,
        },
        { 'Idempotency-Key': creationKey.current },
      );
      setJob(task);
      setJobs((previous) => [task, ...previous.filter((item) => item.id !== task.id)]);
      setComparison(false);
      localStorage.setItem('form_active_job', task.id);
      history.replaceState({}, '', '?job=' + task.id);
      creationKey.current = undefined;
    } catch (error) {
      handleError(error);
    } finally {
      setSubmitting(false);
    }
  }

  async function action(operation: 'cancel' | 'resume' | 'accept' | 'reject') {
    if (!job || acting) return;
    if (operation === 'accept' && !modelLoaded) return notify('请等待模型加载并旋转查看后再审核');
    setActing(true);
    try {
      const updated = await post<Job>(
        `/api/jobs/${job.id}/${['accept', 'reject'].includes(operation) ? 'review' : operation}`,
        ['accept', 'reject'].includes(operation)
          ? {
              decision: operation,
              note:
                operation === 'accept' ? '用户已在工作台审核' : '需要调整图片或参数后创建新候选',
            }
          : {},
      );
      setJob(updated);
      setJobs((previous) => [updated, ...previous.filter((item) => item.id !== updated.id)]);
      if (operation === 'accept') notify('审核通过，交付包已更新');
    } catch (error) {
      handleError(error);
    } finally {
      setActing(false);
    }
  }

  function showSample(item: Sample) {
    if (busy) return notify('请先完成或取消当前任务');
    reset();
    setSample(item);
    setPanel(null);
  }

  function chooseObject(object: DetectedObject) {
    setObjectCategory(object.category);
    if (job) {
      setJob(undefined);
      localStorage.removeItem('form_active_job');
      history.replaceState({}, '', window.location.pathname);
    }
    setSelectedObject(object.id);
    setObjectLabel(object.label);
    setTarget(object.target);
    setStrokes([]);
    selectionTouched.current = true;
    creationKey.current = undefined;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="FORM 首页">
          <span className="brand-mark">
            <Box size={23} strokeWidth={1.6} />
          </span>
          <span>
            FORM<span className="brand-dot">.</span>
          </span>
        </a>
        <div className="workspace-label">CREATIVE WORKSPACE</div>
        <nav>
          <button
            aria-label="创作工作台"
            className={!panel ? 'nav-item selected' : 'nav-item'}
            onClick={() => setPanel(null)}
          >
            <WandSparkles size={18} />
            <span>创作工作台</span>
            <span className="nav-active-dot" />
          </button>
          <button
            aria-label="资产库"
            className={panel === 'assets' ? 'nav-item selected' : 'nav-item'}
            onClick={() => setPanel('assets')}
          >
            <Boxes size={18} />
            <span>资产库</span>
            <span className="nav-count">
              {jobs.filter((item) => item.status === 'completed').length + samples.length}
            </span>
          </button>
          <button
            aria-label="任务记录"
            className={panel === 'history' ? 'nav-item selected' : 'nav-item'}
            onClick={() => {
              setPanel('history');
              void api<Job[]>('/api/jobs').then(setJobs).catch(handleError);
            }}
          >
            <History size={18} />
            <span>任务记录</span>
            {jobs.length > 0 && <span className="nav-count">{jobs.length}</span>}
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="local-card">
            <span className="local-card-icon">
              <Layers3 size={19} />
            </span>
            <strong>从灵感，到立体</strong>
            <p>
              让商品的每个角度
              <br />
              都值得被看见。
            </p>
            <span className="local-version">
              LOCAL PREVIEW <i>v0.1</i>
            </span>
          </div>
          <button aria-label="使用指南" className="nav-item" onClick={() => setPanel('help')}>
            <CircleHelp size={18} />
            <span>使用指南</span>
            <ArrowUpRight size={14} />
          </button>
          <button aria-label="服务设置" className="nav-item" onClick={() => setPanel('settings')}>
            <Settings2 size={18} />
            <span>服务设置</span>
          </button>
          <div className="user-block">
            <div className="avatar">L</div>
            <div>
              <strong>本地工作空间</strong>
              <span>
                <i className={connected ? 'online' : 'offline'} />
                {connected ? '服务已连接' : '连接检查中'}
              </span>
            </div>
            <span className="user-local">本地</span>
          </div>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            工作空间 <ChevronRight size={13} />
            <span>图片转 3D</span>
          </div>
          <div className="topbar-actions">
            <span className="local-pill">
              <span />
              本地工作台
            </span>
            <button className="icon-button" aria-label="使用帮助" onClick={() => setPanel('help')}>
              <CircleHelp size={19} />
            </button>
            <span className="topbar-divider" />
            <div className="mini-avatar">L</div>
          </div>
        </header>
        <main className={modelEditing ? 'editing-model' : ''}>
          <div className="page-intro">
            <div>
              <div className="eyebrow">
                <span /> IMAGE TO 3D
              </div>
              <h1>
                {modelEditing ? '查看与编辑模型' : '让图片，拥有更多角度'}
                <span>。</span>
              </h1>
              <p>
                {modelEditing
                  ? '先查看模型，再选择部件换颜色或材质。'
                  : '从一张参考图片开始，制作可旋转、可查看的商品模型。'}
              </p>
            </div>
            {modelEditing && (
              <button
                className="button secondary"
                onClick={() => {
                  setPreparing(true);
                  setComparison(false);
                }}
              >
                修改图片 / 重新生成
              </button>
            )}
            {preparing && job?.model_url && (
              <button className="button secondary" onClick={() => setPreparing(false)}>
                返回模型编辑
              </button>
            )}
            <button className="button secondary new-task" onClick={reset}>
              <Plus size={16} />
              新建任务
            </button>
          </div>
          {!modelEditing && (
            <div className="workflow">
              {['上传参考图', '准备图片', '生成模型', '审核与导出'].map((step, i) => (
                <div
                  key={step}
                  className={`workflow-step ${i <= progress ? 'reached' : ''} ${i === progress ? 'current' : ''}`}
                >
                  <span className="step-circle">
                    {i < progress ? <Check size={13} /> : `0${i + 1}`}
                  </span>
                  <span>{step}</span>
                  {i < 3 && <div className="step-line" />}
                </div>
              ))}
              <span className="workflow-note">
                <ShieldCheck size={14} />
                原图始终保留
              </span>
            </div>
          )}

          <div className="work-grid">
            {!modelEditing && (
              <section className="card source-card">
                <div className="card-heading">
                  <div>
                    <span className="section-index">01</span>
                    <h2>参考图片</h2>
                  </div>
                  <span className="tag">单件商品</span>
                </div>
                <input
                  type="file"
                  ref={fileInput}
                  accept="image/jpeg,image/png,image/webp"
                  className="hidden"
                  data-testid="image-upload"
                  onChange={(event) => void upload(event.target.files?.[0])}
                />
                {image ? (
                  <>
                    <div className="uploaded-heading">
                      <div>
                        <FileImage size={16} />
                        <span title={image.name}>{image.name}</span>
                        <small>
                          {image.width} × {image.height}
                        </small>
                      </div>
                      <button disabled={busy} onClick={() => fileInput.current?.click()}>
                        更换图片
                      </button>
                    </div>
                    <ImageEditor
                      image={image}
                      target={target}
                      strokes={strokes}
                      onTarget={(value) => {
                        setTarget(value);
                        selectionTouched.current = true;
                        setSelectedObject('');
                        creationKey.current = undefined;
                      }}
                      onStrokes={(value) => {
                        setStrokes(value);
                        selectionTouched.current = true;
                        creationKey.current = undefined;
                      }}
                      disabled={!!busy}
                      objects={objects}
                      onObject={chooseObject}
                    />
                    <DetectedTargets
                      key={image.id}
                      image={image}
                      available={!!config?.detection.available}
                      selected={selectedObject}
                      autoPick={!selectionTouched.current && !job}
                      onObjects={setObjects}
                      onSelect={chooseObject}
                    />
                    {job?.segmented_url && (
                      <div className="segmentation-preview">
                        <strong>SAM 2 目标分割结果</strong>
                        <div className="segmentation-images">
                          <a href={job.segmented_url} target="_blank" rel="noreferrer">
                            <img src={job.segmented_url} alt="目标主体精细分割结果" />
                            <span>主体提取 · 点击放大</span>
                          </a>
                          <a href={job.segmentation_overlay_url} target="_blank" rel="noreferrer">
                            <img src={job.segmentation_overlay_url} alt="目标分割掩码叠加图" />
                            <span>绿色保留 · 红色丢弃</span>
                          </a>
                        </div>
                        <p>
                          这是算法结果，不是真值标注。可检查靠背、扶手与细腿是否保留；不会补全遮挡部分。
                        </p>
                      </div>
                    )}
                    {job?.input_quality && (
                      <div
                        className={
                          'input-preparation ' +
                          (job.input_quality.status === 'blocked' ? 'input-blocked' : '')
                        }
                      >
                        <strong>
                          {job.input_quality.status === 'blocked'
                            ? '输入需要修正，已停止建模'
                            : '输入清理与质量检查已完成'}
                        </strong>
                        <p>
                          {job.input_quality.removed_alpha_pixels > 0
                            ? '已清除与主体分离的尺寸标注。商品文字与主体结构保留。'
                            : '未发现可安全自动清除的独立尺寸文字。'}
                        </p>
                        {job.input_quality.reasons.map((reason) => (
                          <p key={reason.code}>{reason.message}</p>
                        ))}
                        {job.input_quality.warnings.map((warning) => (
                          <p key={warning}>{warning}</p>
                        ))}
                        <div className="segmentation-images">
                          <a href={job.cleaned_url} target="_blank" rel="noreferrer">
                            <img src={job.cleaned_url} alt="清理后的建模输入" />
                            <span>实际清理结果</span>
                          </a>
                          <a href={job.input_overlay_url} target="_blank" rel="noreferrer">
                            <img src={job.input_overlay_url} alt="文字和遮挡检查标记" />
                            <span>绿：清理 · 橙：保留文字 · 红：遮挡候选</span>
                          </a>
                        </div>
                        <p>检查通过只表示可以继续实验，不代表外观合格。遮挡部分尚未补全。</p>
                        <a href={job.input_quality_url} target="_blank" rel="noreferrer">
                          查看输入检查记录
                        </a>
                      </div>
                    )}
                  </>
                ) : (
                  <button
                    className={'upload-zone ' + (dragging ? 'dragging' : '')}
                    disabled={uploading}
                    onClick={() => fileInput.current?.click()}
                    onDragOver={(event) => {
                      event.preventDefault();
                      setDragging(true);
                    }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={(event) => {
                      event.preventDefault();
                      setDragging(false);
                      void upload(event.dataTransfer.files[0]);
                    }}
                  >
                    <span className="upload-illustration">
                      <span className="floating-square" />
                      <span className="photo-symbol">
                        <ImagePlus size={36} strokeWidth={1.4} />
                      </span>
                      <span className="upload-mini">
                        {uploading ? (
                          <LoaderCircle className="spin" size={17} />
                        ) : (
                          <Plus size={17} />
                        )}
                      </span>
                    </span>
                    <strong>
                      {uploading ? '正在保存参考图片…' : '点击上传，或把图片拖到这里'}
                    </strong>
                    <span>白底商品图或场景图均可</span>
                    <small>JPG、PNG、WebP · 最大 12 MB</small>
                  </button>
                )}
                <div className="source-tip">
                  <span className="tip-dot" />
                  <span>尽量选用主体完整、清晰且遮挡较少的图片</span>
                  <CircleHelp size={13} />
                </div>
                {image && !job && (
                  <details className="input-references">
                    <summary>补充参考视图（可选）</summary>
                    <p>
                      当前上传的主图用于生成；侧面、背面等补充图只用于验收对照，当前本地模型不做多视图融合。
                    </p>
                    <input
                      aria-label="建模补充视图"
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      multiple
                      disabled={busy}
                      onChange={async (event) => {
                        const files = Array.from(event.target.files || []);
                        if (inputReferences.length + files.length > 8)
                          return notify('最多 8 张补充图');
                        setUploading(true);
                        try {
                          const added: UploadedImage[] = [];
                          for (const file of files) {
                            const body = new FormData();
                            body.append('file', file);
                            added.push(
                              await api<UploadedImage>('/api/images', { method: 'POST', body }),
                            );
                          }
                          setInputReferences((old) => [...old, ...added]);
                          creationKey.current = undefined;
                        } catch (error) {
                          handleError(error);
                        } finally {
                          setUploading(false);
                        }
                      }}
                    />
                    <div className="reference-thumbnails">
                      {inputReferences.map((ref) => (
                        <button
                          key={ref.id}
                          onClick={() =>
                            setInputReferences((old) => old.filter((v) => v.id !== ref.id))
                          }
                          title="移除此补充视图"
                        >
                          <img src={ref.preview_url} alt="待保存的补充视图" />
                          移除
                        </button>
                      ))}
                    </div>
                  </details>
                )}

                <fieldset disabled={!!busy} className="generation-settings">
                  <label className="field-label" htmlFor="task-name">
                    商品名称 <span>可选</span>
                  </label>
                  <input
                    id="task-name"
                    className="text-input"
                    placeholder="为这件商品起个名字"
                    maxLength={100}
                    value={name}
                    onChange={(event) => {
                      setName(event.target.value);
                      creationKey.current = undefined;
                    }}
                  />
                  <div className="setting-title">
                    <label className="field-label">生成方式</label>
                    <button type="button" onClick={() => setPanel('settings')}>
                      服务状态 <ArrowUpRight size={11} />
                    </button>
                  </div>
                  <div className="route-options">
                    <button
                      disabled={!config?.providers.local.available}
                      className={'route-option local-route ' + (route === 'local' ? 'chosen' : '')}
                      onClick={() => {
                        setRoute('local');
                        creationKey.current = undefined;
                      }}
                    >
                      <Sparkles size={18} />
                      <span>
                        <strong>本地自动生成</strong>
                        <small>
                          {config?.providers.local.available
                            ? localEngine === 'hunyuan-mini'
                              ? 'Hunyuan · 仅几何'
                              : 'TripoSR · 无需密钥'
                            : '本地模型待就绪'}
                        </small>
                      </span>
                      <i>{route === 'local' && <Check size={10} />}</i>
                    </button>
                    <button
                      className={
                        'route-option assistant-route ' + (route === 'assistant' ? 'chosen' : '')
                      }
                      onClick={() => {
                        setRoute('assistant');
                        creationKey.current = undefined;
                      }}
                    >
                      <WandSparkles size={18} />
                      <span>
                        <strong>对话看图建模</strong>
                        <small>对话协作 · 无需密钥</small>
                      </span>
                      <i>{route === 'assistant' && <Check size={10} />}</i>
                    </button>
                    <button
                      className={'route-option ' + (route === 'template' ? 'chosen' : '')}
                      onClick={() => {
                        setRoute('template');
                        creationKey.current = undefined;
                      }}
                    >
                      <Box size={18} />
                      <span>
                        <strong>手动结构工具</strong>
                        <small>仅按参数搭建</small>
                      </span>
                      <i>{route === 'template' && <Check size={10} />}</i>
                    </button>
                    <button
                      disabled={!config?.providers.meshy.available}
                      title={
                        !config?.providers.meshy.available ? '请先在服务端配置 Meshy API 密钥' : ''
                      }
                      className={'route-option ' + (route === 'meshy' ? 'chosen' : '')}
                      onClick={() => {
                        setRoute('meshy');
                        creationKey.current = undefined;
                      }}
                    >
                      <Sparkles size={18} />
                      <span>
                        <strong>云端图生 3D</strong>
                        <small>
                          {config?.providers.meshy.available
                            ? '云端生成 · 按服务计费'
                            : '待配置云端服务'}
                        </small>
                      </span>
                      <i>{route === 'meshy' && <Check size={10} />}</i>
                    </button>
                  </div>
                  {route === 'template' ? (
                    <>
                      <div className="template-row">
                        <label className="field-label" htmlFor="template">
                          结构模板
                        </label>
                        <div className="select-wrap">
                          <select
                            id="template"
                            value={template}
                            onChange={(event) => {
                              setTemplate(event.target.value);
                              creationKey.current = undefined;
                            }}
                          >
                            {Object.entries(templateNames).map(([key, title]) => (
                              <option key={key} value={key}>
                                {title}
                              </option>
                            ))}
                          </select>
                          <ChevronDown size={13} />
                        </div>
                      </div>
                      <div className="dimension-label">
                        <label className="field-label">外形尺寸</label>
                        <span>单位 cm</span>
                      </div>
                      <div className="dimension-inputs">
                        {[
                          ['宽', width, setWidth],
                          ['深', depth, setDepth],
                          ['高', height, setHeight],
                        ].map(([label, value, setter]) => (
                          <label key={String(label)}>
                            <span>{String(label)}</span>
                            <input
                              aria-label={`${label}度（厘米）`}
                              type="number"
                              min={10}
                              max={500}
                              step={1}
                              value={Number(value)}
                              onChange={(event) => {
                                (setter as (v: number) => void)(Number(event.target.value));
                                creationKey.current = undefined;
                              }}
                            />
                          </label>
                        ))}
                      </div>
                      <div className="finish-row">
                        <div className="color-options">
                          <span>底色</span>
                          {colors.map((option) => (
                            <button
                              key={option}
                              style={{ background: option }}
                              className={color === option ? 'selected' : ''}
                              aria-label={'选择颜色 ' + option}
                              title={option}
                              onClick={() => {
                                setColor(option);
                                creationKey.current = undefined;
                              }}
                            >
                              {color === option && (
                                <Check
                                  size={11}
                                  color={option === '#f3f0e9' ? '#34343f' : 'white'}
                                />
                              )}
                            </button>
                          ))}
                        </div>
                        {template === 'shelf' && (
                          <label className="levels-control">
                            层数{' '}
                            <select
                              aria-label="层数"
                              value={levels}
                              onChange={(event) => {
                                setLevels(Number(event.target.value));
                                creationKey.current = undefined;
                              }}
                            >
                              {[2, 3, 4, 5, 6].map((value) => (
                                <option key={value}>{value}</option>
                              ))}
                            </select>
                          </label>
                        )}
                      </div>
                      <label className="checkbox-label">
                        <input
                          type="checkbox"
                          checked={confirmed}
                          onChange={(event) => {
                            setConfirmed(event.target.checked);
                            creationKey.current = undefined;
                          }}
                        />
                        <span>以上尺寸已对照实物或厂家资料确认</span>
                      </label>
                      <p className="method-note">
                        按所选模板与尺寸构建结构；当前需人工选择模板，图片用于参照。
                      </p>
                    </>
                  ) : route === 'local' ? (
                    <div className="assistant-note local-note">
                      <strong>
                        {localReady
                          ? '提交后自动生成，完成后直接在右侧查看。'
                          : '所选本地模型尚未完成运行验证。'}
                      </strong>
                      <div className="template-row">
                        <label className="field-label" htmlFor="local-engine">
                          本地模型
                        </label>
                        <div className="select-wrap">
                          <select
                            id="local-engine"
                            value={localEngine}
                            onChange={(event) => {
                              setLocalEngine(event.target.value as 'triposr' | 'hunyuan-mini');
                              creationKey.current = undefined;
                            }}
                          >
                            <option value="triposr" disabled={!config?.providers.local.available}>
                              TripoSR · 快速彩色
                            </option>
                            <option
                              value="hunyuan-mini"
                              disabled={
                                !config?.providers.local.engines?.['hunyuan-mini']?.available
                              }
                            >
                              Hunyuan3D-2mini · 几何实验
                            </option>
                          </select>
                          <ChevronDown size={13} />
                        </div>
                      </div>
                      <p>
                        {localEngine === 'hunyuan-mini'
                          ? '本轮只生成形状，使用中性灰材质，不包含商品纹理。生成完成后仍须检查关键结构、背面和尺寸。'
                          : '推荐单件、完整、背景干净的商品图。图片在本机处理，输出带颜色的 GLB，背面与尺寸需要审核。'}
                      </p>
                      <div className="template-row">
                        <label className="field-label" htmlFor="object-category">
                          目标品类
                        </label>
                        <select
                          id="object-category"
                          value={objectCategory}
                          onChange={(event) => {
                            setObjectCategory(event.target.value);
                            creationKey.current = undefined;
                          }}
                        >
                          <option value="">跟随识别 / 不确定</option>
                          <option value="cabinet">柜子 / 书柜</option>
                          <option value="table">桌子</option>
                          <option value="sofa">沙发 / 扶手椅</option>
                          <option value="chair">椅子</option>
                          <option value="vase">花瓶</option>
                          <option value="plant">盆栽</option>
                          <option value="lamp">灯具</option>
                          <option value="other">其他 / 薄结构</option>
                        </select>
                      </div>
                      <label className="checkbox-label">
                        <input
                          type="checkbox"
                          checked={autoRetry}
                          onChange={(event) => {
                            setAutoRetry(event.target.checked);
                            creationKey.current = undefined;
                          }}
                        />
                        <span>几何异常时最多换一个本地模型重试</span>
                      </label>
                      <label className="checkbox-label">
                        <input
                          type="checkbox"
                          checked={removeBackground}
                          onChange={(event) => {
                            setRemoveBackground(event.target.checked);
                            creationKey.current = undefined;
                          }}
                        />
                        <span>生成前自动去背景（已抠好的透明图可关闭）</span>
                      </label>
                      {removeBackground && (
                        <>
                          <div className="template-row">
                            <label className="field-label" htmlFor="local-segmentation">
                              分割策略
                            </label>
                            <div className="select-wrap">
                              <select
                                id="local-segmentation"
                                value={localSegmentation}
                                onChange={(event) => {
                                  setLocalSegmentation(
                                    event.target.value as 'auto' | 'sam2' | 'basic',
                                  );
                                  creationKey.current = undefined;
                                }}
                              >
                                <option value="auto">自动选择</option>
                                <option
                                  value="sam2"
                                  disabled={!config?.target_segmentation?.available}
                                >
                                  SAM 2 · 目标框分割
                                </option>
                                <option value="basic">基础去背景</option>
                              </select>
                              <ChevronDown size={13} />
                            </div>
                          </div>
                          <p>
                            {config?.target_segmentation?.available
                              ? '自动模式：复杂背景按目标框使用 SAM 2；白底和透明图保留原有处理。分割完成后可查看掩码叠加图。'
                              : 'SAM 2 尚未就绪，自动模式暂用基础去背景；复杂背景需要检查主体是否完整。'}
                          </p>
                        </>
                      )}
                    </div>
                  ) : route === 'assistant' ? (
                    <div className="assistant-note">
                      <strong>先提交图片，再在当前对话中让我建模。</strong>
                      <p>
                        我会根据选中的商品分析结构、编写模型并导出
                        GLB。完成后，模型会出现在右侧。当前需要对话协作，网页尚不能无人值守地调用我的能力。
                      </p>
                      <span>
                        {objectLabel
                          ? '当前物件：' + objectLabel
                          : '可提交完整商品图，也可选择已识别的物件'}
                      </span>
                    </div>
                  ) : (
                    <div className="cloud-consent">
                      <p>
                        <Cloud size={15} /> 选区与擦除结果将作为云端生成输入。
                      </p>
                      <label className="checkbox-label">
                        <input
                          type="checkbox"
                          checked={consent}
                          onChange={(event) => {
                            setConsent(event.target.checked);
                            creationKey.current = undefined;
                          }}
                        />
                        <span>
                          同意将处理后的图片发送给
                          Meshy，并由已配置账号承担供应商费用。每次仅提交一个候选。
                        </span>
                      </label>
                      <small>
                        提交状态不明确时暂停处理，不自动重复付费生成。实际费用请查看供应商账单。
                      </small>
                    </div>
                  )}
                </fieldset>
                <div className="generate-footer">
                  <button
                    className="button primary generate-button"
                    disabled={
                      !image ||
                      !!busy ||
                      remoteNeedsAttention ||
                      assistantWaiting ||
                      (route === 'local' && !localReady) ||
                      (route === 'meshy' && !consent)
                    }
                    onClick={() => void generate()}
                  >
                    {busy ? (
                      <LoaderCircle size={17} className="spin" />
                    ) : (
                      <WandSparkles size={17} />
                    )}
                    {submitting
                      ? '正在创建任务'
                      : active
                        ? '正在生成模型'
                        : assistantWaiting
                          ? '等待对话建模'
                          : remoteNeedsAttention
                            ? '请先核对云端任务'
                            : job?.model_url
                              ? '生成新的候选'
                              : route === 'assistant'
                                ? '提交看图建模'
                                : '开始生成'}
                    {!busy && <ArrowRight size={16} />}
                  </button>
                  <span>
                    {route === 'assistant'
                      ? '无需密钥 · 在当前对话中继续处理'
                      : route === 'local'
                        ? '本机自动处理 · 无需密钥'
                        : route === 'template'
                          ? '本地处理，无模型 API 费用'
                          : '第三方处理，按供应商规则计费'}
                  </span>
                </div>
              </section>
            )}

            <section className="card result-card">
              <div className="card-heading">
                <div>
                  <span className="section-index">02</span>
                  <h2>{modelEditing ? job?.name || '模型编辑' : '3D 预览'}</h2>
                </div>
                <div className="preview-heading-actions">
                  {modelEditing &&
                    previewUrl &&
                    (materialDraft || editorBusy ? (
                      <button
                        className="button primary model-download"
                        disabled
                        title="请先保存或取消预览"
                      >
                        下载模型
                      </button>
                    ) : (
                      <a className="button primary model-download" href={previewUrl} download>
                        <ArrowDownToLine size={15} />
                        下载模型
                      </a>
                    ))}
                  {job ? (
                    <span className={'status-tag status-' + job.status}>
                      {active && <LoaderCircle className="spin" size={11} />}
                      {viewingEdit
                        ? editedPreview?.reviewStatus === 'accepted'
                          ? '效果已确认'
                          : editedPreview?.reviewStatus === 'rejected'
                            ? '需修改'
                            : '效果待确认'
                        : statusLabels[job.status] || job.status}
                    </span>
                  ) : !image && sample ? (
                    <span className="sample-tag">示例资产</span>
                  ) : (
                    <span className="tag">等待生成</span>
                  )}
                  <button
                    className="icon-button"
                    aria-label="查看结果说明"
                    onClick={() => setPanel(job ? 'report' : 'help')}
                  >
                    <MoreHorizontal size={18} />
                  </button>
                </div>
              </div>
              <div className="result-workspace">
                <div className="model-pane">
                  <div className="preview-tabs">
                    <button
                      className={!comparison ? 'active' : ''}
                      onClick={() => setComparison(false)}
                    >
                      <Box size={14} />
                      查看模型
                    </button>
                    <button
                      disabled={!job?.prepared_url}
                      className={comparison ? 'active' : ''}
                      onClick={() => setComparison(true)}
                    >
                      <Layers3 size={14} />
                      对照原图
                    </button>
                    <span>{job ? '当前候选 · ' + job.id.slice(0, 6) : '可交互预览'}</span>
                  </div>
                  <div className={comparison ? 'comparison-mode' : ''}>
                    {comparison && (
                      <div className="comparison-image">
                        <img
                          src={referenceOverride || job?.model_input_url || job?.prepared_url}
                          alt="当前模型使用的参考图片"
                        />
                        <span>
                          {job?.model_input_url
                            ? '建模输入 · 自动抠图与居中结果'
                            : '建模输入 · 裁剪 / 擦除结果'}
                        </span>
                      </div>
                    )}
                    <Viewer
                      url={previewUrl}
                      label={job?.name || sample?.name || '商品模型预览'}
                      onLoaded={() => setModelLoaded(true)}
                      onPartPick={setPickedPart}
                      selectedPart={pickedPart}
                      selectedPartIds={selectedPartIds}
                      materialDraft={materialDraft}
                      completionBounds={completionBounds}
                      onDraftStatus={setDraftStatus}
                      editingDisabled={editorBusy || assistanceBusy}
                      jobId={job?.id}
                      onAssistanceBusy={setAssistanceBusy}
                      onFacesChange={job?.model_url ? setFaceSelection : undefined}
                      referenceUrl={referenceOverride || job?.model_input_url || job?.prepared_url}
                      showReferenceTools={comparison}
                    />
                  </div>
                  <details className="model-information" open={modelEditing ? undefined : true}>
                    <summary>模型信息与验收记录</summary>
                    {viewingEdit && (
                      <p className="source-report-note">
                        以下生成检查属于源模型。当前编辑版本可在“更多操作”中检查；未保存的预览不在下载文件中。
                      </p>
                    )}
                    <div className="preview-details">
                      <div className="model-title">
                        <span className="model-icon">
                          <Box size={19} />
                        </span>
                        <div>
                          <strong>
                            {job?.name || (!image ? sample?.name : undefined) || '等待新的作品'}
                          </strong>
                          <span>
                            {job
                              ? `${job.request.route === 'local' && (job.actual_engine || job.request.local_engine) === 'hunyuan-mini' ? 'Hunyuan3D-2mini · 仅几何' : routeNames[job.request.route]} · ${job.request.route === 'template' && job.request.dimensions.confirmed ? '用户确认的参数尺寸' : '尺寸未核准'}`
                              : !image && sample
                                ? '已有参考模型 · 用于体验预览'
                                : '生成后可在这里查看模型和质量报告'}
                          </span>
                        </div>
                        {previewUrl && <span className="format-badge">GLB</span>}
                      </div>
                      <div className="model-stats">
                        <div>
                          <span>部件</span>
                          <strong>{displayedMetrics ? displayedMetrics.parts : '—'}</strong>
                        </div>
                        <div>
                          <span>三角面</span>
                          <strong>
                            {displayedMetrics ? displayedMetrics.triangles.toLocaleString() : '—'}
                          </strong>
                        </div>
                        <div>
                          <span>文件大小</span>
                          <strong>
                            {displayedMetrics
                              ? (displayedMetrics.bytes / 1024 / 1024).toFixed(2) + ' MB'
                              : '—'}
                          </strong>
                        </div>
                        <div>
                          <span>尺寸状态</span>
                          <strong className="scale-label">
                            {job?.request.route === 'template' && job.request.dimensions.confirmed
                              ? '参数已确认'
                              : '未核准'}
                          </strong>
                        </div>
                      </div>
                    </div>
                    {job && (
                      <div className="job-progress">
                        {job.output_quality && (
                          <div className="input-preparation">
                            <strong>
                              {job.output_quality.status === 'blocked'
                                ? '输出几何异常，未作为可用资产发布'
                                : '输出几何检查完成，外观仍需审核'}
                            </strong>
                            {job.output_quality.reasons.map((reason) => (
                              <p key={reason.code}>{reason.message}</p>
                            ))}
                            {job.output_quality.warnings.map((warning) => (
                              <p key={warning}>{warning}</p>
                            ))}
                            {job.output_quality_url && (
                              <a href={job.output_quality_url} target="_blank" rel="noreferrer">
                                查看几何检查依据
                              </a>
                            )}
                            {job.output_attempts?.map((attempt) => (
                              <p key={attempt.index}>
                                尝试 {attempt.index} · {attempt.engine} · {attempt.status}{' '}
                                <a href={attempt.candidate_url} target="_blank" rel="noreferrer">
                                  诊断候选（不代表验收）
                                </a>
                              </p>
                            ))}
                          </div>
                        )}
                        <div className="event-current">
                          <span className={active ? 'running-dot' : 'event-dot'} />
                          <span>{job.error || job.events.at(-1)?.message || '任务已进入队列'}</span>
                          {(active ||
                            job.status === 'awaiting_assistant' ||
                            (job.attention_kind === 'local_input' &&
                              job.status === 'awaiting_input')) && (
                            <button disabled={acting} onClick={() => void action('cancel')}>
                              取消
                            </button>
                          )}
                        </div>
                        {job.status === 'awaiting_input' &&
                          job.attention_kind === 'local_input' && (
                            <div className="input-action-note">
                              <strong>本次未生成模型</strong>
                              <p>
                                可换一张无遮挡或更清晰的图片，或调整选区、擦除外部干扰后重新生成。被挡住的结构需要其他视图提供依据。
                              </p>
                              <button
                                className="button secondary"
                                onClick={() =>
                                  document
                                    .querySelector('.image-editor')
                                    ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                                }
                              >
                                回到图片调整
                              </button>
                            </div>
                          )}
                        {job.status === 'awaiting_input' && job.provider_task_id && (
                          <button
                            className="button secondary"
                            disabled={acting}
                            onClick={() => void action('resume')}
                          >
                            恢复查询已有云端任务
                          </button>
                        )}
                        {job.status === 'awaiting_assistant' && (
                          <button
                            className="button secondary"
                            onClick={() => {
                              void navigator.clipboard
                                .writeText('请处理待建模任务 ' + job.id)
                                .then(() => notify('已复制，回到当前对话发送即可'))
                                .catch(() =>
                                  notify('在当前对话中发送：请处理待建模任务 ' + job.id),
                                );
                            }}
                          >
                            复制对话建模请求
                          </button>
                        )}
                      </div>
                    )}
                    {job?.model_url ? (
                      <div className="review-box">
                        <div>
                          <ShieldCheck size={16} />
                          <strong>
                            {viewingEdit
                              ? editedPreview?.reviewStatus === 'accepted'
                                ? '编辑版本已通过人工审核'
                                : editedPreview?.reviewStatus === 'rejected'
                                  ? '编辑版本需要修改'
                                  : '编辑版本未验收，原始审核不继承'
                              : job.status === 'completed'
                                ? '已通过人工审核'
                                : job.status === 'rejected'
                                  ? '需要调整后重新生成'
                                  : '请检查轮廓、部件、背面与材质'}
                          </strong>
                          <button onClick={() => setPanel('report')}>
                            质量报告 <ChevronRight size={12} />
                          </button>
                        </div>
                        {job.status === 'awaiting_review' && !viewingEdit && (
                          <div className="review-actions">
                            <button
                              className="button secondary"
                              disabled={acting}
                              onClick={() => void action('reject')}
                            >
                              <XCircle size={15} />
                              需要修改
                            </button>
                            <button
                              className="button accept"
                              disabled={acting || !modelLoaded}
                              onClick={() => void action('accept')}
                            >
                              <CheckCheck size={16} />
                              审核通过
                            </button>
                          </div>
                        )}
                        <a
                          className={
                            'button download-button ' + (job.status === 'completed' ? 'ready' : '')
                          }
                          href={viewingEdit ? previewUrl : `/api/jobs/${job.id}/files/model.glb`}
                        >
                          <ArrowDownToLine size={16} />
                          {viewingEdit ? '下载编辑模型' : '下载模型'}
                          <span>
                            GLB ·{' '}
                            {viewingEdit
                              ? editedPreview?.reviewStatus === 'accepted'
                                ? '已审核'
                                : '未审核'
                              : job.status === 'completed'
                                ? '已审核'
                                : '未审核'}
                          </span>
                        </a>
                        <a className="records-download" href={`/api/jobs/${job.id}/download`}>
                          {viewingEdit ? '下载原始生成记录包' : '下载处理记录包'}{' '}
                          <span>模型、图片与质量报告（可选）</span>
                        </a>
                      </div>
                    ) : (
                      <div className="preview-footnote">
                        <ShieldCheck size={15} />
                        <span>生成结果需审核后交付；不可见结构可能来自推测。</span>
                      </div>
                    )}
                  </details>
                </div>
                {job?.model_url && (
                  <AssetEditor
                    key={job.id}
                    jobId={job.id}
                    pickedPart={pickedPart}
                    onSelect={setPickedPart}
                    onScope={setSelectedPartIds}
                    onCompletionBounds={setCompletionBounds}
                    onMaterialDraft={setMaterialDraft}
                    previewStatus={draftStatus}
                    onBusyChange={setEditorBusy}
                    externalBusy={assistanceBusy}
                    faces={faceSelection}
                    onReference={(url) => {
                      setReferenceOverride(url);
                      if (url) setComparison(true);
                    }}
                    onPreview={(url, metrics, reviewStatus) =>
                      setEditedPreview({ jobId: job.id, url, metrics, reviewStatus })
                    }
                  />
                )}
              </div>
            </section>
          </div>

          {!modelEditing && (
            <section className="examples-section">
              <div className="examples-heading">
                <div>
                  <h2>看看不同材质的可能</h2>
                  <span>已有参考资产，体验模型的不同角度</span>
                </div>
                <button onClick={() => setPanel('assets')}>
                  浏览资产库 <ArrowRight size={14} />
                </button>
              </div>
              <div className="examples-grid">
                {samples.map((item) => (
                  <button
                    key={item.id}
                    className={
                      'example-card ' + (!image && sample?.id === item.id ? 'example-selected' : '')
                    }
                    onClick={() => showSample(item)}
                  >
                    <div className="example-image">
                      <img loading="lazy" src={item.preview_url} alt={item.name} />
                      <span>参考资产</span>
                      <i>
                        <ArrowUpRight size={16} />
                      </i>
                    </div>
                    <div className="example-caption">
                      <div>
                        <strong>{item.name}</strong>
                        <span>{item.material}</span>
                      </div>
                      <Box size={16} />
                    </div>
                  </button>
                ))}
              </div>
            </section>
          )}
          <footer className="page-footer">
            <span>FORM · 将灵感塑造成形</span>
            <span>单图中的遮挡与不可见结构需要人工确认</span>
          </footer>
        </main>
      </div>

      {toast && (
        <div className="toast" role="alert">
          <span>{toast}</span>
          <button aria-label="关闭提示" onClick={() => setToast('')}>
            <X size={16} />
          </button>
        </div>
      )}
      {panel && (
        <div className="modal-backdrop" onClick={() => setPanel(null)}>
          <section
            className={'modal ' + (panel === 'assets' ? 'wide-modal' : '')}
            role="dialog"
            aria-modal="true"
            aria-labelledby="dialog-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-heading">
              <div>
                <span className="eyebrow">FORM WORKSPACE</span>
                <h2 id="dialog-title">
                  {
                    {
                      history: '任务记录',
                      assets: '资产库',
                      help: '从第一件商品开始',
                      settings: '服务与工作空间',
                      report: '质量报告',
                    }[panel]
                  }
                </h2>
              </div>
              <button className="icon-button" aria-label="关闭窗口" onClick={() => setPanel(null)}>
                <X size={20} />
              </button>
            </div>
            {panel === 'history' && (
              <div className="history-list">
                {jobs.length ? (
                  jobs.map((task) => (
                    <button key={task.id} onClick={() => void openJob(task)}>
                      <span className="history-icon">
                        <Box size={20} />
                      </span>
                      <span>
                        <strong>{task.name}</strong>
                        <small>
                          {new Date(task.created_at).toLocaleString('zh-CN')} ·{' '}
                          {routeNames[task.request.route]}
                        </small>
                      </span>
                      <span className={'status-tag status-' + task.status}>
                        {statusLabels[task.status]}
                      </span>
                      <ChevronRight size={16} />
                    </button>
                  ))
                ) : (
                  <div className="modal-empty">
                    <History size={32} />
                    <p>还没有任务，上传第一张参考图即可开始。</p>
                  </div>
                )}
              </div>
            )}
            {panel === 'assets' && (
              <>
                <p className="modal-description">
                  参考资产用于体验预览；你的生成资产会保存在本地任务记录中。
                </p>
                <div className="asset-grid">
                  {samples.map((item) => (
                    <button className="example-card" key={item.id} onClick={() => showSample(item)}>
                      <div className="example-image">
                        <img src={item.preview_url} alt={item.name} />
                        <span>参考资产</span>
                      </div>
                      <div className="example-caption">
                        <strong>{item.name}</strong>
                        <ArrowUpRight size={16} />
                      </div>
                    </button>
                  ))}
                </div>
                <h3 className="modal-subheading">已审核资产</h3>
                {jobs
                  .filter((task) => task.status === 'completed')
                  .map((task) => (
                    <button className="asset-job" key={task.id} onClick={() => void openJob(task)}>
                      <Box size={16} />
                      {task.name}
                      <ArrowRight size={15} />
                    </button>
                  ))}
                {!jobs.some((task) => task.status === 'completed') && (
                  <p className="muted">审核通过后，你的资产会显示在这里。</p>
                )}
              </>
            )}
            {panel === 'help' && (
              <div className="help-content">
                {[
                  [
                    '01',
                    '上传并选中商品',
                    '上传一张 JPG、PNG 或 WebP 图片，本地模型会自动找出柜子、花瓶、沙发、盆栽等候选，点击即可选择。必要时再修正框选或擦除背景。',
                  ],
                  [
                    '02',
                    '选择生成方式',
                    '本地自动生成无需密钥：提交后由本机 TripoSR 自动生成 GLB。对话看图建模保留用于人工协作；云端服务需要另行配置密钥。',
                  ],
                  [
                    '03',
                    '旋转查看与审核',
                    '查看正面、背面和侧面，确认部件、轮廓与材质。可直接下载 GLB；处理记录包另外保留图片与质量报告，供复查和返工。',
                  ],
                ].map(([number, title, description]) => (
                  <div className="help-step" key={number}>
                    <span>{number}</span>
                    <div>
                      <h3>{title}</h3>
                      <p>{description}</p>
                    </div>
                  </div>
                ))}
                <div className="notice">
                  <ShieldCheck size={18} />
                  <p>
                    单张图片无法保证恢复不可见结构与真实尺度。本地生成会分割主体、清理独立尺寸标注并检查输入风险；破碎掩码、像素不足或可能遮挡的任务会提示修正图片。遮挡补全和精确照片纹理尚未实现。
                  </p>
                </div>
              </div>
            )}
            {panel === 'settings' && (
              <div className="settings-content">
                <div className="service-row">
                  <span>
                    <ShieldCheck size={19} />
                    <strong>尺寸标注清理与输入检查</strong>
                  </span>
                  <span
                    className={config?.input_preparation?.available ? 'service-ready' : 'muted'}
                  >
                    {config?.input_preparation?.available
                      ? '本地已就绪 · 不补全遮挡'
                      : '待安装或实际运行验证'}
                  </span>
                </div>
                <div className="service-row">
                  <span>
                    <Sparkles size={19} />
                    <strong>TripoSR 本地自动生成</strong>
                  </span>
                  <span className={config?.providers.local.available ? 'service-ready' : 'muted'}>
                    {config?.providers.local.available
                      ? '已就绪，无需密钥'
                      : '模型或运行环境待就绪'}
                  </span>
                </div>
                {config?.providers.local.device && (
                  <p className="muted">本地显卡：{config.providers.local.device}</p>
                )}
                <div className="service-row">
                  <span>
                    <Box size={19} />
                    <strong>Hunyuan3D-2mini 几何实验</strong>
                  </span>
                  <span
                    className={
                      config?.providers.local.engines?.['hunyuan-mini']?.available
                        ? 'service-ready'
                        : 'muted'
                    }
                  >
                    {config?.providers.local.engines?.['hunyuan-mini']?.available
                      ? '实际推理已验证 · 无纹理'
                      : '实际运行验证待完成'}
                  </span>
                </div>
                <div className="service-row">
                  <span>
                    <Box size={19} />
                    <strong>对话看图建模</strong>
                  </span>
                  <span className="service-ready">可用</span>
                </div>
                <div className="service-row">
                  <span>
                    <WandSparkles size={19} />
                    <strong>本地目标识别</strong>
                  </span>
                  <span className={config?.detection.available ? 'service-ready' : 'muted'}>
                    {config?.detection.available ? '已就绪，无需密钥' : '模型未就绪'}
                  </span>
                </div>
                <div className="service-row">
                  <span>
                    <Sparkles size={19} />
                    <strong>Meshy 图生 3D</strong>
                  </span>
                  <span className={config?.providers.meshy.available ? 'service-ready' : 'muted'}>
                    {config?.providers.meshy.available ? '密钥已配置，需实际账号联调' : '未配置'}
                  </span>
                </div>
                <div className="service-row">
                  <span>
                    <Layers3 size={19} />
                    <strong>SAM 2 目标精细分割</strong>
                  </span>
                  <span
                    className={config?.target_segmentation?.available ? 'service-ready' : 'muted'}
                  >
                    {config?.target_segmentation?.available
                      ? '本地已就绪 · 按目标框提取'
                      : '待安装或运行验证'}
                  </span>
                </div>
                <p>
                  在项目根目录的 <code>.env</code> 中设置 <code>MESHY_API_KEY</code>
                  ，然后重启后端。密钥保存在服务端，不进入浏览器。
                </p>
                <div className="notice">
                  <Cloud size={18} />
                  <p>
                    云端按供应商规则计费，当前适配器尚需真实账号验证。本地模式采用 SQLite
                    与本地文件，适合单人试验，请保持服务仅监听 127.0.0.1。
                  </p>
                </div>
                <p className="muted">
                  生成式遮挡补全：待接入
                  <br />
                  真实尺寸 AR：待验证
                  <br />
                  本地 API：
                  <a href="/docs" target="_blank" rel="noreferrer">
                    查看接口文档 <ArrowUpRight size={12} />
                  </a>
                </p>
              </div>
            )}
            {panel === 'report' &&
              (job?.report ? (
                <div className="report-content">
                  <div className="report-summary">
                    <ShieldCheck size={22} />
                    <div>
                      <strong>
                        {job.status === 'completed'
                          ? '人工审核已通过'
                          : '技术检查完成，外观需要审核'}
                      </strong>
                      <span>
                        {job.request.route === 'local'
                          ? job.request.local_engine === 'hunyuan-mini'
                            ? '结构来源：本机 Hunyuan3D-2mini；当前仅几何，不含纹理'
                            : '结构来源：本机 TripoSR 根据当前图片自动推理'
                          : job.request.route === 'assistant'
                            ? '结构来源：根据参考图进行独立 Blender 建模'
                            : job.request.route === 'template'
                              ? '结构来源：人工选择的参数模板'
                              : '结构来源：云端图片生成'}
                      </span>
                    </div>
                  </div>
                  <div className="report-rows">
                    <div>
                      <span>GLB 基础结构检查</span>
                      <strong>通过</strong>
                    </div>
                    <div>
                      <span>完整 glTF Validator</span>
                      <span>
                        {job.report.checks.full_gltf_validator === 'pass' ? '通过' : '未执行'}
                      </span>
                    </div>
                    <div>
                      <span>浏览器模型加载</span>
                      <span>{modelLoaded ? '当前页面已加载' : '待查看'}</span>
                    </div>
                    <div>
                      <span>外观审核</span>
                      <span>
                        {job.review_status === 'accepted'
                          ? '已通过'
                          : job.review_status === 'rejected'
                            ? '需修改'
                            : '待审核'}
                      </span>
                    </div>
                    <div>
                      <span>真实尺度 AR</span>
                      <span>未启用</span>
                    </div>
                  </div>
                  <h3>结果说明</h3>
                  <ul>
                    {job.report.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                  <a
                    className="button secondary"
                    href={`/api/jobs/${job.id}/files/quality_report.json`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <ArrowDownToLine size={15} />
                    下载完整质量报告
                  </a>
                </div>
              ) : (
                <div className="modal-empty">
                  <Box size={32} />
                  <p>模型完成后可查看检查报告。</p>
                </div>
              ))}
          </section>
        </div>
      )}
    </div>
  );
}

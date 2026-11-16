import type { FaceSelection } from '../faceSelection';
import type { MaterialDraft, PreviewStatus } from '../materialDraft';
import { api, post } from '../types';
import type {
  Configuration,
  DetectedObject,
  Job,
  Sample,
  Stroke,
  Target,
  UploadedImage,
  Route,
} from '../types';
import { useEffect, useRef, useState } from 'react';
import { wholeImage, colors, Panel } from './constants';

/** All workbench state, derived flags and actions shared by the page sections. */
export function useWorkbench() {
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
  const [route, setRoute] = useState<Route>('local');
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
  const [completionBounds, setCompletionBounds] = useState<number[][]>();
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
  const partsReady = !!config?.providers.parts_first?.available;
  const partsCategoryReady = ['sofa', 'chair', 'table', 'cabinet'].includes(objectCategory);
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
    if (route === 'parts_first' && !partsReady)
      return notify('部件优先生成环境未就绪，请查看服务状态');
    if (route === 'parts_first' && !partsCategoryReady)
      return notify('部件优先生成需要先选择家具类别');
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

  return {
    partsReady,
    partsCategoryReady,
    config,
    setConfig,
    samples,
    setSamples,
    sample,
    setSample,
    jobs,
    setJobs,
    job,
    setJob,
    image,
    setImage,
    inputReferences,
    setInputReferences,
    target,
    setTarget,
    strokes,
    setStrokes,
    name,
    setName,
    route,
    setRoute,
    removeBackground,
    setRemoveBackground,
    localEngine,
    setLocalEngine,
    localSegmentation,
    setLocalSegmentation,
    objectCategory,
    setObjectCategory,
    autoRetry,
    setAutoRetry,
    editedPreview,
    setEditedPreview,
    pickedPart,
    setPickedPart,
    completionBounds,
    setCompletionBounds,
    selectedPartIds,
    setSelectedPartIds,
    draftStatus,
    setDraftStatus,
    editorBusy,
    setEditorBusy,
    assistanceBusy,
    setAssistanceBusy,
    faceSelection,
    setFaceSelection,
    referenceOverride,
    setReferenceOverride,
    objects,
    setObjects,
    selectedObject,
    setSelectedObject,
    objectLabel,
    setObjectLabel,
    selectionTouched,
    template,
    setTemplate,
    width,
    setWidth,
    confirmed,
    setConfirmed,
    color,
    setColor,
    levels,
    setLevels,
    consent,
    setConsent,
    uploading,
    setUploading,
    submitting,
    setSubmitting,
    acting,
    setActing,
    dragging,
    setDragging,
    panel,
    setPanel,
    toast,
    setToast,
    connected,
    setConnected,
    modelLoaded,
    setModelLoaded,
    comparison,
    setComparison,
    preparing,
    setPreparing,
    modelEditing,
    fileInput,
    creationKey,
    busy,
    active,
    remoteNeedsAttention,
    assistantWaiting,
    localReady,
    progress,
    previewUrl,
    viewingEdit,
    displayedMetrics,
    notify,
    handleError,
    upload,
    reset,
    openJob,
    generate,
    action,
    showSample,
    chooseObject,
    materialDraft,
    setMaterialDraft,
    depth,
    setDepth,
    height,
    setHeight,
  };
}

export type Workbench = ReturnType<typeof useWorkbench>;

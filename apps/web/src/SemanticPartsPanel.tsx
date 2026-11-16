import { useEffect, useRef, useState } from 'react';
import { api, post } from './types';
import Viewer from './Viewer';
import './semanticParts.css';
interface Group {
  id: string;
  name: string;
  color: string;
  kind: string;
  faces: number;
  surface_only: boolean;
  needs_boundary_review?: boolean;
  views?: number[];
}
interface Scan {
  scan_id: string;
  version: string;
  status: 'queued' | 'running' | 'ready' | 'failed';
  stage: string;
  error?: string;
  preview_url?: string;
  groups?: Group[];
  parts?: { id: string; logical_group_id?: string }[];
  warnings?: string[];
}
export default function SemanticPartsPanel({
  jobId,
  version,
  disabled,
  category,
  onSave,
}: {
  jobId: string;
  version: string;
  disabled: boolean;
  category: string;
  onSave: (scanId: string) => Promise<void>;
}) {
  const [scan, setScan] = useState<Scan>(),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [selected, setSelected] = useState<string>(),
    [previewOpen, setPreviewOpen] = useState(false);
  const key = jobId + '|' + version,
    latest = useRef(key);
  latest.current = key;
  useEffect(() => {
    setScan(undefined);
    setError('');
    setSelected(undefined);
    setPreviewOpen(false);
  }, [key]);
  useEffect(() => {
    if (scan?.status === 'ready') setPreviewOpen(true);
  }, [scan?.scan_id, scan?.status]);
  useEffect(() => {
    if (!previewOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const escape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPreviewOpen(false);
    };
    document.addEventListener('keydown', escape);
    return () => {
      document.body.style.overflow = previous;
      document.removeEventListener('keydown', escape);
    };
  }, [previewOpen]);
  useEffect(() => {
    if (!scan || !['queued', 'running'].includes(scan.status)) return;
    let disposed = false;
    const captured = key;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api<Scan>(`/api/jobs/${jobId}/asset/semantic-scans/${scan.scan_id}`);
        if (disposed || latest.current !== captured) return;
        setError('');
        setScan(next);
        if (['queued', 'running'].includes(next.status)) timer = setTimeout(poll, 1800);
      } catch (e) {
        if (!disposed && latest.current === captured) {
          setError('连接暂时中断，正在重新读取识别进度…');
          timer = setTimeout(poll, 3000);
        }
      }
    };
    timer = setTimeout(poll, 1200);
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [scan?.scan_id, key]);
  async function recognize() {
    const captured = key;
    setBusy(true);
    setError('');
    try {
      const next = await post<Scan>(`/api/jobs/${jobId}/asset/semantic-scans`, {
        version,
        category: ['sofa', 'chair', 'table', 'cabinet'].includes(category) ? category : 'auto',
      });
      if (latest.current === captured) setScan(next);
    } catch (e) {
      if (latest.current === captured) setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function adopt() {
    if (!scan) return;
    setBusy(true);
    setError('');
    try {
      await onSave(scan.scan_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const running = !!scan && ['queued', 'running'].includes(scan.status),
    stages: Record<string, string> = {
      queued: '等待开始',
      rendering: '查看模型的六个方向',
      waiting_gpu: '等待本地显卡',
      recognizing: 'AI 识别坐垫、靠枕等整体',
      grouping: '合并同一部件并清理碎点',
    };
  const selectedIds = (scan?.parts ?? [])
    .filter((p) => p.logical_group_id === selected)
    .map((p) => p.id);
  return (
    <section className="semantic-parts-panel" aria-label="AI 整体部件识别">
      <strong>AI 整体部件识别与分色</strong>
      <p>自动寻找整体部件候选，合并同一部件；证据不足的区域以灰色保留，无需逐个涂选。</p>
      <button disabled={disabled || busy || running} onClick={() => void recognize()}>
        {running ? '正在自动识别…' : 'AI 自动识别并分色'}
      </button>
      {running && <p role="status">{stages[scan.stage] ?? '正在分析'}。完成前不会改变当前模型。</p>}
      {(error || scan?.error) && <p role="alert">{error || scan?.error}</p>}
      {scan?.status === 'ready' && scan.preview_url && (
        <>
          <button onClick={() => setPreviewOpen(true)}>查看 AI 整体分色结果</button>
          {previewOpen && (
            <div
              className="semantic-modal"
              role="dialog"
              aria-modal="true"
              aria-label="AI 整体分色结果"
            >
              <div className="semantic-modal-content">
                <div className="semantic-modal-heading">
                  <strong>AI 整体分色结果</strong>
                  <button autoFocus onClick={() => setPreviewOpen(false)}>
                    关闭分色预览
                  </button>
                </div>
                <div className="semantic-preview">
                  <Viewer
                    key={scan.scan_id}
                    url={scan.preview_url}
                    label="AI 整体分色预览"
                    inspectionOnly
                    selectedPartIds={selectedIds}
                    onPartPick={(id) =>
                      setSelected(scan.parts?.find((p) => p.id === id)?.logical_group_id)
                    }
                  />
                </div>
                <div className="semantic-group-list" role="group" aria-label="AI 整体部件候选">
                  {scan.groups?.map((g) => (
                    <button
                      key={g.id}
                      aria-pressed={selected === g.id}
                      onClick={() => setSelected(g.id)}
                    >
                      <span className="semantic-colour" style={{ background: g.color }} />
                      {g.name}
                      {g.kind === 'unknown' || g.needs_boundary_review ? ' · 待确认' : ''}
                    </button>
                  ))}
                </div>
                <p>
                  分色只是区分部件，保存后仍保留原材质。粘连模型中的隐藏边界尚未补齐，当前结果适合按组换材质；实体拆装仍需检查。
                </p>
                {scan.warnings?.map((w) => <p key={w}>{w}</p>)}
                {error && <p role="alert">{error}</p>}
                <button disabled={disabled || busy} onClick={() => void adopt()}>
                  采用 AI 整体分组
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}

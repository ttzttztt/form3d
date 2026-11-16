import { useEffect, useState, useRef } from 'react';
import { api, post } from './types';
import Viewer from './Viewer';
interface Candidate {
  id: string;
  name: string;
  status: string;
  stage: string;
  model_url?: string;
  actual_engine?: string;
  requested_engine: string;
  metrics?: { triangles: number };
  output_quality?: { status: string };
  error?: string;
  review_status: string;
  quality?: string;
}
interface Comparison {
  reference_url: string;
  candidates: Candidate[];
}
const stateLabel: Record<string, string> = {
  queued: '排队中',
  running: '生成中',
  awaiting_review: '待检查',
  completed: '已验收',
  rejected: '需要修改',
  failed: '生成失败',
  awaiting_input: '需要处理输入或模型问题',
  cancelled: '已取消',
};
const engineLabel = (engine: string) =>
  engine === 'hunyuan-mini'
    ? 'Hunyuan · 仅形状'
    : engine === 'triposr'
      ? 'TripoSR · 预测颜色'
      : engine;
export default function ReconstructionCompare({
  jobId,
  disabled = false,
  onClose,
}: {
  jobId: string;
  disabled?: boolean;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
    return () => dialog.current?.close();
  }, []);
  const [value, setValue] = useState<Comparison>(),
    [left, setLeft] = useState(''),
    [right, setRight] = useState(''),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const [quality, setQuality] = useState('balanced');
  const refresh = async () => {
    const v = await api<Comparison>(`/api/jobs/${jobId}/reconstruction-comparison`);
    setValue(v);
    setLeft(
      (old) => old || v.candidates.find((c) => c.id === jobId)?.id || v.candidates[0]?.id || '',
    );
    setRight((old) => old || v.candidates.find((c) => c.id !== jobId)?.id || '');
  };
  useEffect(() => {
    let alive = true;
    const poll = () => {
      if (alive) void refresh().catch((e) => setError(e.message));
    };
    poll();
    const timer = setInterval(poll, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [jobId]);
  async function create(engine: string) {
    setBusy(true);
    setError('');
    try {
      const job = await post<Candidate>(`/api/jobs/${jobId}/reconstruction-comparison`, {
        engine,
        quality,
      });
      setRight(job.id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const candidate = (id: string) => value?.candidates.find((c) => c.id === id);
  return (
    <dialog
      ref={dialog}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      className="reconstruction-compare"
      role="dialog"
      aria-label="本地生成结果对照"
      aria-modal="true"
    >
      <button className="comparison-close" onClick={onClose}>
        关闭生成对照
      </button>
      <h3>同图本地引擎对照</h3>
      <p>使用同一图片、选框与清理设置比较本地引擎。保留独立任务，结果需看图验收。</p>
      <label>
        生成档位
        <select
          aria-label="生成细节档位"
          disabled={busy || disabled}
          value={quality}
          onChange={(e) => setQuality(e.target.value)}
        >
          <option value="balanced">常规</option>
          <option value="structure">结构细节（更慢）</option>
        </select>
      </label>
      <p>
        结构细节提高网格提取分辨率；Hunyuan
        同时增加采样步数。缺失的细腿或开口仍可能无法恢复，请对照原图检查。高面数结果可能需要先减面。
      </p>
      <div className="selection-actions">
        <button disabled={busy || disabled} onClick={() => void create('hunyuan-mini')}>
          准备 Hunyuan 几何候选
        </button>
        <button disabled={busy || disabled} onClick={() => void create('triposr')}>
          准备 TripoSR 候选
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      <div className="version-comparison">
        {[
          ['左侧生成候选', left, setLeft],
          ['右侧生成候选', right, setRight],
        ].map(([label, id, set]) => {
          const c = candidate(id as string);
          return (
            <div key={label as string}>
              <label>
                {label as string}
                <select
                  aria-label={label as string}
                  value={id as string}
                  onChange={(e) => (set as (v: string) => void)(e.target.value)}
                >
                  <option value="">请选择</option>
                  {value?.candidates.map((c) => (
                    <option key={c.id} value={c.id}>
                      {engineLabel(c.actual_engine || c.requested_engine)} ·{' '}
                      {stateLabel[c.status] || c.status} ·{' '}
                      {c.quality === 'structure' ? '结构细节' : '常规'} · {c.id.slice(0, 6)}
                    </option>
                  ))}
                </select>
              </label>
              {c && (
                <>
                  <p>
                    {engineLabel(c.actual_engine || c.requested_engine)} ·{' '}
                    {stateLabel[c.status] || c.status}
                    {' · '}
                    {c.quality === 'structure' ? '结构细节' : '常规'}
                    {c.metrics ? ` · ${c.metrics.triangles.toLocaleString()} 面` : ''}
                  </p>
                  {c.model_url ? (
                    <>
                      <Viewer url={c.model_url} label={'生成对照 ' + c.id} />
                      <a href={'/?job=' + c.id}>打开这个候选继续编辑</a>
                    </>
                  ) : (
                    <p>{c.error || '尚无通过文件检查的模型；生成中可稍后刷新。'}</p>
                  )}
                </>
              )}
            </div>
          );
        })}
      </div>
      <details>
        <summary>对照原图检查结构</summary>
        {value && (
          <img
            className="reconstruction-reference"
            src={value.reference_url}
            alt="同图引擎对照的原始图片"
          />
        )}
        {[
          '整体轮廓和比例',
          '桌腿 / 椅腿是否缺失或粘连',
          '柜门、开口和镂空是否保留',
          '是否混入背景摆件',
          '纹理是否错误、是否只有灰色几何',
        ].map((label) => (
          <label key={label}>
            <input type="checkbox" />
            已人工核对：{label}
          </label>
        ))}
        <p>这些勾选只帮助本次检查，不会自动标为外观合格。面数和几何筛查不能代表照片相似度。</p>
      </details>
    </dialog>
  );
}

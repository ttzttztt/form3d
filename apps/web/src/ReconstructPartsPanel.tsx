import { useEffect, useRef, useState } from 'react';
import { post } from './types';
import CutPreview from './CutPreview';

interface Result {
  preview_id: string;
  preview_url: string;
  operation: {
    groups: { id: string; name: string; status: string; reason?: string }[];
  };
}

export default function ReconstructPartsPanel({
  jobId,
  version,
  partIds,
  disabled,
  onSave,
}: {
  jobId: string;
  version: string;
  partIds: string[];
  disabled: boolean;
  onSave: (previewId: string) => Promise<void>;
}) {
  const [preview, setPreview] = useState<Result>(),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [loaded, setLoaded] = useState(false),
    [confirmed, setConfirmed] = useState(false);
  const key = JSON.stringify({ jobId, version, partIds }),
    latest = useRef(key);
  latest.current = key;
  useEffect(() => {
    latest.current = key;
    setBusy(false);
    setPreview(undefined);
    setError('');
    setLoaded(false);
    setConfirmed(false);
    return () => {
      if (latest.current === key) latest.current = '';
    };
  }, [key]);
  async function generate() {
    const captured = key;
    setBusy(true);
    setError('');
    setPreview(undefined);
    setLoaded(false);
    setConfirmed(false);
    try {
      const result = await post<Result>(`/api/jobs/${jobId}/asset/completion-preview`, {
        operation: 'reconstruct_parts',
        base_version: version,
        part_ids: partIds,
      });
      if (latest.current === captured) setPreview(result);
    } catch (e) {
      if (latest.current === captured) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (latest.current === captured) setBusy(false);
    }
  }
  async function save() {
    if (!preview || !loaded || !confirmed) return;
    const captured = key;
    setBusy(true);
    setError('');
    try {
      await onSave(preview.preview_id);
    } catch (e) {
      if (latest.current === captured) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (latest.current === captured) setBusy(false);
    }
  }
  return (
    <details className="solid-part-tools">
      <summary>生成独立部件预览</summary>
      <p>补齐已分组部件的开口，保持一组一个完整部件。未通过检查的组保留原样。</p>
      <button disabled={disabled || busy || !partIds.length} onClick={() => void generate()}>
        {busy ? '正在处理部件…' : '自动补齐当前范围的部件'}
      </button>
      {busy && <p role="status">正在检查闭合、自交和外形偏差，较复杂的模型可能需要几分钟。</p>}
      {error && <p role="alert">{error}</p>}
      {preview && (
        <>
          <CutPreview url={preview.preview_url} reconstructed onReady={() => setLoaded(true)} />
          <ul>
            {preview.operation.groups.map((g) => (
              <li key={g.id}>
                {g.name}：
                {g.status === 'reconstructed'
                  ? '已生成闭合候选，外形待检查'
                  : g.status === 'already_closed'
                    ? '已闭合，保留原样'
                    : '未采用，保留原样'}
                {g.reason ? '（' + g.reason + '）' : ''}
              </li>
            ))}
          </ul>
          <p>它会沿现有分组重建，不能自动修正分错的坐垫、扶手，也不能恢复真实隐藏结构。</p>
          <label>
            <input
              type="checkbox"
              checked={confirmed}
              disabled={!loaded || busy || disabled}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            我已查看正面、侧面和底面，接受这个重建候选
          </label>
          <button disabled={disabled || busy || !loaded || !confirmed} onClick={() => void save()}>
            保存这个独立部件候选
          </button>
        </>
      )}
    </details>
  );
}

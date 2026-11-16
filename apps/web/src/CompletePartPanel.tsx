import { useEffect, useMemo, useRef, useState } from 'react';
import { post } from './types';
import './completePart.css';
import CutPreview from './CutPreview';
import type { FaceSelection } from './faceSelection';
interface Plan {
  warnings?: string[];
  version: string;
  completion_bounds: number[][];
  source_bounds_world: number[][];
  source: { boundary_edges: number; nonmanifold_edges: number };
  guide: { boundary_edges: number };
  guide_direction_area_fraction: Record<string, number>;
}
interface Preview {
  preview_id: string;
  preview_url: string;
  operation: { part: { inferred_area_fraction: number }; plan: Plan };
}
export default function CompletePartPanel({
  jobId,
  version,
  partIds,
  faces,
  disabled,
  name,
  onBounds,
  onComplete,
}: {
  jobId: string;
  version: string;
  partIds: string[];
  faces: FaceSelection[];
  disabled: boolean;
  name: string;
  onBounds?: (bounds?: number[][]) => void;
  onComplete: (
    bounds: number[][],
    profile: string,
    shape: string,
    previewId: string,
  ) => Promise<void>;
}) {
  const [plan, setPlan] = useState<Plan>(),
    [bounds, setBounds] = useState<number[][]>(),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const [profile, setProfile] = useState('cushion');
  const [shape, setShape] = useState('contour'),
    [preview, setPreview] = useState<Preview>(),
    [previewReady, setPreviewReady] = useState(false),
    [confirmed, setConfirmed] = useState(false);
  const scopeKey = partIds.join('|');
  const signature = useMemo(
    () => JSON.stringify({ jobId, version, scopeKey, faces, profile, shape }),
    [jobId, version, scopeKey, faces, profile, shape],
  );
  const sourceRef = useRef(signature);
  sourceRef.current = signature;
  const previewKey = JSON.stringify({ signature, bounds, name });
  const previewRef = useRef(previewKey);
  previewRef.current = previewKey;
  useEffect(() => {
    setPreview(undefined);
    setPreviewReady(false);
    setConfirmed(false);
  }, [previewKey]);
  useEffect(() => {
    setPlan(undefined);
    setBounds(undefined);
    setError('');
    onBounds?.(undefined);
  }, [signature]);
  useEffect(
    () => () => {
      sourceRef.current = '';
      onBounds?.(undefined);
    },
    [],
  );
  const valid =
    !!bounds &&
    bounds.every((row) => row.every((v) => Number.isFinite(v) && v >= 0 && v <= 1)) &&
    bounds[0].every((v, i) => bounds[1][i] - v >= 0.005);
  useEffect(() => {
    if (!plan || !bounds || !valid) {
      onBounds?.(undefined);
      return;
    }
    onBounds?.(
      bounds.map((row) =>
        row.map(
          (v, i) =>
            plan.source_bounds_world[0][i] +
            v * (plan.source_bounds_world[1][i] - plan.source_bounds_world[0][i]),
        ),
      ),
    );
  }, [plan, bounds, valid]);
  async function diagnose() {
    const key = signature;
    setBusy(true);
    setError('');
    try {
      const p = await post<Plan>(`/api/jobs/${jobId}/asset/completion-plan`, {
        operation: 'complete_part',
        base_version: version,
        part_ids: partIds,
        face_selection: faces,
        completion_profile: profile === 'legs' ? 'support' : profile,
        completion_shape: shape,
        detail_level: profile === 'legs' ? 'fine' : 'coarse',
      });
      if (sourceRef.current === key) {
        setPlan(p);
        setBounds(p.completion_bounds);
      }
    } catch (e) {
      if (sourceRef.current === key) setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function previewCut() {
    if (!bounds || !valid) return;
    const key = previewKey;
    setBusy(true);
    setError('');
    setPreview(undefined);
    setPreviewReady(false);
    setConfirmed(false);
    try {
      const result = await post<Preview>(`/api/jobs/${jobId}/asset/completion-preview`, {
        operation: 'complete_part',
        base_version: version,
        part_ids: partIds,
        face_selection: faces,
        completion_bounds: bounds,
        completion_profile: profile === 'legs' ? 'support' : profile,
        completion_shape: shape,
        detail_level: profile === 'legs' ? 'fine' : 'coarse',
        name: name.trim(),
      });
      if (previewRef.current === key) setPreview(result);
    } catch (e) {
      if (previewRef.current === key) setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="solid-part-tools">
      <summary>完整部件：检查范围与补齐接合面</summary>
      <label>
        部件类型
        <select
          aria-label="完整部件类型"
          value={profile}
          disabled={disabled || busy}
          onChange={(e) => setProfile(e.target.value)}
        >
          <option value="cushion">坐垫 / 软包</option>
          <option value="support">底架 / 支撑</option>
          <option value="legs">单根支脚（保留连接座）</option>
          <option value="slab">桌面 / 板件</option>
        </select>
      </label>
      {profile === 'cushion' && (
        <label>
          切分方式
          <select
            aria-label="坐垫切分方式"
            value={shape}
            disabled={disabled || busy}
            onChange={(e) => setShape(e.target.value)}
          >
            <option value="contour">沿表面选区轮廓</option>
            <option value="box">按调整范围（手动确定厚度和前后边界）</option>
          </select>
        </label>
      )}
      <p>
        先在模型中用 AI
        辅助选区的“保留这里”补选侧面，用“不要这里”排除靠垫和扶手；可拖动旋转，也可涂抹增减。分析后调整范围，再预览实际切分结果。
      </p>
      <button
        disabled={
          disabled ||
          busy ||
          (faces.length !== 1 &&
            (partIds.length < 1 || (profile === 'cushion' && partIds.length !== 1)))
        }
        onClick={() => void diagnose()}
      >
        {busy ? '正在检查原网格…' : profile === 'cushion' ? '检查坐垫与原网格' : '检查部件与原网格'}
      </button>
      {error && <p role="alert">{error}</p>}
      {plan && bounds && (
        <>
          {plan.warnings?.map((message) => (
            <p role="alert" key={message}>
              {message}
            </p>
          ))}
          <p role="status">
            当前表面有 {plan.guide.boundary_edges.toLocaleString()}{' '}
            条开口边。会检查范围内未选中的原有表面；缺失的接合面会标为推测。
          </p>
          <div className="completion-bounds-grid">
            {['X 左右', 'Y 上下', 'Z 前后'].map((axis, i) => (
              <div key={axis}>
                <strong>{axis}</strong>
                {['起点', '终点'].map((side, j) => (
                  <label key={side}>
                    {side}（%）
                    <input
                      aria-label={`完整部件 ${axis} ${side}`}
                      type="number"
                      min="0"
                      max="100"
                      step=".1"
                      value={
                        Number.isFinite(bounds[j][i]) ? Number((bounds[j][i] * 100).toFixed(3)) : ''
                      }
                      disabled={disabled || busy}
                      onChange={(e) => {
                        const value = e.target.value === '' ? NaN : Number(e.target.value) / 100;
                        setBounds((old) =>
                          old?.map((row, k) => row.map((v, l) => (k === j && l === i ? value : v))),
                        );
                      }}
                    />
                  </label>
                ))}
              </div>
            ))}
          </div>
          {!valid && <p role="alert">请输入 0～100 的范围，每轴终点至少比起点大 0.5。</p>}
          <p>
            {profile === 'cushion'
              ? shape === 'box'
                ? '按绿色框切分，Y 起点控制底部、Y 终点控制顶部，X / Z 控制左右和前后。框内原表面会重新纳入，排除点不能阻止这一过程，请检查是否混入靠垫或扶手。'
                : '绿色框限制外部范围，框内还会沿选区轮廓收紧。若调整厚度后仍偏薄，可切换为按调整范围。'
              : '按连接高度建议分界；分离的支撑会保留为独立部件。'}
            请旋转检查侧面和底面；边界不合适时调整起止位置。这些是几何建议，不会自动识别真实装配结构。
          </p>
          <button
            disabled={disabled || busy || !valid || !name.trim()}
            onClick={() => void previewCut()}
          >
            {busy ? '正在计算切分预览…' : '预览实际切分'}
          </button>
          {preview && (
            <>
              {preview.operation.plan.warnings?.map((message) => (
                <p role="alert" key={message}>
                  {message}
                </p>
              ))}
              <CutPreview url={preview.preview_url} onReady={() => setPreviewReady(true)} />
              <p>
                拆出部件中，推测接合面的面积占比为{' '}
                {(preview.operation.part.inferred_area_fraction * 100).toFixed(1)}
                %。这个比例不是准确率。
              </p>
              <label>
                <input
                  type="checkbox"
                  aria-label="已检查坐垫厚度与相邻部件边界"
                  disabled={!previewReady || disabled || busy}
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                已检查侧面、底面、厚度及与相邻部件的边界
              </label>
              <button
                disabled={disabled || busy || !valid || !confirmed || !previewReady}
                onClick={() => void onComplete(bounds, profile, shape, preview.preview_id)}
              >
                生成完整部件候选
              </button>
            </>
          )}
          {!name.trim() && <p>请先填写部件名称，例如“坐垫”。</p>}
          <p>
            预览不会保存编辑版本；确认后保存同一份切分结果。会为两侧添加推测接合面，原模型保留。当前支持无贴图、无顶点颜色的静态网格。
          </p>
        </>
      )}
    </details>
  );
}

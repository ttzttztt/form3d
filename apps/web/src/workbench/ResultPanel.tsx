import { lazy, Suspense } from 'react';
import PartsPlanReview from './PartsPlanReview';

// three.js and the editor are the bulk of the bundle; load them after the page shell.
const Viewer = lazy(() => import('../Viewer'));
const AssetEditor = lazy(() => import('../AssetEditor'));
const loading3d = <div className="lazy-fallback">正在加载 3D 查看器…</div>;
import { api, statusLabels } from '../types';
import {
  ArrowDownToLine,
  Box,
  CheckCheck,
  ChevronRight,
  Layers3,
  LoaderCircle,
  MoreHorizontal,
  ShieldCheck,
  XCircle,
} from 'lucide-react';
import { routeNames } from './constants';
import type { Workbench } from './useWorkbench';

export default function ResultPanel({ wb }: { wb: Workbench }) {
  const {
    sample,
    jobs,
    job,
    image,
    target,
    name,
    route,
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
    template,
    confirmed,
    acting,
    setPanel,
    modelLoaded,
    setModelLoaded,
    comparison,
    setComparison,
    modelEditing,
    active,
    progress,
    previewUrl,
    viewingEdit,
    displayedMetrics,
    notify,
    action,
    materialDraft,
    setMaterialDraft,
  } = wb;
  return (
    <>
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
              <button className={!comparison ? 'active' : ''} onClick={() => setComparison(false)}>
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
            {job?.status === 'awaiting_plan_review' && <PartsPlanReview wb={wb} />}
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
              <Suspense fallback={loading3d}>
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
              </Suspense>
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
                  {job.parts_plan && (
                    <div className="input-preparation parts-plan">
                      <strong>原图部件规划 · {job.parts_plan.count} 个部件</strong>
                      <p>{job.parts_plan.parts.map((part) => part.name).join('、')}</p>
                      {job.parts_overlay_url && (
                        <a href={job.parts_overlay_url} target="_blank" rel="noreferrer">
                          查看部件识别叠加图
                        </a>
                      )}
                    </div>
                  )}
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
                  {job.status === 'awaiting_input' && job.attention_kind === 'local_input' && (
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
                          .catch(() => notify('在当前对话中发送：请处理待建模任务 ' + job.id));
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
            <Suspense fallback={loading3d}>
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
            </Suspense>
          )}
        </div>
      </section>
    </>
  );
}

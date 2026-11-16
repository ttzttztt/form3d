import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, LoaderCircle, X } from 'lucide-react';
import { post } from '../types';
import type { Job } from '../types';
import { partKindNames } from './constants';
import type { Workbench } from './useWorkbench';

type Row = { id: string; keep: boolean; kind: string };

/** Shown while a parts_first job waits for the user to confirm the automatic part plan. */
export default function PartsPlanReview({ wb }: { wb: Workbench }) {
  const { job, setJob, setJobs, notify, handleError, action, acting } = wb;
  const plan = job?.parts_plan;
  const [rows, setRows] = useState<Row[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setRows((plan?.parts ?? []).map((part) => ({ id: part.id, keep: true, kind: part.kind })));
  }, [job?.id, plan]);

  const original = useMemo(
    () => new Map((plan?.parts ?? []).map((part) => [part.id, part])),
    [plan],
  );
  const kept = rows.filter((row) => row.keep);
  const unresolved = kept.filter((row) => row.kind === 'unknown').length;
  const tooMany = kept.length > 16;

  if (!job || !plan) return null;

  async function confirm() {
    if (!job) return;
    setSaving(true);
    try {
      const updated = await post<Job>(`/api/jobs/${job.id}/parts-plan/confirm`, {
        remove: rows.filter((row) => !row.keep).map((row) => row.id),
        kinds: Object.fromEntries(
          rows
            .filter((row) => row.keep && row.kind !== original.get(row.id)?.kind)
            .map((row) => [row.id, row.kind]),
        ),
      });
      setJob(updated);
      setJobs((previous) => [updated, ...previous.filter((item) => item.id !== updated.id)]);
      notify('部件规划已确认，开始按部件生成');
    } catch (error) {
      handleError(error);
    } finally {
      setSaving(false);
    }
  }

  const update = (id: string, change: Partial<Row>) =>
    setRows((previous) => previous.map((row) => (row.id === id ? { ...row, ...change } : row)));

  return (
    <section className="parts-plan-review" aria-label="确认部件规划">
      <header>
        <strong>确认部件规划</strong>
        <span>
          识别出 {plan.count} 个部件。可以修正类别，或取消勾选不需要单独生成的部件
          （它会并入相邻部件）。确认后才开始生成。
        </span>
      </header>
      <div className="parts-plan-body">
        {job.parts_overlay_url && (
          <a
            href={job.parts_overlay_url}
            target="_blank"
            rel="noreferrer"
            className="parts-plan-image"
          >
            <img src={job.parts_overlay_url} alt="部件识别叠加图，编号与右侧列表对应" />
          </a>
        )}
        <ol className="parts-plan-list">
          {rows.map((row) => {
            const part = original.get(row.id);
            return (
              <li key={row.id} className={row.keep ? '' : 'removed'}>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={row.keep}
                    onChange={(event) => update(row.id, { keep: event.target.checked })}
                    aria-label={`保留部件 ${part?.index ?? ''}`}
                  />
                  <span className="parts-plan-index">{part?.index ?? '—'}</span>
                </label>
                <select
                  value={row.kind}
                  disabled={!row.keep}
                  onChange={(event) => update(row.id, { kind: event.target.value })}
                  aria-label={`部件 ${part?.index ?? ''} 的类别`}
                >
                  {row.kind === 'unknown' && <option value="unknown">未确定（请选择）</option>}
                  {plan.kind_options.map((kind) => (
                    <option key={kind} value={kind}>
                      {partKindNames[kind] ?? kind}
                    </option>
                  ))}
                </select>
              </li>
            );
          })}
        </ol>
      </div>
      {(unresolved > 0 || tooMany || kept.length === 0 || plan.problem) && (
        <p className="parts-plan-problem" role="status">
          {kept.length === 0
            ? '至少保留一个部件'
            : unresolved > 0
              ? `还有 ${unresolved} 个部件类别未确定`
              : tooMany
                ? `最多 16 个部件，当前 ${kept.length} 个`
                : plan.problem}
        </p>
      )}
      <footer>
        <button
          className="button secondary"
          disabled={acting || saving}
          onClick={() => void action('cancel')}
        >
          <X size={15} /> 取消任务
        </button>
        <button
          className="button primary"
          disabled={saving || unresolved > 0 || tooMany || kept.length === 0}
          onClick={() => void confirm()}
        >
          {saving ? <LoaderCircle size={15} className="spin" /> : <ArrowRight size={15} />}
          确认并开始生成
        </button>
      </footer>
    </section>
  );
}

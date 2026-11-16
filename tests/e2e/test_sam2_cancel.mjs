// Cancel a real segmentation worker. This test does not evaluate mask quality.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';

const base = process.env.WORKBENCH_URL || 'http://127.0.0.1:8000';
async function call(url, options) {
  const response = await fetch(base + url, options);
  assert.ok(response.ok, await response.clone().text());
  return response.json();
}
const baseline = await call('/api/jobs/74d7a1685b704d529354005a2c8608fb');
const request = { ...baseline.request, name: 'SAM 2 真实分割取消验收', local_segmentation: 'sam2' };
let job = await call('/api/jobs', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(request),
});
let observed = false;
for (let i = 0; i < 100; i++) {
  job = await call('/api/jobs/' + job.id);
  if (job.stage === 'segment') {
    observed = true;
    break;
  }
  assert.ok(['queued', 'running'].includes(job.status));
  await new Promise((resolve) => setTimeout(resolve, 250));
}
assert.ok(observed, 'Actual SAM stage was not observed');
await new Promise((resolve) => setTimeout(resolve, 1500));
await call('/api/jobs/' + job.id + '/cancel', { method: 'POST' });
await new Promise((resolve) => setTimeout(resolve, 5000));
job = await call('/api/jobs/' + job.id);
assert.equal(job.status, 'cancelled');
assert.equal(
  await fetch(base + '/api/jobs/' + job.id + '/files/model.glb').then((r) => r.status),
  409,
);
assert.ok(!job.events.some((e) => e.stage === 'review'));
const result = {
  status: 'PASS',
  scope: 'real segmentation cancellation and blocked GLB publication',
  job_id: job.id,
  observed_stage: 'segment',
  final_status: job.status,
  events: job.events,
  process_cleanup_check: 'See cancellation_process_check.json; not inferred from task status',
};
await fs.writeFile(
  '.data/checks/test_sam2_cancel/cancellation.json',
  JSON.stringify(result, null, 2),
);
console.log(JSON.stringify(result));

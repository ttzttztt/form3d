import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
const folder = path.resolve('experiments/asset_upgrade_20261112'),
  base = 'http://127.0.0.1:8000';
const cases = JSON.parse(await fs.readFile(path.join(folder, 'real_edits.json'), 'utf8'));
const browser = await chromium.launch({
  executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-sandbox'],
});
const result = { errors: [], checks: [] };
try {
  const page = await browser.newPage({ viewport: { width: 1500, height: 1200 } });
  page.setDefaultTimeout(60000);
  page.on('pageerror', (error) => result.errors.push(error.message));
  await page.addInitScript(() => {
    window.__draws = 0;
    for (const name of ['drawElements', 'drawArrays']) {
      const original = WebGL2RenderingContext.prototype[name];
      WebGL2RenderingContext.prototype[name] = function (...args) {
        window.__draws++;
        return original.apply(this, args);
      };
    }
  });
  const job = cases.find((c) => c.case === 'table').test_job;
  await page.goto(base + '/?job=' + job, { waitUntil: 'networkidle' });
  await page.locator('.viewer-overlay').waitFor({ state: 'hidden' });
  const editor = page.getByRole('region', { name: '部件与材质编辑' }),
    view = page.getByTestId('model-viewer').first();
  await view.scrollIntoViewIfNeeded();
  await page.waitForTimeout(1200);
  const a = await page.evaluate(() => window.__draws);
  await page.waitForTimeout(1000);
  const b = await page.evaluate(() => window.__draws);
  assert.ok(a > 0);
  assert.equal(a, b);
  result.checks.push({ name: 'idle_draw_calls_stopped', draws_before: a, draws_after: b });
  const rect = await view.locator('canvas').boundingBox();
  await page.mouse.move(rect.x + rect.width * 0.5, rect.y + rect.height * 0.5);
  await page.mouse.down();
  await page.mouse.move(rect.x + rect.width * 0.65, rect.y + rect.height * 0.6, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(500);
  assert.ok((await page.evaluate(() => window.__draws)) > b);
  result.checks.push({ name: 'orbit_redraws_after_idle', pass: true });
  await view.getByRole('button', { name: '拟合参考视角', exact: true }).click();
  await editor.getByLabel('查看编辑版本', { exact: true }).selectOption('original');
  await page.locator('.viewer-overlay').waitFor({ state: 'hidden' });
  await view.getByRole('button', { name: '拟合参考视角', exact: true }).waitFor();
  assert.equal(
    await view.getByRole('button', { name: '拟合参考视角', exact: true }).isEnabled(),
    true,
  );
  result.checks.push({ name: 'camera_fit_cancel_on_version_change', pass: true });
  await editor.getByText('补充视图与版本管理', { exact: true }).click();
  const before = await (await page.request.get(base + `/api/jobs/${job}/asset`)).json();
  const reference = before.reference_views.find((v) => v.role === 'reference_only');
  assert.ok(reference);
  await view.getByRole('button', { name: '拟合参考视角', exact: true }).click();
  await editor
    .locator('.reference-thumbnails button')
    .filter({ has: page.locator(`img[src="${reference.url}"]`) })
    .click();
  await view.getByRole('status').filter({ hasText: '参考图已切换' }).waitFor();
  assert.ok(await view.getByRole('button', { name: '拟合参考视角', exact: true }).isEnabled());
  result.checks.push({ name: 'reference_change_cancels_stale_fit', pass: true });
  await editor.getByRole('button', { name: '移除补充视图 ' + reference.id, exact: true }).click();
  await editor.getByRole('status').filter({ hasText: '补充视图已移除' }).waitFor();
  assert.equal(await editor.getByLabel('查看编辑版本', { exact: true }).inputValue(), 'original');
  const after = await (await page.request.get(base + `/api/jobs/${job}/asset`)).json();
  assert.equal(after.reference_views.length, before.reference_views.length - 1);
  assert.equal(after.version, before.version);
  result.checks.push({
    name: 'remove_reference_preserves_history_preview_and_model_version',
    pass: true,
  });
  const selected = after.parts.find((p) => p.has_texture);
  const response = await page.request.post(base + `/api/jobs/${job}/asset/versions`, {
    data: {
      operation: 'decimate',
      base_version: after.version,
      part_ids: [selected.id],
      lod_ratio: 0.5,
    },
  });
  assert.equal(response.status(), 409);
  const error = await response.json();
  assert.ok(error.detail.includes('UV'));
  assert.ok(error.detail.includes('纹理'));
  result.checks.push({
    name: 'textured_lod_guard_readable_error',
    status: response.status(),
    detail: error.detail,
  });
  assert.equal(
    (await (await page.request.get(base + `/api/jobs/${job}/asset`)).json()).version,
    after.version,
  );
  await view.scrollIntoViewIfNeeded();
  await view.screenshot({ path: path.join(folder, 'review_smoke_viewer.png') });
  assert.deepEqual(result.errors, []);
} finally {
  await fs.writeFile(path.join(folder, 'review_smoke.json'), JSON.stringify(result, null, 2));
  await browser.close();
}
console.log(JSON.stringify(result, null, 2));

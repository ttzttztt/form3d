import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
const folder = path.resolve('experiments/furniture_workbench_20261112'),
  base = 'http://127.0.0.1:8000';
const { job } = JSON.parse(await fs.readFile(path.join(folder, 'ui_job.json'), 'utf8'));
const browser = await chromium.launch({
  executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-sandbox'],
});
const result = { checks: [], errors: [] };
try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1080 } });
  page.setDefaultTimeout(60000);
  page.on('pageerror', (e) => result.errors.push(e.message));
  await page.goto(base + '/?job=' + job, { waitUntil: 'networkidle' });
  await page.locator('.viewer-overlay').waitFor({ state: 'hidden' });
  const editor = page.getByRole('region', { name: '部件与材质编辑' }),
    viewer = page.getByTestId('model-viewer').first(),
    root = base + `/api/jobs/${job}/asset`;
  const before = await (await page.request.get(root)).json();
  let release, enteredResolve, handledResolve;
  const entered = new Promise((r) => (enteredResolve = r)),
    handled = new Promise((r) => (handledResolve = r));
  await page.route('**/api/images', async (route) => {
    const gate = new Promise((r) => (release = r));
    enteredResolve();
    await gate;
    await route.continue();
    handledResolve();
  });
  await editor.getByText('上传纹理图片（可选）', { exact: true }).click();
  await editor
    .getByLabel('色彩贴图', { exact: true })
    .setInputFiles(path.resolve('experiments/asset_upgrade_20261112/base_color_image.png'));
  await entered;
  assert.equal(await editor.getByLabel('编辑范围', { exact: true }).isDisabled(), true);
  assert.equal(
    await viewer.getByRole('button', { name: '点选部件', exact: true }).isDisabled(),
    true,
  );
  assert.equal(await editor.getByLabel('材质颜色', { exact: true }).isDisabled(), true);
  result.checks.push({ name: 'upload_locks_scope_pointer_and_material', pass: true });
  release();
  await handled;
  await page.unroute('**/api/images');
  await page.waitForFunction(() =>
    document.querySelector('.draft-status')?.textContent.includes('正在预览，尚未保存'),
  );
  assert.equal(
    (await (await page.request.get(root)).json()).versions.length,
    before.versions.length,
  );
  await editor.getByRole('button', { name: '取消预览', exact: true }).click();
  // Invalid UV input cannot publish a version or leave a misleading live draft.
  await editor.getByLabel('纹理重复', { exact: true }).fill('0');
  assert.equal(
    await editor.getByRole('button', { name: '保存当前材质效果', exact: true }).isDisabled(),
    true,
  );
  await editor.getByRole('button', { name: '取消预览', exact: true }).click();
  result.checks.push({ name: 'invalid_uv_blocks_save', pass: true });
  // Existing UV geometry must not enter the untextured smoothing path.
  const rejected = await page.request.post(root + '/versions', {
    data: { operation: 'repair_geometry', base_version: before.version, repair_strength: 'gentle' },
  });
  assert.equal(rejected.status(), 409);
  const after = await (await page.request.get(root)).json();
  assert.equal(after.version, before.version);
  assert.equal(after.versions.length, before.versions.length);
  result.checks.push({
    name: 'textured_gentle_repair_rejected_without_version',
    status: rejected.status(),
    message: await rejected.json(),
  });
  assert.deepEqual(result.errors, []);
} catch (e) {
  result.failure = e.stack;
  throw e;
} finally {
  await fs.writeFile(path.join(folder, 'browser_guards.json'), JSON.stringify(result, null, 2));
  await browser.close();
}
console.log(JSON.stringify(result, null, 2));

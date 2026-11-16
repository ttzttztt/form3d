import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
const folder = path.resolve('experiments/furniture_workbench_20261112'),
  base = 'http://127.0.0.1:8000';
const cases = JSON.parse(await fs.readFile(path.join(folder, 'real_runs.json'), 'utf8'));
const browser = await chromium.launch({
  executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-sandbox'],
});
const results = { errors: [], cases: [] };
try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1080 } });
  page.setDefaultTimeout(60000);
  page.on('pageerror', (e) => results.errors.push(e.stack || e.message));
  for (const c of cases) {
    const root = base + `/api/jobs/${c.test_job}/asset`,
      current = await (await page.request.get(root)).json();
    const response = await page.request.post(root + '/versions', {
      data: {
        operation: 'restore_version',
        base_version: current.version,
        source_version: c.auto_version,
      },
    });
    assert.equal(response.status(), 201);
    const restored = await response.json();
    await page.goto(base + '/?job=' + c.test_job, { waitUntil: 'networkidle' });
    await page.locator('.viewer-overlay').waitFor({ state: 'hidden' });
    const editor = page.getByRole('region', { name: '部件与材质编辑' }),
      canvas = page.getByTestId('model-viewer').first().locator('canvas');
    const group = restored.groups[0];
    await editor.getByRole('button', { name: '选择部件 ' + group.name, exact: true }).click();
    await page.waitForTimeout(400);
    const original = await canvas.evaluate((c) => c.toDataURL());
    await editor.getByLabel('材质颜色', { exact: true }).evaluate((input) => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(
        input,
        '#ea3559',
      );
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await page.waitForTimeout(500);
    await canvas.screenshot({ path: path.join(folder, c.case + '_browser_preview.png') });
    const preview = await canvas.evaluate((c) => c.toDataURL());
    assert.notEqual(preview, original, c.case);
    await editor.getByRole('button', { name: '取消预览', exact: true }).click();
    await page.waitForTimeout(500);
    assert.equal(await canvas.evaluate((c) => c.toDataURL()), original, c.case);
    assert.equal(
      (await (await page.request.get(root)).json()).versions.length,
      restored.versions.length,
    );
    assert.equal(
      await editor.getByLabel('编辑范围', { exact: true }).inputValue(),
      'g:' + group.id,
    );
    results.cases.push({
      case: c.case,
      job: c.test_job,
      version: restored.version,
      groups: restored.groups.length,
      preview_visible: true,
      cancel_pixel_exact: true,
      no_draft_versions: true,
    });
    await fs.writeFile(
      path.join(folder, 'browser_furniture_matrix.json'),
      JSON.stringify(results, null, 2),
    );
    console.log(c.case + ' preview/cancel passed');
  }
  assert.deepEqual(results.errors, []);
} catch (e) {
  results.failure = e.stack;
  throw e;
} finally {
  await fs.writeFile(
    path.join(folder, 'browser_furniture_matrix.json'),
    JSON.stringify(results, null, 2),
  );
  await browser.close();
}

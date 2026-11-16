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
const results = { errors: [], checks: [], fits: [] };
try {
  const page = await browser.newPage({
    viewport: { width: 1500, height: 1200 },
    acceptDownloads: true,
  });
  page.setDefaultTimeout(120000);
  page.on('pageerror', (error) => results.errors.push(error.message));
  const job = cases.find((c) => c.case === 'table').test_job;
  const current = await (await page.request.get(base + `/api/jobs/${job}/asset`)).json();
  const reset = await page.request.post(base + `/api/jobs/${job}/asset/versions`, {
    data: { operation: 'restore_original', base_version: current.version },
  });
  assert.equal(reset.status(), 201);
  await page.goto(base + '/?job=' + job, { waitUntil: 'networkidle' });
  const editor = page.getByRole('region', { name: '部件与材质编辑' }),
    viewer = page.getByTestId('model-viewer').first();
  await editor.getByLabel('编辑范围', { exact: true }).waitFor();
  await page.locator('.viewer-overlay').waitFor({ state: 'hidden' });
  await viewer.scrollIntoViewIfNeeded();
  const tool = viewer.getByLabel('选面工具');
  await tool.selectOption('box');
  const canvas = viewer.locator('canvas').first(),
    rect = await canvas.boundingBox();
  assert.ok(rect.width > 100 && rect.height > 100);
  const gesture = async (x1, y1, x2, y2) => {
    await page.mouse.move(rect.x + rect.width * x1, rect.y + rect.height * y1);
    await page.mouse.down();
    await page.mouse.move(rect.x + rect.width * x2, rect.y + rect.height * y2, { steps: 12 });
    await page.mouse.up();
  };
  const count = async () => {
    const text = await viewer.locator('.face-tools').textContent();
    return Number(text.match(/([\d,]+) 面 · 按面中心/)[1].replaceAll(',', ''));
  };
  await gesture(0.15, 0.1, 0.55, 0.9);
  const selected = await count();
  assert.ok(selected > 0);
  results.checks.push({ name: 'box_add', selected });
  await viewer.getByRole('button', { name: '撤销选面', exact: true }).click();
  assert.equal(await count(), 0);
  await viewer.getByRole('button', { name: '重做选面', exact: true }).click();
  assert.equal(await count(), selected);
  await viewer.getByRole('button', { name: '加选', exact: true }).click();
  await gesture(0.15, 0.1, 0.4, 0.9);
  assert.ok((await count()) < selected);
  results.checks.push({ name: 'subtract_and_undo_redo', pass: true });
  await viewer.getByRole('button', { name: '减选', exact: true }).click();
  await tool.selectOption('brush');
  await gesture(0.45, 0.4, 0.6, 0.5);
  assert.ok((await count()) > 0);
  results.checks.push({ name: 'brush', selected: await count() });
  await viewer.screenshot({ path: path.join(folder, 'face_selection.png') });
  async function action(name) {
    const pending = page.waitForResponse(
      (r) => r.url().endsWith('/asset/versions') && r.request().method() === 'POST',
    );
    await editor.getByRole('button', { name, exact: true }).click();
    const response = await pending,
      body = await response.json();
    assert.equal(response.status(), 201, JSON.stringify(body));
    await page.locator('.viewer-overlay').waitFor({ state: 'hidden' });
    return body;
  }
  const split = await action(new RegExp('将所选 .* 面保存为部件'));
  assert.equal(split.parts.length, 2);
  results.checks.push({ name: 'face_group', parts: split.parts.length, version: split.version });
  const ids = split.parts.map((p) => p.id);
  await editor.getByLabel('编辑范围', { exact: true }).selectOption(ids[1]);
  await editor.getByLabel('部件名称').fill('浏览器局部测试');
  const renamed = await action('保存部件名称');
  assert.deepEqual(
    renamed.parts.map((p) => p.id),
    ids,
  );
  assert.equal(renamed.parts[1].name, '浏览器局部测试');
  await editor.getByLabel('编辑范围', { exact: true }).selectOption(ids[1]);
  await editor.getByText('真实 PBR 贴图', { exact: true }).click();
  for (const [label, file] of [
    ['色彩贴图', 'base_color_image.png'],
    ['法线贴图', 'normal_image.png'],
    ['粗糙度贴图', 'roughness_image.png'],
  ]) {
    await editor.getByLabel(label, { exact: true }).setInputFiles(path.join(folder, file));
    await editor
      .getByRole('button', { name: '保存换材质版本', exact: true })
      .waitFor({ state: 'visible' });
    await page.waitForFunction(() => !document.querySelector('[aria-label="色彩贴图"]').disabled);
  }
  await editor.getByLabel('纹理重复', { exact: true }).fill('2');
  await editor.getByLabel('纹理旋转', { exact: true }).fill('45');
  await editor.getByLabel('材质颜色', { exact: true }).evaluate((input) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, '#ffffff');
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
  const textured = await action('保存换材质版本');
  assert.equal(textured.parts[1].has_texture, true);
  assert.deepEqual(
    textured.parts.map((p) => p.id),
    ids,
  );
  results.checks.push({
    name: 'three_map_export',
    validation: textured.manifest.validation,
    version: textured.version,
    job,
  });
  await fs.writeFile(
    path.join(folder, 'browser_textured_table.glb'),
    await (await page.request.get(base + textured.model_url)).body(),
  );
  await viewer.scrollIntoViewIfNeeded();
  await viewer.screenshot({ path: path.join(folder, 'browser_textured_table.png') });
  const invalid = await page.request.post(base + `/api/jobs/${job}/asset/versions`, {
    data: {
      base_version: textured.version,
      operation: 'face_group',
      face_selection: [{ part_id: ids[0], faces: [-1] }],
    },
  });
  assert.equal(invalid.status(), 422);
  await editor.getByText('补充视图与版本管理', { exact: true }).click();
  await editor
    .getByLabel('版本备注', { exact: true })
    .fill('浏览器完成三贴图导出；未验收商品相似度');
  await editor.getByRole('button', { name: '归档当前版本', exact: true }).click();
  await editor.getByRole('status').filter({ hasText: '版本备注与归档状态' }).waitFor();
  await editor.getByRole('button', { name: '比较版本', exact: true }).click();
  await editor.locator('.version-comparison canvas').first().waitFor();
  await editor.getByRole('button', { name: '关闭版本对照', exact: true }).click();
  results.checks.push({ name: 'archive_note_compare_and_invalid_face', pass: true });
  // Real image camera-fit trials. The reported IoU is measured, not product accuracy.
  for (const caseName of ['table', 'vase']) {
    const item = cases.find((c) => c.case === caseName);
    await page.goto(base + '/?job=' + item.test_job, { waitUntil: 'networkidle' });
    await page.locator('.viewer-overlay').waitFor({ state: 'hidden' });
    const view = page.getByTestId('model-viewer').first();
    await view.scrollIntoViewIfNeeded();
    const pending = page.waitForEvent('download');
    await view.getByRole('button', { name: '拟合参考视角', exact: true }).click();
    const download = await pending;
    const file = path.join(folder, caseName + '_reference_fit.json');
    await download.saveAs(file);
    const fit = JSON.parse(await fs.readFile(file, 'utf8'));
    assert.ok(fit.silhouette_iou >= fit.initial_silhouette_iou && fit.silhouette_iou <= 1);
    assert.ok(fit.evaluations >= 99);
    results.fits.push({ case: caseName, ...fit });
    await view.screenshot({ path: path.join(folder, caseName + '_reference_overlay.png') });
  }
  // Real white-background and scene photos of the same cabinet; reference only.
  const cabinet = cases.find((c) => c.case === 'cabinet');
  await page.goto(base + '/?job=' + cabinet.test_job, { waitUntil: 'networkidle' });
  await page.locator('.viewer-overlay').waitFor({ state: 'hidden' });
  await editor.getByText('补充视图与版本管理', { exact: true }).click();
  await editor
    .getByLabel('补充参考图', { exact: true })
    .setInputFiles(path.resolve('images/0304_Forme Cabinet.jpg'));
  await editor.getByRole('status').filter({ hasText: '补充视图已保存' }).waitFor();
  const reference = await (
    await page.request.get(base + `/api/jobs/${cabinet.test_job}/asset`)
  ).json();
  assert.ok(reference.reference_views.some((v) => v.role === 'reference_only'));
  results.checks.push({
    name: 'same_product_scene_reference',
    reference_views: reference.reference_views,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByTestId('model-viewer').first().scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(folder, 'mobile_editor.png'), fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  results.checks.push({ name: 'mobile_no_horizontal_overflow', pass: true });
  assert.deepEqual(results.errors, []);
} finally {
  await fs.writeFile(path.join(folder, 'browser_checks.json'), JSON.stringify(results, null, 2));
  await browser.close();
}
console.log(JSON.stringify(results, null, 2));

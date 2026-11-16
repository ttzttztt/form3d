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
const results = { job, errors: [], checks: [] };
try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1080 } });
  page.setDefaultTimeout(90000);
  page.on('pageerror', (e) => results.errors.push(e.stack || e.message));
  const root = base + `/api/jobs/${job}/asset`,
    catalog = async () => await (await page.request.get(root)).json();
  let initial = await catalog();
  if (initial.version !== 'original') {
    const r = await page.request.post(root + '/versions', {
      data: { operation: 'restore_original', base_version: initial.version },
    });
    assert.equal(r.status(), 201);
  }
  await page.goto(base + '/?job=' + job, { waitUntil: 'networkidle' });
  const editor = page.getByRole('region', { name: '部件与材质编辑' }),
    view = page.getByTestId('model-viewer').first(),
    canvas = view.locator('canvas');
  await page.locator('.viewer-overlay').waitFor({ state: 'hidden' });
  await editor.getByLabel('编辑范围', { exact: true }).waitFor();
  const ready = async () => {
    await page.locator('.viewer-overlay').waitFor({ state: 'hidden' });
    await page.waitForTimeout(700);
  };
  const snap = async (name) => {
    await ready();
    await canvas.screenshot({ path: path.join(folder, name + '.png') });
    return await canvas.evaluate((c) => c.toDataURL());
  };
  async function color(value) {
    await editor.getByLabel('材质颜色', { exact: true }).evaluate((input, value) => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }, value);
    await ready();
  }
  async function action(name) {
    const pending = page.waitForResponse(
      (r) => r.url().endsWith('/asset/versions') && r.request().method() === 'POST',
    );
    await editor.getByRole('button', { name, exact: true }).click();
    const r = await pending,
      body = await r.json();
    assert.equal(r.status(), 201, JSON.stringify(body));
    await ready();
    return body;
  }
  const before = await catalog(),
    baseline = await snap('ui_original');
  await color('#e62e36');
  const red = await snap('ui_live_red');
  assert.notEqual(red, baseline);
  await editor.getByRole('button', { name: '撤销材质预览', exact: true }).click();
  assert.equal(await snap('ui_undo'), baseline);
  await editor.getByRole('button', { name: '重做材质预览', exact: true }).click();
  assert.equal(await snap('ui_redo'), red);
  await editor.getByRole('button', { name: '取消预览', exact: true }).click();
  assert.equal(await snap('ui_cancel'), baseline);
  assert.equal((await catalog()).versions.length, before.versions.length);
  results.checks.push({ name: 'live_color_undo_redo_cancel_no_versions', pass: true });
  await editor.getByRole('button', { name: '拆分部件', exact: true }).click();
  const grouped = await action('生成完整分组候选');
  assert.equal(grouped.groups.length, 2);
  const top = grouped.groups.find((g) => g.name.includes('桌面')),
    bottom = grouped.groups.find((g) => g.name.includes('底座'));
  await editor.getByRole('button', { name: '选择部件 ' + top.name, exact: true }).click();
  assert.equal(await editor.getByLabel('编辑范围', { exact: true }).inputValue(), 'g:' + top.id);
  await view.getByRole('button', { name: '点选部件', exact: true }).click();
  let rect = await canvas.boundingBox();
  await canvas.click({ position: { x: rect.width * 0.5, y: rect.height * 0.31 } });
  assert.equal(await editor.getByLabel('编辑范围', { exact: true }).inputValue(), 'g:' + top.id);
  results.checks.push({ name: 'list_and_canvas_pick_same_complete_top', triangles: top.triangles });
  await color('#39a9de');
  await snap('ui_top_preview');
  const saved = await action('保存当前材质效果');
  const changed = saved.parts
    .filter(
      (p) =>
        JSON.stringify(p.base_color_factor) !==
        JSON.stringify(grouped.parts.find((g) => g.id === p.id).base_color_factor),
    )
    .map((p) => p.id);
  assert.deepEqual(changed, top.part_ids);
  assert.equal(await editor.getByLabel('编辑范围', { exact: true }).inputValue(), 'g:' + top.id);
  await snap('ui_top_saved');
  results.checks.push({
    name: 'save_only_selected_complete_part',
    version: saved.version,
    changed,
  });
  await editor.getByText('上传纹理图片（可选）', { exact: true }).click();
  for (const [label, file] of [
    ['色彩贴图', 'base_color_image.png'],
    ['法线贴图', 'normal_image_nonflat.png'],
    ['粗糙度贴图', 'roughness_image.png'],
  ]) {
    await editor
      .getByLabel(label, { exact: true })
      .setInputFiles(
        label === '法线贴图'
          ? path.join(folder, file)
          : path.resolve('experiments/asset_upgrade_20261112', file),
      );
    await page.waitForFunction(
      () => !document.querySelector('.draft-status')?.textContent.includes('正在载入'),
    );
    await ready();
  }
  await color('#ffffff');
  await editor.getByLabel('纹理重复', { exact: true }).fill('2');
  await editor.getByLabel('纹理旋转', { exact: true }).fill('37');
  await snap('ui_texture_preview');
  assert.ok(
    await editor.getByRole('button', { name: '保存当前材质效果', exact: true }).isEnabled(),
  );
  const textured = await action('保存当前材质效果');
  await snap('ui_texture_saved');
  results.checks.push({
    name: 'three_pbr_maps_live_preview_and_explicit_save',
    version: textured.version,
  });
  await editor.getByRole('button', { name: '拆分部件', exact: true }).click();
  await editor.getByLabel('合并选择 ' + top.name, { exact: true }).check();
  await editor.getByLabel('合并选择 ' + bottom.name, { exact: true }).check();
  await editor.getByLabel('部件名称', { exact: true }).fill('浏览器合并检查');
  const merged = await action('合并已选的 2 个部件');
  assert.equal(merged.groups.length, 1);
  assert.equal(merged.groups[0].material_count, 2);
  assert.deepEqual(
    merged.parts.map((p) => p.material_signature),
    textured.parts.map((p) => p.material_signature),
  );
  await editor.getByRole('button', { name: '换材质', exact: true }).click();
  const mixed = await snap('ui_multimaterial_baseline');
  await color('#f1b52a');
  assert.notEqual(await snap('ui_merged_preview'), mixed);
  await editor.getByRole('button', { name: '取消预览', exact: true }).click();
  assert.equal(await snap('ui_merged_cancel'), mixed);
  results.checks.push({ name: 'logical_merge_and_cancel_restore_different_materials', pass: true });
  await view.getByRole('button', { name: '涂抹修正', exact: true }).click();
  await canvas.scrollIntoViewIfNeeded();
  rect = await canvas.boundingBox();
  await page.mouse.move(rect.x + rect.width * 0.47, rect.y + rect.height * 0.29);
  await page.mouse.down();
  await page.mouse.move(rect.x + rect.width * 0.54, rect.y + rect.height * 0.32, { steps: 8 });
  await page.mouse.up();
  const count = Number(await view.locator('.face-tools').getAttribute('data-selected-faces'));
  assert.ok(count > 0);
  await editor.getByLabel('部件名称', { exact: true }).fill('浏览器涂抹区域');
  const extracted = await action('保存选区为新部件');
  assert.equal(extracted.groups.length, 2);
  assert.equal(extracted.metrics.triangles, grouped.metrics.triangles);
  results.checks.push({
    name: 'brush_extract_real_faces',
    faces: count,
    version: extracted.version,
  });
  // A second brush gesture moves actual faces into an existing logical group.
  await canvas.scrollIntoViewIfNeeded();
  rect = await canvas.boundingBox();
  await page.mouse.move(rect.x + rect.width * 0.48, rect.y + rect.height * 0.34);
  await page.mouse.down();
  await page.mouse.move(rect.x + rect.width * 0.54, rect.y + rect.height * 0.36, { steps: 8 });
  await page.mouse.up();
  assert.ok(Number(await view.locator('.face-tools').getAttribute('data-selected-faces')) > 0);
  const receiver = extracted.groups.find((g) => g.name === '浏览器涂抹区域');
  await editor.getByLabel('选区接收部件', { exact: true }).selectOption(receiver.part_ids[0]);
  const moved = await action('移入接收部件');
  assert.equal(moved.metrics.triangles, grouped.metrics.triangles);
  results.checks.push({ name: 'brush_move_into_existing_group', version: moved.version });
  await editor.getByRole('button', { name: '更多操作', exact: true }).click();
  await editor.getByText('检查与保守修复模型', { exact: true }).click();
  await editor.getByRole('button', { name: '检查当前模型', exact: true }).click();
  await editor.locator('.quality-facts').waitFor();
  results.checks.push({
    name: 'quality_inspection_in_browser',
    text: await editor.locator('.quality-facts').innerText(),
  });
  await page.screenshot({ path: path.join(folder, 'ui_desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(folder, 'ui_mobile.png'), fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  results.checks.push({ name: 'mobile_no_horizontal_overflow', pass: true });
  assert.deepEqual(results.errors, []);
} catch (error) {
  results.failure = error.stack;
  throw error;
} finally {
  await fs.writeFile(path.join(folder, 'browser_checks.json'), JSON.stringify(results, null, 2));
  await browser.close();
}
console.log(JSON.stringify(results, null, 2));

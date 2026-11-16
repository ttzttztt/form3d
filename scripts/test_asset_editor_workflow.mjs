// Actual product GLB edits through the browser/API; no generated fixture substituted.
import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
const folder = path.resolve('experiments/asset_editor_20261111');
await fs.mkdir(folder, { recursive: true });
const base = 'http://127.0.0.1:8000',
  job = '6eab9c5a4a9545febbfc0835fd89ee4e';
const browser = await chromium.launch({
  executablePath:
    process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-sandbox'],
});
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  page.setDefaultTimeout(60000);
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const original = await (
    await page.request.get(base + '/api/jobs/' + job + '/files/model.glb')
  ).body();
  await page.goto(base + '/?job=' + job, { waitUntil: 'networkidle' });
  const editor = page.getByRole('region', { name: '部件与材质编辑' });
  await editor.getByLabel('编辑范围', { exact: true }).waitFor();
  await page.locator('.viewer-overlay').waitFor({ state: 'hidden' });
  async function hex(color) {
    await editor.getByLabel('材质颜色').evaluate((input, value) => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }, color);
  }
  async function action(name) {
    const pending = page.waitForResponse(
      (response) =>
        response.url().endsWith('/asset/versions') && response.request().method() === 'POST',
    );
    await editor.getByRole('button', { name, exact: true }).click();
    const response = await pending;
    const value = await response.json();
    assert.equal(response.status(), 201, JSON.stringify(value));
    await page.waitForFunction(
      (url) => document.querySelector('.asset-version-actions a')?.getAttribute('href') === url,
      value.model_url,
    );
    await page.locator('.viewer-overlay').waitFor({ state: 'hidden' });
    return value;
  }
  await editor.getByLabel('编辑范围', { exact: true }).selectOption('all');
  await hex('#34785a');
  const whole = await action('保存换材质版本');
  assert.ok(whole.parts.every((part) => part.base_color_factor[1] > part.base_color_factor[0]));
  await page
    .locator('.viewer')
    .screenshot({ path: path.join(folder, 'global_material_viewer.png') });
  const chosen = whole.parts[0].id;
  await editor.getByLabel('编辑范围', { exact: true }).selectOption(chosen);
  await hex('#b36a35');
  const partial = await action('保存换材质版本');
  assert.equal(partial.parts.length, 2);
  assert.notDeepEqual(partial.parts[0].base_color_factor, partial.parts[1].base_color_factor);
  await page.locator('.viewer').screenshot({ path: path.join(folder, 'part_material_viewer.png') });
  const partialBytes = await (await page.request.get(base + partial.model_url)).body();
  const restore = await action('恢复原始模型为新版本');
  assert.deepEqual(await (await page.request.get(base + restore.model_url)).body(), original);
  await editor.locator('details').evaluate((element) => (element.open = true));
  const componentResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith('/asset/versions') && response.request().method() === 'POST',
  );
  await editor.getByRole('button', { name: '按连通片分组', exact: true }).click();
  const component = await componentResponse;
  const componentData = await component.json();
  assert.ok([201, 409].includes(component.status()));
  if (component.status() === 201)
    await page.waitForFunction(
      (url) => document.querySelector('.asset-version-actions a')?.getAttribute('href') === url,
      componentData.model_url,
    );
  else await editor.getByRole('alert').waitFor();
  await editor.getByLabel('查看编辑版本').selectOption(partial.version);
  await editor.getByRole('button', { name: '恢复所看版本为新版本', exact: true }).waitFor();
  const final = await action('恢复所看版本为新版本');
  assert.deepEqual(await (await page.request.get(base + final.model_url)).body(), partialBytes);
  assert.deepEqual(
    await (await page.request.get(base + '/api/jobs/' + job + '/files/model.glb')).body(),
    original,
  );
  await page.reload({ waitUntil: 'networkidle' });
  await editor.getByLabel('查看编辑版本').waitFor();
  await page.waitForFunction(
    (version) => document.querySelector('select[aria-label="查看编辑版本"]')?.value === version,
    final.version,
  );
  await page.locator('.viewer-overlay').waitFor({ state: 'hidden' });
  assert.equal(
    await page.getByRole('link', { name: /下载编辑模型/ }).getAttribute('href'),
    final.model_url,
  );
  await page.screenshot({ path: path.join(folder, 'editor_desktop.png'), fullPage: true });
  await page.locator('.viewer').screenshot({ path: path.join(folder, 'final_edited_viewer.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
    false,
    'Editor mobile overflow',
  );
  await page.screenshot({ path: path.join(folder, 'editor_mobile.png'), fullPage: true });
  assert.deepEqual(errors, []);
  await fs.writeFile(
    path.join(folder, 'web_validation.json'),
    JSON.stringify(
      {
        status: 'PASS',
        job_id: job,
        whole_material_version: whole.version,
        part_material_version: partial.version,
        restore_original_version: restore.version,
        final_version: final.version,
        parts: final.parts.length,
        connected_component_http_status: component.status(),
        connected_component_parts: componentData.parts?.length,
        original_sha256: createHash('sha256').update(original).digest('hex'),
        original_unchanged: true,
        history_restore_bytes_identical: true,
        refresh_restored: true,
        mobile_overflow: false,
        page_errors: errors,
        final_url: base + '/?job=' + job,
        manifest: final.manifest,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({
      status: 'PASS',
      job_id: job,
      final_version: final.version,
      parts: final.parts.length,
      connected_components_status: component.status(),
    }),
  );
} finally {
  await browser.close();
}

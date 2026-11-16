import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';

const root = process.cwd();
const base = process.env.WORKBENCH_URL || 'http://127.0.0.1:8000';
const output = path.join(root, '.data', 'checks', 'workbench');
await fs.mkdir(output, { recursive: true });
const chrome = process.env.CHROME_PATH;
const browser = await chromium.launch({
  executablePath: chrome,
  headless: true,
  args: [
    '--use-angle=swiftshader',
    '--enable-unsafe-swiftshader',
    '--disable-dev-shm-usage',
    '--no-sandbox',
  ],
});
const page = await browser.newPage({
  viewport: { width: 1440, height: 1100 },
  deviceScaleFactor: 1,
});
const errors = [];
page.on('pageerror', (error) => errors.push(error.message));
page.on('console', (message) => {
  if (message.type() === 'error' && !message.text().includes('favicon'))
    errors.push(message.text());
});
try {
  await page.goto(base, { waitUntil: 'networkidle' });
  await page.locator('.examples-grid .example-card').first().waitFor();
  assert.equal(await page.locator('.examples-grid .example-card').count(), 4);
  await page.locator('.viewer-canvas canvas').waitFor();
  await page.locator('.viewer-overlay').waitFor({ state: 'hidden', timeout: 60000 });
  assert.equal(await page.getByRole('button', { name: '开始生成', exact: true }).isDisabled(), true);
  await page.screenshot({ path: path.join(output, 'workbench-desktop.png'), fullPage: true });

  await page
    .getByTestId('image-upload')
    .setInputFiles(path.join(root, 'library/previews/furniture6__03_cork_bench.png'));
  await page.locator('.image-editor canvas').waitFor();
  await page.getByRole('button', { name: '框选目标', exact: true }).click();
  await page.getByRole('button', { name: /手动结构工具/ }).click();
  await page.getByLabel('商品名称').fill('置物架 · 流程验收');
  const canvas = page.locator('.image-editor canvas');
  const bounds = await canvas.boundingBox();
  assert.ok(bounds);
  await page.mouse.move(bounds.x + bounds.width * 0.08, bounds.y + bounds.height * 0.08);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width * 0.92, bounds.y + bounds.height * 0.92, {
    steps: 8,
  });
  await page.mouse.up();
  await page.getByRole('button', { name: '擦除背景', exact: true }).click();
  await page.mouse.move(bounds.x + bounds.width * 0.12, bounds.y + bounds.height * 0.12);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width * 0.2, bounds.y + bounds.height * 0.12, {
    steps: 5,
  });
  await page.mouse.up();
  await page.getByLabel('宽度（厘米）').fill('90');
  await page.getByLabel('深度（厘米）').fill('40');
  await page.getByLabel('高度（厘米）').fill('120');
  await page.getByLabel('层数', { exact: true }).selectOption('4');
  await page.getByLabel('以上尺寸已对照实物或厂家资料确认').check();
  await page.getByRole('button', { name: '开始生成' }).click();
  const accept = page.getByRole('button', { name: '审核通过', exact: true });
  await accept.waitFor({ timeout: 30000 });
  await page.waitForFunction(
    () =>
      ![...document.querySelectorAll('button')].find(
        (button) => button.textContent?.trim() === '审核通过',
      )?.disabled,
    { timeout: 30000 },
  );
  await page.getByRole('button', { name: '图片对照', exact: false }).click();
  await page.locator('.comparison-image img').waitFor();
  await page.getByRole('button', { name: '模型视图', exact: false }).click();
  await accept.click();
  await page.getByText('已通过人工审核', { exact: true }).waitFor();
  await page.getByRole('button', { name: '质量报告', exact: false }).click();
  assert.equal(
    await page.locator('.report-rows > div').filter({ hasText: '完整 glTF Validator' }).innerText(),
    '完整 glTF Validator\n通过',
  );
  await page.keyboard.press('Escape');
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('link', { name: '下载处理记录包', exact: false }).click();
  const download = await downloadEvent;
  const downloadPath = path.join(output, 'e2e-asset.zip');
  await download.saveAs(downloadPath);
  assert.ok((await fs.stat(downloadPath)).size > 1000);
  await page.screenshot({ path: path.join(output, 'generated-model.png'), fullPage: true });
  await page.reload({ waitUntil: 'networkidle' });
  await page.getByText('已通过人工审核', { exact: true }).waitFor();
  await page.locator('.viewer-overlay').waitFor({ state: 'hidden' });
  await page.getByRole('button', { name: '任务记录', exact: false }).click();
  await page
    .getByRole('dialog')
    .getByRole('button', { name: /置物架 · 流程验收/ })
    .first()
    .click();
  await page.getByText('已通过人工审核', { exact: true }).waitFor();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(output, 'workbench-mobile.png'), fullPage: true });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  assert.equal(overflow, false, 'Mobile layout overflows horizontally');
  assert.deepEqual(errors, [], 'Browser reported errors');
  console.log(
    JSON.stringify(
      {
        status: 'PASS',
        flow: 'upload → crop → erase → generate → compare → review → download → reload',
        screenshots: output,
      },
      null,
      2,
    ),
  );
} catch (error) {
  await page.screenshot({ path: path.join(output, 'test-failure.png'), fullPage: true });
  console.error('Browser errors:', errors);
  throw error;
} finally {
  await browser.close();
}

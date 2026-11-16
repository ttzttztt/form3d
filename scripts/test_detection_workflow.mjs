import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';

const root = process.cwd();
const output = path.join(root, '.data/checks/workbench');
const base = process.env.WORKBENCH_URL || 'http://127.0.0.1:8000';
const references = JSON.parse(
  await fs.readFile(path.join(root, '.data/assistant_delivery_jobs.json'), 'utf8'),
);
const bookcase = references.find((item) => item.product === 'bookcase');
const alien = references.find((item) => item.product === 'alien');
const browser = await chromium.launch({
  executablePath:
    process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-sandbox'],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const errors = [];
page.on('pageerror', (error) => errors.push(error.message));
try {
  await page.goto(`${base}/?job=${bookcase.job_id}`, { waitUntil: 'networkidle' });
  await page.locator('.object-chips button').first().waitFor({ timeout: 30000 });
  const labels = await page.locator('.object-chips').innerText();
  for (const label of ['书柜', '花瓶', '盆栽', '扶手椅'])
    assert.ok(labels.includes(label), label + ' not detected');
  await page.locator('.viewer-overlay').waitFor({ state: 'hidden', timeout: 30000 });
  await page.screenshot({
    path: path.join(output, 'automatic-targets-bookcase.png'),
    fullPage: true,
  });
  assert.equal(
    await page.getByRole('link', { name: /下载模型/ }).getAttribute('href'),
    `/api/jobs/${bookcase.job_id}/files/model.glb`,
  );
  await page.locator('.object-chips button').filter({ hasText: '花瓶' }).first().click();
  // A changed object must not keep showing the previous object's model.
  assert.equal(await page.locator('.viewer-canvas canvas').count(), 0);
  await page.getByLabel('商品名称').fill('自动目标识别 · 流程验收');
  await page.getByRole('button', { name: '提交看图建模' }).click();
  await page.getByRole('button', { name: '等待对话建模' }).waitFor({ timeout: 15000 });
  assert.ok((await page.locator('.event-current').innerText()).includes('当前对话'));
  const tasks = await (await page.request.get(base + '/api/jobs')).json();
  const task = tasks.find((item) => item.name === '自动目标识别 · 流程验收');
  assert.equal(task.status, 'awaiting_assistant');
  assert.equal(task.request.object_label, '花瓶');
  assert.equal(task.model_url, undefined);
  await page.request.post(`${base}/api/jobs/${task.id}/cancel`);

  await page.goto(`${base}/?job=${alien.job_id}`, { waitUntil: 'networkidle' });
  await page.locator('.viewer-overlay').waitFor({ state: 'hidden', timeout: 30000 });
  await page.screenshot({ path: path.join(output, 'assistant-alien-model.png'), fullPage: true });
  assert.equal(
    await page.getByRole('link', { name: /下载模型/ }).getAttribute('href'),
    `/api/jobs/${alien.job_id}/files/model.glb`,
  );
  assert.deepEqual(errors, []);
  console.log(
    JSON.stringify(
      {
        status: 'PASS',
        classes: ['书柜', '花瓶', '盆栽', '扶手椅'],
        no_template_fallback: true,
        imported_models: 2,
      },
      null,
      2,
    ),
  );
} catch (error) {
  await page.screenshot({ path: path.join(output, 'detection-test-failure.png'), fullPage: true });
  throw error;
} finally {
  await browser.close();
}

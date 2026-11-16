// Asset-free browser smoke test: upload → template route → generate → editor opens.
// Needs a running server (WORKBENCH_URL, default http://127.0.0.1:8000); CHROME_PATH optional.
import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';

const base = process.env.WORKBENCH_URL || 'http://127.0.0.1:8000';
const output = path.resolve('.data/checks/smoke');
await fs.mkdir(output, { recursive: true });
// The fixture image is drawn on a canvas so the test needs no files from library/.
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH,
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-sandbox'],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
page.on('console', (m) => {
  if (m.type() === 'error' && !m.text().includes('favicon')) errors.push(m.text());
});
try {
  await page.goto(base, { waitUntil: 'networkidle' });
  for (const label of ['使用指南', '服务设置']) {
    await page.getByRole('button', { name: label, exact: true }).first().click();
    await page.locator('.modal-backdrop').waitFor();
    await page.locator('.modal-backdrop').click({ position: { x: 5, y: 5 } });
  }
  const png = await page.evaluate(() => {
    const c = document.createElement('canvas');
    c.width = 640;
    c.height = 480;
    const g = c.getContext('2d');
    g.fillStyle = '#fff';
    g.fillRect(0, 0, 640, 480);
    g.fillStyle = '#8c6446';
    g.fillRect(180, 150, 280, 40);
    g.fillStyle = '#5a3c28';
    g.fillRect(200, 190, 20, 190);
    g.fillRect(420, 190, 20, 190);
    return c.toDataURL('image/png').split(',')[1];
  });
  await page
    .locator('input[type=file]')
    .first()
    .setInputFiles({ name: 'table.png', mimeType: 'image/png', buffer: Buffer.from(png, 'base64') });
  await page.getByRole('button', { name: /手动结构工具/ }).click();
  await page.getByRole('button', { name: '开始生成' }).click();
  await page.getByRole('button', { name: '换材质' }).waitFor({ timeout: 60000 });
  await page.screenshot({ path: path.join(output, 'editor.png') });
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ passed: true }));
} finally {
  await browser.close();
}

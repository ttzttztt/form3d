import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const folder = path.resolve('experiments/selection_refinement_20261112'),
  base = 'http://127.0.0.1:8001',
  cases = JSON.parse(await fs.readFile(path.join(folder, 'cases.json'), 'utf8'));
const browser = await chromium.launch({
  executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-sandbox'],
});
const results = { errors: [], cases: [] };
try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
  page.setDefaultTimeout(180000);
  page.on('pageerror', (e) => results.errors.push(e.message));
  let totalRequests = 0;
  page.on('request', (r) => {
    if (r.url().endsWith('/asset/part-proposal')) totalRequests++;
  });
  for (const c of cases) {
    const record = { case: c.case, job: c.job, queries: [] };
    results.cases.push(record);
    await page.goto(base + '/?job=' + c.job, { waitUntil: 'networkidle' });
    await page.locator('.viewer-overlay').waitFor({ state: 'hidden' });
    const view = page.getByTestId('model-viewer').first(),
      canvas = view.locator('canvas');
    await view.getByRole('button', { name: 'AI 辅助选区', exact: true }).click();
    async function click(x, y, label) {
      await page.waitForTimeout(350);
      const request = page
          .waitForRequest((r) => r.url().endsWith('/asset/part-proposal'), { timeout: 8000 })
          .catch(() => undefined),
        pending = page
          .waitForResponse((r) => r.url().endsWith('/asset/part-proposal'), { timeout: 180000 })
          .catch(() => undefined);
      const rect = await canvas.boundingBox();
      await canvas.click({ position: { x: rect.width * x, y: rect.height * y } });
      if (!(await request)) {
        record.queries.push({
          label,
          click: [x, y],
          request_sent: false,
          message: await view.locator('[role=status]').allTextContents(),
        });
        return false;
      }
      const response = await pending;
      if (!response) {
        record.queries.push({ label, timeout: true });
        return false;
      }
      const body = await response.json();
      await page.waitForFunction(
        () => !document.querySelector('.face-tools')?.textContent.includes('辅助分割进行中'),
      );
      const query = {
        label,
        status: response.status(),
        click: [x, y],
        proposal: body.proposal_id,
        views: body.views,
        prompts: JSON.parse(response.request().postData()).views.map((v) => v.points),
        message: await view.locator('[role=status]').allTextContents(),
        faces: Number(await view.locator('.face-tools').getAttribute('data-selected-faces')),
      };
      record.queries.push(query);
      await view.screenshot({ path: path.join(folder, c.case + '_' + label + '.png') });
      return query.faces > 0;
    }
    const initial = c.case === 'accent_chair' ? [0.5, 0.48] : [0.5, 0.4];
    let chosen = await click(...initial, 'initial');
    if (!chosen && record.queries.every((q) => q.request_sent === false))
      chosen = await click(0.5, 0.55, 'initial_retry');
    record.initial_faces = Number(
      await view.locator('.face-tools').getAttribute('data-selected-faces'),
    );
    record.ranges = await view
      .getByLabel('AI 候选范围', { exact: true })
      .locator('option')
      .evaluateAll((options) => options.map((o) => ({ value: o.value, disabled: o.disabled })));
    const previous = totalRequests;
    record.range_faces = [];
    for (const range of record.ranges.filter((r) => !r.disabled)) {
      await view.getByLabel('AI 候选范围', { exact: true }).selectOption(range.value);
      await page.waitForTimeout(150);
      record.range_faces.push({
        range: range.value,
        faces: Number(await view.locator('.face-tools').getAttribute('data-selected-faces')),
      });
    }
    assert.equal(totalRequests, previous);
    record.range_uses_cache = true;
    if (
      chosen &&
      ['round_table', 'accent_chair', 'leather_sofa', 'white_cabinet'].includes(c.case)
    ) {
      await view.getByRole('button', { name: '不要这里', exact: true }).click();
      await click(
        c.case === 'accent_chair' ? 0.57 : 0.53,
        c.case === 'accent_chair' ? 0.56 : 0.62,
        'negative',
      );
      if (c.case === 'accent_chair') {
        await view.getByRole('button', { name: '保留这里', exact: true }).click();
        await click(0.48, 0.54, 'positive');
        await view.screenshot({ path: path.join(folder, 'chair_multipoint.png') });
      }
    }
    const catalog = await (await page.request.get(base + `/api/jobs/${c.job}/asset`)).json();
    assert.equal(catalog.versions.length, 0);
    record.no_model_versions = true;
    record.final_faces = Number(
      await view.locator('.face-tools').getAttribute('data-selected-faces'),
    );
    await view.screenshot({ path: path.join(folder, c.case + '_final.png') });
    await fs.writeFile(path.join(folder, 'sam_matrix.json'), JSON.stringify(results, null, 2));
    console.log(
      JSON.stringify({
        case: c.case,
        queries: record.queries.map((q) => ({ label: q.label, status: q.status, faces: q.faces })),
        ranges: record.range_faces,
      }),
    );
  }
  assert.deepEqual(results.errors, []);
} catch (e) {
  results.failure = e.stack;
  throw e;
} finally {
  await fs.writeFile(path.join(folder, 'sam_matrix.json'), JSON.stringify(results, null, 2));
  await browser.close();
}

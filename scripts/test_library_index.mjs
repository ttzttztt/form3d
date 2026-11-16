import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root=process.cwd();
const output=path.join(root,'.data/checks/library');
await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(pathToFileURL(path.join(root,'library/index.html')).href);
  await page.waitForFunction(()=>document.querySelector('#count').textContent==='68 件模型');
  assert.equal(await page.locator('.card').count(),68);
  await page.selectOption('#batch','catalog24');
  assert.equal(await page.locator('.card:visible').count(),24);
  await page.fill('#search','tulip');
  assert.equal(await page.locator('.card:visible').count(),1);
  await page.selectOption('#batch','');
  await page.fill('#search','');
  assert.equal(await page.locator('.card:visible').count(),68);
  await page.screenshot({path:path.join(output,'library_index.png')});
  const broken=await page.locator('img').evaluateAll(images=>images.filter(image=>image.complete&&image.naturalWidth===0).map(image=>image.src));
  assert.deepEqual(broken,[]);
  assert.deepEqual(errors,[]);
  console.log('LIBRARY_INDEX_OK: 68 cards, batch filter, name search, local previews.');
} finally {await browser.close();}

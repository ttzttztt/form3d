import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const out=path.resolve('experiments/photo_guided_parts_20261113');
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const result={checks:[],errors:[]};
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>result.errors.push(e.message));
 await page.goto(pathToFileURL(path.join(out,'index.html')).href,{waitUntil:'load'});
 const broken=await page.locator('main img').evaluateAll(images=>images.filter(img=>!img.complete||!img.naturalWidth).map(img=>img.src));assert.deepEqual(broken,[]);result.checks.push('all_evidence_images_load');
 await page.locator('main > h1').screenshot({path:path.join(out,'report_title.png')});
 await page.locator('img.zoom').first().click();assert.ok(await page.getByRole('dialog').isVisible());await page.getByRole('button',{name:'关闭',exact:true}).click();assert.equal(await page.getByRole('dialog').count(),0);result.checks.push('click_to_enlarge_and_close');
 await page.getByRole('button',{name:'拒绝样本',exact:true}).click();assert.equal(await page.locator('[data-case]:visible').count(),1);assert.equal(await page.locator('[data-case]:visible').getAttribute('data-case'),'corduroy_side');result.checks.push('case_filter_shows_refusal');
 await page.getByRole('button',{name:'全部',exact:true}).click();assert.equal(await page.locator('[data-case]:visible').count(),3);
 await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.screenshot({path:path.join(out,'report_mobile.png')});result.checks.push('mobile_report_has_no_horizontal_overflow');assert.deepEqual(result.errors,[]);
}catch(e){result.failure=e.stack;throw e;}finally{await fs.writeFile(path.join(out,'report_browser_checks.json'),JSON.stringify(result,null,2));await browser.close();}
console.log(JSON.stringify(result));

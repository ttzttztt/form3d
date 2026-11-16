import {chromium} from 'playwright';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const out=path.resolve(process.env.PART_REGEN_REPORT_OUTPUT||'experiments/part_regeneration_20261113'),result={checks:[],errors:[]};
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 page.on('pageerror',e=>result.errors.push(e.message));
 await page.goto(pathToFileURL(path.join(out,'index.html')).href,{waitUntil:'networkidle'});
 for(const img of await page.locator('figure img').all()){
   await img.scrollIntoViewIfNeeded();
   await img.evaluate(e=>e.complete?Promise.resolve():new Promise((resolve,reject)=>{e.onload=resolve;e.onerror=reject}));
   assert.ok(await img.evaluate(e=>e.naturalWidth>0));
 }
 result.images=await page.locator('figure img').count();result.checks.push('all_report_evidence_images_load');
 await page.locator('figure img').first().click();assert.ok(await page.locator('dialog').evaluate(e=>e.open));
 await page.getByRole('button',{name:'关闭',exact:true}).click();result.checks.push('evidence_image_zoom_and_close');
 await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(out,'report_desktop.png')});
 await page.setViewportSize({width:390,height:844});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.screenshot({path:path.join(out,'report_mobile.png')});result.checks.push('report_mobile_layout_no_overflow');
 assert.deepEqual(result.errors,[]);
}catch(e){result.failure=e.stack;throw e;}
finally{await fs.writeFile(path.join(out,'report_checks.json'),JSON.stringify(result,null,2));await browser.close();}
console.log(JSON.stringify(result));

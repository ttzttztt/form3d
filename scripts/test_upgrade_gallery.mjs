import {chromium}from 'playwright';import fs from 'node:fs/promises';import path from 'node:path';import {pathToFileURL}from 'node:url';import assert from 'node:assert/strict';
const out=path.resolve('experiments/autonomous_upgrade_20261113'),result={checks:[],page_errors:[]};
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--no-sandbox']});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1050}});page.on('pageerror',e=>result.page_errors.push(e.message));await page.goto(pathToFileURL(path.join(out,'index.html')).href);assert.equal(await page.locator('article').count(),28);
 await page.locator('#status').selectOption('preserved');assert.equal(await page.locator('article:visible').count(),9);await page.locator('#status').selectOption('saved');assert.equal(await page.locator('article:visible').count(),19);await page.locator('#status').selectOption('');await page.locator('#query').fill('沙发');assert.equal(await page.locator('article:visible').count(),2);result.checks.push('all_28_cards_present','preserved_and_saved_filters','furniture_search');
 await page.screenshot({path:path.join(out,'gallery_desktop.png'),fullPage:true});await page.setViewportSize({width:390,height:844});await page.evaluate(()=>window.scrollTo(0,0));assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.screenshot({path:path.join(out,'gallery_mobile.png')});result.checks.push('390px_no_overflow');assert.deepEqual(result.page_errors,[]);
}catch(e){result.failure=e.stack;throw e;}finally{await fs.writeFile(path.join(out,'gallery_verification.json'),JSON.stringify(result,null,2));await browser.close();}
console.log(JSON.stringify(result));

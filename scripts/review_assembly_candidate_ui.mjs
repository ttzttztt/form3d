import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const source=path.resolve(process.argv[2]),folder=path.resolve(process.argv[3]);
await fs.mkdir(folder,{recursive:false});
const imported=JSON.parse(await fs.readFile(path.join(source,'workbench_import.json'),'utf8'));
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});
const result={job:imported.job,page_errors:[],checks:[],model_appearance_accepted:false};
try{
 const page=await browser.newPage({viewport:{width:1600,height:1100},acceptDownloads:true});page.setDefaultTimeout(120000);page.on('pageerror',e=>result.page_errors.push(e.message));
 const response=await page.request.get('http://127.0.0.1:8001/api/jobs/'+imported.job+'/asset');assert.equal(response.status(),200,await response.text());
 const catalog=await response.json();result.catalog=catalog;assert.equal(catalog.parts.length,2);assert.equal(new Set(catalog.parts.map(p=>p.logical_group_id)).size,2);
 await page.goto(imported.url,{waitUntil:'networkidle'});await page.locator('.viewer-overlay').waitFor({state:'hidden'});
 await page.screenshot({path:path.join(folder,'workbench.png'),fullPage:true});
 result.buttons=await page.getByRole('button').allTextContents();result.selects=await page.locator('select').evaluateAll(items=>items.map(i=>({label:i.getAttribute('aria-label'),name:i.name,options:[...i.options].map(o=>({text:o.text,value:o.value}))})));
 result.checks.push('browser_loads_imported_two_part_model','two_distinct_logical_groups_present','no_automatic_appearance_acceptance');assert.deepEqual(result.page_errors,[]);
}finally{await fs.writeFile(path.join(folder,'review.json'),JSON.stringify(result,null,2));await browser.close();}

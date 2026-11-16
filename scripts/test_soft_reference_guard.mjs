import {chromium}from'playwright';
import fs from'node:fs/promises';import path from'node:path';import assert from'node:assert/strict';
const out=path.resolve('experiments/soft_part_quality_20261113'),base='http://127.0.0.1:8001';
const c=JSON.parse(await fs.readFile(path.join(out,'cases.json'),'utf8'))[0];
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const result={checks:[]};
try{
 const page=await browser.newPage();const root=`/api/jobs/${c.job}/asset`,catalog=await(await page.request.get(base+root)).json();
 const image=await page.request.post(base+'/api/images',{multipart:{file:{name:'tiny_part.png',mimeType:'image/png',buffer:await fs.readFile(path.join(out,'tiny_reference.png'))}}});assert.equal(image.status(),201);const uploaded=await image.json();
 let response=await page.request.post(base+root+'/part-reference-scans',{data:{version:catalog.version,part_ids:c.part_ids,kind:'pillow',reference_image_id:uploaded.id}});assert.equal(response.status(),200,await response.text());const task=await response.json();
 let refs;for(let i=0;i<60;i++){refs=await(await page.request.get(base+root+'/part-reference-scans/'+task.id)).json();if(!['queued','running'].includes(refs.status))break;await page.waitForTimeout(1000);}
 assert.equal(refs.status,'ready',JSON.stringify(refs));
 response=await page.request.post(base+root+'/part-regenerations',{data:{version:catalog.version,part_ids:c.part_ids,kind:'pillow',reference_image_id:uploaded.id,reference_scan_id:task.id,reference_candidate_id:refs.candidates[0].id}});
 assert.equal(response.status(),409);assert.match((await response.json()).detail,/有效区域不足 96/);assert.equal((await(await page.request.get(base+root)).json()).version,catalog.version);
 result.checks.push('actual_api_rejects_small_alpha_foreground_before_generation','current_model_version_unchanged');
}catch(e){result.failure=e.stack;throw e;}finally{await fs.writeFile(path.join(out,'reference_guard.json'),JSON.stringify(result,null,2));await browser.close();}
console.log(JSON.stringify(result));

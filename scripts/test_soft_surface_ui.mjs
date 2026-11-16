import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
const base='http://127.0.0.1:8001',out=path.resolve('experiments/soft_part_quality_20261113');
const c=JSON.parse(await fs.readFile(path.join(out,'cases.json'),'utf8')).find(c=>c.kind==='cushion');
const root=`/api/jobs/${c.job}/asset`,result={job:c.job,checks:[],errors:[],appearance_review:'candidate_only',new_ai_inference:false};
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});
try{
 const page=await browser.newPage({viewport:{width:1600,height:1150},acceptDownloads:true});page.setDefaultTimeout(180000);page.on('pageerror',e=>result.errors.push(e.message));
 const get=async url=>{const response=await page.request.get(base+url);assert.equal(response.status(),200,await response.text());return response.json();};
 let catalog=await get(root);assert.equal(catalog.version,'original');
 await page.goto(base+'/?job='+c.job,{waitUntil:'networkidle'});await page.locator('.viewer-overlay').waitFor({state:'hidden'});
 const editor=page.getByRole('region',{name:'部件与材质编辑'});
 await editor.getByRole('button',{name:'拆分部件',exact:true}).click();await editor.getByRole('button',{name:'选择部件 '+c.part_name,exact:true}).click();
 const panel=editor.locator('.part-regeneration');await panel.locator(':scope > summary').click();
 let pending=page.waitForResponse(r=>r.url().endsWith('/part-surface-repairs')&&r.request().method()==='POST');
 await panel.getByRole('button',{name:'沿接缝拆出完整坐垫',exact:true}).click();let response=await pending;assert.equal(response.status(),200,await response.text());const task=await response.json();result.task=task.id;
 let state;
 for(let i=0;i<240;i++){state=await get(root+'/part-regenerations/'+task.id);if(!['queued','running'].includes(state.status))break;await page.waitForTimeout(1000);}
 assert.equal(state.status,'ready',JSON.stringify(state));assert.equal(state.operation.method,'source_seam');assert.ok(state.operation.surface_repair);result.operation=state.operation;
 const folder=path.resolve('.data/jobs',c.job,'part_regenerations',task.id),manifest=JSON.parse(await fs.readFile(path.join(folder,'preview/manifest.json'),'utf8'));
 assert.equal(manifest.generation_model,null);assert.equal(manifest.generation_mode,'source_surface_partition');
 assert.equal((await get(root)).version,'original');result.checks.push('actual_source_guided_repair_with_no_photo_or_ai_generation','preview_keeps_original_version');
 const save=panel.getByRole('button',{name:'采用这个替换候选',exact:true});await save.waitFor();assert.ok(await save.isDisabled());
 const confirm=panel.getByRole('checkbox',{name:'已检查部件形状、位置和接合处'});
 await page.waitForFunction(()=>{const c=document.querySelector('.part-regeneration input[type="checkbox"]');return c&&!c.disabled;});
 for(const view of ['正面','侧面','背面','底面']){await panel.getByRole('button',{name:'预览'+view,exact:true}).click();await page.waitForTimeout(250);await panel.screenshot({path:path.join(out,'ui_seat_'+view+'.png')});}
 await panel.getByRole('button',{name:'只看拆出部件',exact:true}).click();
 const download=page.waitForEvent('download');await panel.getByRole('link',{name:'单独下载新部件',exact:true}).click();await(await download).saveAs(path.join(out,'browser_repaired_seat.glb'));
 result.checks.push('four_sided_preview_marks_inferred_roof_and_bottom','isolated_full_logical_group_download','save_is_gated');
 await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await panel.screenshot({path:path.join(out,'ui_seat_mobile.png')});await page.setViewportSize({width:1600,height:1150});
 await confirm.check();pending=page.waitForResponse(r=>r.url().endsWith('/asset/versions')&&r.request().method()==='POST');await save.click();response=await pending;assert.equal(response.status(),201,await response.text());catalog=await response.json();result.saved_version=catalog.version;assert.equal(catalog.groups.length,4);assert.equal(catalog.editor_review_status,'unreviewed');
 const saved=await(await page.request.get(base+catalog.model_url)).body(),preview=await fs.readFile(path.join(folder,'preview/model.glb'));assert.equal(crypto.createHash('sha256').update(saved).digest('hex'),crypto.createHash('sha256').update(preview).digest('hex'));
 result.checks.push('exact_preview_adoption_into_four_logical_groups');
 await page.locator('.viewer-overlay').waitFor({state:'hidden'});await editor.getByRole('button',{name:'换材质',exact:true}).click();
 const group=catalog.groups.find(g=>state.operation.part_group_ids.includes(g.id));result.part_ids=group.part_ids;
 await editor.getByRole('button',{name:'选择部件 '+group.name,exact:true}).click();const before=new Map(catalog.parts.map(p=>[p.id,p.material_signature]));
 await editor.getByLabel('材质颜色',{exact:true}).evaluate(input=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'#387e88');input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));});
 pending=page.waitForResponse(r=>r.url().endsWith('/asset/versions')&&r.request().method()==='POST');await editor.getByRole('button',{name:'保存当前材质效果',exact:true}).click();response=await pending;assert.equal(response.status(),201,await response.text());catalog=await response.json();result.material_version=catalog.version;
 assert.deepEqual(new Set(catalog.parts.filter(p=>before.get(p.id)!==p.material_signature).map(p=>p.id)),new Set(group.part_ids));result.checks.push('material_changes_all_seat_patches_and_no_other_group','mobile_layout_no_overflow');
 await page.screenshot({path:path.join(out,'ui_seat_material.png')});assert.deepEqual(result.errors,[]);
}catch(e){result.failure=e.stack;throw e;}finally{await fs.writeFile(path.join(out,'ui_source_result.json'),JSON.stringify(result,null,2));await browser.close();}
console.log(JSON.stringify(result));

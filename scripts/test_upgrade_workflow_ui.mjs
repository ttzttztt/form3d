import {chromium}from 'playwright';
import fs from 'node:fs/promises';import path from 'node:path';import crypto from 'node:crypto';import assert from 'node:assert/strict';
const base='http://127.0.0.1:8001',out=path.resolve('experiments/autonomous_upgrade_20261113');await fs.mkdir(path.join(out,'ui'),{recursive:true});
const config=process.env.UPGRADE_UI_CONFIG,tag=process.env.UPGRADE_UI_TAG||'v1';
let c=JSON.parse(await fs.readFile(path.join(out,'cases.json'),'utf8')).find(c=>c.case==='corduroy_sofa');
const run=JSON.parse(await fs.readFile(path.join(out,config||'part_corduroy_sofa_v3.json'),'utf8'));if(config)c={...c,job:run.job,source_model:run.source_model};const root=`/api/jobs/${c.job}/asset`,hash=x=>crypto.createHash('sha256').update(x).digest('hex');
const result={job:c.job,task:run.task,checks:[],page_errors:[],physical_appearance_accepted:false};
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});
try{
 const page=await browser.newPage({viewport:{width:1600,height:1150},acceptDownloads:true});page.setDefaultTimeout(180000);page.on('pageerror',e=>result.page_errors.push(e.message));
 const get=async url=>{const r=await page.request.get(base+url);assert.equal(r.status(),200,await r.text());return r.json();};
 let catalog=await get(root);assert.equal(catalog.version,'original');let task=await get(root+'/part-regenerations/'+run.task);assert.equal(task.status,'ready');assert.equal(task.candidate_results.length,3);assert.ok(task.candidate_results.every(c=>['completed','failed'].includes(c.status)));
 const ids=run.request.part_ids,sourceHash=hash(await fs.readFile(path.resolve(c.source_model)));
 const storageKey='form_part_regeneration:'+JSON.stringify({jobId:c.job,version:catalog.version,partIds:ids});
 await page.addInitScript(({key,task})=>sessionStorage.setItem(key,JSON.stringify({task,candidateCount:3})),{key:storageKey,task});
 await page.goto(base+'/?job='+c.job,{waitUntil:'networkidle'});await page.locator('.viewer-overlay').waitFor({state:'hidden'});
 const editor=page.getByRole('region',{name:'部件与材质编辑'});await editor.getByRole('button',{name:'拆分部件',exact:true}).click();await editor.getByRole('button',{name:'选择部件 靠枕 3',exact:true}).click();const panel=editor.locator('.part-regeneration');await panel.locator(':scope > summary').click();
 assert.equal(await panel.getByLabel('部件分项验收').locator('.part-assessment').count(),4);await panel.getByText('查看 3 个候选与未采用原因',{exact:true}).click();
 assert.equal(await panel.locator('.part-candidate-list article').count(),3);result.checks.push('session_restores_actual_ready_task','four_separate_assessments','three_terminal_candidates_and_rejection_reasons');
 const save=panel.getByRole('button',{name:'采用这个替换候选',exact:true});assert.ok(await save.isDisabled());const confirm=panel.getByRole('checkbox',{name:'已检查部件形状、位置和接合处'});await confirm.waitFor();
 for(const view of ['正面','侧面','背面','底面']){await panel.getByRole('button',{name:'预览'+view,exact:true}).click();await page.waitForTimeout(250);await panel.locator('.cut-preview').screenshot({path:path.join(out,'ui',view+'.png')});}
 await panel.getByRole('button',{name:'只看拆出部件',exact:true}).click();const download=page.waitForEvent('download');await panel.getByRole('link',{name:'单独下载新部件',exact:true}).click();await(await download).saveAs(path.join(out,'ui/new_part_download.glb'));
 const folder=path.resolve('.data/jobs',c.job,'part_regenerations',task.id);assert.equal(hash(await fs.readFile(path.join(out,'ui/new_part_download.glb'))),hash(await fs.readFile(path.join(folder,'preview/part.glb'))));result.checks.push('four_preview_directions_and_part_isolation','download_matches_checked_part_bytes');
 assert.equal(task.photo_checks.can_adopt,true);await confirm.check();let pending=page.waitForResponse(r=>r.url().endsWith('/asset/versions')&&r.request().method()==='POST');await save.click();let response=await pending;assert.equal(response.status(),201,await response.text());catalog=await response.json();result.adopted_version=catalog.version;
 const op=catalog.manifest.operation;const group=catalog.groups.find(g=>op.part_group_ids.includes(g.id));assert.ok(group);result.part_ids=group.part_ids;
 assert.equal(hash(await(await page.request.get(base+catalog.model_url)).body()),hash(await fs.readFile(path.join(folder,'preview/model.glb'))));assert.equal(catalog.editor_review_status,'unreviewed');await page.locator('.viewer-overlay').waitFor({state:'hidden'});
 assert.equal(await editor.getByRole('button',{name:'换材质',exact:true}).getAttribute('aria-pressed'),'true');assert.equal(await editor.getByLabel('编辑范围',{exact:true}).inputValue(),'saved_selection');result.checks.push('adopts_exact_selected_preview_bytes','new_complete_group_selected_for_materials','saved_model_remains_unreviewed');
 // Run the actual keep route on the newly closed untextured part, before texturing it.
 response=await page.request.post(base+root+'/part-optimizations',{data:{version:catalog.version,part_ids:group.part_ids,candidate_count:1,target_faces:100000}});assert.equal(response.status(),200,await response.text());let keep=await response.json();
 for(let i=0;i<300;i++){keep=await get(root+'/part-regenerations/'+keep.id);if(!['queued','running'].includes(keep.status))break;await page.waitForTimeout(1000);}
 result.keep_task=keep;assert.equal(keep.status,'ready');assert.equal(keep.operation.method,'keep');assert.equal(keep.photo_checks.can_adopt,false);
 response=await page.request.post(base+root+'/versions',{data:{base_version:catalog.version,operation:'replace_part',part_ids:group.part_ids,regeneration_preview_id:keep.id}});assert.equal(response.status(),409);result.checks.push('actual_keep_route_preserves_complete_part_and_blocks_duplicate_adoption');
 const originalMaterials=new Map(catalog.parts.map(p=>[p.id,p.material_signature]));
 for(const name of ['示例布料','示例皮革','示例木纹']){
  await editor.getByRole('button',{name,exact:true}).click();const cancel=editor.getByRole('button',{name:'取消预览',exact:true});await cancel.waitFor();await page.waitForFunction(()=>document.querySelector('.asset-editor .material-presets button')?.disabled===false);await cancel.click();assert.equal((await get(root)).version,catalog.version);
 }
 result.checks.push('all_three_example_materials_preview_and_cancel_without_saving');
 await editor.getByRole('button',{name:'示例布料',exact:true}).click();const details=editor.getByText('上传纹理图片（可选）',{exact:true});await details.click();await editor.getByLabel('纹理重复',{exact:true}).fill('3.5');await editor.getByLabel('纹理旋转',{exact:true}).fill('30');await page.waitForTimeout(600);await page.getByTestId('model-viewer').first().screenshot({path:path.join(out,'ui/cloth_preview.png')});
 await page.waitForFunction(()=>Array.from(document.querySelectorAll('.asset-editor button')).some(b=>b.textContent==='保存当前材质效果'&&!b.disabled));[response]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/asset/versions')&&r.request().method()==='POST'),editor.getByRole('button',{name:'保存当前材质效果',exact:true}).click()]);assert.equal(response.status(),201,await response.text());catalog=await response.json();result.material_version=catalog.version;
 assert.deepEqual(new Set(catalog.parts.filter(p=>originalMaterials.get(p.id)!==p.material_signature).map(p=>p.id)),new Set(group.part_ids));assert.ok(catalog.parts.filter(p=>group.part_ids.includes(p.id)).every(p=>p.has_texture));assert.equal(catalog.editor_review_status,'unreviewed');assert.equal(hash(await fs.readFile(path.resolve(c.source_model))),sourceHash);result.checks.push('textured_uv_rotation_and_scale_saved','all_target_patches_and_only_target_changed','source_model_bytes_unchanged');
 await page.locator('.viewer-overlay').waitFor({state:'hidden'});await page.screenshot({path:path.join(out,'ui/desktop.png')});await page.setViewportSize({width:390,height:844});await page.waitForTimeout(350);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.screenshot({path:path.join(out,'ui/mobile.png')});result.checks.push('390px_no_horizontal_overflow');assert.deepEqual(result.page_errors,[]);
}catch(e){result.failure=e.stack;throw e;}finally{await fs.writeFile(path.join(out,'browser_flow_'+tag+'.json'),JSON.stringify(result,null,2));await browser.close();}
console.log(JSON.stringify({checks:result.checks,adopted_version:result.adopted_version,material_version:result.material_version}));

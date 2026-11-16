import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
const base='http://127.0.0.1:8001',out=path.resolve('experiments/photo_guided_parts_20261113');
const name=process.argv[2]||'corduroy_center',c=JSON.parse(await fs.readFile(path.join(out,'cases.json'),'utf8')).find(c=>c.case===name);
assert.ok(c);const root=`/api/jobs/${c.job}/asset`,result={case:name,job:c.job,checks:[],page_errors:[],appearance_acceptance:false};
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
try{
 const page=await browser.newPage({viewport:{width:1600,height:1150},acceptDownloads:true});page.setDefaultTimeout(180000);page.on('pageerror',e=>result.page_errors.push(e.message));
 const get=async url=>{const r=await page.request.get(base+url);assert.equal(r.status(),200,await r.text());return r.json();};
 let catalog=await get(root);assert.equal(catalog.version,'original');
 await page.goto(base+'/?job='+c.job,{waitUntil:'networkidle'});await page.locator('.viewer-overlay').waitFor({state:'hidden'});
 const editor=page.getByRole('region',{name:'部件与材质编辑'});await editor.getByRole('button',{name:'拆分部件',exact:true}).click();await editor.getByRole('button',{name:'选择部件 '+c.part_name,exact:true}).click();
 const panel=editor.locator('.part-regeneration');await panel.locator(':scope > summary').click();
 let pending=page.waitForResponse(r=>r.url().endsWith('/part-optimizations')&&r.request().method()==='POST');
 await panel.getByRole('button',{name:'自动分析并优化部件',exact:true}).click();let response=await pending;assert.equal(response.status(),200,await response.text());const task=await response.json();result.task=task.id;
 await fs.writeFile(path.join(out,name+'_live.json'),JSON.stringify(result,null,2));
 let state,last;
 for(let i=0;i<900;i++){
  state=await get(root+'/part-regenerations/'+task.id);const stage=state.stage+':'+state.sampling_step;
  if(last!==stage){console.log(name,stage);last=stage;}
  if(!['queued','running'].includes(state.status))break;
  if(i%20===0)assert.equal((await get(root)).version,'original');
  await page.waitForTimeout(1000);
 }
 result.terminal_state=state;assert.ok(['ready','needs_input','failed'].includes(state.status));
 assert.equal((await get(root)).version,'original');result.checks.push('one_click_real_worker_and_automatic_route','source_version_unchanged_before_explicit_adoption');
 await page.waitForTimeout(1500);
 if(state.association_url){const r=await page.request.get(base+state.association_url);assert.equal(r.status(),200);await fs.writeFile(path.join(out,name+'_association.png'),await r.body());result.checks.push('original_photo_correspondence_overlay');}
 if(state.status==='ready'){
  const save=panel.getByRole('button',{name:'采用这个替换候选',exact:true});await save.waitFor({state:'visible'});assert.ok(await save.isDisabled());
  const folder=path.resolve('.data/jobs',c.job,'part_regenerations',task.id);result.manifest=JSON.parse(await fs.readFile(path.join(folder,'preview/manifest.json'),'utf8'));
  assert.equal(result.manifest.generation_model,state.generated_valid?'Hunyuan3D-2mini':null);result.checks.push('generation_provenance_matches_actual_route');
  await page.waitForFunction(()=>!!document.querySelector('.cut-preview canvas'));
  await page.waitForTimeout(2000);
  for(const view of ['正面','侧面','背面','底面']){await panel.getByRole('button',{name:'预览'+view,exact:true}).click();await page.waitForTimeout(400);await panel.screenshot({path:path.join(out,name+'_'+view+'.png')});}
  await panel.getByRole('button',{name:'只看拆出部件',exact:true}).click();const download=page.waitForEvent('download');await panel.getByRole('link',{name:'单独下载新部件',exact:true}).click();await(await download).saveAs(path.join(out,name+'_download.glb'));result.checks.push('four_views_and_isolated_complete_group_download');
  const r=await page.request.get(base+state.comparison_url);assert.equal(r.status(),200);await fs.writeFile(path.join(out,name+'_comparison.png'),await r.body());
  const confirm=panel.getByRole('checkbox',{name:'已检查部件形状、位置和接合处'});
  if(state.photo_checks.can_adopt){
   await confirm.check();pending=page.waitForResponse(r=>r.url().endsWith('/asset/versions')&&r.request().method()==='POST');await save.click();response=await pending;assert.equal(response.status(),201,await response.text());catalog=await response.json();result.saved_version=catalog.version;
   const saved=await(await page.request.get(base+catalog.model_url)).body(),preview=await fs.readFile(path.join(folder,'preview/model.glb'));assert.equal(hash(saved),hash(preview));assert.equal(catalog.editor_review_status,'unreviewed');result.checks.push('exact_preview_adoption_and_unreviewed_status');
   await page.locator('.viewer-overlay').waitFor({state:'hidden'});await editor.getByRole('button',{name:'换材质',exact:true}).click();const group=catalog.groups.find(g=>state.operation.part_group_ids.includes(g.id));result.adopted_part_ids=group.part_ids;
   await editor.getByRole('button',{name:'选择部件 '+group.name,exact:true}).click();const before=new Map(catalog.parts.map(p=>[p.id,p.material_signature]));
   await editor.getByLabel('材质颜色',{exact:true}).evaluate(input=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'#387e88');input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));});
   pending=page.waitForResponse(r=>r.url().endsWith('/asset/versions')&&r.request().method()==='POST');await editor.getByRole('button',{name:'保存当前材质效果',exact:true}).click();response=await pending;assert.equal(response.status(),201,await response.text());catalog=await response.json();result.material_version=catalog.version;
   assert.deepEqual(new Set(catalog.parts.filter(p=>before.get(p.id)!==p.material_signature).map(p=>p.id)),new Set(group.part_ids));result.checks.push('material_changes_every_target_patch_and_no_adjacent_group');
  }else{
   assert.ok(await confirm.isDisabled());response=await page.request.post(base+root+'/versions',{data:{base_version:'original',operation:'replace_part',regeneration_preview_id:task.id,part_ids:c.part_ids}});assert.equal(response.status(),409);result.checks.push('failed_comparison_blocks_checkbox_and_direct_api_adoption');
  }
 }else{
  response=await page.request.post(base+root+'/versions',{data:{base_version:'original',operation:'replace_part',regeneration_preview_id:task.id,part_ids:c.part_ids}});assert.equal(response.status(),409);result.checks.push('inconclusive_or_failed_candidate_cannot_replace_source');
  if(state.generated_url){response=await page.request.get(base+state.generated_url);assert.equal(response.status(),200);await fs.writeFile(path.join(out,name+'_unassembled.glb'),await response.body());result.checks.push('valid_unassembled_generation_remains_downloadable');}
 }
 await page.screenshot({path:path.join(out,name+'_desktop.png')});await page.setViewportSize({width:390,height:844});await page.waitForTimeout(350);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.screenshot({path:path.join(out,name+'_mobile.png')});result.checks.push('mobile_no_horizontal_overflow');assert.deepEqual(result.page_errors,[]);
}catch(e){result.failure=e.stack;throw e;}finally{await fs.writeFile(path.join(out,name+'_ui.json'),JSON.stringify(result,null,2));await browser.close();}
console.log(JSON.stringify({case:name,checks:result.checks,status:result.terminal_state?.status,task:result.task}));

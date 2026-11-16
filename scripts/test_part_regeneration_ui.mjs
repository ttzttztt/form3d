import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';

const base='http://127.0.0.1:8001',out=path.resolve(process.env.PART_REGEN_OUTPUT||'experiments/part_regeneration_20261113');
const cases=JSON.parse(await fs.readFile(path.join(out,'cases.json'),'utf8'));
const c=cases.find(c=>c.case==='corduroy_pillow'),root=`/api/jobs/${c.job}/asset`;
const result={job:c.job,checks:[],page_errors:[],appearance_acceptance:false,
  test_scope:'isolated clone; save/material assertions are workflow tests, not appearance approval'};
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
try{
  const page=await browser.newPage({viewport:{width:1600,height:1150},acceptDownloads:true});
  page.setDefaultTimeout(180000);page.on('pageerror',e=>result.page_errors.push(e.message));
  const get=async url=>{const r=await page.request.get(base+url);assert.equal(r.status(),200,await r.text());return r.json();};
  let catalog=await get(root);assert.equal(catalog.version,'original');
  await page.goto(base+'/?job='+c.job,{waitUntil:'networkidle'});
  await page.locator('.viewer-overlay').waitFor({state:'hidden'});
  const editor=page.getByRole('region',{name:'部件与材质编辑'});
  await editor.getByRole('button',{name:'拆分部件',exact:true}).click();
  await editor.getByRole('button',{name:'选择部件 '+c.part_name,exact:true}).click();
  const panel=editor.locator('.part-regeneration');
  await panel.locator(':scope > summary').click();
  assert.equal(await panel.getByRole('combobox').inputValue(),'pillow');
  let pending=page.waitForResponse(r=>r.url().endsWith('/part-reference-scans')&&r.request().method()==='POST');
  await panel.getByRole('button',{name:'寻找部件参考候选',exact:true}).click();
  let response=await pending;assert.equal(response.status(),200,await response.text());const scan=await response.json();result.reference_scan=scan.id;
  let refs;
  for(let i=0;i<390;i++){
    refs=await get(root+'/part-reference-scans/'+scan.id);
    if(!['running','queued'].includes(refs.status))break;
    await page.waitForTimeout(1000);
  }
  assert.equal(refs.status,'ready',JSON.stringify(refs));
  const index=refs.candidates.findIndex(v=>v.id==='d391b5818dc25703678f6b057d2b9d14');
  assert.ok(index>=0,'Previously visually inspected clean pillow reference must be present');
  result.reference_candidate=refs.candidates[index].id;result.reference_candidates=refs.candidates.length;
  const generate=panel.getByRole('button',{name:'用所选参考生成 3D 预览',exact:true});
  await generate.waitFor({state:'visible'});assert.ok(await generate.isDisabled());
  await panel.getByRole('button',{name:refs.candidates[index].label,exact:true}).click();
  await panel.screenshot({path:path.join(out,'ui_reference_candidates.png')});
  result.checks.push('actual_original_photo_reference_extraction_and_explicit_candidate_selection');
  pending=page.waitForResponse(r=>r.url().endsWith('/part-regenerations')&&r.request().method()==='POST');
  await generate.click();response=await pending;assert.equal(response.status(),200,await response.text());const task=await response.json();result.regeneration_id=task.id;
  await fs.writeFile(path.join(out,'ui_live_task.json'),JSON.stringify(result,null,2));
  const extra=await page.request.post(base+root+'/part-reference-scans',{data:{version:'original',part_ids:c.part_ids,kind:'pillow'}});
  assert.equal(extra.status(),200,await extra.text());const extraTask=await extra.json();
  await page.request.post(base+root+'/part-reference-scans/'+extraTask.id+'/cancel');
  let state,last;
  for(let i=0;i<540;i++){
    state=await get(root+'/part-regenerations/'+task.id);
    const status=state.stage+':'+state.sampling_step;
    if(last!==status){console.log(status);last=status;}
    if(!['running','queued'].includes(state.status))break;
    if(i%20===0)assert.equal((await get(root)).version,'original');
    await page.waitForTimeout(1000);
  }
  result.terminal_state=state;
  assert.equal(state.status,'ready',JSON.stringify(state));
  assert.equal((await get(root+'/part-reference-scans/'+extraTask.id)).status,'cancelled');
  result.checks.push('actual_local_hunyuan_generation_and_alignment_without_publishing','queued_reference_cancellation');
  const save=panel.getByRole('button',{name:'采用这个替换候选',exact:true});
  await save.waitFor({state:'visible'});assert.ok(await save.isDisabled());
  const confirmation=panel.getByRole('checkbox',{name:'已检查部件形状、位置和接合处'});
  await confirmation.waitFor({state:'visible'});
  await page.waitForFunction(()=>{const e=document.querySelector('.part-regeneration input[type="checkbox"]');return e&&!e.disabled;},{},{timeout:240000});
  for(const view of ['正面','侧面','背面','底面']){
    await panel.getByRole('button',{name:'预览'+view,exact:true}).click();
    await page.waitForTimeout(400);
    await panel.screenshot({path:path.join(out,`ui_preview_${view}.png`)});
  }
  await panel.getByRole('button',{name:'只看拆出部件',exact:true}).click();
  const download=page.waitForEvent('download');await panel.getByRole('link',{name:'单独下载新部件',exact:true}).click();
  await(await download).saveAs(path.join(out,'browser_regenerated_pillow.glb'));
  result.checks.push('four_views_and_isolated_part_download','save_requires_loaded_preview_and_explicit_confirmation');
  await page.setViewportSize({width:390,height:844});await page.waitForTimeout(400);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await panel.screenshot({path:path.join(out,'ui_regeneration_mobile.png')});
  await page.setViewportSize({width:1600,height:1150});
  const wrong=await page.request.post(base+root+'/versions',{data:{base_version:'original',operation:'replace_part',regeneration_preview_id:task.id,part_ids:[catalog.parts.find(p=>!c.part_ids.includes(p.id)).id]}});
  assert.equal(wrong.status(),409);assert.equal((await get(root)).version,'original');
  await confirmation.check();pending=page.waitForResponse(r=>r.url().endsWith('/asset/versions')&&r.request().method()==='POST');
  await save.click();response=await pending;assert.equal(response.status(),201,await response.text());catalog=await response.json();
  result.saved_version=catalog.version;
  const adopted=await(await page.request.get(base+catalog.model_url)).body();
  const preview=await fs.readFile(path.resolve('.data/jobs',c.job,'part_regenerations',task.id,'preview/model.glb'));
  assert.equal(hash(adopted),hash(preview));result.preview_sha256=hash(preview);
  assert.equal(catalog.editor_review_status,'unreviewed');
  result.checks.push('changed_scope_rejected','adopted_exact_preview_bytes_into_new_unreviewed_version');
  await page.locator('.viewer-overlay').waitFor({state:'hidden'});
  await editor.getByRole('button',{name:'换材质',exact:true}).click();
  const group=catalog.groups.find(g=>g.id===state.operation.source_group_id);
  await editor.getByRole('button',{name:'选择部件 '+group.name,exact:true}).click();
  const before=new Map(catalog.parts.map(p=>[p.id,p.material_signature]));
  await editor.getByLabel('材质颜色',{exact:true}).evaluate(input=>{
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'#297d88');
    input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));
  });
  pending=page.waitForResponse(r=>r.url().endsWith('/asset/versions')&&r.request().method()==='POST');
  await editor.getByRole('button',{name:'保存当前材质效果',exact:true}).click();response=await pending;assert.equal(response.status(),201,await response.text());catalog=await response.json();
  assert.deepEqual(new Set(catalog.parts.filter(p=>before.get(p.id)!==p.material_signature).map(p=>p.id)),new Set(group.part_ids));
  result.material_version=catalog.version;result.checks.push('material_change_affects_regenerated_pillow_only','mobile_no_horizontal_overflow');
  const stale=await page.request.post(base+root+'/versions',{data:{base_version:'original',operation:'replace_part',regeneration_preview_id:task.id,part_ids:c.part_ids}});
  assert.equal(stale.status(),409);result.checks.push('stale_preview_cannot_override_later_version');
  await page.screenshot({path:path.join(out,'ui_regenerated_material.png')});
  assert.deepEqual(result.page_errors,[]);
}catch(e){result.failure=e.stack;throw e;}
finally{await fs.writeFile(path.join(out,'ui_results.json'),JSON.stringify(result,null,2));await browser.close();}
console.log(JSON.stringify(result));

import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const out=path.resolve('experiments/part_regeneration_20261113'),base='http://127.0.0.1:8001';
const c=JSON.parse(await fs.readFile(path.join(out,'cases.json'),'utf8')).find(c=>c.case==='leather_cushion');
const result={job:c.job,checks:[],errors:[],generation_in_this_test:false};
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});
try{
  const page=await browser.newPage({viewport:{width:1500,height:1100}});page.setDefaultTimeout(60000);
  page.on('pageerror',e=>result.errors.push(e.message));
  const root=`/api/jobs/${c.job}/asset`;
  const catalog=await(await page.request.get(base+root)).json();
  assert.equal(catalog.version,'original');
  await page.goto(base+'/?job='+c.job,{waitUntil:'networkidle'});
  let editor=page.getByRole('region',{name:'部件与材质编辑'}),panel=editor.locator('.part-regeneration');
  async function select(name){
    await editor.getByRole('button',{name:'拆分部件',exact:true}).click();
    await editor.getByRole('button',{name:'选择部件 '+name,exact:true}).click();
    if(!await panel.evaluate(e=>e.open))await panel.locator(':scope > summary').click();
  }
  await select(c.part_name);assert.equal(await panel.getByRole('combobox').inputValue(),'cushion');
  await panel.locator('summary').filter({hasText:'使用单独的部件参考图'}).click();
  const upload=path.join(out,'leather_cushion/completed_reference/reference.png');
  await panel.getByLabel('部件参考图片').setInputFiles(upload);
  await panel.getByRole('button',{name:'恢复使用原图',exact:true}).waitFor();
  let pending=page.waitForResponse(r=>r.url().endsWith('/part-reference-scans')&&r.request().method()==='POST');
  await panel.getByRole('button',{name:'寻找部件参考候选',exact:true}).click();
  const response=await pending;assert.equal(response.status(),200,await response.text());const scan=await response.json();
  result.reference_scan=scan.id;result.uploaded_reference_is_inferred=true;
  await page.reload({waitUntil:'networkidle'});await select(c.part_name);
  await panel.getByRole('button',{name:'提供的透明部件参考',exact:true}).waitFor();
  assert.equal(await panel.locator('.part-reference-grid button').count(),1);
  const state=await(await page.request.get(base+root+'/part-reference-scans/'+scan.id)).json();
  assert.equal(state.status,'ready');assert.equal(state.reference_origin,'uploaded');
  result.checks.push('actual_alpha_upload_preserved_without_claiming_automatic_extraction','reload_restores_reference_and_resumes_existing_task_polling');
  await panel.getByRole('button',{name:'提供的透明部件参考',exact:true}).click();
  await page.reload({waitUntil:'networkidle'});await select(c.part_name);
  assert.equal(await panel.getByRole('button',{name:'提供的透明部件参考',exact:true}).getAttribute('aria-pressed'),'true');
  assert.ok(await panel.getByRole('button',{name:'用所选参考生成 3D 预览',exact:true}).isEnabled());
  result.checks.push('reload_keeps_reference_choice_but_does_not_start_generation_or_adopt_model');
  await panel.locator('summary').filter({hasText:'使用单独的部件参考图'}).click();
  let notifyUpload;const uploaded=new Promise(r=>notifyUpload=r);
  await page.route('**/api/images',async route=>{
    const reply=await route.fetch();notifyUpload();await new Promise(r=>setTimeout(r,1800));await route.fulfill({response:reply});
  });
  await panel.getByLabel('部件参考图片').setInputFiles(upload);await uploaded;
  const bolster=catalog.groups.find(g=>g.semantic_kind==='bolster');
  await editor.getByRole('button',{name:'选择部件 '+bolster.name,exact:true}).click();
  if(!await panel.evaluate(e=>e.open))await panel.locator(':scope > summary').click();
  await page.waitForTimeout(2200);
  assert.equal(await panel.getByRole('combobox').inputValue(),'bolster');
  assert.equal(await panel.getByRole('button',{name:'恢复使用原图',exact:true}).count(),0);
  assert.equal(await panel.locator('.part-reference-grid button').count(),0);
  await page.unroute('**/api/images');
  result.checks.push('scope_switch_sets_matching_kind_and_discards_late_upload_response');
  await select(c.part_name);
  assert.equal(await panel.getByRole('button',{name:'提供的透明部件参考',exact:true}).getAttribute('aria-pressed'),'true');
  await panel.screenshot({path:path.join(out,'ui_cushion_uploaded_reference.png')});
  assert.equal((await(await page.request.get(base+root)).json()).version,'original');
  assert.deepEqual(result.errors,[]);
}catch(e){result.failure=e.stack;throw e;}
finally{await fs.writeFile(path.join(out,'ui_controls.json'),JSON.stringify(result,null,2));await browser.close();}
console.log(JSON.stringify(result));

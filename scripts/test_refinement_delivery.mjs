import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
const folder=path.resolve('experiments/selection_refinement_20261112'),base='http://127.0.0.1:8001';
const c=JSON.parse(await fs.readFile(path.join(folder,'delivery_case.json'),'utf8'));
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});
const result={job:c.job,errors:[],queries:[],checks:[]};
try {
  const page=await browser.newPage({viewport:{width:1600,height:1200}});page.setDefaultTimeout(180000);page.on('pageerror',e=>result.errors.push(e.message));
  await page.goto(base+'/?job='+c.job,{waitUntil:'networkidle'});await page.locator('.viewer-overlay').waitFor({state:'hidden'});
  const view=page.getByTestId('model-viewer').first(),editor=page.getByRole('region',{name:'部件与材质编辑'}),canvas=view.locator('canvas');
  const original=await(await page.request.get(base+`/api/jobs/${c.job}/asset`)).json();assert.equal(original.version,'original');
  await view.getByRole('button',{name:'AI 辅助选区',exact:true}).click();
  async function click(x,y,label){await page.waitForTimeout(450);const pending=page.waitForResponse(r=>r.url().endsWith('/asset/part-proposal'));const rect=await canvas.boundingBox();await canvas.click({position:{x:rect.width*x,y:rect.height*y}});const r=await pending;assert.equal(r.status(),200,await r.text());await page.waitForFunction(()=>!document.querySelector('.face-tools')?.textContent.includes('辅助分割进行中'));const faces=Number(await view.locator('.face-tools').getAttribute('data-selected-faces'));assert.ok(faces>0);result.queries.push({label,faces,proposal:(await r.json()).proposal_id});}
  await click(.5,.48,'initial');await view.getByRole('button',{name:'不要这里',exact:true}).click();await click(.57,.56,'negative');await view.getByRole('button',{name:'保留这里',exact:true}).click();await click(.48,.54,'positive');
  assert.equal(await view.getByLabel('AI 候选范围',{exact:true}).isEnabled(),true);
  await editor.getByLabel('部件名称',{exact:true}).fill('多点修正表面（验收副本）');
  async function action(name){const pending=page.waitForResponse(r=>r.url().endsWith('/asset/versions')&&r.request().method()==='POST');await editor.getByRole('button',{name,exact:true}).click();const r=await pending;assert.equal(r.status(),201,await r.text());const catalog=await r.json();await page.locator('.viewer-overlay').waitFor({state:'hidden'});return catalog;}
  const split=await action('保存选区为新部件');assert.equal(split.metrics.triangles,original.metrics.triangles);const target=split.groups.find(g=>g.name==='多点修正表面（验收副本）');assert.ok(target);result.split_version=split.version;result.part_ids=target.part_ids;
  assert.equal(await view.getByLabel('AI 候选范围',{exact:true}).isDisabled(),true);assert.ok((await view.locator('.face-tools').textContent()).includes('保留点 0 · 排除点 0'));result.checks.push({name:'new_model_version_clears_prompt_counts_and_cached_ranges',pass:true});
  await editor.getByLabel('材质颜色',{exact:true}).evaluate(input=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'#38a684');input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));});
  const colored=await action('保存当前材质效果');const changed=colored.parts.filter(p=>p.material_signature!==split.parts.find(o=>o.id===p.id).material_signature).map(p=>p.id);assert.deepEqual(changed,target.part_ids);result.material_version=colored.version;result.checks.push({name:'multipoint_selection_to_part_and_local_material_only',pass:true});await page.screenshot({path:path.join(folder,'multipoint_saved_material.png'),fullPage:true});
  await page.goto(base+'/?job='+c.source_job,{waitUntil:'networkidle'});await page.locator('.viewer-overlay').waitFor({state:'hidden'});await editor.getByRole('button',{name:'更多操作',exact:true}).click();await editor.getByText('同图本地引擎对照与结构验收',{exact:true}).click();await editor.getByRole('button',{name:'打开生成结果对照',exact:true}).click();const dialog=page.getByRole('dialog',{name:'本地生成结果对照'});await dialog.waitFor();
  await dialog.getByLabel('生成细节档位',{exact:true}).selectOption('structure');const pending=page.waitForResponse(r=>r.url().endsWith('/reconstruction-comparison')&&r.request().method()==='POST');await dialog.getByRole('button',{name:'准备 TripoSR 候选',exact:true}).click();const response=await pending;assert.equal(response.status(),200);const job=await response.json();assert.equal(job.id,'7e06cf8be00a4f1a86fdd7fd739d5183');assert.equal(job.request.local_quality,'structure');result.reuses_structure_job=job.id;
  await dialog.getByLabel('右侧生成候选',{exact:true}).selectOption('89fcd5efbcb2476eb5e7283834f5b88b');await dialog.locator('.viewer-overlay').first().waitFor({state:'hidden'});await dialog.locator('.viewer-overlay').last().waitFor({state:'hidden'});assert.equal(await dialog.getByTestId('model-viewer').count(),2);result.checks.push({name:'balanced_and_structure_in_same_comparison_family',pass:true});await page.screenshot({path:path.join(folder,'structure_comparison_desktop.png')});
  await page.setViewportSize({width:390,height:844});await page.waitForTimeout(350);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.screenshot({path:path.join(folder,'structure_comparison_mobile.png')});await dialog.getByRole('button',{name:'关闭生成对照',exact:true}).click();assert.deepEqual(result.errors,[]);
}catch(e){result.failure=e.stack;throw e;}finally{await fs.writeFile(path.join(folder,'delivery_browser.json'),JSON.stringify(result,null,2));await browser.close();}
console.log(JSON.stringify(result,null,2));

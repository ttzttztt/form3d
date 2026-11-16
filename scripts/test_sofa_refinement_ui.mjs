import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const out=path.resolve('experiments/sofa_refinement_20261113'),base='http://127.0.0.1:8001';
const c=JSON.parse(await fs.readFile(path.join(out,'cases.json'),'utf8')).find(c=>c.case==='leather_sofa');
const result={job:c.job,errors:[],checks:[],sam:[]};
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});
try {
 const page=await browser.newPage({viewport:{width:1600,height:1150}});page.setDefaultTimeout(180000);page.on('pageerror',e=>result.errors.push(e.message));
 await page.goto(base+'/?job='+c.job,{waitUntil:'networkidle'});await page.locator('.viewer-overlay').waitFor({state:'hidden'});
 const view=page.getByTestId('model-viewer').first(),canvas=view.locator('canvas'),editor=page.getByRole('region',{name:'部件与材质编辑'});
 await view.screenshot({path:path.join(out,'ui_initial.png')});
 await view.getByRole('button',{name:'AI 辅助选区',exact:true}).click();
 async function prompt(button,x,y) {
  if(button)await view.getByRole('button',{name:button,exact:true}).click();
  const reply=page.waitForResponse(r=>r.url().endsWith('/asset/part-proposal'),{timeout:180000});
  const box=await canvas.boundingBox();await canvas.click({position:{x:box.width*x,y:box.height*y}});
  const r=await reply;result.sam.push({button,status:r.status(),request:JSON.parse(r.request().postData()),body:await r.json()});
  await view.getByRole('button',{name:'开始新选区',exact:true}).waitFor();
  await page.waitForFunction(()=>!document.querySelector('.face-tools')?.textContent.includes('正在根据保留点'));
  return r.status();
 }
 assert.equal(await prompt(null,.60,.55),200);
 await prompt('不要这里',.44,.36);await view.screenshot({path:path.join(out,'ui_exclusion.png')});
 // Drag still rotates in SAM mode, then supplement a visible side surface.
 const box=await canvas.boundingBox();await page.mouse.move(box.x+box.width*.5,box.y+box.height*.5);await page.mouse.down();await page.mouse.move(box.x+box.width*.5+55,box.y+box.height*.5,{steps:12});await page.mouse.up();await page.waitForTimeout(300);
 await prompt('保留这里',.61,.64);await view.screenshot({path:path.join(out,'ui_side_supplement.png')});
 result.selected_faces=Number(await view.locator('.face-tools').getAttribute('data-selected-faces'));assert.ok(result.selected_faces>0);
 result.checks.push('real_positive_negative_and_rotated_supplement_requests');
 await editor.getByRole('button',{name:'拆分部件',exact:true}).click();await editor.getByLabel('部件名称',{exact:true}).fill('界面坐垫预览');await editor.getByText('完整部件：检查范围与补齐接合面',{exact:true}).click();await editor.getByLabel('坐垫切分方式',{exact:true}).selectOption('box');
 let pending=page.waitForResponse(r=>r.url().endsWith('/asset/completion-plan'));await editor.getByRole('button',{name:'检查坐垫与原网格',exact:true}).click();let r=await pending;assert.equal(r.status(),200,await r.text());
 const bounds=[[0,.385,0],[1,.523,1]];
 for(let i=0;i<3;i++)for(let j=0;j<2;j++)await editor.getByLabel(`完整部件 ${['X 左右','Y 上下','Z 前后'][i]} ${['起点','终点'][j]}`,{exact:true}).fill(String(bounds[j][i]*100));
 pending=page.waitForResponse(r=>r.url().endsWith('/asset/completion-preview'));await editor.getByRole('button',{name:'预览实际切分',exact:true}).click();r=await pending;assert.equal(r.status(),200,await r.text());result.preview=await r.json();
 await editor.getByRole('button',{name:'预览侧面',exact:true}).click();await page.waitForTimeout(200);await editor.locator('.cut-preview').screenshot({path:path.join(out,'ui_preview_side.png')});await editor.getByRole('button',{name:'只看拆出部件',exact:true}).click();await editor.getByRole('button',{name:'预览底面',exact:true}).click();await page.waitForTimeout(200);await editor.locator('.cut-preview').screenshot({path:path.join(out,'ui_preview_bottom.png')});
 const save=editor.getByRole('button',{name:'生成完整部件候选',exact:true});assert.ok(await save.isDisabled());
 assert.equal((await(await page.request.get(base+`/api/jobs/${c.job}/asset`)).json()).version,'original');
 await editor.getByLabel('已检查坐垫厚度与相邻部件边界',{exact:true}).check();assert.ok(await save.isEnabled());
 result.checks.push('real_cut_preview_views_inferred_colours_and_confirmation_gate');
 // Changing bounds invalidates the old preview and its confirmation.
 await editor.getByLabel('完整部件 Y 上下 起点',{exact:true}).fill('38.6');await editor.locator('.cut-preview').waitFor({state:'hidden'});assert.equal(await save.count(),0);
 const stale={...JSON.parse(r.request().postData()),completion_preview_id:result.preview.preview_id,completion_bounds:[[0,.386,0],[1,.523,1]]};const refused=await page.request.post(base+`/api/jobs/${c.job}/asset/versions`,{data:stale});assert.equal(refused.status(),409);result.stale_status=refused.status();
 result.checks.push('changed_bounds_invalidate_preview_and_backend_rejects_stale_save');
 await page.setViewportSize({width:390,height:844});await page.waitForTimeout(300);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.screenshot({path:path.join(out,'ui_mobile.png'),fullPage:true});result.checks.push('mobile_no_horizontal_overflow');assert.deepEqual(result.errors,[]);
} catch(e){result.failure=e.stack;throw e;} finally {await fs.writeFile(path.join(out,'ui_results.json'),JSON.stringify(result,null,2));await browser.close();}
console.log(JSON.stringify({checks:result.checks,sam:result.sam.map(s=>({button:s.button,status:s.status})),errors:result.errors},null,2));

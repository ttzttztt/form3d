import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
const folder=path.resolve('experiments/selection_ux_20261112'),base='http://127.0.0.1:8000';
const cases=JSON.parse(await fs.readFile(path.join(folder,'cases.json'),'utf8'));
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});
const results={errors:[],checks:[]};
try{
 const page=await browser.newPage({viewport:{width:1600,height:1080}});page.setDefaultTimeout(90000);page.on('pageerror',error=>results.errors.push(error.message));
 const table=cases.find(c=>c.case==='table');
 const current=await(await page.request.get(base+`/api/jobs/${table.job}/asset`)).json();
 const reset=await page.request.post(base+`/api/jobs/${table.job}/asset/versions`,{data:{operation:'restore_original',base_version:current.version}});assert.equal(reset.status(),201);
 await page.goto(base+'/?job='+table.job,{waitUntil:'networkidle'});await page.locator('.viewer-overlay').waitFor({state:'hidden'});
 const editor=page.getByRole('region',{name:'部件与材质编辑'}),view=page.getByTestId('model-viewer').first();
 assert.equal(await page.locator('.source-card').count(),0);assert.equal(await page.locator('.examples-section').count(),0);assert.equal(await editor.getByLabel('查看编辑版本',{exact:true}).count(),0);
 assert.ok(await editor.getByRole('button',{name:'应用材质并保存',exact:true}).isVisible());
 assert.equal(await view.getByRole('button',{name:'自动调整到相近视角',exact:true}).count(),0);
 const firstCanvas=await view.locator('canvas').boundingBox();assert.ok(firstCanvas.width>700,JSON.stringify(firstCanvas));results.checks.push({name:'focused_model_stage',canvas:firstCanvas});
 await page.screenshot({path:path.join(folder,'desktop_default.png'),fullPage:true});
 await view.getByRole('button',{name:'涂抹选择',exact:true}).click();
 const rect=await view.locator('canvas').boundingBox();
 const paint=async()=>{await page.mouse.move(rect.x+rect.width*.43,rect.y+rect.height*.31);await page.mouse.down();await page.mouse.move(rect.x+rect.width*.57,rect.y+rect.height*.31,{steps:15});await page.mouse.up();};
 await paint();await editor.getByRole('button',{name:'保存选区为部件',exact:true}).waitFor();
 assert.equal(await view.getByLabel('同时选择背面',{exact:true}).isChecked(),false);
 await view.screenshot({path:path.join(folder,'table_visible_selection.png')});
 await editor.getByLabel('部件名称',{exact:true}).fill('桌面局部');
 const pending=page.waitForResponse(r=>r.url().endsWith('/asset/versions')&&r.request().method()==='POST');await editor.getByRole('button',{name:'保存选区为部件',exact:true}).click();
 const response=await pending,split=await response.json();assert.equal(response.status(),201,JSON.stringify(split));
 await editor.getByRole('button',{name:'应用材质并保存',exact:true}).waitFor();await page.locator('.viewer-overlay').waitFor({state:'hidden'});
 assert.equal(await editor.getByLabel('编辑范围',{exact:true}).inputValue(),'saved_selection');
 const selected=split.parts.filter(p=>p.selection_role==='selected');assert.ok(selected.length>0);
 results.checks.push({name:'visible_selection_saves_and_scopes_material',selected_ids:selected.map(p=>p.id),version:split.version});
 await editor.getByLabel('材质颜色',{exact:true}).evaluate(input=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'#d3422f');input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));});
 const materialPending=page.waitForResponse(r=>r.url().endsWith('/asset/versions')&&r.request().method()==='POST');await editor.getByRole('button',{name:'应用材质并保存',exact:true}).click();const materialResponse=await materialPending,material=await materialResponse.json();assert.equal(materialResponse.status(),201,JSON.stringify(material));
 const changed=material.parts.filter(p=>JSON.stringify(p.base_color_factor)!==JSON.stringify(split.parts.find(s=>s.id===p.id).base_color_factor)).map(p=>p.id);assert.deepEqual(changed.sort(),selected.map(p=>p.id).sort());results.checks.push({name:'only_saved_surface_changes_material',changed,version:material.version});
 await page.locator('.viewer-overlay').waitFor({state:'hidden'});await page.screenshot({path:path.join(folder,'desktop_after_material.png'),fullPage:true});
 await page.getByRole('button',{name:'对照原图',exact:true}).click();assert.ok(await page.getByAltText('当前模型使用的参考图片').isVisible());await view.getByText('原图对照设置',{exact:true}).waitFor();
 await page.getByRole('button',{name:'查看模型',exact:true}).click();assert.equal(await page.getByAltText('当前模型使用的参考图片').count(),0);
 await page.getByRole('button',{name:'修改图片 / 重新生成',exact:true}).click();assert.ok(await page.locator('.source-card').isVisible());await page.getByRole('button',{name:'返回模型编辑',exact:true}).click();assert.equal(await page.locator('.source-card').count(),0);results.checks.push({name:'reference_and_preparation_are_on_demand',pass:true});
 await editor.getByRole('button',{name:'更多操作',exact:true}).click();assert.ok(await editor.getByLabel('查看编辑版本',{exact:true}).isVisible());await editor.getByRole('button',{name:'换材质',exact:true}).click();assert.equal(await editor.getByLabel('查看编辑版本',{exact:true}).count(),0);
 // Contextual controls and layouts on two more real models.
 for(const item of cases.filter(c=>c.case!=='table')){
   await page.goto(base+'/?job='+item.job,{waitUntil:'networkidle'});await page.locator('.viewer-overlay').waitFor({state:'hidden'});assert.equal(await page.locator('.source-card').count(),0);await page.screenshot({path:path.join(folder,item.case+'_desktop.png'),fullPage:true});results.checks.push({name:item.case+'_model_stage',pass:true});
 }
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(folder,'mobile.png'),fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);results.checks.push({name:'mobile_no_horizontal_overflow',pass:true});
 assert.deepEqual(results.errors,[]);
}finally{await fs.writeFile(path.join(folder,'browser_checks.json'),JSON.stringify(results,null,2));await browser.close();}
console.log(JSON.stringify(results,null,2));

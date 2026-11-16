import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const folder=path.resolve('experiments/point_selection_20261112'),base='http://127.0.0.1:8000';
const cases=JSON.parse(await fs.readFile(path.join(folder,'cases.json'),'utf8'));
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});
const results={errors:[],checks:[]};
try{
 const page=await browser.newPage({viewport:{width:1600,height:1080}});page.setDefaultTimeout(120000);page.on('pageerror',e=>results.errors.push(e.stack||e.message));
 const item=cases.find(c=>c.case==='table'),root=`/api/jobs/${item.job}`;
 const old=await(await page.request.get(base+root+'/asset')).json();if(old.version!=='original'){const r=await page.request.post(base+root+'/asset/versions',{data:{operation:'restore_original',base_version:old.version}});assert.equal(r.status(),201);}
 await page.goto(base+'/?job='+item.job,{waitUntil:'networkidle'});await page.locator('.viewer-overlay').waitFor({state:'hidden'});
 const view=page.getByTestId('model-viewer').first(),editor=page.getByRole('region',{name:'部件与材质编辑'}),count=async()=>Number(await view.locator('.face-tools').getAttribute('data-selected-faces'));
 await view.getByRole('button',{name:'点选部件',exact:true}).click();
 const canvas=view.locator('canvas'),clickTop=async()=>{const r=await canvas.boundingBox();await canvas.click({position:{x:r.width*.5,y:r.height*.31}});};
 await clickTop();await editor.getByRole('button',{name:'保存选区为部件',exact:true}).waitFor();const normal=await count();assert.ok(normal>1000);await view.getByRole('status').filter({hasText:'连续平面'}).waitFor();
 await view.screenshot({path:path.join(folder,'table_one_click.png')});results.checks.push({name:'one_click_table_plane',faces:normal});
 await view.getByText('点选设置',{exact:true}).click();await view.getByLabel('点选范围',{exact:true}).selectOption('wide');const wide=await count();assert.ok(wide>=normal);await view.getByLabel('追加到已有选区',{exact:true}).check();await view.getByLabel('点选范围',{exact:true}).selectOption('tight');const tight=await count();assert.ok(tight<=normal);results.checks.push({name:'range_shrinks_with_append_enabled',normal,wide,tight});
 await view.getByRole('button',{name:'清空',exact:true}).click();assert.equal(await count(),0);assert.ok(await view.getByLabel('点选范围',{exact:true}).isDisabled());results.checks.push({name:'clear_prevents_stale_seed_reappearing',pass:true});
 await view.getByLabel('追加到已有选区',{exact:true}).uncheck();await clickTop();const chosen=await count();await view.getByRole('button',{name:'撤销',exact:true}).click();assert.equal(await count(),0);await view.getByRole('button',{name:'重做',exact:true}).click();assert.equal(await count(),chosen);results.checks.push({name:'point_selection_undo_redo',faces:chosen});
 await editor.getByLabel('部件名称',{exact:true}).fill('桌面上表面');
 async function action(name){const pending=page.waitForResponse(r=>r.url().endsWith('/asset/versions')&&r.request().method()==='POST');await editor.getByRole('button',{name,exact:true}).click();const response=await pending,body=await response.json();assert.equal(response.status(),201,JSON.stringify(body));await page.locator('.viewer-overlay').waitFor({state:'hidden'});return body;}
 const split=await action('保存选区为部件');assert.equal(await editor.getByLabel('编辑范围',{exact:true}).inputValue(),'saved_selection');
 await editor.getByLabel('材质颜色',{exact:true}).evaluate(input=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'#b7773b');input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));});
 const colored=await action('应用材质并保存');const selected=colored.parts.filter(p=>p.selection_role==='selected');assert.equal(selected.length,1);const changed=colored.parts.filter(p=>JSON.stringify(p.base_color_factor)!==JSON.stringify(split.parts.find(s=>s.id===p.id).base_color_factor)).map(p=>p.id);assert.deepEqual(changed,[selected[0].id]);results.checks.push({name:'saved_plane_only_material_changes',job:item.job,version:colored.version,selected_id:selected[0].id,validation:colored.manifest.validation});
 await page.screenshot({path:path.join(folder,'table_material.png'),fullPage:true});
 // A saved part is selectable directly, with no second split or new request.
 await clickTop();await view.getByRole('status').filter({hasText:'已有部件'}).waitFor();assert.equal(await count(),0);assert.equal(await editor.getByLabel('编辑范围',{exact:true}).inputValue(),selected[0].id);results.checks.push({name:'saved_part_direct_pick',pass:true});
 // Drag in point mode rotates rather than selecting a new region.
 const rect=await canvas.boundingBox();await page.mouse.move(rect.x+rect.width*.5,rect.y+rect.height*.5);await page.mouse.down();await page.mouse.move(rect.x+rect.width*.6,rect.y+rect.height*.55,{steps:10});await page.mouse.up();assert.equal(await count(),0);results.checks.push({name:'point_mode_drag_rotates',pass:true});
 await view.getByRole('button',{name:'涂抹修正',exact:true}).click();const brushRect=await canvas.boundingBox();await page.mouse.move(brushRect.x+brushRect.width*.45,brushRect.y+brushRect.height*.3);await page.mouse.down();await page.mouse.move(brushRect.x+brushRect.width*.55,brushRect.y+brushRect.height*.4,{steps:10});await page.mouse.up();assert.ok(await count()>0);await view.getByText('选择设置',{exact:true}).click();assert.equal(await view.getByLabel('同时选择背面',{exact:true}).isChecked(),false);await view.getByRole('button',{name:'框选区域',exact:true}).click();assert.equal(await view.getByRole('button',{name:'框选区域',exact:true}).getAttribute('aria-pressed'),'true');results.checks.push({name:'brush_visible_only_and_box_retained',pass:true});
 // Exercise a connected soft shape without assuming that it can be segmented.
 const sofa=cases.find(c=>c.case==='sofa');await page.goto(base+'/?job='+sofa.job,{waitUntil:'networkidle'});await page.locator('.viewer-overlay').waitFor({state:'hidden'});await view.getByRole('button',{name:'点选部件',exact:true}).click();const sr=await canvas.boundingBox();await canvas.click({position:{x:sr.width*.5,y:sr.height*.48}});const message=await view.getByRole('status').last().textContent();const faces=await count();assert.ok(message.includes('连续平面')||message.includes('暂时无法')||message.includes('独立连通'));results.checks.push({name:'soft_shape_honest_result',faces,message});await view.screenshot({path:path.join(folder,'sofa_result.png')});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(folder,'mobile.png'),fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);results.checks.push({name:'mobile_no_horizontal_overflow',pass:true});assert.deepEqual(results.errors,[]);
}finally{await fs.writeFile(path.join(folder,'browser_checks.json'),JSON.stringify(results,null,2));await browser.close();}
console.log(JSON.stringify(results,null,2));

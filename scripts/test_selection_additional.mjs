import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
const folder=path.resolve('experiments/selection_ux_20261112'),base='http://127.0.0.1:8000';
const cases=JSON.parse(await fs.readFile(path.join(folder,'cases.json'),'utf8'));
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});
const results={errors:[],checks:[]};
try{
const page=await browser.newPage({viewport:{width:1500,height:1000}});page.setDefaultTimeout(90000);page.on('pageerror',e=>results.errors.push(e.message));
for(const item of cases.filter(c=>c.case!=='table')){
 await page.goto(base+'/?job='+item.job,{waitUntil:'networkidle'});await page.locator('.viewer-overlay').waitFor({state:'hidden'});
 const view=page.getByTestId('model-viewer').first(),editor=page.getByRole('region',{name:'部件与材质编辑'});
 await view.getByRole('button',{name:'框选区域',exact:true}).click();const rect=await view.locator('canvas').boundingBox();
 await page.mouse.move(rect.x+rect.width*.3,rect.y+rect.height*.2);await page.mouse.down();await page.mouse.move(rect.x+rect.width*.7,rect.y+rect.height*.6,{steps:10});await page.mouse.up();
 await editor.getByRole('button',{name:'保存选区为部件',exact:true}).waitFor();assert.equal(await view.getByLabel('同时选择背面',{exact:true}).isChecked(),false);
 await view.getByRole('button',{name:'撤销',exact:true}).click();assert.equal(await editor.getByRole('button',{name:'保存选区为部件',exact:true}).count(),0);
 await view.getByRole('button',{name:'重做',exact:true}).click();assert.ok(await editor.getByRole('button',{name:'保存选区为部件',exact:true}).isVisible());
 await view.screenshot({path:path.join(folder,item.case+'_selected.png')});results.checks.push({case:item.case,selection:true,visible_only_default:true,undo_redo:true});
}
await page.getByRole('button',{name:'新建任务',exact:true}).click();assert.ok(await page.locator('.source-card').isVisible());assert.equal(await page.getByRole('region',{name:'部件与材质编辑'}).count(),0);assert.ok(await page.getByTestId('image-upload').count());results.checks.push({case:'new_task',image_preparation_visible:true,model_editor_hidden:true});
assert.deepEqual(results.errors,[]);
}finally{await fs.writeFile(path.join(folder,'additional_selection_checks.json'),JSON.stringify(results,null,2));await browser.close();}
console.log(JSON.stringify(results));

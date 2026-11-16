import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const folder=path.resolve('experiments/point_selection_20261112'),cases=JSON.parse(await fs.readFile(path.join(folder,'cases.json'),'utf8'));
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});
const result={errors:[]};
try{
 const page=await browser.newPage({viewport:{width:1600,height:1080}});page.setDefaultTimeout(90000);page.on('pageerror',e=>result.errors.push(e.message));await page.goto('http://127.0.0.1:8000/?job='+cases[0].job,{waitUntil:'networkidle'});await page.locator('.viewer-overlay').waitFor({state:'hidden'});
 const editor=page.getByRole('region',{name:'部件与材质编辑'}),view=page.getByTestId('model-viewer').first(),canvas=view.locator('canvas'),count=async()=>Number(await view.locator('.face-tools').getAttribute('data-selected-faces'));
 await editor.getByRole('button',{name:'更多操作',exact:true}).click();await editor.getByLabel('查看编辑版本',{exact:true}).selectOption('original');await page.locator('.viewer-overlay').waitFor({state:'hidden'});
 await view.getByRole('button',{name:'点选部件',exact:true}).click();let rect=await canvas.boundingBox();await canvas.click({position:{x:rect.width*.5,y:rect.height*.31}});result.original_faces=await count();assert.ok(result.original_faces>1000);assert.equal(await view.getByLabel('点选范围',{exact:true}).isDisabled(),false);
 await view.getByRole('button',{name:'涂抹修正',exact:true}).click();await view.getByRole('button',{name:'擦掉多选',exact:true}).click();rect=await canvas.boundingBox();await page.mouse.move(rect.x+rect.width*.47,rect.y+rect.height*.31);await page.mouse.down();await page.mouse.move(rect.x+rect.width*.53,rect.y+rect.height*.31,{steps:8});await page.mouse.up();result.corrected_faces=await count();assert.ok(result.corrected_faces>0&&result.corrected_faces<result.original_faces);
 await view.getByRole('button',{name:'点选部件',exact:true}).click();assert.equal(await view.getByLabel('点选范围',{exact:true}).isDisabled(),true);assert.equal(await count(),result.corrected_faces);result.correction_preserved=true;assert.deepEqual(result.errors,[]);
}finally{await fs.writeFile(path.join(folder,'correction_context.json'),JSON.stringify(result,null,2));await browser.close();}
console.log(JSON.stringify(result));

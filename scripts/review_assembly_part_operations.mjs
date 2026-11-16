import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';

const source=path.resolve(process.argv[2]),folder=path.resolve(process.argv[3]);
await fs.mkdir(folder,{recursive:false});
const imported=JSON.parse(await fs.readFile(path.join(source,'workbench_import.json'),'utf8'));
const base='http://127.0.0.1:8001',root=`${base}/api/jobs/${imported.job}/asset`;
const hash=b=>createHash('sha256').update(b).digest('hex');
const result={job:imported.job,checks:[],page_errors:[],appearance_accepted:false};
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});
try{
 const page=await browser.newPage({viewport:{width:1600,height:1100},acceptDownloads:true});page.setDefaultTimeout(120000);page.on('pageerror',e=>result.page_errors.push(e.message));
 const before=await(await page.request.get(root)).json();result.before=before;
 const originalHash=hash(await(await page.request.get(base+before.original_url)).body());result.original_sha256=originalHash;
 const top=before.groups.find(g=>g.semantic_kind==='tabletop'),support=before.groups.find(g=>g.semantic_kind==='leg');assert.ok(top&&support);
 await page.goto(imported.url,{waitUntil:'networkidle'});await page.locator('.viewer-overlay').waitFor({state:'hidden'});
 const editor=page.getByRole('region',{name:'部件与材质编辑'}),view=page.getByTestId('model-viewer').first(),canvas=view.locator('canvas');
 await editor.getByLabel('编辑范围',{exact:true}).selectOption('g:'+top.id);await view.getByText('检查部件与拆解展示',{exact:true}).click();
 const snap=async name=>{await page.waitForTimeout(450);return await canvas.screenshot({path:path.join(folder,name+'.png')});};
 const all=await snap('assembled_selected');await view.getByRole('button',{name:'仅看选中部件',exact:true}).click();assert.notEqual(hash(await snap('tabletop_isolated')),hash(all));
 await view.getByRole('button',{name:'显示全部 / 复位拆解',exact:true}).click();assert.equal(hash(await snap('assembled_restored')),hash(all));
 await view.getByRole('button',{name:'隐藏选中部件',exact:true}).click();assert.notEqual(hash(await snap('support_without_top')),hash(all));await view.getByRole('button',{name:'显示全部 / 复位拆解',exact:true}).click();
 for(const [name,label]of [['front','查看正面'],['back','查看背面'],['under','查看底面']]){await view.getByRole('button',{name:label,exact:true}).click();await snap(name);}
 result.checks.push('independent_top_selection_isolate_hide_and_restore','front_back_under_views_recorded');
 await editor.getByLabel('材质颜色',{exact:true}).evaluate(input=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,input.value==='#2c8c7f'?'#bc734a':'#2c8c7f');input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));});
 const pending=page.waitForResponse(r=>r.url().endsWith('/asset/versions')&&r.request().method()==='POST');await editor.getByRole('button',{name:'保存当前材质效果',exact:true}).click();const response=await pending;assert.equal(response.status(),201,await response.text());
 const after=await response.json();result.material_version=after.version;result.after=after;
 assert.deepEqual(new Set(JSON.parse(response.request().postData()).part_ids),new Set(top.part_ids));assert.deepEqual(new Set(after.parts.filter(p=>p.material_signature!==before.parts.find(o=>o.id===p.id).material_signature).map(p=>p.id)),new Set(top.part_ids));
 assert.equal(after.editor_review_status,'unreviewed');result.checks.push('saved_material_changes_top_only_support_unchanged','saved_version_stays_unreviewed');
 await page.locator('.viewer-overlay').waitFor({state:'hidden'});await snap('material_top_only');
 await editor.getByRole('button',{name:'拆分部件',exact:true}).click();await editor.getByText('部件移动与单独导出',{exact:true}).click();
 for(const group of [top,support]){
  await editor.getByLabel('编辑范围',{exact:true}).selectOption('g:'+group.id);
  const download=page.waitForEvent('download');await editor.getByRole('button',{name:'单独导出选中部件',exact:true}).click();const file=path.join(folder,group.semantic_kind+'.glb');await(await download).saveAs(file);assert.equal((await fs.readFile(file)).subarray(0,4).toString(),'glTF');
 }
 result.checks.push('each_logical_part_downloaded_through_browser');
 assert.equal(hash(await(await page.request.get(base+before.original_url)).body()),originalHash);assert.equal(hash(await fs.readFile(path.join(source,'model.glb'))),originalHash);result.checks.push('original_and_experiment_model_bytes_unchanged');
 await page.screenshot({path:path.join(folder,'workbench.png'),fullPage:true});assert.deepEqual(result.page_errors,[]);
}catch(e){result.failure=e.stack;throw e;}finally{await fs.writeFile(path.join(folder,'review.json'),JSON.stringify(result,null,2));await browser.close();}
console.log(JSON.stringify({job:result.job,checks:result.checks,material_version:result.material_version}));

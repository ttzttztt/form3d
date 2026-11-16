import {chromium}from 'playwright';import fs from 'node:fs/promises';import path from 'node:path';import assert from 'node:assert/strict';
const folder=path.resolve(process.argv[2]);await fs.mkdir(folder,{recursive:false});const base='http://127.0.0.1:8001';
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});const result={errors:[],checks:[],mutations:0};
try{
 const page=await browser.newPage({viewport:{width:1600,height:1100}});page.setDefaultTimeout(120000);page.on('pageerror',e=>result.errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')result.mutations++;});
 await page.goto(base+'/?job=eb9c3008532b4a5099d020e680cdff1b',{waitUntil:'networkidle'});await page.locator('.viewer-overlay').waitFor({state:'hidden'});const editor=page.getByRole('region',{name:'部件与材质编辑'});
 await editor.getByText('已按生成计划分为 2 个部件候选。点击下方部件即可换材质；形状与隐藏结构仍需核对。',{exact:true}).waitFor();assert.equal(await editor.getByRole('button',{name:'AI 自动识别并分色',exact:true}).count(),0);
 await editor.getByRole('button',{name:'选择部件 桌面 1',exact:true}).click();assert.ok((await editor.getByLabel('编辑范围',{exact:true}).inputValue()).startsWith('g:'));
 await page.screenshot({path:path.join(folder,'planned_parts.png'),fullPage:true});await editor.getByRole('button',{name:'更多操作',exact:true}).click();await editor.getByRole('button',{name:'AI 自动识别并分色',exact:true}).waitFor();
 result.checks.push('native_parts_explain_existing_candidates_without_repeat_scan','planned_top_still_one_click_selectable','optional_rescan_available_in_more');
 await page.goto(base+'/?job=0ee3d49864e543bb92a66ad9cf19115b',{waitUntil:'networkidle'});await page.locator('.viewer-overlay').waitFor({state:'hidden'});await editor.getByRole('button',{name:'AI 自动识别并分色',exact:true}).waitFor();result.checks.push('legacy_sofa_keeps_default_ai_scan');
 assert.equal(result.mutations,0);assert.deepEqual(result.errors,[]);
}catch(e){result.failure=e.stack;throw e;}finally{await fs.writeFile(path.join(folder,'review.json'),JSON.stringify(result,null,2));await browser.close();}
console.log(JSON.stringify(result));

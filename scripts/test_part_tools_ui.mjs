import {chromium} from 'playwright';import fs from 'node:fs/promises';import path from 'node:path';import assert from 'node:assert/strict';
const folder=path.resolve('experiments/part_tools_20261112'),base='http://127.0.0.1:8001',cases=JSON.parse(await fs.readFile(path.join(folder,'cases.json'),'utf8'));
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});const result={errors:[],cases:[]};
try{const page=await browser.newPage({viewport:{width:1600,height:1080},acceptDownloads:true});page.setDefaultTimeout(180000);page.on('pageerror',e=>result.errors.push(e.message));
for(const c of cases){const record={case:c.case,job:c.job};result.cases.push(record);await page.goto(base+'/?job='+c.job,{waitUntil:'networkidle'});await page.locator('.viewer-overlay').waitFor({state:'hidden'});const view=page.getByTestId('model-viewer').first(),canvas=view.locator('canvas');await view.scrollIntoViewIfNeeded();await view.getByRole('button',{name:'AI 辅助选区',exact:true}).click();
 let response;for(const [x,y] of [[.5,.4],[.5,.5],[.5,.6],[.45,.55]]){
  const requested=page.waitForRequest(r=>r.url().endsWith('/asset/part-proposal'),{timeout:10000}).catch(()=>undefined),pending=page.waitForResponse(r=>r.url().endsWith('/asset/part-proposal'),{timeout:180000}).catch(()=>undefined);const rect=await canvas.boundingBox();await canvas.click({position:{x:rect.width*x,y:rect.height*y}});if(await requested){record.click=[x,y];response=await pending;break;}
 }
 if(response){const body=await response.json();record.response_status=response.status();record.sam=Object.fromEntries(Object.entries(body).filter(([key])=>key!=='masks'));await page.waitForFunction(()=>![...document.querySelectorAll('.face-tools [role=status]')].some(el=>el.textContent.includes('正在用本地 SAM')||el.textContent.includes('辅助分割进行中')),{},{timeout:180000});record.selected_faces=Number(await view.locator('.face-tools').getAttribute('data-selected-faces'));record.message=await view.locator('[role=status]').allTextContents();}else{record.no_request=true;record.message=await view.locator('[role=status]').allTextContents();}
 await view.screenshot({path:path.join(folder,c.case+'_sam.png')});await fs.writeFile(path.join(folder,'sam_browser.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(record));
 // A rejected proposal must preserve the original model and create no version.
 const catalog=await(await page.request.get(base+`/api/jobs/${c.job}/asset`)).json();assert.equal(catalog.versions.length,0);record.original_version_preserved=true;
}
assert.deepEqual(result.errors,[]);
}catch(e){result.failure=e.stack;throw e;}finally{await fs.writeFile(path.join(folder,'sam_browser.json'),JSON.stringify(result,null,2));await browser.close();}

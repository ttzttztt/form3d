// Real browser -> API -> Hunyuan CUDA inference -> validated GLB; no inference mocks.
import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';

const root=process.cwd();
const base=process.env.WORKBENCH_URL || 'http://127.0.0.1:8000';
const output=path.join(root,'experiments/quality_20261111');
const baseline=JSON.parse(await fs.readFile(path.join(output,'chair/triposr/job.json'),'utf8'));
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});
const page=await browser.newPage({viewport:{width:1440,height:1100}});
const errors=[];
page.on('pageerror',error=>errors.push(error.message));
try {
  await page.goto(base+'/?job='+baseline.id,{waitUntil:'networkidle'});
  await page.getByLabel('本地模型',{exact:true}).selectOption('hunyuan-mini');
  assert.ok((await page.locator('.local-note').innerText()).includes('不包含商品纹理'));
  await page.getByLabel('商品名称').fill('Hunyuan 几何实验 · 网页真实推理验收');
  const created=page.waitForResponse(response=>response.url().endsWith('/api/jobs') && response.request().method()==='POST');
  await page.locator('.generate-button').click();
  const response=await created;
  assert.equal(response.status(),202);
  let job=await response.json();
  assert.equal(job.request.local_engine,'hunyuan-mini');
  let stage;
  for(let tick=0;tick<300;tick++) {
    job=await (await page.request.get(base+'/api/jobs/'+job.id)).json();
    if(job.stage!==stage) {console.log(job.id.slice(0,8)+' '+job.status+' / '+job.stage);stage=job.stage;}
    if(!['queued','running'].includes(job.status)) break;
    await new Promise(resolve=>setTimeout(resolve,1000));
  }
  assert.equal(job.status,'awaiting_review',JSON.stringify(job));
  assert.equal(new URL(page.url()).searchParams.get('job'),job.id,'Current URL must identify the newly generated task');
  assert.equal(job.report.evidence.geometry_source,'hunyuan3d_2mini_image_to_shape');
  assert.equal(job.report.evidence.texture_source,'none_neutral_material');
  assert.equal(job.report.local_inference.model,'Hunyuan3D-2mini');
  assert.equal(job.report.local_inference.mode,'shape_only');
  assert.equal(job.report.gltf_validation.errors,0);
  assert.equal(job.report.checks.appearance,'needs_review');
  assert.ok(!job.events.some(event=>event.stage==='awaiting_assistant'));
  await page.locator('.viewer-canvas canvas').waitFor({timeout:30000});
  await page.locator('.viewer-overlay').waitFor({state:'hidden',timeout:30000});
  const link=page.getByRole('link',{name:/下载模型/});
  assert.equal(await link.getAttribute('href'),job.model_url);
  const model=await (await page.request.get(base+job.model_url)).body();
  assert.equal(model.subarray(0,4).toString(),'glTF');
  await page.screenshot({path:path.join(output,'web_hunyuan_desktop.png'),fullPage:true});
  await page.locator('.viewer').screenshot({path:path.join(output,'web_hunyuan_viewer.png')});
  await page.reload({waitUntil:'networkidle'});
  await page.waitForFunction(id=>document.querySelector('a[href="/api/jobs/'+id+'/files/model.glb"]'),job.id,{timeout:30000});
  await page.locator('.viewer-overlay').waitFor({state:'hidden',timeout:30000});
  assert.equal(await page.getByLabel('本地模型',{exact:true}).inputValue(),'hunyuan-mini');
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Mobile overflow');
  await page.screenshot({path:path.join(output,'web_hunyuan_mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  const result={status:'PASS',scope:'workflow and file validity, not product appearance acceptance',
    job_id:job.id,url:base+'/?job='+job.id,engine:job.request.local_engine,
    inference:job.report.local_inference,validation:job.report.gltf_validation,
    review_status:job.review_status,appearance_accepted:false,page_errors:errors};
  await fs.writeFile(path.join(output,'web_workflow.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify({status:result.status,job:job.id,url:result.url,appearance_accepted:false}));
} catch(error) {
  await page.screenshot({path:path.join(output,'web_hunyuan_failure.png'),fullPage:true}).catch(()=>{});
  await fs.writeFile(path.join(output,'web_workflow_last_failure.json'),JSON.stringify({
    status:'failed',scope:'browser workflow',error:String(error),appearance_accepted:false,
  },null,2));
  throw error;
} finally {await browser.close();}

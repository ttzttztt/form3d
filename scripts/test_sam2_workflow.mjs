// Real local SAM 2 + Hunyuan inference. No mocked model or review acceptance.
import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';

const base=process.env.WORKBENCH_URL || 'http://127.0.0.1:8000';
const output=path.resolve('experiments/segmentation_20261111');
await fs.mkdir(path.join(output,'armchair/web_run'),{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});
const page=await browser.newPage({viewport:{width:1440,height:1100}});
const errors=[];
page.on('pageerror',error=>errors.push(error.message));
let job;
try {
  if(process.env.SAM2_RESUME_JOB) {
    await page.goto(base+'/?job='+process.env.SAM2_RESUME_JOB,{waitUntil:'networkidle'});
    job=await (await page.request.get(base+'/api/jobs/'+process.env.SAM2_RESUME_JOB)).json();
  } else {
  await page.goto(base+'/?job=2a00fc53dc444a80afc11f902f98fe83',{waitUntil:'networkidle'});
  await page.getByLabel('本地模型',{exact:true}).selectOption('hunyuan-mini');
  await page.getByLabel('分割策略',{exact:true}).selectOption('auto');
  await page.getByLabel('商品名称').fill('SAM 2 分割实测 · 同图场景扶手椅');
  const created=page.waitForResponse(response=>response.url().endsWith('/api/jobs') && response.request().method()==='POST');
  await page.locator('.generate-button').click();
  const response=await created;
  assert.equal(response.status(),202);
  job=await response.json();
  await fs.writeFile(path.join(output,'active_job.json'),JSON.stringify(job,null,2));
  }
  assert.equal(job.request.local_segmentation,'auto');
  let previous;
  let maskVisibleDuringGeneration=false;
  for(let tick=0;tick<420;tick++) {
    job=await (await page.request.get(base+'/api/jobs/'+job.id)).json();
    if(job.stage!==previous) {console.log(job.id+' '+job.status+' / '+job.stage);previous=job.stage;}
    if(job.segmented_url && job.status==='running' && !maskVisibleDuringGeneration) {
      await page.getByAltText('目标主体精细分割结果').waitFor({timeout:15000});
      for(const key of ['segmented_url','segmentation_mask_url','segmentation_overlay_url']) {
        assert.equal((await page.request.get(base+job[key])).status(),200,key);
      }
      await page.screenshot({path:path.join(output,'web_mask_during_generation.png'),fullPage:true});
      maskVisibleDuringGeneration=true;
    }
    if(!['queued','running'].includes(job.status)) break;
    await new Promise(resolve=>setTimeout(resolve,1000));
  }
  assert.equal(job.status,'awaiting_review',JSON.stringify(job));
  assert.ok(maskVisibleDuringGeneration,'Mask should be reviewable while generating');
  assert.ok(job.events.some(e=>e.stage==='segment'));
  const local=job.report.local_inference;
  assert.equal(local.background_method,'sam2_box');
  assert.equal(local.generator_background_method,'provided_input_alpha');
  assert.equal(local.segmentation_selection.selected,'sam2');
  assert.equal(local.model,'Hunyuan3D-2mini');
  assert.equal(job.report.gltf_validation.errors,0);
  assert.equal(job.report.checks.appearance,'needs_review');
  assert.equal(new URL(page.url()).searchParams.get('job'),job.id);
  const folder=path.join(output,'armchair/web_run');
  for(const filename of ['model.glb','segmented.png','segmentation_mask.png','segmentation_overlay.png',
    'segmentation_summary.json','local_summary.json','foreground.png','model_input.png','prepared.png','quality_report.json']) {
    const artifact=await page.request.get(base+'/api/jobs/'+job.id+'/files/'+filename);
    assert.equal(artifact.status(),200,filename);
    await fs.writeFile(path.join(folder,filename),await artifact.body());
  }
  await fs.writeFile(path.join(folder,'job.json'),JSON.stringify(job,null,2));
  await page.locator('.viewer-overlay').waitFor({state:'hidden',timeout:30000});
  await page.screenshot({path:path.join(output,'web_sam2_desktop.png'),fullPage:true});
  await page.locator('.viewer').screenshot({path:path.join(output,'web_sam2_viewer.png')});
  await page.reload({waitUntil:'networkidle'});
  await page.waitForFunction(id=>document.querySelector('a[href="/api/jobs/'+id+'/files/model.glb"]'),job.id,{timeout:30000});
  assert.equal(await page.getByLabel('分割策略',{exact:true}).inputValue(),'auto');
  await page.getByAltText('目标主体精细分割结果').waitFor();
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Mobile overflow');
  await page.screenshot({path:path.join(output,'web_sam2_mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  const result={status:'PASS',scope:'real segmentation/inference workflow and file validity; not product acceptance',
    job_id:job.id,url:base+'/?job='+job.id,mask_visible_during_generation:maskVisibleDuringGeneration,
    inference:local,validation:job.report.gltf_validation,review_status:job.review_status,
    appearance_accepted:false,page_errors:errors};
  await fs.writeFile(path.join(output,'web_workflow.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify({status:'PASS',job_id:job.id,url:result.url}));
} catch(error) {
  await page.screenshot({path:path.join(output,'web_sam2_failure.png'),fullPage:true}).catch(()=>{});
  await fs.writeFile(path.join(output,'web_workflow_last_failure.json'),JSON.stringify({
    status:'failed',error:String(error),job_id:job?.id,appearance_accepted:false},null,2));
  throw error;
} finally {await browser.close();}

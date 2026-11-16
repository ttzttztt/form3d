// Real CUDA reconstruction test. No inference stubs, templates or paid APIs.
import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';

const base = process.env.WORKBENCH_URL || 'http://127.0.0.1:8000';
const root = process.cwd();
const output = path.join(root, '.data/checks/local3d-validation');
await fs.mkdir(output, {recursive: true});
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH,
  headless: true,
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-sandbox'],
});
const page = await browser.newPage({viewport:{width:1440, height:1100}});
const errors = [];
page.on('pageerror', error => errors.push(error.message));

async function finished(id) {
  let previous;
  for (let count = 0; count < 240; count++) {
    const response = await page.request.get(base + '/api/jobs/' + id);
    const job = await response.json();
    if (job.stage !== previous) {
      console.log(id.slice(0, 8) + ' ' + job.status + ' / ' + job.stage);
      previous = job.stage;
    }
    if (!['queued','running'].includes(job.status)) return job;
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  throw new Error('Local 3D task did not finish within 240 seconds');
}

async function checkResult(job) {
  assert.equal(job.status, 'awaiting_review', JSON.stringify(job));
  assert.equal(job.request.route, 'local');
  assert.ok(!job.events.some(event => event.stage === 'awaiting_assistant'));
  assert.equal(job.report.evidence.geometry_source, 'triposr_image_to_3d');
  assert.equal(job.report.gltf_validation.errors, 0);
  assert.equal(job.report.gltf_validation.warnings, 0);
  assert.equal(job.report.local_inference.offline, true);
  assert.equal(job.report.local_inference.color_encoding,'sRGB prediction converted to linear glTF vertex colors');
  assert.equal(job.provider_task_id, null);
  const response = await page.request.get(base + job.model_url);
  assert.equal(response.status(), 200);
  const model = await response.body();
  assert.equal(model.subarray(0,4).toString(), 'glTF');
  assert.equal(model.length, job.metrics.bytes);
  assert.ok(job.metrics.triangles > 1000);
  return model;
}

try {
  const config = await (await page.request.get(base + '/api/config')).json();
  assert.equal(config.providers.local.available, true);
  await page.goto(base, {waitUntil:'networkidle'});
  assert.ok((await page.locator('.local-route').getAttribute('class')).includes('chosen'));
  await page.getByTestId('image-upload').setInputFiles({
    name:'alien-table-local-test.png', mimeType:'image/png',
    buffer:await fs.readFile(path.join(root,'.data/images/44d71e2eda144ab3b53e71df0d5fdd59/normalized.png')),
  });
  await page.locator('.image-editor canvas').waitFor();
  // The unusual character's low-score class is irrelevant to a whole-product test.
  await page.getByRole('button',{name:'重置选区和擦除', exact:true}).click();
  await page.getByLabel('商品名称').fill('三眼造型桌 · 本地自动生成验收');
  const creation = page.waitForResponse(response => response.url().endsWith('/api/jobs') && response.request().method()==='POST');
  await page.getByRole('button',{name:'开始生成', exact:true}).click();
  const submitted = await (await creation).json();
  assert.equal(submitted.request.route,'local');
  assert.equal(submitted.request.target.width,1);
  const alien = await finished(submitted.id);
  const alienBytes = await checkResult(alien);
  assert.equal(alien.report.local_inference.background_method,'white_background_connected_components');
  await page.locator('.viewer-canvas canvas').waitFor({timeout:30000});
  await page.locator('.viewer-overlay').waitFor({state:'hidden',timeout:30000});
  await page.screenshot({path:path.join(output,'alien-workbench.png'),fullPage:true});
  await page.locator('.viewer').screenshot({path:path.join(output,'alien-viewer.png')});
  await page.getByRole('button',{name:'图片对照',exact:false}).click();
  assert.equal(await page.locator('.comparison-image img').getAttribute('src'),alien.model_input_url);
  await page.reload({waitUntil:'networkidle'});
  await page.locator('.viewer-overlay').waitFor({state:'hidden',timeout:30000});
  assert.equal(await page.getByRole('link',{name:/下载模型/}).getAttribute('href'),alien.model_url);
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:path.join(output,'mobile-workbench.png'),fullPage:true});
  await page.setViewportSize({width:1440,height:1100});

  // Start a real worker, cancel during import/loading and prove the GPU queue
  // can subsequently make progress. Only this test's task is cancelled.
  const cancel = await (await page.request.post(base+'/api/jobs',{data:{
    image_id:alien.request.image_id,route:'local',name:'本地推理取消验收',
  }})).json();
  for(let count=0;count<90;count++) {
    const current=await (await page.request.get(base+'/api/jobs/'+cancel.id)).json();
    if(current.events.some(event=>event.stage==='loading')) break;
    if(count===89) throw new Error('Cancellation fixture did not start');
    await new Promise(resolve=>setTimeout(resolve,500));
  }
  assert.equal((await page.request.post(base+'/api/jobs/'+cancel.id+'/cancel')).status(),200);
  assert.equal((await (await page.request.get(base+'/api/jobs/'+cancel.id)).json()).status,'cancelled');
  assert.equal((await page.request.get(base+'/api/jobs/'+cancel.id+'/files/model.glb')).status(),409);

  const upload = await page.request.post(base+'/api/images',{multipart:{file:{
    name:'TripoSR-official-chair-example.png', mimeType:'image/png',
    buffer:await fs.readFile(path.join(root,'.tools/TripoSR/examples/chair.png')),
  }}});
  assert.equal(upload.status(),201);
  const source=await upload.json();
  const second=await page.request.post(base+'/api/jobs',{data:{
    image_id:source.id,route:'local',name:'官方椅子示例 · 本地自动生成验收',
  }});
  assert.equal(second.status(),202);
  const chair=await finished((await second.json()).id);
  const chairBytes=await checkResult(chair);
  assert.notDeepEqual(alienBytes,chairBytes);
  assert.notEqual(alien.report.local_inference.model_input_sha256,chair.report.local_inference.model_input_sha256);
  await page.goto(base+'/?job='+chair.id,{waitUntil:'networkidle'});
  await page.locator('.viewer-canvas canvas').waitFor({timeout:30000});
  await page.locator('.viewer-overlay').waitFor({state:'hidden',timeout:30000});
  await page.screenshot({path:path.join(output,'chair-workbench.png'),fullPage:true});
  await page.locator('.viewer').screenshot({path:path.join(output,'chair-viewer.png')});
  assert.deepEqual(errors,[]);
  const result={status:'PASS',model:'TripoSR',cancelled_task:cancel.id,
    cancelled_worker_releases_gpu:true, browser_errors:errors,
    jobs:[alien,chair].map(job=>({id:job.id,name:job.name,metrics:job.metrics,
      duration_seconds:job.report.local_inference.duration_seconds,
      peak_vram_mb:job.report.local_inference.peak_vram_mb,
      background_method:job.report.local_inference.background_method,
      url:base+'/?job='+job.id}))};
  await fs.writeFile(path.join(output,'result.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result,null,2));
} catch(error) {
  await page.screenshot({path:path.join(output,'failure.png'),fullPage:true}).catch(()=>{});
  throw error;
} finally {
  await browser.close();
}

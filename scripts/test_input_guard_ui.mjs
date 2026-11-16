// Actual blocked API jobs; no inference fixtures or fabricated acceptance.
import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';

const folder=path.resolve('experiments/input_guard_20261111');
const base='http://127.0.0.1:8000';
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1100}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const ids=['scene_cabinet','scene_sofa_cat','scene_table_glass','scene_vase_flowers','scene_plant_small'];
  const checks=[];
  for(const id of ids) {
    const execution=JSON.parse(await fs.readFile(path.join(folder,'batch',id,'execution.json'),'utf8'));
    const job=await (await page.request.get(base+'/api/jobs/'+execution.job_id)).json();
    assert.equal(job.status,'awaiting_input');assert.equal(job.attention_kind,'local_input');
    assert.ok(!job.model_url);
    assert.equal((await page.request.get(base+'/api/jobs/'+job.id+'/files/model.glb')).status(),409);
    assert.equal((await page.request.get(base+job.cleaned_url)).status(),200);
    assert.equal((await page.request.get(base+job.input_quality_url)).status(),200);
    assert.ok(!job.events.some(event=>event.stage==='inference'));
    checks.push({id,job_id:job.id,model_blocked:true,input_evidence_accessible:true});
  }
  const selected=checks.find(check=>check.id==='scene_sofa_cat');
  await page.goto(base+'/?job='+selected.job_id,{waitUntil:'networkidle'});
  await page.getByText('本次未生成模型',{exact:true}).waitFor();
  await page.getByAltText('清理后的建模输入').waitFor();
  assert.equal(await page.getByRole('link',{name:/下载模型/}).count(),0);
  await page.screenshot({path:path.join(folder,'blocked_desktop.png'),fullPage:true});
  await page.reload({waitUntil:'networkidle'});
  await page.getByText('本次未生成模型',{exact:true}).waitFor();
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Blocked UI mobile overflow');
  await page.screenshot({path:path.join(folder,'blocked_mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  await fs.writeFile(path.join(folder,'web_blocked_validation.json'),JSON.stringify({status:'PASS',checks,refresh_restored:true,mobile_overflow:false,page_errors:errors,scope:'actual input gate and UI; not model accuracy'},null,2));
  console.log('PASS: 5 real jobs blocked model access; UI restored after refresh, mobile layout verified');
} finally {await browser.close();}

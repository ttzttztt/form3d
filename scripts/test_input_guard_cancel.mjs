// Cancel a real OCR/preflight child before shape inference.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const base='http://127.0.0.1:8000';
async function call(url,options){const response=await fetch(base+url,options);assert.ok(response.ok,await response.clone().text());return response.json();}
const baseline=JSON.parse(await fs.readFile('experiments/input_guard_20261111/batch/clean_plant/job.json','utf8'));
let job=await call('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...baseline.request,name:'输入检查阶段真实取消验收'})});
let observed=false;
for(let i=0;i<160;i++){
 job=await call('/api/jobs/'+job.id);
 if(job.stage==='input_check'){observed=true;break;}
 assert.ok(['queued','running'].includes(job.status));
 await new Promise(resolve=>setTimeout(resolve,150));
}
assert.ok(observed,'Did not observe actual input_check stage');
await new Promise(resolve=>setTimeout(resolve,400));
await call('/api/jobs/'+job.id+'/cancel',{method:'POST'});
await new Promise(resolve=>setTimeout(resolve,4000));
job=await call('/api/jobs/'+job.id);
assert.equal(job.status,'cancelled');assert.ok(!job.model_url);
assert.equal(await fetch(base+'/api/jobs/'+job.id+'/files/model.glb').then(r=>r.status),409);
assert.ok(!job.events.some(e=>e.stage==='inference'));
const result={status:'PASS',scope:'Real input-check cancellation, no shape inference or GLB publication',job_id:job.id,events:job.events};
await fs.writeFile('experiments/input_guard_20261111/cancellation.json',JSON.stringify(result,null,2));
console.log(JSON.stringify(result));

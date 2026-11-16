import fs from'node:fs/promises';import path from'node:path';import assert from'node:assert/strict';import validator from'gltf-validator';
const out=path.resolve('experiments/solid_parts_20261113'),verification=JSON.parse(await fs.readFile(path.join(out,'verification.json'),'utf8')),files=[];
for(const c of verification){files.push(c.source);for(const g of c.groups)files.push(path.join(out,g.export));}
files.push(path.join(out,'final_ui_verified/browser_solid_bolster.glb'));
const records=[];
for(const file of files){const r=await validator.validateBytes(new Uint8Array(await fs.readFile(file)),{uri:path.basename(file),maxIssues:30,externalResourceFunction:()=>Promise.reject(new Error('external resources forbidden'))});records.push({file:path.relative(out,file).replaceAll('\\','/'),errors:r.issues.numErrors,warnings:r.issues.numWarnings,messages:r.issues.messages});await fs.writeFile(path.join(out,'gltf_validation.json'),JSON.stringify(records,null,2));assert.equal(r.issues.numErrors,0,file);assert.equal(r.issues.numWarnings,0,file);}
console.log(JSON.stringify({files:records.length,errors:0,warnings:0}));

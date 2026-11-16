// Independent brute-force three.js rays; deliberately does not import the BVH selector.
import * as THREE from 'three';
import {GLTFLoader} from 'three/examples/jsm/loaders/GLTFLoader.js';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const folder=path.resolve('experiments/selection_ux_20261112'),base='http://127.0.0.1:8000';
const cases=JSON.parse(await fs.readFile(path.join(folder,'cases.json'),'utf8'));const job=cases[0].job;
const catalog=await(await fetch(`${base}/api/jobs/${job}/asset`)).json();
const bytes=await(await fetch(base+catalog.model_url)).arrayBuffer();
const gltf=await new Promise((resolve,reject)=>new GLTFLoader().parse(bytes,'',resolve,reject));
const model=gltf.scene;model.updateMatrixWorld(true);const bounds=new THREE.Box3().setFromObject(model),size=bounds.getSize(new THREE.Vector3()),center=bounds.getCenter(new THREE.Vector3());
model.position.sub(new THREE.Vector3(center.x,bounds.min.y,center.z));model.updateMatrixWorld(true);
const radius=Math.max(size.x,size.y,size.z),origin=new THREE.Vector3(radius*1.65,size.y*.6+radius*.95,radius*2.15),points=[];
model.traverse(child=>{
 if(!(child instanceof THREE.Mesh))return;
 const materials=Array.isArray(child.material)?child.material:[child.material];for(const material of materials)material.side=THREE.DoubleSide;
 if(!materials.some(m=>m.color.r>m.color.g*2))return;
 const p=child.geometry.getAttribute('position'),index=child.geometry.index,a=new THREE.Vector3(),b=new THREE.Vector3(),c=new THREE.Vector3();
 for(let face=0;face<(index?.count??p.count)/3;face++){
  a.fromBufferAttribute(p,index?index.getX(face*3):face*3);b.fromBufferAttribute(p,index?index.getX(face*3+1):face*3+1);c.fromBufferAttribute(p,index?index.getX(face*3+2):face*3+2);
  points.push({face,point:a.clone().add(b).add(c).multiplyScalar(1/3).applyMatrix4(child.matrixWorld)});
 }
});
points.sort((a,b)=>a.point.y-b.point.y);
const samples=[...points.slice(0,30),...Array.from({length:30},(_,i)=>points[Math.floor(i*(points.length-1)/29)])];
const ray=new THREE.Raycaster(),direction=new THREE.Vector3(),checks=[];
for(const sample of samples){direction.copy(sample.point).sub(origin).normalize();ray.set(origin,direction);const hit=ray.intersectObject(model,true)[0];const distance=origin.distanceTo(sample.point);checks.push({face:sample.face,height:sample.point.y,distance_error:hit?Math.abs(hit.distance-distance):null,visible:!!hit&&Math.abs(hit.distance-distance)<=radius*2e-6});}
const result={job,version:catalog.version,selected_triangles:points.length,sample_rule:'30 lowest-height selected face centroids and 30 evenly spaced height-order samples',checked:checks.length,hidden_samples:checks.filter(c=>!c.visible).length,checks};
await fs.writeFile(path.join(folder,'independent_visibility.json'),JSON.stringify(result,null,2));assert.equal(result.hidden_samples,0,JSON.stringify(result));console.log(JSON.stringify({checked:result.checked,hidden_samples:result.hidden_samples,version:result.version}));

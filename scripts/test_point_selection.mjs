import {build} from 'esbuild';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const folder=path.resolve('experiments/point_selection_20261112');await fs.mkdir(folder,{recursive:true});
const bundle=await build({stdin:{contents:"export * from './apps/web/src/pointSelection'; export * as THREE from 'three'; export {GLTFLoader} from 'three/examples/jsm/loaders/GLTFLoader.js'; export {mergeGeometries} from 'three/examples/jsm/utils/BufferGeometryUtils.js';",resolveDir:process.cwd(),loader:'ts'},bundle:true,platform:'node',format:'esm',write:false});
const {THREE,pointSelection,GLTFLoader,mergeGeometries}=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
const results=[];
function mesh(geometry){const value=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial());value.userData.formPartId='part';value.updateMatrixWorld(true);return value;}
function normalsAndCenter(value,face){const p=value.geometry.getAttribute('position'),idx=value.geometry.index,a=new THREE.Vector3(),b=new THREE.Vector3(),c=new THREE.Vector3();a.fromBufferAttribute(p,idx?idx.getX(face*3):face*3);b.fromBufferAttribute(p,idx?idx.getX(face*3+1):face*3+1);c.fromBufferAttribute(p,idx?idx.getX(face*3+2):face*3+2);return{center:a.clone().add(b).add(c).multiplyScalar(1/3).applyMatrix4(value.matrixWorld),normal:b.sub(a).cross(c.sub(a)).applyMatrix3(new THREE.Matrix3().getNormalMatrix(value.matrixWorld)).normalize()};}
function record(name,fn){try{const value=fn();results.push({name,status:'pass',...value});}catch(error){results.push({name,status:'fail',error:String(error)});throw error;}}
try{
 record('disconnected_piece_in_one_primitive',()=>{const value=mesh(mergeGeometries([new THREE.BoxGeometry(1,1,1),new THREE.BoxGeometry(1,1,1).translate(3,0,0)]));const r=pointSelection(value,0);assert.equal(r.kind,'component');assert.equal(r.count,12);return{kind:r.kind,count:r.count};});
 record('indexed_cube_seed_face_zero',()=>{const value=mesh(new THREE.BoxGeometry(1,1,1)),before=Array.from(value.geometry.index.array);const r=pointSelection(value,0);assert.equal(r.kind,'plane');assert.equal(r.count,2);assert.deepEqual(Array.from(value.geometry.index.array),before);return{count:r.count,index_unchanged:true};});
 record('nonindexed_uv_seams_and_transform',()=>{const value=mesh(new THREE.BoxGeometry(1,1,1).toNonIndexed());value.scale.set(-2,.7,1.2);value.rotation.set(.4,.2,.6);value.updateMatrixWorld(true);const r=pointSelection(value,4);assert.equal(r.kind,'plane');assert.equal(r.count,2);assert.equal(value.geometry.index,null);return{count:r.count,nonindexed_preserved:true};});
 record('connected_table_plane_stops_at_downward_join',()=>{const geometry=new THREE.PlaneGeometry(2,2,20,20).rotateX(-Math.PI/2),p=geometry.getAttribute('position');for(let i=0;i<p.count;i++){const radius=Math.max(Math.abs(p.getX(i)),Math.abs(p.getZ(i)));p.setY(i,radius<.3?-.6*(1-radius/.3):0);}const value=mesh(geometry),seed=0,r=pointSelection(value,seed);assert.equal(r.kind,'plane');assert.ok(r.count>500);const minimum=Math.min(...r.faces.part.map(f=>normalsAndCenter(value,f).center.y));assert.ok(minimum>-.02);return{count:r.count,minimum_y:minimum};});
 record('organic_sphere_refuses_fake_whole_part',()=>{const value=mesh(new THREE.IcosahedronGeometry(1,4));assert.throws(()=>pointSelection(value,0),/没有清晰/);return{refused:true};});
 record('invalid_seed_keeps_geometry',()=>{const value=mesh(new THREE.BoxGeometry(1,1,1));assert.throws(()=>pointSelection(value,-1),/失效/);assert.throws(()=>pointSelection(value,1000),/失效/);return{invalid_seeds_refused:true};});
 await fs.writeFile(path.join(folder,'controls.json'),JSON.stringify(results,null,2));
 const cases=[['table','b51be48468e54d0680a542174c0c873b'],['cabinet','212518024ebe4a4b9e4bd3543ee4a13c'],['sofa','11c5d7496508427cad48c22c5959f53b'],['vase','98b4389eb9e240cab5aa94934e089b6f']];
 const real=[];
 for(const[name,id]of cases){
  const bytes=await fs.readFile(path.resolve('.data/jobs',id,'model.glb'));const gltf=await new Promise((resolve,reject)=>new GLTFLoader().parse(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),'',resolve,reject));gltf.scene.updateMatrixWorld(true);
  const meshes=[];gltf.scene.traverse(child=>{if(child instanceof THREE.Mesh){child.userData.formPartId='part_'+meshes.length;meshes.push(child);}});
  const value=meshes[0],count=(value.geometry.index?.count??value.geometry.getAttribute('position').count)/3;
  const positionsBefore=Buffer.from(value.geometry.getAttribute('position').array.buffer).toString('base64'),indicesBefore=value.geometry.index?Buffer.from(value.geometry.index.array.buffer).toString('base64'):null;
  // Pick reproducible surfaces. Table uses its top centre; other samples use a central front-facing plane candidate.
  const bounds=new THREE.Box3().setFromObject(value),size=bounds.getSize(new THREE.Vector3()),center=bounds.getCenter(new THREE.Vector3());let seed=-1,score=Infinity;
  for(let f=0;f<count;f++){const item=normalsAndCenter(value,f);if(name==='table'){if(item.normal.y<.95||item.center.y<bounds.max.y-size.y*.05)continue;const q=(item.center.x-center.x)**2+(item.center.z-center.z)**2;if(q<score){score=q;seed=f;}}else{if(item.normal.z<.9)continue;const q=(item.center.x-center.x)**2+(item.center.y-center.y)**2;if(q<score){score=q;seed=f;}}}
  const start=performance.now();let result;
  try{const proposal=pointSelection(value,seed);const selected=proposal.faces[value.userData.formPartId],chosen=new THREE.Box3();for(const f of selected)chosen.expandByPoint(normalsAndCenter(value,f).center);result={case:name,source_job:id,seed,status:'proposal',kind:proposal.kind,count:proposal.count,centroid_bounds:[chosen.min.toArray(),chosen.max.toArray()],message:proposal.message};if(name==='table'){assert.equal(proposal.kind,'plane');assert.ok(chosen.min.y>bounds.max.y-size.y*.05);assert.ok(proposal.count>1000);}}
  catch(error){result={case:name,source_job:id,seed,status:'refused',message:String(error)};if(name==='table')throw error;}
  assert.equal(Buffer.from(value.geometry.getAttribute('position').array.buffer).toString('base64'),positionsBefore);assert.equal(value.geometry.index?Buffer.from(value.geometry.index.array.buffer).toString('base64'):null,indicesBefore);
  real.push({...result,seconds:(performance.now()-start)/1000,source_geometry_unchanged:true});await fs.writeFile(path.join(folder,'real_proposals.json'),JSON.stringify(real,null,2));console.log(JSON.stringify(real[real.length-1]));
 }
}finally{await fs.writeFile(path.join(folder,'controls.json'),JSON.stringify(results,null,2));}
console.log(JSON.stringify(results));

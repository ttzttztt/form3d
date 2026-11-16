import {build} from 'esbuild';
import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const folder=path.resolve('.data/checks/test_visible_selection');await fs.mkdir(folder,{recursive:true});
const bundle=await build({stdin:{contents:"export * from './apps/web/src/faceSelection'; export * as THREE from 'three';",resolveDir:process.cwd(),loader:'ts'},bundle:true,format:'iife',globalName:'SelectionTest',write:false});
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH,headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});
try{
const page=await browser.newPage();await page.setContent('<canvas id="test"></canvas>');await page.addScriptTag({content:bundle.outputFiles[0].text});
const results=await page.evaluate(()=>{
 const {THREE,screenFaces,combineFaces}=SelectionTest;
 const renderer=new THREE.WebGLRenderer({canvas:document.getElementById('test'),preserveDrawingBuffer:true});renderer.setSize(512,512);
 const group=new THREE.Group();
 const top=new THREE.Mesh(new THREE.BoxGeometry(2,.12,2),new THREE.MeshBasicMaterial({color:0xb38663}));top.position.y=1;top.userData.formPartId='top';group.add(top);
 const leg=new THREE.Mesh(new THREE.BoxGeometry(.35,1,.35),new THREE.MeshBasicMaterial({color:0xaaaaaa}));leg.position.y=.5;leg.userData.formPartId='leg';group.add(leg);
 const outside=new THREE.Mesh(new THREE.BoxGeometry(.2,.4,.2),new THREE.MeshBasicMaterial());outside.position.set(1.3,.2,0);outside.userData.formPartId='outside';group.add(outside);
 const scene=new THREE.Scene();scene.add(group);const results=[];const before=group.children.map(m=>Array.from(m.geometry.index.array));
 for(const perspective of [false,true]){
 const camera=perspective?new THREE.PerspectiveCamera(40,1,.01,100):new THREE.OrthographicCamera(-1.6,1.6,1.6,-1.6,.01,100);camera.position.set(0,5,0);camera.up.set(0,0,-1);camera.lookAt(0,0,0);camera.updateMatrixWorld(true);camera.updateProjectionMatrix();
 for(const box of [false,true]){
   const points=box?[{x:80,y:80},{x:432,y:432}]:[{x:256,y:256}];

   const visible=screenFaces(group,camera,512,512,points,box,180,true),through=screenFaces(group,camera,512,512,points,box,180,false);
   results.push({name:`${perspective?'perspective':'orthographic'}_${box?'box':'brush'}`,visible,through,leg_hidden:!visible.leg,top_selected:!!visible.top,through_selects_leg:!!through.leg});
 }
 // A separate exposed object remains selectable; visibility does not ban all lower parts.

 const exposed=screenFaces(group,camera,512,512,[{x:0,y:0},{x:512,y:512}],true,24,true);results.push({name:`exposed_${perspective}`,outside_selected:!!exposed.outside});
 }
 // Slope correction and transformed hierarchy: overlapping parallel plates.
 const sloped=new THREE.Group();const front=new THREE.Mesh(new THREE.PlaneGeometry(2,2,8,8).toNonIndexed(),new THREE.MeshBasicMaterial({side:THREE.DoubleSide}));front.userData.formPartId='front';sloped.add(front);
 const back=front.clone();back.userData={formPartId:'back'};back.position.z=-.03;sloped.add(back);sloped.rotation.set(.4,.3,.2);sloped.scale.set(1.2,.7,1);sloped.position.set(.2,-.1,0);
 const camera=new THREE.PerspectiveCamera(40,1,.01,100);camera.position.set(0,0,5);camera.lookAt(0,0,0);camera.updateMatrixWorld(true);
 const visible=screenFaces(sloped,camera,512,512,[{x:170,y:170},{x:330,y:330}],true,24,true);
 results.push({name:'geometry_indices_preserved',indexed_unchanged:JSON.stringify(before)===JSON.stringify(group.children.map(m=>Array.from(m.geometry.index.array))),nonindexed_unchanged:front.geometry.index===null});
 results.push({name:'sloped_transformed',front_selected:!!visible.front,back_hidden:!visible.back,visible});
 const subtracted=combineFaces({top:[1,2],leg:[3]},{top:[2],leg:[3]},true);results.push({name:'subtract_keeps_other_faces',result:subtracted});
 renderer.dispose();renderer.forceContextLoss();return results;
});
await fs.writeFile(path.join(folder,'visible_selection_controls.json'),JSON.stringify(results,null,2));
for(const r of results){if('leg_hidden' in r){assert.equal(r.leg_hidden,true,r.name);assert.equal(r.top_selected,true,r.name);assert.equal(r.through_selects_leg,true,r.name);}if('outside_selected'in r)assert.equal(r.outside_selected,true,r.name);if('front_selected'in r){assert.equal(r.front_selected,true);assert.equal(r.back_hidden,true);}if(r.name==='subtract_keeps_other_faces')assert.deepEqual(r.result,{top:[1]});if(r.name==='geometry_indices_preserved'){assert.equal(r.indexed_unchanged,true);assert.equal(r.nonindexed_unchanged,true);}}
console.log(JSON.stringify(results));
}finally{await browser.close();}

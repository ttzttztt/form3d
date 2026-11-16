// Independent GLTFLoader render of actual exported bytes. No material overrides.
import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
const root=process.cwd(),out=path.join(root,'experiments/autonomous_upgrade_20261113'),detailTag=process.env.UPGRADE_DETAIL_TAG||'';
const cases=JSON.parse(await fs.readFile(path.join(out,'cases.json'),'utf8'));
const matrix=JSON.parse(await fs.readFile(path.join(out,'static_material_matrix_reviewed.json'),'utf8').catch(()=> '[]'));
await fs.mkdir(path.join(out,'renders'),{recursive:true});
const records=JSON.parse(await fs.readFile(path.join(out,'render_records.json'),'utf8').catch(()=> '[]'));
const files=new Map(),queue=[];
if(process.env.UPGRADE_SYNTHETIC_MODEL)files.set('synthetic_complete_sofa',path.resolve(process.env.UPGRADE_SYNTHETIC_MODEL));
if(process.env.UPGRADE_DETAIL_MODEL)files.set('detail_part',path.resolve(process.env.UPGRADE_DETAIL_MODEL));
for(const c of cases){
 if(!c.source_model)continue;
 const m=matrix.find(r=>r.case===c.case&&!r.failure);
 const stages=[['original',path.resolve(c.source_model)]];
 if(m){
  if(m.simplification.status==='saved')stages.push(['simplified',path.join(root,'.data/jobs',m.job,'assets',m.simplification.version,'model.glb')]);
  stages.push(['local_material',path.join(root,'.data/jobs',m.job,'assets',m.local_material_version,'model.glb')],['whole_material',path.join(root,'.data/jobs',m.job,'assets',m.whole_material_version,'model.glb')]);
 }
 for(const [stage,file]of stages){const id=c.case+'__'+stage;files.set(id,file);queue.push({case:c.case,title:c.title,stage,id,file,original:c.case+'__original'});}
}
const html=`<!doctype html><meta charset="utf-8"><style>body{margin:0}canvas{display:block}</style><script type="importmap">{"imports":{"three":"/three/build/three.module.js"}}</script><script type="module">
import * as THREE from 'three';import {GLTFLoader}from '/three/examples/jsm/loaders/GLTFLoader.js';import {RoomEnvironment}from '/three/examples/jsm/environments/RoomEnvironment.js';
const renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true,alpha:true});renderer.setClearAlpha(0);renderer.setSize(480,480);renderer.setPixelRatio(1);renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;document.body.appendChild(renderer.domElement);
const pmrem=new THREE.PMREMGenerator(renderer);const env=pmrem.fromScene(new RoomEnvironment(),.04).texture;const loader=new GLTFLoader();let old;
window.drawAsset=async(id,bounds,direction=[1.5,.85,2.1],width=480,synthetic=false)=>{if(old){old.traverse(o=>{if(o.isMesh){o.geometry.dispose();for(const m of Array.isArray(o.material)?o.material:[o.material]){for(const v of Object.values(m))if(v?.isTexture)v.dispose();m.dispose();}}});}
const gltf=await loader.loadAsync('/asset/'+encodeURIComponent(id));old=gltf.scene;const box=new THREE.Box3().setFromObject(old);const norm=bounds||{min:box.min.toArray(),max:box.max.toArray()};const shared=new THREE.Box3(new THREE.Vector3(...norm.min),new THREE.Vector3(...norm.max)),center=shared.getCenter(new THREE.Vector3()),extent=shared.getSize(new THREE.Vector3()),scale=1/Math.max(...extent.toArray());
const group=new THREE.Group();group.add(old);group.scale.setScalar(scale);group.position.copy(center).multiplyScalar(-scale);const scene=new THREE.Scene();scene.background=synthetic?null:new THREE.Color('#edf0f4');if(synthetic)old.traverse(o=>{if(o.isMesh)o.material=new THREE.MeshStandardMaterial({color:'#a97847',roughness:.7});});scene.environment=env;scene.add(group);scene.add(new THREE.HemisphereLight(0xffffff,0x64748b,1.4));const light=new THREE.DirectionalLight(0xffffff,2);light.position.set(-2,4,4);scene.add(light);const camera=synthetic==='perspective'?new THREE.PerspectiveCamera(35,1,.001,20):new THREE.OrthographicCamera(-.72,.72,.72,-.72,.001,20);camera.position.fromArray(direction).normalize().multiplyScalar(synthetic==='perspective'?2.8:3);camera.lookAt(0,0,0);renderer.setSize(width,width);renderer.render(scene,camera);let textures=0,meshes=0;old.traverse(o=>{if(o.isMesh){meshes++;for(const m of Array.isArray(o.material)?o.material:[o.material])if(m.map)textures++;}});return{bounds:norm,meshes,textured_material_uses:textures,draw_calls:renderer.info.render.calls,triangles:renderer.info.render.triangles,camera_direction:direction};};window.renderReady=true;
</script>`;
const server=http.createServer(async(req,res)=>{try{
 const url=new URL(req.url,'http://127.0.0.1');
 if(url.pathname==='/'){res.setHeader('Content-Type','text/html');res.end(html);return;}
 let file;
 if(url.pathname.startsWith('/asset/'))file=files.get(decodeURIComponent(url.pathname.slice(7)));
 else if(url.pathname.startsWith('/three/')){const base=path.join(root,'node_modules/three');const candidate=path.resolve(base,url.pathname.slice(7));if(candidate.startsWith(base+path.sep))file=candidate;}
 if(!file){res.statusCode=404;res.end();return;}
 res.setHeader('Content-Type',file.endsWith('.js')?'application/javascript':'model/gltf-binary');res.end(await fs.readFile(file));
}catch(e){res.statusCode=500;res.end(String(e));}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});
try{
 const page=await browser.newPage({viewport:{width:480,height:480}});page.setDefaultTimeout(120000);const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:'+server.address().port);await page.waitForFunction(()=>window.renderReady);
 for(const row of process.argv.includes('--synthetic-only')||process.argv.includes('--detail-only')?[]:queue){
  const sha=crypto.createHash('sha256').update(await fs.readFile(row.file)).digest('hex');
  if(records.some(r=>r.id===row.id&&r.sha256===sha))continue;
  const original=records.find(r=>r.id===row.original);const stats=await page.evaluate(async({id,bounds})=>window.drawAsset(id,bounds),{id:row.id,bounds:original?.stats.bounds});
  assert.ok(stats.meshes>0&&stats.triangles>0);const image='renders/'+row.id+(records.some(r=>r.id===row.id)?'__'+sha.slice(0,10):'')+'.png';await page.locator('canvas').screenshot({path:path.join(out,image)});
  records.push({...row,file:path.relative(root,row.file),image,sha256:sha,stats,material_override:false,camera_matched_to_reference_photo:false,physical_appearance_accepted:false});await fs.writeFile(path.join(out,'render_records.json'),JSON.stringify(records,null,2));console.log(row.id,stats.triangles,stats.textured_material_uses);
 }
 // Supplemental-view regression input is explicitly a render, never a second real photo.
 const leather=files.get('leather_sofa__original');if(leather){const stats=await page.evaluate(()=>window.drawAsset('leather_sofa__original',null,[.8,.7,2.5],768,true));await page.setViewportSize({width:768,height:768});await page.locator('canvas').screenshot({path:path.join(out,'synthetic_leather_oblique_v2.png'),omitBackground:true});await fs.writeFile(path.join(out,'synthetic_leather_oblique_v2_provenance.json'),JSON.stringify({source:path.relative(root,leather),kind:'synthetic_render_regression',material_override:true,geometry_unchanged:true,real_product_photo:false,...stats},null,2));}
 if(files.has('synthetic_complete_sofa')){const stats=await page.evaluate(()=>window.drawAsset('synthetic_complete_sofa',null,[.8,.7,2.5],768,true));await page.locator('canvas').screenshot({path:path.join(out,'synthetic_complete_sofa.png'),omitBackground:true});await fs.writeFile(path.join(out,'synthetic_complete_sofa_provenance.json'),JSON.stringify({source:path.relative(root,files.get('synthetic_complete_sofa')),kind:'synthetic_render_regression',material_override:true,geometry_unchanged:true,real_product_photo:false,...stats},null,2));}
 if(files.has('synthetic_complete_sofa')){
  const stats=await page.evaluate(()=>window.drawAsset('synthetic_complete_sofa',null,[.460530497,.389418342,.797662219],768,'perspective'));
  await page.locator('canvas').screenshot({path:path.join(out,'synthetic_complete_sofa_perspective.png'),omitBackground:true});
  await fs.writeFile(path.join(out,'synthetic_complete_sofa_perspective_provenance.json'),JSON.stringify({source:path.relative(root,files.get('synthetic_complete_sofa')),kind:'synthetic_render_regression',material_override:true,geometry_unchanged:true,real_product_photo:false,camera_model:'perspective_35_degrees',...stats},null,2));
 }
 if(files.has('detail_part')){
  const detail=[];
  for(const [name,direction]of [['front',[0,.15,2]],['side',[2,.15,0]],['back',[0,.15,-2]],['bottom',[0,-2,.05]]]){
   const stats=await page.evaluate(({direction})=>window.drawAsset('detail_part',null,direction,600,false),{direction});await page.setViewportSize({width:600,height:600});const filename='ui/textured_part_'+name+(detailTag?'_'+detailTag:'')+'.png';await page.locator('canvas').screenshot({path:path.join(out,filename)});detail.push({view:name,filename,stats,material_override:false,source:path.relative(root,files.get('detail_part')),source_sha256:crypto.createHash('sha256').update(await fs.readFile(files.get('detail_part'))).digest('hex')});
  }
  await fs.writeFile(path.join(out,'textured_part_views'+(detailTag?'_'+detailTag:'')+'.json'),JSON.stringify(detail,null,2));
 }
 assert.deepEqual(errors,[]);
}finally{await browser.close();await new Promise(r=>server.close(r));}

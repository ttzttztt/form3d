# -*- coding: utf-8 -*-
"""Real isolated API versions, with failures and source hashes retained."""
import hashlib,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import httpx,numpy as np,trimesh
from services.api.glb_document import read_glb,parts_catalog
from furniture_parts import primitive_data
from complete_part import mesh_stats
from edit_asset import accessor_array
OUT=ROOT/'experiments/multifurniture_20261113';CASES=json.loads((OUT/'cases.json').read_text(encoding='utf-8'));CLIENT=httpx.Client(base_url='http://127.0.0.1:8001',timeout=240)

def geometry(path):
    doc,binary,_=read_glb(path);groups={}
    for p in parts_catalog(doc):
        pr=doc['meshes'][doc['nodes'][p['node']]['mesh']]['primitives'][p['primitive']];_,f,w,_,_,_=primitive_data(doc,binary,p,pr);used=np.unique(f);remap=np.full(len(w),-1,dtype=int);remap[used]=np.arange(len(used));groups.setdefault(p.get('logical_group_id') or p['id'],[]).append(trimesh.Trimesh(w[used],remap[f],process=False))
    meshes={}
    for key,parts in groups.items():m=trimesh.util.concatenate(parts);m.merge_vertices(digits_vertex=8);m.remove_unreferenced_vertices();meshes[key]=m
    return meshes

class Bench:
    def __init__(self,c):
        self.c=c;self.root=f"/api/jobs/{c['job']}/asset";self.catalog=CLIENT.get(self.root).json();self.record={**c,'steps':[]};self.records=[]
    def save(self):
        (OUT/(self.c['case']+'_run.json')).write_text(json.dumps(self.record,ensure_ascii=False,indent=2),encoding='utf-8')
    def edit(self,operation,**values):
        start=time.monotonic();response=CLIENT.post(self.root+'/versions',json={'operation':operation,'base_version':self.catalog['version'],**values});body=response.json();step={'operation':operation,'status':response.status_code,'seconds':round(time.monotonic()-start,3),'request':values};self.record['steps'].append(step)
        if response.status_code==201:self.catalog=body;step.update(version=body['version'],evidence=body['manifest']['operation'])
        else:step['error']=body
        self.save();print(json.dumps({'case':self.c['case'],'operation':operation,'status':response.status_code,'error':step.get('error')},ensure_ascii=False),flush=True);return response.status_code==201
    def plan(self,**values):
        response=CLIENT.post(self.root+'/completion-plan',json={'operation':'complete_part','base_version':self.catalog['version'],**values});self.record.setdefault('plans',[]).append({'status':response.status_code,'body':response.json()});self.save();response.raise_for_status();return response.json()
    def freeze(self,stage):
        path=OUT/(self.c['case']+'_'+stage+'.glb');path.write_bytes(CLIENT.get(self.catalog['model_url']).content);self.record[stage+'_version']=self.catalog['version'];self.save();return path
    def exercise(self,groups,stage='verified'):
        ids=[i for g in self.catalog['groups'] if g['id'] in groups for i in g['part_ids']];assert ids;before=self.freeze(stage+'_assembled');meshes=geometry(before);self.record['groups_checked']={key:mesh_stats(meshes[key]) for key in groups};assert all(meshes[key].is_watertight and meshes[key].is_winding_consistent for key in groups)
        materials={p['id']:p['material_signature'] for p in self.catalog['parts']};assert self.edit('material',part_ids=ids,color='#3a918b',roughness=.7,mode='tint');changed=[p['id'] for p in self.catalog['parts'] if p['material_signature']!=materials[p['id']]];assert set(changed)==set(ids);self.record['material_changed_ids']=changed;self.freeze(stage+'_material');material_version=self.catalog['version']
        assert self.edit('translate_parts',part_ids=ids,translation=[0,0,1.6]);moved=self.freeze(stage+'_moved');after=geometry(moved)
        for key,m in meshes.items():np.testing.assert_allclose(after[key].triangles,m.triangles+([0,0,1.6] if key in groups else [0,0,0]),atol=5e-7)
        exports=[]
        for ordinal,key in enumerate(groups,1):
            part_ids=next(g['part_ids'] for g in self.catalog['groups'] if g['id']==key);r=CLIENT.post(self.root+'/export-parts',json={'version':self.catalog['version'],'part_ids':part_ids});r.raise_for_status();path=OUT/f"{self.c['case']}_{stage}_part_{ordinal}.glb";path.write_bytes(r.content);m=trimesh.load(path,force='mesh',process=False);m.merge_vertices(digits_vertex=8,merge_tex=True,merge_norm=True);stats=mesh_stats(m);assert stats['watertight'] and stats['winding_consistent'];exports.append({'file':path.name,'group_id':key,**stats})
        self.record['exports']=exports;self.record['other_groups_unchanged_on_move']=True;assert self.edit('restore_version',source_version=material_version);self.record['demo_version']=self.catalog['version'];self.freeze(stage+'_final');self.record['source_unchanged']=hashlib.sha256((ROOT/'.data/jobs'/self.c['job']/'model.glb').read_bytes()).hexdigest()==self.c['source_sha256'];assert self.record['source_unchanged'];self.save()

def structural(c):
    b=Bench(c)
    if c['case']=='chair':
        group=next(g for g in b.catalog['groups'] if g['name']=='其余结构');protected=[g['id'] for g in b.catalog['groups'] if g['id']!=group['id']];original=geometry(ROOT/'.data/jobs'/c['job']/'model.glb');values={'part_ids':group['part_ids'],'completion_profile':'support','name':'底架支撑'}
        plan=b.plan(**values)
        if not b.edit('complete_part',completion_bounds=plan['completion_bounds'],**values):return
        evidence=b.catalog['manifest']['operation'];ids=evidence['part_group_ids'];b.freeze('split');new=geometry(OUT/(c['case']+'_split.glb'))
        for key in protected:np.testing.assert_array_equal(new[key].triangles,original[key].triangles)
        b.record['existing_cushion_geometry_preserved']=True;b.record['inherited_inferred_triangles_preserved']=evidence['remainder']['inherited_inferred_triangles'];b.exercise(ids)
    else:
        values={'part_ids':b.catalog['groups'][0]['part_ids'],'completion_profile':'slab','name':'桌面'};plan=b.plan(**values)
        if not b.edit('complete_part',completion_bounds=plan['completion_bounds'],**values):return
        evidence=b.catalog['manifest']['operation'];top=evidence['part_group_ids'];base=evidence['remainder_group_id'];base_ids=next(g['part_ids'] for g in b.catalog['groups'] if g['id']==base);b.freeze('slab_split')
        if b.edit('separate_solids',part_ids=base_ids,name='支脚'):supports=b.catalog['manifest']['operation']['part_group_ids']
        else:supports=[base]
        b.record['tabletop_group_ids']=top;b.record['support_group_ids']=supports;b.exercise(top+supports)

def bookcase(c):
    b=Bench(c);parts=b.catalog['parts'];names={'node_0_primitive_0':'左侧板','node_1_primitive_0':'右侧板','node_2_primitive_0':'背板','node_3_primitive_0':'底板','node_8_primitive_0':'顶板','node_9_primitive_0':'前踢脚板','node_10_primitive_0':'后踢脚板'}
    for n in range(4,8):names[f'node_{n}_primitive_0']=f'层板 {n-3}'
    for p in parts:assert b.edit('rename',part_ids=[p['id']],name=names[p['id']])
    before_doc,before_binary,_=read_glb(ROOT/'.data/jobs'/c['job']/'model.glb');p=b.freeze('organized');doc,binary,_=read_glb(p)
    def attrs(d,data):return {p['id']:{k:accessor_array(d,data,i).tobytes() for k,i in d['meshes'][d['nodes'][p['node']]['mesh']]['primitives'][p['primitive']]['attributes'].items()} for p in parts_catalog(d)}
    assert attrs(before_doc,before_binary)==attrs(doc,binary);b.record['all_geometry_uv_attributes_preserved']=True;b.record['organized_names']=[g['name'] for g in b.catalog['groups']];b.exercise([g['id'] for g in b.catalog['groups']])

def sofas(c):
    b=Bench(c);path=OUT/(c['case']+'_guide_request.json')
    if not path.exists():b.record['outcome']='no_saved_guide';b.save();return
    request=json.loads(path.read_text(encoding='utf-8'));request.pop('base_version',None);request.pop('operation',None);request.update(name='坐垫候选',completion_profile='cushion');plan=b.plan(**request)
    if b.edit('complete_part',completion_bounds=plan['completion_bounds'],**request):b.freeze('split');b.exercise(b.catalog['manifest']['operation']['part_group_ids'])

if __name__=='__main__':
    choices=set(sys.argv[1:]) or {'chair','round_table','bookcase'}
    for c in CASES:
        if c['case'] not in choices:continue
        try:(sofas if 'sofa' in c['case'] else bookcase if c['case']=='bookcase' else structural)(c)
        except Exception as ex:
            (OUT/(c['case']+'_error.txt')).write_text(repr(ex),encoding='utf-8');print(c['case']+' FAILED '+repr(ex),flush=True)
    CLIENT.close()

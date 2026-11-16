"""Eight real furniture: xatlas, exact subset export, world translation and immutable source."""
import copy,hashlib,json,shutil,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import httpx,numpy as np
from services.api.store import Store,now
from services.api.glb_document import read_glb,parts_catalog
from verify_asset_upgrade import signature
from test_part_tools import triangles
from edit_asset import accessor_array
OUT=ROOT/'experiments/part_tools_20261112';store=Store(ROOT/'.data');client=httpx.Client(base_url='http://127.0.0.1:8001',timeout=240);records=[]
def uv_stats(path,identity,planar=False):
    doc,binary,_=read_glb(path);p=next(x for x in parts_catalog(doc) if x['id']==identity);pr=doc['meshes'][doc['nodes'][p['node']]['mesh']]['primitives'][p['primitive']];f=accessor_array(doc,binary,pr['indices']).reshape(-1,3)
    if planar:
        v=accessor_array(doc,binary,pr['attributes']['POSITION']);axes=np.argsort(np.ptp(v,axis=0))[-2:];uv=v[:,axes];uv=(uv-uv.min(0))/np.maximum(np.ptp(uv,axis=0),1e-9)
    else:uv=accessor_array(doc,binary,pr['attributes']['TEXCOORD_0'])
    t=uv[f];area=abs(np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]))*.5
    return {'triangles':len(f),'uv_zero_area_faces':int((area<1e-12).sum()),'uv_range':[uv.min(0).tolist(),uv.max(0).tolist()]}
for case in json.loads((OUT/'cases.json').read_text(encoding='utf-8')):
    source=store.job(case['source_job']);job=copy.deepcopy(source);identity=uuid.uuid4().hex
    for key in ('asset_versions','current_asset_version','review'):job.pop(key,None)
    job.update(id=identity,name='UV 与拆装实测 · '+case['case'],status='awaiting_review',stage='part_tools_edit_test',created_at=now(),updated_at=now(),events=[],review_status='pending',test_clone_of=source['id'])
    for key,value in list(job.items()):
        if isinstance(value,str):job[key]=value.replace(source['id'],identity)
    directory=store.root/'jobs'/identity;directory.mkdir()
    for path in (store.root/'jobs'/source['id']).iterdir():
        if path.is_file() and (path.suffix=='.png' or path.name=='model.glb'):shutil.copyfile(path,directory/path.name)
    store.create_job(job,'',identity);record={'case':case['case'],'category':case['category'],'source_job':source['id'],'job':identity,'steps':[]};records.append(record);root=f'/api/jobs/{identity}/asset';catalog=client.get(root).json();before=signature(directory/'model.glb');digest=hashlib.sha256((directory/'model.glb').read_bytes()).hexdigest()
    def save():(OUT/'real_edits.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    def edit(operation,**params):
        global catalog
        started=time.monotonic();r=client.post(root+'/versions',json={'operation':operation,'base_version':catalog['version'],**params});body=r.json();step={'operation':operation,'status':r.status_code,'seconds':round(time.monotonic()-started,3)};record['steps'].append(step)
        if r.status_code==201:catalog=body;step.update(version=body['version'],manifest=body['manifest'])
        else:step['error']=body
        save();return r.status_code==201
    assert edit('auto_parts',category=case['category']);group=next((g for g in catalog['groups'] if '桌面' in g['name']),catalog['groups'][0]);selected=group['part_ids'];record['selected_group']=group
    # Limit this benchmark to one complete raw member. Logical multi-material
    # grouping is covered by prior tests; these samples have one member per proposal.
    selected=[selected[0]];record['part_ids']=selected;grouped=OUT/(case['case']+'_grouped.glb');grouped.write_bytes(client.get(catalog['model_url']).content);record['planar_uv']=uv_stats(grouped,selected[0],True)
    if edit('unwrap_uv',part_ids=selected):
        path=OUT/(case['case']+'_uv.glb');path.write_bytes(client.get(catalog['model_url']).content);assert signature(path)==before;record['world_triangles_retained_after_uv']=True;record['atlas_uv']=uv_stats(path,selected[0]);record['uv_version']=catalog['version']
        r=client.post(root+'/export-parts',json={'version':catalog['version'],'part_ids':selected});assert r.status_code==200,r.text;export=OUT/(case['case']+'_part.glb');export.write_bytes(r.content);doc,binary,_=read_glb(path);expected=triangles(doc,binary);subset,subbin,_=read_glb(export);actual=triangles(subset,subbin);assert list(actual)==selected;np.testing.assert_array_equal(actual[selected[0]],expected[selected[0]]);record['subset_export_exact']=True
        assert edit('translate_parts',part_ids=selected,translation=[.08,0,0]);moved=OUT/(case['case']+'_moved.glb');moved.write_bytes(client.get(catalog['model_url']).content);doc,binary,_=read_glb(moved);after=triangles(doc,binary);errors=[]
        for key,values in expected.items():
            error=float(abs(after[key]-(values+([.08,0,0] if key in selected else [0,0,0]))).max());errors.append(error);assert error<2e-6
        record['max_world_translation_error']=max(errors);record['moved_version']=catalog['version']
    else:record['uv_not_published']=True
    record['source_unchanged']=hashlib.sha256((directory/'model.glb').read_bytes()).hexdigest()==digest==hashlib.sha256((store.root/'jobs'/source['id']/'model.glb').read_bytes()).hexdigest();assert record['source_unchanged'];save();print(json.dumps({'case':case['case'],'steps':[(s['operation'],s['status']) for s in record['steps']],'uv':record.get('atlas_uv')}),flush=True)
client.close()

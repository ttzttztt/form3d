"""Static asset operations. No external resource paths come from browser input."""
import copy
import io
import math
from pathlib import Path

from services.api.glb_document import selected_primitives, material_edit


def append_array(doc,binary,array,kind,component=5126,target=34962):
    import numpy as np
    dtype={5126:'<f4',5125:'<u4'}[component]
    array=np.asarray(array,dtype=dtype)
    binary.extend(b'\0'*(-len(binary)%4));offset=len(binary);binary.extend(array.tobytes())
    view=len(doc.setdefault('bufferViews',[]));doc['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':array.nbytes,'target':target})
    value={'bufferView':view,'componentType':component,'count':len(array),'type':kind}
    if kind=='VEC3':value.update(min=array.min(axis=0).tolist(),max=array.max(axis=0).tolist())
    index=len(doc.setdefault('accessors',[]));doc['accessors'].append(value);return index


def texture_edit(doc,binary,request):
    from PIL import Image
    from edit_asset import accessor_array
    import numpy as np
    targets=selected_primitives(doc,request.get('part_ids',[]))
    maps={}
    for slot,path in request.get('_texture_paths',{}).items():
        from services.api.textures import texture_image
        image=texture_image(path,slot)
        output=io.BytesIO();image.save(output,format='PNG');data=output.getvalue()
        binary.extend(b'\0'*(-len(binary)%4));offset=len(binary);binary.extend(data)
        view=len(doc.setdefault('bufferViews',[]));doc['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(data)})
        image_index=len(doc.setdefault('images',[]));doc['images'].append({'bufferView':view,'mimeType':'image/png'})
        sampler=len(doc.setdefault('samplers',[]));doc['samplers'].append({'wrapS':10497,'wrapT':10497,'magFilter':9729,'minFilter':9987})
        texture=len(doc.setdefault('textures',[]));doc['textures'].append({'source':image_index,'sampler':sampler})
        transform={'scale':[request['uv_scale']]*2,'rotation':math.radians(request['uv_rotation'])}
        maps[slot]={'index':texture,'extensions':{'KHR_texture_transform':transform}}
    if maps and 'KHR_texture_transform' not in doc.setdefault('extensionsUsed',[]):doc['extensionsUsed'].append('KHR_texture_transform')
    generated=[]
    for part,p in targets:
        if maps and 'TEXCOORD_0' not in p['attributes']:
            vertices=accessor_array(doc,binary,p['attributes']['POSITION'])
            # Explicit planar fallback, not an unwrap or inferred product texture.
            axes=np.argsort(np.ptp(vertices,axis=0))[-2:];uv=vertices[:,axes].copy()
            uv=(uv-uv.min(axis=0))/np.maximum(np.ptp(uv,axis=0),1e-9)
            p['attributes']['TEXCOORD_0']=append_array(doc,binary,uv,'VEC2');generated.append(part['id'])
        material=doc['materials'][p['material']];pbr=material['pbrMetallicRoughness']
        for slot,info in maps.items():
            if slot=='base_color_image':pbr['baseColorTexture']=copy.deepcopy(info)
            elif slot=='roughness_image':pbr['metallicRoughnessTexture']=copy.deepcopy(info)
            else:material['normalTexture']=copy.deepcopy(info)
        if 'normal_image' in maps and 'TANGENT' not in p['attributes']:
            attrs=p['attributes'];v=accessor_array(doc,binary,attrs['POSITION']);uv=accessor_array(doc,binary,attrs['TEXCOORD_0'])
            f=accessor_array(doc,binary,p['indices']).reshape(-1,3) if 'indices' in p else np.arange(len(v)).reshape(-1,3)
            if 'NORMAL' in attrs:n=accessor_array(doc,binary,attrs['NORMAL']).astype(float)
            else:
                n=np.zeros_like(v,dtype=float);face_normal=np.cross(v[f[:,1]]-v[f[:,0]],v[f[:,2]]-v[f[:,0]])
                for k in range(3):np.add.at(n,f[:,k],face_normal)
                n/=np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-12)
                attrs['NORMAL']=append_array(doc,binary,n,'VEC3')
            n/=np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-12)
            edge1=v[f[:,1]]-v[f[:,0]];edge2=v[f[:,2]]-v[f[:,0]];d1=uv[f[:,1]]-uv[f[:,0]];d2=uv[f[:,2]]-uv[f[:,0]]
            determinant=d1[:,0]*d2[:,1]-d1[:,1]*d2[:,0];inverse=np.divide(1,determinant,out=np.zeros_like(determinant),where=np.abs(determinant)>1e-12)
            face_t=(edge1*d2[:,1,None]-edge2*d1[:,1,None])*inverse[:,None];face_b=(edge2*d1[:,0,None]-edge1*d2[:,0,None])*inverse[:,None]
            t=np.zeros_like(v,dtype=float);b=np.zeros_like(v,dtype=float)
            for k in range(3):np.add.at(t,f[:,k],face_t);np.add.at(b,f[:,k],face_b)
            t-=n*np.sum(t*n,axis=1,keepdims=True);length=np.linalg.norm(t,axis=1,keepdims=True)
            fallback=np.cross(n,np.where((np.abs(n[:,0])<.9)[:,None],[1,0,0],[0,1,0]));bad=length[:,0]<1e-9;t[bad]=fallback[bad]
            t/=np.maximum(np.linalg.norm(t,axis=1,keepdims=True),1e-12)
            # Unused/degenerate vertices still require legal unit tangents.
            bad=np.linalg.norm(t,axis=1)<.5;t[bad]=[1,0,0]
            handedness=np.where(np.sum(np.cross(n,t)*b,axis=1)<0,-1.,1.)
            attrs['TANGENT']=append_array(doc,binary,np.c_[t,handedness],'VEC4')
    return {'maps':list(maps),'planar_uv_parts':generated,'uv_warning':'Planar fallback may stretch on curved surfaces; inspect seams.' if generated else ''}


def decimate(doc,binary,request):
    import numpy as np
    import pymeshlab
    from scipy.spatial import cKDTree
    from edit_asset import accessor_array
    if doc.get('animations') or doc.get('skins'):raise ValueError('轻量化只支持静态网格')
    evidence=[]
    for part,p in selected_primitives(doc,request.get('part_ids',[])):
        if p.get('mode',4)!=4 or p.get('targets') or p.get('extensions'):raise ValueError('该网格类型暂不支持安全轻量化')
        attrs=p['attributes']
        if set(attrs)-{'POSITION','NORMAL','COLOR_0'}:raise ValueError('含 UV、切线或其他属性的部件暂不轻量化，以保留纹理接缝')
        vertices=accessor_array(doc,binary,attrs['POSITION'])
        faces=accessor_array(doc,binary,p['indices']).reshape(-1,3) if 'indices' in p else np.arange(len(vertices)).reshape(-1,3)
        if len(faces)<40:raise ValueError('面数过少，轻量化没有实际收益；请选择更复杂的部件')
        ms=pymeshlab.MeshSet();ms.add_mesh(pymeshlab.Mesh(vertices.astype(float),faces.astype(np.int32)))
        ms.meshing_decimation_quadric_edge_collapse(targetfacenum=max(12,int(len(faces)*request['lod_ratio'])),preserveboundary=True,preservenormal=True,preservetopology=True,optimalplacement=True)
        mesh=ms.current_mesh();v=mesh.vertex_matrix();f=mesh.face_matrix();normals=mesh.vertex_normal_matrix()
        used=vertices[np.unique(faces)];diagonal=max(float(np.linalg.norm(np.ptp(used,axis=0))),1e-9)
        # Deterministic vertex sample distances, explicitly not Hausdorff or photo similarity.
        a=used[::max(1,len(used)//10000)];b=v[::max(1,len(v)//10000)]
        distance=max(float(cKDTree(v).query(a)[0].max()),float(cKDTree(used).query(b)[0].max()))/diagonal
        bounds_delta=float(np.max(np.abs(np.array([used.min(0),used.max(0)])-np.array([v.min(0),v.max(0)]))))/diagonal
        if distance>.05 or bounds_delta>.03:raise ValueError('轻量化偏差超过保护阈值，请提高保留比例')
        if len(f)>=len(faces):raise ValueError('保护边界后未减少面数，请调整比例或部件')
        new_attrs={'POSITION':append_array(doc,binary,v,'VEC3'),'NORMAL':append_array(doc,binary,normals,'VEC3')}
        if 'COLOR_0' in attrs:
            source=doc['accessors'][attrs['COLOR_0']];colors=accessor_array(doc,binary,attrs['COLOR_0'])
            if source.get('normalized'):colors=colors/np.iinfo(colors.dtype).max
            colors=colors[cKDTree(vertices).query(v)[1]]
            new_attrs['COLOR_0']=append_array(doc,binary,colors,'VEC4' if colors.shape[1]==4 else 'VEC3')
        p['attributes']=new_attrs;p['indices']=append_array(doc,binary,f.ravel(),'SCALAR',5125,34963)
        evidence.append({'part_id':part['id'],'before':len(faces),'after':len(f),'sampled_vertex_distance_ratio':distance,'bounds_delta_ratio':bounds_delta})
    return {'operation':'decimate','parts':evidence,'limits':'Per-primitive material boundaries kept; sampled vertex distance is not surface Hausdorff distance. Visual review required.'}


def apply_operation(doc,binary,request):
    from edit_asset import group_geometry
    from furniture_parts import auto_parts,merge_parts,assign_faces
    operation=request['operation']
    if operation=='reconstruct_parts':
        from reconstruct_parts import reconstruct_parts
        return reconstruct_parts(doc,binary,request)
    if operation=='separate_solids':
        from closed_components import separate_solids
        return separate_solids(doc,binary,request)
    if operation=='complete_part':
        from complete_part import complete_part
        return complete_part(doc,binary,request)
    if operation in {'unwrap_uv','translate_parts','export_parts'}:
        from part_tools import unwrap_uv,translate_parts,export_parts
        if operation=='export_parts':return export_parts(doc,binary,request)
        return (unwrap_uv if operation=='unwrap_uv' else translate_parts)(doc,binary,request)
    if operation=='auto_parts':return auto_parts(doc,binary,request)
    if operation=='merge_parts':return merge_parts(doc,request)
    if operation=='assign_faces':return assign_faces(doc,binary,request)
    if operation=='repair_geometry':
        from mesh_quality import repair_geometry
        return repair_geometry(doc,binary,request)
    if operation=='material':
        result=material_edit(doc,request);result.update(texture_edit(doc,binary,request))
        result['note']='Embedded user maps; planar UV fallback disclosed. Geometry positions unchanged.'
        return result
    if operation=='rename':
        for _,p in selected_primitives(doc,request['part_ids']):p.setdefault('extras',{})['form_part_name']=request['name'].strip()
        return {'operation':operation,'name':request['name'],'parts':request['part_ids']}
    if operation=='decimate':return decimate(doc,binary,request)
    if operation=='optimize_mesh':
        from static_simplification import optimize_static
        return optimize_static(doc,binary,request)
    if operation=='face_group':request['part_ids']=[s['part_id'] for s in request['face_selection']]
    return group_geometry(doc,binary,request)

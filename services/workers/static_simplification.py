# -*- coding: utf-8 -*-
"""Material-boundary preserving asset reduction, including measured UV guards."""
import numpy as np
import trimesh
from scipy.spatial import cKDTree
import tempfile
from pathlib import Path
from services.api.glb_document import selected_primitives
from edit_asset import accessor_array
from asset_operations import append_array
from solid_partition import prepare_mesh
from shape_simplification import validate_simplification,silhouette_masks,component_count
from uv_quality import uv_diagnostics


def textured_mesh_set(vertices,faces,wedge):
    """OBJ loader initializes MeshLab wedge texture indices consistently.

    Its Python Mesh constructor leaves those indices invalid in the installed
    version, even after attaching a dummy texture. Only UVs enter QEM; the
    original GLB images/materials remain unchanged.
    """
    import pymeshlab
    from PIL import Image
    with tempfile.TemporaryDirectory(prefix='img3d_uv_qem_')as temporary:
        folder=Path(temporary);Image.new('RGB',(1,1),'white').save(folder/'dummy.png')
        (folder/'material.mtl').write_text('newmtl surface\nmap_Kd dummy.png\n',encoding='ascii')
        with(folder/'mesh.obj').open('w',encoding='ascii')as stream:
            stream.write('mtllib material.mtl\nusemtl surface\n')
            for v in vertices:stream.write('v %.12g %.12g %.12g\n'%tuple(v))
            for uv in wedge:stream.write('vt %.12g %.12g\n'%tuple(uv))
            for i,face in enumerate(faces):stream.write('f '+' '.join(f'{int(v)+1}/{i*3+k+1}'for k,v in enumerate(face))+'\n')
        result=pymeshlab.MeshSet();result.load_new_mesh(str(folder/'mesh.obj'))
    return result


def tangents(vertices,faces,normals,uv):
    a=vertices[faces[:,1]]-vertices[faces[:,0]];b=vertices[faces[:,2]]-vertices[faces[:,0]]
    u=uv[faces[:,1]]-uv[faces[:,0]];v=uv[faces[:,2]]-uv[faces[:,0]];det=u[:,0]*v[:,1]-u[:,1]*v[:,0]
    inv=np.divide(1.,det,out=np.zeros(len(det)),where=abs(det)>1e-12)
    ft=(a*v[:,1,None]-b*u[:,1,None])*inv[:,None];fb=(b*u[:,0,None]-a*v[:,0,None])*inv[:,None]
    t=np.zeros_like(vertices);bit=np.zeros_like(vertices)
    for k in range(3):np.add.at(t,faces[:,k],ft);np.add.at(bit,faces[:,k],fb)
    t-=normals*np.sum(t*normals,axis=1,keepdims=True);length=np.linalg.norm(t,axis=1)
    bad=length<1e-10;t[bad]=np.cross(normals[bad],np.where((abs(normals[bad,0])<.9)[:,None],[1.,0,0],[0.,1,0]))
    t/=np.maximum(np.linalg.norm(t,axis=1,keepdims=True),1e-12)
    return np.c_[t,np.where(np.sum(np.cross(normals,t)*bit,axis=1)<0,-1.,1.)]


def interpolate_attributes(vertices,source_vertices,source_faces,attributes):
    import igl
    _,which,closest=igl.point_mesh_squared_distance(np.ascontiguousarray(vertices),np.ascontiguousarray(source_vertices),np.ascontiguousarray(source_faces,dtype=np.int64))
    with np.errstate(divide='ignore',invalid='ignore'):
        weights=trimesh.triangles.points_to_barycentric(source_vertices[source_faces[which]],closest)
    invalid=(which<0)|~np.isfinite(weights).all(axis=1)|(weights.min(axis=1)<-1e-5)|(abs(weights.sum(axis=1)-1)>1e-5)
    weights[invalid]=[1,0,0]
    nearest=cKDTree(source_vertices).query(vertices[invalid])[1]if invalid.any()else[]
    result={}
    for key,values in attributes.items():
        interpolated=np.einsum('ni,nij->nj',weights,values[source_faces[which]])
        if invalid.any():interpolated[invalid]=values[nearest]
        if not np.isfinite(interpolated).all():raise ValueError('源属性包含无法插值的数值，保留原网格')
        result[key]=interpolated
    return result


def optimize_static(doc,binary,request):
    import pymeshlab
    if doc.get('animations')or doc.get('skins'):raise ValueError('保形减面只支持静态模型')
    entries=selected_primitives(doc,request.get('part_ids',[]));total=sum(p['triangles']for p,_ in entries)
    target=request.get('target_faces',100000);ratio=min(1.,target/max(total,1));rows=[];changed=0
    for part,primitive in entries:
        row={'part_id':part['id'],'before':part['triangles'],'after':part['triangles'],'status':'preserved'};rows.append(row)
        attrs=primitive['attributes']
        if ratio>=1 or part['triangles']<48:row['reason']='当前范围已在目标内或该网格面数较少';continue
        if set(attrs)-{'POSITION','NORMAL','TEXCOORD_0','TANGENT','COLOR_0'}or primitive.get('targets')or primitive.get('extensions')or primitive.get('mode',4)!=4:row['reason']='含尚未支持的属性，保留原网格';continue
        if'TEXCOORD_0'in attrs and'COLOR_0'in attrs:row['reason']='同时含 UV 与顶点颜色，保留原网格';continue
        if part['triangles']>1500000:row['reason']='单网格超出本轮保守处理上限，保留原网格';continue
        vertices=accessor_array(doc,binary,attrs['POSITION']).astype(float)
        faces=accessor_array(doc,binary,primitive['indices']).reshape(-1,3)if'indices'in primitive else np.arange(len(vertices)).reshape(-1,3)
        source,_=prepare_mesh(trimesh.Trimesh(vertices,faces,process=False))
        if len(source.faces)>100000 and component_count(source)>256:row['reason']='密集毛发或大量独立碎片，保留原网格以免误删细节';continue
        source_masks=silhouette_masks(source,source.bounds)
        welded,which=np.unique(vertices.astype(np.float32),axis=0,return_inverse=True);wfaces=which[faces]
        uv=accessor_array(doc,binary,attrs['TEXCOORD_0']).astype(float)if'TEXCOORD_0'in attrs else None
        if uv is not None:ms=textured_mesh_set(welded,wfaces,uv[faces].reshape(-1,2))
        else:
            ms=pymeshlab.MeshSet();ms.add_mesh(pymeshlab.Mesh(welded.astype(float),wfaces.astype(np.int32)))
        try:
            budget=max(24,int(len(faces)*ratio))
            if uv is not None:
                ms.meshing_decimation_quadric_edge_collapse_with_texture(targetfacenum=budget,preserveboundary=True,preservenormal=True,optimalplacement=True,extratcoordw=4.,qualitythr=.5)
            else:ms.meshing_decimation_quadric_edge_collapse(targetfacenum=budget,preserveboundary=True,preservenormal=True,preservetopology=True,optimalplacement=True,qualitythr=.5)
            mesh=ms.current_mesh();v=mesh.vertex_matrix();f=mesh.face_matrix()
            result,_=prepare_mesh(trimesh.Trimesh(v,f,process=False));checks=validate_simplification(source,result,source_masks)
            if 0<checks['self_intersection_faces']<=16 and checks['source_closed']:
                from storage_contacts import clean_indexed_contacts
                repaired,cleanup=clean_indexed_contacts(v,f)
                if repaired is not None:
                    validated,_=prepare_mesh(trimesh.Trimesh(repaired,f,process=False));rechecked=validate_simplification(source,validated,source_masks)
                    row['initial_checks']=checks;row['bounded_storage_cleanup']=cleanup
                    if rechecked['passed']:v,result,checks=repaired,validated,rechecked
            row['checks']=checks
            if not checks['passed']or len(f)>=len(faces):row['reason']='保形检查未通过或未减少面数';continue
            source_attributes={}
            for key in('NORMAL','COLOR_0'):
                if key in attrs:
                    values=accessor_array(doc,binary,attrs[key]).astype(float)
                    if doc['accessors'][attrs[key]].get('normalized'):values/=np.iinfo(accessor_array(doc,binary,attrs[key]).dtype).max
                    source_attributes[key]=values
            values=interpolate_attributes(v,vertices,faces,source_attributes)
            geometric_normals=trimesh.Trimesh(v,f,process=False).vertex_normals.copy()
            normals=values.get('NORMAL',geometric_normals);length=np.linalg.norm(normals,axis=1)
            bad=length<1e-10
            if bad.any():normals[bad]=geometric_normals[bad];length=np.linalg.norm(normals,axis=1)
            if np.any(length<1e-10)or not np.isfinite(length).all():raise ValueError('无法保留可靠法线，保留原网格')
            normals/=length[:,None]
            if uv is not None:
                wedge=mesh.wedge_tex_coord_matrix();keys=np.c_[f.ravel(),np.round(wedge,8)]
                _,first,inverse=np.unique(keys,axis=0,return_index=True,return_inverse=True);mapping=f.ravel()[first];newuv=wedge[first];v=v[mapping];normals=normals[mapping];f=inverse.reshape(-1,3)
                baseline=uv_diagnostics(vertices,faces,uv);actual=uv_diagnostics(v,f,newuv)
                row['uv_checks']={'before':baseline,'after':actual}
                if actual['collapsed_geometry_area_fraction']>max(.001,baseline['collapsed_geometry_area_fraction']+.0001)or actual['geometric_mean_anisotropy']>baseline['geometric_mean_anisotropy']*1.15 or actual['area_fraction_anisotropy_over_4']>baseline['area_fraction_anisotropy_over_4']+.005:row['reason']='UV 拉伸或塌缩检查未通过';continue
            newattrs={'POSITION':append_array(doc,binary,v,'VEC3'),'NORMAL':append_array(doc,binary,normals,'VEC3')}
            if uv is not None:
                newattrs['TEXCOORD_0']=append_array(doc,binary,newuv,'VEC2')
                if'TANGENT'in attrs:newattrs['TANGENT']=append_array(doc,binary,tangents(v,f,normals,newuv),'VEC4')
            if'COLOR_0'in values:
                colors=np.clip(values['COLOR_0'],0,1);newattrs['COLOR_0']=append_array(doc,binary,colors,'VEC4'if colors.shape[1]==4 else'VEC3')
            primitive['attributes']=newattrs;primitive['indices']=append_array(doc,binary,f.ravel(),'SCALAR',5125,34963)
            row.update(status='simplified',after=len(f),material_and_logical_identity_preserved=True);changed+=1
        except(RuntimeError,ValueError,pymeshlab.PyMeshLabException)as exc:row['reason']='该网格减面未完成，已保留原网格';row['diagnostic']=str(exc)[:200]
    after=sum(r['after']for r in rows)
    return {'operation':'optimize_mesh','parts':rows,'target_faces':target,'faces_before':total,'faces_after':after,'changed_parts':changed,'target_reached':after<=target*1.02,'physical_accuracy_verified':False,'uv_and_material_boundaries_preserved':True}

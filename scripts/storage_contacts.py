"""Bounded cleanup of a few numerical contacts, never a general solid repair."""
import numpy as np
import trimesh
from solid_partition import prepare_mesh


def selected_contacts(mesh):
    import pymeshlab
    ms=pymeshlab.MeshSet();ms.add_mesh(pymeshlab.Mesh(mesh.vertices,mesh.faces.astype(np.int32)))
    ms.compute_selection_by_self_intersections_per_face()
    return np.flatnonzero(ms.current_mesh().face_selection_array())


def clean_storage_contacts(mesh):
    mesh,_=prepare_mesh(mesh);faces=selected_contacts(mesh)
    if not len(faces):return mesh,None
    if len(faces)>16:raise ValueError('轮廓重建出现明显自交，未自动采用')
    ids=np.unique(mesh.faces[faces]);diagonal=float(np.linalg.norm(mesh.extents));neighbors=mesh.vertex_neighbors
    delta=np.array([mesh.vertices[neighbors[i]].mean(0)-mesh.vertices[i]for i in ids])
    maximum=diagonal*.0005
    for strength in(.02,.08,.2):
        shift=delta*strength;length=np.linalg.norm(shift,axis=1);shift*=np.minimum(1,maximum/np.maximum(length,1e-12))[:,None]
        candidate=mesh.copy();candidate.vertices[ids]+=shift;candidate,_=prepare_mesh(candidate)
        if candidate.is_watertight and candidate.is_winding_consistent and candidate.volume>0 and not len(selected_contacts(candidate)):
            return candidate,{'method':'bounded_vertex_relaxation_of_storage_contacts','input_selected_faces':len(faces),'adjusted_vertices':len(ids),'maximum_displacement_source_units':float(np.linalg.norm(shift,axis=1).max()),'maximum_allowed_diagonal_ratio':.0005}
    raise ValueError('轮廓尖角在存储精度下仍自交，候选已保留但未采用')


def clean_indexed_contacts(vertices,faces):
    """Bounded numerical cleanup without changing UV wedge/face indices."""
    base=trimesh.Trimesh(np.asarray(vertices,dtype=np.float32),faces,process=False)
    selected=selected_contacts(base)
    if not 0<len(selected)<=16:return None,None
    if not base.is_watertight or not base.is_winding_consistent or base.volume<=0:return None,None
    ids=np.unique(base.faces[selected]);neighbors=base.vertex_neighbors;diagonal=float(np.linalg.norm(base.extents));maximum=diagonal*.0005
    delta=np.array([base.vertices[neighbors[i]].mean(0)-base.vertices[i]for i in ids])
    for strength in(.02,.08,.2):
        shift=delta*strength;length=np.linalg.norm(shift,axis=1);shift*=np.minimum(1,maximum/np.maximum(length,1e-12))[:,None]
        values=base.vertices.copy();values[ids]+=shift;values=values.astype(np.float32)
        check,_=prepare_mesh(trimesh.Trimesh(values,faces,process=False))
        if len(check.vertices)!=len(values)or len(check.faces)!=len(faces):continue
        if check.is_watertight and check.is_winding_consistent and check.volume>0 and not len(selected_contacts(check)):
            return values,{'method':'bounded_index_preserving_numerical_contact_cleanup','input_selected_faces':len(selected),'adjusted_vertices':len(ids),'maximum_displacement_source_units':float(np.linalg.norm(shift,axis=1).max()),'maximum_allowed_diagonal_ratio':.0005,'face_order_and_uv_wedges_preserved':True}
    return None,None

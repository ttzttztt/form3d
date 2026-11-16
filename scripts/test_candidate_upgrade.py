# -*- coding: utf-8 -*-
"""Synthetic geometry contracts, not measured furniture accuracy."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import cv2,numpy as np,trimesh
from PIL import Image
from services.api.glb_document import parts_catalog
from asset_operations import append_array
from edit_asset import accessor_array
from shape_simplification import simplify_shape,validate_simplification
from static_simplification import optimize_static,tangents
from part_tools import box_unwrap
from replacement_uv import prepare_replacement_uv
from photo_part_evidence import camera_matrix,rasterize
from photo_pose_refinement import refine_photo_pose
from candidate_quality import assess_candidate,neighbor_penetration
from auto_part_optimization import compare


def document(mesh,uv=False):
    doc={'asset':{'version':'2.0'},'buffers':[{'byteLength':0}],'scene':0,'scenes':[{'nodes':[0]}],'nodes':[{'mesh':0,'name':'fixture'}],'meshes':[{'primitives':[]}],'materials':[{'pbrMetallicRoughness':{'baseColorFactor':[.5,.5,.5,1],'metallicFactor':0,'roughnessFactor':.8}}]};binary=bytearray()
    vertices,faces=mesh.vertices.copy(),mesh.faces.copy();normal=mesh.vertex_normals.copy()
    if uv:
        mapping,faces,tex=box_unwrap(vertices,faces);vertices=vertices[mapping];normal=normal[mapping]
    attrs={'POSITION':append_array(doc,binary,vertices,'VEC3'),'NORMAL':append_array(doc,binary,normal,'VEC3')}
    if uv:attrs.update(TEXCOORD_0=append_array(doc,binary,tex,'VEC2'),TANGENT=append_array(doc,binary,tangents(vertices,faces,normal,tex),'VEC4'))
    doc['meshes'][0]['primitives'].append({'attributes':attrs,'indices':append_array(doc,binary,faces.ravel(),'SCALAR',5125,34963),'material':0,'extras':{'form_logical_group_id':'fixture_group','form_semantic_kind':'pillow'}})
    return doc,binary


class CandidateUpgradeTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.folder=Path(temporary.name)

    def test_simplification_preserves_solid_and_reduces_faces(self):
        source=trimesh.creation.icosphere(subdivisions=3)
        result,proof=simplify_shape(source,800)
        self.assertTrue(proof['accepted']);self.assertLess(len(result.faces),len(source.faces));self.assertTrue(result.is_watertight)
        self.assertEqual(proof['attempts'][-1]['checks']['self_intersection_faces'],0)

    def test_surface_guard_rejects_a_shifted_candidate(self):
        source=trimesh.creation.box();wrong=source.copy();wrong.apply_translation([.15,0,0]);proof=validate_simplification(source,wrong)
        self.assertFalse(proof['passed']);self.assertGreater(proof['bounds_delta_diagonal_ratio'],.03)

    def test_textured_decimation_preserves_uv_tangents_and_material_identity(self):
        source=trimesh.creation.icosphere(subdivisions=3);doc,binary=document(source,True);material=copy.deepcopy(doc['materials'])
        proof=optimize_static(doc,binary,{'target_faces':900,'part_ids':[]})
        self.assertEqual(proof['changed_parts'],1);self.assertLess(proof['faces_after'],len(source.faces));self.assertEqual(doc['materials'],material)
        primitive=doc['meshes'][0]['primitives'][0];self.assertIn('TEXCOORD_0',primitive['attributes']);self.assertIn('TANGENT',primitive['attributes'])
        tangent=accessor_array(doc,binary,primitive['attributes']['TANGENT']);np.testing.assert_allclose(np.linalg.norm(tangent[:,:3],axis=1),1,atol=1e-5)
        self.assertTrue(proof['parts'][0]['checks']['passed'])

    def test_shared_uv_uses_same_coordinates_across_technical_patches(self):
        source=trimesh.creation.box();doc,binary=document(source)
        primitive=doc['meshes'][0]['primitives'][0];faces=source.faces;up=np.flatnonzero(source.face_normals[:,1]>.9)
        chunks=[faces[[up[0]]],faces[[up[1]]],faces[np.setdiff1d(np.arange(len(faces)),up)]]
        primitives=[]
        for chunk in chunks:
            p=copy.deepcopy(primitive);p['indices']=append_array(doc,binary,chunk.ravel(),'SCALAR',5125,34963);primitives.append(p)
        doc['meshes'][0]['primitives']=primitives;proof=prepare_replacement_uv(doc,binary,['fixture_group'])
        maps=[]
        for p in doc['meshes'][0]['primitives'][:2]:
            v=accessor_array(doc,binary,p['attributes']['POSITION']);uv=accessor_array(doc,binary,p['attributes']['TEXCOORD_0']);maps.append({tuple(x):tex for x,tex in zip(v,uv)})
        shared=set(maps[0])&set(maps[1]);self.assertEqual(len(shared),2)
        for vertex in shared:np.testing.assert_array_equal(maps[0][vertex],maps[1][vertex])
        self.assertTrue(proof['shared_density_within_logical_group'])

    def test_degenerate_source_triangles_cannot_propagate_nan_attributes(self):
        from static_simplification import interpolate_attributes
        vertices=np.array([[0.,0,0],[1.,0,0],[2.,0,0]])
        values=np.array([[1.,0,0],[0.,1,0],[0.,0,1]])
        result=interpolate_attributes(np.array([[.1,0,0]]),vertices,np.array([[0,1,2]]),{'NORMAL':values})
        self.assertTrue(np.isfinite(result['NORMAL']).all())
        np.testing.assert_array_equal(result['NORMAL'],values[[0]])

    def test_complete_overlap_with_neighbor_is_detected_using_interior_points(self):
        source=trimesh.creation.box();doc,binary=document(source);doc['nodes'].append({'mesh':0,'name':'neighbor','translation':[2,0,0]});doc['scenes'][0]['nodes'].append(1)
        result=source.copy();result.apply_translation([2,0,0])
        proof=neighbor_penetration(result,source,doc,binary,['node_0_primitive_0'])
        self.assertTrue(proof['severe_increase']);self.assertEqual(proof['closed_neighbors_tested'],1)

    def test_open_neighbors_are_reported_as_unchecked(self):
        source=trimesh.creation.box();doc,binary=document(source);p=copy.deepcopy(doc['meshes'][0]['primitives'][0]);p['indices']=append_array(doc,binary,source.faces[:-2].ravel(),'SCALAR',5125,34963)
        doc['meshes'].append({'primitives':[p]});doc['nodes'].append({'mesh':1});doc['scenes'][0]['nodes'].append(1)
        views=[{'part_silhouette_iou_before':.8,'part_silhouette_iou_after':.85,'passed':True}]
        result=assess_candidate(source,source,doc,binary,['node_0_primitive_0'],views,100000,{})
        integrity=result['dimensions'][0];self.assertEqual(integrity['status'],'warning');self.assertEqual(integrity['metrics']['neighbor_penetration']['open_or_invalid_neighbors_skipped'],1)

    def test_small_pose_refinement_improves_known_synthetic_views(self):
        source=trimesh.creation.icosphere(subdivisions=1);source.apply_scale([.7,.55,.22]);candidate=source.copy();candidate.apply_translation([.035,.01,0]);views=[]
        for azimuth in(0.,1.57):
            matrix=camera_matrix(np.zeros(3),1,azimuth,.15,.7);mask=rasterize({'target':source},matrix,(256,256))[0]>0
            views.append({'matrix':matrix,'mask':mask,'others':{}})
        result,proof=refine_photo_pose(candidate,source,'pillow',views)
        self.assertTrue(proof['applied']);self.assertGreater(np.mean(proof['after_view_ious']),np.mean(proof['before_view_ious']));self.assertTrue(result.is_watertight)
        self.assertTrue(proof['same_reference_used_for_constraint_and_comparison'])

    def test_far_pose_is_not_forced_to_match_a_photo(self):
        source=trimesh.creation.box();candidate=source.copy();candidate.apply_translation([3,0,0]);matrix=camera_matrix(np.zeros(3),4,0,.2,.7);mask=rasterize({'target':source},matrix,(256,256))[0]>0
        result,proof=refine_photo_pose(candidate,source,'pillow',[{'matrix':matrix,'mask':mask,'others':{}}])
        self.assertFalse(proof['applied']);np.testing.assert_array_equal(result.vertices,candidate.vertices);json.dumps(proof,allow_nan=False)

    def test_side_view_can_block_adoption_when_front_view_is_identical(self):
        source=trimesh.creation.box(extents=[1,1,.2]);after=trimesh.creation.box(extents=[1,1,.6]);before_doc,before_binary=document(source);after_doc,after_binary=document(after)
        main=np.array([[100.,0,0,128],[0,100,0,128],[0,0,0,1]]);side=np.array([[0.,0,100,128],[0,100,0,128],[0,0,0,1]])
        folder=self.folder;(folder/'references').mkdir();(folder/'views/0/references').mkdir(parents=True)
        for location,matrix in[(folder,main),(folder/'views/0',side)]:
            mask=rasterize({'fixture_group':source},matrix,(256,256))[0]>0
            Image.fromarray(mask.astype('uint8')*255).save(location/'references/expected.png');Image.new('RGB',(256,256),'white').save(location/'references/product.png')
            (location/'camera.json').write_text(json.dumps({'projection_from_world':matrix.tolist(),'image_size':[256,256],'silhouette_iou':1}),encoding='utf-8')
            (location/'references/references.json').write_text(json.dumps({'candidates':[{'id':'expected','mask_file':'expected.png'}]}),encoding='utf-8')
        plan={'route':'ai_regeneration','photo_association':{'candidate_id':'expected'},'additional_views':[{'index':0,'image_id':'e'*32,'role':'side','association':{'candidate_id':'expected'}}]}
        checks=compare(folder,{'part_ids':['node_0_primitive_0'],'kind':'pillow','seat_with_frame':False},before_doc,before_binary,after_doc,after_binary,'fixture_group','fixture_group',{},plan)
        self.assertTrue(checks['views'][0]['passed']);self.assertFalse(checks['views'][1]['passed']);self.assertFalse(checks['can_adopt'])


if __name__=='__main__':unittest.main(verbosity=2)

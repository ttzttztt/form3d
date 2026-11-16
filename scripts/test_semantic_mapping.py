import copy,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np,trimesh
from PIL import Image
from semantic_mapping import associate_instances,project_visible
from semantic_asset import merge_opposite_sides,create_semantic_asset
from cylinder_evidence import fit_cylinder
from services.api.glb_document import read_glb,parts_catalog
from edit_asset import accessor_array

class SemanticMappingTests(unittest.TestCase):
    def test_occluded_face_cannot_vote_from_rgb_mask(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'depth.png';Image.fromarray(np.full((4,4),round(2/8*65535),dtype=np.uint16)).save(path);view={'clip_from_source':np.eye(4),'view_from_source':[[1,0,0,0],[0,1,0,0],[0,0,1,-2],[0,0,0,1]],'image_size':[4,4],'depth_path':path,'depth_scale':8};_,_,seen,_=project_visible(np.array([[0,0,0],[0,0,.5]]),view,tolerance=.001);self.assertEqual(seen.tolist(),[True,False])
    def test_union_mask_cannot_transitively_merge_disjoint_same_view_pillows(self):
        def candidate(f,view):return {'faces':np.asarray(f),'kind':'pillow','view':view,'center':np.zeros(3)}
        clusters=associate_instances([candidate([0,1,2,3],0),candidate([4,5,6,7],0),candidate(list(range(8)),1)],np.ones(8),1)
        self.assertEqual(sorted(map(len,clusters)),[1,2])
    def fixture(self,separate=False):
        xy=np.array([[x,y] for x in (-.2,0,.2) for y in (-.2,0,.2)]);a=np.c_[xy,np.full(9,.04)];b=np.c_[xy+([1,0] if separate else [0,0]),np.full(9,-.04)];centers=np.vstack([a,b]);normals=np.vstack([np.tile([0,0,1],(9,1)),np.tile([0,0,-1],(9,1))]);groups=[{'label':1,'source_kind':'pillow','views':[0,1,5],'observations':3},{'label':2,'source_kind':'pillow','views':[2,3,4],'observations':3}];return np.r_[np.ones(9,int),np.full(9,2)],groups,centers,normals,np.ones(18)
    def test_front_and_back_of_one_pillow_become_one_logical_instance(self):
        labels,groups,c,n,a=self.fixture();labels,groups,merged=merge_opposite_sides(labels,groups,c,n,a,2);self.assertEqual(len(groups),1);self.assertEqual(len(np.unique(labels)),1);self.assertEqual(len(merged),1)
    def test_adjacent_pillows_are_not_merged_by_matching_normals(self):
        labels,groups,c,n,a=self.fixture(True);labels,groups,merged=merge_opposite_sides(labels,groups,c,n,a,2);self.assertEqual(len(groups),2);self.assertEqual(merged,[])
    def test_cylinder_fit_separates_round_bolster_from_a_fused_flat_patch(self):
        cylinder=trimesh.creation.cylinder(radius=.2,height=1.4,sections=64).subdivide().subdivide();plane=trimesh.creation.box(extents=[.01,.8,1.4]);plane.apply_translation([.35,.2,0]);mesh=trimesh.util.concatenate([cylinder,plane]);result=fit_cylinder(mesh.triangles_center,mesh.face_normals,mesh.area_faces,np.linalg.norm(mesh.extents));self.assertIsNotNone(result);mask,evidence=result;self.assertAlmostEqual(evidence['radius_source_units'],.2,delta=.02);self.assertGreater(mask[:len(cylinder.faces)].mean(),.8);self.assertLess(mask[len(cylinder.faces):].mean(),.2)
    def test_flat_pillow_is_not_named_cylindrical_by_text_alone(self):
        mesh=trimesh.creation.icosphere(subdivisions=3);mesh.apply_scale([.07,.28,.6]);self.assertIsNone(fit_cylinder(mesh.triangles_center,mesh.face_normals,mesh.area_faces,np.linalg.norm(mesh.extents)))
    def test_whole_model_cannot_be_published_as_one_detected_tabletop(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.glb';mesh=trimesh.creation.icosphere(subdivisions=2);mesh.export(path);doc,binary,_=read_glb(path);labels=np.ones(len(mesh.faces),int);groups=[{'label':1,'kind':'tabletop','source_kind':'tabletop','views':[0,1],'observations':2}]
            with patch('semantic_asset.map_masks',return_value=(labels,groups,[])),patch('semantic_asset.refine_regions',side_effect=lambda v,f,c,a,l,g:(l,{})):
                with self.assertRaisesRegex(ValueError,'未识别出多个'):create_semantic_asset(doc,binary,tmp)
    def test_grouping_preserves_all_original_positions_normals_uv_and_triangles(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source.glb';mesh=trimesh.creation.icosphere(subdivisions=2);mesh.visual=trimesh.visual.TextureVisuals(uv=np.zeros((len(mesh.vertices),2)));mesh.export(source);doc,binary,_=read_glb(source);original=copy.deepcopy(doc);before=bytes(binary);part=parts_catalog(doc)[0];primitive=doc['meshes'][doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']];faces=accessor_array(doc,binary,primitive['indices']).reshape(-1,3);labels=np.where(np.arange(len(faces))<len(faces)//2,1,2);groups=[{'label':i,'kind':'pillow','source_kind':'pillow','views':[0,1],'observations':2} for i in (1,2)]
            def mapped(*args,**kwargs):
                support=np.stack([np.where(labels==i,2,0)for i in(1,2)]).astype(np.uint8);kwargs['evidence'].update(visible_views=np.full(len(labels),2,np.uint8),support_views=support,scores=support.astype(float)/3,raw_labels=labels.copy())
                return labels,groups,[]
            with patch('semantic_asset.map_masks',side_effect=mapped):
                result=create_semantic_asset(doc,binary,tmp)
            self.assertEqual(result['triangles_preserved'],len(faces));after=[]
            for p in parts_catalog(doc):
                primitive_after=doc['meshes'][doc['nodes'][p['node']]['mesh']]['primitives'][p['primitive']];after.extend(accessor_array(doc,binary,primitive_after['indices']).reshape(-1,3).tolist())
                for index in primitive['attributes'].values():self.assertEqual(accessor_array(doc,binary,index).tobytes(),accessor_array(original,before,index).tobytes())
            self.assertEqual(sorted(map(tuple,after)),sorted(map(tuple,faces.tolist())))
if __name__=='__main__':unittest.main(verbosity=2)

import copy,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'services/workers')]
import numpy as np,trimesh
from shapely.geometry import Polygon
from services.api.glb_document import read_glb,parts_catalog,write_glb,set_part_ids
from complete_part import complete_part,completion_plan
from closed_components import separate_solids
from edit_asset import accessor_array
from services.api.models import AssetEditRequest

class StructuralTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)/'u.glb';shape=Polygon([[-1,0],[-.6,0],[-.6,1],[.6,1],[.6,0],[1,0],[1,1.4],[-1,1.4]]);trimesh.creation.extrude_polygon(shape,height=.5,engine='earcut').export(self.path);self.doc,self.binary,_=read_glb(self.path);set_part_ids(self.doc)
    def request(self,profile,bounds,ids=None):return {'operation':'complete_part','completion_profile':profile,'part_ids':ids or [parts_catalog(self.doc)[0]['id']],'completion_bounds':bounds,'name':'测试结构'}
    def test_support_creates_two_closed_groups(self):
        result=complete_part(self.doc,self.binary,self.request('support',[[0,0,0],[1,.5,1]]));self.assertEqual(result['part']['components'],2);self.assertEqual(len(result['part_group_ids']),2);self.assertTrue(result['part']['watertight']);self.assertTrue(result['remainder']['watertight']);self.assertEqual(result['cut_planes'],1)
    def test_fine_support_scan_finds_repeatable_lower_components(self):
        mesh=trimesh.load(self.path,force='mesh',process=False)
        for _ in range(3):mesh=mesh.subdivide()
        mesh.export(self.path);self.doc,self.binary,_=read_glb(self.path);set_part_ids(self.doc);request=self.request('support',[]);request['detail_level']='fine';plan=completion_plan(self.doc,self.binary,request);self.assertEqual(plan['strategy']['seed_component_count'],2);self.assertLess(plan['strategy']['cut_height_world'],1);self.assertGreater(len(plan['strategy']['height_candidates']),2)
    def test_existing_top_and_inferred_caps_survive_lower_split(self):
        top=complete_part(self.doc,self.binary,self.request('slab',[[0,.8,0],[1,1,1]]));before=parts_catalog(self.doc);top_ids=[p['id'] for p in before if p['logical_group_id']==top['part_group_id']];old={p['id']:p for p in before if p['id'] in top_ids};body_ids=[p['id'] for p in before if p['logical_group_id']==top['remainder_group_id']]
        result=complete_part(self.doc,self.binary,self.request('support',[[0,0,0],[1,.5,1]],body_ids));after=parts_catalog(self.doc);stable=lambda parts:{key:{k:v for k,v in p.items() if k!='primitive'} for key,p in parts.items()};self.assertEqual(stable({p['id']:p for p in after if p['id'] in top_ids}),stable(old));self.assertGreater(result['remainder']['inherited_inferred_triangles'],0)
    def test_cutting_existing_inferred_interfaces_refused(self):
        top=complete_part(self.doc,self.binary,self.request('slab',[[0,.8,0],[1,1,1]]));ids=[p['id'] for p in parts_catalog(self.doc) if p['logical_group_id']==top['remainder_group_id']]
        with self.assertRaisesRegex(ValueError,'切到已有推测'):complete_part(self.doc,self.binary,self.request('support',[[0,.3,0],[1,1,1]],ids))
    def test_explicit_bounds_do_not_depend_on_height_detector(self):
        from unittest.mock import patch
        with patch('structural_completion.structural_bounds',side_effect=AssertionError('must not run')):plan=completion_plan(self.doc,self.binary,self.request('support',[[0,0,0],[1,.5,1]]))
        self.assertEqual(plan['strategy']['automatic_region'],False)
    def test_separate_closed_solids_preserves_attributes(self):
        boxes=trimesh.util.concatenate([trimesh.creation.box(),trimesh.creation.box(transform=trimesh.transformations.translation_matrix([2,0,0]))]);boxes.export(self.path);doc,binary,_=read_glb(self.path);set_part_ids(doc);part=parts_catalog(doc)[0];old={i:accessor_array(doc,binary,i).tobytes() for m in doc['meshes'] for p in m['primitives'] for i in p['attributes'].values()};result=separate_solids(doc,binary,{'part_ids':[part['id']],'name':'独立支撑'});self.assertEqual(len(result['components']),2);self.assertEqual(result['new_inferred_faces'],0);self.assertEqual({i:accessor_array(doc,binary,i).tobytes() for i in old},old)
    def test_protocol_accepts_group_and_rejects_unsaved_faces(self):
        request=AssetEditRequest(operation='complete_part',completion_profile='support',part_ids=['a','b']);self.assertEqual(request.completion_profile,'support')
        with self.assertRaises(ValueError):AssetEditRequest(operation='separate_solids',part_ids=['a'],face_selection=[{'part_id':'a','faces':[0]}])
if __name__=='__main__':unittest.main(verbosity=2)

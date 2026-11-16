import copy,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np,trimesh
from services.api.glb_document import read_glb,parts_catalog,selected_primitives,write_glb,compact_static
from services.api.models import AssetEditRequest
from reconstruct_parts import keep_single_solid,reconstruct_parts,solid_candidate,source_deviation
from winding_surface import winding_surface
from furniture_parts import primitive_data
from part_tools import reconstructed_scope,translate_parts,export_parts

class SolidReconstructionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.folder=Path(self.temp.name)
    def asset(self):
        scene=trimesh.Scene();scene.add_geometry(trimesh.creation.icosphere(subdivisions=2),node_name='pillow');other=trimesh.creation.box();other.apply_translation([4,0,0]);scene.add_geometry(other,node_name='frame');path=self.folder/'source.glb';scene.export(path)
        d,b,e=read_glb(path);parts=parts_catalog(d)
        for i,(part,p) in enumerate(selected_primitives(d,[])):p.setdefault('extras',{}).update(form_logical_group_id=f'group_{i}',form_group_kind='ai_semantic_instance')
        return d,b,e,parts
    def test_winding_orientation_does_not_change_for_translated_open_part(self):
        m=trimesh.creation.icosphere(subdivisions=2);m.update_faces(m.triangles_center[:,2]>.0);m.remove_unreferenced_vertices();offset=np.array([15.,-2.,-13.])
        a,_=winding_surface(m,resolution=40,observed_distance=True);b,_=winding_surface(m.copy().apply_translation(offset),resolution=40,observed_distance=True)
        self.assertTrue(a.is_watertight and b.is_watertight);np.testing.assert_allclose(a.bounds,b.bounds-offset,atol=.002)
    def test_significant_secondary_solid_is_rejected(self):
        a=trimesh.creation.icosphere(subdivisions=1);b=a.copy().apply_translation([3,0,0])
        with self.assertRaisesRegex(ValueError,'多个明显实体'):keep_single_solid(trimesh.util.concatenate([a,b]))
    def test_tiny_generated_island_is_measured_and_source_deviation_still_checked(self):
        a=trimesh.creation.icosphere(subdivisions=1);b=a.copy().apply_scale(.001).apply_translation([3,0,0]);m,e=keep_single_solid(trimesh.util.concatenate([a,b]));self.assertEqual(e['discarded_reconstructed_components'],1);self.assertGreater(e['discarded_reconstructed_area_fraction'],0);self.assertAlmostEqual(m.area,a.area)
        moved=a.copy().apply_translation([1,0,0]);self.assertGreater(source_deviation(a,moved)['source_p95_diagonal_ratio'],.1)
    def test_closed_source_is_kept_and_bad_winding_refused(self):
        m=trimesh.creation.icosphere(subdivisions=1);_,e=solid_candidate(m);self.assertTrue(e['already_closed']);m.invert()
        with self.assertRaisesRegex(ValueError,'闭合网格'):solid_candidate(m)
    def test_reconstructed_whole_group_preserves_neighbour_and_roundtrip(self):
        d,b,e,parts=self.asset();target=parts[0]['id'];other=parts[1]['id'];before=copy.deepcopy(next(p for part,p in selected_primitives(d,[other])))
        m=trimesh.creation.icosphere(subdivisions=2);evidence={'already_closed':False,'after':{},'method':{'grid_step_source_units':.02}}
        with patch('reconstruct_parts.solid_candidate',return_value=(m,evidence)):
            result=reconstruct_parts(d,b,{'part_ids':[target]})
        self.assertEqual(next(p for part,p in selected_primitives(d,[other])),before);self.assertEqual(result['part_group_ids'],['group_0']);self.assertFalse(result['semantic_boundary_verified'])
        p=[p for p in parts_catalog(d) if p['logical_group_id']=='group_0'];self.assertTrue(all(x['completion_role'] in ('reconstructed_surface','inferred_interface') for x in p));write_glb(self.folder/'out.glb',d,compact_static(d,b),e);read_glb(self.folder/'out.glb')
    def test_texture_is_refused_without_changing_source(self):
        d,b,e,parts=self.asset();p=selected_primitives(d,[parts[0]['id']])[0][1];p['attributes']['TEXCOORD_0']=p['attributes']['POSITION'];before=copy.deepcopy(d);data=bytes(b)
        with self.assertRaisesRegex(ValueError,'带贴图'):reconstruct_parts(d,b,{'part_ids':[parts[0]['id']]})
        self.assertEqual(d,before);self.assertEqual(bytes(b),data)
    def test_scope_never_drops_unknown_id(self):
        d,b,e,parts=self.asset()
        with self.assertRaises(ValueError):reconstructed_scope(d,[parts[0]['id'],'missing'])
    def test_technical_patches_move_and_export_as_one_group(self):
        d,b,e,parts=self.asset();part,p=selected_primitives(d,[parts[0]['id']])[0];p['extras']['form_group_kind']='reconstructed_logical_part';mesh=d['meshes'][d['nodes'][part['node']]['mesh']];mesh['primitives'].append(copy.deepcopy(p));d['nodes'][part['node']].setdefault('extras',{}).setdefault('form_part_ids',{})['1']='cap'
        ids=reconstructed_scope(d,[part['id']]);self.assertEqual(set(ids),{part['id'],'cap'})
        moved=copy.deepcopy(d);result=translate_parts(moved,bytearray(b),{'part_ids':['cap'],'translation':[0,1,0]});self.assertEqual(set(result['part_ids']),set(ids))
        export=copy.deepcopy(d);result=export_parts(export,bytearray(b),{'part_ids':['cap']});self.assertEqual(set(result['part_ids']),set(ids))
    def test_protocol_requires_saved_groups(self):
        for data in ({},{'part_ids':['a'],'face_selection':[{'part_id':'a','faces':[0]}]},{'part_ids':['a'],'completion_bounds':[[0,0,0],[1,1,1]]}):
            with self.assertRaises(ValueError):AssetEditRequest(operation='reconstruct_parts',**data)
        self.assertEqual(AssetEditRequest(operation='reconstruct_parts',part_ids=['a'],completion_preview_id='b'*32).operation,'reconstruct_parts')
    def test_observed_bolster_rebuilds_full_radius_instead_of_a_hollow_half(self):
        m=trimesh.creation.cylinder(radius=.2,height=1.4,sections=64).subdivide().subdivide();m.update_faces(m.face_normals[:,0]<.85);m.remove_unreferenced_vertices()
        candidate,e=solid_candidate(m,'bolster');self.assertTrue(candidate.is_watertight);self.assertEqual(len(candidate.split()),1);self.assertGreater(candidate.volume,np.pi*.2**2*1.4*.85);self.assertEqual(e['method']['method'],'observed_cylinder_axis_and_angular_radius_profile_with_end_caps')

if __name__=='__main__':unittest.main(verbosity=2)

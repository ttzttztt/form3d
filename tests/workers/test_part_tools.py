import copy,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'services/workers')]
import numpy as np
from services.api.geometry import build_template,validate_glb
from services.api.models import JobRequest,AssetEditRequest,PartPromptRequest,PartExportRequest
from services.api.glb_document import read_glb,write_glb,set_part_ids,parts_catalog,compact_static
from part_tools import unwrap_uv,translate_parts,export_parts
from edit_asset import accessor_array,node_world_matrices
from verify_asset_upgrade import signature
def triangles(doc,binary):
    result={};world=node_world_matrices(doc)
    for p in parts_catalog(doc):
        pr=doc['meshes'][doc['nodes'][p['node']]['mesh']]['primitives'][p['primitive']];v=accessor_array(doc,binary,pr['attributes']['POSITION']);f=accessor_array(doc,binary,pr['indices']).reshape(-1,3);result[p['id']]=(np.c_[v,np.ones(len(v))]@world[p['node']].T)[f,:3]
    return result
class PartToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)/'original.glb';build_template(JobRequest(image_id='a'*32,template='table'),self.path);self.doc,self.binary,self.extra=read_glb(self.path);set_part_ids(self.doc)
    def save(self):
        output=Path(self.temp.name)/'result.glb';self.binary=compact_static(self.doc,self.binary);write_glb(output,self.doc,self.binary,self.extra);self.assertEqual(validate_glb(output)['errors'],0);return output
    def test_xatlas_retains_world_triangles_and_materials(self):
        before=signature(self.path);materials=copy.deepcopy(self.doc.get('materials'));e=unwrap_uv(self.doc,self.binary,{'part_ids':[parts_catalog(self.doc)[0]['id']]});self.assertEqual(e['parts'][0]['algorithm'],'xatlas');self.assertEqual(signature(self.save()),before);self.assertEqual(self.doc['materials'],materials)
    def test_six_chart_unwrap_retains_world_triangles_and_valid_uv(self):
        before=signature(self.path);e=unwrap_uv(self.doc,self.binary,{'part_ids':[],'uv_unwrap_mode':'box'});self.assertTrue(all(p['algorithm']=='six_normal_charts' for p in e['parts']));self.assertEqual(signature(self.save()),before)
        for part in parts_catalog(self.doc):
            p=self.doc['meshes'][self.doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']];uv=accessor_array(self.doc,self.binary,p['attributes']['TEXCOORD_0']);self.assertTrue(np.isfinite(uv).all());self.assertGreaterEqual(uv.min(),0);self.assertLessEqual(uv.max(),1)
    def test_proxy_unwrap_keeps_original_world_triangles(self):
        before=signature(self.path);e=unwrap_uv(self.doc,self.binary,{'part_ids':[parts_catalog(self.doc)[0]['id']],'uv_unwrap_mode':'proxy'});self.assertEqual(e['parts'][0]['algorithm'],'proxy_xatlas_transfer');self.assertEqual(signature(self.save()),before)
    def test_cylinder_unwrap_keeps_original_world_triangles(self):
        before=signature(self.path);e=unwrap_uv(self.doc,self.binary,{'part_ids':[parts_catalog(self.doc)[0]['id']],'uv_unwrap_mode':'cylinder','axis':'y'});self.assertEqual(e['parts'][0]['algorithm'],'continuous_cylinder_and_caps');self.assertEqual(signature(self.save()),before)
    def test_uv_quality_detects_seams_and_collapsed_area(self):
        from uv_quality import uv_diagnostics
        vertices=np.array([[0,0,0],[1,0,0],[1,1,0],[0,0,0],[1,1,0],[0,1,0]],dtype=float);faces=np.array([[0,1,2],[3,4,5]])
        continuous=uv_diagnostics(vertices,faces,vertices[:,:2]);self.assertEqual(continuous['normalized_seam_length'],0);self.assertAlmostEqual(continuous['geometric_mean_anisotropy'],1)
        tex=vertices[:,:2].copy();tex[3:]+=2;seamed=uv_diagnostics(vertices,faces,tex);self.assertAlmostEqual(seamed['normalized_seam_length'],1)
        collapsed=uv_diagnostics(vertices,faces,np.zeros((6,2)));self.assertEqual(collapsed['collapsed_geometry_area_fraction'],1)
    def test_auto_uv_guard_rejects_seam_and_stretch_regressions(self):
        from uv_quality import prefer_proxy
        baseline={'normalized_seam_length':10,'geometric_mean_anisotropy':1.05,'collapsed_geometry_area_fraction':0,'area_fraction_anisotropy_over_4':0}
        candidate={**baseline,'normalized_seam_length':8}
        self.assertTrue(prefer_proxy(baseline,candidate))
        for change in ({'normalized_seam_length':11},{'geometric_mean_anisotropy':2},{'collapsed_geometry_area_fraction':.01},{'area_fraction_anisotropy_over_4':.02},{'normalized_seam_length':float('nan')}):
            self.assertFalse(prefer_proxy(baseline,{**candidate,**change}))
    def test_auto_uv_fallback_reports_actual_box_algorithm(self):
        from unittest.mock import patch
        before=signature(self.path)
        with patch('part_tools.AUTO_PROXY_FACE_LIMIT',0),patch('uv_quality.prefer_proxy',return_value=False):
            e=unwrap_uv(self.doc,self.binary,{'part_ids':[parts_catalog(self.doc)[0]['id']],'uv_unwrap_mode':'auto'})
        part=e['parts'][0];self.assertEqual(part['algorithm'],'six_normal_charts');self.assertFalse(part['auto_quality_comparison']['proxy_selected']);self.assertIn('proxy_attempt',part);self.assertEqual(signature(self.save()),before)
    def test_world_translation_of_one_part_retains_other_parts(self):
        before=triangles(self.doc,self.binary);identity=parts_catalog(self.doc)[0]['id'];translate_parts(self.doc,self.binary,{'part_ids':[identity],'translation':[.2,-.1,.3]});after=triangles(self.doc,self.binary)
        for key,t in before.items():np.testing.assert_allclose(after[key],t+np.array([.2,-.1,.3]) if key==identity else t,atol=2e-7)
        self.save()
    def test_translation_keeps_float32_vertex_buffers_exact(self):
        indices={p['attributes']['POSITION'] for m in self.doc['meshes'] for p in m['primitives']};before={i:accessor_array(self.doc,self.binary,i).tobytes() for i in indices};identity=parts_catalog(self.doc)[0]['id'];result=translate_parts(self.doc,self.binary,{'part_ids':[identity],'translation':[0,0,1.8]});self.assertTrue(result['local_vertex_attributes_preserved'])
        self.assertEqual({i:accessor_array(self.doc,self.binary,i).tobytes() for i in indices},before);self.save()
    def test_export_exact_selected_part_with_world_transforms(self):
        before=triangles(self.doc,self.binary);identity=parts_catalog(self.doc)[1]['id'];export_parts(self.doc,self.binary,{'part_ids':[identity]});self.save();after=triangles(self.doc,self.binary);self.assertEqual(list(after),[identity]);np.testing.assert_array_equal(after[identity],before[identity])
    def test_export_unknown_part_refused(self):
        with self.assertRaises(ValueError):export_parts(self.doc,self.binary,{'part_ids':['unknown']})
    def test_export_with_pbr_extension_removes_unselected_meshes(self):
        self.doc['extensionsUsed']=['KHR_materials_ior'];self.doc['materials'][0].setdefault('extensions',{})['KHR_materials_ior']={'ior':1.5};identity=parts_catalog(self.doc)[0]['id'];export_parts(self.doc,self.binary,{'part_ids':[identity]});out=self.save();doc,_,_=read_glb(out);self.assertEqual(len(doc['meshes']),1);self.assertEqual(doc['materials'][0]['extensions']['KHR_materials_ior']['ior'],1.5)
    def test_export_drops_vertices_not_used_by_selected_faces(self):
        from asset_operations import append_array
        part=parts_catalog(self.doc)[0];p=self.doc['meshes'][self.doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']];f=accessor_array(self.doc,self.binary,p['indices']).reshape(-1,3)[:2];p['indices']=append_array(self.doc,self.binary,f.ravel(),'SCALAR',5125,34963);export_parts(self.doc,self.binary,{'part_ids':[part['id']]});self.save();p=self.doc['meshes'][0]['primitives'][0];self.assertLessEqual(self.doc['accessors'][p['attributes']['POSITION']]['count'],6)
    def test_translation_request_rejects_empty_zero_nan_and_large(self):
        for values in ({'part_ids':[],'translation':[1,0,0]},{'part_ids':['a'],'translation':[0,0,0]},{'part_ids':['a'],'translation':[float('nan'),0,0]},{'part_ids':['a'],'translation':[6,0,0]}):
            with self.assertRaises(ValueError):AssetEditRequest(operation='translate_parts',**values)
    def test_prompt_and_export_requests_are_bounded(self):
        with self.assertRaises(ValueError):PartExportRequest(part_ids=[])
        with self.assertRaises(ValueError):PartPromptRequest(views=[])
        with self.assertRaises(ValueError):PartPromptRequest(views=[{'image':'a'*60,'point':{'x':1.2,'y':0}}])
if __name__=='__main__':unittest.main(verbosity=2)

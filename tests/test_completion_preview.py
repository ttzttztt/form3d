import copy,hashlib,json,shutil,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from services.api.models import AssetEditRequest,JobRequest
from services.api.store import Store
from services.api.geometry import build_template
from services.api.completion_preview import preview_completion,verified_preview
from services.api.asset_editor import edit_asset

class CompletionPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name));self.job={'id':'a'*32,'status':'awaiting_review','request':JobRequest(image_id='b'*32).model_dump(),'events':[],'model_url':'/source.glb'}
        self.store.create_job(self.job,'','');self.folder=self.store.root/'jobs'/self.job['id'];self.folder.mkdir(parents=True)
        self.source=self.folder/'model.glb';build_template(JobRequest(image_id='b'*32,template='table'),self.source)
        self.request=AssetEditRequest(operation='complete_part',part_ids=['node_0_primitive_0'],completion_shape='box',completion_bounds=[[.1,.2,.3],[.7,.8,.9]],name='seat')
    def worker(self,argv,**kwargs):
        out=Path(argv[argv.index('--output')+1]);shutil.copyfile(self.source,out/'model.glb');shutil.copyfile(self.source,out/'diagnostic.glb')
        digest=hashlib.sha256(self.source.read_bytes()).hexdigest()
        (out/'manifest.json').write_text(json.dumps({'model_sha256':digest,'source_sha256':digest,'operation':{'part_group_ids':['test']}}),encoding='utf-8')
        return SimpleNamespace(returncode=0)
    def preview(self):
        with patch('services.api.completion_preview.local_python',return_value='python'),patch('services.api.completion_preview.subprocess.run',side_effect=self.worker),patch('services.api.completion_preview.validate_glb',return_value={}):
            return preview_completion(self.store,self.job,self.request)
    def test_preview_is_read_only_and_commit_reuses_exact_model(self):
        before=copy.deepcopy(self.store.job(self.job['id']));result=self.preview()
        self.assertEqual(self.store.job(self.job['id']),before);self.assertFalse(result['published'])
        request=self.request.model_copy(update={'completion_preview_id':result['preview_id']})
        with patch('services.api.asset_editor.subprocess.run') as worker,patch('services.api.asset_editor.validate_glb',return_value={}):catalog=edit_asset(self.store,self.job['id'],request);worker.assert_not_called()
        self.assertEqual((self.folder/'assets'/catalog['version']/'model.glb').read_bytes(),self.source.read_bytes())
        self.assertEqual(catalog['manifest']['completion_preview_id'],result['preview_id'])
    def test_changed_bounds_scope_and_shape_cannot_save_old_preview(self):
        result=self.preview()
        for change in ({'completion_bounds':[[0,0,0],[1,1,1]]},{'part_ids':['other']},{'completion_shape':'contour'},{'name':'changed'},{'face_selection':[{'part_id':'a','faces':[1]}]}):
            data=self.request.model_dump();data.update(change,completion_preview_id=result['preview_id']);request=AssetEditRequest(**data)
            with self.assertRaisesRegex(ValueError,'已变化'):verified_preview(self.store,self.job,request,self.source)
    def test_tampered_source_and_preview_are_refused(self):
        result=self.preview();request=self.request.model_copy(update={'completion_preview_id':result['preview_id']})
        original=self.source.read_bytes();self.source.write_bytes(original+b'changed')
        with self.assertRaisesRegex(ValueError,'已变化'):verified_preview(self.store,self.job,request,self.source)
        self.source.write_bytes(original);path=self.folder/'completion_previews'/result['preview_id']/'model.glb';path.write_bytes(b'broken')
        with self.assertRaisesRegex(ValueError,'校验失败'):verified_preview(self.store,self.job,request,self.source)
    def test_version_changed_during_preview_is_refused(self):
        def changed(argv,**kwargs):
            value=self.worker(argv,**kwargs);self.store.update(self.job['id'],lambda j:j.update(current_asset_version='c'*32));return value
        with patch('services.api.completion_preview.local_python',return_value='python'),patch('services.api.completion_preview.subprocess.run',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'期间源版本已变化'):preview_completion(self.store,self.job,self.request)
    def test_preview_id_is_strict_and_cannot_be_used_for_other_operations(self):
        for data in ({'completion_preview_id':'../model'},{'completion_preview_id':'d'*32,'operation':'material'}):
            with self.assertRaises(ValueError):AssetEditRequest(**data)
    def test_solid_reconstruction_requires_preview_and_reuses_exact_bytes(self):
        self.request=AssetEditRequest(operation='reconstruct_parts',part_ids=['node_0_primitive_0'])
        with self.assertRaisesRegex(ValueError,'先查看独立'):edit_asset(self.store,self.job['id'],self.request)
        result=self.preview();request=self.request.model_copy(update={'completion_preview_id':result['preview_id']})
        with patch('services.api.asset_editor.subprocess.run') as worker,patch('services.api.asset_editor.validate_glb',return_value={}):
            catalog=edit_asset(self.store,self.job['id'],request);worker.assert_not_called()
        self.assertEqual((self.folder/'assets'/catalog['version']/'model.glb').read_bytes(),self.source.read_bytes())
    def test_preview_cannot_change_geometry_operation(self):
        result=self.preview();request=AssetEditRequest(operation='reconstruct_parts',part_ids=self.request.part_ids,completion_preview_id=result['preview_id'])
        with self.assertRaisesRegex(ValueError,'已变化'):verified_preview(self.store,self.job,request,self.source)
    def test_only_one_cpu_reconstruction_preview_runs_and_failure_releases_lock(self):
        import subprocess
        from services.api.completion_preview import RECONSTRUCTION_LOCK
        self.request=AssetEditRequest(operation='reconstruct_parts',part_ids=['node_0_primitive_0'])
        with RECONSTRUCTION_LOCK:
            with self.assertRaisesRegex(ValueError,'正在计算'):self.preview()
        with patch('services.api.completion_preview.local_python',return_value='python'),patch('services.api.completion_preview.subprocess.run',side_effect=subprocess.TimeoutExpired('worker',360)):
            with self.assertRaises(subprocess.TimeoutExpired):preview_completion(self.store,self.job,self.request)
        self.assertTrue(RECONSTRUCTION_LOCK.acquire(blocking=False));RECONSTRUCTION_LOCK.release()

if __name__=='__main__':unittest.main(verbosity=2)

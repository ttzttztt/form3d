import base64,copy,io,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from fastapi.testclient import TestClient
from PIL import Image
from services.api.app import create_app
from services.api.models import JobRequest,PartPromptRequest
from services.api.geometry import build_template
from services.api.part_prompt import propose_part
class PartContracts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.app=create_app(self.temp.name);self.client=TestClient(self.app);self.addCleanup(self.client.close);store=self.app.state.store
        image=Image.new('RGB',(128,128),'white');out=io.BytesIO();image.save(out,format='PNG')
        with patch('services.api.app.detector_status',return_value={'available':False}):self.image=self.client.post('/api/images',files={'file':('test.png',out.getvalue(),'image/png')}).json()['id']
        self.job={'id':'a'*32,'name':'test','status':'awaiting_review','stage':'review','request':JobRequest(image_id=self.image,route='local',local_engine='triposr').model_dump(),'events':[],'model_url':'/api/jobs/'+'a'*32+'/files/model.glb','review_status':'pending'};store.create_job(self.job,'','');folder=store.root/'jobs'/self.job['id'];folder.mkdir(parents=True);build_template(JobRequest(image_id=self.image,template='table'),folder/'model.glb')
    def test_comparison_filters_different_target(self):
        other=copy.deepcopy(self.job);other['id']='b'*32;other['request']['target']['width']=.5;self.app.state.store.create_job(other,'','');r=self.client.get('/api/jobs/'+self.job['id']+'/reconstruction-comparison');self.assertEqual(r.status_code,200);self.assertEqual([c['id'] for c in r.json()['candidates']],[self.job['id']]);self.assertFalse(r.json()['similarity_measured'])
    def test_alternative_reuses_input_engine_and_forbids_external(self):
        with patch('services.api.app.local3d_status',return_value={'engines':{'hunyuan-mini':{'available':True}}}),patch.object(self.app.state.executor,'submit') as submit:
            root='/api/jobs/'+self.job['id']+'/reconstruction-comparison';a=self.client.post(root,json={'engine':'hunyuan-mini'});b=self.client.post(root,json={'engine':'hunyuan-mini'});self.assertEqual(a.status_code,200,a.text);self.assertEqual(a.json()['id'],b.json()['id']);self.assertEqual(a.json()['request']['target'],self.job['request']['target']);self.assertFalse(a.json()['request']['allow_external']);self.assertFalse(a.json()['request']['local_auto_retry']);self.assertEqual(submit.call_count,1)
    def test_same_crop_integer_and_float_coordinates_share_comparison(self):
        other=copy.deepcopy(self.job);other['id']='c'*32;other['request']['local_engine']='hunyuan-mini';other['request']['target']={k:float(v) for k,v in other['request']['target'].items()};self.app.state.store.create_job(other,'','');r=self.client.get('/api/jobs/'+self.job['id']+'/reconstruction-comparison');self.assertEqual({c['id'] for c in r.json()['candidates']},{self.job['id'],other['id']})
    def test_quality_profiles_are_separate_and_repeated_requests_reuse(self):
        with patch('services.api.app.local3d_status',return_value={'engines':{'hunyuan-mini':{'available':True}}}),patch.object(self.app.state.executor,'submit') as submit:
            root='/api/jobs/'+self.job['id']+'/reconstruction-comparison';detail=self.client.post(root,json={'engine':'hunyuan-mini','quality':'structure'});regular=self.client.post(root,json={'engine':'hunyuan-mini','quality':'balanced'});repeat=self.client.post(root,json={'engine':'hunyuan-mini','quality':'structure'});self.assertEqual(detail.status_code,200,detail.text);self.assertNotEqual(detail.json()['id'],regular.json()['id']);self.assertEqual(detail.json()['id'],repeat.json()['id']);self.assertEqual(submit.call_count,2);self.assertEqual(detail.json()['request']['local_quality'],'structure')
    def test_labelled_prompts_are_bounded_and_require_positive_anchor(self):
        good={'views':[{'image':'a'*60,'point':{'x':.5,'y':.5},'points':[{'x':.5,'y':.5,'label':1},{'x':.8,'y':.5,'label':0}]}],'candidate_range':'medium'};body=PartPromptRequest(**good);self.assertEqual(body.views[0].points[1].label,0)
        for bad in ([{'x':.5,'y':.5,'label':0}],[{'x':.5,'y':.5,'label':1}]*25):
            good['views'][0]['points']=bad
            with self.assertRaises(ValueError):PartPromptRequest(**good)
    def test_prompt_missing_runtime_and_invalid_payload(self):
        with patch('services.api.part_prompt.segmentation_status',return_value={'available':False}):
            r=self.client.post('/api/jobs/'+self.job['id']+'/asset/part-proposal',json={'views':[{'image':'a'*60,'point':{'x':.5,'y':.5}}]});self.assertEqual(r.status_code,409)
        self.assertEqual(self.client.post('/api/jobs/'+self.job['id']+'/asset/part-proposal',json={'views':[]}).status_code,422)
    def test_invalid_render_is_refused_before_worker(self):
        with patch('services.api.part_prompt.segmentation_status',return_value={'available':True}),patch('services.api.part_prompt.subprocess.run') as worker:
            with self.assertRaises(ValueError):propose_part(self.app.state.store,self.job,PartPromptRequest(views=[{'image':'a'*60,'point':{'x':.5,'y':.5}}]))
            worker.assert_not_called()
    def test_subset_export_requires_explicit_part_ids(self):
        self.assertEqual(self.client.post('/api/jobs/'+self.job['id']+'/asset/export-parts',json={'part_ids':[]}).status_code,422)
    def test_complete_part_rejects_invalid_scope_and_bounds(self):
        root='/api/jobs/'+self.job['id']+'/asset/completion-plan'
        with patch('services.api.asset_editor.subprocess.run') as worker:
            self.assertEqual(self.client.post(root,json={'operation':'complete_part'}).status_code,422)
            self.assertEqual(self.client.post(root,json={'operation':'complete_part','part_ids':['a'],'completion_bounds':[[0,0,0],[0,1,1]]}).status_code,422)
            worker.assert_not_called()
    def test_complete_plan_does_not_publish_version(self):
        root='/api/jobs/'+self.job['id']+'/asset/completion-plan'
        with patch('services.api.app.plan_completion',return_value={'version':'original','completion_bounds':[[.2,.2,.2],[.8,.8,.8]]}) as planner:
            response=self.client.post(root,json={'operation':'complete_part','part_ids':['a']});self.assertEqual(response.status_code,200,response.text);planner.assert_called_once()
        self.assertNotIn('asset_versions',self.app.state.store.job(self.job['id']))
    def test_structural_profiles_accept_a_logical_group_scope(self):
        root='/api/jobs/'+self.job['id']+'/asset/completion-plan'
        with patch('services.api.app.plan_completion',return_value={'version':'original'}) as planner:
            for profile in ('support','slab'):
                response=self.client.post(root,json={'operation':'complete_part','completion_profile':profile,'part_ids':['observed','cap']});self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(planner.call_count,2)
    def test_closed_component_split_requires_saved_scope(self):
        root='/api/jobs/'+self.job['id']+'/asset/versions'
        self.assertEqual(self.client.post(root,json={'operation':'separate_solids','part_ids':[]}).status_code,422)
        self.assertEqual(self.client.post(root,json={'operation':'separate_solids','part_ids':['a'],'face_selection':[{'part_id':'a','faces':[0]}]}).status_code,422)
if __name__=='__main__':unittest.main(verbosity=2)

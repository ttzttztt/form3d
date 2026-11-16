import io
import json
import os
import struct
import tempfile
import time
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from services.api.app import create_app
from services.api.geometry import build_template, inspect_glb
from services.api.models import JobRequest
from services.api.provider import SubmissionUnknown, generate_meshy
from services.api.store import Store
from services.api.assistant_assets import attach_asset
from services.api.preflight import InputNeedsAttention
from services.api.output_quality import OutputNeedsAttention


def picture():
    output = io.BytesIO()
    image = Image.new("RGBA", (160, 120), "white")
    ImageDraw.Draw(image).rectangle((35, 20, 125, 100), fill="#ad947a")
    image.save(output, "PNG")
    return output.getvalue()


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"MESHY_API_KEY": ""})
        self.environment.start()
        self.application = create_app(self.temporary.name)
        self.client = TestClient(self.application)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.environment.stop()
        self.temporary.cleanup()

    def upload(self):
        response = self.client.post("/api/images", files={"file": ("reference.png", picture(), "image/png")})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_curated_samples_use_the_central_library(self):
        samples = self.client.get('/api/samples').json()
        self.assertEqual(len(samples), 4)
        for sample in samples:
            model = self.client.get(sample['model_url'])
            preview = self.client.get(sample['preview_url'])
            self.assertEqual(model.status_code, 200)
            self.assertEqual(model.content[:4], b'glTF')
            self.assertEqual(preview.status_code, 200)
            self.assertTrue(preview.content.startswith(b'\x89PNG'))

    def create(self, **overrides):
        body = {"image_id": self.upload()["id"], "name": "测试置物架", "route": "template"}
        body.update(overrides)
        result = self.client.post("/api/jobs", json=body)
        self.assertEqual(result.status_code, 202, result.text)
        return result.json()

    def finished(self, job):
        for _ in range(100):
            value = self.client.get("/api/jobs/" + job["id"]).json()
            if value["status"] not in ("queued", "running"):
                return value
            time.sleep(0.02)
        self.fail("Local generation did not finish")

    def test_complete_review_and_delivery(self):
        task = self.finished(self.create(dimensions={"width": 0.8, "depth": 0.4, "height": 1.2, "confirmed": True}))
        self.assertEqual(task["status"], "awaiting_review")
        self.assertEqual(task["metrics"]["dimensions_m"], [0.8, 1.2, 0.4])
        self.assertFalse(task["report"]["ar_true_scale_ready"])
        self.assertIn(task["report"]["checks"]["full_gltf_validator"], ("pass", "not_run"))
        review = self.client.post(f'/api/jobs/{task["id"]}/review', json={"decision": "accept"})
        self.assertEqual(review.status_code, 200, review.text)
        self.assertEqual(review.json()["status"], "completed")
        package = self.client.get(f'/api/jobs/{task["id"]}/download')
        with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
            self.assertIn("model.glb", archive.namelist())
            self.assertEqual(json.loads(archive.read("quality_report.json"))["review_status"], "accepted")
            self.assertEqual(json.loads(archive.read("metadata.json"))["review_status"], "accepted")

    def test_crop_and_mask_preserve_original(self):
        image = self.upload()
        task = self.finished(self.create(image_id=image["id"], target={"x": .25, "y": .25, "width": .5, "height": .5},
                                         strokes=[{"points": [{"x": .5, "y": .5}], "radius": .035}]))
        self.assertEqual(task["status"], "awaiting_review")
        result = self.client.get(task["prepared_url"])
        prepared = Image.open(io.BytesIO(result.content))
        self.assertEqual(prepared.size, (80, 60))
        self.assertEqual(prepared.getpixel((40, 30))[3], 0)
        original = Path(self.temporary.name) / "images" / image["id"] / "original.bin"
        self.assertEqual(original.read_bytes(), picture())

    def test_concurrent_idempotency_and_conflict(self):
        image = self.upload()
        body = {"image_id": image["id"], "name": "幂等任务", "route": "template"}
        def send(_):
            return self.client.post("/api/jobs", json=body, headers={"Idempotency-Key": "stable-request"})
        with ThreadPoolExecutor(max_workers=5) as pool:
            responses = list(pool.map(send, range(5)))
        self.assertTrue(all(response.status_code == 202 for response in responses))
        self.assertEqual(len({response.json()["id"] for response in responses}), 1)
        self.assertEqual(len(self.client.get("/api/jobs").json()), 1)
        body["name"] = "changed"
        self.assertEqual(self.client.post("/api/jobs", json=body, headers={"Idempotency-Key": "stable-request"}).status_code, 409)

    def test_missing_provider_does_not_fallback(self):
        image = self.upload()
        response = self.client.post("/api/jobs", json={"image_id": image["id"], "route": "meshy", "allow_external": True})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.get("/api/jobs").json(), [])

    def test_cloud_requires_explicit_consent(self):
        response = self.client.post("/api/jobs", json={"image_id": self.upload()["id"], "route": "meshy"})
        self.assertEqual(response.status_code, 422)

    def test_invalid_dimensions_and_target(self):
        image = self.upload()
        for extra in [{"dimensions": {"width": 0}}, {"target": {"x": .9, "width": .5}}, {"levels": 20}, {"color": "bad"}]:
            response = self.client.post("/api/jobs", json={"image_id": image["id"], **extra})
            self.assertEqual(response.status_code, 422, response.text)

    def test_invalid_image_and_foreign_origin(self):
        result = self.client.post("/api/images", files={"file": ("fake.png", b"invalid", "image/png")})
        self.assertEqual(result.status_code, 422)
        self.assertEqual(self.client.get("/api/config", headers={"Origin": "https://untrusted.example"}).status_code, 403)
        self.assertEqual(self.client.get("/api/config", headers={"Host": "untrusted.example"}).status_code, 403)
        self.assertEqual(self.client.get("http://127.0.0.1:8123/api/config", headers={"Origin": "http://127.0.0.1:8123"}).status_code, 200)

    def test_rejected_result_and_immutable_review(self):
        task = self.finished(self.create())
        endpoint = f'/api/jobs/{task["id"]}/review'
        result = self.client.post(endpoint, json={"decision": "reject", "note": "支腿不一致"})
        self.assertEqual(result.json()["status"], "rejected")
        self.assertEqual(self.client.post(endpoint, json={"decision": "accept"}).status_code, 409)
        self.assertEqual(self.client.get(f'/api/jobs/{task["id"]}/files/../workbench.sqlite3').status_code, 404)

    def test_cancelled_job_cannot_be_resurrected(self):
        store = self.application.state.store
        item = {"id": "cancel-test", "status": "running", "events": []}
        store.create_job(item, "", "")
        store.update(item["id"], lambda value: value.update(status="cancelled"))
        store.event(item["id"], "review", "late result", status="awaiting_review")
        self.assertEqual(store.job(item["id"])["status"], "cancelled")
        self.assertEqual(self.client.post('/api/jobs/cancel-test/review', json={"decision": "accept"}).status_code, 409)

    def test_data_survives_store_reopen(self):
        task = self.finished(self.create())
        reopened = Store(Path(self.temporary.name))
        self.assertEqual(reopened.job(task["id"])["status"], "awaiting_review")
        self.assertEqual(reopened.image(task["request"]["image_id"])["width"], 160)

    def test_submission_unknown_is_never_retried(self):
        store = self.application.state.store
        store.create_job({"id": "remote-unknown", "status": "running", "submission_started": True, "provider_task_id": None, "events": []}, "", "")
        with patch.dict(os.environ, {"MESHY_API_KEY": "test-only"}), patch('httpx.Client.post') as submit:
            with self.assertRaises(SubmissionUnknown):
                generate_meshy(store, "remote-unknown", Path("unused.png"), Path("unused.glb"))
            submit.assert_not_called()

    def test_template_scale_and_face_winding(self):
        for name in ("shelf", "table", "cabinet"):
            path = Path(self.temporary.name) / (name + ".glb")
            request = JobRequest(image_id="a" * 32, template=name, dimensions={"width": 1.3, "depth": .45, "height": .75})
            metrics = build_template(request, path)
            for value, expected in zip(metrics["dimensions_m"], [1.3, .75, .45]):
                self.assertAlmostEqual(value, expected)
            self.assertGreater(inspect_glb(path)["triangles"], 0)
            data = path.read_bytes()
            length = struct.unpack_from('<I', data, 12)[0]
            doc = json.loads(data[20:20 + length])
            binary = data[28 + length:]
            for mesh in doc['meshes']:
                primitive = mesh['primitives'][0]
                position = doc['accessors'][primitive['attributes']['POSITION']]
                normal = doc['accessors'][primitive['attributes']['NORMAL']]
                offset = doc['bufferViews'][position['bufferView']]['byteOffset']
                normals_offset = doc['bufferViews'][normal['bufferView']]['byteOffset']
                vertices = struct.unpack_from('<72f', binary, offset)
                normals = struct.unpack_from('<72f', binary, normals_offset)
                for face in range(6):
                    base = face * 12
                    a, b, c = [vertices[base + i:base + i + 3] for i in (0, 3, 6)]
                    u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
                    cross = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
                    self.assertGreater(sum(cross[i] * normals[base+i] for i in range(3)), 0)

    def test_assistant_waits_for_real_model_instead_of_building_bookcase(self):
        task = self.finished(self.create(route="assistant", object_label="花瓶"))
        self.assertEqual(task["status"], "awaiting_assistant")
        self.assertNotIn("model_url", task)
        self.assertFalse((Path(self.temporary.name) / 'jobs' / task['id'] / 'model.glb').exists())
        self.assertEqual(self.client.get(task['prepared_url']).status_code, 200)
        # A real GLB fixture verifies attachment only, not photo reconstruction.
        model = Path(self.temporary.name) / 'authored-fixture.glb'
        build_template(JobRequest(image_id='a'*32, template='table'), model)
        imported = attach_asset(self.application.state.store, task['id'], model, ['test fixture'])
        self.assertEqual(imported['status'], 'awaiting_review')
        self.assertEqual(imported['report']['evidence']['geometry_source'], 'assistant_authored_blender_from_visual_reference')
        self.assertEqual(self.client.get(imported['model_url']).content[:4], b'glTF')

    def test_detection_requests_are_deduplicated(self):
        image = self.upload()
        with patch('services.api.app.detector_status', return_value={'available': True}), patch('services.api.app.analyze_image') as inference:
            with ThreadPoolExecutor(max_workers=5) as pool:
                responses = list(pool.map(lambda _: self.client.post(f'/api/images/{image["id"]}/analysis'), range(5)))
            self.assertTrue(all(response.status_code == 202 for response in responses))
            for _ in range(30):
                if inference.call_count: break
                time.sleep(.01)
            self.assertEqual(inference.call_count, 1)

    def test_unavailable_local_model_rejects_without_fallback(self):
        image = self.upload()
        with patch('services.api.app.local3d_status', return_value={'available': False}):
            # Default requests now select local automatic image-to-3D.
            result = self.client.post('/api/jobs', json={'image_id': image['id']})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.client.get('/api/jobs').json(), [])

    def test_local_result_is_validated_and_provenance_is_preserved(self):
        def fixture_worker(store, job_id, input_path, directory, check_cancelled, **kwargs):
            # Synthetic geometry is a transport fixture, not a reconstruction test.
            check_cancelled()
            build_template(JobRequest(image_id='a'*32, template='table'), directory / 'model.glb')
            for filename in ('foreground.png', 'model_input.png'):
                (directory / filename).write_bytes(picture())
            self.assertTrue(kwargs['remove_background'])
            return {'model': 'TripoSR', 'background_method': 'u2netp', 'offline': True}
        with patch('services.api.app.local3d_status', return_value={'available': True}), \
             patch('services.api.pipeline.generate_local', side_effect=fixture_worker), \
             patch('services.api.pipeline.generate_meshy') as cloud:
            task = self.finished(self.create(route='local'))
        self.assertEqual(task['status'], 'awaiting_review')
        self.assertFalse(any(event['stage'] == 'awaiting_assistant' for event in task['events']))
        self.assertEqual(task['report']['evidence']['geometry_source'], 'triposr_image_to_3d')
        self.assertEqual(task['report']['scale_status'], 'normalized_unverified')
        self.assertTrue(task['report']['local_inference']['offline'])
        self.assertEqual(self.client.get(task['model_url']).content[:4], b'glTF')
        self.assertEqual(self.client.get(task['model_input_url']).status_code, 200)
        self.assertEqual(self.client.get(task['foreground_url']).status_code, 200)
        cloud.assert_not_called()

    def test_local_failure_does_not_publish_mesh(self):
        with patch('services.api.app.local3d_status', return_value={'available': True}), \
             patch('services.api.pipeline.generate_local', side_effect=ValueError('local inference failed')):
            task = self.finished(self.create(route='local'))
        self.assertEqual(task['status'], 'failed')
        self.assertNotIn('model_url', task)
        self.assertEqual(self.client.get('/api/jobs/' + task['id'] + '/files/model.glb').status_code, 409)

    def test_untested_hunyuan_cannot_fallback_to_available_triposr(self):
        image = self.upload()
        with patch('services.api.app.local3d_status', return_value={
            'available': True, 'engines': {'triposr': {'available': True}, 'hunyuan-mini': {'available': False}}}):
            result = self.client.post('/api/jobs', json={
                'image_id': image['id'], 'route': 'local', 'local_engine': 'hunyuan-mini'})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.client.get('/api/jobs').json(), [])

    def test_hunyuan_geometry_transport_never_claims_generated_texture(self):
        def transport_fixture(store, job_id, input_path, directory, check_cancelled, **kwargs):
            # This tests the transport/report contract only, not neural inference.
            self.assertEqual(kwargs['engine'], 'hunyuan-mini')
            build_template(JobRequest(image_id='a'*32, template='table'), directory / 'model.glb')
            for filename in ('foreground.png', 'model_input.png'):
                (directory / filename).write_bytes(picture())
            return {'model': 'Hunyuan3D-2mini', 'mode': 'shape_only', 'background_method': 'provided_alpha', 'watertight': False}
        with patch('services.api.app.local3d_status', return_value={
                'available': True, 'engines': {'hunyuan-mini': {'available': True}}}), \
             patch('services.api.pipeline.generate_local', side_effect=transport_fixture):
            task = self.finished(self.create(route='local', local_engine='hunyuan-mini'))
        self.assertEqual(task['status'], 'awaiting_review')
        self.assertEqual(task['report']['evidence']['geometry_source'], 'hunyuan3d_2mini_image_to_shape')
        self.assertEqual(task['report']['evidence']['texture_source'], 'none_neutral_material')
        self.assertIn('不含纹理', ''.join(task['report']['warnings']))
        self.assertIn('并非完全封闭', ''.join(task['report']['warnings']))
        self.assertEqual(task['report']['checks']['appearance'], 'needs_review')

    def test_unavailable_explicit_sam_rejects_without_job(self):
        image=self.upload()
        with patch('services.api.app.local3d_status',return_value={'available':True}), \
             patch('services.api.app.segmentation_status',return_value={'available':False}):
            response=self.client.post('/api/jobs',json={
                'image_id':image['id'],'local_segmentation':'sam2'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.client.get('/api/jobs').json(),[])

    def test_segmentation_artifacts_and_report_are_preserved(self):
        # Transport fixtures are not SAM predictions or quality measurements.
        evidence={'method':'sam2_box','score_note':'not measured accuracy',
                  'hidden_surface_completion':False,'fixture_only':True}
        def transport_fixture(store,job_id,input_path,directory,check_cancelled,**kwargs):
            self.assertEqual(kwargs['segmentation'],'sam2')
            build_template(JobRequest(image_id='a'*32,template='table'),directory/'model.glb')
            for filename in ['foreground.png','model_input.png','segmented.png',
                             'segmentation_mask.png','segmentation_overlay.png']:
                (directory/filename).write_bytes(picture())
            (directory/'segmentation_summary.json').write_text(json.dumps(evidence))
            store.event(job_id,'segment_ready','transport fixture',
                        segmented_url=f'/api/jobs/{job_id}/files/segmented.png',
                        segmentation_mask_url=f'/api/jobs/{job_id}/files/segmentation_mask.png',
                        segmentation_overlay_url=f'/api/jobs/{job_id}/files/segmentation_overlay.png')
            return {'model':'TripoSR','background_method':'sam2_box','segmentation':evidence}
        with patch('services.api.app.local3d_status',return_value={'available':True}), \
             patch('services.api.app.segmentation_status',return_value={'available':True}), \
             patch('services.api.pipeline.generate_local',side_effect=transport_fixture):
            task=self.finished(self.create(route='local',local_segmentation='sam2'))
        self.assertEqual(task['status'],'awaiting_review')
        self.assertEqual(task['report']['evidence']['target_segmentation'],evidence)
        self.assertEqual(task['report']['checks']['appearance'],'needs_review')
        self.assertEqual(self.client.get(task['segmented_url']).status_code,200)
        self.assertEqual(self.client.get(task['segmentation_overlay_url']).status_code,200)
        with zipfile.ZipFile(io.BytesIO(self.client.get(f'/api/jobs/{task["id"]}/download').content)) as archive:
            self.assertEqual(json.loads(archive.read('segmentation_summary.json')),evidence)
            self.assertIn('segmentation_mask.png',archive.namelist())

    def test_local_input_block_never_publishes_or_resumes_cloud(self):
        evidence={'status':'blocked','reasons':[{'code':'fragmented_mask','message':'需要更换图片'}],
                  'warnings':[],'removed_alpha_pixels':0,'hidden_surface_completion':False}
        def blocked_fixture(store,job_id,input_path,directory,check_cancelled,**kwargs):
            # Contract fixture only; no claim about real OCR or masks.
            (directory/'cleaned.png').write_bytes(picture())
            (directory/'input_quality.json').write_text(json.dumps(evidence),encoding='utf-8')
            store.event(job_id,'input_checked','fixture',input_quality=evidence,
                        cleaned_url=f'/api/jobs/{job_id}/files/cleaned.png')
            raise InputNeedsAttention('需要更换图片')
        with patch('services.api.app.local3d_status',return_value={'available':True}), \
             patch('services.api.pipeline.generate_local',side_effect=blocked_fixture), \
             patch('services.api.pipeline.generate_meshy') as cloud:
            task=self.finished(self.create(route='local'))
        self.assertEqual(task['status'],'awaiting_input')
        self.assertEqual(task['attention_kind'],'local_input')
        self.assertEqual(task['input_quality'],evidence)
        self.assertNotIn('model_url',task)
        self.assertEqual(self.client.get(task['cleaned_url']).status_code,200)
        self.assertEqual(self.client.get(f'/api/jobs/{task["id"]}/files/input_quality.json').status_code,200)
        self.assertEqual(self.client.get(f'/api/jobs/{task["id"]}/files/model.glb').status_code,409)
        self.assertEqual(self.client.post(f'/api/jobs/{task["id"]}/resume').status_code,409)
        cloud.assert_not_called()

    def test_output_block_preserves_diagnostics_without_publishing_asset(self):
        def failed_geometry(store,job_id,input_path,directory,check_cancelled,**kwargs):
            candidate=directory/'attempts/01_hunyuan-mini';candidate.mkdir(parents=True)
            build_template(JobRequest(image_id='a'*32,template='table'),candidate/'model.glb')
            evidence={'status':'blocked','reasons':[{'code':'fixture_only','message':'几何异常'}],'warnings':[]}
            (directory/'geometry_quality.json').write_text(json.dumps(evidence))
            store.event(job_id,'geometry_checked','fixture',output_quality=evidence,
                        output_attempts=[{'index':1,'engine':'hunyuan-mini','status':'geometry_blocked'}])
            raise OutputNeedsAttention('几何异常')
        with patch('services.api.app.local3d_status',return_value={'available':True}),patch('services.api.pipeline.generate_local',side_effect=failed_geometry):
            task=self.finished(self.create(route='local'))
        self.assertEqual(task['attention_kind'],'local_output');self.assertNotIn('model_url',task)
        self.assertEqual(self.client.get(f'/api/jobs/{task["id"]}/files/model.glb').status_code,409)
        self.assertEqual(self.client.get(f'/api/jobs/{task["id"]}/files/geometry_quality.json').status_code,200)
        self.assertEqual(self.client.get(f'/api/jobs/{task["id"]}/attempts/1/model.glb').status_code,200)

    def test_asset_catalog_and_restore_preserve_original(self):
        task=self.finished(self.create())
        endpoint=f'/api/jobs/{task["id"]}/asset'
        catalog=self.client.get(endpoint).json();self.assertEqual(catalog['version'],'original')
        original=self.client.get(task['model_url']).content
        response=self.client.post(endpoint+'/versions',json={'operation':'restore_original','base_version':'original'})
        self.assertEqual(response.status_code,201,response.text)
        edited=response.json();self.assertEqual(edited['editor_review_status'],'unreviewed')
        self.assertEqual(self.client.get(edited['model_url']).content,original)
        self.assertEqual(self.client.get(task['model_url']).content,original)
        stale=self.client.post(endpoint+'/versions',json={'operation':'restore_original','base_version':'original'})
        self.assertEqual(stale.status_code,409)
        restored=self.client.post(endpoint+'/versions',json={'operation':'restore_version','base_version':edited['version'],'source_version':'original'})
        self.assertEqual(restored.status_code,201,restored.text)
        self.assertEqual(self.client.get(restored.json()['model_url']).content,original)

    def test_edit_review_is_independent_and_not_inherited(self):
        task=self.finished(self.create());endpoint=f'/api/jobs/{task["id"]}/asset'
        edit=self.client.post(endpoint+'/versions',json={'operation':'restore_original'}).json()
        review=f'/api/jobs/{task["id"]}/assets/{edit["version"]}/review'
        accepted=self.client.post(review,json={'decision':'accept'});self.assertEqual(accepted.status_code,200,accepted.text)
        self.assertEqual(accepted.json()['editor_review_status'],'accepted')
        self.assertEqual(self.client.get('/api/jobs/'+task['id']).json()['review_status'],'pending')
        self.assertEqual(self.client.post(review,json={'decision':'reject'}).status_code,409)
        newer=self.client.post(endpoint+'/versions',json={'operation':'restore_version','base_version':edit['version'],'source_version':edit['version']}).json()
        self.assertEqual(newer['editor_review_status'],'unreviewed')

    def test_version_archive_compare_and_storage_keep_bytes(self):
        task=self.finished(self.create());root=f'/api/jobs/{task["id"]}'
        original=self.client.get(task['model_url']).content
        a=self.client.post(root+'/asset/versions',json={'operation':'restore_original','note':'baseline'}).json()
        b=self.client.post(root+'/asset/versions',json={'operation':'restore_original','base_version':a['version']}).json()
        annotation=self.client.post(root+'/assets/'+a['version']+'/annotation',json={'note':'kept history','archived':True})
        self.assertEqual(annotation.status_code,200,annotation.text)
        old=self.client.get(root+'/asset?version='+a['version']).json()
        self.assertTrue(next(v for v in old['versions'] if v['id']==a['version'])['archived'])
        self.assertEqual(old['latest_version'],b['version'])
        compare=self.client.get(root+'/asset/compare',params={'left':a['version'],'right':b['version']})
        self.assertEqual(compare.status_code,200,compare.text)
        self.assertEqual(compare.json()['delta'],{'parts':0,'triangles':0,'bytes':0})
        storage=self.client.post(root+'/asset/compact-storage')
        self.assertEqual(storage.status_code,200,storage.text)
        self.assertEqual(storage.json()['unique_content_bytes'],len(original))
        self.assertEqual(storage.json()['duplicate_content_bytes'],len(original)*2)
        for url in [task['model_url'],a['model_url'],b['model_url']]:self.assertEqual(self.client.get(url).content,original)

    def test_reference_views_do_not_claim_geometry_fusion(self):
        task=self.finished(self.create());root=f'/api/jobs/{task["id"]}'
        image=self.upload()
        response=self.client.post(root+'/reference-views',json={'image_ids':[image['id']]})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['reference_views'][1]['role'],'reference_only')
        self.assertIn('not fused',response.json()['reconstruction_strategy'])
        self.assertEqual(self.client.post(root+'/reference-views',json={'image_ids':['f'*32]}).status_code,404)
        self.assertEqual(self.client.post(root+'/reference-views',json={'image_ids':[image['id'],image['id']]}).status_code,422)
        removed=self.client.post(root+'/reference-views',json={'image_ids':[]})
        self.assertEqual(len(removed.json()['reference_views']),1)

    def test_complete_groups_merge_assign_and_quality_contracts(self):
        task=self.finished(self.create());root=f'/api/jobs/{task["id"]}'
        original=self.client.get(root+'/asset').json()
        r=self.client.post(root+'/asset/versions',json={'operation':'auto_parts','category':'table'})
        self.assertEqual(r.status_code,201,r.text);grouped=r.json();self.assertGreaterEqual(len(grouped['groups']),2)
        ids=grouped['groups'][0]['part_ids']+grouped['groups'][1]['part_ids']
        r=self.client.post(root+'/asset/versions',json={'operation':'merge_parts','base_version':grouped['version'],'part_ids':ids,'name':'Combined'})
        self.assertEqual(r.status_code,201,r.text);merged=r.json();self.assertEqual(merged['metrics']['parts'],grouped['metrics']['parts']-1)
        self.assertEqual(merged['metrics']['triangles'],original['metrics']['triangles'])
        before=self.client.get(root+'/asset/quality',params={'version':'original'});after=self.client.get(root+'/asset/quality',params={'version':merged['version']})
        self.assertEqual(before.status_code,200,before.text);self.assertEqual(after.status_code,200,after.text);self.assertEqual(before.json()['whole_model'],after.json()['whole_model'])

    def test_texture_preview_uses_export_channels(self):
        from PIL import Image
        import io
        image=self.upload();response=self.client.get('/api/images/'+image['id']+'/texture/roughness_image')
        self.assertEqual(response.status_code,200,response.text)
        pixel=Image.open(io.BytesIO(response.content)).getpixel((0,0));self.assertEqual(pixel[0],255);self.assertEqual(pixel[2],255)
        self.assertEqual(self.client.get('/api/images/'+image['id']+'/texture/unknown').status_code,404)


if __name__ == '__main__':
    unittest.main(verbosity=2)

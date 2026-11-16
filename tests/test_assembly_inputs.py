"""Regression checks that image-planned native generation cannot spoof provenance."""
import hashlib,json,tempfile,unittest
from pathlib import Path
from PIL import Image
from services.api.assembly_planning import plan_from_image_observations
from services.api.assembly_inputs import validate_generation_binding


class GenerationBindingTests(unittest.TestCase):
    def fixture(self,folder):
        target={'x':0,'y':0,'width':1,'height':1}
        Image.new('L',(4,4),255).save(folder/'mask.png');Image.new('RGBA',(4,4),'white').save(folder/'foreground.png')
        sha=hashlib.sha256((folder/'mask.png').read_bytes()).hexdigest()
        row={'kind':'seat_cushion','mask_sha256':sha,'mask_file':'mask.png','target':target}
        plan=plan_from_image_observations('a'*32,'b'*64,'sofa',target,[row])
        (folder/'plan.json').write_text(plan.model_dump_json(),encoding='utf-8')
        data={'planning_phase':'before_3d_generation','input_sha256':'b'*64,'parts':[row],
              'generation_input_sha256':hashlib.sha256((folder/'foreground.png').read_bytes()).hexdigest()}
        (folder/'observations.json').write_text(json.dumps(data),encoding='utf-8')
        return plan

    def test_binds_parts_and_count_to_existing_plan_and_masks(self):
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);plan=self.fixture(folder)
            bound=validate_generation_binding(folder/'plan.json',folder/'foreground.png')
            self.assertEqual(bound['num_parts'],1)
            self.assertEqual(bound['part_ids'],[p.id for p in plan.parts if p.geometry_role=='physical_part'])
            self.assertEqual(bound['structural_group_ids'],[p.id for p in plan.parts if p.geometry_role=='structural_group'])
            self.assertFalse(bound['semantic_assignment_verified'])

    def test_changed_input_or_mask_and_unresolved_plans_are_refused(self):
        for mode in('input','mask','plan'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory()as temp:
                folder=Path(temp);plan=self.fixture(folder)
                if mode=='input':(folder/'foreground.png').write_bytes(b'changed input')
                elif mode=='mask':(folder/'mask.png').write_bytes(b'changed mask')
                else:
                    plan.status='needs_evidence';(folder/'plan.json').write_text(plan.model_dump_json(),encoding='utf-8')
                with self.assertRaises(ValueError):validate_generation_binding(folder/'plan.json',folder/'foreground.png')

    def test_empty_mask_or_silently_removed_observation_is_refused(self):
        for mode in('empty','missing'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory()as temp:
                folder=Path(temp);plan=self.fixture(folder)
                manifest=json.loads((folder/'observations.json').read_text(encoding='utf-8'))
                if mode=='empty':
                    Image.new('L',(4,4),0).save(folder/'mask.png')
                    sha=hashlib.sha256((folder/'mask.png').read_bytes()).hexdigest()
                    manifest['parts'][0]['mask_sha256']=sha;plan.parts[0].observations[0].mask_sha256=sha
                else:plan.parts=plan.parts[1:];plan.relations=[]
                (folder/'plan.json').write_text(plan.model_dump_json(),encoding='utf-8')
                (folder/'observations.json').write_text(json.dumps(manifest),encoding='utf-8')
                with self.assertRaises(ValueError):validate_generation_binding(folder/'plan.json',folder/'foreground.png')


if __name__=='__main__':unittest.main()

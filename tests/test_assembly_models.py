"""Planning invariants, not image recognition or physical-fidelity measurements."""
import copy,unittest
from pydantic import ValidationError
from services.api.assembly_models import AssemblyPlan


def fixture():
    ids=['part_'+str(i)*32 for i in(1,2)]
    observation={'image_id':'b'*32,'image_sha256':'c'*64,'mask_sha256':'d'*64,'target':{'x':0,'y':0,'width':1,'height':1},'evidence_kind':'original_photo','visibility':'partial'}
    return{'id':'a'*32,'primary_image_id':'b'*32,'primary_image_sha256':'c'*64,'furniture_target':{'x':0,'y':0,'width':1,'height':1},'object_category':'sofa','planning_basis':'image_first','parts':[
        {'id':ids[0],'name':'座架','kind':'frame','identity_status':'geometry_hypothesis','geometry_method':'native_joint'},
        {'id':ids[1],'name':'坐垫','kind':'seat_cushion','parent_id':ids[0],'identity_status':'image_instance','observations':[observation],'geometry_method':'native_joint'}],
        'relations':[{'part_id':ids[1],'target_part_id':ids[0],'kind':'supported_by','evidence':'inferred'}]}


class AssemblyPlanTests(unittest.TestCase):
    def test_plan_roundtrip_preserves_semantic_identity_and_uncertainty(self):
        plan=AssemblyPlan.model_validate(fixture());again=AssemblyPlan.model_validate_json(plan.model_dump_json())
        self.assertEqual(plan,again);self.assertFalse(plan.physical_structure_verified)
        self.assertTrue(all(p.requires_review for p in plan.parts));self.assertEqual(len(plan.parts),2)

    def test_hierarchy_cycles_missing_parent_and_missing_relation_target_refused(self):
        for mutate in(lambda d:d['parts'][0].update(parent_id=d['parts'][1]['id']),lambda d:d['parts'][0].update(parent_id='missing'),lambda d:d['parts'][1].update(parent_id='missing'),lambda d:d['relations'][0].update(target_part_id='missing')):
            data=fixture();mutate(data)
            with self.assertRaises(ValidationError):AssemblyPlan.model_validate(data)

    def test_image_identity_requires_actual_observation_and_known_kind(self):
        for changes in({'observations':[]},{'kind':'unknown'}):
            data=fixture();data['parts'][1].update(changes)
            with self.assertRaises(ValidationError):AssemblyPlan.model_validate(data)

    def test_geometry_cannot_be_claimed_ready_without_output_or_with_shared_owner(self):
        data=fixture();data['status']='ready_for_review'
        with self.assertRaises(ValidationError):AssemblyPlan.model_validate(data)
        for p in data['parts']:p.update(status='ready',model_sha256='e'*64,primitive_ids=['same_primitive'])
        with self.assertRaises(ValidationError):AssemblyPlan.model_validate(data)

    def test_bounds_and_nonfinite_coordinates_refused(self):
        for bounds in([[-1,-1,-1],[1,1,-1]],[[-1,-1,-1],[1,float('nan'),1]]):
            data=fixture();data['overall_bounds_world']=bounds
            with self.assertRaises(ValidationError):AssemblyPlan.model_validate(data)


if __name__=='__main__':unittest.main()

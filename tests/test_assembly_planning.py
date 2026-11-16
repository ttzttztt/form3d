"""Evidence and identity contracts; no mocked model accuracy claims."""
import copy,unittest
from services.api.assembly_planning import plan_from_image_observations


class ImageFirstPlanningTests(unittest.TestCase):
    target={'x':.1,'y':.1,'width':.8,'height':.8}
    observations=[{'kind':'seat_cushion','mask_sha256':'d'*64,'target':{'x':.2,'y':.5,'width':.6,'height':.2}},{'kind':'back_cushion','mask_sha256':'e'*64,'target':{'x':.3,'y':.2,'width':.3,'height':.3}}]
    def plan(self,observations=None,category='sofa'):
        return plan_from_image_observations('b'*32,'c'*64,category,self.target,self.observations if observations is None else observations,plan_id='a'*32)

    def test_ids_do_not_depend_on_detector_order_and_body_hypothesis_is_explicit(self):
        a=self.plan();b=self.plan(list(reversed(self.observations)))
        self.assertEqual(a,b);self.assertEqual(len(a.parts),3)
        body=next(p for p in a.parts if p.kind=='frame');self.assertEqual(body.identity_status,'geometry_hypothesis');self.assertEqual(body.observations,[])
        self.assertEqual(body.geometry_role,'structural_group');self.assertEqual(body.geometry_method,'unresolved')
        self.assertTrue(all(r.evidence=='inferred'for r in a.relations))

    def test_no_detections_does_not_invent_default_furniture_parts(self):
        result=self.plan([]);self.assertEqual(result.parts,[]);self.assertEqual(result.status,'needs_evidence')

    def test_continuous_upholstered_body_is_not_split_into_an_invented_seat_and_frame(self):
        data=copy.deepcopy(self.observations);data[0]['kind']='body'
        plan=self.plan(data);body=next(p for p in plan.parts if p.kind=='body')
        self.assertEqual(len(plan.parts),2);self.assertEqual(body.geometry_role,'physical_part')
        self.assertFalse(any(p.kind in('frame','seat_cushion')for p in plan.parts))
        pillow=next(p for p in plan.parts if p.kind=='back_cushion')
        self.assertEqual(pillow.parent_id,body.id);self.assertEqual(plan.relations[0].target_part_id,body.id)

    def test_other_instance_and_duplicate_mask_refused(self):
        data=copy.deepcopy(self.observations);data[0]['target']['x']=0
        with self.assertRaises(ValueError):self.plan(data)
        with self.assertRaises(ValueError):self.plan([self.observations[0],self.observations[0]])

    def test_ambiguous_part_blocks_automatic_generation_without_erasing_evidence(self):
        data=copy.deepcopy(self.observations);data[0]['kind']='unknown';plan=self.plan(data)
        self.assertEqual(plan.status,'needs_evidence');self.assertEqual(len(plan.parts),3)
        self.assertTrue(any(p.identity_status=='unassigned'and p.observations for p in plan.parts))

    def test_table_does_not_receive_sofa_frame_or_fixed_leg_count(self):
        data=copy.deepcopy(self.observations);data[0]['kind']='tabletop';data[1]['kind']='leg';plan=self.plan(data,'table')
        self.assertEqual(len(plan.parts),2);self.assertFalse(any(p.kind=='frame'for p in plan.parts))

    def test_observed_frame_keeps_hierarchy_without_inventing_a_second_frame(self):
        data=copy.deepcopy(self.observations)+[{'kind':'frame','mask_sha256':'f'*64,'target':{'x':.15,'y':.6,'width':.7,'height':.2}}]
        plan=self.plan(data);frame=next(p for p in plan.parts if p.kind=='frame')
        self.assertEqual(frame.identity_status,'image_instance');self.assertEqual(len(plan.parts),3)
        self.assertEqual(frame.geometry_role,'physical_part')
        self.assertTrue(all(p.parent_id==frame.id for p in plan.parts if p.id!=frame.id))
        self.assertEqual(len(plan.relations),2)

    def test_pillow_support_hypothesis_uses_nearby_seat_instead_of_first_in_list(self):
        data=[{'kind':'seat_cushion','mask_sha256':'1'*64,'target':{'x':.15,'y':.5,'width':.25,'height':.2}},
              {'kind':'seat_cushion','mask_sha256':'2'*64,'target':{'x':.55,'y':.5,'width':.25,'height':.2}},
              {'kind':'back_cushion','mask_sha256':'3'*64,'target':{'x':.6,'y':.25,'width':.15,'height':.25}}]
        plan=self.plan(data);pillow=next(p for p in plan.parts if p.kind=='back_cushion')
        right=next(p for p in plan.parts if p.kind=='seat_cushion'and p.observations[0].target.x>.5)
        relation=next(r for r in plan.relations if r.part_id==pillow.id)
        self.assertEqual(relation.target_part_id,right.id);self.assertEqual(relation.evidence,'inferred')


if __name__=='__main__':unittest.main()

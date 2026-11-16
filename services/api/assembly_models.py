"""Image-bound part identities and assembly constraints, independent of mesh patches."""
from typing import List, Literal, Optional
from pydantic import Field, model_validator
from .models import StrictModel, Target

PartKind=Literal['seat_cushion','back_cushion','backrest','bolster','armrest','frame','body','leg','tabletop','door','drawer','shelf','panel','other','unknown']


class PartObservation(StrictModel):
    image_id: str=Field(pattern=r'^[a-f0-9]{32}$')
    image_sha256: str=Field(pattern=r'^[a-f0-9]{64}$')
    mask_sha256: str=Field(pattern=r'^[a-f0-9]{64}$')
    target: Target
    evidence_kind: Literal['original_input','original_photo','additional_photo','synthetic_render']
    visibility: Literal['visible','partial']
    semantic_verified: bool=False


class PartPlan(StrictModel):
    id: str=Field(pattern=r'^part_[a-f0-9]{32}$')
    name: str=Field(min_length=1,max_length=100)
    kind: PartKind
    parent_id: Optional[str]=None
    identity_status: Literal['image_instance','geometry_hypothesis','unassigned']
    observations: List[PartObservation]=Field(default_factory=list,max_length=12)
    geometry_method: Literal['native_joint','image_part','geometry_fit','source_repair','preserved','unresolved']
    geometry_role: Literal['physical_part','structural_group']='physical_part'
    status: Literal['planned','generating','ready','needs_evidence','failed']='planned'
    hidden_surface_status: Literal['inferred','unverified','source_supported']='unverified'
    bounds_world: Optional[List[List[float]]]=None
    primitive_ids: List[str]=Field(default_factory=list,max_length=64)
    model_sha256: Optional[str]=Field(default=None,pattern=r'^[a-f0-9]{64}$')
    requires_review: bool=True

    @model_validator(mode='after')
    def evidence_consistency(self):
        if self.identity_status=='image_instance'and not self.observations:
            raise ValueError('An image-derived part identity requires image observations')
        if self.kind=='unknown'and self.identity_status=='image_instance':
            raise ValueError('An unclassified region is not a verified semantic part identity')
        if self.geometry_role=='structural_group'and(self.primitive_ids or self.model_sha256 is not None):
            raise ValueError('A structural grouping node cannot own invented physical geometry')
        if self.status=='ready'and self.geometry_role=='physical_part'and(not self.primitive_ids or self.model_sha256 is None):
            raise ValueError('A ready part requires actual geometry identities and a model hash')
        if self.bounds_world is not None:validate_bounds(self.bounds_world)
        return self


class AssemblyRelation(StrictModel):
    part_id: str
    target_part_id: str
    kind: Literal['supported_by','attached_to','inside','aligned_with']
    evidence: Literal['observed','coarse_geometry','inferred']
    tolerance_world: Optional[float]=Field(default=None,ge=0)


def validate_bounds(bounds):
    if len(bounds)!=2 or any(len(row)!=3 for row in bounds)or any(bounds[1][axis]<=bounds[0][axis]for axis in range(3)):
        raise ValueError('Assembly bounds require two finite XYZ points with positive extent')


class AssemblyPlan(StrictModel):
    schema_version: Literal['parts-first/1']='parts-first/1'
    id: str=Field(pattern=r'^[a-f0-9]{32}$')
    primary_image_id: str=Field(pattern=r'^[a-f0-9]{32}$')
    primary_image_sha256: str=Field(pattern=r'^[a-f0-9]{64}$')
    furniture_target: Target
    object_category: Literal['sofa','chair','table','cabinet','other']
    coordinate_system: Literal['gltf_y_up_right_handed']='gltf_y_up_right_handed'
    scale_status: Literal['normalized_unverified','measured_dimensions']='normalized_unverified'
    planning_basis: Literal['image_first','image_and_coarse_geometry','native_joint_hypothesis']
    coarse_model_sha256: Optional[str]=Field(default=None,pattern=r'^[a-f0-9]{64}$')
    overall_bounds_world: Optional[List[List[float]]]=None
    status: Literal['planned','generating','ready_for_review','needs_evidence','failed']='planned'
    parts: List[PartPlan]=Field(default_factory=list,max_length=64)
    relations: List[AssemblyRelation]=Field(default_factory=list,max_length=256)
    limitations: List[str]=Field(default_factory=list,max_length=64)
    physical_structure_verified: Literal[False]=False

    @model_validator(mode='after')
    def graph_consistency(self):
        if self.overall_bounds_world is not None:validate_bounds(self.overall_bounds_world)
        ids={p.id for p in self.parts}
        if len(ids)!=len(self.parts):raise ValueError('A semantic part identity cannot occur twice')
        primitive_owners={}
        parent={p.id:p.parent_id for p in self.parts}
        if any(value is not None and value not in ids for value in parent.values()):raise ValueError('Assembly parent does not exist')
        for part in self.parts:
            seen={part.id};cursor=part.parent_id
            while cursor is not None:
                if cursor in seen:raise ValueError('Assembly hierarchy contains a cycle')
                seen.add(cursor);cursor=parent[cursor]
            for primitive in part.primitive_ids:
                if primitive in primitive_owners:raise ValueError('One primitive cannot belong to two semantic parts')
                primitive_owners[primitive]=part.id
        for relation in self.relations:
            if relation.part_id not in ids or relation.target_part_id not in ids:raise ValueError('Assembly relation references a missing part')
            if relation.part_id==relation.target_part_id:raise ValueError('A part cannot attach to or support itself')
        if self.status=='ready_for_review'and(not self.parts or any(p.status!='ready'for p in self.parts)):
            raise ValueError('An assembly cannot be ready while any part is missing or unresolved')
        return self

"""Validated, immutable input snapshots for the local MVP."""

from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Point(StrictModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class Target(StrictModel):
    x: float = Field(default=0, ge=0, lt=1)
    y: float = Field(default=0, ge=0, lt=1)
    width: float = Field(default=1, gt=0, le=1)
    height: float = Field(default=1, gt=0, le=1)

    @model_validator(mode="after")
    def check_bounds(self):
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("选区超出图片范围")
        return self


class Stroke(StrictModel):
    points: List[Point] = Field(min_length=1, max_length=2000)
    radius: float = Field(default=0.025, ge=0.002, le=0.2)


class Dimensions(StrictModel):
    width: float = Field(default=0.8, ge=0.1, le=5)
    depth: float = Field(default=0.4, ge=0.1, le=5)
    height: float = Field(default=0.8, ge=0.1, le=5)
    confirmed: bool = False


class JobRequest(StrictModel):
    image_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    reference_image_ids: List[str] = Field(default_factory=list, max_length=8)
    name: str = Field(default="未命名商品", min_length=1, max_length=100)
    target: Target = Field(default_factory=Target)
    strokes: List[Stroke] = Field(default_factory=list, max_length=200)
    route: Literal["local", "assistant", "template", "meshy", "parts_first"] = "local"
    local_remove_background: bool = True
    local_engine: Literal["triposr", "hunyuan-mini"] = "triposr"
    local_segmentation: Literal["auto", "sam2", "basic"] = "auto"
    local_auto_retry: bool = True
    local_quality: Literal["balanced", "structure"] = "balanced"
    object_category: Literal["", "unknown", "cabinet", "table", "sofa", "chair", "vase", "plant", "lamp", "other"] = ""
    object_label: str = Field(default="", max_length=100)
    object_id: str = Field(default="", max_length=100)
    template: Literal["shelf", "table", "cabinet"] = "shelf"
    dimensions: Dimensions = Field(default_factory=Dimensions)
    color: str = Field(default="#b79370", pattern=r"^#[0-9a-fA-F]{6}$")
    levels: int = Field(default=3, ge=2, le=6)
    allow_external: bool = False

    @model_validator(mode="after")
    def structural_constraints(self):
        import re

        if any(not re.fullmatch(r"[a-f0-9]{32}", value) for value in self.reference_image_ids):
            raise ValueError("参考图片 ID 无效")
        if (
            len(set(self.reference_image_ids)) != len(self.reference_image_ids)
            or self.image_id in self.reference_image_ids
        ):
            raise ValueError("参考图片不可重复或包含主图")
        if self.route == "meshy" and not self.allow_external:
            raise ValueError("云端生成需要明确允许图片传给第三方服务")
        if self.route == "parts_first" and self.object_category not in ("sofa", "chair", "table", "cabinet"):
            raise ValueError("部件优先生成需要选择家具类别：沙发、椅子、桌子或柜子")
        if self.route == "template" and self.template == "shelf":
            if self.dimensions.height / self.levels < 0.065:
                raise ValueError("层间距过小，请增大高度或减少层数")
        return self


class ReviewRequest(StrictModel):
    decision: Literal["accept", "reject"]
    note: str = Field(default="", max_length=1000)


class FaceSelection(StrictModel):
    part_id: str = Field(min_length=1, max_length=100)
    faces: List[int] = Field(min_length=1, max_length=500000)


class VersionAnnotation(StrictModel):
    note: str = Field(default="", max_length=1000)
    archived: bool = False


class ReferenceViews(StrictModel):
    image_ids: List[str] = Field(max_length=8)

    @model_validator(mode="after")
    def validate_ids(self):
        import re

        if len(set(self.image_ids)) != len(self.image_ids) or any(
            not re.fullmatch(r"[a-f0-9]{32}", i) for i in self.image_ids
        ):
            raise ValueError("参考图片 ID 无效或重复")
        return self


class AssetEditRequest(StrictModel):
    base_version: str = Field(default="original", pattern=r"^(original|[a-f0-9]{32})$")
    operation: Literal[
        "material",
        "connected_components",
        "plane_group",
        "face_group",
        "rename",
        "decimate",
        "optimize_mesh",
        "auto_parts",
        "merge_parts",
        "assign_faces",
        "repair_geometry",
        "unwrap_uv",
        "translate_parts",
        "complete_part",
        "reconstruct_parts",
        "replace_part",
        "separate_solids",
        "semantic_parts",
        "restore_original",
        "restore_version",
    ] = "material"
    source_version: str = Field(default="original", pattern=r"^(original|[a-f0-9]{32})$")
    part_ids: List[str] = Field(default_factory=list, max_length=512)
    color: str = Field(default="#b79370", pattern=r"^#[0-9a-fA-F]{6}$")
    metalness: float = Field(default=0, ge=0, le=1)
    roughness: float = Field(default=0.7, ge=0, le=1)
    opacity: float = Field(default=1, ge=0.02, le=1)
    mode: Literal["replace", "tint"] = "replace"
    name: str = Field(default="", max_length=60)
    axis: Literal["x", "y", "z"] = "y"
    position: float = Field(default=0.5, gt=0, lt=1)
    min_faces: int = Field(default=128, ge=1, le=100000)
    max_groups: int = Field(default=32, ge=2, le=64)
    face_selection: List[FaceSelection] = Field(default_factory=list, max_length=64)
    base_color_image: str = Field(default="", pattern=r"^([a-f0-9]{32})?$")
    normal_image: str = Field(default="", pattern=r"^([a-f0-9]{32})?$")
    roughness_image: str = Field(default="", pattern=r"^([a-f0-9]{32})?$")
    uv_scale: float = Field(default=1, ge=0.05, le=100)
    uv_rotation: float = Field(default=0, ge=-180, le=180)
    lod_ratio: float = Field(default=0.5, ge=0.1, le=0.9)
    target_faces: int = Field(default=100000, ge=10000, le=300000)
    note: str = Field(default="", max_length=1000)
    category: Literal["auto", "table", "chair", "sofa", "cabinet", "lamp", "other"] = "auto"
    detail_level: Literal["coarse", "fine"] = "coarse"
    target_part_id: str = Field(default="", max_length=100)
    repair_strength: Literal["cleanup", "gentle"] = "gentle"
    translation: List[float] = Field(default_factory=lambda: [0, 0, 0], min_length=3, max_length=3)
    uv_unwrap_mode: Literal["auto", "atlas", "box", "proxy", "cylinder"] = "auto"
    completion_bounds: List[List[float]] = Field(default_factory=list, max_length=2)
    completion_profile: Literal["cushion", "support", "slab"] = "cushion"
    completion_shape: Literal["contour", "box"] = "contour"
    completion_preview_id: str = Field(default="", pattern=r"^([a-f0-9]{32})?$")
    semantic_scan_id: str = Field(default="", pattern=r"^([a-f0-9]{32})?$")
    regeneration_preview_id: str = Field(default="", pattern=r"^([a-f0-9]{32})?$")

    @model_validator(mode="after")
    def validate_operation(self):
        if self.regeneration_preview_id and self.operation != "replace_part":
            raise ValueError("部件重生预览只能用于替换部件")
        if self.operation == "replace_part" and (
            not self.regeneration_preview_id
            or not self.part_ids
            or self.face_selection
            or self.completion_preview_id
            or self.semantic_scan_id
        ):
            raise ValueError("请先生成部件替换预览，再采用同一候选")
        if self.operation == "semantic_parts" and (not self.semantic_scan_id or self.part_ids or self.face_selection):
            raise ValueError("AI 整体分组需要完整识别结果，请先清空局部选区")
        if self.semantic_scan_id and self.operation != "semantic_parts":
            raise ValueError("AI 识别结果只能用于整体分组")
        if self.completion_preview_id and self.operation not in ("complete_part", "reconstruct_parts"):
            raise ValueError("切分预览只能用于完整部件重建")
        if self.operation == "reconstruct_parts" and (
            not self.part_ids or self.face_selection or self.completion_bounds
        ):
            raise ValueError("实体重建需要已保存的整体部件，请清空局部选区与手动范围")
        if self.operation == "separate_solids" and (not self.part_ids or self.face_selection):
            raise ValueError("请选择已有部件，并清空未保存选区后拆分闭合体")
        if self.completion_bounds:
            b = self.completion_bounds
            if (
                len(b) != 2
                or any(len(row) != 3 for row in b)
                or any(not 0 <= value <= 1 for row in b for value in row)
                or any(b[1][i] - b[0][i] < 0.005 for i in range(3))
            ):
                raise ValueError("完整部件范围需为两组三维 0～1 坐标，每轴起点小于终点至少 0.005")
        if self.operation == "complete_part" and (
            (len(self.face_selection) != 1)
            if self.face_selection
            else not 1 <= len(self.part_ids) <= (1 if self.completion_profile == "cushion" else 32)
        ):
            raise ValueError("完整部件重建需要一个局部选区，或同一组内的已保存部件")
        if self.operation == "face_group" and not self.face_selection:
            raise ValueError("请先选择三角面")
        if len({s.part_id for s in self.face_selection}) != len(self.face_selection):
            raise ValueError("同一部件的选面请合并提交")
        if any(face < 0 for selection in self.face_selection for face in selection.faces):
            raise ValueError("三角面编号不能为负数")
        if self.operation == "rename" and (not self.name.strip() or not self.part_ids):
            raise ValueError("重命名需要选择部件并输入名称")
        if self.operation == "merge_parts" and len(set(self.part_ids)) < 2:
            raise ValueError("至少选择两个部件合并")
        if self.operation == "assign_faces" and (
            not self.face_selection or (not self.target_part_id and not self.name.strip())
        ):
            raise ValueError("需要选择面，并指定接收部件或新部件名称")
        if any(abs(v) > 5 for v in self.translation):
            raise ValueError("单次移动每轴需在 -5～5 个模型单位内")
        if self.operation == "translate_parts" and (not self.part_ids or not any(self.translation)):
            raise ValueError("请选择部件并输入非零移动量")
        return self


class PartExportRequest(StrictModel):
    version: str = Field(default="original", pattern=r"^(original|[a-f0-9]{32})$")
    part_ids: List[str] = Field(min_length=1, max_length=512)


class SemanticScanRequest(StrictModel):
    version: str = Field(default="original", pattern=r"^(original|[a-f0-9]{32})$")
    category: Literal["auto", "sofa", "chair", "table", "cabinet", "other"] = "auto"
    force: bool = False


class PartReferenceRequest(StrictModel):
    version: str = Field(default="original", pattern=r"^(original|[a-f0-9]{32})$")
    part_ids: List[str] = Field(min_length=1, max_length=512)
    kind: Literal["pillow", "cushion", "bolster"] = "pillow"
    reference_image_id: str = Field(default="", pattern=r"^([a-f0-9]{32})?$")


class PartRegenerationRequest(PartReferenceRequest):
    reference_scan_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    reference_candidate_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class PartSurfaceRepairRequest(StrictModel):
    version: str = Field(default="original", pattern=r"^(original|[a-f0-9]{32})$")
    part_ids: List[str] = Field(min_length=1, max_length=512)


class PartOptimizationView(StrictModel):
    image_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    role: Literal["side", "back", "front"] = "side"
    target: Target = Field(default_factory=Target)


class PartOptimizationRequest(PartSurfaceRepairRequest):
    candidate_count: int = Field(default=3, ge=1, le=3)
    target_faces: int = Field(default=100000, ge=10000, le=300000)
    reference_views: List[PartOptimizationView] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def unique_views(self):
        if len({v.image_id for v in self.reference_views}) != len(self.reference_views):
            raise ValueError("补充视图不可重复")
        return self


class LabelledPrompt(Point):
    label: Literal[0, 1] = 1


class PartPromptView(StrictModel):
    image: str = Field(min_length=50, max_length=1_600_000)
    point: Point
    points: List[LabelledPrompt] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def positive_prompt(self):
        if self.points and not any(p.label == 1 for p in self.points):
            raise ValueError("至少需要一个保留点")
        if self.points and self.points[0].label != 1:
            raise ValueError("第一个提示点必须为保留点")
        return self


class PartPromptRequest(StrictModel):
    version: str = Field(default="original", pattern=r"^(original|[a-f0-9]{32})$")
    views: List[PartPromptView] = Field(min_length=1, max_length=3)
    candidate_range: Literal["small", "medium", "large"] = "small"
    refine_boundary: bool = True


class AlternativeRequest(StrictModel):
    engine: Literal["triposr", "hunyuan-mini"]
    quality: Literal["balanced", "structure"] = "balanced"

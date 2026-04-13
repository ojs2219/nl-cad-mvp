"""
Intermediate Representation (IR) for CAD models.

IR is a recursive node tree that sits between natural-language input and the
backend generator (OpenSCAD, CadQuery, …).  Each node has an `op` (operation
type), typed `params`, and zero-or-more `children`.

Node taxonomy
─────────────
PRIMITIVE   leaf nodes that produce 3-D geometry directly
  box         params: width, depth, height [, center=False]
  cylinder    params: radius, height [, r1, r2, center=False]
  sphere      params: radius
  cone        params: r1, r2, height          (r2=0 → pointed)

BOOLEAN     require ≥2 children
  union       merge all children
  difference  subtract children[1:] from children[0]
  intersection  keep only shared volume

TRANSFORM   require exactly 1 child
  translate   params: x=0, y=0, z=0
  rotate      params: x=0, y=0, z=0  (degrees)
  scale       params: x=1, y=1, z=1
  mirror      params: x=0, y=0, z=0  (axis-normal vector, 0 or 1)

PROFILE (2-D)  leaf nodes used as children of extrusions
  polygon     params: points [[x,y], …]
  circle_2d   params: radius
  square_2d   params: width, height [, center=False]
  path        params: points [[x,y], …], closed=True  (alias for polygon)

EXTRUSION   require exactly 1 child (a 2-D profile)
  linear_extrude   params: height [, twist=0, scale=1.0, center=False]
  rotate_extrude   params: angle=360

PATTERN     require exactly 1 child (the template shape)
  linear_pattern    params: count, spacing=[dx,dy,dz]
  circular_pattern  params: count, radius [, axis="z"]

RELATION    semantic placement — resolved to geometry before code generation
  relation  params: type, [axis], [direction]
            type: "on_top_of" | "center_of" | "next_to" | "inside" | "aligned_center"
            children: [reference_shape, subject_shape, ...]
            → resolver.resolve() converts these to translate/union/difference
            → partial shapes (hemisphere etc.) are expressed via boolean/clip,
              not as new primitives
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

# ── node-type constants ───────────────────────────────────────────────────────

PRIMITIVE_OPS   = {"box", "cylinder", "sphere", "cone"}
BOOLEAN_OPS     = {"union", "difference", "intersection"}
TRANSFORM_OPS   = {"translate", "rotate", "scale", "mirror"}
PROFILE_OPS     = {"polygon", "circle_2d", "square_2d", "path"}
EXTRUDE_OPS     = {"linear_extrude", "rotate_extrude"}
PATTERN_OPS     = {"linear_pattern", "circular_pattern"}
RELATION_OPS    = {"relation"}
# relation.params:
#   type (required): "on_top_of" | "center_of" | "next_to" | "inside" | "aligned_center"
#   axis (optional): "x" | "y" | "z"  — directional axis for next_to (default "x")
#   direction (optional): 1 | -1       — placement direction for next_to (default 1)

ALL_OPS = (
    PRIMITIVE_OPS | BOOLEAN_OPS | TRANSFORM_OPS
    | PROFILE_OPS | EXTRUDE_OPS | PATTERN_OPS | RELATION_OPS
)


# ── IR node ───────────────────────────────────────────────────────────────────

class IRNode(BaseModel):
    """Single node in the IR tree."""

    op: str
    """Operation type – must be one of ALL_OPS."""

    params: Dict[str, Any] = Field(default_factory=dict)
    """Op-specific numeric/string parameters."""

    children: List[IRNode] = Field(default_factory=list)
    """Child nodes (semantics depend on `op`)."""

    id: Optional[str] = None
    """Optional stable identifier for addressing this node in modifications."""

    comment: Optional[str] = None
    """Human-readable label, stored in IR and emitted as OpenSCAD comment."""

    # ── convenience helpers ───────────────────────────────────────────────────

    def p(self, key: str, default: Any = 0) -> Any:
        """Safely fetch a param with a fallback."""
        return self.params.get(key, default)

    def pf(self, key: str, default: float = 0.0) -> float:
        return float(self.params.get(key, default))


IRNode.model_rebuild()   # resolve forward reference


# ── IR tree (root wrapper) ────────────────────────────────────────────────────

class IRTree(BaseModel):
    """Complete IR document."""

    version: str = "1.0"
    root: IRNode
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, s: str) -> "IRTree":
        return cls.model_validate_json(s)

    @classmethod
    def single(cls, node: IRNode, **meta) -> "IRTree":
        """Wrap a lone node into a tree."""
        return cls(root=node, metadata=meta)


# ── validation ────────────────────────────────────────────────────────────────

class IRValidationError(ValueError):
    pass


def validate(node: IRNode, path: str = "root") -> None:
    """Raise IRValidationError if the tree is structurally invalid."""
    if node.op not in ALL_OPS:
        raise IRValidationError(f"{path}: unknown op '{node.op}'")

    n = len(node.children)

    if node.op in BOOLEAN_OPS and n < 2:
        raise IRValidationError(f"{path}({node.op}): needs ≥2 children, got {n}")

    if node.op in TRANSFORM_OPS and n != 1:
        raise IRValidationError(f"{path}({node.op}): needs exactly 1 child, got {n}")

    if node.op in EXTRUDE_OPS and n != 1:
        raise IRValidationError(f"{path}({node.op}): needs exactly 1 child (profile), got {n}")

    if node.op in PATTERN_OPS and n != 1:
        raise IRValidationError(f"{path}({node.op}): needs exactly 1 child (template), got {n}")

    if node.op in PRIMITIVE_OPS | PROFILE_OPS and n != 0:
        raise IRValidationError(f"{path}({node.op}): leaf node must have 0 children, got {n}")

    if node.op in RELATION_OPS and n < 2:
        raise IRValidationError(f"{path}(relation): needs ≥2 children (reference + subject), got {n}")

    for i, child in enumerate(node.children):
        validate(child, f"{path}.children[{i}]")

"""
NL → IR parser.

Fast path: regex rules for common Korean/English patterns.
Slow path: Claude API with an IR-aware system prompt.
"""
from __future__ import annotations
import re
import os
import json
from typing import Optional

from services.ir.schema import IRNode, IRTree, validate, IRValidationError

# ── AI system prompt ──────────────────────────────────────────────────────────

_IR_SYSTEM_PROMPT = """You are a CAD IR (Intermediate Representation) generator.
Convert the user's natural-language description into a structured IR JSON tree.

━━ IR JSON format ━━
{"root": <node>}

Each node:
{"op": "<op>", "params": {<key>: <value>}, "children": [<node>, ...], "id": "<optional>", "comment": "<optional>"}

━━ Supported ops ━━

PRIMITIVES (leaf, no children):
  "box"       params: {width, depth, height}
  "cylinder"  params: {radius, height}  or  {r1, r2, height} for taper
  "sphere"    params: {radius}
  "cone"      params: {r1, r2, height}   (r2=0 → pointed)

2-D PROFILES (leaf, used as child of extrusions):
  "polygon"   params: {points: [[x,y], ...]}
  "circle_2d" params: {radius}
  "square_2d" params: {width, height}

EXTRUSIONS (exactly 1 child: a 2-D profile):
  "linear_extrude"  params: {height [, twist=0, scale=1.0, center=false]}
  "rotate_extrude"  params: {angle=360}

BOOLEANS (≥2 children):
  "union"        merges all children
  "difference"   subtracts children[1:] from children[0]
  "intersection" keeps shared volume

TRANSFORMS (exactly 1 child):
  "translate"  params: {x=0, y=0, z=0}
  "rotate"     params: {x=0, y=0, z=0}  (degrees)
  "scale"      params: {x=1, y=1, z=1}
  "mirror"     params: {x=0, y=0, z=0}

PATTERNS (exactly 1 child: the template shape):
  "linear_pattern"    params: {count, spacing: [dx, dy, dz]}
  "circular_pattern"  params: {count, radius [, axis="z"]}

━━ Rules ━━
- All dimensions in mm.
- Shapes without explicit position are at the origin.
- Use "translate" to stack or position shapes.
- Use "difference" for holes or subtractions.
- Return ONLY the JSON object — no markdown, no explanation.

━━ Examples ━━

"100×50×10 box with a 5mm hole through the center":
{"root":{"op":"difference","children":[
  {"op":"box","params":{"width":100,"depth":50,"height":10},"comment":"plate"},
  {"op":"translate","params":{"x":50,"y":25,"z":-1},
   "children":[{"op":"cylinder","params":{"radius":5,"height":12},"comment":"hole"}]}
]}}

"3 cylinders in a row, 30mm apart, r=10 h=20":
{"root":{"op":"linear_pattern","params":{"count":3,"spacing":[30,0,0]},
 "children":[{"op":"cylinder","params":{"radius":10,"height":20}}]}}

"L-bracket (polygon extruded 5mm)":
{"root":{"op":"linear_extrude","params":{"height":5},
 "children":[{"op":"polygon","params":{"points":[[0,0],[100,0],[100,30],[30,30],[30,100],[0,100]]}}]}}

"cylinder r=20 h=5 with 6 holes r=3 in a circle":
{"root":{"op":"difference","children":[
  {"op":"cylinder","params":{"radius":20,"height":5}},
  {"op":"circular_pattern","params":{"count":6,"radius":14},
   "children":[{"op":"cylinder","params":{"radius":3,"height":7}}]}
]}}
"""


# ── public entry point ────────────────────────────────────────────────────────

async def parse_to_ir(
    text: str,
    system_prompt: Optional[str] = None,
    user_prompt: Optional[str] = None,
) -> IRTree:
    """Convert NL text to an IRTree.  Regex fast path → Claude API fallback."""

    tree = _regex_parse(text)
    if tree:
        return tree

    return await _ai_parse(text, system_prompt, user_prompt)


# ── regex fast path ───────────────────────────────────────────────────────────

def _box(w, d, h, center=True) -> IRNode:
    """Return a box centered at XY origin, bottom at Z=0."""
    if center:
        return IRNode(
            op="translate",
            params={"x": -w / 2, "y": -d / 2, "z": 0},
            children=[IRNode(op="box", params={"width": w, "depth": d, "height": h})],
        )
    return IRNode(op="box", params={"width": w, "depth": d, "height": h})


def _cylinder(r, h) -> IRNode:
    return IRNode(op="cylinder", params={"radius": r, "height": h})


def _sphere(r) -> IRNode:
    return IRNode(op="sphere", params={"radius": r})


def _number(text: str, *keywords) -> Optional[float]:
    for kw in keywords:
        m = re.search(rf"{kw}\s*[：:=]?\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if m:
            return float(m.group(1))
    return None


def _parse_single_to_node(text: str) -> Optional[IRNode]:
    """Try to build a single IR node from text.  Returns None on failure."""

    # ── box: "100x50x10 박스" ─────────────────────────────────────────────────
    m = re.search(r"(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)", text)
    if m and any(k in text for k in ["박스", "직육면체", "상자", "box"]):
        w, d, h = float(m.group(1)), float(m.group(2)), float(m.group(3))
        return _box(w, d, h)

    if any(k in text for k in ["박스", "직육면체", "상자", "box"]):
        w = _number(text, "가로", "width", "w")
        d = _number(text, "세로", "depth", "d")
        h = _number(text, "높이", "height", "h")
        if w and d and h:
            return _box(w, d, h)

    # ── cylinder: "지름 20 높이 50 원기둥" ────────────────────────────────────
    if any(k in text for k in ["원기둥", "실린더", "cylinder"]):
        h = _number(text, "높이", "height", "h")
        d = _number(text, "지름", "직경", "diameter")
        r = _number(text, "반지름", "반경", "radius", "r")
        if h and (d or r):
            return _cylinder(r if r else d / 2, h)

    # ── sphere: "반지름 15 구" ────────────────────────────────────────────────
    if "구" in text and "원기둥" not in text and "구멍" not in text:
        r = _number(text, "반지름", "반경", "radius", "r")
        d = _number(text, "지름", "직경", "diameter")
        if r:
            return _sphere(r)
        if d:
            return _sphere(d / 2)

    # ── plate with holes: "가로 100 세로 50 두께 5 판에 지름 10 구멍 4개" ─────
    if ("판" in text or "plate" in text.lower()) and ("구멍" in text or "홀" in text or "hole" in text.lower()):
        w  = _number(text, "가로", "width")
        d  = _number(text, "세로", "depth")
        h  = _number(text, "두께", "thickness", "높이", "height")
        hd = _number(text, "지름", "직경", "diameter")
        hr = _number(text, "반지름", "반경", "radius")
        cm = re.search(r"구멍\s*(\d+)\s*개", text) or re.search(r"(\d+)\s*개?\s*구멍", text)
        count = int(cm.group(1)) if cm else 1
        if w and d and h:
            hole_r = hr if hr else (hd / 2 if hd else 5.0)
            return _plate_with_holes(w, d, h, hole_r, count)

    return None


def _plate_with_holes(w: float, d: float, h: float, hole_r: float, count: int) -> IRNode:
    """Build IR for a plate with N holes using difference + union of translates."""
    from services.scad_generator import get_hole_positions  # reuse position logic
    positions = get_hole_positions(count, w, d)

    if not positions:
        return _box(w, d, h)

    hole_nodes = [
        IRNode(
            op="translate",
            params={"x": float(x), "y": float(y), "z": -0.5},
            children=[IRNode(op="cylinder", params={"radius": hole_r, "height": h + 1})],
            comment=f"hole {i+1}",
        )
        for i, (x, y) in enumerate(positions)
    ]

    holes = hole_nodes[0] if len(hole_nodes) == 1 else IRNode(op="union", children=hole_nodes)

    plate = IRNode(
        op="translate",
        params={"x": -w / 2, "y": -d / 2, "z": 0},
        children=[IRNode(op="box", params={"width": w, "depth": d, "height": h})],
        comment="plate",
    )

    return IRNode(op="difference", children=[plate, holes])


def _regex_parse(text: str) -> Optional[IRTree]:
    text = text.strip()

    # "A 위에 B" → union(A, translate(z=A_height) B)
    if "위에" in text:
        idx = text.index("위에")
        base_node = _parse_single_to_node(text[:idx].strip())
        top_node  = _parse_single_to_node(text[idx + 2:].strip())
        if base_node and top_node:
            # Estimate base height for stacking
            base_h = _estimate_height(base_node)
            stacked = IRNode(
                op="union",
                children=[
                    base_node,
                    IRNode(
                        op="translate",
                        params={"x": 0, "y": 0, "z": base_h},
                        children=[top_node],
                        comment="stacked on top",
                    ),
                ],
            )
            return IRTree(root=stacked)

    node = _parse_single_to_node(text)
    if node:
        return IRTree(root=node)

    return None


def _estimate_height(node: IRNode) -> float:
    """Heuristic: extract the height of the topmost shape for stacking."""
    if node.op == "box":
        return node.pf("height", 10)
    if node.op == "cylinder":
        return node.pf("height", 10)
    if node.op == "sphere":
        return node.pf("radius", 5) * 2
    # For translate/union/difference nodes, recurse into first child
    if node.children:
        return _estimate_height(node.children[0])
    return 10.0


# ── AI fallback ───────────────────────────────────────────────────────────────

async def _ai_parse(
    text: str,
    db_system_prompt: Optional[str],
    user_prompt: Optional[str],
) -> IRTree:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "입력을 이해하지 못했습니다. 예시 형식으로 입력해 주세요.\n"
            "예: '100x50x10 박스'  |  '지름 20 높이 50 원기둥'  |  '반지름 15 구'"
        )

    try:
        import anthropic

        # IR system prompt is always included; DB prompt adds domain context
        sys_parts = [_IR_SYSTEM_PROMPT]
        if db_system_prompt:
            sys_parts.append(f"\n추가 도메인 지식:\n{db_system_prompt}")
        if user_prompt:
            sys_parts.append(f"\n사용자 맞춤 지침:\n{user_prompt}")
        combined_sys = "\n".join(sys_parts)

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2048,
            system=combined_sys,
            messages=[{"role": "user", "content": text}],
        )
        raw = msg.content[0].text.strip()

        # Strip markdown fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        data = json.loads(raw)
        tree = IRTree.model_validate(data)
        validate(tree.root)
        return tree

    except IRValidationError as e:
        raise ValueError(f"IR 구조 오류: {e}")
    except json.JSONDecodeError as e:
        raise ValueError(f"AI 응답을 JSON으로 파싱할 수 없습니다: {e}")
    except Exception as e:
        raise ValueError(f"AI 서비스 오류: {e}")

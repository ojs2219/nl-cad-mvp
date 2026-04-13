"""
NL → IR parser.

Design philosophy
─────────────────
Rather than matching complete feature names ("판에 구멍", "박스 위에 원기둥"),
the parser decomposes the input into four semantic components and reassembles
them as an IR tree:

  1. Objects   — what shape(s) are described?   (box / cylinder / sphere / …)
  2. Dimensions — what measurements apply?       (width, height, radius, …)
  3. Patterns  — count / arrangement info?       (N개, 원형, 일렬, grid)
  4. Relations — how are objects placed?         (위에, 안에, 옆에, 가운데)

Partial shapes (hemisphere, quarter shapes, …) are NOT new primitives.
They are expressed via boolean / intersection composition:
  hemisphere  = intersection(sphere, upper-half clip box)
  lower half  = intersection(sphere, translate(z=-r)(box))
  …

Fast path  : regex-based component extraction for common Korean/English input.
Slow path  : Claude API with an IR-aware system prompt (unchanged).
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
  "intersection" keeps shared volume  ← use for partial shapes

TRANSFORMS (exactly 1 child):
  "translate"  params: {x=0, y=0, z=0}
  "rotate"     params: {x=0, y=0, z=0}  (degrees)
  "scale"      params: {x=1, y=1, z=1}
  "mirror"     params: {x=0, y=0, z=0}

PATTERNS (exactly 1 child: the template shape):
  "linear_pattern"    params: {count, spacing: [dx, dy, dz]}
  "circular_pattern"  params: {count, radius [, axis="z"]}

RELATIONS (≥2 children — resolved to geometry before rendering):
  "relation"  params: {type: "on_top_of"|"center_of"|"next_to"|"inside"|"aligned_center"
                       [, axis: "x"|"y"|"z"] [, direction: 1|-1]}
              children: [reference_shape, subject_shape]

━━ Key rules ━━
- All dimensions in mm.
- DO NOT invent new primitives for partial shapes. Use boolean/intersection:
    hemisphere = intersection(sphere, clip_box_for_upper_half)
    quarter cylinder = intersection(cylinder, two clip boxes)
- Use "relation" nodes for semantic placement (on_top_of, inside, …)
- Use "translate" only when you know the exact numeric offset.
- Use "difference" for holes or subtractions.
- Return ONLY the JSON object — no markdown, no explanation.

━━ Examples ━━

"100×50×10 box with a 5mm hole":
{"root":{"op":"difference","children":[
  {"op":"box","params":{"width":100,"depth":50,"height":10},"comment":"plate"},
  {"op":"translate","params":{"x":50,"y":25,"z":-1},
   "children":[{"op":"cylinder","params":{"radius":5,"height":12},"comment":"hole"}]}
]}}

"hemisphere r=30":
{"root":{"op":"intersection","comment":"hemisphere","children":[
  {"op":"sphere","params":{"radius":30}},
  {"op":"translate","params":{"x":-31,"y":-31,"z":0},
   "children":[{"op":"box","params":{"width":62,"depth":62,"height":31},"comment":"upper clip"}]}
]}}

"cylinder on top of box":
{"root":{"op":"relation","params":{"type":"on_top_of"},"children":[
  {"op":"box","params":{"width":60,"depth":60,"height":20}},
  {"op":"cylinder","params":{"radius":10,"height":30}}
]}}

"3 cylinders in a row, 30mm apart, r=10 h=20":
{"root":{"op":"linear_pattern","params":{"count":3,"spacing":[30,0,0]},
 "children":[{"op":"cylinder","params":{"radius":10,"height":20}}]}}

"cylinder r=20 h=5 with 6 holes r=3 arranged in a circle":
{"root":{"op":"difference","children":[
  {"op":"cylinder","params":{"radius":20,"height":5}},
  {"op":"circular_pattern","params":{"count":6,"radius":14},
   "children":[{"op":"cylinder","params":{"radius":3,"height":7}}]}
]}}

"L-bracket extruded 5mm":
{"root":{"op":"linear_extrude","params":{"height":5},
 "children":[{"op":"polygon","params":{"points":[[0,0],[100,0],[100,30],[30,30],[30,100],[0,100]]}}]}}
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


# ── Korean numeral normalizer ─────────────────────────────────────────────────

# Maps Korean numeral words → digits, longest first to avoid partial matches
_KO_NUM: list[tuple[str, str]] = [
    ("열하나", "11"), ("열둘", "12"), ("열셋", "13"), ("열넷", "14"), ("열다섯", "15"),
    ("열여섯", "16"), ("열일곱", "17"), ("열여덟", "18"), ("열아홉", "19"), ("열", "10"),
    ("하나", "1"), ("한", "1"),
    ("둘", "2"), ("두", "2"),
    ("셋", "3"), ("세", "3"),
    ("넷", "4"), ("네", "4"),
    ("다섯", "5"),
    ("여섯", "6"),
    ("일곱", "7"),
    ("여덟", "8"),
    ("아홉", "9"),
]


def _normalize_ko_numerals(text: str) -> str:
    """Convert Korean numeral words before 개 to digit strings.
    "세개" → "3개", "두개" → "2개", etc.
    """
    for word, digit in _KO_NUM:
        text = re.sub(rf"{word}\s*개", f"{digit}개", text)
    return text


# ── component extractors ──────────────────────────────────────────────────────

def _num(text: str, *keywords) -> Optional[float]:
    """Extract first number following any of the given keyword(s)."""
    for kw in keywords:
        m = re.search(rf"{kw}\s*[：:=]?\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if m:
            return float(m.group(1))
    return None


def _extract_dims(text: str) -> dict:
    """Return all dimension values found in text."""
    dims: dict = {}

    # WxDxH shorthand: "100x50x10"
    m = re.search(r"(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)", text)
    if m:
        dims["width"]  = float(m.group(1))
        dims["depth"]  = float(m.group(2))
        dims["height"] = float(m.group(3))

    def _set(key, *kws):
        v = _num(text, *kws)
        if v is not None and key not in dims:
            dims[key] = v

    _set("width",     "가로", "width", r"\bw\b")
    _set("depth",     "세로", "depth", r"\bd\b")
    _set("height",    "높이", "height", r"\bh\b")
    _set("thickness", "두께", "thickness")
    _set("radius",    "반지름", "반경", "radius", r"\br\b")
    _set("diameter",  "지름", "직경", "diameter")

    # Promote diameter → radius
    if "diameter" in dims and "radius" not in dims:
        dims["radius"] = dims["diameter"] / 2

    # height alias: use thickness when height absent
    if "thickness" in dims and "height" not in dims:
        dims["height"] = dims["thickness"]

    # Hole dimensions (separate from main shape)
    hd = _num(text, "구멍.*지름", "홀.*지름", "hole.*diameter")
    hr = _num(text, "구멍.*반지름", "홀.*반지름", "hole.*radius")
    if hd and "hole_radius" not in dims:
        dims["hole_radius"] = hd / 2
    if hr and "hole_radius" not in dims:
        dims["hole_radius"] = hr

    return dims


def _detect_kinds(text: str) -> list[str]:
    """Return shape kinds detected in text, most-specific first."""
    found: list[str] = []

    # Partial shapes — before raw primitives
    if re.search(r"반구|hemisphere", text, re.I):
        found.append("hemisphere")

    # Primitives
    if re.search(r"원기둥|실린더|cylinder", text, re.I):
        found.append("cylinder")
    if re.search(r"원뿔|cone\b", text, re.I):
        found.append("cone")
    if re.search(r"박스|직육면체|상자|box\b", text, re.I):
        found.append("box")
    # "판": flat box — only when "box" not already found
    if re.search(r"\b판\b|plate\b", text, re.I) and "box" not in found:
        found.append("plate")
    # sphere: "구" but exclude 반구 (already found), 구멍, 원기둥
    text_no_special = re.sub(r"반구|구멍|원기둥", "", text)
    if re.search(r"\b구\b", text_no_special):
        found.append("sphere")

    # Hole modifier (attached to plates/boxes)
    if re.search(r"구멍|홀|hole\b", text, re.I):
        found.append("hole")

    return found


def _extract_pattern_info(text: str) -> Optional[dict]:
    """
    Detect count + arrangement keywords.
    Returns {"arrangement": "circular"|"linear", "count": N, ...} or None.

    Handles Korean numeral words ("세개" → 3) before matching.
    """
    # Normalize Korean numeral words first
    t = _normalize_ko_numerals(text)

    # ── circular ─────────────────────────────────────────────────────────────
    m = re.search(
        r"(\d+)\s*개\s*(?:씩\s*)?원형|원형으로\s*(\d+)\s*개?|circular\s*(\d+)",
        t, re.I
    )
    if m:
        count = int(next(v for v in m.groups() if v is not None))
        # Pattern radius: explicit keyword or "중심으로부터 N 떨어진"
        pat_r = (
            _num(t, "패턴.*반지름", "배치.*반지름")
            or _extract_center_distance(t)
        )
        return {"arrangement": "circular", "count": count, "radius": pat_r}

    # ── grid ──────────────────────────────────────────────────────────────────
    m = re.search(r"(\d+)\s*[xX×]\s*(\d+)\s*(?:배열|grid)", t, re.I)
    if m:
        rows, cols = int(m.group(1)), int(m.group(2))
        spacing = _num(t, "간격", "spacing") or 30.0
        return {"arrangement": "grid", "rows": rows, "cols": cols, "spacing": spacing}

    # ── linear ────────────────────────────────────────────────────────────────
    # exclude hole count "구멍 N개" before matching
    t_no_hole = re.sub(r"구멍\s*\d+\s*개|\d+\s*개\s*구멍", "", t)
    m = re.search(
        r"(\d+)\s*개\s*(?:씩\s*)?(?:일렬|linear|row)|(\d+)\s*개.*간격",
        t_no_hole, re.I
    )
    if m:
        count = int(next(v for v in m.groups() if v is not None))
        if count > 1:
            spacing = _num(t, "간격", "spacing") or 30.0
            return {"arrangement": "linear", "count": count, "spacing": spacing}

    return None


def _extract_center_distance(text: str) -> Optional[float]:
    """Extract distance from center: '중심으로부터 N 떨어진' or '중심에서 N'."""
    m = re.search(r"중심(?:으로)?부터\s*(\d+(?:\.\d+)?)|중심에서\s*(\d+(?:\.\d+)?)", text)
    if m:
        return float(next(v for v in m.groups() if v is not None))
    return None


# ── shape builders ────────────────────────────────────────────────────────────

def _box_node(w: float, d: float, h: float) -> IRNode:
    """Box centred at XY origin, bottom at Z=0."""
    return IRNode(
        op="translate",
        params={"x": round(-w / 2, 4), "y": round(-d / 2, 4), "z": 0},
        children=[IRNode(op="box", params={"width": w, "depth": d, "height": h})],
    )


def _cylinder_node(r: float, h: float) -> IRNode:
    return IRNode(op="cylinder", params={"radius": r, "height": h})


def _sphere_node(r: float) -> IRNode:
    return IRNode(op="sphere", params={"radius": r})


def _hemisphere_node(r: float, upper: bool = True) -> IRNode:
    """
    Upper hemisphere = intersection(sphere, clip box covering upper half).
    This is the canonical "partial shape via boolean" pattern — no new primitive.
    """
    eps = max(r * 0.01, 0.5)          # small clearance for clean boolean
    clip_h = round(r + eps, 4)
    clip_xy = round(r + eps, 4)
    z_offset = 0.0 if upper else round(-(r + eps), 4)

    clip = IRNode(
        op="translate",
        params={"x": round(-clip_xy, 4), "y": round(-clip_xy, 4), "z": z_offset},
        children=[
            IRNode(
                op="box",
                params={"width": round(2 * clip_xy, 4),
                        "depth": round(2 * clip_xy, 4),
                        "height": clip_h},
                comment="hemisphere clip",
            )
        ],
    )
    return IRNode(
        op="intersection",
        children=[IRNode(op="sphere", params={"radius": r}), clip],
        comment="hemisphere (upper)" if upper else "hemisphere (lower)",
    )


def _build_shape_node(kind: str, dims: dict) -> Optional[IRNode]:
    """Build the base geometry node for a detected shape kind."""

    if kind in ("box", "plate"):
        w = dims.get("width")
        d = dims.get("depth")
        h = dims.get("height")
        if w and d and h:
            return _box_node(w, d, h)
        return None

    if kind == "cylinder":
        r = dims.get("radius")
        h = dims.get("height")
        if r:
            # Default height = radius (sensible for decorative/pattern cylinders)
            return _cylinder_node(r, h if h else round(r, 4))
        return None

    if kind == "sphere":
        r = dims.get("radius")
        if r:
            return _sphere_node(r)
        return None

    if kind == "hemisphere":
        r = dims.get("radius")
        if r:
            return _hemisphere_node(r)
        return None

    if kind == "cone":
        r1 = dims.get("radius", dims.get("r1", 10.0))
        r2 = dims.get("r2", 0.0)
        h  = dims.get("height")
        if h:
            return IRNode(op="cone", params={"r1": r1, "r2": r2, "height": h})
        return None

    return None


def _apply_holes(
    shape: IRNode,
    hole_count: int,
    hole_r: float,
    dims: dict,
) -> IRNode:
    """Return difference(shape, holes) using circular_pattern for N>1."""
    plate_w = dims.get("width", 100.0)
    plate_d = dims.get("depth", plate_w)
    h       = dims.get("height", 10.0)

    if hole_count == 1:
        hole = IRNode(
            op="cylinder",
            params={"radius": hole_r, "height": round(h + 2, 4)},
            comment="hole",
        )
        holes: IRNode = IRNode(
            op="translate",
            params={"x": 0, "y": 0, "z": -1},
            children=[hole],
        )
    elif hole_count <= 4:
        # Use explicit translated cylinders for small counts
        from services.scad_generator import get_hole_positions
        positions = get_hole_positions(hole_count, plate_w, plate_d)
        hole_nodes = [
            IRNode(
                op="translate",
                params={"x": round(float(x), 4), "y": round(float(y), 4), "z": -1},
                children=[
                    IRNode(
                        op="cylinder",
                        params={"radius": hole_r, "height": round(h + 2, 4)},
                        comment=f"hole {i + 1}",
                    )
                ],
            )
            for i, (x, y) in enumerate(positions)
        ]
        holes = hole_nodes[0] if len(hole_nodes) == 1 \
            else IRNode(op="union", children=hole_nodes)
    else:
        # Use circular_pattern for large counts
        pat_r = round(min(plate_w, plate_d) * 0.35, 4)
        hole_template = IRNode(
            op="cylinder",
            params={"radius": hole_r, "height": round(h + 2, 4)},
            comment="hole template",
        )
        holes = IRNode(
            op="translate",
            params={"x": 0, "y": 0, "z": -1},
            children=[
                IRNode(
                    op="circular_pattern",
                    params={"count": hole_count, "radius": pat_r},
                    children=[hole_template],
                )
            ],
        )

    return IRNode(op="difference", children=[shape, holes])


def _apply_pattern(node: IRNode, info: dict) -> IRNode:
    """Wrap a shape node in a linear_pattern or circular_pattern."""
    arrangement = info["arrangement"]

    if arrangement == "circular":
        count = info["count"]
        # Default pattern radius: larger than shape footprint
        radius = info.get("radius") or 20.0
        return IRNode(
            op="circular_pattern",
            params={"count": count, "radius": radius},
            children=[node],
        )

    if arrangement == "linear":
        count   = info["count"]
        spacing = info.get("spacing", 30.0)
        return IRNode(
            op="linear_pattern",
            params={"count": count, "spacing": [spacing, 0, 0]},
            children=[node],
        )

    if arrangement == "grid":
        rows    = info.get("rows", 2)
        cols    = info.get("cols", 2)
        spacing = info.get("spacing", 30.0)
        # Grid = linear_pattern(linear_pattern(shape))
        row_strip = IRNode(
            op="linear_pattern",
            params={"count": cols, "spacing": [spacing, 0, 0]},
            children=[node],
        )
        return IRNode(
            op="linear_pattern",
            params={"count": rows, "spacing": [0, spacing, 0]},
            children=[row_strip],
        )

    return node


# ── segment parser ────────────────────────────────────────────────────────────

def _parse_segment(text: str) -> Optional[IRNode]:
    """
    Parse a single object description.
    Detects shape kind → extracts dims → applies holes → applies pattern.
    """
    text = text.strip()
    if not text:
        return None

    kinds = _detect_kinds(text)
    if not kinds:
        return None

    dims    = _extract_dims(text)
    pattern = _extract_pattern_info(text)

    # Determine main shape (first non-hole kind)
    main_kind = next((k for k in kinds if k != "hole"), None)
    if main_kind is None:
        return None

    shape = _build_shape_node(main_kind, dims)
    if shape is None:
        return None

    # Apply hole modifier for plate/box
    if "hole" in kinds and main_kind in ("plate", "box"):
        hole_r = dims.get("hole_radius") or dims.get("radius") or 5.0
        # Hole count
        cm = (
            re.search(r"구멍\s*(\d+)\s*개", text)
            or re.search(r"(\d+)\s*개?\s*구멍", text)
            or re.search(r"hole[s]?\s*[×x]?\s*(\d+)", text, re.I)
        )
        hole_count = int(cm.group(1)) if cm else 1
        shape = _apply_holes(shape, hole_count, hole_r, dims)

    # Apply pattern if detected in this segment
    if pattern:
        shape = _apply_pattern(shape, pattern)

    return shape


# ── relation splitters ────────────────────────────────────────────────────────

# (keyword, relation_type)  — ordered longest-first to avoid partial matches
_RELATION_SPLITTERS: list[tuple[str, str]] = [
    ("가운데에", "center_of"),
    ("중앙에",   "center_of"),
    ("가운데",   "center_of"),
    ("위에",     "on_top_of"),
    ("위로",     "on_top_of"),
    ("안에",     "inside"),
    ("옆에",     "next_to"),
    ("on top of", "on_top_of"),
    ("inside",    "inside"),
    ("next to",   "next_to"),
    ("centered on", "center_of"),
]


def _regex_parse(text: str) -> Optional[IRTree]:
    """
    Component-based fast-path parser.

    1. Try to split on a relation keyword → build relation node.
    2. Otherwise parse as a single shape segment.
    """
    text = text.strip()

    # ── relation split ────────────────────────────────────────────────────────
    for kw, rel_type in _RELATION_SPLITTERS:
        idx = text.lower().find(kw)
        if idx == -1:
            continue
        left  = text[:idx].strip()
        right = text[idx + len(kw):].strip()

        left_node  = _parse_segment(left)
        right_node = _parse_segment(right)

        if left_node and right_node:
            relation = IRNode(
                op="relation",
                params={"type": rel_type},
                children=[left_node, right_node],
            )
            return IRTree(root=relation)

    # ── single segment ────────────────────────────────────────────────────────
    node = _parse_segment(text)
    if node:
        return IRTree(root=node)

    return None


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
            "예: '100x50x10 박스'  |  '지름 20 높이 50 원기둥'  |  '반지름 15 구'  |  '반지름 30 반구'"
        )

    try:
        import anthropic

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

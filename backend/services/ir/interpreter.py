"""
IR Interpreter — geometry-language two-stage extraction.

Pipeline
────────
  NL text (반정형 입력)
    │
    ▼  Stage 1: interpret()
  IRDraft  ← primitive / profile / generator / pattern / modifier / relation
    │
    ▼  Stage 2: validate()
  ValueError  ← specific Korean error for missing required params
    │  (valid)
    ▼  Stage 3: build_ir()
  IRTree  ← geometry instruction tree with parse_summary metadata

Design rules
────────────
* No "feature" names are detected.  Only geometry elements are extracted:
    primitive  (box, cylinder, sphere, cone)
    composite  (hemisphere = sphere+clip, trapezoid_pillar = profile+extrude,
                n_gon_pillar = regular_polygon+extrude)
    modifier   (hole → difference subtraction)
    pattern    (linear_pattern, circular_pattern, grid_pattern)
    relation   (on_top_of, inside, center_of, next_to)

* hemisphere is NOT a primitive.  It is intersection(sphere, upper_clip_box).
* trapezoid_pillar is NOT a primitive.
  It is linear_extrude(depth, trapezoid_profile(bw, tw, h)).
* n_gon_pillar is NOT a primitive.
  It is linear_extrude(height, regular_polygon(sides, radius)).
* grid_pattern is a proper IR node (not nested linear_patterns).
* Validation uses GEO_DICT required-param lists — no ad-hoc checks.
* AI is never called here.  parse_to_ir() in parser.py handles AI fallback.
"""
from __future__ import annotations

import re
import math
from dataclasses import dataclass, field
from typing import Any, Optional

from services.ir.schema import IRNode, IRTree
from services.ir.shape_dict import (
    GEO_DICT, COMPOSITE_FORMS, N_GON_SIDES,
    POSITION_ANCHORS, RELATION_KEYWORDS,
    display_name, display_param,
)


# ── data classes ──────────────────────────────────────────────────────────────

@dataclass
class _HoleSpec:
    radius: float
    position: tuple[float, float]
    count: int = 1


@dataclass
class _PatternSpec:
    arrangement: str          # "linear" | "circular" | "grid"
    count: int
    radius: Optional[float] = None
    spacing: Optional[float] = None
    rows: int = 1
    cols: int = 1
    row_spacing: Optional[float] = None
    col_spacing: Optional[float] = None


@dataclass
class _ObjectSpec:
    kind: str                        # primitive / composite key
    dims: dict[str, float]
    hole: Optional[_HoleSpec] = None
    pattern: Optional[_PatternSpec] = None
    comment: str = ""
    sides: int = 0                   # for n_gon_pillar


@dataclass
class IRDraft:
    objects: list[_ObjectSpec] = field(default_factory=list)
    relation: Optional[tuple[str, int, int]] = None
    errors: list[str] = field(default_factory=list)
    summary: str = ""
    summary_json: dict = field(default_factory=dict)


# ── Korean numeral normaliser ─────────────────────────────────────────────────

_KO_NUM: list[tuple[str, str]] = [
    ("열하나","11"),("열둘","12"),("열셋","13"),("열넷","14"),("열다섯","15"),
    ("열여섯","16"),("열일곱","17"),("열여덟","18"),("열아홉","19"),("열","10"),
    ("하나","1"),("한","1"),("둘","2"),("두","2"),("셋","3"),("세","3"),
    ("넷","4"),("네","4"),("다섯","5"),("여섯","6"),("일곱","7"),
    ("여덟","8"),("아홉","9"),
]

def _norm(text: str) -> str:
    for word, digit in _KO_NUM:
        text = re.sub(rf"{word}\s*개", f"{digit}개", text)
    return text


# ── numeric extractor ─────────────────────────────────────────────────────────

def _num(text: str, *kws: str) -> Optional[float]:
    for kw in kws:
        m = re.search(rf"{kw}\s*[：:=]?\s*(\d+(?:\.\d+)?)", text, re.I)
        if m:
            return float(m.group(1))
    return None


# ── dimension extractor ───────────────────────────────────────────────────────

def extract_dims(text: str) -> dict[str, float]:
    dims: dict[str, float] = {}

    # WxDxH shorthand
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)", text
    )
    if m:
        dims["width"]  = float(m.group(1))
        dims["depth"]  = float(m.group(2))
        dims["height"] = float(m.group(3))

    def _set(key: str, *kws: str) -> None:
        if key not in dims:
            v = _num(text, *kws)
            if v is not None:
                dims[key] = v

    # Standard dimensions
    _set("width",        "가로", "너비", "width")
    _set("depth",        "세로", "깊이", "depth")
    _set("height",       "높이", "height")
    _set("thickness",    "두께", "thickness")
    _set("radius",       "반지름", "반경", "radius")
    _set("diameter",     "지름", "직경", "diameter")

    # Trapezoid profile dimensions
    _set("bottom_width", "아래너비", "아래 너비", "아래쪽 너비", "아래폭", "bottom.width")
    _set("top_width",    "위너비",   "위 너비",   "위쪽 너비",   "위폭",   "top.width")

    # Grid pattern spacing
    _set("row_spacing",  "행.{0,3}간격", "row.spacing")
    _set("col_spacing",  "열.{0,3}간격", "col.spacing")

    # Promotions
    if "diameter" in dims and "radius" not in dims:
        dims["radius"] = dims["diameter"] / 2
    if "thickness" in dims and "height" not in dims:
        dims["height"] = dims["thickness"]

    return dims


# ── element detector ──────────────────────────────────────────────────────────

def detect_kinds(text: str) -> list[str]:
    """
    Return list of geometry element kinds detected in text.
    Composite forms (hemisphere, trapezoid_pillar, n_gon_pillar) are checked
    first and take priority over raw primitives.
    """
    found: list[str] = []

    # ── composites first ──────────────────────────────────────────────────
    if re.search(r"반구|hemisphere", text, re.I):
        found.append("hemisphere")

    if re.search(r"사다리꼴|trapezoid", text, re.I):
        found.append("trapezoid_pillar")

    # N-gon pillar: "육각기둥", "육각형 기둥", "육각형", etc.
    ngon_sides = _detect_n_gon_sides(text)
    if ngon_sides and ngon_sides != 4:   # 4각 = box, handled separately
        found.append("n_gon_pillar")

    # ── shape primitives ──────────────────────────────────────────────────
    if re.search(r"원기둥|실린더|cylinder", text, re.I):
        found.append("cylinder")
    if re.search(r"원뿔|cone\b", text, re.I):
        found.append("cone")
    if re.search(r"박스|직육면체|상자|box\b", text, re.I):
        found.append("box")
    if re.search(r"\b판\b|plate\b", text, re.I) and "box" not in found:
        found.append("plate")

    # sphere: "구" but not 반구, 구멍, 원기둥
    for_sphere = re.sub(r"반구|구멍|관통홀|원기둥", "", text)
    if re.search(r"\b구\b", for_sphere):
        found.append("sphere")

    # ── modifier ──────────────────────────────────────────────────────────
    if re.search(r"구멍|관통홀|홀|hole\b", text, re.I):
        found.append("hole")

    return found


def _detect_n_gon_sides(text: str) -> Optional[int]:
    """Extract n-gon side count from text: '육각기둥' → 6, '5각형' → 5."""
    for prefix, sides in N_GON_SIDES.items():
        if re.search(rf"{prefix}각\s*(?:기둥|형|prism|pillar)?", text, re.I):
            return sides
    # Numeric: "N각형" / "N각기둥"
    m = re.search(r"(\d+)\s*각\s*(?:형|기둥|prism)", text, re.I)
    if m:
        return int(m.group(1))
    return None


# ── pattern extractor ─────────────────────────────────────────────────────────

def extract_pattern(text: str) -> Optional[_PatternSpec]:
    t = _norm(text)

    # circular
    m = re.search(
        r"(\d+)\s*개\s*(?:씩\s*)?원형|원형으로\s*(\d+)\s*개?|circular\s*(\d+)", t, re.I
    )
    if m:
        count = int(next(v for v in m.groups() if v))
        dist = _center_distance(t)
        return _PatternSpec("circular", count, radius=dist)

    # grid: "2x3 배열" or "2x3 격자"
    m = re.search(r"(\d+)\s*[xX×]\s*(\d+)\s*(?:배열|격자|grid)", t, re.I)
    if m:
        rows, cols = int(m.group(1)), int(m.group(2))
        sp = _num(t, "간격", "spacing") or 30.0
        rs = _num(t, r"행.{0,3}간격", "row.spacing") or sp
        cs = _num(t, r"열.{0,3}간격", "col.spacing") or sp
        return _PatternSpec("grid", rows * cols, spacing=sp,
                            rows=rows, cols=cols, row_spacing=rs, col_spacing=cs)

    # linear — exclude hole counts
    t2 = re.sub(r"구멍\s*\d+\s*개|\d+\s*개\s*구멍", "", t)
    m = re.search(
        r"(\d+)\s*개\s*(?:씩\s*)?(?:일렬|linear|row)|(\d+)\s*개.*간격", t2, re.I
    )
    if m:
        count = int(next(v for v in m.groups() if v))
        if count > 1:
            sp = _num(t, "간격", "spacing") or 30.0
            return _PatternSpec("linear", count, spacing=sp)

    return None


def _center_distance(text: str) -> Optional[float]:
    m = re.search(r"중심(?:으로)?부터\s*(\d+(?:\.\d+)?)|중심에서\s*(\d+(?:\.\d+)?)", text)
    if m:
        return float(next(v for v in m.groups() if v))
    return None


# ── hole extractor ────────────────────────────────────────────────────────────

def extract_hole(text: str) -> Optional[_HoleSpec]:
    """
    Extract hole spec if present AND position is explicit.
    Returns None when position is missing (caller emits an error).
    """
    if not re.search(r"구멍|관통홀|홀|hole\b", text, re.I):
        return None

    pos: Optional[tuple[float, float]] = None
    for kw, xy in POSITION_ANCHORS.items():
        if kw in text.lower():
            pos = xy
            break
    if pos is None:
        return None

    hr = (_num(text, r"구멍.*반지름", r"홀.*반지름", r"hole.*radius")
          or _num(text, "반지름", "반경", "radius"))
    hd = _num(text, r"구멍.*지름", r"홀.*지름", "지름", "직경", "diameter")
    if hd and not hr:
        hr = hd / 2
    if not hr:
        return None

    cm = (re.search(r"구멍\s*(\d+)\s*개", text)
          or re.search(r"(\d+)\s*개\s*구멍", text)
          or re.search(r"holes?\s*[×x]?\s*(\d+)", text, re.I))
    count = int(cm.group(1)) if cm else 1

    return _HoleSpec(radius=hr, position=pos, count=count)


# ── IR node builders ──────────────────────────────────────────────────────────

def _box_node(w: float, d: float, h: float) -> IRNode:
    return IRNode(
        op="translate",
        params={"x": round(-w / 2, 4), "y": round(-d / 2, 4), "z": 0},
        children=[IRNode(op="box", params={"width": w, "depth": d, "height": h})],
    )

def _cylinder_node(r: float, h: float) -> IRNode:
    return IRNode(op="cylinder", params={"radius": r, "height": h})

def _sphere_node(r: float) -> IRNode:
    return IRNode(op="sphere", params={"radius": r})

def _hemisphere_node(r: float) -> IRNode:
    """
    Upper hemisphere = intersection(sphere, upper_clip_box).
    Composite form — no 'hemisphere' op in the IR.
    """
    eps = max(r * 0.01, 0.5)
    ch = round(r + eps, 4); cxy = round(r + eps, 4)
    clip = IRNode(
        op="translate",
        params={"x": round(-cxy, 4), "y": round(-cxy, 4), "z": 0.0},
        children=[IRNode(op="box",
                         params={"width": round(2*cxy,4),
                                 "depth": round(2*cxy,4),
                                 "height": ch},
                         comment="hemisphere clip")],
    )
    return IRNode(op="intersection",
                  children=[IRNode(op="sphere", params={"radius": r}), clip],
                  comment="hemisphere = intersection(sphere, upper_clip)")

def _trapezoid_pillar_node(bw: float, tw: float, ph: float, depth: float) -> IRNode:
    """
    Trapezoid prism = linear_extrude(depth, trapezoid_profile(bw, tw, ph)).
    Composite form — no 'trapezoid_pillar' op in the IR.
    """
    profile = IRNode(
        op="trapezoid",
        params={"bottom_width": bw, "top_width": tw, "height": ph},
        comment="trapezoid cross-section",
    )
    return IRNode(
        op="linear_extrude",
        params={"height": depth},
        children=[profile],
        comment=f"trapezoid_pillar bw={bw} tw={tw} h={ph} depth={depth}",
    )

def _n_gon_pillar_node(sides: int, r: float, h: float) -> IRNode:
    """
    N-gon prism = linear_extrude(h, regular_polygon(sides, r)).
    Composite form — no 'n_gon_pillar' op in the IR.
    """
    profile = IRNode(
        op="regular_polygon",
        params={"sides": sides, "radius": r},
        comment=f"{sides}각형 단면",
    )
    return IRNode(
        op="linear_extrude",
        params={"height": h},
        children=[profile],
        comment=f"{sides}각기둥 r={r} h={h}",
    )

def _build_shape(spec: _ObjectSpec) -> Optional[IRNode]:
    d = spec.dims
    k = spec.kind

    if k in ("box", "plate"):
        return _box_node(d["width"], d["depth"], d["height"])
    if k == "cylinder":
        r = d["radius"]; h = d.get("height", r)
        return _cylinder_node(r, h)
    if k == "sphere":
        return _sphere_node(d["radius"])
    if k == "hemisphere":
        return _hemisphere_node(d["radius"])
    if k == "cone":
        return IRNode(op="cone",
                      params={"r1": d["r1"], "r2": d.get("r2", 0.0), "height": d["height"]})
    if k == "trapezoid_pillar":
        return _trapezoid_pillar_node(
            d["bottom_width"], d["top_width"], d["height"], d["depth"]
        )
    if k == "n_gon_pillar":
        return _n_gon_pillar_node(spec.sides, d["radius"], d["height"])
    return None

def _build_holes(shape: IRNode, hole: _HoleSpec, main_dims: dict) -> IRNode:
    w = main_dims.get("width", 100.0); dep = main_dims.get("depth", w)
    h = main_dims.get("height", 10.0)

    if hole.count == 1:
        cyl = IRNode(op="cylinder",
                     params={"radius": hole.radius, "height": round(h + 2, 4)},
                     comment="관통홀")
        hole_node = IRNode(op="translate",
                           params={"x": hole.position[0], "y": hole.position[1], "z": -1.0},
                           children=[cyl])
    elif hole.count <= 4:
        from services.scad_generator import get_hole_positions
        positions = get_hole_positions(hole.count, w, dep)
        nodes = [
            IRNode(op="translate",
                   params={"x": round(float(x), 4), "y": round(float(y), 4), "z": -1.0},
                   children=[IRNode(op="cylinder",
                                    params={"radius": hole.radius, "height": round(h+2,4)},
                                    comment=f"관통홀 {i+1}")])
            for i, (x, y) in enumerate(positions)
        ]
        hole_node = nodes[0] if len(nodes) == 1 else IRNode(op="union", children=nodes)
    else:
        pat_r = round(min(w, dep) * 0.35, 4)
        tmpl = IRNode(op="cylinder",
                      params={"radius": hole.radius, "height": round(h+2,4)},
                      comment="관통홀 템플릿")
        hole_node = IRNode(op="translate",
                           params={"x": 0, "y": 0, "z": -1.0},
                           children=[IRNode(op="circular_pattern",
                                            params={"count": hole.count, "radius": pat_r},
                                            children=[tmpl])])
    return IRNode(op="difference", children=[shape, hole_node])

def _build_pattern(node: IRNode, spec: _PatternSpec) -> IRNode:
    if spec.arrangement == "circular":
        return IRNode(op="circular_pattern",
                      params={"count": spec.count, "radius": spec.radius or 20.0},
                      children=[node])
    if spec.arrangement == "linear":
        sp = spec.spacing or 30.0
        return IRNode(op="linear_pattern",
                      params={"count": spec.count, "spacing": [sp, 0, 0]},
                      children=[node])
    if spec.arrangement == "grid":
        rs = spec.row_spacing or spec.spacing or 30.0
        cs = spec.col_spacing or spec.spacing or 30.0
        return IRNode(op="grid_pattern",
                      params={"rows": spec.rows, "cols": spec.cols,
                              "row_spacing": rs, "col_spacing": cs},
                      children=[node])
    return node

def _build_node(spec: _ObjectSpec) -> Optional[IRNode]:
    node = _build_shape(spec)
    if node is None:
        return None
    if spec.hole:
        node = _build_holes(node, spec.hole, spec.dims)
    if spec.pattern:
        node = _build_pattern(node, spec.pattern)
    return node


# ── segment interpreter ───────────────────────────────────────────────────────

def _interpret_segment(text: str) -> tuple[Optional[_ObjectSpec], list[str]]:
    """
    Interpret one shape segment → (_ObjectSpec, errors).
    Validates required params from GEO_DICT / COMPOSITE_FORMS.
    """
    kinds = detect_kinds(text)
    errors: list[str] = []

    main_kind = next((k for k in kinds if k != "hole"), None)
    if not main_kind:
        return None, ["형상 종류를 인식할 수 없습니다. 예: 박스, 원기둥, 구, 반구, 판, 사다리꼴, 육각기둥"]

    dims = extract_dims(text)
    sides = 0

    # ── required param validation ─────────────────────────────────────────
    if main_kind in COMPOSITE_FORMS:
        form = COMPOSITE_FORMS[main_kind]
        required = form["required"]

        # Special case: n_gon_pillar — extract sides from text
        if main_kind == "n_gon_pillar":
            sides = _detect_n_gon_sides(text) or 6
            required = [r for r in required if r != "sides"]

        # depth of trapezoid_pillar: accept "depth" or "깊이", else fall back to height
        if main_kind == "trapezoid_pillar" and "depth" not in dims and "height" in dims:
            dims["depth"] = dims["height"]
            # If bottom_width/top_width not explicit but width is, infer them
            if "bottom_width" not in dims and "width" in dims:
                dims["bottom_width"] = dims["width"]
            if "top_width" not in dims and "width" in dims:
                dims["top_width"] = dims["width"] * 0.6

        for req in required:
            if req not in dims:
                kind_ko = display_name(main_kind)
                param_ko = display_param(req)
                errors.append(f"'{kind_ko}'에 {param_ko}이(가) 필요합니다")

    else:
        # Primitive validation via GEO_DICT
        entry = GEO_DICT.get(main_kind)
        if entry:
            for req in entry.required:
                if req not in dims:
                    kind_ko = display_name(main_kind)
                    param_ko = display_param(req)
                    errors.append(f"'{kind_ko}'에 {param_ko}이(가) 필요합니다")

    if errors:
        return None, errors

    # ── hole validation ───────────────────────────────────────────────────
    hole_spec: Optional[_HoleSpec] = None
    if "hole" in kinds and main_kind in ("box", "plate"):
        has_position = bool(re.search(r"중심|중앙|가운데|center", text, re.I))
        hole_r = (_num(text, r"구멍.*반지름", r"홀.*반지름", r"hole.*radius")
                  or _num(text, "반지름", "반경", "radius"))
        if not has_position:
            errors.append(
                "구멍 위치가 명시되지 않았습니다. "
                "'중심에', '중앙에', '가운데에' 중 하나를 추가하세요."
            )
        elif not hole_r:
            errors.append("구멍의 반지름이 필요합니다. 예: '반지름 5 구멍'")
        else:
            hole_spec = extract_hole(text)

    if errors:
        return None, errors

    pat_spec = extract_pattern(text)

    spec = _ObjectSpec(
        kind=main_kind,
        dims=dims,
        hole=hole_spec,
        pattern=pat_spec,
        comment=_make_comment(main_kind, dims, sides),
        sides=sides,
    )
    return spec, []


def _make_comment(kind: str, dims: dict, sides: int = 0) -> str:
    if kind in ("box", "plate"):
        return (f"{display_name(kind)} "
                f"{dims.get('width',0)}×{dims.get('depth',0)}×{dims.get('height',0)}mm")
    if kind == "cylinder":
        return f"원기둥 r={dims.get('radius',0)} h={dims.get('height',0)}mm"
    if kind in ("sphere", "hemisphere"):
        return f"{display_name(kind)} r={dims.get('radius',0)}mm"
    if kind == "cone":
        return f"원뿔 r1={dims.get('r1',0)} h={dims.get('height',0)}mm"
    if kind == "trapezoid_pillar":
        return (f"사다리꼴 기둥 "
                f"bw={dims.get('bottom_width',0)} tw={dims.get('top_width',0)} "
                f"h={dims.get('height',0)} d={dims.get('depth',0)}mm")
    if kind == "n_gon_pillar":
        return f"{sides}각기둥 r={dims.get('radius',0)} h={dims.get('height',0)}mm"
    return kind


# ── summary builder ───────────────────────────────────────────────────────────

def _build_summary(draft: IRDraft) -> tuple[str, dict]:
    parts = []
    obj_list = []

    for spec in draft.objects:
        line = spec.comment
        if spec.hole:
            h = spec.hole
            line += f", 중심에 r={h.radius}mm 관통홀 {h.count}개"
        if spec.pattern:
            p = spec.pattern
            if p.arrangement == "circular":
                line += f" (원형 배치 {p.count}개, r={p.radius or '?'}mm)"
            elif p.arrangement == "linear":
                line += f" (일렬 {p.count}개, 간격 {p.spacing or 30}mm)"
            elif p.arrangement == "grid":
                line += f" ({p.rows}×{p.cols} 격자, 행간={p.row_spacing or 30}mm 열간={p.col_spacing or 30}mm)"
        parts.append(line)

        obj_entry: dict[str, Any] = {"형상": display_name(spec.kind), "치수": {}}
        for k, v in spec.dims.items():
            obj_entry["치수"][display_param(k)] = v
        if spec.sides:
            obj_entry["변의수"] = spec.sides
        if spec.hole:
            obj_entry["구멍"] = {"반지름": spec.hole.radius, "위치": "중심", "개수": spec.hole.count}
        if spec.pattern:
            obj_entry["패턴"] = {"배치": spec.pattern.arrangement, "개수": spec.pattern.count}
        obj_list.append(obj_entry)

    rel_str = "없음"
    if draft.relation:
        rel_type, ri, si = draft.relation
        rel_map = {"on_top_of":"위에 배치","center_of":"중심에 배치",
                   "inside":"내부 (차집합)","next_to":"옆에 배치"}
        ref = draft.objects[ri].comment if ri < len(draft.objects) else f"객체{ri}"
        subj = draft.objects[si].comment if si < len(draft.objects) else f"객체{si}"
        rel_str = f"{ref} {rel_map.get(rel_type, rel_type)} → {subj}"

    summary_text = " / ".join(parts) if parts else "해석 실패"
    if draft.relation:
        summary_text += f" [{rel_str}]"

    summary_json: dict[str, Any] = {"객체": obj_list, "관계": rel_str, "요약": summary_text}
    return summary_text, summary_json


# ── public API ────────────────────────────────────────────────────────────────

def interpret(text: str) -> IRDraft:
    """
    Stage 1 — decompose NL text into a structured IRDraft.
    Errors are collected in draft.errors; no exceptions raised.
    """
    text = text.strip()
    draft = IRDraft()

    # ── relation split ────────────────────────────────────────────────────
    split_kw: Optional[str] = None
    split_rel: Optional[str] = None
    split_idx: int = -1

    for kw, rel_type in RELATION_KEYWORDS:
        idx = text.lower().find(kw)
        if idx != -1:
            split_kw, split_rel, split_idx = kw, rel_type, idx
            break

    if split_kw and split_rel:
        left  = text[:split_idx].strip()
        right = text[split_idx + len(split_kw):].strip()

        left_spec,  left_errs  = _interpret_segment(left)
        right_spec, right_errs = _interpret_segment(right)

        if left_errs:
            draft.errors += [f"기준 객체: {e}" for e in left_errs]
        if right_errs:
            draft.errors += [f"배치 객체: {e}" for e in right_errs]
        if left_spec:
            draft.objects.append(left_spec)
        if right_spec:
            draft.objects.append(right_spec)
        if not draft.errors and left_spec and right_spec:
            draft.relation = (split_rel, 0, 1)
        elif not left_spec and not right_spec:
            draft.errors.append("관계 표현에서 두 객체를 모두 인식하지 못했습니다.")
    else:
        spec, errs = _interpret_segment(text)
        draft.errors += errs
        if spec:
            draft.objects.append(spec)

    if not draft.errors:
        draft.summary, draft.summary_json = _build_summary(draft)
    else:
        draft.summary = "해석 실패: " + "; ".join(draft.errors)
        draft.summary_json = {"오류": draft.errors, "입력": text}

    return draft


def validate(draft: IRDraft) -> None:
    """Stage 2 — raise ValueError with specific Korean message if errors exist."""
    if draft.errors:
        raise ValueError("\n".join(draft.errors))


def build_ir(draft: IRDraft) -> IRTree:
    """Stage 3 — construct IRTree from a validated IRDraft."""
    if draft.errors:
        raise ValueError("IRDraft에 오류가 있어 IR을 생성할 수 없습니다.")

    if draft.relation:
        rel_type, ri, si = draft.relation
        ref_node  = _build_node(draft.objects[ri])
        subj_node = _build_node(draft.objects[si])
        if not ref_node or not subj_node:
            raise ValueError("관계 객체 중 하나의 IR 노드를 생성할 수 없습니다.")
        root = IRNode(op="relation", params={"type": rel_type},
                      children=[ref_node, subj_node])
    elif draft.objects:
        root = _build_node(draft.objects[0])
        if root is None:
            raise ValueError("IR 노드를 생성할 수 없습니다. 파라미터를 확인하세요.")
    else:
        raise ValueError("해석 가능한 객체가 없습니다.")

    return IRTree(root=root, metadata={
        "parse_summary":      draft.summary,
        "parse_summary_json": draft.summary_json,
    })

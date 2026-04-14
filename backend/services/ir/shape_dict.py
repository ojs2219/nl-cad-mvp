"""
Geometry Semantic Dictionary — maps Korean/English surface forms to geometry elements.

Element taxonomy
────────────────
  primitive   → direct 3-D solid  (box, cylinder, sphere, cone)
  profile     → 2-D cross-section (square_2d, circle_2d, trapezoid, regular_polygon, polygon)
  generator   → 2-D → 3-D op     (linear_extrude, rotate_extrude)
  combinator  → boolean op        (union, difference, intersection)
  pattern     → repetition op     (linear_pattern, circular_pattern, grid_pattern)
  placement   → position / orient (translate, rotate, relation)
  modifier    → shape modifier    (hole — produces difference subtraction)

Composite forms (not primitives — resolved into IR subtrees by interpreter)
──────────────────────────────────────────────────────────────────────────────
  hemisphere      = intersection(sphere(r), translate(clip_box))
  trapezoid_pillar = linear_extrude(depth, trapezoid(bw, tw, ph))
  n_gon_pillar    = linear_extrude(height, regular_polygon(n, r))
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


# ── element type ──────────────────────────────────────────────────────────────

ELEMENT_TYPES = frozenset({
    "primitive", "profile", "generator",
    "combinator", "pattern", "placement", "modifier",
})


@dataclass
class GeoEntry:
    """A single entry in the geometry semantic dictionary."""
    element_type: str       # one of ELEMENT_TYPES
    op: str                 # canonical IR op name
    required: list[str]     # required params (missing → validation error)
    note: str = ""


# ── geometry semantic dictionary ──────────────────────────────────────────────

GEO_DICT: dict[str, GeoEntry] = {

    # ── shape primitives ──────────────────────────────────────────────────
    "box":             GeoEntry("primitive", "box",      ["width", "depth", "height"]),
    "cylinder":        GeoEntry("primitive", "cylinder", ["radius", "height"]),
    "sphere":          GeoEntry("primitive", "sphere",   ["radius"]),
    "cone":            GeoEntry("primitive", "cone",     ["r1", "height"]),

    # ── profile primitives (2-D, child of generator) ──────────────────────
    "rectangle":       GeoEntry("profile", "square_2d",       ["width", "height"]),
    "circle_profile":  GeoEntry("profile", "circle_2d",       ["radius"]),
    "trapezoid":       GeoEntry("profile", "trapezoid",
                                ["bottom_width", "top_width", "height"]),
    "regular_polygon": GeoEntry("profile", "regular_polygon", ["sides", "radius"]),
    "polygon":         GeoEntry("profile", "polygon",         ["points"]),

    # ── generators ────────────────────────────────────────────────────────
    "linear_extrude":  GeoEntry("generator", "linear_extrude", ["height"]),
    "revolve":         GeoEntry("generator", "rotate_extrude", []),

    # ── combinators ───────────────────────────────────────────────────────
    "union":           GeoEntry("combinator", "union",        []),
    "difference":      GeoEntry("combinator", "difference",   []),
    "intersection":    GeoEntry("combinator", "intersection", []),

    # ── patterns ──────────────────────────────────────────────────────────
    "linear_pattern":  GeoEntry("pattern", "linear_pattern",  ["count"]),
    "circular_pattern":GeoEntry("pattern", "circular_pattern",["count", "radius"]),
    "grid_pattern":    GeoEntry("pattern", "grid_pattern",    ["rows", "cols"]),

    # ── placement ─────────────────────────────────────────────────────────
    "translate":       GeoEntry("placement", "translate", []),
    "rotate":          GeoEntry("placement", "rotate",    []),
    "relation":        GeoEntry("placement", "relation",  ["type"]),

    # ── modifier ──────────────────────────────────────────────────────────
    "hole":            GeoEntry("modifier", "cylinder", ["radius"],
                                note="관통홀 — 위치 키워드(중심/중앙/가운데) 필수"),
}


# ── composite form rules ──────────────────────────────────────────────────────
# Resolved by interpreter into correct IR subtrees — never appear as IR ops.

COMPOSITE_FORMS: dict[str, dict] = {
    "hemisphere": {
        "description": "intersection(sphere, upper_clip_box)",
        "required":    ["radius"],
        "base":        "sphere",
    },
    "trapezoid_pillar": {
        "description": "linear_extrude(depth, trapezoid(bottom_width, top_width, height))",
        "required":    ["bottom_width", "top_width", "height", "depth"],
        "profile":     "trapezoid",
        "generator":   "linear_extrude",
    },
    "n_gon_pillar": {
        "description": "linear_extrude(height, regular_polygon(sides, radius))",
        "required":    ["radius", "height"],
        "profile":     "regular_polygon",
        "generator":   "linear_extrude",
    },
}


# ── alias table ───────────────────────────────────────────────────────────────
# Surface form (Korean / English) → canonical key in GEO_DICT or COMPOSITE_FORMS

GEO_ALIASES: dict[str, str] = {
    # primitives
    "박스":      "box",       "직육면체": "box",  "상자":   "box",  "box":   "box",
    "판":        "box",       "플레이트": "box",  "plate":  "box",
    "원기둥":    "cylinder",  "실린더":   "cylinder",       "cylinder": "cylinder",
    "구":        "sphere",    "sphere":   "sphere",
    "원뿔":      "cone",      "콘":       "cone",            "cone":   "cone",
    # composites
    "반구":      "hemisphere",           "hemisphere": "hemisphere",
    # profiles
    "사다리꼴":  "trapezoid_pillar",     "trapezoid":  "trapezoid_pillar",
    # n-gon pillars (sides looked up separately via N_GON_SIDES)
    "삼각기둥":  "n_gon_pillar",  "삼각형기둥": "n_gon_pillar",
    "오각기둥":  "n_gon_pillar",  "오각형기둥": "n_gon_pillar",
    "육각기둥":  "n_gon_pillar",  "육각형기둥": "n_gon_pillar",
    "칠각기둥":  "n_gon_pillar",  "칠각형기둥": "n_gon_pillar",
    "팔각기둥":  "n_gon_pillar",  "팔각형기둥": "n_gon_pillar",
    # hole (modifier)
    "구멍":      "hole",  "홀":     "hole",  "hole":  "hole",
    "holes":     "hole",  "관통홀": "hole",
}

# Korean N-gon prefix → number of sides
N_GON_SIDES: dict[str, int] = {
    "삼": 3, "사": 4, "오": 5, "육": 6,
    "칠": 7, "팔": 8, "구": 9, "십": 10,
}


# ── position anchors ──────────────────────────────────────────────────────────

POSITION_ANCHORS: dict[str, tuple[float, float]] = {
    "중심":   (0.0, 0.0),
    "중앙":   (0.0, 0.0),
    "가운데": (0.0, 0.0),
    "center": (0.0, 0.0),
}


# ── relation keywords ─────────────────────────────────────────────────────────
# Ordered longest-first to prevent partial substring matches.

RELATION_KEYWORDS: list[tuple[str, str]] = [
    ("가운데에",    "center_of"),
    ("중앙에",      "center_of"),
    ("가운데",      "center_of"),
    ("위에",        "on_top_of"),
    ("위로",        "on_top_of"),
    ("안에",        "inside"),
    ("옆에",        "next_to"),
    ("on top of",   "on_top_of"),
    ("centered on", "center_of"),
    ("inside",      "inside"),
    ("next to",     "next_to"),
]


# ── display helpers ───────────────────────────────────────────────────────────

_NAME_KO: dict[str, str] = {
    "box":              "박스",
    "cylinder":         "원기둥",
    "sphere":           "구",
    "cone":             "원뿔",
    "hemisphere":       "반구",
    "trapezoid":        "사다리꼴",
    "trapezoid_pillar": "사다리꼴 기둥",
    "regular_polygon":  "정다각형",
    "n_gon_pillar":     "다각 기둥",
    "hole":             "구멍(관통홀)",
}

_PARAM_KO: dict[str, str] = {
    "width":          "너비(가로)",
    "depth":          "깊이(세로)",
    "height":         "높이",
    "radius":         "반지름",
    "r1":             "아래쪽 반지름(r1)",
    "r2":             "위쪽 반지름(r2)",
    "bottom_width":   "아래쪽 너비",
    "top_width":      "위쪽 너비",
    "sides":          "변의 수",
    "count":          "개수",
    "spacing":        "간격",
    "rows":           "행 수",
    "cols":           "열 수",
    "row_spacing":    "행 간격",
    "col_spacing":    "열 간격",
}


def display_name(kind: str) -> str:
    return _NAME_KO.get(kind, kind)


def display_param(param: str) -> str:
    return _PARAM_KO.get(param, param)


# ── lookup helpers ────────────────────────────────────────────────────────────

def lookup(term: str) -> Optional[GeoEntry]:
    """Return GeoEntry for a canonical geo term, or None."""
    return GEO_DICT.get(term)


def alias_to_canonical(surface: str) -> Optional[str]:
    """Map a surface alias to its canonical key (GEO_DICT or COMPOSITE_FORMS)."""
    return GEO_ALIASES.get(surface)

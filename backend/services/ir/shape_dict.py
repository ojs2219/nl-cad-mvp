"""
Shape Dictionary — canonical shape definitions for the NL-CAD interpreter.

Centralises:
  - Korean / English surface aliases → normalised op name
  - Required parameters per shape (missing any → validation error)
  - Position anchor keywords  (hole placement)
  - Relation keywords          (on_top_of, center_of, …)
  - Param display names for user-facing error messages
"""
from __future__ import annotations
from dataclasses import dataclass, field


# ── shape definition ──────────────────────────────────────────────────────────

@dataclass
class ShapeDef:
    op: str                           # canonical IR op  (box / cylinder / …)
    required: list[str]               # dimension keys that MUST be present
    composite: bool = False           # True → built from boolean ops (hemisphere)
    note: str = ""                    # user-facing hint shown in error messages


SHAPE_DEFS: dict[str, ShapeDef] = {
    "box":        ShapeDef("box",      ["width", "depth", "height"]),
    "plate":      ShapeDef("box",      ["width", "depth", "height"]),
    "cylinder":   ShapeDef("cylinder", ["radius", "height"]),
    "sphere":     ShapeDef("sphere",   ["radius"]),
    "hemisphere": ShapeDef("sphere",   ["radius"], composite=True,
                           note="반구 = intersection(구, 상반구 클리핑 박스)"),
    "cone":       ShapeDef("cone",     ["r1", "height"]),
    # 'hole' has its own position-validation path — radius required, position separate
    "hole":       ShapeDef("cylinder", ["radius"],
                           note="관통홀 — 위치 키워드(중심/중앙/가운데)가 필요합니다"),
}


# ── alias tables ──────────────────────────────────────────────────────────────

# Surface alias (Korean + English) → normalised kind key in SHAPE_DEFS
SHAPE_ALIASES: dict[str, str] = {
    # box / plate
    "박스":      "box",
    "직육면체":  "box",
    "상자":      "box",
    "box":       "box",
    "판":        "plate",
    "플레이트":  "plate",
    "plate":     "plate",
    # cylinder
    "원기둥":    "cylinder",
    "실린더":    "cylinder",
    "cylinder":  "cylinder",
    # sphere
    "구":        "sphere",
    "sphere":    "sphere",
    # hemisphere
    "반구":      "hemisphere",
    "hemisphere": "hemisphere",
    # cone
    "원뿔":      "cone",
    "콘":        "cone",
    "cone":      "cone",
    # hole (modifier, not standalone shape)
    "구멍":      "hole",
    "홀":        "hole",
    "hole":      "hole",
    "holes":     "hole",
    "관통홀":    "hole",
}


# ── display names for user-facing messages ────────────────────────────────────

SHAPE_NAME_KO: dict[str, str] = {
    "box":        "박스",
    "plate":      "판",
    "cylinder":   "원기둥",
    "sphere":     "구",
    "hemisphere": "반구",
    "cone":       "원뿔",
    "hole":       "구멍(관통홀)",
}

PARAM_NAME_KO: dict[str, str] = {
    "width":    "너비(가로)",
    "depth":    "깊이(세로)",
    "height":   "높이",
    "radius":   "반지름",
    "r1":       "아래쪽 반지름(r1)",
    "r2":       "위쪽 반지름(r2)",
    "count":    "개수",
    "spacing":  "간격",
}


# ── position anchors ──────────────────────────────────────────────────────────

# Named position keywords → (x, y) offset relative to shape XY centre
POSITION_ANCHORS: dict[str, tuple[float, float]] = {
    "중심":   (0.0, 0.0),
    "중앙":   (0.0, 0.0),
    "가운데": (0.0, 0.0),
    "center": (0.0, 0.0),
}


# ── relation keywords ─────────────────────────────────────────────────────────

# Ordered longest-first to avoid partial substring matches
RELATION_KEYWORDS: list[tuple[str, str]] = [
    ("가운데에",   "center_of"),
    ("중앙에",     "center_of"),
    ("가운데",     "center_of"),
    ("위에",       "on_top_of"),
    ("위로",       "on_top_of"),
    ("안에",       "inside"),
    ("옆에",       "next_to"),
    ("on top of",  "on_top_of"),
    ("centered on","center_of"),
    ("inside",     "inside"),
    ("next to",    "next_to"),
]


# ── helpers ───────────────────────────────────────────────────────────────────

def kind_from_alias(token: str) -> str | None:
    """Map any surface alias to a canonical kind key, or None if unknown."""
    return SHAPE_ALIASES.get(token)


def display_name(kind: str) -> str:
    return SHAPE_NAME_KO.get(kind, kind)


def display_param(param: str) -> str:
    return PARAM_NAME_KO.get(param, param)

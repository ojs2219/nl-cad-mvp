"""
NL → IR parser.

Design philosophy
─────────────────
Two-stage pipeline:

  1. Interpreter (fast path, rule-based)
       interpret(text) → IRDraft  — extract objects / dims / relations / patterns
       validate(draft)            — raise ValueError with specific Korean message
       build_ir(draft) → IRTree  — construct IR tree with parse_summary metadata

  2. AI fallback (Claude API)
       Called only when no shapes were recognised by the rule-based interpreter.
       Produces the same IRTree format; useful for free-form / complex descriptions.

All validation logic, shape detection, and IR construction live in interpreter.py.
This module owns only the two-stage dispatch and the AI prompt.
"""
from __future__ import annotations
import re
import os
import json
from typing import Optional

from services.ir.schema import IRNode, IRTree, validate, IRValidationError
from services.ir.interpreter import (
    interpret,
    validate as validate_draft,
    build_ir,
)


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
    """
    Convert NL text to an IRTree.

    Fast path  : rule-based interpreter (interpreter.py)
    Slow path  : Claude API fallback for unrecognised / complex input
    """
    draft = interpret(text)

    if draft.objects:
        # Shapes were recognised — validate (raises ValueError on error) then build.
        validate_draft(draft)
        return build_ir(draft)

    # No shapes recognised at all → try AI.
    return await _ai_parse(text, system_prompt, user_prompt)


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

"""
IR modifier — apply a natural-language edit request to an existing IRTree.

Strategy:
1. Try regex fast-path for simple param changes (height, radius, width, etc.)
2. Fall back to Claude API for complex modifications.

The modifier also exposes a small set of programmatic patch helpers
(set_param, add_child, remove_child) for when the caller already knows
which node to change.
"""
from __future__ import annotations
import copy
import os
import re
import json
from typing import Any, List, Optional

from services.ir.schema import IRNode, IRTree, validate, IRValidationError


_MODIFY_SYSTEM_PROMPT = """You are a CAD IR editor. You will receive:
1. An existing IR JSON tree representing a 3-D model.
2. A natural-language modification request.

Your task: return a COMPLETE updated IR JSON tree that reflects the requested change.

IR format rules (same as for generation):
- Each node: {"op": "<op>", "params": {...}, "children": [...], "id": "...", "comment": "..."}
- Top-level: {"root": <node>}
- Supported ops: box, cylinder, sphere, cone, union, difference, intersection,
  translate, rotate, scale, mirror, polygon, circle_2d, square_2d,
  linear_extrude, rotate_extrude, linear_pattern, circular_pattern
- Return ONLY the JSON — no markdown, no explanation.

Modification guidelines:
- "두께 변경" / "height change" → update the relevant height param
- "구멍 추가" / "add hole" → wrap with difference(), add cylinder child
- "크기 조절" / "scale" → wrap with scale() or update dimension params
- "위치 조정" / "move" → adjust translate params
- "패턴 추가" / "repeat" → wrap the shape with linear_pattern or circular_pattern
- Preserve unchanged parts of the tree exactly as given
"""


# ── regex fast-path for simple param modifications ────────────────────────────

# Maps Korean/English keywords → IR param names and which op types to update
_PARAM_RULES: list[tuple[re.Pattern, str, list[str]]] = [
    # height / 높이
    (re.compile(r"높이(?:를|을|은|이)?\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
     "height", ["box", "cylinder", "cone", "linear_extrude"]),
    (re.compile(r"height\s*(?:to|=|:)?\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
     "height", ["box", "cylinder", "cone", "linear_extrude"]),

    # radius / 반지름
    (re.compile(r"반지름(?:를|을|은|이)?\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
     "radius", ["cylinder", "sphere", "cone", "circle_2d"]),
    (re.compile(r"radius\s*(?:to|=|:)?\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
     "radius", ["cylinder", "sphere", "cone", "circle_2d"]),

    # width / 너비 / 폭
    (re.compile(r"(?:너비|폭)(?:를|을|은|이)?\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
     "width", ["box", "square_2d"]),
    (re.compile(r"width\s*(?:to|=|:)?\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
     "width", ["box", "square_2d"]),

    # depth / 깊이
    (re.compile(r"깊이(?:를|을|은|이)?\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
     "depth", ["box"]),
    (re.compile(r"depth\s*(?:to|=|:)?\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
     "depth", ["box"]),

    # thickness / 두께
    (re.compile(r"두께(?:를|을|은|이)?\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
     "height", ["box"]),
    (re.compile(r"thickness\s*(?:to|=|:)?\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
     "height", ["box"]),

    # size / 크기 (applies width/depth/height uniformly on box, radius on sphere/cylinder)
    (re.compile(r"크기(?:를|을|은|이)?\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
     "__size__", []),
    (re.compile(r"size\s*(?:to|=|:)?\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
     "__size__", []),

    # count / 개수 / 수량
    (re.compile(r"(?:개수|수량|갯수)(?:를|을|은|이)?\s*(\d+)", re.IGNORECASE),
     "count", ["linear_pattern", "circular_pattern"]),
    (re.compile(r"count\s*(?:to|=|:)?\s*(\d+)", re.IGNORECASE),
     "count", ["linear_pattern", "circular_pattern"]),
]


def _apply_param_to_node(node: IRNode, param: str, value: float, ops: list[str]) -> IRNode:
    """Recursively walk tree; update `param` wherever `node.op in ops`."""
    updated_params = dict(node.params)
    if node.op in ops:
        updated_params[param] = value

    new_children = [_apply_param_to_node(c, param, value, ops) for c in node.children]
    return node.model_copy(update={"params": updated_params, "children": new_children})


def _apply_size_to_node(node: IRNode, value: float) -> IRNode:
    """Special case: 'size' updates width/depth/height for box, radius for sphere/cylinder."""
    updated_params = dict(node.params)
    if node.op == "box":
        updated_params["width"] = value
        updated_params["depth"] = value
        updated_params["height"] = value
    elif node.op in ("sphere",):
        updated_params["radius"] = value
    elif node.op in ("cylinder", "cone"):
        updated_params["radius"] = value
        updated_params["height"] = value

    new_children = [_apply_size_to_node(c, value) for c in node.children]
    return node.model_copy(update={"params": updated_params, "children": new_children})


def _regex_modify(ir: IRTree, text: str) -> Optional[IRTree]:
    """
    Try to apply simple NL modifications without the Claude API.
    Returns a modified IRTree if a rule matched, else None.
    """
    for pattern, param, ops in _PARAM_RULES:
        m = pattern.search(text)
        if not m:
            continue
        value = float(m.group(1))
        if param == "__size__":
            new_root = _apply_size_to_node(ir.root, value)
        else:
            new_root = _apply_param_to_node(ir.root, param, value, ops)

        if new_root == ir.root:
            # nothing actually changed — rule matched text but op not found in tree
            continue

        return ir.model_copy(update={"root": new_root})

    return None


# ── public API ────────────────────────────────────────────────────────────────

async def modify_ir(ir: IRTree, modification_text: str) -> IRTree:
    """Apply a NL modification request to an IRTree, returning a new tree.

    First tries a regex fast-path for simple parameter changes.
    Falls back to Claude API for complex modifications.
    """
    # 1. Try regex fast-path (no API credits needed)
    fast = _regex_modify(ir, modification_text)
    if fast is not None:
        return fast

    # 2. Fall back to Claude API
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "단순 파라미터 수정이 아닌 경우 ANTHROPIC_API_KEY가 필요합니다. "
            "높이/반지름/너비/깊이/두께/크기/개수 변경은 API 없이도 가능합니다."
        )

    try:
        import anthropic

        current_json = ir.to_json()
        user_message = (
            f"Current IR:\n```json\n{current_json}\n```\n\n"
            f"Modification request: {modification_text}"
        )

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            system=_MODIFY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = msg.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        data = json.loads(raw)
        tree = IRTree.model_validate(data)
        validate(tree.root)
        return tree

    except IRValidationError as e:
        raise ValueError(f"수정 후 IR 구조 오류: {e}")
    except json.JSONDecodeError as e:
        raise ValueError(f"AI 수정 응답 파싱 실패: {e}")
    except Exception as e:
        raise ValueError(f"AI 수정 서비스 오류: {e}")


# ── programmatic patch helpers ────────────────────────────────────────────────

def set_param(tree: IRTree, node_id: str, key: str, value: Any) -> IRTree:
    """Return a new tree with `node.params[key] = value` for node matching id."""
    new_root = _set_param_node(tree.root, node_id, key, value)
    return tree.model_copy(update={"root": new_root})


def add_child(tree: IRTree, node_id: str, child: IRNode, index: Optional[int] = None) -> IRTree:
    """Return a new tree with `child` inserted into the children of node_id."""
    new_root = _add_child_node(tree.root, node_id, child, index)
    return tree.model_copy(update={"root": new_root})


def remove_child(tree: IRTree, node_id: str, child_index: int) -> IRTree:
    """Return a new tree with children[child_index] removed from node_id."""
    new_root = _remove_child_node(tree.root, node_id, child_index)
    return tree.model_copy(update={"root": new_root})


# ── internal recursive helpers ────────────────────────────────────────────────

def _set_param_node(node: IRNode, node_id: str, key: str, value: Any) -> IRNode:
    if node.id == node_id:
        new_params = {**node.params, key: value}
        return node.model_copy(update={"params": new_params})
    new_children = [_set_param_node(c, node_id, key, value) for c in node.children]
    return node.model_copy(update={"children": new_children})


def _add_child_node(node: IRNode, node_id: str, child: IRNode, index: Optional[int]) -> IRNode:
    if node.id == node_id:
        children = list(node.children)
        if index is None:
            children.append(child)
        else:
            children.insert(index, child)
        return node.model_copy(update={"children": children})
    new_children = [_add_child_node(c, node_id, child, index) for c in node.children]
    return node.model_copy(update={"children": new_children})


def _remove_child_node(node: IRNode, node_id: str, child_index: int) -> IRNode:
    if node.id == node_id:
        children = list(node.children)
        children.pop(child_index)
        return node.model_copy(update={"children": children})
    new_children = [_remove_child_node(c, node_id, child_index) for c in node.children]
    return node.model_copy(update={"children": new_children})

"""
IR resolver — converts semantic `relation` nodes into concrete geometry.

Call `resolve(tree)` before passing the tree to any CAD generator.

Supported relation types
────────────────────────
on_top_of   children=[base, subject, ...]
            → union(base, translate(z=height(base))(subject), ...)

inside      children=[container, subject, ...]
            → difference(container, subject, ...)

center_of   children=[base, subject]
            → union(base, translate(cx, cy, 0)(subject))
            where cx/cy centres subject on base's XY footprint

next_to     children=[base, subject]
            params: axis="x"|"y"|"z" (default "x"), direction=1|-1 (default 1)
            → union(base, translate(axis * size(base))(subject))

aligned_center  children=[shape1, shape2, ...]
            → union(all shapes), each centred on the max-footprint XY

Partial shapes (hemisphere, quarter-cylinder, …) are NOT new primitives.
They are expressed via boolean/intersection composition — see parser.py for
the builder functions (_hemisphere, etc.).
"""
from __future__ import annotations

from services.ir.schema import IRNode, IRTree


# ── public API ────────────────────────────────────────────────────────────────

def resolve(tree: IRTree) -> IRTree:
    """Walk the tree and replace every relation node with concrete geometry."""
    return tree.model_copy(update={"root": _node(tree.root)})


# ── recursive resolver ────────────────────────────────────────────────────────

def _node(node: IRNode) -> IRNode:
    # Resolve children first (bottom-up)
    resolved_children = [_node(c) for c in node.children]
    node = node.model_copy(update={"children": resolved_children})

    if node.op == "relation":
        return _relation(node)
    return node


def _relation(node: IRNode) -> IRNode:
    rel_type  = node.params.get("type", "on_top_of")
    children  = node.children          # already resolved

    if rel_type == "on_top_of":
        return _on_top_of(children)

    if rel_type == "inside":
        return _inside(children)

    if rel_type == "center_of":
        return _center_of(children)

    if rel_type == "next_to":
        axis      = str(node.params.get("axis", "x"))
        direction = int(node.params.get("direction", 1))
        return _next_to(children, axis, direction)

    if rel_type == "aligned_center":
        return _aligned_center(children)

    # Unknown type: fall back to union (safe)
    return IRNode(op="union", children=children, comment=f"relation({rel_type}) fallback")


# ── relation implementations ──────────────────────────────────────────────────

def _on_top_of(children: list[IRNode]) -> IRNode:
    """Place children[1:] on top of children[0], stacked in Z."""
    base    = children[0]
    subjects = children[1:]
    z_offset = _bbox(base)[2]          # height of base shape

    placed = [
        IRNode(
            op="translate",
            params={"x": 0, "y": 0, "z": round(z_offset, 4)},
            children=[s],
            comment="on_top_of",
        )
        for s in subjects
    ]
    return IRNode(op="union", children=[base] + placed)


def _inside(children: list[IRNode]) -> IRNode:
    """Subtract children[1:] from children[0]."""
    return IRNode(op="difference", children=children)


def _center_of(children: list[IRNode]) -> IRNode:
    """Centre subject on the XY footprint of base."""
    base    = children[0]
    subject = children[1]

    bw, bd, _ = _bbox(base)
    sw, sd, _ = _bbox(subject)

    ox = round((bw - sw) / 2, 4)
    oy = round((bd - sd) / 2, 4)

    placed = IRNode(
        op="translate",
        params={"x": ox, "y": oy, "z": 0},
        children=[subject],
        comment="center_of",
    )
    return IRNode(op="union", children=[base, placed])


def _next_to(children: list[IRNode], axis: str, direction: int) -> IRNode:
    """Place subject directly adjacent to base along `axis`."""
    base    = children[0]
    subject = children[1]

    bw, bd, bh = _bbox(base)
    offset = {"x": 0.0, "y": 0.0, "z": 0.0}

    if axis == "x":
        offset["x"] = round(bw * direction, 4)
    elif axis == "y":
        offset["y"] = round(bd * direction, 4)
    elif axis == "z":
        offset["z"] = round(bh * direction, 4)

    placed = IRNode(
        op="translate",
        params=offset,
        children=[subject],
        comment="next_to",
    )
    return IRNode(op="union", children=[base, placed])


def _aligned_center(children: list[IRNode]) -> IRNode:
    """Union of all children, each nudged so their XY centres align."""
    bboxes  = [_bbox(c) for c in children]
    max_w   = max(b[0] for b in bboxes)
    max_d   = max(b[1] for b in bboxes)

    out = []
    for child, (cw, cd, _) in zip(children, bboxes):
        ox = round((max_w - cw) / 2, 4)
        oy = round((max_d - cd) / 2, 4)
        if ox != 0 or oy != 0:
            out.append(
                IRNode(
                    op="translate",
                    params={"x": ox, "y": oy, "z": 0},
                    children=[child],
                    comment="aligned_center",
                )
            )
        else:
            out.append(child)

    return IRNode(op="union", children=out)


# ── bounding-box estimator ────────────────────────────────────────────────────

def _bbox(node: IRNode) -> tuple[float, float, float]:
    """
    Estimate bounding box (width, depth, height) in mm.
    Values are approximate — good enough for resolver placement math.
    """
    op = node.op

    if op == "box":
        return (node.pf("width", 10), node.pf("depth", 10), node.pf("height", 10))

    if op == "cylinder":
        r = node.pf("radius", 5)
        return (2 * r, 2 * r, node.pf("height", 10))

    if op == "sphere":
        r = node.pf("radius", 5)
        return (2 * r, 2 * r, 2 * r)

    if op == "cone":
        r = max(node.pf("r1", 5), node.pf("r2", 0))
        return (2 * r, 2 * r, node.pf("height", 10))

    if op == "translate":
        if not node.children:
            return (0.0, 0.0, 0.0)
        cw, cd, ch = _bbox(node.children[0])
        # Add absolute Z offset so stacking math stays correct
        z_off = abs(float(node.params.get("z", 0)))
        return (cw, cd, ch + z_off)

    if op == "linear_extrude":
        return (20.0, 20.0, node.pf("height", 10))

    if op == "rotate_extrude":
        if node.children:
            cw, _, ch = _bbox(node.children[0])
            return (cw * 2, cw * 2, ch)
        return (20.0, 20.0, 20.0)

    if op == "linear_pattern":
        if not node.children:
            return (10.0, 10.0, 10.0)
        cw, cd, ch = _bbox(node.children[0])
        spacing = node.p("spacing", [0, 0, 0])
        count   = int(node.p("count", 1))
        dx = float(spacing[0]) if len(spacing) > 0 else 0.0
        dy = float(spacing[1]) if len(spacing) > 1 else 0.0
        dz = float(spacing[2]) if len(spacing) > 2 else 0.0
        return (
            cw + dx * (count - 1),
            cd + dy * (count - 1),
            ch + dz * (count - 1),
        )

    if op == "circular_pattern":
        r = node.pf("radius", 10)
        if node.children:
            _, _, ch = _bbox(node.children[0])
        else:
            ch = 10.0
        return (2 * r, 2 * r, ch)

    if op in ("union", "difference", "intersection"):
        if not node.children:
            return (10.0, 10.0, 10.0)
        # Approximate: use largest child (union) or first child (difference)
        bboxes = [_bbox(c) for c in node.children]
        return (
            max(b[0] for b in bboxes),
            max(b[1] for b in bboxes),
            max(b[2] for b in bboxes),
        )

    if node.children:
        return _bbox(node.children[0])

    return (10.0, 10.0, 10.0)

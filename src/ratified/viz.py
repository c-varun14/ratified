"""Render a compact inline-SVG highlight of one resolved path.

The path is drawn as a bright vertical chain, and the nodes that are *not* on it
(the draft's other revisions, the clause's other threads) are drawn dimmed beside
it, so the resolved edges read at a glance. No client-side graph library, no
layout physics — a fixed two-column strip.
"""
from __future__ import annotations

from html import escape

NODE_H = 30
STEP = 44
TOP = 18
WIDTH = 560
PATH_X = 12
PATH_W = 272
GHOST_X = 304
GHOST_W = 244
MAX_GHOSTS = 6


def _node(x: int, y: int, width: int, kind: str, label: str, css: str) -> str:
    label = escape(str(label))
    if len(label) > 30:
        label = label[:27] + "…"
    baseline = y + NODE_H // 2 + 4
    return (
        f'<g class="node {css}"><rect x="{x}" y="{y}" width="{width}" height="{NODE_H}" rx="6"/>'
        f'<text x="{x + 10}" y="{baseline}"><tspan class="kind">{escape(kind)}</tspan> {label}</text></g>'
    )


MAX_REVISIONS = 3


def _collapse(steps: list[dict]) -> list[dict]:
    """Keep the first and last revisions of a long chain and fold the middle into one node."""
    revisions = [i for i, step in enumerate(steps) if step["kind"] == "revision"]
    if len(revisions) <= MAX_REVISIONS:
        return steps
    first, last = revisions[0], revisions[-1]
    folded = {"kind": "revision", "label": f"… {last - first - 1} more revisions …"}
    return steps[: first + 1] + [folded] + steps[last:]


def path_svg(steps: list[dict], other_revisions: list[str], other_threads: list[str]) -> str:
    steps = _collapse(steps)
    ghosts = [("revision", revision) for revision in other_revisions]
    ghosts += [("thread", thread) for thread in other_threads]
    extra = max(0, len(ghosts) - MAX_GHOSTS)
    ghosts = ghosts[:MAX_GHOSTS]
    if extra:
        ghosts.append(("", f"+{extra} more dimmed"))
    rows = max(len(steps), len(ghosts))
    height = TOP + rows * STEP + 8
    parts = [
        f'<svg class="path-graph" viewBox="0 0 {WIDTH} {height}" role="img" '
        f'aria-label="resolved path, other nodes dimmed" width="100%" preserveAspectRatio="xMidYMin meet">'
    ]
    column = PATH_X + PATH_W // 2
    for index in range(len(steps) - 1):
        y1 = TOP + index * STEP + NODE_H
        y2 = TOP + (index + 1) * STEP
        parts.append(f'<line class="edge" x1="{column}" y1="{y1}" x2="{column}" y2="{y2}"/>')
    for index, step in enumerate(steps):
        parts.append(_node(PATH_X, TOP + index * STEP, PATH_W, step["kind"], step["label"], "on-path"))
    for index, (kind, label) in enumerate(ghosts):
        parts.append(_node(GHOST_X, TOP + index * STEP, GHOST_W, kind, label, "ghost"))
    parts.append("</svg>")
    return "".join(parts)

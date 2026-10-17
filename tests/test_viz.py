from __future__ import annotations

from ratified import viz


def step(kind, label):
    return {"kind": kind, "label": label, "url": f"https://example.org/{label}"}


def test_path_svg_marks_path_nodes_and_dims_the_rest():
    steps = [
        step("thread", "tls:1"),
        step("revision", "draft-x-01"),
        step("section", "5.4 Record Padding"),
    ]
    svg = viz.path_svg(steps, ["draft-x-00", "draft-x-02"], ["tls:9"])
    assert svg.startswith("<svg")
    assert svg.count('class="node on-path"') == 3
    assert svg.count('class="node ghost"') == 3
    assert "5.4 Record Padding" in svg
    assert svg.count('class="edge"') == 2


def test_path_svg_is_empty_safe():
    assert viz.path_svg([], [], []).startswith("<svg")

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


def test_a_long_revision_chain_folds_its_middle():
    steps = [step("message", "m1"), step("thread", "tls:1")]
    steps += [step("revision", f"draft-x-{n:02d}") for n in range(18, 29)]
    steps += [step("rfc", "rfc8446"), step("section", "4.2.10 Early Data Indication")]
    svg = viz.path_svg(steps, [], [])
    assert "draft-x-18" in svg and "draft-x-28" in svg
    assert "draft-x-23" not in svg
    assert "… 9 more revisions …" in svg
    assert svg.count('class="node on-path"') == 7

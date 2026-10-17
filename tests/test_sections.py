from __future__ import annotations

from ratified import sections


def sec(number, title, text=None):
    return {"number": number, "title": title, "text": text if text is not None else f"body of {title}"}


def test_parse_sections_skips_noise_and_toc():
    text = "\n".join(
        [
            "\f",
            "Rescorla                 Standards Track                    [Page 1]",
            "Internet-Draft      TLS 1.3             August 2017",
            "1.  Introduction",
            "   Introduction ....... 3",
            "   The introduction body.",
            "2.  Numbers",
            "   Numbers body.",
            "2.1.  Integers",
            "   Integers body.",
        ]
    )
    parsed = sections.parse_sections(text)
    assert set(parsed) == {"1", "2", "2.1"}
    assert parsed["1"]["title"] == "Introduction"
    assert parsed["2.1"]["text"] == "Integers body."


def test_norm_heading_folds_case_and_punctuation():
    assert sections.norm_heading("Record  Padding, (TLS)") == "record padding tls"


def test_align_prefers_heading_over_moved_number():
    rfc = {
        "3.1": sec("3.1", "Numbers"),
        "3.4": sec("3.4", "Vectors"),
    }
    draft = {"3.1": sec("3.1", "Vectors")}
    align, stats = sections.align_to_rfc(draft, rfc)
    assert align["3.1"]["rfc_number"] == "3.4"
    assert align["3.1"]["how"] == "heading"
    assert stats["aligned"] == 1


def test_align_disambiguates_by_ancestor_path():
    rfc = {
        "3": sec("3", "Overview"),
        "4": sec("4", "Details"),
        "3.1": sec("3.1", "Foo"),
        "4.1": sec("4.1", "Foo"),
    }
    draft = {
        "3": sec("3", "Overview"),
        "4": sec("4", "Details"),
        "4.9": sec("4.9", "Foo"),
    }
    align, stats = sections.align_to_rfc(draft, rfc)
    assert align["4.9"]["rfc_number"] == "4.1"
    assert align["4.9"]["how"] == "heading+path"
    assert stats["ambiguous"] == 0


def test_align_refuses_ambiguous_heading():
    rfc = {"3.1": sec("3.1", "Foo"), "4.1": sec("4.1", "Foo")}
    draft = {"5.1": sec("5.1", "Foo")}
    align, stats = sections.align_to_rfc(draft, rfc)
    assert align == {}
    assert stats["ambiguous"] == 1


def test_align_reports_unmatched_and_changed():
    rfc = {"5.4": sec("5.4", "Record Padding", "MUST NOT exceed 2^14 + 1 octets")}
    draft = {
        "5.4": sec("5.4", "Record Padding", "MUST not exceed 2^14 octets"),
        "1.2": sec("1.2", "Change Log"),
    }
    align, stats = sections.align_to_rfc(draft, rfc)
    assert align["5.4"]["changed"] is True
    assert align["5.4"]["how"] == "heading"
    assert stats["unmatched"] == 1


def test_measured_precision_constants():
    assert sections.ALIGNMENT_METHOD == "heading"
    assert sections.ALIGNMENT_SAMPLE_N == 25
    assert sections.ALIGNMENT_PRECISION == 1.0
    assert sections.ALIGNMENT_HEADING_EQUALITY == 1.0

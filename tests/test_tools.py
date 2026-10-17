from __future__ import annotations

import copy
from datetime import date

from ratified import ingest, routing, tools


def test_aggregate_unresolved_reports_the_hero_clause(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.aggregate_unresolved(graph, "draft-ietf-tls-tls13")
    assert result["outcome"] == "answer"
    assert any("§5.4" in claim["text"] for claim in result["claims"])
    assert any(claim["unresolved"] for claim in result["claims"])
    assert any(chip["kind"] == "section" for chip in result["chips"])
    assert all(chip["url"].startswith("http") for chip in result["chips"])
    assert result["explanation"].startswith("This is the graph saying")


def test_why_clause_traces_discussion_people_and_a_draft_question(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.why_clause(graph, "5.4")
    assert result["outcome"] == "answer"
    assert result["sid"] == "rfc8446#5.4"
    assert result["answer"] == ["Ada Lovelace"]
    assert any("Ada Lovelace cited §5.4 Record Padding" in claim["text"] for claim in result["claims"])
    assert {chip["kind"] for chip in result["claims"][0]["chips"]} == {"message", "thread", "revision"}
    assert [person["name"] for person in result["who_to_ask"]] == ["Ada Lovelace", "ad", "chair"]
    message = result["draft_message"]
    assert message["to"] == ["Ada Lovelace"]
    assert message["subject"] == "Question on RFC 8446 §5.4 Record Padding"
    assert "TLS 1.3 Record Padding removal" in message["body"]
    assert "rfc8446.html#section-5.4" in message["body"]
    assert result["explanation"].startswith("Connected, not caused")


def test_discussed_clauses_lists_only_traceable_clauses(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    assert tools.discussed_clauses(graph) == [{"number": "5.4", "title": "Record Padding", "messages": 1, "people": 1}]


def test_why_clause_resolves_a_heading(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    assert tools.why_clause(graph, heading="Record Padding")["sid"] == "rfc8446#5.4"


def test_why_clause_is_partial_when_nothing_cites_the_clause(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.why_clause(graph, "5.5")
    assert result["outcome"] == "partial"
    assert result["answer"] == []
    assert result["missing"] == ["no message in the graph cites §5.5 Record Payload Protection while its text was still changing"]


def test_why_clause_does_not_know_a_missing_section(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.why_clause(graph, "9.4")
    assert result["outcome"] == "unknown"
    assert result["answer"] is None


def test_clause_receipt_limit_keeps_the_first_path(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    assert len(tools.clause_receipt(graph, "draft-ietf-tls-tls13", "rfc8446#5.4", limit=1)["paths"]) == 1


def test_who_argued_lists_people(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.who_argued(graph, "draft-ietf-tls-tls13")
    assert result["outcome"] == "answer"
    assert {claim["text"].split(" — ")[0] for claim in result["claims"]} == {"Ada Lovelace", "Grace Hopper"}


def test_precedent_traces_message_to_rfc_section(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.precedent(graph, "aaa111")
    assert result["outcome"] == "answer"
    assert any("rfc8446" in claim["text"] for claim in result["claims"])
    assert any(chip["kind"] == "section" for chip in result["chips"])
    assert any(chip["kind"] == "revision" for chip in result["chips"])


def test_precedent_unknown_when_no_path(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.precedent(graph, "no-such-message")
    assert result["outcome"] == "unknown"
    assert result["outcome_message"] == "the graph does not know"


def test_revision_chip_uses_the_canonical_datatracker_path():
    chip = tools.revision_chip("draft-ietf-tls-tls13-21")
    assert chip["url"] == "https://datatracker.ietf.org/doc/draft-ietf-tls-tls13/21/"


def test_revision_chip_falls_back_for_a_non_numeric_suffix():
    chip = tools.revision_chip("draft-ietf-tls-tls13-latest")
    assert chip["url"] == "https://datatracker.ietf.org/doc/draft-ietf-tls-tls13-latest/"


def test_precedent_conflict_when_citation_is_ambiguous(graph, sample_dataset):
    data = copy.deepcopy(sample_dataset)
    data["messages"].append(
        {
            "id": "ccc333",
            "thread_numeric": 1001,
            "message_id": "<c@example.org>",
            "subject": "draft-ietf-tls-tls13-21 padding and protection",
            "date": "2017-08-13",
            "from_display": "Ada Lovelace",
            "from_name": "Ada Lovelace",
            "from_email": "ada@example.org",
            "depth": 2,
            "url": "https://mailarchive.ietf.org/arch/msg/tls/ccc333/",
            "body": "See Section 5.4 and Section 5.5 of draft-ietf-tls-tls13-21.",
        }
    )
    data["sections"]["drafts"]["draft-ietf-tls-tls13-21"]["align"]["5.5"] = {
        "draft_number": "5.5",
        "draft_title": "Record Payload Protection",
        "rfc_number": "5.5",
        "rfc_title": "Record Payload Protection",
        "how": "heading",
        "similarity": 0.9,
        "changed": True,
    }
    ingest.ingest(graph, data)
    result = tools.precedent(graph, "ccc333")
    assert result["outcome"] == "conflict"
    assert result["conflicts"]


def test_what_happened_to_reports_alignment_and_unknown(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    known = tools.what_happened_to(graph, "5.4")
    assert known["outcome"] == "answer"
    assert any("changed" in claim["text"] for claim in known["claims"])
    assert any(chip["kind"] == "rfc" for chip in known["chips"])

    unknown = tools.what_happened_to(graph, "99.9")
    assert unknown["outcome"] == "unknown"


def test_routing_maps_questions_to_the_catalogue():
    assert routing.route("which clauses were argued against and never resolved")[0] == "aggregate_unresolved"
    assert routing.route("who argued about draft-ietf-tls-tls13-21")[0] == "who_argued"
    assert routing.route("what happened to section 5.4") == ("what_happened_to", {"number": "5.4"})
    assert routing.route("is the graph up to date")[0] == "sync"
    assert routing.route("trace the precedent for message abcdefghijklmnop")[0] == "precedent"
    assert routing.route("anything at all") == ("not_understood", {})
    assert routing.route("why is the sky blue") == ("why_clause", {"topic": "why is the sky blue", "draft": "draft-ietf-tls-tls13"})


def test_why_clause_resolves_a_plain_words_topic_through_the_full_text_index(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.why_clause(graph, topic="how come record padding works like this")
    assert result["sid"] == "rfc8446#5.4"
    assert result["resolved"]["matches"][0]["number"] == "5.4"
    missing = tools.why_clause(graph, topic="why is the sky blue")
    assert missing["outcome"] == "unknown"
    assert missing["answer"] is None


def test_search_discussion_expands_hits_to_cited_clauses(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.search_discussion(graph, "what did people say about padding leaks?")
    assert result["answer"][0] == "aaa111"
    assert any("§5.4 Record Padding" in note for note in result["notes"])
    assert tools.search_discussion(graph, "quantum teleportation")["outcome"] == "unknown"


def test_who_knows_ranks_people_by_pagerank(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.who_knows(graph)
    assert set(result["answer"]) == {"Ada Lovelace", "Grace Hopper"}
    assert "algo.pageRank" in result["notes"][0]


def test_not_understood_says_what_can_be_asked():
    result = tools.run(None, "not_understood")
    assert result["outcome"] == "unknown"
    assert result["answer"] is None
    assert any("why a section of RFC 8446" in note for note in result["notes"])
    assert routing.route("who argued about draft-ietf-tls-tls13-28")[1] == {"draft": "draft-ietf-tls-tls13"}


def test_aggregate_claims_carry_a_clause_id_for_the_receipt(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.aggregate_unresolved(graph, "draft-ietf-tls-tls13")
    assert result["claims"]
    assert all(claim["sid"].startswith("rfc8446#") for claim in result["claims"])
    assert all(claim["draft"] == "draft-ietf-tls-tls13" for claim in result["claims"])


def test_aggregate_labels_topic_links_as_leads(graph, sample_dataset):
    data = copy.deepcopy(sample_dataset)
    data["sections"]["drafts"]["draft-ietf-tls-tls13-21"]["align"]["5.5"] = {
        "draft_number": "5.5",
        "draft_title": "Record Payload Protection",
        "rfc_number": "5.5",
        "rfc_title": "Record Payload Protection",
        "how": "heading",
        "similarity": 0.9,
        "changed": True,
    }
    ingest.ingest(graph, data)
    result = tools.aggregate_unresolved(graph, "draft-ietf-tls-tls13")
    buckets: dict[str, list] = {}
    for claim in result["claims"]:
        buckets.setdefault(claim["bucket"], []).append(claim)
    assert any("§5.4" in claim["text"] for claim in buckets["cited"])
    assert any("§5.5" in claim["text"] for claim in buckets["topic"])
    assert result["notes"] and "measured" in result["notes"][0]


def test_clause_receipt_traces_object_thread_revisions_to_section(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    receipt = tools.clause_receipt(graph, "draft-ietf-tls-tls13", "rfc8446#5.4")
    assert receipt["paths"]
    steps = receipt["paths"][0]["steps"]
    kinds = [step["kind"] for step in steps]
    assert kinds[0] == "message"
    assert kinds[1] == "thread"
    assert "revision" in kinds
    assert kinds[-2] == "rfc" and kinds[-1] == "section"
    assert all(step["url"].startswith("http") for step in steps)
    assert receipt["paths"][0]["svg"].startswith("<svg")
    assert 'class="node on-path"' in receipt["paths"][0]["svg"]


def test_clause_receipt_empty_for_unknown_clause(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    assert tools.clause_receipt(graph, "draft-ietf-tls-tls13", "rfc8446#99.9")["paths"] == []


def _browse_row(msg_id, thread_numeric, subject, sender, when):
    return (
        '<div class="xtr">'
        f'<div class="xtd thread-col">{thread_numeric}</div>'
        '<div class="xtd id-col">9999</div>'
        f'<div class="xtd subj-col"><a href="/arch/msg/tls/{msg_id}/">{subject}</a></div>'
        f'<div class="xtd from-col">{sender}</div>'
        f'<div class="xtd date-col">{when}</div>'
        f'<a href="/arch/msg/tls/{msg_id}/">x</a><span class="depth-1"></span>'
        "</div>"
    )


NEW_BODY = (
    b"From: New Person <new@example.org>\r\n"
    b"Subject: Re: draft-ietf-tls-tls13-21 Section 5.5\r\n"
    b"Date: Sat, 17 Oct 2026 10:00:00 +0000\r\n"
    b"Message-ID: <ddd@example.org>\r\n"
    b"Content-Type: text/plain\r\n\r\n"
    b"About Section 5.5 of draft-ietf-tls-tls13-21.\r\n"
)


class _FakeFetcher:
    offline = False

    def __init__(self, page, body=b""):
        self.page = page.encode()
        self.body = body

    def get(self, url, use_cache=True):
        return self.body if url.endswith("download/") else self.page

    def cache_age(self, url):
        return 0.0


class _OfflineFetcher:
    offline = True

    def get(self, url, use_cache=True):
        raise RuntimeError("offline: not cached")

    def cache_age(self, url):
        return None


class _RateLimitedFetcher:
    offline = False

    def get(self, url, use_cache=True):
        raise RuntimeError("HTTP 429")

    def cache_age(self, url):
        return None


def _with_55_changed(sample_dataset):
    data = copy.deepcopy(sample_dataset)
    data["sections"]["drafts"]["draft-ietf-tls-tls13-21"]["align"]["5.5"] = {
        "draft_number": "5.5",
        "draft_title": "Record Payload Protection",
        "rfc_number": "5.5",
        "rfc_title": "Record Payload Protection",
        "how": "heading",
        "similarity": 0.9,
        "changed": True,
    }
    return data


def test_sync_appends_new_messages_and_reports_aggregate_change(graph, sample_dataset):
    data = _with_55_changed(sample_dataset)
    ingest.ingest(graph, data)
    page = _browse_row("ddd444", 1001, "draft-ietf-tls-tls13-21 Section 5.5", "New Person", date.today().isoformat())
    result = tools.sync(graph, days=1, fetcher=_FakeFetcher(page, NEW_BODY), sections=data["sections"])
    assert result["deferred"] is False
    assert result["n_changed"] == 1
    assert "New Person" in result["new_people"]
    assert result["aggregate_changed"] is True
    assert result["aggregate"]["title"].startswith("2 clauses")
    assert graph.query("MATCH (m:Message {id:'ddd444'}) RETURN count(m)").result_set[0][0] == 1


def test_sync_reports_unchanged_when_nothing_is_new(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    page = _browse_row("aaa111", 1001, "draft-ietf-tls-tls13-21 padding", "Ada Lovelace", date.today().isoformat())
    result = tools.sync(graph, days=1, fetcher=_FakeFetcher(page), sections=sample_dataset["sections"])
    assert result["n_changed"] == 0
    assert result["aggregate_changed"] is False
    assert result["title"] == "sync — 0 changed / 0 new people"


def test_sync_defers_offline(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.sync(graph, days=1, fetcher=_OfflineFetcher())
    assert result["deferred"] is True
    assert result["reason"] == "offline"
    assert result["title"] == "sync deferred (offline), graph unchanged"


def test_sync_defers_on_rate_limit_without_a_usable_cache(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.sync(graph, days=1, fetcher=_RateLimitedFetcher())
    assert result["deferred"] is True
    assert result["reason"] == "rate limit"
    assert result["title"] == "sync deferred (rate limit), graph unchanged"


def test_section_by_heading_returns_the_number(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.section_by_heading(graph, "draft-ietf-tls-tls13", "Record Padding")
    assert result["outcome"] == "answer"
    assert result["answer"] == "5.4"
    assert result["title"] == "§5.4 — Record Padding"
    assert any(chip["kind"] == "section" for chip in result["chips"])
    assert all(chip["url"].startswith("http") for chip in result["chips"])


def test_section_by_heading_is_unknown_for_an_absent_heading(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.section_by_heading(graph, "draft-ietf-tls-tls13", "No Such Heading")
    assert result["outcome"] == "unknown"
    assert result["outcome_message"] == "the graph does not know"
    assert result["answer"] is None


def test_revisions_lists_ranges_latest_and_count(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    ids = ["draft-ietf-tls-tls13-20", "draft-ietf-tls-tls13-21"]
    listed = tools.revisions(graph, "draft-ietf-tls-tls13")
    assert listed["answer"] == ids
    assert listed["count"] == 2 and listed["latest"] == ids[-1]
    assert all(chip["kind"] == "revision" for chip in listed["chips"])
    assert tools.revisions(graph, "draft-ietf-tls-tls13", lo=21, hi=21)["answer"] == [ids[-1]]
    assert tools.revisions(graph, "draft-ietf-tls-tls13", latest=True)["answer"] == ids[-1]
    assert tools.revisions(graph, "draft-ietf-tls-tls13", count=True)["answer"] == 2


def test_revisions_unknown_for_an_absent_draft(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    assert tools.revisions(graph, "draft-ietf-tls-nope")["outcome"] == "unknown"


def test_count_unresolved_counts_cited_clauses_only(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.count_unresolved(graph, "draft-ietf-tls-tls13")
    assert result["outcome"] == "answer"
    assert result["answer"] == 1 and result["count"] == 1
    assert any("§5.4" in claim["text"] for claim in result["claims"])
    assert any(chip["kind"] == "section" for chip in result["chips"])


def test_chairs_lists_the_chairs_and_area_directors(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.chairs(graph, "tls")
    assert result["outcome"] == "answer"
    assert result["answer"] == ["chair"]
    assert result["area_directors"] == ["ad"]
    assert tools.chairs(graph, "no-such-wg")["outcome"] == "unknown"


def test_became_rfc_reads_the_became_edge(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.became_rfc(graph, "draft-ietf-tls-tls13")
    assert result["outcome"] == "answer"
    assert result["answer"] == "rfc8446"
    assert any(chip["kind"] == "rfc" for chip in result["chips"])
    assert tools.became_rfc(graph, "draft-ietf-tls-nope")["outcome"] == "unknown"


def test_threads_by_subject_matches_a_message_subject(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.threads_by_subject(graph, "draft-ietf-tls-tls13-21")
    assert result["outcome"] == "answer"
    assert result["answer"] == ["tls:1001"]
    assert any(chip["kind"] == "thread" for chip in result["chips"])
    assert tools.threads_by_subject(graph, "nothing-matches-this")["outcome"] == "unknown"


def test_count_became_counts_the_matching_family(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    assert tools.count_became(graph, "draft-ietf-tls-")["answer"] == 1
    assert tools.count_became(graph, "draft-ietf-tls-tls13")["answer"] == 1
    assert tools.count_became(graph, "draft-ietf-tls-nope")["outcome"] == "unknown"


def test_count_thread_messages_counts_the_thread(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.count_thread_messages(graph, "tls:1001")
    assert result["outcome"] == "answer"
    assert result["answer"] == 2
    assert any(chip["kind"] == "thread" for chip in result["chips"])
    assert tools.count_thread_messages(graph, "tls:9999")["outcome"] == "unknown"

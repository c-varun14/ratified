from __future__ import annotations

import urllib.error

import pytest

from ratified import mail
from ratified.fetch import Fetcher

RECORDED_429 = {"status": 429, "error_code": 1015, "retry_after": "131"}
URL = "https://mailarchive.ietf.org/arch/browse/tls/?page=1"


def http_error(url, code, headers=None):
    return urllib.error.HTTPError(url, code, "error", headers or {}, None)


def test_honors_recorded_429_retry_after(tmp_path):
    calls = []
    sleeps = []

    def opener(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise http_error(request.full_url, 429, {"Retry-After": RECORDED_429["retry_after"]})
        return b"ok", "text/plain", 200

    fetcher = Fetcher(cache_dir=str(tmp_path), opener=opener, sleep=sleeps.append, min_interval=0.0)
    assert fetcher.get(URL) == b"ok"
    assert len(calls) == 2
    assert sleeps[0] >= float(RECORDED_429["retry_after"])
    assert fetcher.stats["rate_limited_429"] == 1
    assert fetcher.stats["retries"] == 1
    assert fetcher.min_interval == 2.0


def test_cache_hit_avoids_network(tmp_path):
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        return b"body", "text/plain", 200

    fetcher = Fetcher(cache_dir=str(tmp_path), opener=opener, sleep=lambda _: None, min_interval=0.0)
    assert fetcher.get(URL) == b"body"
    assert fetcher.get(URL) == b"body"
    assert len(calls) == 1
    assert fetcher.stats["cache_hits"] == 1


def test_retries_transient_http_error(tmp_path):
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise http_error(request.full_url, 503)
        return b"recovered", "text/plain", 200

    fetcher = Fetcher(
        cache_dir=str(tmp_path), opener=opener, sleep=lambda _: None, min_interval=0.0, base_delay=0.0
    )
    assert fetcher.get(URL) == b"recovered"
    assert len(calls) == 2


def test_offline_miss_raises_and_hit_replays(tmp_path):
    fetcher = Fetcher(
        cache_dir=str(tmp_path), opener=lambda r, t: (b"cached", "text/plain", 200),
        sleep=lambda _: None, min_interval=0.0,
    )
    fetcher.get(URL)

    offline = Fetcher(cache_dir=str(tmp_path), offline=True, opener=lambda r, t: (_ for _ in ()).throw(AssertionError))
    assert offline.get(URL) == b"cached"

    miss = Fetcher(cache_dir=str(tmp_path), offline=True)
    with pytest.raises(RuntimeError, match="offline"):
        miss.get("https://mailarchive.ietf.org/arch/browse/tls/?page=99")


BROWSE_ROW = (
    '<div class="xtr">'
    '<div class="xtd thread-col">1001</div>'
    '<div class="xtd id-col">2045</div>'
    '<div class="xtd subj-col"><a href="/arch/msg/tls/abc/">draft-ietf-tls-tls13-21 padding</a></div>'
    '<div class="xtd from-col">Ada Lovelace</div>'
    '<div class="xtd date-col">2017-08-11</div>'
    '<a href="/arch/msg/tls/abc/">x</a><span class="depth-1"></span>'
    "</div>"
)


def test_parse_rows_reads_browse_html():
    rows = mail.parse_rows(BROWSE_ROW, "tls")
    assert len(rows) == 1
    assert rows[0]["id"] == "abc"
    assert rows[0]["thread_numeric"] == 1001
    assert rows[0]["subject"] == "draft-ietf-tls-tls13-21 padding"
    assert rows[0]["from_display"] == "Ada Lovelace"
    assert rows[0]["depth"] == 1
    assert rows[0]["url"] == "https://mailarchive.ietf.org/arch/msg/tls/abc/"


def test_parse_body_extracts_draft_refs():
    raw = (
        b"From: Ada Lovelace <ada@example.org>\r\n"
        b"Subject: Re: draft-ietf-tls-tls13-21\r\n"
        b"Date: Fri, 11 Aug 2017 10:00:00 +0000\r\n"
        b"Message-ID: <msg-1@example.org>\r\n"
        b"Content-Type: text/plain\r\n\r\n"
        b"About that padding clause.\r\n"
    )
    parsed = mail.parse_body(raw)
    assert parsed["from_email"] == "ada@example.org"
    assert "draft-ietf-tls-tls13-21" in parsed["draft_refs"]
    assert parsed["body"].startswith("About that padding clause.")

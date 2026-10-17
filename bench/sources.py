"""Read the raw primary records behind the corpus, without touching the product.

Everything here parses the bytes that were actually served by the authoritative
sources — the RFC Editor, the IETF datatracker API, the mailarchive browse pages
and per-message downloads — out of the cache-first HTTP store. It does not import
`ratified.ingest`, `ratified.sections` or `ratified.tools`, and it never opens
FalkorDB, so a key derived here is a statement about the primary record rather
than a restatement of what the graph already believes.

Each parser is a second, independent implementation of the same read the product
performs; agreement between the two is the thing the bench measures.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "cache" / "http"

RFC = "rfc8446"
RFC_TXT_URL = f"https://www.rfc-editor.org/rfc/{RFC}.txt"
DRAFT = "draft-ietf-tls-tls13"
LIST = "tls"
DRAFT_URL = "https://www.ietf.org/archive/id/{name}.txt"
BASE = "https://datatracker.ietf.org"
ARCHIVE = "https://mailarchive.ietf.org"

HEAD_RE = re.compile(r"^(\d+(?:\.\d+)*)\.\s+(\S.*)$")
NOISE_RE = re.compile(
    r"^(?:\S+\s+Standards Track.*|Internet-Draft.*|RFC \d+.*|.*\[Page \d+\].*|\f?)$"
)
TOC_RE = re.compile(r"\.{3,}\s*\d+\s*$")
REV_RE = re.compile(r"(draft-[a-z0-9-]+?)-(\d{2})(?![a-z0-9-])")
SECTION_RE = re.compile(r"\b[Ss]ection\s+(\d+(?:\.\d+)*)")


def cached(url: str) -> bytes | None:
    """The cached response body for a URL, or None when it was never fetched."""
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    path = CACHE_DIR / f"{key}.body"
    return path.read_bytes() if path.exists() else None


def cached_json(url: str):
    body = cached(url)
    return json.loads(body.decode("utf-8")) if body else None


def cached_urls() -> list[str]:
    """Every URL present in the HTTP cache, from its metadata sidecar."""
    urls = []
    for meta in CACHE_DIR.glob("*.meta.json"):
        try:
            urls.append(json.loads(meta.read_text()).get("url") or "")
        except (ValueError, OSError):
            continue
    return sorted(u for u in urls if u)


def clean_text(text: str) -> str:
    return "\n".join(
        line.rstrip()
        for line in text.splitlines()
        if not NOISE_RE.match(line) and not TOC_RE.search(line)
    )


def sections(text: str) -> dict[str, dict]:
    """Number -> {title, body} for every numbered heading in an IETF text file."""
    lines = clean_text(text).splitlines()
    heads = [
        (index, match.group(1), match.group(2).strip())
        for index, match in ((i, HEAD_RE.match(line)) for i, line in enumerate(lines))
        if match
    ]
    out: dict[str, dict] = {}
    for position, (start, number, title) in enumerate(heads):
        end = heads[position + 1][0] if position + 1 < len(heads) else len(lines)
        body = "\n".join(lines[start + 1 : end]).strip()
        if number not in out:
            out[number] = {"title": title, "body": body}
    return out


def rfc_sections() -> dict[str, dict]:
    body = cached(RFC_TXT_URL)
    if body is None:
        raise FileNotFoundError(f"not cached: {RFC_TXT_URL}")
    return sections(body.decode("utf-8", "replace"))


def draft_sections(revision: str) -> dict[str, dict]:
    body = cached(DRAFT_URL.format(name=revision))
    if body is None:
        raise FileNotFoundError(f"not cached: {revision}")
    return sections(body.decode("utf-8", "replace"))


def _col(chunk: str, klass: str) -> str:
    match = re.search(r'<div class="xtd ' + klass + r'[^"]*">(.*?)</div>', chunk, re.S)
    return re.sub(r"<[^>]+>", "", match.group(1)).strip() if match else ""


def _unescape(text: str) -> str:
    import html

    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def browse_rows(list_name: str = LIST) -> list[dict]:
    """Every message row across the cached mailarchive browse pages.

    The product enumerates threads from the same pages; this is a second reader of
    the same HTML, keyed off the row markup rather than the product's parser.
    """
    rows: list[dict] = []
    seen: set[str] = set()
    link_re = re.compile(r'href="/arch/msg/' + re.escape(list_name) + r'/([^"/]+)/"')
    for url in cached_urls():
        if f"/arch/browse/{list_name}/" not in url:
            continue
        page = cached(url)
        if page is None:
            continue
        for chunk in re.split(r'<div class="xtr">', page.decode("utf-8", "replace"))[1:]:
            link = link_re.search(chunk)
            if not link or link.group(1) in seen:
                continue
            seen.add(link.group(1))
            subject_html = _col(chunk, "subj-col")
            anchor = re.search(r"<a[^>]*>(.*?)</a>", subject_html, re.S)
            thread = _col(chunk, "thread-col")
            rows.append(
                {
                    "id": link.group(1),
                    "thread": f"{list_name}:{thread}",
                    "subject": _unescape(anchor.group(1) if anchor else subject_html),
                    "from": _unescape(_col(chunk, "from-col")),
                    "date": _unescape(_col(chunk, "date-col")),
                    "url": f"{ARCHIVE}/arch/msg/{list_name}/{link.group(1)}/",
                }
            )
    return rows


def message_downloads(list_name: str = LIST) -> dict[str, str]:
    """Message id -> raw downloaded message text, for every cached download."""
    out: dict[str, str] = {}
    for url in cached_urls():
        marker = f"/arch/msg/{list_name}/"
        if marker not in url or not url.endswith("/download/"):
            continue
        body = cached(url)
        if body is not None:
            out[url.split(marker)[1].split("/")[0]] = body.decode("utf-8", "replace")
    return out


def dochistory(name: str = DRAFT) -> list[dict]:
    """Every revision record the datatracker lists for one draft name."""
    for url in cached_urls():
        if "/api/v1/doc/dochistory/" not in url:
            continue
        page = cached_json(url)
        if not page:
            continue
        objects = [o for o in page.get("objects", []) if o.get("name") == name]
        if objects:
            return objects
    return []


def revisions(name: str = DRAFT) -> list[str]:
    """Revision labels (e.g. '00' .. '28') for a draft, ascending."""
    return sorted(
        {o["rev"] for o in dochistory(name) if o.get("rev")},
        key=lambda rev: (len(rev), rev),
    )


def became_rfc(prefix: str = "draft-ietf-tls-") -> dict[str, str]:
    """Draft name -> RFC name, from the datatracker became_rfc relationship."""
    mapping: dict[str, str] = {}
    for url in cached_urls():
        if "/api/v1/doc/relateddocument/" not in url or "became_rfc" not in url:
            continue
        page = cached_json(url)
        if not page:
            continue
        for obj in page.get("objects", []):
            source = obj["source"].strip("/").split("/")[-1]
            target = obj["target"].strip("/").split("/")[-1]
            if source.startswith(prefix):
                mapping.setdefault(source, target)
    return mapping


def roles(role: str, list_name: str = LIST) -> list[dict]:
    """The people holding one datatracker role for the group (chair / ad)."""
    for url in cached_urls():
        if "/api/v1/group/role/" not in url or f"name={role}" not in url:
            continue
        page = cached_json(url)
        if not page:
            continue
        people = []
        for obj in page.get("objects", []):
            email = (obj.get("email") or "").strip("/").split("/")[-1]
            person = (obj.get("person") or "").strip("/").split("/")[-1]
            record = cached_json(f"{BASE}/api/v1/person/person/{person}/?format=json") if person else None
            if email:
                people.append({"name": (record or {}).get("name") or email.split("@")[0], "email": email})
        if people:
            return people
    return []


def draft_revisions_named(text: str, prefix: str = DRAFT) -> set[str]:
    """Draft revision ids named in a body of text, as the product's regex reads them."""
    return {f"{m.group(1)}-{m.group(2)}" for m in REV_RE.finditer(text) if m.group(1).startswith(prefix)}


def sections_named(text: str) -> set[str]:
    """Section numbers named as 'Section N' in a body of text."""
    return set(SECTION_RE.findall(text))

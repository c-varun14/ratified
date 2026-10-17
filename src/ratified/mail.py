"""Pull one Working Group's mailing-list record from mailarchive.

Cloudflare rate-limits the archive under burst load, so threads are enumerated from
the paginated /arch/browse/<list>/ rows (40 messages per request, each row already
carrying its thread id) and raw message bodies are downloaded only for a selected
subset. Everything goes through the shared cache-first Fetcher.
"""
from __future__ import annotations

import email
import email.policy
import email.utils
import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

from .paths import DATA_DIR

BASE = "https://mailarchive.ietf.org"
ROW_SPLIT = re.compile(r'<div class="xtr">')
DEPTH_RE = re.compile(r"depth-(\d+)")
DRAFT_SUBJ_RE = re.compile(r"draft-|rfc\s?\d{3,4}|tls 1\.3|tls13", re.I)
DRAFT_RE = re.compile(r"draft-[a-z0-9-]+-\d{2}|\brfc\s?\d{3,5}\b", re.I)


def parse_rows(page_html: str, list_name: str) -> list[dict]:
    rows = []
    link_re = re.compile(r'href="/arch/msg/' + re.escape(list_name) + r'/([^"/]+)/"')
    for chunk in ROW_SPLIT.split(page_html)[1:]:
        link = link_re.search(chunk)
        if not link:
            continue
        thread = _col(chunk, "thread-col")
        number = _col(chunk, "id-col")
        subject_html = _col(chunk, "subj-col")
        subject = ""
        if subject_html:
            anchor = re.search(r"<a[^>]*>(.*?)</a>", subject_html, re.S)
            subject = html.unescape(re.sub(r"<[^>]+>", "", anchor.group(1) if anchor else subject_html)).strip()
        depth = DEPTH_RE.search(chunk)
        rows.append(
            {
                "id": link.group(1),
                "numeric_id": int(number) if number.isdigit() else None,
                "thread_numeric": int(thread) if thread.isdigit() else None,
                "subject": subject,
                "from_display": html.unescape(_col(chunk, "from-col")),
                "date": html.unescape(_col(chunk, "date-col")),
                "depth": int(depth.group(1)) if depth else 0,
                "url": f"{BASE}/arch/msg/{list_name}/{link.group(1)}/",
            }
        )
    return rows


def parse_body(raw: bytes) -> dict:
    try:
        message = email.message_from_bytes(raw, policy=email.policy.default)
    except Exception:  # noqa: BLE001
        return {}
    references = [r.strip().strip("<>") for r in (message.get("References") or "").split()]
    try:
        parsed = email.utils.parsedate_to_datetime(message.get("Date"))
        date_iso = parsed.isoformat() if parsed else None
    except (TypeError, ValueError):
        date_iso = None
    text = _body_text(message)
    display, address = email.utils.parseaddr(message.get("From") or "")
    return {
        "message_id": (message.get("Message-ID") or "").strip().strip("<>") or None,
        "in_reply_to": (message.get("In-Reply-To") or "").strip().strip("<>") or None,
        "references": [r for r in references if r],
        "date_header": date_iso,
        "from_name": display,
        "from_email": (address or "").lower(),
        "body": text,
        "draft_refs": sorted(
            {m.group(0).lower() for m in DRAFT_RE.finditer((message.get("Subject") or "") + "\n" + text)}
        ),
    }


def pull(
    fetcher,
    list_name: str,
    data_dir: str = DATA_DIR,
    *,
    query: str = "",
    target_threads: int = 200,
    max_pages: int = 45,
    workers: int = 1,
    body_mode: str = "draft_subjects",
    body_cap: int = 700,
    body_threads: set[int] | None = None,
) -> dict:
    rows: list[dict] = []
    seen: set[str] = set()
    pages_ok = 0
    for page in range(1, max_pages + 1):
        suffix = f"?q={quote(query)}&page={page}" if query else f"?page={page}"
        page_html = fetcher.get(f"{BASE}/arch/browse/{list_name}/{suffix}").decode("utf-8", "replace")
        pages_ok += 1
        new = [row for row in parse_rows(page_html, list_name) if row["id"] not in seen]
        if not new:
            break
        seen.update(row["id"] for row in new)
        rows.extend(new)
        if not query and len({r["thread_numeric"] for r in rows}) >= target_threads:
            break
        if query and len(new) < 40:
            break

    by_thread: dict[int, list[dict]] = {}
    for row in rows:
        by_thread.setdefault(row["thread_numeric"], []).append(row)

    targets = _body_targets(rows, body_mode, body_threads or set())[:body_cap]
    bodies: dict[str, dict] = {}
    errors: list[str] = []
    if targets:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetcher.get, row["url"] + "download/"): row["id"] for row in targets}
            for future in as_completed(futures):
                try:
                    bodies[futures[future]] = parse_body(future.result())
                except RuntimeError:
                    errors.append(futures[future])

    messages = []
    for row in rows:
        merged = dict(row)
        merged.update(
            {k: bodies.get(row["id"], {}).get(k) for k in
             ("message_id", "in_reply_to", "references", "from_name", "from_email", "body", "draft_refs")}
        )
        merged.setdefault("draft_refs", [])
        messages.append(merged)

    threads = []
    for number, thread_rows in by_thread.items():
        ordered = sorted(thread_rows, key=lambda r: r.get("date") or "")
        root = ordered[0]
        threads.append(
            {
                "thread_numeric": number,
                "thread_id": root["id"],
                "url": root["url"],
                "subject": root["subject"],
                "n_messages": len(thread_rows),
                "first_date": ordered[0].get("date"),
                "last_date": ordered[-1].get("date"),
                "message_ids": [r["id"] for r in ordered],
                "participants": sorted({r["from_display"] for r in thread_rows if r.get("from_display")}),
                "draft_refs": sorted({d for r in thread_rows for d in (r.get("draft_refs") or [])}),
            }
        )
    threads.sort(key=lambda t: t["last_date"] or "", reverse=True)

    mail_dir = Path(data_dir) / "mail"
    mail_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug(query)
    (mail_dir / f"{list_name}{slug}_messages.json").write_text(json.dumps(messages))
    (mail_dir / f"{list_name}{slug}_threads.json").write_text(json.dumps(threads))
    return {
        "list": list_name,
        "pages": pages_ok,
        "messages": len(messages),
        "threads": len(threads),
        "bodies_downloaded": len(bodies),
        "body_failures": len(errors),
    }


def _body_targets(rows: list[dict], body_mode: str, body_threads: set[int]) -> list[dict]:
    if body_mode == "all":
        return list(rows)
    if body_mode == "threads":
        return [row for row in rows if row["thread_numeric"] in body_threads]
    if body_mode == "draft_subjects":
        return [row for row in rows if DRAFT_SUBJ_RE.search(row["subject"])]
    return []


def _body_text(message) -> str:
    try:
        part = message.get_body(preferencelist=("plain",))
        text = part.get_content() if part else ""
    except Exception:  # noqa: BLE001
        text = ""
    if not text:
        try:
            part = message.get_body(preferencelist=("html",))
            text = re.sub(r"<[^>]+>", " ", part.get_content()) if part else ""
        except Exception:  # noqa: BLE001
            text = ""
    return re.sub(r"\n{3,}", "\n\n", (text or "")).strip()


def _col(chunk: str, klass: str) -> str:
    match = re.search(r'<div class="xtd ' + klass + r'[^"]*">(.*?)</div>', chunk, re.S)
    return re.sub(r"<[^>]+>", "", match.group(1)).strip() if match else ""


def _slug(query: str) -> str:
    return "_q_" + re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:40] if query else ""


def main() -> None:
    import argparse

    from .fetch import Fetcher

    parser = argparse.ArgumentParser(description="Pull a Working Group's mailing-list record.")
    parser.add_argument("--list", default=os.environ.get("RATIFIED_LIST", "tls"))
    parser.add_argument("--query", default=os.environ.get("RATIFIED_QUERY", ""))
    parser.add_argument("--target-threads", type=int, default=200)
    parser.add_argument("--max-pages", type=int, default=45)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--body-mode", default="draft_subjects", choices=["none", "draft_subjects", "all", "threads"])
    parser.add_argument("--body-cap", type=int, default=700)
    parser.add_argument("--body-threads", default="")
    parser.add_argument("--min-interval", type=float, default=2.5)
    args = parser.parse_args()
    fetcher = Fetcher(min_interval=args.min_interval)
    summary = pull(
        fetcher,
        args.list,
        query=args.query,
        target_threads=args.target_threads,
        max_pages=args.max_pages,
        workers=args.workers,
        body_mode=args.body_mode,
        body_cap=args.body_cap,
        body_threads={int(x) for x in args.body_threads.split(",") if x.strip()},
    )
    fetcher.save_stats()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

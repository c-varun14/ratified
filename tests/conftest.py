from __future__ import annotations

import os
import uuid

import pytest
from falkordb import FalkorDB


@pytest.fixture(scope="session")
def falkor():
    host = os.environ.get("RATIFIED_FALKOR_HOST", "127.0.0.1")
    port = int(os.environ.get("RATIFIED_FALKOR_PORT", "6379"))
    try:
        db = FalkorDB(host=host, port=port)
        db.select_graph("__schema_ping__").query("RETURN 1")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"FalkorDB unreachable at {host}:{port}: {exc}")
    return db


@pytest.fixture
def graph(falkor):
    g = falkor.select_graph(f"ratified_test_{uuid.uuid4().hex[:10]}")
    yield g
    try:
        g.delete()
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture
def sample_dataset():
    return {
        "messages": [
            {
                "id": "aaa111",
                "thread_numeric": 1001,
                "message_id": "<a@example.org>",
                "subject": "draft-ietf-tls-tls13-21: TLS 1.3 Record Padding removal",
                "date": "2017-08-11",
                "from_display": "Ada Lovelace",
                "from_name": "Ada Lovelace",
                "from_email": "ada@example.org",
                "depth": 0,
                "url": "https://mailarchive.ietf.org/arch/msg/tls/aaa111/",
                "body": "Removing the padding leaks record sizes. See Section 5.4 of draft-ietf-tls-tls13-21.",
            },
            {
                "id": "bbb222",
                "thread_numeric": 1001,
                "message_id": "<b@example.org>",
                "subject": "Re: draft-ietf-tls-tls13-21: TLS 1.3 Record Padding removal",
                "date": "2017-08-12",
                "from_display": "Grace Hopper",
                "from_name": "",
                "from_email": "",
                "depth": 1,
                "url": "https://mailarchive.ietf.org/arch/msg/tls/bbb222/",
                "body": "",
            },
        ],
        "threads": [
            {
                "thread_numeric": 1001,
                "url": "https://mailarchive.ietf.org/arch/msg/tls/aaa111/",
                "subject": "TLS 1.3 Record Padding removal",
                "n_messages": 2,
                "first_date": "2017-08-11",
                "last_date": "2017-08-12",
            }
        ],
        "docs": {
            "group": {"acronym": "tls", "name": "Transport Layer Security", "list_email": "tls@ietf.org"},
            "chairs": [{"email": "chair@example.org"}],
            "ads": [{"email": "ad@example.org"}],
            "drafts": [
                {
                    "name": "draft-ietf-tls-tls13",
                    "title": "The Transport Layer Security (TLS) Protocol Version 1.3",
                    "latest_rev": "21",
                    "rfc": "rfc8446",
                    "revisions": [
                        {"revision": "draft-ietf-tls-tls13-20", "rev": "20", "date": "2017-07-01"},
                        {"revision": "draft-ietf-tls-tls13-21", "rev": "21", "date": "2017-08-01"},
                    ],
                }
            ],
            "rfcs": {"rfc8446": {"title": "The Transport Layer Security (TLS) Protocol Version 1.3", "rfc_number": 8446}},
        },
        "sections": {
            "rfc": {
                "name": "rfc8446",
                "number": 8446,
                "title": "The Transport Layer Security (TLS) Protocol Version 1.3",
                "sections": {
                    "5.4": {"number": "5.4", "title": "Record Padding", "text": "padding content"},
                    "5.5": {"number": "5.5", "title": "Record Payload Protection", "text": "protection"},
                },
            },
            "drafts": {
                "draft-ietf-tls-tls13-21": {
                    "align": {
                        "5.4": {
                            "draft_number": "5.4",
                            "draft_title": "Record Padding",
                            "rfc_number": "5.4",
                            "rfc_title": "Record Padding",
                            "how": "heading",
                            "similarity": 0.75,
                            "changed": True,
                        }
                    }
                }
            },
        },
    }

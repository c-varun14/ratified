"""Pull one Working Group's roles, drafts, revision history and draft -> RFC map.

All requests go through the shared cache-first Fetcher, so a warmed cache replays
the whole pull with no network.
"""
from __future__ import annotations

import json
from pathlib import Path

from .paths import DATA_DIR

BASE = "https://datatracker.ietf.org"


def jget(fetcher, path: str) -> dict:
    return json.loads(fetcher.get(BASE + path).decode("utf-8"))


def paged(fetcher, path: str, limit: int = 100, cap: int = 200) -> list[dict]:
    out: list[dict] = []
    offset = 0
    while True:
        separator = "&" if "?" in path else "?"
        page = jget(fetcher, f"{path}{separator}limit={limit}&offset={offset}&format=json")
        objects = page.get("objects", [])
        out.extend(objects)
        if not page.get("meta", {}).get("next") or not objects or len(out) >= cap:
            break
        offset += limit
    return out


def pull(fetcher, group: str = "tls", prefix: str = "draft-ietf-tls", data_dir: str = DATA_DIR) -> dict:
    group_obj = jget(fetcher, f"/api/v1/group/group/?acronym={group}&format=json")["objects"][0]
    group_id = group_obj["id"]
    area_id = int(group_obj["parent"].strip("/").split("/")[-1])
    chairs = paged(fetcher, f"/api/v1/group/role/?group={group_id}&name=chair", cap=50)
    ads = paged(fetcher, f"/api/v1/group/role/?group={area_id}&name=ad", cap=50)
    area = jget(fetcher, f"/api/v1/group/group/{area_id}/?format=json")

    drafts = [
        d
        for d in paged(fetcher, f"/api/v1/doc/document/?name__startswith={prefix}", limit=100, cap=1000)
        if d.get("type", "").endswith("/draft/")
    ]

    rfc_map: dict[str, str] = {}
    offset = 0
    while True:
        page = jget(
            fetcher,
            f"/api/v1/doc/relateddocument/?relationship__slug=became_rfc&limit=500&offset={offset}&format=json",
        )
        for obj in page["objects"]:
            source = obj["source"].strip("/").split("/")[-1]
            if source.startswith(prefix):
                rfc_map[source] = obj["target"].strip("/").split("/")[-1]
        if not page["meta"]["next"] or offset + 500 > page["meta"]["total_count"]:
            break
        offset += 500

    revisions = []
    for draft in drafts:
        history = paged(fetcher, f"/api/v1/doc/dochistory/?doc={draft['id']}", limit=100, cap=400)
        revs: dict[str, str] = {}
        for entry in history:
            rev = entry.get("rev") or ""
            when = entry.get("time") or ""
            if rev and (rev not in revs or when < revs[rev]):
                revs[rev] = when
        if not revs:
            latest = draft.get("rev") or "00"
            revs = {f"{n:02d}": "" for n in range(int(latest) + 1)} if latest.isdigit() else {}
        revisions.append(
            {
                "name": draft["name"],
                "title": draft.get("title") or "",
                "latest_rev": draft.get("rev") or "",
                "n_submissions": len(draft.get("submissions") or []),
                "rfc": rfc_map.get(draft["name"]),
                "revisions": [
                    {"revision": f"{draft['name']}-{rev}", "rev": rev, "date": revs[rev]}
                    for rev in sorted(revs, key=lambda r: (len(r), r))
                ],
            }
        )

    rfcs: dict[str, dict] = {}
    for name in sorted(set(rfc_map.values())):
        objects = jget(fetcher, f"/api/v1/doc/document/?name={name}&format=json")["objects"]
        rfcs[name] = {"title": objects[0].get("title") or "", "rfc_number": objects[0].get("rfc_number")}

    def people(roles: list[dict]) -> list[dict]:
        out = []
        for role in roles:
            person = role["person"].strip("/").split("/")[-1]
            out.append(
                {
                    "person": person,
                    "name": jget(fetcher, f"/api/v1/person/person/{person}/?format=json").get("name") or "",
                    "email": (role.get("email") or "").strip("/").split("/")[-1],
                }
            )
        return out

    record = {
        "group": {
            "acronym": group_obj["acronym"],
            "name": group_obj["name"],
            "id": group_id,
            "list_email": group_obj.get("list_email"),
            "list_archive": group_obj.get("list_archive"),
        },
        "area": {"acronym": area.get("acronym"), "name": area.get("name"), "id": area_id},
        "chairs": people(chairs),
        "ads": people(ads),
        "drafts": revisions,
        "rfcs": rfcs,
    }
    path = Path(data_dir) / "docs" / f"{group}_docs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))
    return record


def main() -> None:
    import argparse

    from .fetch import Fetcher

    parser = argparse.ArgumentParser(description="Pull a Working Group's datatracker record.")
    parser.add_argument("--group", default="tls")
    parser.add_argument("--prefix", default="draft-ietf-tls")
    args = parser.parse_args()
    fetcher = Fetcher(min_interval=0.25)
    record = pull(fetcher, args.group, args.prefix)
    fetcher.save_stats()
    print(json.dumps({"drafts": len(record["drafts"]), "rfcs": len(record["rfcs"])}, indent=2))


if __name__ == "__main__":
    main()

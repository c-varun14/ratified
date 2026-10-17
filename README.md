# Ratified

A FalkorDB knowledge graph over one IETF working group's public record — drafts,
RFCs, mailing-list threads, chairs and area directors.

## Run

```sh
docker compose up --build        # FalkorDB + the app on http://127.0.0.1:8000
```

## Rebuild the graph

The graph is rebuilt from the record cached in `data/`. With the package installed
(`pip install -e .`) or inside the app container:

```sh
python -m ratified            # rebuild from the local cache
python -m ratified --refresh  # re-fetch datatracker and section text first, then rebuild
```

`--refresh` warms the cache with fresh pulls; without it the command replays the
cache and never touches the network. Both print the node and edge counts.

# SC2 Replay Parser

Parse StarCraft II bot replays into structured JSONL data for training and analysis.

Built on [sc2reader](https://github.com/ggtracker/sc2reader) with fixes for bot replay compatibility (AI Arena / custom games lack Battle.net region data, which crashes vanilla sc2reader — see [Issue #149](https://github.com/ggtracker/sc2reader/issues/149)).

## Why This Exists

Standard replay parsers break on bot games because they expect Battle.net metadata. This parser handles that gracefully and extracts the data that matters for AI training:

- **Unit tracks** — birth position, death position, unit type, owner, morphs
- **Resource timelines** — minerals, vespene, supply, workers, army value per snapshot
- **Build orders** — structures and units created in order with supply count
- **Upgrade timings** — completed upgrades with timestamps
- **Army composition** — active unit counts at regular intervals
- **Raw events** — every tracker event available for custom processing

## Install

```bash
pip install git+https://github.com/DrekkSama/sc2reader.git@upstream  # Bot replay fix
pip install -e .
```

## Usage

```bash
# JSONL output (one event per line)
python -m sc2_replay_parser replay.SC2Replay

# JSON output (structured object)
python -m sc2_replay_parser --json replay.SC2Replay

# Write to file
python -m sc2_replay_parser replay.SC2Replay output.jsonl
python -m sc2_replay_parser --json replay.SC2Replay output.json
```

## Python API

```python
from sc2_replay_parser.parser import parse_replay, parse_to_jsonl

# Structured dict
data = parse_replay("replay.SC2Replay")
print(data["players"])
print(data["timeline"][0])

# JSONL string
jsonl = parse_to_jsonl("replay.SC2Replay")
```

## Output Format

JSONL output has one JSON object per line with a `type` field:

- `metadata` — map, region, expansion, game length, players
- `build_order` — unit/structure creation with supply and timestamp
- `upgrade` — completed upgrades with timestamp
- `unit_track` — unit lifecycle (born position, death, type, owner)
- `timeline_snapshot` — periodic snapshot of resources, army composition
- `player_stats` — raw PlayerStats events
- Raw unit events (UnitBorn, UnitDied, UnitTypeChange)

## Requires

- Python 3.10+
- sc2reader (DrekkSama fork with bot replay fix)

## License

MIT
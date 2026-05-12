# SC2 Replay Parser & Benchmark Framework

Parse StarCraft II bot replays into structured JSON, then validate bot behavior against progressive workshop benchmarks — CodeCrafters for SC2 bots.

**Part of [VersusAI Workshop](https://community.versusai.net)** — progressive bot-building challenges with automated feedback.

## What This Does

1. **Parse** any SC2 replay (including bot games) into structured JSON with unit tracks, build orders, upgrades, resource timelines, and army snapshots
2. **Benchmark** parsed replays against workshop step validations — pytest-based checks that verify your bot built the right things at the right time
3. **Pipeline** — run a match, parse the replay, run benchmarks, get per-step pass/fail

## Why This Exists

Standard replay parsers crash on bot games because they expect Battle.net metadata. This parser handles that gracefully (see [sc2reader Issue #149](https://github.com/ggtracker/sc2reader/issues/149)) and extracts the data that matters:

- **Unit tracks** — birth/death positions, unit type, owner, morphs
- **Resource timelines** — minerals, vespene, supply, workers, army value per snapshot
- **Build orders** — structures and units created in order with supply count and timestamps
- **Upgrade timings** — completed upgrades with timestamps
- **Army composition** — active unit counts at regular intervals
- **Raw events** — every tracker event available for custom processing
- **Match metadata** — bot names, races, map (enriched from workshop match files)

## Install

```bash
pip install git+https://github.com/DrekkSama/sc2reader.git@upstream  # Bot replay fix
pip install -e .
```

Requires Python 3.10+.

## Parsing Replays

### Command Line

```bash
# JSONL output (one event per line)
python -m sc2_replay_parser replay.SC2Replay

# JSON output (structured object)
python -m sc2_replay_parser --json replay.SC2Replay

# Write to file
python -m sc2_replay_parser replay.SC2Replay output.jsonl
python -m sc2_replay_parser --json replay.SC2Replay output.json
```

### Python API

```python
from sc2_replay_parser.parser import parse_replay, parse_to_jsonl

# Structured dict
data = parse_replay("replay.SC2Replay")
print(data["players"])
print(data["timeline"][0])

# JSONL string
jsonl = parse_to_jsonl("replay.SC2Replay")
```

### Match Orchestration

`run_match.py` runs a full match → parse pipeline:

```bash
# Run a match and parse the replay
python run_match.py --json

# Just parse an existing replay
python run_match.py --json --replay-only ./replays/file.SC2Replay
```

This spins up Docker containers (from `sc2-workshop` config), runs the match, saves the replay, parses it, and enriches bot names from the `matches` file.

## Benchmark Tests

The real power: validate bot behavior against workshop steps.

### Running Benchmarks

```bash
# Against a pre-parsed replay
pytest tests/benchmarks/ -v --parsed=results/match.json

# Against a raw replay file
pytest tests/benchmarks/ -v --replay=path/to/replay.SC2Replay

# Specify which player is the bot (defaults to player 1)
pytest tests/benchmarks/ -v --parsed=results/match.json --bot-player=2

# Run only the Zerg Rush benchmark
pytest tests/benchmarks/test_zerg_rush.py -v --parsed=results/match.json
```

### Zerg Rush Benchmark (Workshop Step 1)

Maps to [Creating a Zerg Rush Bot](https://community.versusai.net/t/creating-a-zerg-rush-bot-in-python-from-scratch/40) on VersusAI Discourse:

| Step | Test | What it checks |
|------|------|---------------|
| 1 | Workers to 16 | ≥16 workers reached; ≥12 drones before pool |
| 2 | Spawning Pool | Pool built; at supply 11-14; at most 1 pool |
| 3 | Extractor | Built; after pool starts |
| 4 | Overlords | No extended supply block before pool |
| 5 | Expand | 2nd Hatchery built; after supply 14 |
| 6 | Zerglings + Queens | Zerglings produced; Queen produced; after pool |
| 7 | Ling Speed | Speed researched; after pool |
| 8 | Queen Production | ≥1 Queen exists |
| 9 | Attack | Zerglings moved toward enemy (death positions or game outcome) |

### Adding New Benchmarks

Benchmarks are just pytest classes in `tests/benchmarks/`. Create a new file for each workshop challenge:

```
tests/benchmarks/
├── __init__.py
├── test_zerg_rush.py          ← Workshop Step 1 (9 steps)
├── test_terran_bio.py         ← (future)
├── test_protoss_4gate.py      ← (future)
└── ...
```

Each benchmark imports helpers from `tests/conftest.py`:

```python
from conftest import (
    LOOPS_PER_SECOND,
    ZERG_UNITS,
    get_build_order,
    get_unit_tracks,
    find_build_entry,
    find_all_build_entries,
)
```

Use the `replay_data` and `bot_player` fixtures in tests — they handle loading and player identification automatically.

### Player-Agnostic Design

Tests don't hardcode player IDs. The `--bot-player` flag specifies which player is the bot being tested:

```bash
# Test player 1 (default)
pytest tests/benchmarks/ --parsed=match.json

# Test player 2
pytest tests/benchmarks/ --parsed=match.json --bot-player=2
```

The `bot_player` fixture resolves this from match metadata when available, falling back to player 1.

## Output Format

### JSON Structure

```json
{
  "map": "Automaton LE",
  "expansion": "LotV",
  "game_length_seconds": 268.0,
  "game_length_loops": 6003,
  "players": {
    "1": {"name": "speedlingbot", "race": "Z", "result": "Unknown"},
    "2": {"name": "loser_bot", "race": "T", "result": "Unknown"}
  },
  "match": {
    "bot1_name": "speedlingbot",
    "bot1_race": "Z",
    "bot2_name": "loser_bot",
    "bot2_race": "T",
    "map": "AutomatonLE"
  },
  "build_orders": {"1": [...], "2": [...]},
  "upgrades": {"1": [...], "2": [...]},
  "unit_tracks": {"1": [...], "2": [...]},
  "timeline": [...],
  "raw_stats_events": {"1": [...], "2": [...]}
}
```

### Build Order Entry

```json
{"frame": 801, "time_seconds": 35.8, "supply": 14.0, "name": "Overlord", "is_worker": false, "is_structure": false}
```

### Unit Track Entry

```json
{"unit_type": "Zergling", "born_at": 3069, "born_x": 155, "born_y": 111, "died_at": null, "died_x": null, "died_y": null, "owner": 1}
```

### Timeline Snapshot

```json
{"time_seconds": 120.0, "players": {"1": {"minerals": 525, "vespene": 28, "workers_active": 20, "food_used": 23.0, "food_made": 30.0, "army_value": 150}}}
```

## Architecture

```
User uploads bot → Match runs (Docker) → Replay saved → Parser extracts JSON → Benchmarks validate → Per-step pass/fail
```

The pipeline is three stages:

1. **Match** — `run_match.py` uses Docker Compose to run bot vs opponent, saves `.SC2Replay` file
2. **Parse** — `sc2_replay_parser` reads the replay, patches sc2reader's bot-replay bug, extracts structured data
3. **Benchmark** — `pytest tests/benchmarks/` validates parsed data against workshop steps

Each stage is independent. You can run benchmarks against any parsed replay without re-running the match.

## sc2reader Patch

Bot games (Private category) lack Battle.net region data, which crashes vanilla sc2reader at `cache_handles`. Our patch in `parser.py` catches the `IndexError` and sets `self.region = 'XX'`, allowing the replay to parse fully.

This is tracked as [Issue #149](https://github.com/ggtracker/sc2reader/issues/149) upstream. When fixed, the patch can be removed.

## Repository Structure

```
sc2-replay-parser/
├── sc2_replay_parser/
│   ├── __init__.py
│   ├── __main__.py          # CLI entry point
│   └── parser.py            # Core parser (sc2reader + patch)
├── tests/
│   ├── conftest.py           # Shared helpers, fixtures, unit constants
│   ├── fixtures/
│   │   └── sample_zerg_rush.json
│   └── benchmarks/
│       ├── __init__.py
│       └── test_zerg_rush.py    # Workshop Step 1 (9 steps, 19 tests)
├── run_match.py              # Match → parse orchestration
├── pyproject.toml
└── README.md
```

## License

MIT
"""SC2 replay parser test configuration.

Registers CLI options for benchmark tests and provides shared fixtures.
Benchmark modules import helpers from this conftest.
"""

import json
from pathlib import Path
from typing import Optional

import pytest

from sc2_replay_parser.parser import parse_replay

# ---------------------------------------------------------------------------
# SC2 constants (replay event names)
# ---------------------------------------------------------------------------
LOOPS_PER_SECOND = 22.4

# Unit/structure names as they appear in replay tracker events
ZERG_UNITS = {
    "SPAWNING_POOL": "SpawningPool",
    "EXTRACTOR": "Extractor",
    "HATCHERY": "Hatchery",
    "OVERLORD": "Overlord",
    "DRONE": "Drone",
    "ZERGLING": "Zergling",
    "QUEEN": "Queen",
    "LARVA": "Larva",
    "BANELING_NEST": "BanelingNest",
    "ROACH_WARREN": "RoachWarren",
    "HYDRALISK_DEN": "HydraliskDen",
    "SPIRE": "Spire",
    "EVOLUTION_CHAMBER": "EvolutionChamber",
    "SPINE_CRAWLER": "SpineCrawler",
    "SPORE_CRAWLER": "SporeCrawler",
    "LAIR": "Lair",
    "HIVE": "Hive",
    "NYDUS_NETWORK": "NydusNetwork",
    "GREATER_SPIRE": "GreaterSpire",
    "INFESTATION_PIT": "InfestationPit",
    "ULTRALISK_CAVERN": "UltraliskCavern",
}

# Terran and Protoss stubs — to be populated when those benchmarks are added
TERRAN_UNITS = {}
PROTOSS_UNITS = {}


# ---------------------------------------------------------------------------
# Data access helpers — player-agnostic
# ---------------------------------------------------------------------------

def resolve_bot_player(data: dict, bot_player: Optional[str] = None) -> str:
    """Determine which player is the bot.

    If bot_player is explicitly provided, use it.
    Otherwise, check match metadata for bot names.
    Falls back to player "1".
    """
    if bot_player is not None:
        return str(bot_player)
    match = data.get("match", {})
    if match.get("bot1_name") and match.get("bot2_name"):
        return "1"
    return "1"


def get_build_order(data: dict, player_id: str = "1") -> list[dict]:
    """Get build order entries for a player."""
    return data.get("build_orders", {}).get(player_id, [])


def get_timeline(data: dict) -> list[dict]:
    """Get timeline snapshots."""
    return data.get("timeline", [])


def get_unit_tracks(data: dict, player_id: str = "1") -> list[dict]:
    """Get unit tracks for a player."""
    return data.get("unit_tracks", {}).get(player_id, [])


def get_upgrades(data: dict, player_id: str = "1") -> list[dict]:
    """Get upgrades for a player."""
    return data.get("upgrades", {}).get(player_id, [])


def get_raw_stats(data: dict, player_id: str = "1") -> list[dict]:
    """Get raw player stats events."""
    return data.get("raw_stats_events", {}).get(player_id, [])


# ---------------------------------------------------------------------------
# Build order search helpers
# ---------------------------------------------------------------------------

def find_build_entry(build_order: list[dict], name: str) -> Optional[dict]:
    """Find the first build order entry for a specific unit/structure name."""
    for entry in build_order:
        if entry["name"] == name:
            return entry
    return None


def find_all_build_entries(build_order: list[dict], name: str) -> list[dict]:
    """Find all build order entries for a specific unit/structure name."""
    return [entry for entry in build_order if entry["name"] == name]


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

def get_supply_at_frame(data: dict, player_id: str, frame: int) -> float:
    """Get food_used at the closest stats event at or before a given frame."""
    stats = get_raw_stats(data, player_id)
    best = None
    best_dist = float("inf")
    for s in stats:
        dist = abs(s["frame"] - frame)
        if dist < best_dist and s["frame"] <= frame:
            best_dist = dist
            best = s
    return best["food_used"] if best else 0.0


def get_minerals_at_frame(data: dict, player_id: str, frame: int) -> int:
    """Get minerals at the closest stats event at or before a given frame."""
    stats = get_raw_stats(data, player_id)
    best = None
    best_dist = float("inf")
    for s in stats:
        dist = abs(s["frame"] - frame)
        if dist < best_dist and s["frame"] <= frame:
            best_dist = dist
            best = s
    return best["minerals"] if best else 0


def get_unit_count_at_frame(data: dict, player_id: str, unit_type: str, frame: int) -> int:
    """Count units of a given type alive at a specific frame."""
    tracks = get_unit_tracks(data, player_id)
    count = 0
    for track in tracks:
        if track["unit_type"] == unit_type:
            if track["born_at"] <= frame:
                if track["died_at"] is None or track["died_at"] > frame:
                    count += 1
    return count


def get_active_units_at_time(data: dict, player_id: str, time_seconds: float) -> dict:
    """Get active unit counts at a specific time from timeline snapshots."""
    for snap in get_timeline(data):
        if abs(snap["time_seconds"] - time_seconds) < 5:
            return snap.get("active_units", {}).get(player_id, {})
    return {}


# ---------------------------------------------------------------------------
# CLI options and fixtures
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--replay",
        action="store",
        default=None,
        help="Path to .SC2Replay file to parse and benchmark",
    )
    parser.addoption(
        "--parsed",
        action="store",
        default=None,
        help="Path to pre-parsed JSON file to benchmark",
    )
    parser.addoption(
        "--bot-player",
        action="store",
        default=None,
        help="Which player is the bot (1 or 2). Auto-detected if not specified.",
    )


@pytest.fixture(scope="session")
def replay_data(request):
    """Load parsed replay data from file or pre-parsed JSON."""
    parsed_path = request.config.getoption("--parsed")
    replay_path = request.config.getoption("--replay")

    if parsed_path:
        with open(parsed_path) as f:
            return json.load(f)
    elif replay_path:
        return parse_replay(replay_path)
    else:
        pytest.skip("Provide --replay or --parsed option")


@pytest.fixture(scope="session")
def bot_player(request, replay_data):
    """Resolve which player ID is the bot."""
    explicit = request.config.getoption("--bot-player")
    return resolve_bot_player(replay_data, explicit)
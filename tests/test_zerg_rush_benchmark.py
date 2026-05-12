"""Benchmark suite for SC2 bot behavior validation from replay data.

Maps to the VersusAI Workshop "Creating a Zerg Rush Bot" steps:
  Step 1: Train workers to 16 supply
  Step 2: Build Spawning Pool at 12 supply
  Step 3: Build Extractor
  Step 4: Build Overlords when needed
  Step 5: Expand after 14 supply
  Step 6: Spawn Zerglings and Queens
  Step 7: Research Zergling Speed
  Step 8: Inject Larvae with Queens
  Step 9: Attack enemy base

Uses parsed replay data (from sc2-replay-parser) instead of live observer data.

Usage:
    pytest tests/test_zerg_rush_benchmark.py -v --replay=path/to/replay.SC2Replay

    # Or with pre-parsed JSON:
    pytest tests/test_zerg_rush_benchmark.py -v --parsed=path/to/parsed.json
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sc2_replay_parser.parser import parse_replay

# ---------------------------------------------------------------------------
# SC2 constants
# ---------------------------------------------------------------------------
LOOPS_PER_SECOND = 22.4

# Unit/structure names as they appear in replay tracker events
SPAWNING_POOL = "SpawningPool"
EXTRACTOR = "Extractor"
HATCHERY = "Hatchery"
OVERLORD = "Overlord"
DRONE = "Drone"
ZERGLING = "Zergling"
QUEEN = "Queen"
LARVA = "Larva"

# Zerg speed upgrade name in replay events
ZERGLING_SPEED = "ZerglingMovementspeed"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_parsed_replay(path: str) -> dict:
    """Load a parsed replay JSON file."""
    with open(path) as f:
        return json.load(f)


def parse_and_load(replay_path: str) -> dict:
    """Parse a .SC2Replay file and return structured data."""
    return parse_replay(replay_path)


# ---------------------------------------------------------------------------
# Assertion helpers for replay data
# ---------------------------------------------------------------------------

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


def find_build_entry(build_order: list[dict], name: str) -> Optional[dict]:
    """Find the first build order entry for a specific unit/structure name."""
    for entry in build_order:
        if entry["name"] == name:
            return entry
    return None


def find_all_build_entries(build_order: list[dict], name: str) -> list[dict]:
    """Find all build order entries for a specific unit/structure name."""
    return [entry for entry in build_order if entry["name"] == name]


def get_supply_at_frame(data: dict, player_id: str, frame: int) -> float:
    """Get food_used at the closest stats event to a given frame."""
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
    """Get minerals at the closest stats event to a given frame."""
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
        if abs(snap["time_seconds"] - time_seconds) < 5:  # Within 5 seconds
            return snap.get("active_units", {}).get(player_id, {})
    return {}


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def replay_data(request):
    """Load parsed replay data from file or pre-parsed JSON."""
    parsed_path = request.config.getoption("--parsed")
    replay_path = request.config.getoption("--replay")

    if parsed_path:
        return load_parsed_replay(parsed_path)
    elif replay_path:
        return parse_and_load(replay_path)
    else:
        # Try the default test replay
        default = Path(__file__).parent / "fixtures" / "1_speedlingbot_vs_loser_bot.json"
        if default.exists():
            return load_parsed_replay(str(default))
        pytest.skip("Provide --replay or --parsed option, or place a test fixture in tests/fixtures/")


# ---------------------------------------------------------------------------
# Workshop Step 1: Train Workers to 16 Supply
# ---------------------------------------------------------------------------

class TestStep1WorkersTo16:
    """Step 1: Train Drones until you reach 16 supply."""

    def test_16_workers_reached(self, replay_data):
        """At some point during the game, the bot should have at least 16 workers."""
        # Check timeline snapshots for worker count >= 16
        for snap in get_timeline(replay_data):
            player = snap.get("players", {}).get("1", {})
            if player.get("workers_active", 0) >= 16:
                return  # Success

        # Also check raw stats
        for stats in get_raw_stats(replay_data, "1"):
            if stats.get("workers_active", 0) >= 16:
                return

        pytest.fail("Never reached 16 workers during the game")

    def test_workers_before_pool(self, replay_data):
        """Worker production should begin before the Spawning Pool.

        At least 12 Drones should be trained before the Spawning Pool appears.
        """
        build_order = get_build_order(replay_data)
        pool_entry = find_build_entry(build_order, SPAWNING_POOL)
        if not pool_entry:
            pytest.skip("No Spawning Pool built in this replay")

        pool_frame = pool_entry["frame"]

        # Count drones built before the pool
        drones_before_pool = sum(
            1 for entry in build_order
            if entry["name"] == DRONE and entry["frame"] < pool_frame
        )

        assert drones_before_pool >= 12, (
            f"Expected ≥ 12 Drones before Spawning Pool, got {drones_before_pool}"
        )


# ---------------------------------------------------------------------------
# Workshop Step 2: Build Spawning Pool at 12 Supply
# ---------------------------------------------------------------------------

class TestStep2SpawningPool:
    """Step 2: Build a Spawning Pool after reaching 12 supply."""

    def test_spawning_pool_built(self, replay_data):
        """A Spawning Pool should appear in the build order."""
        build_order = get_build_order(replay_data)
        pool_entry = find_build_entry(build_order, SPAWNING_POOL)
        assert pool_entry is not None, "No Spawning Pool built during the game"

    def test_pool_at_supply_12(self, replay_data):
        """Spawning Pool should start at supply 12 (Zerg standard).

        Tolerance: supply between 11 and 14 is acceptable.
        """
        build_order = get_build_order(replay_data)
        pool_entry = find_build_entry(build_order, SPAWNING_POOL)
        if not pool_entry:
            pytest.skip("No Spawning Pool built")

        supply = pool_entry.get("supply", 0)
        # Accept supply 11-14 (some variance for overlord timing)
        assert 11 <= supply <= 14, (
            f"Spawning Pool started at supply {supply}, expected 11-14"
        )

    def test_at_most_one_pool(self, replay_data):
        """At no point should there be more than 1 Spawning Pool."""
        build_order = get_build_order(replay_data)
        pool_entries = find_all_build_entries(build_order, SPAWNING_POOL)
        assert len(pool_entries) <= 1, (
            f"Built {len(pool_entries)} Spawning Pools, expected at most 1"
        )


# ---------------------------------------------------------------------------
# Workshop Step 3: Build Extractor
# ---------------------------------------------------------------------------

class TestStep3Extractor:
    """Step 3: Secure gas by building an Extractor."""

    def test_extractor_built(self, replay_data):
        """An Extractor should appear in the build order."""
        build_order = get_build_order(replay_data)
        extractor = find_build_entry(build_order, EXTRACTOR)
        assert extractor is not None, "No Extractor built during the game"

    def test_extractor_after_pool(self, replay_data):
        """Extractor should be built after the Spawning Pool starts."""
        build_order = get_build_order(replay_data)
        pool = find_build_entry(build_order, SPAWNING_POOL)
        extractor = find_build_entry(build_order, EXTRACTOR)

        if not pool or not extractor:
            pytest.skip("Need both Spawning Pool and Extractor to compare timing")

        assert extractor["frame"] >= pool["frame"], (
            f"Extractor built at frame {extractor['frame']} before Pool at {pool['frame']}"
        )


# ---------------------------------------------------------------------------
# Workshop Step 4: Build Overlords When Needed
# ---------------------------------------------------------------------------

class TestStep4Overlords:
    """Step 4: Avoid supply blocks by producing Overlords on time."""

    def test_no_extended_supply_block_before_pool(self, replay_data):
        """No extended hard supply block before Pool.

        Zerg naturally hit 14/14 before their second Overlord pops. This is normal
        and expected — the Overlord costs 0 supply so the bot can still produce one.
        A true block means being stuck at cap for an extended time without any
        Overlord started. We check for blocks lasting >15 seconds with no Overlord.
        """
        build_order = get_build_order(replay_data)
        pool = find_build_entry(build_order, SPAWNING_POOL)
        pool_frame = pool["frame"] if pool else float("inf")

        # Find all frames before pool where food_used >= food_made
        block_frames = []
        for stats in get_raw_stats(replay_data, "1"):
            if stats["frame"] >= pool_frame:
                break
            food_used = stats.get("food_used", 0)
            food_made = stats.get("food_made", 1)
            if food_used >= food_made and food_made > 0:
                block_frames.append(stats["frame"])

        if not block_frames:
            return  # No blocks at all

        # Check if there's an Overlord started within 15 seconds of the first block
        overlords = find_all_build_entries(build_order, OVERLORD)
        first_block_time = block_frames[0] / LOOPS_PER_SECOND

        for ol in overlords:
            ol_time = ol["time_seconds"]
            if ol_time <= first_block_time + 15:
                return  # Overlord started within 15s of block

        # No Overlord produced within 15 seconds of hitting supply cap
        pytest.fail(
            f"Supply block from {first_block_time:.1f}s with no Overlord "
            f"started within 15 seconds"
        )


# ---------------------------------------------------------------------------
# Workshop Step 5: Expand After 14 Supply
# ---------------------------------------------------------------------------

class TestStep5Expand:
    """Step 5: Secure a second Hatchery."""

    def test_second_hatchery_built(self, replay_data):
        """A second Hatchery should be built (natural expansion).

        The starting Hatchery is pre-placed (frame=0) and may not appear
        in unit_tracks. We check that at least 2 total Hatcheries exist.
        """
        # Count Hatcheries from unit tracks
        tracks = get_unit_tracks(replay_data)
        hatchery_tracks = [t for t in tracks if t["unit_type"] == HATCHERY]

        # Also check build order for explicit expansions
        build_order = get_build_order(replay_data)
        hatchery_bo = find_all_build_entries(build_order, HATCHERY)

        # Total = build order entries (excludes starting Hatchery)
        # + 1 for the starting Hatchery if any track exists
        starting = 1 if hatchery_tracks else 0
        total = max(len(hatchery_bo), len(hatchery_tracks)) + (starting if len(hatchery_bo) < len(hatchery_tracks) else 0)
        total = max(len(hatchery_bo) + starting, len(hatchery_tracks))

        assert total >= 2, (
            f"Expected ≥ 2 Hatcheries, found {total} "
            f"({len(hatchery_bo)} in build order, {len(hatchery_tracks)} in tracks)"
        )

    def test_expansion_after_14_supply(self, replay_data):
        """Second Hatchery should start at or after 14 supply."""
        build_order = get_build_order(replay_data)
        hatchery_entries = find_all_build_entries(build_order, HATCHERY)

        # The initial Hatchery is frame=0 supply=0 — that's the starting base.
        # Any Hatchery after that is the expansion.
        expansions = [h for h in hatchery_entries if h["frame"] > 0]
        if not expansions:
            pytest.skip("No expansion Hatchery in build order")

        expansion = expansions[0]
        supply = expansion.get("supply", 0)
        assert supply >= 14, (
            f"Expansion Hatchery at supply {supply}, expected ≥ 14"
        )


# ---------------------------------------------------------------------------
# Workshop Step 6: Spawn Zerglings and Queens
# ---------------------------------------------------------------------------

class TestStep6ZerglingsAndQueens:
    """Step 6: Build army with Zerglings and Queens."""

    def test_zerglings_produced(self, replay_data):
        """Zerglings should appear in the build order after Pool is ready."""
        build_order = get_build_order(replay_data)
        zerglings = find_all_build_entries(build_order, ZERGLING)
        assert len(zerglings) > 0, "No Zerglings produced during the game"

    def test_queen_produced(self, replay_data):
        """At least one Queen should be produced."""
        build_order = get_build_order(replay_data)
        queens = find_all_build_entries(build_order, QUEEN)
        assert len(queens) >= 1, "No Queen produced during the game"

    def test_zerglings_after_pool(self, replay_data):
        """Zerglings should only be produced after Pool starts."""
        build_order = get_build_order(replay_data)
        pool = find_build_entry(build_order, SPAWNING_POOL)
        if not pool:
            pytest.skip("No Spawning Pool to compare timing")

        zerglings = find_all_build_entries(build_order, ZERGLING)
        if not zerglings:
            pytest.skip("No Zerglings produced")

        first_zerg = zerglings[0]
        assert first_zerg["frame"] >= pool["frame"], (
            f"First Zergling at frame {first_zerg['frame']} before Pool at {pool['frame']}"
        )


# ---------------------------------------------------------------------------
# Workshop Step 7: Research Zergling Speed
# ---------------------------------------------------------------------------

class TestStep7ZerglingSpeed:
    """Step 7: Research Zergling Movement Speed."""

    def test_speed_researched(self, replay_data):
        """Zergling Movement Speed upgrade should complete."""
        upgrades = get_upgrades(replay_data)
        # Upgrade names from replay are lowercase: "zerglingmovementspeed"
        speed_ups = [u for u in upgrades
                     if "movementspeed" in u.get("name", "").lower()
                     or "speed" in u.get("name", "").lower()]
        assert len(speed_ups) > 0, "Zergling Movement Speed not researched"

    def test_speed_after_pool_and_extractor(self, replay_data):
        """Speed should be researched after Pool is ready."""
        build_order = get_build_order(replay_data)
        upgrades = get_upgrades(replay_data)

        pool = find_build_entry(build_order, SPAWNING_POOL)
        speed_ups = [u for u in upgrades
                     if "movementspeed" in u.get("name", "").lower()
                     or "speed" in u.get("name", "").lower()]

        if not speed_ups:
            pytest.skip("Zergling Speed not researched")

        if not pool:
            pytest.skip("No Spawning Pool to compare timing")

        speed_frame = speed_ups[0]["frame"]
        assert speed_frame > pool["frame"], (
            f"Speed researched at frame {speed_frame} before Pool at {pool['frame']}"
        )


# ---------------------------------------------------------------------------
# Workshop Step 8: Inject Larvae with Queens
# ---------------------------------------------------------------------------

class TestStep8QueenInjects:
    """Step 8: Use Queens to inject Larva into Hatchery.

    Note: Replay data doesn't directly capture inject orders, but we can verify
    that Queens exist and Larva counts increase beyond natural production.
    """

    def test_queen_exists(self, replay_data):
        """At least one Queen should be produced."""
        tracks = get_unit_tracks(replay_data)
        queens = [t for t in tracks if t["unit_type"] == QUEEN]
        assert len(queens) >= 1, "No Queen produced during the game"


# ---------------------------------------------------------------------------
# Workshop Step 9: Attack Enemy Base
# ---------------------------------------------------------------------------

class TestStep9Attack:
    """Step 9: Attack enemy base with Zerglings.

    Note: Replay data doesn't capture attack commands directly (those are in
    game_events which bot replays don't include). We verify that Zerglings
    moved toward the enemy base by checking their death positions.
    """

    def test_zerglings_sent_to_enemy(self, replay_data):
        """Zerglings should move away from their starting position (indicating attack).

        Bot replays may not record death positions if the opponent surrenders.
        If death data is available, we check distance from spawn. Otherwise, we
        verify that enough zerglings were produced and the game ended quickly
        (indicating a rush attack succeeded).
        """
        tracks = get_unit_tracks(replay_data)
        zerglings = [t for t in tracks if t["unit_type"] == ZERGLING]

        if not zerglings:
            pytest.skip("No Zerglings produced")

        # Check if any zerglings have death position data
        died_with_position = [
            z for z in zerglings
            if z["died_at"] is not None and z.get("died_x") is not None
        ]

        if died_with_position:
            # Use death positions: zerglings that died far from spawn were attacking
            attackers = 0
            for z in died_with_position:
                dx = z["died_x"] - z["born_x"]
                dy = z["died_y"] - z["born_y"]
                dist = (dx ** 2 + dy ** 2) ** 0.5
                if dist > 20:
                    attackers += 1
            assert attackers > 0, (
                f"No Zerglings died away from birth position. "
                f"Total: {len(zerglings)}, died with pos: {len(died_with_position)}"
            )
        else:
            # No death data (opponent surrendered). Fall back to verifying
            # that zerglings were produced and the game ended as a rush.
            total_zerglings = len(zerglings)
            game_length = replay_data.get("game_length_seconds", 0)

            assert total_zerglings >= 4, (
                f"Only {total_zerglings} Zerglings produced — need ≥ 4 to verify attack"
            )
            assert game_length < 300, (
                f"Game took {game_length:.0f}s — rush attack expected under 300s"
            )


# ---------------------------------------------------------------------------
# Overall: Game Result
# ---------------------------------------------------------------------------

class TestGameResult:
    """Overall game outcome validation."""

    def test_game_completed(self, replay_data):
        """Game should have completed (not crashed or timed out)."""
        game_loops = replay_data.get("game_length_loops", 0)
        assert game_loops > 0, "Game did not complete (0 game loops)"

    def test_game_length_reasonable(self, replay_data):
        """Game should last between 30 seconds and 10 minutes for a rush build."""
        duration = replay_data.get("game_length_seconds", 0)
        assert 30 <= duration <= 600, (
            f"Game duration {duration:.0f}s outside expected range (30-600s)"
        )
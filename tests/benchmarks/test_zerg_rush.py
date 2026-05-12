"""Zerg Rush benchmark — progressive validation for Workshop Step "Creating a Zerg Rush Bot".

Maps to VersusAI Workshop Discourse topic 40:
https://community.versusai.net/t/creating-a-zerg-rush-bot-in-python-from-scratch/40

9 progressive steps:
  Step 1: Train workers to 16 supply
  Step 2: Build Spawning Pool at 12 supply
  Step 3: Build Extractor after Pool
  Step 4: Build Overlords when needed (no extended supply blocks)
  Step 5: Expand after 14 supply
  Step 6: Spawn Zerglings and Queens
  Step 7: Research Zergling Speed
  Step 8: Produce Queens
  Step 9: Attack enemy base

Uses parsed replay data from sc2-replay-parser. Player-agnostic — use
--bot-player=1 or --bot-player=2 to specify which player is the bot.
"""

import pytest

from conftest import (
    LOOPS_PER_SECOND,
    ZERG_UNITS,
    get_build_order,
    get_unit_tracks,
    get_upgrades,
    get_raw_stats,
    get_timeline,
    find_build_entry,
    find_all_build_entries,
)

# Shorthand constants for this benchmark
SPAWNING_POOL = ZERG_UNITS["SPAWNING_POOL"]
EXTRACTOR = ZERG_UNITS["EXTRACTOR"]
HATCHERY = ZERG_UNITS["HATCHERY"]
OVERLORD = ZERG_UNITS["OVERLORD"]
DRONE = ZERG_UNITS["DRONE"]
ZERGLING = ZERG_UNITS["ZERGLING"]
QUEEN = ZERG_UNITS["QUEEN"]


# ---------------------------------------------------------------------------
# Step 1: Train Workers to 16 Supply
# ---------------------------------------------------------------------------

class TestStep1WorkersTo16:
    """Step 1: Train Drones until you reach 16 supply."""

    def test_16_workers_reached(self, replay_data, bot_player):
        """At some point during the game, the bot should have at least 16 workers."""
        for snap in get_timeline(replay_data):
            player = snap.get("players", {}).get(bot_player, {})
            if player.get("workers_active", 0) >= 16:
                return

        for stats in get_raw_stats(replay_data, bot_player):
            if stats.get("workers_active", 0) >= 16:
                return

        pytest.fail("Never reached 16 workers during the game")

    def test_workers_before_pool(self, replay_data, bot_player):
        """At least 12 Drones should be trained before the Spawning Pool appears."""
        build_order = get_build_order(replay_data, bot_player)
        pool_entry = find_build_entry(build_order, SPAWNING_POOL)
        if not pool_entry:
            pytest.skip("No Spawning Pool built in this replay")

        pool_frame = pool_entry["frame"]
        drones_before_pool = sum(
            1 for entry in build_order
            if entry["name"] == DRONE and entry["frame"] < pool_frame
        )

        assert drones_before_pool >= 12, (
            f"Expected ≥ 12 Drones before Spawning Pool, got {drones_before_pool}"
        )


# ---------------------------------------------------------------------------
# Step 2: Build Spawning Pool at 12 Supply
# ---------------------------------------------------------------------------

class TestStep2SpawningPool:
    """Step 2: Build a Spawning Pool after reaching 12 supply."""

    def test_spawning_pool_built(self, replay_data, bot_player):
        """A Spawning Pool should appear in the build order."""
        build_order = get_build_order(replay_data, bot_player)
        pool_entry = find_build_entry(build_order, SPAWNING_POOL)
        assert pool_entry is not None, "No Spawning Pool built during the game"

    def test_pool_at_supply_12(self, replay_data, bot_player):
        """Spawning Pool should start at supply 11-14 (Zerg standard range)."""
        build_order = get_build_order(replay_data, bot_player)
        pool_entry = find_build_entry(build_order, SPAWNING_POOL)
        if not pool_entry:
            pytest.skip("No Spawning Pool built")

        supply = pool_entry.get("supply", 0)
        assert 11 <= supply <= 14, (
            f"Spawning Pool started at supply {supply}, expected 11-14"
        )

    def test_at_most_one_pool(self, replay_data, bot_player):
        """At no point should there be more than 1 Spawning Pool."""
        build_order = get_build_order(replay_data, bot_player)
        pool_entries = find_all_build_entries(build_order, SPAWNING_POOL)
        assert len(pool_entries) <= 1, (
            f"Built {len(pool_entries)} Spawning Pools, expected at most 1"
        )


# ---------------------------------------------------------------------------
# Step 3: Build Extractor
# ---------------------------------------------------------------------------

class TestStep3Extractor:
    """Step 3: Secure gas by building an Extractor."""

    def test_extractor_built(self, replay_data, bot_player):
        """An Extractor should appear in the build order."""
        build_order = get_build_order(replay_data, bot_player)
        extractor = find_build_entry(build_order, EXTRACTOR)
        assert extractor is not None, "No Extractor built during the game"

    def test_extractor_after_pool(self, replay_data, bot_player):
        """Extractor should be built after the Spawning Pool starts."""
        build_order = get_build_order(replay_data, bot_player)
        pool = find_build_entry(build_order, SPAWNING_POOL)
        extractor = find_build_entry(build_order, EXTRACTOR)

        if not pool or not extractor:
            pytest.skip("Need both Spawning Pool and Extractor to compare timing")

        assert extractor["frame"] >= pool["frame"], (
            f"Extractor built at frame {extractor['frame']} before Pool at {pool['frame']}"
        )


# ---------------------------------------------------------------------------
# Step 4: Build Overlords When Needed
# ---------------------------------------------------------------------------

class TestStep4Overlords:
    """Step 4: Avoid supply blocks by producing Overlords on time."""

    def test_no_extended_supply_block_before_pool(self, replay_data, bot_player):
        """No extended hard supply block before Pool.

        Zerg naturally hit 14/14 before their second Overlord pops. The Overlord
        costs 0 supply, so the bot can still produce one. A true block means being
        stuck at cap for an extended time with no Overlord started.
        """
        build_order = get_build_order(replay_data, bot_player)
        pool = find_build_entry(build_order, SPAWNING_POOL)
        pool_frame = pool["frame"] if pool else float("inf")

        # Find all frames before pool where food_used >= food_made
        block_frames = []
        for stats in get_raw_stats(replay_data, bot_player):
            if stats["frame"] >= pool_frame:
                break
            food_used = stats.get("food_used", 0)
            food_made = stats.get("food_made", 1)
            if food_used >= food_made and food_made > 0:
                block_frames.append(stats["frame"])

        if not block_frames:
            return  # No blocks at all

        # Check if an Overlord was started within 15 seconds of the first block
        overlords = find_all_build_entries(build_order, OVERLORD)
        first_block_time = block_frames[0] / LOOPS_PER_SECOND

        for ol in overlords:
            if ol["time_seconds"] <= first_block_time + 15:
                return  # Overlord started within 15s of block

        pytest.fail(
            f"Supply block from {first_block_time:.1f}s with no Overlord "
            f"started within 15 seconds"
        )


# ---------------------------------------------------------------------------
# Step 5: Expand After 14 Supply
# ---------------------------------------------------------------------------

class TestStep5Expand:
    """Step 5: Secure a second Hatchery."""

    def test_second_hatchery_built(self, replay_data, bot_player):
        """A second Hatchery should be built (natural expansion)."""
        tracks = get_unit_tracks(replay_data, bot_player)
        hatchery_tracks = [t for t in tracks if t["unit_type"] == HATCHERY]

        build_order = get_build_order(replay_data, bot_player)
        hatchery_bo = find_all_build_entries(build_order, HATCHERY)

        # Starting Hatchery is pre-placed (frame=0 or in unit_tracks)
        # Expansion Hatchery appears in build order with frame > 0
        total = max(len(hatchery_bo) + 1, len(hatchery_tracks))

        assert total >= 2, (
            f"Expected ≥ 2 Hatcheries, found {total} "
            f"({len(hatchery_bo)} in build order, {len(hatchery_tracks)} in tracks)"
        )

    def test_expansion_after_14_supply(self, replay_data, bot_player):
        """Second Hatchery should start at or after 14 supply."""
        build_order = get_build_order(replay_data, bot_player)
        hatchery_entries = find_all_build_entries(build_order, HATCHERY)

        # The initial Hatchery is frame=0 supply=0 — that's the starting base.
        expansions = [h for h in hatchery_entries if h["frame"] > 0]
        if not expansions:
            pytest.skip("No expansion Hatchery in build order")

        expansion = expansions[0]
        supply = expansion.get("supply", 0)
        assert supply >= 14, (
            f"Expansion Hatchery at supply {supply}, expected ≥ 14"
        )


# ---------------------------------------------------------------------------
# Step 6: Spawn Zerglings and Queens
# ---------------------------------------------------------------------------

class TestStep6ZerglingsAndQueens:
    """Step 6: Build army with Zerglings and Queens."""

    def test_zerglings_produced(self, replay_data, bot_player):
        """Zerglings should appear in the build order after Pool is ready."""
        build_order = get_build_order(replay_data, bot_player)
        zerglings = find_all_build_entries(build_order, ZERGLING)
        assert len(zerglings) > 0, "No Zerglings produced during the game"

    def test_queen_produced(self, replay_data, bot_player):
        """At least one Queen should be produced."""
        build_order = get_build_order(replay_data, bot_player)
        queens = find_all_build_entries(build_order, QUEEN)
        assert len(queens) >= 1, "No Queen produced during the game"

    def test_zerglings_after_pool(self, replay_data, bot_player):
        """Zerglings should only be produced after Pool starts."""
        build_order = get_build_order(replay_data, bot_player)
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
# Step 7: Research Zergling Speed
# ---------------------------------------------------------------------------

class TestStep7ZerglingSpeed:
    """Step 7: Research Zergling Movement Speed."""

    def test_speed_researched(self, replay_data, bot_player):
        """Zergling Movement Speed upgrade should complete."""
        upgrades = get_upgrades(replay_data, bot_player)
        speed_ups = [u for u in upgrades
                     if "movementspeed" in u.get("name", "").lower()
                     or "speed" in u.get("name", "").lower()]
        assert len(speed_ups) > 0, "Zergling Movement Speed not researched"

    def test_speed_after_pool(self, replay_data, bot_player):
        """Speed should be researched after Pool is started."""
        build_order = get_build_order(replay_data, bot_player)
        upgrades = get_upgrades(replay_data, bot_player)

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
# Step 8: Produce Queens
# ---------------------------------------------------------------------------

class TestStep8QueenProduction:
    """Step 8: Produce Queens for inject and defense."""

    def test_queen_exists(self, replay_data, bot_player):
        """At least one Queen should be produced."""
        tracks = get_unit_tracks(replay_data, bot_player)
        queens = [t for t in tracks if t["unit_type"] == QUEEN]
        assert len(queens) >= 1, "No Queen produced during the game"


# ---------------------------------------------------------------------------
# Step 9: Attack Enemy Base
# ---------------------------------------------------------------------------

class TestStep9Attack:
    """Step 9: Attack enemy base with Zerglings.

    Replay data doesn't capture attack commands directly. We verify attack
    intent through death positions (units died far from spawn) or, when no
    death data is available, through game outcome (short game + army produced).
    """

    def test_zerglings_sent_to_enemy(self, replay_data, bot_player):
        """Zerglings should move away from spawn (indicating attack)."""
        tracks = get_unit_tracks(replay_data, bot_player)
        zerglings = [t for t in tracks if t["unit_type"] == ZERGLING]

        if not zerglings:
            pytest.skip("No Zerglings produced")

        # Check if any zerglings have death position data
        died_with_position = [
            z for z in zerglings
            if z["died_at"] is not None and z.get("died_x") is not None
        ]

        if died_with_position:
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
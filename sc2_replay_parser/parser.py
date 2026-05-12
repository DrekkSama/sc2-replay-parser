"""SC2 Replay Parser — Extract structured data from StarCraft II bot replays.

Reads .SC2Replay files (including bot games that crash vanilla sc2reader)
and outputs structured JSONL data: unit positions, resource timelines,
build orders, army compositions, upgrade timings, and unit tracks.

Requires: sc2reader (DrekkSama fork with bot replay fix)
"""

import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import sc2reader

# SC2 game loops per second
LOOPS_PER_SECOND = 22.4


@dataclass
class PlayerStats:
    minerals: int = 0
    vespene: int = 0
    food_used: float = 0.0
    food_made: float = 0.0
    workers_active: int = 0
    army_value: int = 0  # minerals_army + vespene_army
    minerals_collected: int = 0  # cumulative
    vespene_collected: int = 0  # cumulative


@dataclass
class UnitTrack:
    unit_type: str
    born_at: int  # game loop
    born_x: int
    born_y: int
    died_at: Optional[int] = None  # game loop, None if alive at end
    died_x: Optional[int] = None
    died_y: Optional[int] = None
    owner: int = 0


@dataclass
class BuildOrderEntry:
    frame: int
    time_seconds: float
    supply: float
    name: str
    is_worker: bool = False
    is_structure: bool = False


@dataclass
class UpgradeEntry:
    frame: int
    time_seconds: float
    name: str


@dataclass
class TimelineSnapshot:
    time_seconds: float
    frame: int
    players: dict  # {pid: PlayerStats-as-dict}
    active_units: dict  # {pid: {unit_type: count}}


@dataclass
class ReplayData:
    """Structured output from a parsed replay."""
    map_name: str
    region: str
    expansion: str
    game_length_seconds: float
    game_length_loops: int
    players: dict  # {pid: {name, race, result}}
    build_orders: dict  # {pid: [BuildOrderEntry]}
    upgrades: dict  # {pid: [UpgradeEntry]}
    unit_tracks: dict  # {pid: [UnitTrack]}
    timeline: list  # [TimelineSnapshot] every 10 seconds
    raw_stats_events: dict  # {pid: [{frame, stats}]}
    raw_unit_events: list  # all UnitBorn/UnitDied/UnitTypeChange events

    # Workers for build order detection
    WORKER_TYPES = {"SCV", "Drone", "Probe", "MULE"}
    STRUCTURE_TYPES = {
        # Terran
        "CommandCenter", "OrbitalCommand", "PlanetaryFortress",
        "Barracks", "Factory", "Starport",
        "SupplyDepot", "Refinery", "Bunker", "MissileTurret",
        "EngineeringBay", "Armory", "GhostAcademy",
        "FusionCore", "SensorTower",
        # Protoss
        "Nexus", "Gateway", "WarpGate", "CyberneticsCore",
        "Stargate", "RoboticsFacility", "RoboticsBay",
        "Forge", "TwilightCouncil", "TemplarArchive", "DarkShrine",
        "FleetBeacon", "PhotonCannon", "ShieldBattery", "Pylon",
        "Assimilator",
        # Zerg
        "Hatchery", "Lair", "Hive",
        "SpawningPool", "RoachWarren", "HydraliskDen", "BanelingNest",
        "Spire", "GreaterSpire", "InfestationPit", "UltraliskCavern",
        "EvolutionChamber", "SpineCrawler", "SporeCrawler",
        "Extractor", "CreepTumor", "NydusNetwork",
    }


def parse_replay(replay_path: str, timeline_interval: int = 10) -> dict:
    """Parse an SC2 replay file and return structured data.

    Args:
        replay_path: Path to .SC2Replay file
        timeline_interval: Seconds between timeline snapshots (default 10)

    Returns:
        dict with all parsed replay data
    """
    replay = sc2reader.load_replay(replay_path, load_level=3)

    game_loops = replay.game_length.seconds * LOOPS_PER_SECOND if hasattr(replay.game_length, 'seconds') else 0

    # Player info from PlayerSetupEvents
    players = {}
    for e in replay.tracker_events:
        if type(e).__name__ == "PlayerSetupEvent":
            pid = e.pid
            players[pid] = {
                "name": f"Player {pid}",
                "race": "Unknown",
                "result": "Unknown",
            }

    # Try to get player names and races from replay object
    for p in getattr(replay, 'players', []):
        if p and hasattr(p, 'pid') and p.pid in players:
            players[p.pid]["name"] = p.name if hasattr(p, 'name') else f"Player {p.pid}"
            players[p.pid]["race"] = str(p.play_race) if hasattr(p, 'play_race') else "Unknown"
            players[p.pid]["result"] = str(p.result) if hasattr(p, 'result') else "Unknown"

    # Build unit tracks
    unit_tracks = _build_unit_tracks(replay)

    # Build orders
    build_orders = _build_orders(replay)

    # Upgrades
    upgrades = _build_upgrades(replay)

    # Timeline snapshots
    timeline = _build_timeline(replay, timeline_interval)

    # Raw stats events for detailed analysis
    raw_stats = _extract_raw_stats(replay)

    # Raw unit events
    raw_unit_events = _extract_raw_unit_events(replay)

    return {
        "map_name": replay.map_name,
        "region": replay.region,
        "expansion": replay.expansion,
        "game_length_seconds": round(game_loops / LOOPS_PER_SECOND, 1),
        "game_length_loops": int(game_loops),
        "players": players,
        "build_orders": {pid: [asdict(e) for e in entries] for pid, entries in build_orders.items()},
        "upgrades": {pid: [asdict(e) for e in entries] for pid, entries in upgrades.items()},
        "unit_tracks": {pid: [asdict(t) for t in tracks] for pid, tracks in unit_tracks.items()},
        "timeline": [asdict(snap) for snap in timeline],
        "raw_stats_events": raw_stats,
        "raw_unit_events": raw_unit_events,
    }


def _build_unit_tracks(replay) -> dict:
    """Track every unit born and died per player."""
    # {unit_tag: UnitTrack}
    units = {}
    born_loops = {}

    for e in replay.tracker_events:
        etype = type(e).__name__

        if etype == "UnitBornEvent":
            tag = e.unit_id
            owner = getattr(e, 'control_pid', getattr(e, 'control_player_id', 0))
            utype = getattr(e, 'unit_type_name', 'Unknown')
            # Skip neutral units
            if owner not in (1, 2):
                continue
            # Skip beacons and debris
            if utype.startswith("Beacon") or utype in ("Debris2x2NonConjoined", "Debris4x4NonConjoined"):
                continue

            track = UnitTrack(
                unit_type=utype,
                born_at=e.frame,
                born_x=getattr(e, 'x', 0),
                born_y=getattr(e, 'y', 0),
                owner=owner,
            )
            units[tag] = track
            born_loops[tag] = e.frame

        elif etype == "UnitDiedEvent":
            tag = e.unit_id
            if tag in units:
                units[tag].died_at = e.frame
                units[tag].died_x = getattr(e, 'x', 0)
                units[tag].died_y = getattr(e, 'y', 0)

        elif etype == "UnitTypeChangeEvent":
            tag = e.unit_id
            if tag in units:
                units[tag].unit_type = getattr(e, 'unit_type_name', units[tag].unit_type)

    # Group by owner
    by_player = defaultdict(list)
    for track in units.values():
        by_player[track.owner].append(track)

    return dict(by_player)


def _build_orders(replay) -> dict:
    """Extract build orders (units and structures created) per player."""
    orders = defaultdict(list)
    seen = set()  # Avoid duplicates from UnitBorn + UnitDone

    for e in replay.tracker_events:
        etype = type(e).__name__

        if etype in ("UnitBornEvent", "UnitInitEvent", "UnitDoneEvent"):
            tag = e.unit_id
            # UnitDone is the completion event for structures; UnitBorn for regular units
            # Use the earliest event for each unit
            if tag in seen:
                continue
            seen.add(tag)

            owner = getattr(e, 'control_pid', getattr(e, 'control_player_id', 0))
            if owner not in (1, 2):
                continue

            utype = getattr(e, 'unit_type_name', 'Unknown')
            if utype.startswith("Beacon") or utype in ("Debris2x2NonConjoined",):
                continue
            # Skip Larva from build order
            if utype == "Larva":
                continue

            # Find supply at this frame
            supply = _get_supply_at_frame(replay, owner, e.frame)

            entry = BuildOrderEntry(
                frame=e.frame,
                time_seconds=round(e.frame / LOOPS_PER_SECOND, 1),
                supply=supply,
                name=utype,
                is_worker=utype in ReplayData.WORKER_TYPES,
                is_structure=utype in ReplayData.STRUCTURE_TYPES,
            )
            orders[owner].append(entry)

    return dict(orders)


def _build_upgrades(replay) -> dict:
    """Extract completed upgrades per player."""
    upgrades = defaultdict(list)

    for e in replay.tracker_events:
        if type(e).__name__ == "UpgradeCompleteEvent":
            pid = getattr(e, 'pid', 0)
            if pid not in (1, 2):
                continue
            name = getattr(e, 'upgrade_type_name', 'Unknown')
            # Skip spray upgrades
            if name.startswith("Spray"):
                continue

            upgrades[pid].append(UpgradeEntry(
                frame=e.frame,
                time_seconds=round(e.frame / LOOPS_PER_SECOND, 1),
                name=name,
            ))

    return dict(upgrades)


def _build_timeline(replay, interval: int) -> list:
    """Build timeline snapshots at regular intervals."""
    # Collect all stats events per player
    stats_by_frame = defaultdict(dict)
    for e in replay.tracker_events:
        if type(e).__name__ == "PlayerStatsEvent":
            pid = e.pid
            if pid not in (1, 2):
                continue
            stats_by_frame[e.frame][pid] = PlayerStats(
                minerals=e.minerals_current,
                vespene=e.vespene_current,
                food_used=e.food_used,
                food_made=e.food_made,
                workers_active=e.workers_active_count,
                army_value=getattr(e, 'minerals_used_current_army', 0) + getattr(e, 'vespene_used_current_army', 0),
            )

    # Collect active units per frame range
    # We'll track unit births and deaths to compute active units at each snapshot time
    unit_births = []  # (frame, owner, type)
    unit_deaths = {}  # unit_tag -> frame

    for e in replay.tracker_events:
        etype = type(e).__name__
        if etype == "UnitBornEvent":
            owner = getattr(e, 'control_pid', getattr(e, 'control_player_id', 0))
            if owner in (1, 2):
                unit_births.append((e.frame, owner, getattr(e, 'unit_type_name', 'Unknown'), e.unit_id))
        elif etype == "UnitDiedEvent":
            unit_deaths[e.unit_id] = e.frame
        elif etype == "UnitTypeChangeEvent":
            # Track morphs — we skip for simplicity in timeline
            pass

    # Build snapshots
    game_length_frames = max(stats_by_frame.keys()) if stats_by_frame else 0
    interval_frames = int(interval * LOOPS_PER_SECOND)
    snapshots = []

    for target_frame in range(0, game_length_frames + 1, interval_frames):
        # Find closest stats frame for each player
        closest_stats = {}
        for pid in (1, 2):
            best_frame = None
            best_dist = float('inf')
            for frame, pdata in stats_by_frame.items():
                if pid in pdata and abs(frame - target_frame) < best_dist:
                    best_dist = abs(frame - target_frame)
                    best_frame = frame
            if best_frame is not None:
                closest_stats[pid] = stats_by_frame[best_frame][pid]

        # Count active units at this frame
        active_units = defaultdict(lambda: defaultdict(int))
        for birth_frame, owner, utype, tag in unit_births:
            if birth_frame > target_frame:
                continue
            death_frame = unit_deaths.get(tag)
            if death_frame is not None and death_frame <= target_frame:
                continue
            # Skip workers and Larva for army composition
            if utype in ("Larva", "Egg", "Drone", "SCV", "Probe", "MULE"):
                if utype != "Drone" and utype != "SCV" and utype != "Probe":
                    continue
            active_units[owner][utype] += 1

        snap = TimelineSnapshot(
            time_seconds=round(target_frame / LOOPS_PER_SECOND, 1),
            frame=target_frame,
            players={pid: asdict(stats) for pid, stats in closest_stats.items()},
            active_units={pid: dict(units) for pid, units in active_units.items()},
        )
        snapshots.append(snap)

    return snapshots


def _get_supply_at_frame(replay, pid: int, frame: int) -> float:
    """Find the closest food_used value for a player at a given frame."""
    for e in replay.tracker_events:
        if type(e).__name__ == "PlayerStatsEvent" and e.pid == pid:
            # Find the closest stats event at or before this frame
            pass

    # Walk backwards from the frame to find closest stats
    best_supply = 0.0
    best_dist = float('inf')
    for e in replay.tracker_events:
        if type(e).__name__ == "PlayerStatsEvent" and e.pid == pid:
            dist = abs(e.frame - frame)
            if dist < best_dist and e.frame <= frame:
                best_dist = dist
                best_supply = e.food_used
    return best_supply


def _extract_raw_stats(replay) -> dict:
    """Extract raw PlayerStatsEvents per player."""
    result = defaultdict(list)
    for e in replay.tracker_events:
        if type(e).__name__ == "PlayerStatsEvent":
            pid = e.pid
            if pid not in (1, 2):
                continue
            result[pid].append({
                "frame": e.frame,
                "second": e.second,
                "minerals": e.minerals_current,
                "vespene": e.vespene_current,
                "food_used": e.food_used,
                "food_made": e.food_made,
                "workers_active": e.workers_active_count,
                "minerals_used_active_army": getattr(e, 'minerals_used_current_army', 0),
                "vespene_used_active_army": getattr(e, 'vespene_used_current_army', 0),
                "minerals_used_active_economy": getattr(e, 'minerals_used_current_economy', 0),
                "vespene_used_active_economy": getattr(e, 'vespene_used_current_economy', 0),
            })
    return dict(result)


def _extract_raw_unit_events(replay) -> list:
    """Extract raw unit events (born, died, type change)."""
    events = []
    for e in replay.tracker_events:
        etype = type(e).__name__
        if etype in ("UnitBornEvent", "UnitDiedEvent", "UnitTypeChangeEvent"):
            owner = getattr(e, 'control_pid', getattr(e, 'control_player_id', 0))
            if etype == "UnitDiedEvent":
                owner = 0  # Death events don't have owner

            event = {
                "type": etype,
                "frame": e.frame,
                "second": e.second,
                "unit_id": getattr(e, 'unit_id', 0),
                "unit_type": getattr(e, 'unit_type_name', 'Unknown'),
                "owner": owner,
                "x": getattr(e, 'x', 0),
                "y": getattr(e, 'y', 0),
            }
            events.append(event)
    return events


def parse_to_jsonl(replay_path: str, timeline_interval: int = 10) -> str:
    """Parse a replay and return JSONL string (one JSON object per line).

    Each line is a self-contained event or snapshot.
    """
    data = parse_replay(replay_path, timeline_interval)
    lines = []

    # Metadata line
    meta = {
        "type": "metadata",
        "map": data["map_name"],
        "region": data["region"],
        "expansion": data["expansion"],
        "game_length_seconds": data["game_length_seconds"],
        "game_length_loops": data["game_length_loops"],
        "players": data["players"],
    }
    lines.append(json.dumps(meta))

    # Build order lines
    for pid, entries in data["build_orders"].items():
        for entry in entries:
            line = {"type": "build_order", "player": int(pid)}
            line.update(entry)
            lines.append(json.dumps(line))

    # Upgrade lines
    for pid, entries in data["upgrades"].items():
        for entry in entries:
            line = {"type": "upgrade", "player": int(pid)}
            line.update(entry)
            lines.append(json.dumps(line))

    # Unit track lines
    for pid, tracks in data["unit_tracks"].items():
        for track in tracks:
            line = {"type": "unit_track", "player": int(pid)}
            line.update(track)
            lines.append(json.dumps(line))

    # Timeline snapshots
    for snap in data["timeline"]:
        line = {"type": "timeline_snapshot"}
        line.update(snap)
        lines.append(json.dumps(line))

    # Raw stats
    for pid, stats_list in data["raw_stats_events"].items():
        for stats in stats_list:
            line = {"type": "player_stats", "player": int(pid)}
            line.update(stats)
            lines.append(json.dumps(line))

    # Raw unit events
    for event in data["raw_unit_events"]:
        lines.append(json.dumps(event))

    return "\n".join(lines)


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: sc2-replay-parser <replay_file.SC2Replay> [output.jsonl]")
        print("       sc2-replay-parser --json <replay_file.SC2Replay> [output.json]")
        sys.exit(1)

    replay_path = sys.argv[1]
    output_format = "jsonl"

    if sys.argv[1] == "--json":
        output_format = "json"
        replay_path = sys.argv[2]
        output_file = sys.argv[3] if len(sys.argv) > 3 else None
    else:
        output_file = sys.argv[2] if len(sys.argv) > 2 else None

    if not Path(replay_path).exists():
        print(f"Error: File not found: {replay_path}", file=sys.stderr)
        sys.exit(1)

    if output_format == "json":
        data = parse_replay(replay_path)
        output = json.dumps(data, indent=2, default=str)
    else:
        output = parse_to_jsonl(replay_path)

    if output_file:
        Path(output_file).write_text(output)
        print(f"Output written to {output_file}")
    else:
        print(output)


if __name__ == "__main__":
    main()
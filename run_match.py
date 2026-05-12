#!/usr/bin/env python3
"""SC2 Match Runner — Run a match and parse the replay automatically.

Usage:
    python run_match.py [--parse] [--json] [--keep-containers]

    --parse             Parse the replay after the match (default: True)
    --json              Output parsed data as JSON instead of JSONL
    --keep-containers   Don't shut down containers after match
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Workshop directory (where docker-compose.yml lives)
WORKSHOP_DIR = Path(__file__).parent
REPLAYS_DIR = WORKSHOP_DIR / "replays"
MATCHES_FILE = WORKSHOP_DIR / "matches"
RESULTS_DIR = WORKSHOP_DIR / "results"


def parse_matches_file():
    """Parse the matches file to get bot names and races.

    Format: #Bot1_ID,Bot1_name,Bot1_race,Bot1_type,Bot2_ID,Bot2_name,Bot2_race,Bot2_type,Map
    Lines starting with '#' followed by a header keyword are skipped.
    Data lines start with '#1,...' where the # is stripped before parsing.
    """
    matches = []
    with open(MATCHES_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Remove leading #
            if line.startswith("#"):
                line = line[1:]
            # Skip header rows (contain column names, not data)
            # Data rows start with a match ID (digit)
            if not line or not line[0].isdigit():
                continue
            parts = line.split(",")
            if len(parts) >= 8:
                matches.append({
                    "bot1_id": parts[0].strip(),
                    "bot1_name": parts[1].strip(),
                    "bot1_race": parts[2].strip(),
                    "bot1_type": parts[3].strip(),
                    "bot2_id": parts[4].strip(),
                    "bot2_name": parts[5].strip(),
                    "bot2_race": parts[6].strip(),
                    "bot2_type": parts[7].strip(),
                    "map": parts[8].strip() if len(parts) > 8 else "AutomatonLE",
                })
    return matches


def run_match(timeout=300):
    """Run the match via docker compose and wait for completion.

    Returns the replay file path, or None if no replay found.
    """
    print("Starting match...")
    cwd = str(WORKSHOP_DIR)

    # Start containers
    subprocess.run(["docker", "compose", "up", "-d"], cwd=cwd, check=True)

    # Wait for containers to exit (they auto-shutdown after match)
    print("Waiting for match to complete (timeout: {}s)...".format(timeout))
    start = time.time()
    while time.time() - start < timeout:
        result = subprocess.run(
            ["docker", "compose", "ps", "-q"],
            cwd=cwd, capture_output=True, text=True
        )
        if not result.stdout.strip():
            print("All containers exited.")
            break
        time.sleep(2)
    else:
        print(f"Match timed out after {timeout}s")

    # Find replay files
    replay_files = sorted(REPLAYS_DIR.glob("*.SC2Replay"), key=lambda f: f.stat().st_mtime)
    if replay_files:
        replay_path = replay_files[-1]
        print(f"Replay found: {replay_path.name}")
        return replay_path
    else:
        print("No replay file found!")
        return None


def parse_replay_file(replay_path, output_format="jsonl"):
    """Parse the replay file using sc2-replay-parser.

    Args:
        replay_path: Path to .SC2Replay file
        output_format: 'jsonl' or 'json'

    Returns:
        Parsed data dict (if json) or None (jsonl prints to stdout)
    """
    from sc2_replay_parser.parser import parse_replay, parse_to_jsonl

    # Enrich with match metadata from matches file
    matches = parse_matches_file()
    match_info = matches[0] if matches else {}

    if output_format == "json":
        data = parse_replay(str(replay_path))

        # Enrich with match metadata
        if match_info:
            data["match"] = {
                "bot1_name": match_info.get("bot1_name", "Unknown"),
                "bot1_race": match_info.get("bot1_race", "Unknown"),
                "bot2_name": match_info.get("bot2_name", "Unknown"),
                "bot2_race": match_info.get("bot2_race", "Unknown"),
                "map": match_info.get("map", "Unknown"),
            }

            # Map player IDs to bot names
            for pid in data.get("players", {}):
                pid_str = str(pid)
                if pid_str == "1":
                    data["players"][pid]["name"] = match_info.get("bot1_name", f"Player {pid}")
                    data["players"][pid]["race"] = match_info.get("bot1_race", "Unknown")
                elif pid_str == "2":
                    data["players"][pid]["name"] = match_info.get("bot2_name", f"Player {pid}")
                    data["players"][pid]["race"] = match_info.get("bot2_race", "Unknown")

        return data
    else:
        # JSONL — get base data, enrich, output
        data = parse_replay(str(replay_path))

        # Enrich with match metadata
        if match_info:
            data["match"] = {
                "bot1_name": match_info.get("bot1_name", "Unknown"),
                "bot1_race": match_info.get("bot1_race", "Unknown"),
                "bot2_name": match_info.get("bot2_name", "Unknown"),
                "bot2_race": match_info.get("bot2_race", "Unknown"),
                "map": match_info.get("map", "Unknown"),
            }
            for pid in data.get("players", {}):
                pid_str = str(pid)
                if pid_str == "1":
                    data["players"][pid]["name"] = match_info.get("bot1_name", f"Player {pid}")
                    data["players"][pid]["race"] = match_info.get("bot1_race", "Unknown")
                elif pid_str == "2":
                    data["players"][pid]["name"] = match_info.get("bot2_name", f"Player {pid}")
                    data["players"][pid]["race"] = match_info.get("bot2_race", "Unknown")

        jsonl = parse_to_jsonl(str(replay_path))

        # Replace metadata line with enriched version
        lines = jsonl.split("\n")
        enriched_lines = []
        for line in lines:
            obj = json.loads(line)
            if obj["type"] == "metadata" and match_info:
                obj["match"] = {
                    "bot1_name": match_info.get("bot1_name", "Unknown"),
                    "bot1_race": match_info.get("bot1_race", "Unknown"),
                    "bot2_name": match_info.get("bot2_name", "Unknown"),
                    "bot2_race": match_info.get("bot2_race", "Unknown"),
                    "map": match_info.get("map", "Unknown"),
                }
                # Update player names in metadata
                for pid in obj.get("players", {}):
                    pid_str = str(pid)
                    if pid_str == "1":
                        obj["players"][pid]["name"] = match_info.get("bot1_name", f"Player {pid}")
                        obj["players"][pid]["race"] = match_info.get("bot1_race", "Unknown")
                    elif pid_str == "2":
                        obj["players"][pid]["name"] = match_info.get("bot2_name", f"Player {pid}")
                        obj["players"][pid]["race"] = match_info.get("bot2_race", "Unknown")
            enriched_lines.append(json.dumps(obj))

        return "\n".join(enriched_lines)


def save_results(replay_path, parsed_data, output_format):
    """Save parsed results to the results directory."""
    RESULTS_DIR.mkdir(exist_ok=True)
    stem = replay_path.stem  # e.g., "1_speedlingbot_vs_loser_bot"
    ext = "json" if output_format == "json" else "jsonl"
    output_path = RESULTS_DIR / f"{stem}.{ext}"

    if output_format == "json":
        output_path.write_text(json.dumps(parsed_data, indent=2, default=str))
    else:
        output_path.write_text(parsed_data)

    print(f"Results saved to: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Run an SC2 match and parse the replay")
    parser.add_argument("--parse", action="store_true", default=True, help="Parse replay after match")
    parser.add_argument("--json", action="store_true", help="Output as JSON instead of JSONL")
    parser.add_argument("--keep-containers", action="store_true", help="Don't shut down containers after match")
    parser.add_argument("--replay-only", type=str, help="Parse an existing replay file without running a match")
    parser.add_argument("--timeout", type=int, default=300, help="Match timeout in seconds (default: 300)")
    args = parser.parse_args()

    output_format = "json" if args.json else "jsonl"

    if args.replay_only:
        # Just parse an existing replay
        replay_path = Path(args.replay_only)
        if not replay_path.exists():
            print(f"Error: File not found: {replay_path}", file=sys.stderr)
            sys.exit(1)
        print(f"Parsing replay: {replay_path.name}")
        parsed = parse_replay_file(replay_path, output_format)
        output_path = save_results(replay_path, parsed, output_format)

        # Print summary
        if output_format == "json":
            print(f"\nMap: {parsed['map_name']}")
            print(f"Players: {json.dumps(parsed['players'], indent=2)}")
            print(f"Game length: {parsed['game_length_seconds']}s ({parsed['game_length_loops']} loops)")
            print(f"Unit tracks: {sum(len(v) for v in parsed['unit_tracks'].values())}")
            print(f"Build orders: {sum(len(v) for v in parsed['build_orders'].values())} entries")
            print(f"Timeline snapshots: {len(parsed['timeline'])}")
        else:
            # Count types in JSONL
            types = {}
            for line in parsed.split("\n"):
                obj = json.loads(line)
                t = obj["type"]
                types[t] = types.get(t, 0) + 1
            print("\nEvent counts:")
            for t, c in sorted(types.items()):
                print(f"  {t}: {c}")
        return

    # Run the match
    replay_path = run_match(timeout=args.timeout)

    if not args.keep_containers:
        print("Shutting down containers...")
        subprocess.run(["docker", "compose", "down"], cwd=str(WORKSHOP_DIR), check=True)

    if replay_path and args.parse:
        print(f"\nParsing replay: {replay_path.name}")
        parsed = parse_replay_file(replay_path, output_format)
        output_path = save_results(replay_path, parsed, output_format)

        # Print summary
        if output_format == "json":
            print(f"\nMap: {parsed['map_name']}")
            print(f"Game length: {parsed['game_length_seconds']}s")
            print(f"Players: {json.dumps(parsed['players'], indent=2)}")
            print(f"Unit tracks: {sum(len(v) for v in parsed['unit_tracks'].values())}")
        else:
            types = {}
            for line in parsed.split("\n"):
                obj = json.loads(line)
                t = obj["type"]
                types[t] = types.get(t, 0) + 1
            print("\nEvent counts:")
            for t, c in sorted(types.items()):
                print(f"  {t}: {c}")
    elif not replay_path:
        print("No replay to parse.")


if __name__ == "__main__":
    main()
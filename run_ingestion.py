"""
Run the full ingestion pipeline: config -> schema init -> teams ->
players -> per-competition matches/events -> minutes.

Usage (from repo root, e.g. /kaggle/working/midfieldscout):
    python run_ingestion.py --competition England

Or import run_competition() directly in a notebook cell for more
granular control / progress printing between leagues.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from config import load_config
from ingestion.loader import init_db, load_teams_file, load_competition_file
import json


def run_competition(cfg: dict, competition_name: str, source_file: str, season: str) -> None:
    raw_root = Path(cfg["resolved_paths"]["raw"])
    # This Kaggle dataset layout nests matches/events in subfolders,
    # with players.json/teams.json flat at raw_root — checked against
    # the actual mounted paths, not assumed.
    matches_path = raw_root / "matches" / f"matches_{competition_name}.json"
    events_path = raw_root / "events" / f"events_{competition_name}.json"

    if not matches_path.exists():
        raise FileNotFoundError(
            f"Expected {matches_path} — check filenames in your Kaggle dataset "
            f"match this pattern (matches_<Competition>.json)."
        )
    if not events_path.exists():
        raise FileNotFoundError(f"Expected {events_path}")

    print(f"[{competition_name}] loading events feed...")
    all_events = json.loads(events_path.read_text())
    events_by_match: dict[int, list] = {}
    for e in all_events:
        events_by_match.setdefault(e["matchId"], []).append(e)
    print(f"[{competition_name}] {len(all_events)} events across {len(events_by_match)} matches")

    con = init_db(cfg["resolved_paths"]["duckdb_file"], "src/ingestion/schema.sql")

    players_path = raw_root / "players.json"
    teams_path = raw_root / "teams.json"
    load_teams_file(con, str(teams_path))

    result = load_competition_file(
        con,
        str(matches_path),
        events_by_match,
        str(players_path),
        competition=competition_name,
        season=season,
    )
    print(f"[{competition_name}] matches={result.matches_loaded} "
          f"events={result.events_loaded} participation_rows={result.participation_rows} "
          f"warnings={len(result.warnings)}")
    if result.warnings[:5]:
        print("  first warnings:", result.warnings[:5])

    con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--competition", required=True,
                         help="England, Spain, Italy, Germany, or France")
    args = parser.parse_args()

    cfg = load_config("configs/paths.yaml")
    comp_cfg = next(
        (c for c in cfg["wyscout"]["competitions"] if c["name"] == args.competition), None
    )
    if comp_cfg is None:
        raise ValueError(f"Unknown competition {args.competition}; check configs/paths.yaml")

    run_competition(cfg, args.competition, comp_cfg["source_file"], comp_cfg["season"])
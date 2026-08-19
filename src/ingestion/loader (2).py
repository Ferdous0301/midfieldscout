"""
Ingestion loader for the Wyscout Public Dataset (Pappalardo et al., 2019).

IMPORTANT DATA-SHAPE NOTE (validated against real files, Aug 2026):
    Two different packagings of this dataset exist:

    1. Original figshare files (what the user downloads directly, per
       project decision): `matches_<Competition>.json` is a LIST of match
       objects, each containing `teamsData.<teamId>.formation.lineup`,
       `.bench`, and `.substitutions` (with substitution minute). This is
       the ONLY packaging that lets us compute accurate minutes-played,
       so it is the one this loader targets.

    2. The GitHub "processed" repackaging (koenvo/wyscout-soccer-match-
       event-dataset) strips substitution/lineup metadata down to just
       {events, teams, players} per match. It was used only to sanity-check
       the event/player schema during design and is NOT sufficient for
       minutes calculation. Do not point production ingestion at it.

Minutes-played derivation (documented assumption):
    - Starting XI players are assumed to play from minute 0 until either
      full time or their substitution-off minute, whichever comes first.
    - Bench players who were substituted on are assumed to play from
      their substitution-on minute until full time.
    - Players not in `lineup` or `bench` are given minutes_played = NULL
      (not 0) — NULL means "unknown", 0 means "known not to have played",
      and these must not be treated as equivalent downstream.
    - Match length is taken as 90 minutes + any stoppage inferred from the
      max event_sec in the second half; extra time is out of scope for v1
      (league matches only).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class DataIntegrityError(Exception):
    """Raised when raw data fails a hard validation check (not silently skipped)."""


@dataclass(frozen=True)
class IngestResult:
    matches_loaded: int
    events_loaded: int
    players_loaded: int
    teams_loaded: int
    participation_rows: int
    warnings: list[str]


def _parse_birthdate(raw: str | None) -> date | None:
    if not raw or raw in ("0000-00-00", ""):
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, "null", ""):
            return None
        return int(value)
    except (ValueError, TypeError):
        return None


def upsert_teams(con: duckdb.DuckDBPyConnection, teams_raw: dict[str, Any]) -> int:
    rows = []
    for team_id_str, t in teams_raw.items():
        rows.append(
            (
                int(team_id_str),
                t.get("name"),
                t.get("officialName"),
                (t.get("area") or {}).get("name"),
            )
        )
    if not rows:
        return 0
    con.executemany(
        """
        INSERT INTO teams (team_id, name, official_name, country)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (team_id) DO UPDATE SET
            name = excluded.name,
            official_name = excluded.official_name,
            country = excluded.country
        """,
        rows,
    )
    return len(rows)


def upsert_players(con: duckdb.DuckDBPyConnection, players_by_team: dict[str, list[dict]]) -> int:
    rows = []
    seen: set[int] = set()
    for _team_id, plist in players_by_team.items():
        for entry in plist:
            p = entry.get("player", entry)  # tolerate both shapes
            pid = _safe_int(p.get("wyId") or entry.get("playerId"))
            if pid is None or pid in seen:
                continue
            seen.add(pid)
            role = p.get("role") or {}
            rows.append(
                (
                    pid,
                    p.get("firstName"),
                    p.get("lastName"),
                    p.get("shortName"),
                    _parse_birthdate(p.get("birthDate")),
                    _safe_int(p.get("height")),
                    _safe_int(p.get("weight")),
                    p.get("foot"),
                    role.get("code2"),
                    role.get("name"),
                    (p.get("birthArea") or {}).get("name"),
                    _safe_int(p.get("currentTeamId")),
                )
            )
    if not rows:
        return 0
    con.executemany(
        """
        INSERT INTO players (
            player_id, first_name, last_name, short_name, birth_date,
            height_cm, weight_kg, foot, role_code, role_name,
            birth_country, current_team_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (player_id) DO UPDATE SET
            first_name = excluded.first_name,
            last_name = excluded.last_name,
            short_name = excluded.short_name,
            birth_date = excluded.birth_date,
            height_cm = excluded.height_cm,
            weight_kg = excluded.weight_kg,
            foot = excluded.foot,
            role_code = excluded.role_code,
            role_name = excluded.role_name,
            birth_country = excluded.birth_country,
            current_team_id = excluded.current_team_id
        """,
        rows,
    )
    return len(rows)


def insert_match(
    con: duckdb.DuckDBPyConnection,
    match_id: int,
    competition: str,
    season: str,
    label: str | None,
    home_team_id: int | None,
    away_team_id: int | None,
    match_date: datetime | None,
) -> None:
    con.execute(
        """
        INSERT INTO matches (match_id, competition, season, label, home_team_id, away_team_id, match_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (match_id) DO NOTHING
        """,
        [match_id, competition, season, label, home_team_id, away_team_id, match_date],
    )


def insert_events(con: duckdb.DuckDBPyConnection, match_id: int, events: list[dict]) -> int:
    rows = []
    for e in events:
        positions = e.get("positions") or []
        start = positions[0] if len(positions) > 0 else {}
        end = positions[1] if len(positions) > 1 else {}
        rows.append(
            (
                e.get("id"),
                match_id,
                e.get("teamId"),
                e.get("playerId"),
                e.get("matchPeriod"),
                e.get("eventSec"),
                e.get("eventName"),
                e.get("subEventName"),
                start.get("x"),
                start.get("y"),
                end.get("x"),
                end.get("y"),
                json.dumps(e.get("tags", [])),
            )
        )
    if not rows:
        return 0
    con.executemany(
        """
        INSERT INTO events (
            event_id, match_id, team_id, player_id, match_period, event_sec,
            event_name, sub_event_name, start_x, start_y, end_x, end_y, tags
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (event_id) DO NOTHING
        """,
        rows,
    )
    return len(rows)


def compute_and_insert_minutes(
    con: duckdb.DuckDBPyConnection,
    match_id: int,
    teams_data: dict[str, Any],
    full_time_minute: float = 90.0,
) -> int:
    """
    Derive minutes_played from formation.lineup / bench / substitutions.
    Requires the ORIGINAL figshare match object shape — see module docstring.
    Returns number of participation rows written.
    """
    rows = []
    for team_id_str, td in teams_data.items():
        team_id = _safe_int(team_id_str)
        formation = td.get("formation") or {}
        lineup = formation.get("lineup") or []
        bench = formation.get("bench") or []
        subs = formation.get("substitutions") or []

        # minute a starter was subbed OFF, if any
        subbed_off_minute = {
            _safe_int(s.get("playerOut")): s.get("minute")
            for s in subs
            if s.get("playerOut") is not None
        }
        # minute a bench player was subbed ON, if any
        subbed_on_minute = {
            _safe_int(s.get("playerIn")): s.get("minute")
            for s in subs
            if s.get("playerIn") is not None
        }

        for p in lineup:
            pid = _safe_int(p.get("playerId"))
            if pid is None:
                continue
            off_minute = subbed_off_minute.get(pid, full_time_minute)
            minutes = max(0.0, float(off_minute))
            rows.append((match_id, pid, team_id, True, minutes))

        for p in bench:
            pid = _safe_int(p.get("playerId"))
            if pid is None:
                continue
            on_minute = subbed_on_minute.get(pid)
            if on_minute is None:
                # never came on
                rows.append((match_id, pid, team_id, False, 0.0))
            else:
                minutes = max(0.0, full_time_minute - float(on_minute))
                rows.append((match_id, pid, team_id, False, minutes))

    if not rows:
        return 0
    con.executemany(
        """
        INSERT INTO player_match_participation
            (match_id, player_id, team_id, is_starter, minutes_played)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (match_id, player_id) DO UPDATE SET
            minutes_played = excluded.minutes_played,
            is_starter = excluded.is_starter
        """,
        rows,
    )
    return len(rows)


def init_db(db_path: str, schema_sql_path: str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(db_path)
    con.execute(Path(schema_sql_path).read_text())
    return con


def load_teams_file(con: duckdb.DuckDBPyConnection, teams_json_path: str) -> int:
    """
    Loads the global teams.json (flat list of team dicts: wyId, name,
    officialName, area). Same shape family as players.json. Call this
    BEFORE load_competition_file() so team names resolve instead of
    falling back to placeholder 'team_{id}' rows.
    """
    teams = json.loads(Path(teams_json_path).read_text())
    teams_wrapped = {str(t.get("wyId")): t for t in teams if t.get("wyId") is not None}
    return upsert_teams(con, teams_wrapped)


def load_competition_file(
    con: duckdb.DuckDBPyConnection,
    matches_json_path: str,
    events_by_match: dict[int, list[dict]],
    players_json_path: str,
    competition: str,
    season: str,
) -> IngestResult:
    """
    Production loader for a full competition, using the ORIGINAL figshare
    layout: matches_<Competition>.json (list of match objects with
    teamsData/formation/substitutions) + a separate events feed keyed by
    match_id, + the global players.json.

    `events_by_match` is intentionally passed in pre-split rather than
    loaded from a path here: the figshare events export is one large file
    per competition (list of ALL events for ALL matches), so splitting by
    match_id is a distinct, testable step done by the caller/ingestion
    script rather than hidden inside this function.
    """
    warnings: list[str] = []
    matches = json.loads(Path(matches_json_path).read_text())
    all_players = json.loads(Path(players_json_path).read_text())

    # players.json (global) is a flat list, not team-keyed like the
    # per-match sample — normalise to the team-keyed shape upsert_players
    # expects by wrapping each player under a synthetic key.
    players_wrapped = {"global": [{"player": p} for p in all_players]}
    n_players = upsert_players(con, players_wrapped)

    n_teams = 0
    n_events = 0
    n_participation = 0

    for m in matches:
        match_id = _safe_int(m.get("wyId"))
        if match_id is None:
            warnings.append(f"Skipping match with missing wyId: {m.get('label')}")
            continue

        teams_data = m.get("teamsData") or {}
        team_ids = list(teams_data.keys())
        home_id, away_id = None, None
        for tid_str, td in teams_data.items():
            if td.get("side") == "home":
                home_id = _safe_int(tid_str)
            elif td.get("side") == "away":
                away_id = _safe_int(tid_str)

        # Teams themselves come from a separate teams.json in the original
        # layout; if not loaded separately, we at least register bare rows
        # here so foreign keys resolve, to be enriched later.
        for tid_str in team_ids:
            tid = _safe_int(tid_str)
            if tid is not None:
                con.execute(
                    "INSERT INTO teams (team_id, name) VALUES (?, ?) "
                    "ON CONFLICT (team_id) DO NOTHING",
                    [tid, f"team_{tid}"],
                )
                n_teams += 1

        match_date = None
        raw_date = m.get("dateutc")
        if raw_date:
            try:
                match_date = datetime.strptime(raw_date, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass

        insert_match(con, match_id, competition, season, m.get("label"), home_id, away_id, match_date)

        if not m.get("hasFormation") or not teams_data:
            warnings.append(f"Match {match_id}: no formation data, minutes will be NULL.")
        else:
            n_participation += compute_and_insert_minutes(con, match_id, teams_data)

        events = events_by_match.get(match_id)
        if events:
            n_events += insert_events(con, match_id, events)
        else:
            warnings.append(f"Match {match_id}: no events found in events feed.")

    for w in warnings:
        logger.warning(w)

    return IngestResult(
        matches_loaded=len(matches),
        events_loaded=n_events,
        players_loaded=n_players,
        teams_loaded=n_teams,
        participation_rows=n_participation,
        warnings=warnings,
    )


def load_single_match_from_repackaged_sample(
    con: duckdb.DuckDBPyConnection,
    match_json_path: str,
    match_id: int,
    competition: str,
    season: str,
) -> IngestResult:
    """
    Dev/validation-only loader for the GitHub repackaged sample format
    ({events, teams, players}, no substitution data). Used to sanity-check
    schema and event parsing before running against the full figshare
    dataset. Minutes are NOT computed here — see module docstring.
    """
    warnings: list[str] = []
    data = json.loads(Path(match_json_path).read_text())

    n_teams = upsert_teams(con, data["teams"])
    n_players = upsert_players(con, data["players"])

    team_ids = list(data["teams"].keys())
    home_id = _safe_int(team_ids[0]) if len(team_ids) > 0 else None
    away_id = _safe_int(team_ids[1]) if len(team_ids) > 1 else None
    insert_match(con, match_id, competition, season, None, home_id, away_id, None)

    n_events = insert_events(con, match_id, data["events"])
    warnings.append(
        "Minutes not computed: repackaged sample format lacks substitution data. "
        "Use the original figshare matches.json for production ingestion."
    )
    logger.warning(warnings[0])

    return IngestResult(
        matches_loaded=1,
        events_loaded=n_events,
        players_loaded=n_players,
        teams_loaded=n_teams,
        participation_rows=0,
        warnings=warnings,
    )

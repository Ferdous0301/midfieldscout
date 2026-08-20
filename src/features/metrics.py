"""
Implementations of the five v1 CM fit-scoring metrics.
Each function's docstring formula must match docs/phase4_metrics.md
exactly — that file is the source of truth; this is the implementation.

All functions return a DataFrame keyed by player_id (one row per
player, aggregated across whatever matches are currently loaded in the
DB — season-level aggregation is the caller's responsibility via which
match_ids/competition/season filters are applied upstream).
"""
from __future__ import annotations

import duckdb
import pandas as pd

PROGRESSIVE_THRESHOLD = 10.0      # pitch units, 0-100 scale
FINAL_THIRD_X = 66.7
PRESSURE_TIME_WINDOW = 2.0        # seconds
PRESSURE_DIST = 5.0                # pitch units


def progressive_pass_pct(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    Metric 1: share of accurate passes that move the ball >= 10 pitch
    units upfield. See docs/phase4_metrics.md #1.
    """
    query = f"""
        SELECT
            player_id,
            count(*) FILTER (
                WHERE sub_event_name IS NOT NULL
                  AND tags LIKE '%1801%'
                  AND (end_x - start_x) >= {PROGRESSIVE_THRESHOLD}
            ) AS progressive_passes,
            count(*) AS total_passes,
            CASE WHEN count(*) > 0
                 THEN count(*) FILTER (
                        WHERE tags LIKE '%1801%'
                          AND (end_x - start_x) >= {PROGRESSIVE_THRESHOLD}
                      )::DOUBLE / count(*)
                 ELSE NULL END AS progressive_pass_pct
        FROM events
        WHERE event_name = 'Pass'
        GROUP BY player_id
    """
    return con.execute(query).fetchdf()


def final_third_entries(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    Metric 3: accurate passes ending in the attacking third, starting
    outside it. See docs/phase4_metrics.md #3.
    """
    query = f"""
        SELECT
            player_id,
            count(*) FILTER (
                WHERE tags LIKE '%1801%'
                  AND end_x >= {FINAL_THIRD_X}
                  AND start_x < {FINAL_THIRD_X}
            ) AS final_third_entries
        FROM events
        WHERE event_name = 'Pass'
        GROUP BY player_id
    """
    return con.execute(query).fetchdf()


def defensive_actions_per90(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    Metric 4: interceptions + won defensive duels, normalized per 90.
    Requires player_match_participation.minutes_played to be populated
    (Phase 2). See docs/phase4_metrics.md #4.
    """
    query = """
        WITH def_events AS (
            SELECT player_id, match_id, count(*) AS n
            FROM events
            WHERE (sub_event_name = 'Ground defending duel' AND tags LIKE '%703%')
               OR tags LIKE '%1401%'
            GROUP BY player_id, match_id
        ),
        minutes AS (
            SELECT player_id, sum(minutes_played) AS total_minutes
            FROM player_match_participation
            WHERE minutes_played IS NOT NULL
            GROUP BY player_id
        )
        SELECT
            m.player_id,
            coalesce(sum(d.n), 0) AS defensive_actions,
            CASE WHEN m.total_minutes > 0
                 THEN coalesce(sum(d.n), 0) / (m.total_minutes / 90.0)
                 ELSE NULL END AS defensive_actions_per90
        FROM minutes m
        LEFT JOIN def_events d ON d.player_id = m.player_id
        GROUP BY m.player_id, m.total_minutes
    """
    return con.execute(query).fetchdf()


def turnover_rate(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    Metric 5: share of on-ball events tagged inaccurate (1802) or
    dangerous_ball_lost (2001). Reported as two separate rates per
    docs/phase4_metrics.md #5 — NOT blended into one number.
    """
    query = """
        SELECT
            player_id,
            count(*) AS total_onball_events,
            count(*) FILTER (WHERE tags LIKE '%1802%') AS inaccurate_events,
            count(*) FILTER (WHERE tags LIKE '%2001%') AS dangerous_losses,
            CASE WHEN count(*) > 0
                 THEN count(*) FILTER (WHERE tags LIKE '%1802%')::DOUBLE / count(*)
                 ELSE NULL END AS inaccurate_rate,
            CASE WHEN count(*) > 0
                 THEN count(*) FILTER (WHERE tags LIKE '%2001%')::DOUBLE / count(*)
                 ELSE NULL END AS dangerous_loss_rate
        FROM events
        WHERE player_id IS NOT NULL
        GROUP BY player_id
    """
    return con.execute(query).fetchdf()


def pressure_completion(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    DEPRECATED / NOT USED IN v1 — kept for documentation purposes only.

    Validated against real match data (2499841) and found empirically
    non-viable: within a +-2s window, the closest opposing Duel to any
    Pass event was ~20 pitch units away, never under the originally
    specified 5-unit threshold. Even loosening to 25 units matched
    ~1% of candidates. See docs/phase4_metrics.md #2 for the full
    writeup. Do not call this from build_metric_table.
    """
    query = f"""
        WITH passes AS (
            SELECT event_id, player_id, team_id, match_id, match_period,
                   event_sec, start_x, start_y, tags
            FROM events
            WHERE event_name = 'Pass'
        ),
        duels AS (
            SELECT match_id, match_period, team_id, event_sec, start_x, start_y
            FROM events
            WHERE event_name = 'Duel'
        ),
        pressured_passes AS (
            SELECT DISTINCT p.event_id, p.player_id, p.tags
            FROM passes p
            JOIN duels d
              ON d.match_id = p.match_id
             AND d.match_period = p.match_period
             AND d.team_id != p.team_id
             AND abs(d.event_sec - p.event_sec) <= {PRESSURE_TIME_WINDOW}
             AND sqrt(pow(d.start_x - p.start_x, 2) + pow(d.start_y - p.start_y, 2)) <= {PRESSURE_DIST}
        )
        SELECT
            player_id,
            count(*) AS pressured_passes,
            count(*) FILTER (WHERE tags LIKE '%1801%') AS pressured_accurate,
            CASE WHEN count(*) > 0
                 THEN count(*) FILTER (WHERE tags LIKE '%1801%')::DOUBLE / count(*)
                 ELSE NULL END AS pressure_completion_pct
        FROM pressured_passes
        GROUP BY player_id
    """
    return con.execute(query).fetchdf()


def build_metric_table(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    Joins the four v1-viable metrics into one player-level table.
    Metric 2 (pressure completion) is excluded — see pressure_completion()
    docstring and docs/phase4_metrics.md #2 for why it was dropped after
    real-data validation.

    Left-joined on progressive_pass_pct's player set as the base (any
    player with at least one pass); players with no passes at all are
    excluded, which is reasonable for a CM candidate pool but should be
    sanity-checked once real season data is loaded (are we silently
    dropping anyone who should be in scope?).
    """
    m1 = progressive_pass_pct(con)
    m3 = final_third_entries(con)
    m4 = defensive_actions_per90(con)
    m5 = turnover_rate(con)

    out = m1.merge(m3, on="player_id", how="left")
    out = out.merge(m4, on="player_id", how="left")
    out = out.merge(m5, on="player_id", how="left")
    return out
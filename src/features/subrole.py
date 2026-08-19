"""
Sub-role classification for players tagged role_code == 'MD' (Wyscout's
coarse midfielder bucket covers CM, CDM, CAM, LM, RM indiscriminately).

METHOD (documented per Phase 4 requirements — define before implement):

Definition:
    A player's sub-role for a given season is estimated from the
    minutes-weighted centroid and spread of their own on-ball event
    locations (start_x, start_y), using Wyscout's 0-100 pitch coordinate
    system (0 = own goal line, 100 = opponent's goal line; y: 0-100
    left-to-right from the team's attacking perspective).

Formula:
    centroid_x = sum(start_x * event_weight) / sum(event_weight)
    centroid_y = sum(start_y * event_weight) / sum(event_weight)
    where event_weight = 1 for every on-ball event in matches where the
    player is tagged role_code == 'MD' (all events weighted equally;
    no shot/pass distinction at this stage).

    lateral_spread = std(start_y) over the player's events, as a proxy
    for how central vs. wide their involvement is.

Classification rule (v1, heuristic thresholds — NOT a trained model):
    - centroid_y within [35, 65]  (central third of pitch width)
      AND lateral_spread < 20      -> "CM" (central midfielder)
    - centroid_y within [35, 65] AND centroid_x < 45 -> "CDM"
    - centroid_y within [35, 65] AND centroid_x > 60 -> "CAM"
    - otherwise                    -> "WIDE_MID" (LM/RM)

Inputs:
    - events table (start_x, start_y, player_id, event_name)
    - players table (role_code, filtered to 'MD')

Assumptions:
    - Average positioning across a season is a reasonable, if imperfect,
      proxy for tactical role. A CM used as a temporary winger in a few
      matches will be pulled toward that average; this is a known
      limitation, not corrected for in v1.
    - No possession-adjustment: a player at a possession-dominant club
      naturally has more events, but this affects sample size, not
      centroid location directly.
    - Thresholds (35/65, 45, 60, spread 20) are heuristic starting
      points based on visual inspection of pitch-third boundaries, NOT
      fitted or validated against ground truth. This must be stated
      as a limitation in the report, not presented as calibrated.

Limitations:
    - Untrained heuristic, not a classifier in the ML sense. Appropriate
      for a defensible v1; a natural stretch goal (Phase 6/8) is to
      replace this with k-means clustering over (centroid_x, centroid_y,
      spread, pass-direction ratio) and validate cluster labels against
      a small hand-labeled sample of well-known players.

Why relevant to the recruitment problem:
    Restricting the candidate pool to true central midfielders (not all
    Wyscout-tagged 'MD' players) is required before any fit-scoring can
    be meaningful, since a winger and a CDM should never compete on the
    same shortlist.
"""
from __future__ import annotations

from dataclasses import dataclass

import duckdb


@dataclass(frozen=True)
class SubRoleEstimate:
    player_id: int
    n_events: int
    centroid_x: float
    centroid_y: float
    lateral_spread: float
    sub_role: str


def classify_midfield_subroles(
    con: duckdb.DuckDBPyConnection,
    min_events: int = 200,
) -> list[SubRoleEstimate]:
    """
    Compute sub-role estimates for all players tagged role_code == 'MD'.
    `min_events` is a reliability floor: players with few recorded events
    get an unreliable centroid and should be excluded or flagged with low
    confidence downstream (see Phase 11 — confidence is separate from score).
    """
    rows = con.execute(
        """
        SELECT
            e.player_id,
            count(*)                        AS n_events,
            avg(e.start_x)                  AS centroid_x,
            avg(e.start_y)                  AS centroid_y,
            stddev_samp(e.start_y)          AS lateral_spread
        FROM events e
        JOIN players p ON p.player_id = e.player_id
        WHERE p.role_code = 'MD'
          AND e.start_x IS NOT NULL
          AND e.start_y IS NOT NULL
        GROUP BY e.player_id
        HAVING count(*) >= ?
        """,
        [min_events],
    ).fetchall()

    results = []
    for player_id, n_events, cx, cy, spread in rows:
        spread = spread if spread is not None else 0.0
        sub_role = _classify(cx, cy, spread)
        results.append(
            SubRoleEstimate(
                player_id=player_id,
                n_events=n_events,
                centroid_x=cx,
                centroid_y=cy,
                lateral_spread=spread,
                sub_role=sub_role,
            )
        )
    return results


def _classify(centroid_x: float, centroid_y: float, lateral_spread: float) -> str:
    is_central = 35 <= centroid_y <= 65
    if is_central and lateral_spread < 20:
        return "CM"
    if is_central and centroid_x < 45:
        return "CDM"
    if is_central and centroid_x > 60:
        return "CAM"
    return "WIDE_MID"

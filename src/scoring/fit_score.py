"""
Phase 5 (context adjustment) + Phase 7 (fit scoring), combined since
scoring depends directly on the reliability modifier.

DESIGN (per project's define-before-implement principle):

Candidate pool definition:
    A player qualifies for the CM shortlist if, across the 2017/18
    season pool (or whichever competitions are loaded):
      - sub_role == 'CM' (from features/subrole.py, min_events applied)
      - age at 2017-08-01 (season start proxy) <= configs/paths.yaml
        case_study.max_age
      - total minutes_played >= case_study.min_minutes

Reliability modifier (Phase 5):
    Raw metrics computed on few minutes are noisy. Rather than exclude
    borderline-sample players outright (min_minutes is a hard floor,
    not a smoothing mechanism), apply empirical-Bayes-style shrinkage:
    a player's metric value is pulled toward the population mean in
    proportion to how far below a "trusted" minutes threshold they are.

    shrinkage_weight = min(1.0, minutes_played / trusted_minutes)
    adjusted_value = shrinkage_weight * raw_value
                      + (1 - shrinkage_weight) * population_mean

    trusted_minutes defaults to 1800 (~20 full matches) — a player at
    that volume or above is trusted at face value; below it, their
    score is progressively pulled toward the mean rather than let a
    3-match hot streak dominate the shortlist.

Fit score (Phase 7):
    A simple, transparent weighted sum over min-max normalized,
    reliability-adjusted metrics. NOT a trained/fitted model — weights
    are stated design choices, documented here, open to justified
    revision, not derived from opaque optimization.

    fit_score = sum(weight_i * normalized_adjusted_metric_i)

    Default weights (v1, CM possession-profile brief):
        progressive_pass_pct:      0.30
        final_third_entries_p90:   0.20
        defensive_actions_per90:   0.30
        inaccurate_rate (inverted):0.20
    These sum to 1.0 and are a starting point tied to the stated case
    study ("possession-based club... progressive passing... defensive
    contribution"), not a claim of optimality. Phase 11 (explainability)
    surfaces each player's per-metric contribution so the weighting
    choice is inspectable, not a black box.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import duckdb
import pandas as pd

DEFAULT_WEIGHTS = {
    "progressive_pass_pct": 0.30,
    "final_third_entries_p90": 0.20,
    "defensive_actions_per90": 0.30,
    "inaccurate_rate_inverted": 0.20,
}

TRUSTED_MINUTES = 1800.0


def compute_age(birth_date, as_of: date) -> float | None:
    if birth_date is None or pd.isnull(birth_date):
        return None
    # DuckDB's fetchdf() returns birth_date as pandas Timestamp, not a
    # plain datetime.date — normalize so subtraction always works
    # regardless of caller (tested with both types after this bug was
    # caught against real Kaggle data).
    if hasattr(birth_date, "date"):
        birth_date = birth_date.date()
    days = (as_of - birth_date).days
    return days / 365.25


def build_candidate_pool(
    con: duckdb.DuckDBPyConnection,
    subrole_df: pd.DataFrame,
    max_age: int,
    min_minutes: float,
    season_start: date = date(2017, 8, 1),
) -> pd.DataFrame:
    """
    Joins sub-role estimates with player metadata and total minutes,
    applies the age + minutes gates. Returns one row per qualifying
    player-competition-pool (assumes subrole_df/minutes are already
    aggregated across whichever matches are loaded — caller's choice
    of scope, e.g. single league vs all five).
    """
    cm_players = subrole_df[subrole_df["sub_role"] == "CM"]["player_id"].tolist()
    if not cm_players:
        return pd.DataFrame()

    placeholders = ",".join(str(p) for p in cm_players)
    meta = con.execute(f"""
        SELECT p.player_id, p.first_name, p.last_name, p.birth_date,
               p.current_team_id,
               coalesce(m.total_minutes, 0) AS total_minutes
        FROM players p
        LEFT JOIN (
            SELECT player_id, sum(minutes_played) AS total_minutes
            FROM player_match_participation
            WHERE minutes_played IS NOT NULL
            GROUP BY player_id
        ) m ON m.player_id = p.player_id
        WHERE p.player_id IN ({placeholders})
    """).fetchdf()

    meta["age"] = meta["birth_date"].apply(
        lambda bd: compute_age(bd, season_start) if pd.notnull(bd) else None
    )

    qualified = meta[
        (meta["age"].notnull())
        & (meta["age"] <= max_age)
        & (meta["total_minutes"] >= min_minutes)
    ].copy()

    qualified["low_sample"] = qualified["total_minutes"] < TRUSTED_MINUTES
    return qualified


def _shrink(raw: pd.Series, minutes: pd.Series, trusted_minutes: float = TRUSTED_MINUTES) -> pd.Series:
    pop_mean = raw.mean()
    weight = (minutes / trusted_minutes).clip(upper=1.0)
    return weight * raw + (1 - weight) * pop_mean


def _minmax(s: pd.Series) -> pd.Series:
    lo, hi = s.min(), s.max()
    if hi == lo:
        return pd.Series([0.5] * len(s), index=s.index)
    return (s - lo) / (hi - lo)


@dataclass
class ScoringResult:
    table: pd.DataFrame
    weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))


def compute_fit_scores(
    candidate_pool: pd.DataFrame,
    metrics_df: pd.DataFrame,
    weights: dict | None = None,
) -> ScoringResult:
    """
    candidate_pool: output of build_candidate_pool (player_id, total_minutes, low_sample, ...)
    metrics_df: output of features.metrics.build_metric_table (raw per-player metrics)
    """
    weights = weights or DEFAULT_WEIGHTS
    assert abs(sum(weights.values()) - 1.0) < 1e-6, "weights must sum to 1.0"

    df = candidate_pool.merge(metrics_df, on="player_id", how="left", suffixes=("", "_metric_dup"))
    dup_cols = [c for c in df.columns if c.endswith("_metric_dup")]
    if dup_cols:
        raise ValueError(
            f"Column collision between candidate_pool and metrics_df: {dup_cols}. "
            f"metrics_df should only contain player_id + metric columns, not fields "
            f"already present in candidate_pool (e.g. total_minutes)."
        )

    # derive final_third_entries_p90 (raw metric table has counts, not per-90)
    df["final_third_entries_p90"] = (
        df["final_third_entries"] / (df["total_minutes"] / 90.0)
    ).replace([float("inf"), -float("inf")], None)

    # invert inaccurate_rate so higher = better, consistent with other metrics
    df["inaccurate_rate_inverted"] = 1 - df["inaccurate_rate"]

    metric_cols = [
        "progressive_pass_pct",
        "final_third_entries_p90",
        "defensive_actions_per90",
        "inaccurate_rate_inverted",
    ]

    for col in metric_cols:
        df[col] = df[col].fillna(df[col].mean())
        df[f"{col}_adj"] = _shrink(df[col], df["total_minutes"])
        df[f"{col}_norm"] = _minmax(df[f"{col}_adj"])
        df[f"{col}_contribution"] = df[f"{col}_norm"] * weights[col]

    df["fit_score"] = sum(df[f"{c}_contribution"] for c in metric_cols)

    df = df.sort_values("fit_score", ascending=False).reset_index(drop=True)
    return ScoringResult(table=df, weights=weights)
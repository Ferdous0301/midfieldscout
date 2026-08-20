"""
Phase 12: generates a markdown recruitment report from a ScoringResult.
Deliberately markdown, not docx/pdf — this is an internal analytical
deliverable, not a client-facing formal document (see file_creation
guidance: markdown is the right default unless a Word doc is explicitly
requested).
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from scoring.fit_score import ScoringResult


def generate_report(
    result: ScoringResult,
    competition_scope: str,
    top_n: int = 15,
) -> str:
    df = result.table.head(top_n)

    lines = [
        f"# CM Recruitment Shortlist — {competition_scope}",
        "",
        f"Generated {date.today().isoformat()}. Simulated brief: possession-based "
        f"club seeking a central midfielder, U23, 2017/18 season.",
        "",
        "## Methodology summary",
        "",
        "Candidates are central midfielders as classified by event-location "
        "clustering (not source metadata alone — see `src/features/subrole.py`), "
        "filtered by age and minimum minutes played, then scored on 4 metrics "
        "with reliability shrinkage applied for low-minute samples "
        "(see `src/scoring/fit_score.py` docstring for full formulas).",
        "",
        "**Weights used:**",
        "",
    ]
    for k, v in result.weights.items():
        lines.append(f"- `{k}`: {v}")

    lines += [
        "",
        "**Known limitations** (stated explicitly, not omitted):",
        "- Pass-completion-under-pressure metric was dropped after real-data "
        "validation showed it was not viable with Wyscout's event structure "
        "(see `docs/phase4_metrics.md` #2).",
        "- Ball-carrying/dribble progression is not captured (Wyscout has no "
        "carry event type) — see `docs/stretch_dribble_reconstruction.md`.",
        "- Sub-role classification is a heuristic based on average event "
        "location, not a validated/trained classifier.",
        "",
        "## Shortlist",
        "",
        "| Rank | Player | Age | Minutes | Fit Score | Low Sample? |",
        "|---|---|---|---|---|---|",
    ]

    for i, row in df.iterrows():
        name = f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()
        lines.append(
            f"| {i+1} | {name} | {row['age']:.1f} | {row['total_minutes']:.0f} | "
            f"{row['fit_score']:.3f} | {'Yes' if row['low_sample'] else 'No'} |"
        )

    lines += [
        "",
        "## Per-metric breakdown (top 5)",
        "",
    ]
    metric_cols = [c for c in df.columns if c.endswith("_contribution")]
    for i, row in df.head(5).iterrows():
        name = f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()
        lines.append(f"**{name}** (fit_score={row['fit_score']:.3f})")
        for mc in metric_cols:
            metric_name = mc.replace("_contribution", "")
            lines.append(f"  - {metric_name}: {row[mc]:.3f} contribution")
        lines.append("")

    return "\n".join(lines)

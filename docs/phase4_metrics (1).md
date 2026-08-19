# CM Fit-Scoring Metrics (v1)

Grounded against real data: sub-event names confirmed from an actual
match file (`sample_match_2499841.json`); tag id -> meaning mapping
confirmed against `socceraction`'s Wyscout converter (ML-KULeuven,
published research library), not guessed. Tag 1801/1802 = accurate/not
accurate is also independently confirmed in the original Nature paper
(Pappalardo et al. 2019).

Every metric below is defined BEFORE any implementation, per the
project's stated principle: definition -> formula -> data source ->
assumptions -> limitations. None are implemented yet.

---

## 1. Progressive Pass %
**Definition**: share of a player's own-team passes that move the ball
meaningfully upfield, regardless of whether they're "successful" line-
breaking passes in the technical sense — Wyscout has no line-breaking
tag, so this is a distance/direction proxy.
**Formula**: `count(passes where accurate AND (end_x - start_x) >= 10) / count(all passes)`
(10 units on the 0-100 pitch scale is the threshold; will be validated,
not just assumed — see Limitations.)
**Source**: `events` where `event_name = 'Pass'`, tag 1801 (accurate),
`start_x`/`end_x`.
**Assumptions**: pitch coordinates are consistent 0-100 regardless of
team attacking direction (Wyscout normalizes this per-team already —
confirmed in the paper's field description).
**Limitations**: distance-based proxy, not True progressive-pass logic
(e.g. StatsBomb-style zone-entry definitions). Must state this openly,
not call it "progressive passes" without qualification in the report.

## 2. Pass Completion Under Pressure — **REMOVED FROM v1 (empirically non-viable)**
**Original definition** (as first specified): accurate-pass rate for
passes made within ±2s and 5 pitch units of an opposing Duel event.

**Why removed**: validated against real match data
(`2499841 - Huddersfield - Man City`), not just reasoned about in the
abstract. Within the ±2s time window, the CLOSEST any opposing Duel got
to a Pass event was ~20 pitch units — never under 5. Loosening the
threshold to 25 units (half the pitch width — no longer a meaningful
"pressure" definition) still only matched 1 of 102 candidate pairs.
Wyscout also has no native pressure/duel-context tag (confirmed against
`socceraction`'s full tag mapping) to fall back on. The likely reason:
Duel and Pass are logged as distinct sequential events, not concurrent
ones — a duel contesting a specific pass typically IS the next event,
not a nearby-in-time-and-space second event, so spatial-proximity
joining doesn't capture what "pressure" actually looks like in this
event stream.

**Decision**: dropped from v1 rather than kept with a fudged threshold
that returns near-zero signal. This is reported here as a real, tested
finding for the methodology section — "we attempted a pressure proxy,
validated it against real data, and found it empirically unsupportable
with event-only data; this is a known limitation of event data vs.
StatsBomb-style tracking-adjacent tagging" is a stronger, more credible
statement than a working-looking metric with fabricated signal.

**v1 replacement**: none. CM fit-scoring proceeds on 4 metrics (1, 3,
4, 5), not 5. If pursued later, the honest path is StatsBomb's actual
pressure tags on a StatsBomb-sourced supplementary sample (Phase 0's
originally-scoped optional cross-check data), not a re-attempted proxy
on Wyscout.


## 3. Final-Third Entries
**Definition**: successful passes or carries into the attacking third.
**Formula**: `count(accurate passes where end_x >= 66.7 AND start_x < 66.7)`
**Source**: `events`, Pass, tag 1801.
**Limitations**: Wyscout doesn't have a distinct "carry" event type the
way StatsBomb does — dribble-like progression must be inferred from
consecutive `Touch`/duel-won sequences by the same player, which is a
stretch item, not v1.

## 4. Defensive Actions per 90
**Definition**: recoveries, interceptions, and won defensive duels,
normalized per 90 minutes.
**Formula**: `(count(Interception) + count(Duel, sub_event contains
'defending', tag 703 won)) / (minutes_played / 90)`
**Source**: `events` (sub_event_name = 'Ground defending duel', tag 1401
interception), `player_match_participation.minutes_played`.
**Assumptions**: relies on `minutes_played` being correctly computed —
this is why Phase 2's minutes validation mattered before this phase.
**Limitations**: does not capture positioning-based defensive value
(e.g. blocking passing lanes without a recorded action) — an inherent
limitation of event data vs. tracking data.

## 5. Turnover Rate
**Definition**: share of a player's own-ball involvements that result
in possession loss.
**Formula**: `count(events, tag 1802 not_accurate OR tag 2001
dangerous_ball_lost) / count(all on-ball events)`
**Source**: `events`, tags 1802 and 2001.
**Limitations**: some "inaccurate" events are low-risk (e.g. a
speculative long ball) vs. genuinely costly turnovers (tag 2001 is
meant to capture the latter specifically) — the two should be reported
separately, not blended into one number, to avoid misleading fit scores.

## 6. Minutes-Weighted Reliability Flag (not a metric — a modifier)
Every metric above must be paired with a `minutes_played` total for
that player-season. Players below `min_minutes` (900, per
`configs/paths.yaml`) get a `low_sample` flag carried through to
Phase 11 (explainability) rather than being silently dropped or
silently trusted — matches this project's stated principle of surfacing
small-sample risk instead of hiding it.

---

## What's deliberately excluded from v1
- xT (expected threat) and VAEP: real methodologies, but implementing a
  credible version requires possession-chain modeling beyond this
  project's honest scope. If added later (stretch), use `socceraction`'s
  published implementation and cite it — do not reimplement from scratch
  and call it VAEP.
- Carries/dribble progression: no clean event type for it in Wyscout;
  would require heuristic reconstruction with meaningfully uncertain
  accuracy.
- Aerial/physical metrics: Wyscout event data has no physical/tracking
  layer; any "athleticism" claim would be unsupported by this dataset
  and should not appear in the final scoring model.

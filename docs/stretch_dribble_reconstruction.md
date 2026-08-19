# Stretch Item: Heuristic Dribble/Carry Reconstruction

Status: SCOPED, NOT IMPLEMENTED. Build only after the v1 core (Phases
2-7, 9-12 per the agreed cut list) is working end-to-end. This document
exists so the idea is specified now, while the schema is fresh, rather
than reverse-engineered later.

## Why this exists
Wyscout has no "carry" or "dribble" event type (unlike StatsBomb). A
progressive-carrying CM (e.g. someone who drives forward on the ball
rather than only passing) is invisible to Metric 3 (Final-Third
Entries) as currently defined — that metric only counts passes. This
under-values a real, common CM archetype, so it's worth reconstructing
even heuristically, rather than silently excluding it.

## Definition
A "carry" is inferred as: the same player producing two consecutive
on-ball events (any event type) within a short time window, where the
ball's location moved meaningfully between the end of event N and the
start of event N+1 — i.e., the player kept possession and moved with
it, rather than the ball changing hands.

## Formula (heuristic reconstruction, not a Wyscout-native event)
For consecutive events `e1`, `e2` in the same match, same player:
```
carry_distance = euclidean(e1.end_x, e1.end_y, e2.start_x, e2.start_y)
carry_time     = e2.event_sec - e1.event_sec

is_carry ⟺  same player_id
            AND same team_id
            AND 0 < carry_time <= 5 seconds
            AND carry_distance >= 5 pitch units
            AND no intervening event from a different player
```
`progressive_carry ⟺ is_carry AND (e2.start_x - e1.end_x) >= 10`
(same +10 progressive threshold as Metric 1, for consistency).

## Data source
`events` table only — no new raw data needed, since this is entirely
derived from existing `start_x/y`, `end_x/y`, `event_sec`, `player_id`.
Requires events to be strictly ordered by `(match_id, match_period,
event_sec)`, which the current schema supports but the loader does not
yet explicitly guarantee via an index — add one before implementing
this.

## Assumptions
- Gaps in the event stream (e.g. a foul or throw-in between two
  otherwise-carry-like events) should NOT count as carries — the
  "no intervening event from a different player" clause exists for
  this, but interruption-type events (Foul, Offside) by the SAME team
  that don't represent a real ball-in-play gap need special-casing,
  not yet resolved here.
- 5-second / 5-unit thresholds are arbitrary starting points, same
  status as Metric 1/2's thresholds: heuristic, not fitted or validated
  against ground truth.

## Limitations (to state plainly if/when built)
- This is a proxy for ball-carrying, not a verified carry detector. It
  will conflate genuine dribbles with things like a player receiving a
  pass, taking a touch, then passing again from nearly the same spot
  (false positive) — and will miss carries interrupted by a stoppage
  that resumes with the same player (false negative).
- No public precedent to benchmark against, since this reconstruction
  is not a standard method (unlike xT/VAEP, which have published
  reference implementations). This should be labeled clearly as an
  original heuristic, not cited as an established technique.

## Build trigger
Only implement after: (a) v1 core CM shortlist + Phase 9 validation are
working on Metrics 1-5, and (b) there is time remaining per the
project's own scope-protection priority (Phase 9 > everything else).
If time runs short, this stays documented-but-unbuilt and gets listed
honestly as future work in the final report — not silently dropped.

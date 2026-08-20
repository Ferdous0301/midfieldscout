# Phase 9: Historical Validation Plan

Status: SCOPED, not yet implemented — depends on the shortlist existing
first (needs all 5 leagues loaded + fit scores computed).

## Why this phase is protected (per earlier scope discussion)
This is the phase that separates a real analytical exercise from a
plausible-looking scoring model with no accountability. Almost no
portfolio project actually checks whether its own recommendations held
up. This one will.

## Method
1. Take the top ~15-20 ranked CM candidates from the 2017/18 fit-score
   shortlist (age <=23 at the time).
2. For each, manually source (not scraped — small N, done by hand,
   citing sources) their subsequent career path through roughly 2020-21:
   - Did they move to a "bigger" club (defined via league tier +
     European competition participation, stated explicitly)?
   - Minutes played in the following 2-3 seasons at their new/existing
     club.
   - Highest competition level reached (domestic league, European
     competition, senior national team).
3. Build a simple, stated **outcome proxy score** (e.g. 0-3 scale:
   stayed same level / moved up one tier / moved up multiple tiers or
   became a regular starter at a top-5-league club / became a full
   international).
4. Compare fit_score rank against outcome proxy — Spearman correlation
   is the appropriate stat (ordinal, not assuming linear relationship),
   reported plainly with confidence caveats given small N (~15-20 is
   not enough for a strong claim, and that must be stated, not hidden).

## Deliberate limitations to state in the report, not hide
- **Survivorship bias**: only the shortlisted players are checked;
  players NOT shortlisted who also succeeded are not part of this
  comparison, so this validates "did our picks do well" not "would we
  have beaten an unshortlisted alternative." A real precision/recall
  test against a full known-outcome dataset is out of scope for a
  solo project with this data.
- **Confound, not causation**: a player improving after 2017/18 may be
  due to factors the model can't see (coaching, injury luck, tactical
  fit) — outcome correlation is suggestive, not proof the scoring
  model "works" in a causal sense.
- **Small N**: 15-20 players is enough to show the exercise was done
  honestly, not enough for statistical significance claims. State the
  correlation with its limitations, not as a headline "X% accurate"
  claim.
- **Outcome-proxy scale is a judgment call**: document the specific
  criteria used for each proxy tier so it's reproducible/inspectable,
  not an ad hoc score.

## Data sourcing for this phase
Manual lookup (Wikipedia transfer history, Transfermarkt for reference
only — cite as source, don't scrape), done once for ~15-20 players.
This is explicitly NOT automated, and that's a deliberate, stated
choice: automating scraping of a site with restrictive terms for 15-20
lookups is not worth the legal/reproducibility risk for the benefit
gained, and manual sourcing is fully transparent/citable.

## Trigger to implement
Once `fit_score.py` has run against the full 5-league candidate pool
and produced a real ranked shortlist (not synthetic test data).

"""Declared context-RULE-CONFORMANCE grading -- a second, separate yardstick from `labels.py`'s
relevance grade, but NOT an independent validation of the ranker's rain nudge. Read
`docs/adr/0003-relevance-vs-context-appropriateness.md` before using a metric built from this
module in an argument.

Relevance (`labels.grade_candidate`) answers "does this suit what the person asked for and has
liked before?" from a persona brief that is never told about the weather -- by design (see
`dataset.py`'s module docstring on information asymmetry). This module answers a different
question: "does the ranker's output conform to a declared rain/environment rule?" A gardening
session can be an excellent match on the first question and score badly on the second when it is
raining. Grading both from the SAME rule would make one of them meaningless; that conflation is
what made a real, deliberate context nudge in the ranker (`activity_search.py`'s `context` factor,
F35) look like a regression on a relevance benchmark that was never told it was raining.

IMPORTANT LIMITATION, stated plainly because it is easy to miss: this rule is NOT independent of
the thing it is used to check. `grade_context_fit` deliberately restates the SAME rain/environment
premise `activity_search.score_candidate`'s own `context_fit` encodes (rain + environment left
open + outdoors is treated as a worse fit; an explicit environment ask overrides the forecast) --
it just does so without importing or calling `activity_search`, so a coding bug in one is not
automatically hidden by the other. That is a weaker property than genuine independence: a metric
built from this rule (`context_rule_conformance_at_3`) can only show whether the ranker's
`context` factor is wired and behaves as this module declares it should. It CANNOT show that the
declared rule is itself a good idea -- checking that would require a judgement authored from a
source other than the ranker's own premise (e.g. per-listing shelter/weather-sensitivity facts
added to the dataset independently of the score, or a human-authored per-case appropriateness
call). See the ADR's "What would change our mind" for this as a named follow-up.

Grades (highest applicable rule wins):

  2  GOOD_FIT      no rain in the forecast, OR the person explicitly asked for an environment
                    (a stated ask about indoor/outdoor is a stronger signal than weather and is
                    honoured regardless of it -- the same asymmetry `activity_search.
                    score_candidate` encodes for its own rain nudge: `rain_forecast` never
                    applies when `intent.environment != EITHER`)
  1  UNKNOWN_FIT    rain in the forecast, the person left the environment open, and the listing
                    does not say whether it is under cover
  0  POOR_FIT       rain in the forecast, the person left the environment open, and the listing
                    is outdoors

NOT_USER_TRUTH: like everything else in this package, this rule is an authored evaluation
convention for this benchmark, not a real weather-safety policy and not a claim about any real
listing. It exists to check that the context factor conforms to what it is declared to do,
separate from whether it matched a persona's taste -- not to validate the rule's own merit.
"""

from __future__ import annotations

from silverloop.models import ActivityCandidate, ActivityEnvironment, ActivityIntent, IndoorOutdoor

CONTEXT_POOR_FIT = 0
CONTEXT_UNKNOWN_FIT = 1
CONTEXT_GOOD_FIT = 2


def grade_context_fit(
    candidate: ActivityCandidate, intent: ActivityIntent, *, rain_forecast: bool
) -> int:
    """One candidate's conformance (0-2) to the declared context rule above, for one case.

    A pure function of `candidate.indoor_outdoor`, `intent.environment` and `rain_forecast`
    alone -- never of a persona, a preference store, or a value `activity_search` computed. It
    does not import or call `activity_search`, but see the module docstring: it still shares that
    module's `context` factor's premise by construction, so this is a conformance check, not an
    independent judgement.
    """
    if not rain_forecast or intent.environment != ActivityEnvironment.EITHER:
        return CONTEXT_GOOD_FIT
    if candidate.indoor_outdoor == IndoorOutdoor.OUTDOOR:
        return CONTEXT_POOR_FIT
    if candidate.indoor_outdoor == IndoorOutdoor.UNKNOWN:
        return CONTEXT_UNKNOWN_FIT
    return CONTEXT_GOOD_FIT

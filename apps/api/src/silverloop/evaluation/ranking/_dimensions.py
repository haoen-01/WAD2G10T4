"""How a `PreferenceDimension` maps onto a candidate, for the evaluation harness.

This used to be an evaluation-only *copy* of `preferences._candidate_dimension_value`, written
that way so the package would depend on nothing private. The cost was a hand-copied 2000 m
distance threshold and a hand-copied set of time-of-day boundaries, with the seam documented as
accepted risk: "if a future change moves either constant there, this module will silently
disagree with production about where the near/far or morning/afternoon line falls."

That change came. DISTANCE became ordinal -- a ceiling in metres, not a near/far bucket -- and a
copy that still bucketed at 2000 m would have gone on grading the whole dataset against a rule the
ranker no longer applies, with every metric in the artifact still reading as if it were measuring
the product. The copy is gone; this re-exports the production helper.

The discipline the copy existed to protect is worth keeping, so it is stated rather than enforced
by duplication: this module is used only to (a) grade a candidate against a persona's authored
BRIEF (`labels.py`) and (b) decide which persona pairs are comparable (`runner.py`). It is never
used to influence a score.
"""

from __future__ import annotations

from silverloop.preferences import _candidate_dimension_value

candidate_dimension_value = _candidate_dimension_value
"""The production reader, re-exported under the name this package already used.

Returns `None` wherever the candidate does not carry the fact an axis needs -- honest ignorance
rather than a fabricated match -- and `None` for DISTANCE, which is ordinal and is scored solely
by `activity_search.travel_utility` from a tolerance in metres.
"""

__all__ = ["candidate_dimension_value"]

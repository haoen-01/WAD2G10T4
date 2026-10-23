# Care+ glossary

Terms used across the product, the API and the docs. Definitions only; design lives in `docs/adr/` and
the specs under `docs/`.

**Review setting / review timing.** How far below a senior's own baseline, and for how many low
valid-wear days, before Care+ asks a coordinator to review. It starts at 40% for 3 days and moves
only within fixed bounds, one step at a time, with a coordinator's approval. The web UI calls it
"review timing"; API text, contract names (`ReviewThreshold…`) and backend docs say "review setting".
They are the same thing. It never changes the baseline.

**Absolute floor.** A drop of 60% or more for 3 low days always asks a human, whatever the person's
review setting is.

**Shadow check.** While a looser review setting is live, Care+ works out from stored history the
first day the starting setting would have asked. If the personal setting has not asked 3 days later, the
case opens and the setting goes back to the starting one.

**Calibration-eligible judgement.** A review that may count toward a looser review setting: a
coordinator resolved the case as "Not a concern for this person", did not mark it as reaching them too
late, the case opened within the last 30 days, and the current setting was already live when it opened.
Free-text notes never count.

**Review lesson.** What one stored review taught Care+, worked out on read. Exactly one of:

- _Counts toward review setting_: resolved as not a concern (toward waiting longer), or marked "should
  have reached me sooner" (toward asking sooner).
- _Records a context gap_: overridden because the care team already knew why.
- _Teaches nothing_: agreement, a hold, doubtful data, recent contact, another reason, an unresolved
  "not a concern", no structured choice, or a case Care+ closed itself.

**Context gap.** Context the care team knew and Care+ could not see, recorded when a coordinator
overrides for "known context". It is counted per person for the care team and changes no decision,
proposal or review setting. Optional categories: _away_ (away from home), _already in touch_ (through
another service or family; distinct from the care team's own recent contact), _resting or recovering_,
_other known_.

**Review-setting receipt.** For the proposal or setting on screen: which reviews counted, which asked
sooner, which were excluded and why, and how many of the needed reviews have counted.

**Since your last review.** What changed on an open case since a human last reviewed it (or since it
opened): counts of recorded, usable and below-usual days, rain or holiday starting or ending, outreach
and its replies, and review-timing changes. Produced by the server as fixed sentences; never anything
the senior said, a note, or a step figure.

**Simulated coordinator profile.** A written-down reviewing rule used only in the calibration
evaluation: _accurate_, _dismissive_ (always "not a concern") or _over-cautious_ (always agrees and
says it reached them too late). Never a real coordinator.

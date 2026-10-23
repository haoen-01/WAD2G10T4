"""The `llm_recorded` benchmark arm: the agent loops, measured offline, from committed fixtures.

Read this before reading a number this package produces
-------------------------------------------------------
**The recordings this repository ships were not produced by a model.** They were produced by
`scripted_model.ScriptedRankingModel` -- a deterministic, rule-based stand-in with two rules,
written out in full in that module's docstring -- and every artifact, banner and table says so.

That is a deliberate choice, not a shortcut waiting to be fixed. What M25 is actually about is
that agent behaviour is *unmeasurable offline*: CI runs with `LLM_ENABLED=false`, so every
planner counter is structurally zero and the benchmark measures the deterministic ranker only.
This package closes that: a real `plan_activity_ranking` loop, a real guardrail, a real
degradation path and a real metric family, driven by a transport that needs no network. Swap the
stand-in for recordings of an actual model (`synthesise.py --inner`, one human-run command) and
every number here becomes a statement about that model, with no code change.

Until then, no number here is evidence about model quality, and nothing in this package claims
one. What it is evidence about:

* that the loop, guardrail, allow-list, narrowing bound and fallback paths run end to end
  offline, over all 84 benchmark cases;
* that the metric family can distinguish a reordering from the deterministic order at all
  (agreement, narrowing, promotion, rejection, fallback), rather than reporting structural zeros;
* that a stale or missing recording degrades loudly -- `RecordingMiss` -> `fallback_error` -- and
  is reported as "not recorded" rather than as a quietly identical result.

Why it is a sibling package rather than `evaluation/ranking/llm.py`
------------------------------------------------------------------
`test_ranking_evaluation.py`'s import-boundary test asserts that importing
`silverloop.evaluation.ranking` loads no `silverloop.agent`, `silverloop.config` or provider SDK
module. That boundary is worth keeping exactly as it is: the deterministic benchmark must stay
provably free of the LLM layer. This package sits beside it and imports both.
"""

from silverloop.evaluation.ranking_llm.runner import (
    ARM_LLM_RECORDED,
    ArmCaseResult,
    LlmArmResult,
    LlmSplitResult,
    run_llm_evaluation,
)

__all__ = [
    "ARM_LLM_RECORDED",
    "ArmCaseResult",
    "LlmArmResult",
    "LlmSplitResult",
    "run_llm_evaluation",
]

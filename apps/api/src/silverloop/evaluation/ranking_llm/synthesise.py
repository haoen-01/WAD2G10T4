"""Generate the committed recordings. Run by a human, never by a test and never by CI.

    cd apps/api && uv run python -m silverloop.evaluation.ranking_llm.synthesise

`RecordedClient(mode="record")` refuses to run when any CI marker is set, so this command cannot
execute on an automated run at all. Nothing under `tests/` imports it.

What it records, and against what
---------------------------------
By default, against `scripted_model.ScriptedRankingModel` / `ScriptedIntentModel` -- deterministic
rules, not a model. Every file it writes carries `"synthetic": true` and a banner saying so, and
every artifact built from those files repeats it.

To record against a real provider instead, pass `--inner anthropic` (or `--inner bedrock`) with
the usual credentials in the environment. That makes one live call per request, costs money, and
is the one moment in this pipeline where a network connection exists. The output files then carry
`"synthetic": false` and the real model id, and every number the arm reports becomes a statement
about that model with no other change anywhere. That is the whole design: the stand-in is a
placeholder in the fixtures, not in the code.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from silverloop.agent.intent_planner import plan_intent
from silverloop.agent.planner import _build_client, plan_activity_ranking
from silverloop.agent.recorded_client import RecordedClient, RecordingRefused
from silverloop.config import Settings
from silverloop.evaluation.ranking import ablations
from silverloop.evaluation.ranking.dataset import CORE_PERSONAS, HOLDOUT_PERSONAS, QUERY_TEMPLATES
from silverloop.evaluation.ranking.runner import CORE_SPLIT, HOLDOUT_SPLIT, run_case
from silverloop.evaluation.ranking_llm.harness import (
    ACTIVITY_RECORDINGS,
    ADVERSARIAL_RECORDINGS,
    INTENT_CASES,
    INTENT_RECORDINGS,
    THRESHOLD_RECORDINGS,
    adversarial_context,
    ranking_context,
    recorded_settings,
)
from silverloop.evaluation.ranking_llm.scripted_model import (
    SCRIPT_VERSION,
    SCRIPTED_MODEL_ID,
    ScriptedIntentModel,
    ScriptedRankingModel,
    ScriptedThresholdModel,
)
from silverloop.intent import parse_intent

SYNTHETIC_BANNER = (
    "SYNTHETIC RECORDING -- NOT A MODEL. Every response in this file was produced by "
    "`silverloop.evaluation.ranking_llm.scripted_model`, a deterministic rule-based stand-in "
    "whose two rules are written out in that module's docstring. Latency and token counts are "
    "synthesised from the request hash and are NOT measurements. Nothing in this file is "
    "evidence about any model's behaviour; it exists so the agent loop, its guardrail and its "
    "degradation paths can be exercised and measured offline."
)

SYNTHETIC_THRESHOLD_BANNER = (
    "SYNTHETIC RECORDING -- NOT A MODEL. Every response in this file was produced by "
    "`silverloop.evaluation.ranking_llm.scripted_model.ScriptedThresholdModel`, a deterministic "
    "rule-based stand-in whose rules are written out in its docstring, playing the "
    "review-threshold calibrator through the guided `mdm-wong` sequence. Latency and token counts "
    "are synthesised from the request hash and are NOT measurements. Nothing in this file is "
    "evidence about any model's behaviour; it exists so the calibration and write-up loops, their "
    "guardrail and the replayed demo can be exercised offline."
)

LIVE_BANNER = (
    "RECORDED FROM A LIVE PROVIDER. Responses in this file were returned by the named model on "
    "the date this file was committed. They are a frozen sample of one run, not a distribution: "
    "the same prompt on another day may differ."
)

# The stand-in's script for the intent parse: (substring of the request, `record_intent` args).
# Readings a competent parser would produce for these six synthetic sentences -- including the
# `unparsed_terms` the deterministic keyword reader has no way to populate.
INTENT_ANSWERS: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        "don't mind what",
        {
            "on_date": None,
            "time_window": "any",
            "max_distance_m": None,
            "social_preference": "either",
            "environment": "either",
            "intensity": "either",
            "language": None,
            "unparsed_terms": [],
        },
    ),
    (
        "gentle indoors",
        {
            "on_date": None,
            "time_window": "morning",
            "max_distance_m": None,
            "social_preference": "either",
            "environment": "indoor",
            "intensity": "light",
            "language": None,
            "unparsed_terms": ["tomorrow"],
        },
    ),
    (
        "meet some people",
        {
            "on_date": None,
            "time_window": "any",
            "max_distance_m": 1000,
            "social_preference": "social",
            "environment": "either",
            "intensity": "either",
            "language": None,
            "unparsed_terms": [],
        },
    ),
    (
        "in mandarin",
        {
            "on_date": None,
            "time_window": "any",
            "max_distance_m": None,
            "social_preference": "either",
            "environment": "either",
            "intensity": "either",
            "language": "Mandarin",
            "unparsed_terms": [],
        },
    ),
    (
        "nothing far",
        {
            "on_date": None,
            "time_window": "any",
            "max_distance_m": 1000,
            "social_preference": "either",
            "environment": "either",
            "intensity": "either",
            "language": None,
            "unparsed_terms": ["my knees are not what they were"],
        },
    ),
    (
        "on my own in the evening",
        {
            "on_date": None,
            "time_window": "evening",
            "max_distance_m": None,
            "social_preference": "solo",
            "environment": "either",
            "intensity": "either",
            "language": None,
            "unparsed_terms": ["quiet"],
        },
    ),
)


def _generator_label(inner_label: str) -> str:
    return f"silverloop.evaluation.ranking_llm.synthesise ({inner_label})"


def _inner_for(kind: str, settings: Settings, *, intent: bool) -> tuple[Any, bool, str]:
    """`(client, synthetic, label)`. `scripted` is the default and the only offline one."""
    if kind == "scripted":
        inner = ScriptedIntentModel(answers=INTENT_ANSWERS) if intent else ScriptedRankingModel()
        return inner, True, SCRIPT_VERSION
    live_settings = settings.model_copy(update={"llm_provider": kind})
    client, unavailable = _build_client(live_settings, live_settings.llm_timeout_seconds)
    if client is None:
        raise SystemExit(f"Cannot record against {kind}: {unavailable}")
    return client, False, f"{kind}:{live_settings.llm_model}"


def record_activity_split(
    split: str, personas: tuple[Any, ...], out: Path, *, inner_kind: str, model: str
) -> Path:
    settings = recorded_settings(out, model=model)
    inner, synthetic, label = _inner_for(inner_kind, settings, intent=False)
    client = RecordedClient(
        out,
        mode="record",
        inner=inner,
        loop="activity_ranking",
        banner=SYNTHETIC_BANNER if synthetic else LIVE_BANNER,
        generator=_generator_label(label),
    )
    client.recording.synthetic = synthetic
    for persona in personas:
        for template in QUERY_TEMPLATES:
            case = run_case(split, persona, template)
            ranked = case.arms[ablations.ARM_FULL]
            run = plan_activity_ranking(
                ranking_context(case, ranked),
                settings=settings,
                fallback_order=[item.ranked.candidate.activity_id for item in ranked],
                client_factory=lambda: (client, None),
            )
            if not run.used_agent:
                print(
                    f"  ! {split}/{persona.person_id}/{template.name}: {run.mode} "
                    f"({run.fallback_reason})",
                    file=sys.stderr,
                )
    client.save(out)
    print(f"  {out} ({len(client.recording.entries)} entries)")
    return out


def record_intent(out: Path, *, inner_kind: str, model: str) -> Path:
    settings = recorded_settings(out, model=model)
    inner, synthetic, label = _inner_for(inner_kind, settings, intent=True)
    client = RecordedClient(
        out,
        mode="record",
        inner=inner,
        loop="intent",
        banner=SYNTHETIC_BANNER if synthetic else LIVE_BANNER,
        generator=_generator_label(label),
    )
    client.recording.synthetic = synthetic
    for case in INTENT_CASES:
        _, mode = plan_intent(
            case.text,
            today=case.today,
            settings=settings,
            fallback=parse_intent(case.text, today=case.today),
            client_factory=lambda: (client, None),
        )
        if mode != "agent":
            print(f"  ! intent/{case.name}: {mode}", file=sys.stderr)
    client.save(out)
    print(f"  {out} ({len(client.recording.entries)} entries)")
    return out


def record_adversarial(out: Path, *, model: str) -> Path:
    """One fixture where the stand-in proposes a key that was never permitted, so the guardrail
    rejection and the revision turn are exercised from a recording rather than a hand fake."""
    settings = recorded_settings(out, model=model)
    context = adversarial_context()
    client = RecordedClient(
        out,
        mode="record",
        inner=ScriptedRankingModel(invent_key_once=True),
        loop="activity_ranking",
        banner=SYNTHETIC_BANNER,
        generator=_generator_label(f"{SCRIPT_VERSION}+invent_key_once"),
    )
    run = plan_activity_ranking(
        context,
        settings=settings,
        fallback_order=list(context.permitted_keys),
        client_factory=lambda: (client, None),
    )
    if not run.rejected_proposal_count or not run.used_agent:
        raise SystemExit(
            "The adversarial fixture must record a guardrail rejection AND an approved revision; "
            f"got mode={run.mode} with {run.rejected_proposal_count} rejection(s)."
        )
    client.save(out)
    print(f"  {out} ({len(client.recording.entries)} entries, {run.mode})")
    return out


def record_threshold(out: Path, *, inner_kind: str, model: str) -> Path:
    """The review-threshold calibrator's guided `mdm-wong` sequence (ADR 0008, spec section 11),
    driven through the real repository on in-memory SQLite with every calibrator request recorded.

    `scripted` (the default) records `ScriptedThresholdModel` -- NOT A MODEL -- into a file marked
    synthetic. A live provider produces `live_demo.json`, which a human records and commits.
    """
    from silverloop.evaluation.ranking_llm.threshold_sequence import run_guided_threshold_sequence

    settings = recorded_settings(out, model=model)
    if inner_kind == "scripted":
        inner: Any = ScriptedThresholdModel()
        synthetic, label = True, f"{SCRIPT_VERSION}+threshold"
    else:
        inner, synthetic, label = _inner_for(inner_kind, settings, intent=False)
    client = RecordedClient(
        out,
        mode="record",
        inner=inner,
        loop="review_threshold",
        banner=SYNTHETIC_THRESHOLD_BANNER if synthetic else LIVE_BANNER,
        generator=_generator_label(label),
    )
    client.recording.synthetic = synthetic
    state = run_guided_threshold_sequence(settings=settings, client_factory=lambda: (client, None))
    modes = [
        (item.output_kind.value, (item.agent_run or {}).get("mode")) for item in state.proposals
    ]
    if not any(mode == "agent" for _, mode in modes):
        raise SystemExit(f"The guided sequence recorded no agent output: {modes}")
    client.save(out)
    print(f"  {out} ({len(client.recording.entries)} entries; outputs {modes})")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m silverloop.evaluation.ranking_llm.synthesise")
    parser.add_argument(
        "--inner",
        choices=("scripted", "anthropic", "bedrock"),
        default="scripted",
        help="What to record from. `scripted` (default) makes no network call.",
    )
    parser.add_argument("--model", default="", help="Model id to record under.")
    parser.add_argument("--activity-out", type=Path, default=ACTIVITY_RECORDINGS)
    parser.add_argument("--intent-out", type=Path, default=INTENT_RECORDINGS)
    parser.add_argument("--adversarial-out", type=Path, default=ADVERSARIAL_RECORDINGS)
    parser.add_argument("--threshold-out", type=Path, default=THRESHOLD_RECORDINGS)
    parser.add_argument(
        "--threshold-only",
        action="store_true",
        help="Record only the review-threshold guided sequence (scripted.json, or live_demo.json "
        "from a live provider).",
    )
    args = parser.parse_args(argv)

    model = args.model or SCRIPTED_MODEL_ID
    if args.inner != "scripted" and not args.model:
        print("error: --model is required when recording from a live provider", file=sys.stderr)
        return 2

    try:
        if args.threshold_only:
            name = "scripted.json" if args.inner == "scripted" else "live_demo.json"
            print("Recording the review-threshold guided sequence:")
            record_threshold(args.threshold_out / name, inner_kind=args.inner, model=model)
            return 0
        print("Recording activity-ranking loop:")
        record_activity_split(
            CORE_SPLIT,
            CORE_PERSONAS,
            args.activity_out / "core.json",
            inner_kind=args.inner,
            model=model,
        )
        record_activity_split(
            HOLDOUT_SPLIT,
            HOLDOUT_PERSONAS,
            args.activity_out / "holdout.json",
            inner_kind=args.inner,
            model=model,
        )
        print("Recording intent parse:")
        record_intent(args.intent_out / "queries.json", inner_kind=args.inner, model=model)
        if args.inner == "scripted":
            print("Recording the adversarial guardrail-revision fixture:")
            record_adversarial(args.adversarial_out / "guardrail_revision.json", model=model)
    except RecordingRefused as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print("Done. Two steps remain, both of them deliberate:")
    print("  1. pnpm exec prettier --write apps/api/tests/recordings")
    print("     (this writer indents every array; prettier keeps short ones inline, and")
    print("      `pnpm format:check` is what enforces that across the repository)")
    print("  2. python -m silverloop.evaluation.ranking_llm --out ../../docs/evaluation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

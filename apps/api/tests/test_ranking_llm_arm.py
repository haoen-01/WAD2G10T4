"""Tests for the `llm_recorded` benchmark arm (M25).

The arm's value is entirely in its honesty, so that is what these pin: it measures the real loop
(not a shortcut), it reports "not recorded" rather than a zero when a fixture is absent, its
displayed order matches what the repository would actually show, and its artifact is
deterministic and committed.

None of these assert a quality number. The committed recordings come from a deterministic
stand-in (see `silverloop.evaluation.ranking_llm`), and a test that gated on their NDCG would be
asserting the stand-in's rule, not the product's behaviour.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from silverloop.agent.constants import MAX_PROMOTION
from silverloop.agent.recorded_client import RecordedClient
from silverloop.evaluation.ranking import ablations
from silverloop.evaluation.ranking.dataset import CORE_PERSONAS, HOLDOUT_PERSONAS, QUERY_TEMPLATES
from silverloop.evaluation.ranking.runner import CORE_SPLIT, run_case
from silverloop.evaluation.ranking_llm.harness import (
    ACTIVITY_RECORDINGS,
    ranking_context,
    recorded_settings,
)
from silverloop.evaluation.ranking_llm.report import (
    JSON_FILENAME,
    MARKDOWN_FILENAME,
    NOT_RECORDED,
    check_artifacts,
    to_json_document,
    to_markdown,
    write_artifacts,
)
from silverloop.evaluation.ranking_llm.runner import (
    agreement_at_k,
    apply_planner_order,
    max_promotion,
    run_arm_case,
    run_llm_evaluation,
)
from silverloop.evaluation.ranking_llm.scripted_model import MIN_OFFERED, scripted_order

DOCS_EVALUATION = Path(__file__).parents[3] / "docs" / "evaluation"


@pytest.fixture(scope="module")
def result():
    return run_llm_evaluation()


# ── The arm runs the real loop over the real dataset ───────────────────────────────────────────


def test_every_benchmark_case_is_replayed(result) -> None:
    assert result.core.n_cases == len(CORE_PERSONAS) * len(QUERY_TEMPLATES)
    assert result.holdout.n_cases == len(HOLDOUT_PERSONAS) * len(QUERY_TEMPLATES)


def test_the_committed_recordings_answer_every_case(result) -> None:
    """A miss here means the prompt, the tool schema or the deterministic order moved and the
    fixtures were not regenerated -- the loud failure the request-keyed design exists to give."""
    assert result.core.misses == 0
    assert result.holdout.misses == 0
    assert result.core.recorded_cases == result.core.n_cases
    assert result.holdout.recorded_cases == result.holdout.n_cases


def test_the_arm_reaches_agent_mode_rather_than_measuring_the_fallback(result) -> None:
    """If this ever reports only fallbacks, every metric below is the deterministic arm restated
    and the whole artifact is meaningless."""
    assert result.core.fallback_counts.get("agent") == result.core.n_cases


def test_the_arm_exercises_reordering_and_narrowing(result) -> None:
    """Not a quality claim: only that the machinery moved at all. An arm whose stand-in always
    agreed would report structural 1.0/0.0 and measure nothing -- which is the state M25 exists
    to leave behind."""
    assert 0.0 < result.core.agreement_at_3.mean < 1.0
    assert result.core.narrowing_rate.mean > 0.0
    assert result.core.max_promotion_observed > 0


def test_cost_is_reported_from_the_recording(result) -> None:
    assert result.core.latency_p50_ms is not None
    assert result.core.latency_p95_ms >= result.core.latency_p50_ms
    assert result.core.tokens_per_run_mean > 0


def test_the_recording_is_declared_synthetic(result) -> None:
    assert result.recording_is_synthetic is True
    assert "NOT A MODEL" in result.recording_banner
    assert result.model == "synthetic-scripted-stand-in-v1"


# ── "not recorded", never a silent zero ────────────────────────────────────────────────────────


def test_the_arm_reports_not_recorded_when_fixtures_are_missing(tmp_path: Path) -> None:
    missing = run_llm_evaluation(tmp_path / "no-recordings-here")
    assert missing.recording_entries == 0
    assert missing.recorded is False
    assert missing.core.recorded is False
    assert missing.core.recorded_cases == 0

    document = to_json_document(missing)
    core = document["splits"]["core"]
    assert core["status"] == NOT_RECORDED
    # Null, not zero: a missing fixture must not be plottable as a measurement.
    assert core["metrics"] is None
    assert core["arm_metrics"] is None
    assert core["cost"] is None

    markdown = to_markdown(missing)
    assert NOT_RECORDED in markdown
    assert "0.0000" not in markdown


def test_a_recording_that_answers_nothing_is_reported_as_missing(tmp_path: Path) -> None:
    """An empty directory and a directory of irrelevant recordings must read the same way: the
    arm ran, nothing replayed, and the report says so rather than averaging the fallbacks in."""
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "nothing.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "synthetic": True,
                "banner": "SYNTHETIC RECORDING -- NOT A MODEL. Empty on purpose.",
                "loop": "activity_ranking",
                "generator": "test",
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    result = run_llm_evaluation(empty)
    assert result.core.recorded is False
    assert to_json_document(result)["splits"]["core"]["status"] == NOT_RECORDED


# ── The displayed order mirrors the repository ─────────────────────────────────────────────────


def test_narrowing_demotes_rather_than_deletes() -> None:
    """`sql_repository.search_activities` keeps a narrowed option, demoted, and records it under
    `planner_narrowed`. An arm that deleted it would overstate narrowing's effect."""
    case = run_case(CORE_SPLIT, CORE_PERSONAS[0], QUERY_TEMPLATES[0])
    ranked = case.arms[ablations.ARM_FULL]
    ids = [item.ranked.candidate.activity_id for item in ranked]
    displayed, narrowed = apply_planner_order(ranked, [ids[2], ids[0]])

    assert [item.ranked.candidate.activity_id for item in displayed][:2] == [ids[2], ids[0]]
    assert set(narrowed) <= set(ids)
    assert len(displayed) == len(ranked)
    assert {item.ranked.candidate.activity_id for item in displayed} == set(ids)


def test_an_empty_proposal_keeps_the_deterministic_order() -> None:
    case = run_case(CORE_SPLIT, CORE_PERSONAS[0], QUERY_TEMPLATES[0])
    ranked = case.arms[ablations.ARM_FULL]
    displayed, narrowed = apply_planner_order(ranked, [])
    assert displayed == ranked
    assert narrowed == []


def test_agreement_and_promotion_are_computed_as_documented() -> None:
    assert agreement_at_k(["a", "b", "c"], ["a", "b", "c"]) == 1.0
    assert agreement_at_k(["c", "b", "a"], ["a", "b", "c"]) == 1.0  # a set, not an order
    assert agreement_at_k(["x", "y", "z"], ["a", "b", "c"]) == 0.0
    assert max_promotion(["a", "b", "c"], ["c", "a", "b"]) == 2
    assert max_promotion(["a", "b", "c"], ["a", "b", "c"]) == 0


# ── The stand-in's own rules ───────────────────────────────────────────────────────────────────


def _option(key: str, category: str) -> dict[str, object]:
    return {"activity_key": key, "category": category}


def test_rule_a_varies_the_first_three_categories() -> None:
    options = [
        _option("a", "movement"),
        _option("b", "movement"),
        _option("c", "movement"),
        _option("d", "social"),
        _option("e", "craft"),
    ]
    assert scripted_order(options)[:3] == ["a", "d", "e"]


def test_rule_b_never_offers_fewer_than_the_floor() -> None:
    """Ten repeats of one category: rule B hides tail repeats, but never below `MIN_OFFERED`
    and never more than `MAX_PROMOTION` of them, because hiding lifts every later option by one
    place and the guardrail measures promotion on the final position."""
    options = [_option(f"k{index}", "movement") for index in range(10)]
    ordered = scripted_order(options)
    assert len(ordered) == max(MIN_OFFERED, len(options) - MAX_PROMOTION)
    # Hidden options come from the tail; what is kept stays in deterministic order.
    assert ordered[:MIN_OFFERED] == [f"k{index}" for index in range(MIN_OFFERED)]
    positions = [int(key[1:]) for key in ordered]
    assert positions == sorted(positions)


def test_the_stand_in_never_invents_or_duplicates_a_key() -> None:
    options = [_option("a", "movement"), _option("b", "social"), _option("c", "movement")]
    ordered = scripted_order(options)
    assert len(ordered) == len(set(ordered))
    assert set(ordered) <= {"a", "b", "c"}


# ── Hermetic settings ──────────────────────────────────────────────────────────────────────────


def test_arm_settings_ignore_the_ambient_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's `.env` must not change the request shape, or the published artifact would
    be machine-dependent and every fixture would miss."""
    monkeypatch.setitem(os.environ, "LLM_REQUEST_PROFILE", "legacy")
    monkeypatch.setitem(os.environ, "LLM_MODEL", "somebody-elses-model")
    monkeypatch.setitem(os.environ, "LLM_ENABLED", "false")
    settings = recorded_settings(ACTIVITY_RECORDINGS)
    assert settings.llm_request_profile == "modern"
    assert settings.llm_model == "synthetic-scripted-stand-in-v1"
    assert settings.llm_enabled is True


def test_the_arm_context_matches_what_the_repository_would_send() -> None:
    """The projection is duplicated from `sql_repository.search_activities`; if it drifts, the
    arm measures a prompt the product never sends."""
    case = run_case(CORE_SPLIT, CORE_PERSONAS[0], QUERY_TEMPLATES[1])
    ranked = case.arms[ablations.ARM_FULL]
    context = ranking_context(case, ranked)
    assert context.permitted_keys == [
        item.ranked.candidate.activity_id for item in ranked[: len(context.permitted_keys)]
    ]
    for option, item in zip(context.options, ranked, strict=True):
        assert option.key == item.ranked.candidate.activity_id
        assert option.deterministic_rank == item.ranked.rank
        assert option.reasons == [reason.text for reason in item.ranked.reasons]


def test_one_case_replays_identically_twice() -> None:
    """Determinism at the arm level, not only at the client level."""
    settings = recorded_settings(ACTIVITY_RECORDINGS)
    runs = []
    for _ in range(2):
        client = RecordedClient(ACTIVITY_RECORDINGS, mode="replay")
        runs.append(
            run_arm_case(
                CORE_SPLIT,
                CORE_PERSONAS[0],
                QUERY_TEMPLATES[0],
                client=client,
                settings=settings,
            )
        )
    assert runs[0].displayed_order == runs[1].displayed_order
    assert runs[0].metrics == runs[1].metrics
    assert runs[0].total_tokens == runs[1].total_tokens
    assert runs[0].latencies_ms == runs[1].latencies_ms


# ── Every interval is resampled over personas, and says so ─────────────────────────────────────
#
# Decisions §16: "persona-clustered paired bootstrap everywhere, `n_clusters` in every header".
# This arm used `bootstrap_stat`/`paired_delta`, which resample CASES. Six cases share one
# persona's trace, preference store and grade table, so that CI is ~2.2x too narrow on this
# design -- `metrics.py` says so in its own docstring -- and `n_clusters` appeared nowhere in the
# artifact. Three published deltas excluded zero only under the narrower test.


def test_every_interval_in_the_arm_is_resampled_over_personas(result) -> None:
    from silverloop.evaluation.ranking_llm.runner import CASE_METRIC_NAMES

    for split, personas in ((result.core, CORE_PERSONAS), (result.holdout, HOLDOUT_PERSONAS)):
        for name in CASE_METRIC_NAMES:
            assert split.metrics[name].n_clusters == len(personas), name
            assert split.deltas[name].n_clusters == len(personas), name
        assert split.agreement_at_3.n_clusters == len(personas)
        assert split.narrowing_rate.n_clusters == len(personas)


def test_the_artifact_prints_n_clusters_in_every_header(result) -> None:
    markdown = to_markdown(result)
    document = to_json_document(result)

    assert "n_clusters" in markdown
    for split in ("core", "holdout"):
        metrics = document["splits"][split]["metrics"]
        deltas = document["splits"][split]["deltas_vs_deterministic"]
        assert all("n_clusters" in stat for stat in metrics.values())
        assert all("n_clusters" in delta for delta in deltas.values())
        assert all("excludes_zero" in delta for delta in deltas.values())


def test_every_delta_is_persona_clustered(result) -> None:
    """The arm used to bootstrap per case, which overstated the evidence: three deltas that
    excluded zero per case did not under the persona-clustered test the design mandates. Which
    small deltas clear zero moves with the deterministic order, so that is read from the artifact,
    never pinned here; what is pinned is that every delta was clustered by persona at all."""
    for split in (result.core, result.holdout):
        for name, delta in split.deltas.items():
            assert delta.n_clusters > 0, (split.split, name, delta)
            assert delta.n_clusters <= delta.n, (split.split, name, delta)


# ── The artifact ───────────────────────────────────────────────────────────────────────────────


def test_the_artifact_is_byte_identical_on_two_runs(result, tmp_path: Path) -> None:
    write_artifacts(result, tmp_path)
    first = (tmp_path / JSON_FILENAME).read_text(encoding="utf-8")
    write_artifacts(run_llm_evaluation(), tmp_path)
    assert (tmp_path / JSON_FILENAME).read_text(encoding="utf-8") == first


def test_the_artifact_carries_no_absolute_path(result) -> None:
    """An absolute recording path would differ per machine and break `--check` everywhere else."""
    document = json.dumps(to_json_document(result))
    assert str(ACTIVITY_RECORDINGS) not in document
    assert "/Users/" not in document


def test_the_artifact_leads_with_the_not_a_model_banner(result) -> None:
    markdown = to_markdown(result)
    assert markdown.splitlines()[2].startswith("**NOT_A_MODEL")


def test_the_committed_artifact_is_not_stale(result) -> None:
    """Regenerate with `python -m silverloop.evaluation.ranking_llm --out ../../docs/evaluation`
    (and `...ranking_llm.synthesise` first if the prompt or the dataset moved)."""
    assert check_artifacts(result, DOCS_EVALUATION), (
        "docs/evaluation/ranking-llm.{json,md} are stale"
    )


def test_the_arm_does_not_write_the_deterministic_artifact(tmp_path: Path) -> None:
    write_artifacts(run_llm_evaluation(tmp_path / "absent"), tmp_path)
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        JSON_FILENAME,
        MARKDOWN_FILENAME,
    ]


def test_check_exits_3_on_drift(tmp_path: Path, result) -> None:
    from silverloop.evaluation.ranking_llm.__main__ import main

    write_artifacts(result, tmp_path)
    assert main(["--out", str(tmp_path), "--check"]) == 0
    (tmp_path / JSON_FILENAME).write_text("{}", encoding="utf-8")
    assert main(["--out", str(tmp_path), "--check"]) == 3


def test_check_without_out_is_a_usage_error() -> None:
    from silverloop.evaluation.ranking_llm.__main__ import main

    assert main(["--check"]) == 2


def test_a_missing_recording_is_not_an_error_for_the_cli(tmp_path: Path) -> None:
    """ "Not recorded" is a reported state, not a failed run."""
    from silverloop.evaluation.ranking_llm.__main__ import main

    assert main(["--recordings", str(tmp_path / "absent"), "--out", str(tmp_path)]) == 0

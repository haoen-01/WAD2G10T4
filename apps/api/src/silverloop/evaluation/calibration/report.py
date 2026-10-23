"""Artifacts: `docs/evaluation/review-calibration.{json,md}`.

The same determinism discipline as the other evaluation reports: no timestamps, no ids, no paths --
simulated sequence days, counts and ratios of counts only -- so a regeneration is byte-identical
and `--check` catches drift.

Labelled synthetic throughout: the sequences are authored, the coordinators are three written-down
rules, and the agent arm's calibrator is a scripted stand-in (NOT A MODEL).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from silverloop.evaluation.calibration.metrics import containment, run_metrics, totals
from silverloop.evaluation.calibration.profiles import PROFILE_DESCRIPTIONS, PROFILES
from silverloop.evaluation.calibration.runner import ARM_DESCRIPTIONS, ARMS, PERSON
from silverloop.evaluation.calibration.sequences import sequences_digest, sequences_document
from silverloop.review_threshold import (
    ABSOLUTE_REVIEW_FLOOR,
    CHECKING_PERIOD_DAYS,
    COOLDOWN_DAYS,
    DEFAULT_REVIEW_THRESHOLD,
    FIXED_RULE_FALSE_ALARMS,
    FIXED_RULE_WINDOW_DAYS,
    SHADOW_GRACE_DAYS,
    WEEKLY_PROPOSAL_CAP,
)

if TYPE_CHECKING:
    from silverloop.evaluation.calibration.runner import CalibrationResult

SCHEMA_VERSION = 1
JSON_FILENAME = "review-calibration.json"
MARKDOWN_FILENAME = "review-calibration.md"

TITLE = "Review-setting calibration with imperfect coordinators"

DISCLOSURE = (
    "SYNTHETIC. Every activity sequence here is authored, every coordinator is one of three "
    "written-down rules, and the agent arm's calibrator is a deterministic scripted stand-in "
    "(NOT A MODEL). No row is, or is derived from, a real senior's or coordinator's data, and no "
    "number here is evidence about any language model or any real coordinator."
)

METHODOLOGY = (
    "Each run drives the real repository on a fresh in-memory SQLite database for the synthetic "
    f"persona `{PERSON}`: reset, then sixty simulated days, each advanced with an authored "
    "reading (steps as a fraction of the person's anchored reference, wear-time and rain) that "
    "replaces the simulation event's own. When a day opens a review case, the simulated "
    "coordinator reviews it that day through the same repository call the API uses; in the "
    "`fixed_rule` and `agent` arms any proposal then open is approved that day. The policy "
    "ladder, the absolute floor, the shadow check, the calibrator and its guardrail, the "
    "put-backs and the audited skips are the product's own. Every episode carries a latent "
    "label Care+ never sees: whether it is review-worthy, and by which day it should reach "
    "a coordinator. Delays are measured against the `starting_setting` arm for the same profile "
    "and sequence. The weekly proposal cap counts wall-clock time, so the sequences are authored "
    "to stay under it and the report counts any skip it causes."
)

CONTAINMENT_NOTE = (
    "Containment asks whether an arm that lets coordinators loosen the review setting stayed "
    "inside the guarantees the setting's bounds promise: no more review-worthy episodes missed "
    "than the starting setting (in every sequence), no review-worthy episode reaching a "
    f"coordinator more than {SHADOW_GRACE_DAYS} days later than the starting setting would have, "
    "every episode at or past the absolute floor opening a case, and no calibration skipped by "
    "the weekly cap."
)


def _cell_runs(result: CalibrationResult, arm: str, profile: str) -> list[dict[str, Any]]:
    sequences = {sequence.sequence_id: sequence for sequence in result.sequences}
    starting = {
        (trace.profile, trace.sequence_id): trace
        for trace in result.traces
        if trace.arm == "starting_setting"
    }
    return [
        run_metrics(
            trace,
            starting[(trace.profile, trace.sequence_id)],
            sequences[trace.sequence_id],
        )
        for trace in result.traces
        if trace.arm == arm and trace.profile == profile
    ]


def to_json_document(result: CalibrationResult) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    for profile in PROFILES:
        starting_runs = _cell_runs(result, "starting_setting", profile)
        for arm in ARMS:
            runs = starting_runs if arm == "starting_setting" else _cell_runs(result, arm, profile)
            cells.append(
                {
                    "arm": arm,
                    "profile": profile,
                    "totals": totals(runs),
                    "containment": (
                        None if arm == "starting_setting" else containment(runs, starting_runs)
                    ),
                    "by_sequence": runs,
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "title": TITLE,
        "synthetic": True,
        "disclosure": DISCLOSURE,
        "methodology": METHODOLOGY,
        "containment_note": CONTAINMENT_NOTE,
        "person": PERSON,
        "sequences_digest": sequences_digest(result.sequences),
        "settings": {
            "starting_setting": [
                DEFAULT_REVIEW_THRESHOLD.severity_pct,
                DEFAULT_REVIEW_THRESHOLD.persistence_days,
            ],
            "floor": [ABSOLUTE_REVIEW_FLOOR.severity_pct, ABSOLUTE_REVIEW_FLOOR.persistence_days],
            "shadow_grace_days": SHADOW_GRACE_DAYS,
            "fixed_rule_false_alarms": FIXED_RULE_FALSE_ALARMS,
            "fixed_rule_window_days": FIXED_RULE_WINDOW_DAYS,
            "cooldown_days": COOLDOWN_DAYS,
            "checking_period_days": CHECKING_PERIOD_DAYS,
            "weekly_proposal_cap": WEEKLY_PROPOSAL_CAP,
        },
        "arms": [{"arm": arm, "description": ARM_DESCRIPTIONS[arm]} for arm in ARMS],
        "profiles": [
            {"profile": profile, "description": PROFILE_DESCRIPTIONS[profile]}
            for profile in PROFILES
        ],
        "sequences": sequences_document(result.sequences),
        "cells": cells,
    }


def _dumps(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, list):
        return f"{value[0]}%/{value[1]}d"
    return str(value)


def _counts(values: dict[str, int]) -> str:
    present = [f"{key} {count}" for key, count in values.items() if count]
    return ", ".join(present) if present else "none"


def to_markdown(result: CalibrationResult) -> str:
    document = to_json_document(result)
    lines: list[str] = [
        f"# {TITLE}",
        "",
        f"> **{DISCLOSURE}**",
        "",
        "Generated by `python -m silverloop.evaluation.calibration --out ../../docs/evaluation`. "
        "Do not edit by hand; `--check` fails on drift.",
        "",
        f"Sequences digest: `{document['sequences_digest']}`",
        "",
        "## Method",
        "",
        METHODOLOGY,
        "",
        "Arms:",
        "",
        *[f"- `{item['arm']}` -- {item['description']}" for item in document["arms"]],
        "",
        "Simulated coordinators:",
        "",
        *[f"- `{item['profile']}` -- {item['description']}" for item in document["profiles"]],
        "",
        "## Sequences",
        "",
        "| Sequence | Episode | Label | Days | Review-worthy | Reach by day | Reaches floor |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for sequence in document["sequences"]:
        for episode in sequence["episodes"]:
            lines.append(
                f"| {sequence['sequence_id']} | {episode['episode_id']} | {episode['label']} | "
                f"{episode['start_day']}-{episode['end_day']} | "
                f"{_fmt(episode['review_worthy'])} | {_fmt(episode['should_reach_by_day'])} | "
                f"{_fmt(episode['reaches_floor'])} |"
            )
    lines += [
        "",
        "## Workload against missed review-worthy episodes",
        "",
        "Totals over all sequences. `Cases` counts review cases opened; `missed` and `late` count "
        "review-worthy episodes; `max delay` is in simulated days against `starting_setting`. An "
        "episode is retained when a case opened during it or a case was still unresolved at the "
        "end of one of its days (an acknowledged case stays with the coordinator and is refreshed "
        "rather than reopened); `late` and `max delay` use the first such day. `Benign asked` and "
        "`floor episodes opened` count cases opened.",
        "",
        "| Profile | Arm | Cases | Via setting / floor / shadow | Benign asked | "
        "Review-worthy retained | Missed | Late | Max delay | Floor episodes opened |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for cell in document["cells"]:
        workload = cell["totals"]["workload"]
        episodes = cell["totals"]["episodes"]
        routes = workload["cases_by_route"]
        lines.append(
            f"| {cell['profile']} | {cell['arm']} | {workload['cases_opened']} | "
            f"{routes.get('review_setting', 0)} / {routes.get('floor', 0)} / "
            f"{routes.get('shadow_check', 0)} | "
            f"{episodes['benign_asked_about']} of {episodes['benign']} | "
            f"{episodes['review_worthy_retained']} of {episodes['review_worthy']} | "
            f"{episodes['review_worthy_missed']} | {episodes['review_worthy_late']} | "
            f"{_fmt(episodes['max_delay_days'])} | "
            f"{episodes['floor_episodes_opened']} of {episodes['floor_episodes']} |"
        )
    lines += [
        "",
        "## Containment",
        "",
        CONTAINMENT_NOTE,
        "",
        "| Profile | Arm | Missed <= starting | Max delay | Within grace | Floor episodes opened "
        "| Weekly-cap skips | Holds |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for cell in document["cells"]:
        check = cell["containment"]
        if check is None:
            continue
        lines.append(
            f"| {cell['profile']} | {cell['arm']} | "
            f"{_fmt(check['missed_no_more_than_starting_setting'])} | "
            f"{_fmt(check['max_delay_days'])} | {_fmt(check['max_delay_within_grace_days'])} | "
            f"{_fmt(check['every_floor_episode_opened_a_case'])} | {check['weekly_cap_skips']} | "
            f"**{_fmt(check['holds'])}** |"
        )
    lines += [
        "",
        "## Review-setting movement",
        "",
        "| Profile | Arm | Approved (looser / sooner) | Put back (shadow / too late / far more "
        "severe) | Severity range | Persistence range | Days looser | Days sooner | "
        "Calibration skips | Discards | Approvals refused |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for cell in document["cells"]:
        threshold = cell["totals"]["threshold"]
        calibrator = cell["totals"]["calibrator"]
        triggers = threshold["put_backs_by_trigger"]
        lines.append(
            f"| {cell['profile']} | {cell['arm']} | {threshold['approved_changes']} "
            f"({threshold['approved_looser']} / {threshold['approved_sooner']}) | "
            f"{threshold['put_backs']} ({triggers.get('shadow_check', 0)} / "
            f"{triggers.get('reached_too_late', 0)} / {triggers.get('far_more_severe', 0)}) | "
            f"{threshold['severity_pct_min']}-{threshold['severity_pct_max']}% | "
            f"{threshold['persistence_days_min']}-{threshold['persistence_days_max']}d | "
            f"{threshold['days_looser_than_start']} | {threshold['days_sooner_than_start']} | "
            f"{_counts(calibrator['calibration_skips'])} | "
            f"{_counts(calibrator['calibration_discards'])} | {calibrator['approvals_refused']} |"
        )
    lines += [
        "",
        "## Reviewer pattern (simulated profiles only)",
        "",
        "Per simulated profile, never per real coordinator. `Eligible` is a review the fixed rule "
        "may count toward a looser setting (resolved, not a concern, not marked too late); the "
        "last column is the share of eligible reviews behind an approved loosening whose "
        "loosening was later put back.",
        "",
        "| Profile | Arm | Reviews | Override rate | Eligible share | Behind a loosening | "
        "Later put back | Put-back share |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for cell in document["cells"]:
        pattern = cell["totals"]["reviewer_pattern"]
        lines.append(
            f"| {cell['profile']} | {cell['arm']} | {pattern['reviews']} | "
            f"{_fmt(pattern['override_rate'])} | {_fmt(pattern['eligible_to_loosen_share'])} | "
            f"{pattern['eligible_led_to_approved_loosening']} | "
            f"{pattern['eligible_loosening_later_reverted']} | "
            f"{_fmt(pattern['eligible_loosening_later_reverted_share'])} |"
        )
    lines += [
        "",
        "## Per sequence",
        "",
        "| Profile | Arm | Sequence | Cases | Missed | Max delay | Final setting | Changes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for cell in document["cells"]:
        for run in cell["by_sequence"]:
            changes = "; ".join(
                f"day {change['decided_on_day']} {change['kind']}"
                + (f" ({change['trigger']})" if change["trigger"] else "")
                + f" -> {_fmt(change['after'])}"
                for change in run["threshold"]["changes"]
            )
            lines.append(
                f"| {cell['profile']} | {cell['arm']} | {run['sequence_id']} | "
                f"{run['workload']['cases_opened']} | {run['episodes']['review_worthy_missed']} | "
                f"{_fmt(run['episodes']['max_delay_days'])} | "
                f"{_fmt(run['threshold']['final_setting'])} | {changes or 'none'} |"
            )
    return "\n".join(lines) + "\n"


def write_artifacts(result: CalibrationResult, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / JSON_FILENAME).write_text(_dumps(to_json_document(result)), encoding="utf-8")
    (out_dir / MARKDOWN_FILENAME).write_text(to_markdown(result), encoding="utf-8")


def check_artifacts(result: CalibrationResult, out_dir: Path) -> bool:
    json_path = out_dir / JSON_FILENAME
    markdown_path = out_dir / MARKDOWN_FILENAME
    if not json_path.exists() or not markdown_path.exists():
        return False
    return json_path.read_text(encoding="utf-8") == _dumps(
        to_json_document(result)
    ) and markdown_path.read_text(encoding="utf-8") == to_markdown(result)


__all__ = [
    "DISCLOSURE",
    "JSON_FILENAME",
    "MARKDOWN_FILENAME",
    "SCHEMA_VERSION",
    "check_artifacts",
    "to_json_document",
    "to_markdown",
    "write_artifacts",
]

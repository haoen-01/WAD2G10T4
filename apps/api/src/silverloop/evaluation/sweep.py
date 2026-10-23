"""Sensitivity sweep for the universal-step-threshold baseline.

## Why this exists

`fixed_threshold` acts when `steps < 3000`. Mr Ravi's seeded baseline is ~2,400 steps a day, so he
is below that line every single day by construction, and "the fixed threshold contacts Mr Ravi 5/5
while Care+ contacts him 0/5" is arithmetic before it is evidence. Reporting that number on
its own invites the obvious objection: you picked a threshold he fails.

The honest answer is not to move the threshold to one that flatters the comparison -- that would be
the same error with the sign flipped -- but to sweep it and let the reader see the whole curve. If
some threshold existed that left Mr Ravi alone AND still caught Mdm Lim's genuine decline, the
"personal baseline beats a universal threshold" claim would be false and this table would say so.

The sweep runs UNCAPPED on purpose: it asks which cut point discriminates, and a contact budget
would mask over-contacting at low thresholds by truncating it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from silverloop.evaluation.fold import fold_policy
from silverloop.evaluation.metrics import CONTACT, DecisionRecord, PolicyMetrics, aggregate
from silverloop.evaluation.protocol import SWEEP_POLICY_VERSION, sweep_entry
from silverloop.evaluation.scenario_spec import EvaluationScenario, GroundTruthState
from silverloop.evaluation.simulation import EnvironmentStep

#: Spans the plausible range for a universal daily-step rule for older adults, bracketing the
#: playbook's quoted 3,000 on both sides. Fixed, never tuned per run.
SWEEP_THRESHOLDS: tuple[int, ...] = (2000, 2500, 3000, 3500, 4000, 4500, 5000)

QUIET_LABELS = frozenset({GroundTruthState.STABLE, GroundTruthState.EXPLAINED_DIP})


@dataclass(frozen=True)
class SweepRow:
    threshold: int
    metrics: PolicyMetrics
    #: person_id -> number of CONTACT decisions this threshold produced for that person.
    contacts_by_person: dict[str, int]
    #: person_id -> contacts that landed on a `stable`/`explained_dip` step.
    unwarranted_by_person: dict[str, int]


def _by_person(records: Sequence[DecisionRecord]) -> tuple[dict[str, int], dict[str, int]]:
    contacts: dict[str, int] = {}
    unwarranted: dict[str, int] = {}
    for record in records:
        contacts.setdefault(record.person_id, 0)
        unwarranted.setdefault(record.person_id, 0)
        if record.decision in CONTACT:
            contacts[record.person_id] += 1
            if record.label in QUIET_LABELS:
                unwarranted[record.person_id] += 1
    return contacts, unwarranted


def run_sweep(
    scenarios: Sequence[EvaluationScenario],
    replayed: dict[str, list[EnvironmentStep]],
) -> tuple[SweepRow, ...]:
    """Fold a universal-threshold policy over the already-replayed environment once per threshold.

    Takes the replayed steps rather than the scenario directory so the sweep is provably scored on
    the identical environment stream as the headline comparison (D2).
    """
    rows: list[SweepRow] = []
    for threshold in SWEEP_THRESHOLDS:
        entry = sweep_entry(threshold)
        records: list[DecisionRecord] = []
        for scenario in scenarios:
            records.extend(fold_policy(entry, scenario, replayed[scenario.name], cap=None))
        contacts, unwarranted = _by_person(records)
        rows.append(
            SweepRow(
                threshold=threshold,
                metrics=aggregate(entry.name, SWEEP_POLICY_VERSION, records),
                contacts_by_person=contacts,
                unwarranted_by_person=unwarranted,
            )
        )
    return tuple(rows)

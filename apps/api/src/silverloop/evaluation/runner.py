"""Orchestration: replay each scenario once, fold every policy over it, aggregate and report.

CLI: `python -m silverloop.evaluation <scenario-dir> [--out DIR] [--check] [--seed N]
[--fail-on-violation POLICY|all|none]`

Exit codes: 0 ok, 1 gated hard violation, 2 spec/load error, 3 artifact drift.

## Arms, and why there is more than one

A single table comparing three policies is only honest if the policies were given the same
resources. They were not: `silverloop` caps itself at two contacts a week and neither baseline caps
itself at all, so the original "Care+ makes 11 contacts, the baselines 19 and 15" compared a
budgeted policy against unbudgeted ones and then scored the difference as judgement.

The harness therefore runs two arms over the identical replayed environment:

- **`capped`** -- the headline. The harness itself applies the SAME weekly contact cap
  (`UNIFORM_CONTACT_CAP`) to every policy, converting a would-be contact into `SUPPRESS` once the
  budget is spent. Differences in this arm are differences in *which* contacts a policy chose to
  spend its budget on.
- **`uncapped`** -- each policy exactly as written, retained so the size of the budget effect is
  visible. `silverloop`'s own cap still fires here because it is part of the policy; that is the
  point, and it is why the two arms are identical for `silverloop` and not for the baselines.

Both arms run over two scenario sets, always reported separately and never pooled: the `core` set
(`<scenario-dir>/*.yaml`, which the policy's thresholds were developed against) and the `holdout`
set (`<scenario-dir>/holdout/*.yaml`, which they were not).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

from silverloop.evaluation.fold import BUDGET_WITHHELD_RATIONALE, fold_policy
from silverloop.evaluation.funnel import Funnel, authored_outcomes, compute_funnel
from silverloop.evaluation.holdout import frozen_label, holdout_frozen
from silverloop.evaluation.latent_labels import (
    LabelAgreement,
    StepLabels,
    build_label_agreement,
    label_rows,
)
from silverloop.evaluation.metrics import CONTACT_CAP, DecisionRecord, PolicyMetrics, aggregate
from silverloop.evaluation.outcomes import AuthoredOutcome
from silverloop.evaluation.protocol import (
    ABLATION_REFERENCE,
    ABLATIONS,
    POLICIES,
    PolicyEntry,
)
from silverloop.evaluation.report import check_artifacts, to_markdown, write_artifacts
from silverloop.evaluation.scenario_spec import (
    EvaluationScenario,
    ScenarioSpecError,
    discover_scenarios,
)
from silverloop.evaluation.simulation import EnvironmentStep, SimulationError, replay
from silverloop.evaluation.sweep import SWEEP_THRESHOLDS, SweepRow, run_sweep

HARNESS_VERSION = "2.0.0"
DEFAULT_SEED = 2026
DEFAULT_FAIL_ON = "silverloop"

CORE_SET = "core"
HOLDOUT_SET = "holdout"
HOLDOUT_DIRNAME = "holdout"

UNCAPPED_ARM = "uncapped"
CAPPED_ARM = "capped"
HEADLINE_ARM = CAPPED_ARM
#: Deliberately broken variants of Care+. Excluded from every gate: an ablation that produced
#: no violation would mean the gate it removed was doing nothing.
ABLATION_ARM = "ablation"

#: The single weekly budget every policy is held to in the `capped` arm. It is deliberately the
#: same constant the metrics layer uses for `CONTACT_CAP_BREACH`, so "the cap" means one thing.
UNIFORM_CONTACT_CAP = CONTACT_CAP


@dataclass(frozen=True)
class ScenarioSet:
    name: str
    scenarios: tuple[EvaluationScenario, ...]
    digest: str

    @property
    def scenario_names(self) -> tuple[str, ...]:
        return tuple(scenario.name for scenario in self.scenarios)


@dataclass(frozen=True)
class Arm:
    """One (scenario set, budget) combination, folded over by every registered policy."""

    scenario_set: str
    arm: str
    cap: int | None
    records: dict[str, list[DecisionRecord]]
    metrics: dict[str, PolicyMetrics]

    @property
    def key(self) -> str:
        return f"{self.scenario_set}/{self.arm}"


@dataclass(frozen=True)
class EvaluationResult:
    harness_version: str
    seed: int
    scenario_digest: str
    scenario_names: tuple[str, ...]
    #: Core set, uncapped arm. Retained under the original names so every existing consumer of
    #: `result.records` / `result.metrics` keeps its previous meaning exactly.
    records: dict[str, list[DecisionRecord]]
    metrics: dict[str, PolicyMetrics]
    holdout_digest: str = ""
    holdout_names: tuple[str, ...] = ()
    arms: dict[str, Arm] = field(default_factory=dict)
    #: scenario set -> policy name -> metrics, for the one-gate-at-a-time ablation.
    ablations: dict[str, dict[str, PolicyMetrics]] = field(default_factory=dict)
    #: scenario set -> threshold sensitivity rows for the universal-threshold baseline.
    sweep: dict[str, tuple[SweepRow, ...]] = field(default_factory=dict)
    #: Both ground-truth label columns for every replayed step of both sets, and the agreement
    #: rate between them (M24). Built from the replay alone -- it never sees a decision.
    label_agreement: LabelAgreement = field(default_factory=lambda: LabelAgreement(rows=()))
    #: scenario set -> policy name -> follow-through funnel over the authored `outcomes:` blocks
    #: (M38). Empty stages where no scenario in the set authors outcomes.
    funnels: dict[str, dict[str, Funnel]] = field(default_factory=dict)
    #: Scenario names in each set that author an `outcomes:` block, so a small denominator can be
    #: read next to how few scenarios produced it.
    outcome_scenarios: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def arm_metrics(self, scenario_set: str, arm: str) -> dict[str, PolicyMetrics]:
        return self.arms[f"{scenario_set}/{arm}"].metrics

    @property
    def has_holdout(self) -> bool:
        return bool(self.holdout_names)


def _scenario_digest(paths: list[Path]) -> str:
    hasher = hashlib.sha256()
    for path in sorted(paths, key=lambda candidate: candidate.name):
        hasher.update(path.name.encode("utf-8"))
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _load_set(name: str, directory: Path, seed: int | None) -> ScenarioSet:
    scenarios = discover_scenarios(directory)
    if seed is not None:
        scenarios = [replace(scenario, seed=seed) for scenario in scenarios]
    return ScenarioSet(
        name=name,
        scenarios=tuple(scenarios),
        digest=_scenario_digest([scenario.path for scenario in scenarios]),
    )


def _run_arm(
    entries: tuple[PolicyEntry, ...],
    scenario_set: ScenarioSet,
    replayed: dict[str, list[EnvironmentStep]],
    *,
    arm: str,
    cap: int | None,
) -> Arm:
    records: dict[str, list[DecisionRecord]] = {entry.name: [] for entry in entries}
    for scenario in scenario_set.scenarios:
        steps = replayed[scenario.name]
        for entry in entries:
            records[entry.name].extend(fold_policy(entry, scenario, steps, cap=cap))
    versions = {entry.name: entry.version for entry in entries}
    return Arm(
        scenario_set=scenario_set.name,
        arm=arm,
        cap=cap,
        records=records,
        metrics={name: aggregate(name, versions[name], rows) for name, rows in records.items()},
    )


def run_evaluation(scenario_dir: Path, *, seed: int | None = None) -> EvaluationResult:
    """Replay every scenario exactly once and fold every registered policy over the identical
    stream (D2). Passing `seed` overrides every scenario's own `seed:` field uniformly, for
    demonstrating that the harness is controllable and deterministic; omitting it uses each
    scenario's own seed (every scenario ships with `seed: 2026` today).

    A `holdout/` subdirectory, if present, is loaded as a SEPARATE scenario set and never merged
    into the core set. `discover_scenarios` globs non-recursively, so the core set is unaffected by
    the holdout's existence.
    """
    scenario_dir = Path(scenario_dir)
    core = _load_set(CORE_SET, scenario_dir, seed)

    holdout: ScenarioSet | None = None
    holdout_dir = scenario_dir / HOLDOUT_DIRNAME
    if holdout_dir.is_dir() and any(holdout_dir.glob("*.yaml")):
        holdout = _load_set(HOLDOUT_SET, holdout_dir, seed)

    sets = [candidate for candidate in (core, holdout) if candidate is not None]
    replayed: dict[str, dict[str, list[EnvironmentStep]]] = {
        candidate.name: {scenario.name: replay(scenario) for scenario in candidate.scenarios}
        for candidate in sets
    }

    # Built before any policy runs, from the replay alone, so that the label columns in the
    # artifact are provably decision-independent (M24).
    labels: list[StepLabels] = []
    for candidate in sets:
        for scenario in candidate.scenarios:
            labels.extend(
                label_rows(candidate.name, scenario.name, replayed[candidate.name][scenario.name])
            )

    arms: dict[str, Arm] = {}
    ablations: dict[str, dict[str, PolicyMetrics]] = {}
    sweep: dict[str, tuple[SweepRow, ...]] = {}
    funnels: dict[str, dict[str, Funnel]] = {}
    outcome_scenarios: dict[str, tuple[str, ...]] = {}
    for candidate in sets:
        for arm_name, cap in ((UNCAPPED_ARM, None), (CAPPED_ARM, UNIFORM_CONTACT_CAP)):
            built = _run_arm(POLICIES, candidate, replayed[candidate.name], arm=arm_name, cap=cap)
            arms[built.key] = built
        # Ablations run harness-uncapped so that switching off Care+'s OWN contact-cap gate
        # is observable; a harness cap would silently reinstate it.
        ablation_arm = _run_arm(
            (ABLATION_REFERENCE, *ABLATIONS),
            candidate,
            replayed[candidate.name],
            arm="ablation",
            cap=None,
        )
        arms[ablation_arm.key] = ablation_arm
        ablations[candidate.name] = ablation_arm.metrics
        sweep[candidate.name] = run_sweep(candidate.scenarios, replayed[candidate.name])

        # The funnel is scored on the headline (budget-matched) arm, so "how many offers turned
        # into attendance" is measured on the same budget the correctness table is.
        outcomes: dict[tuple[str, int], AuthoredOutcome] = {}
        authored: list[str] = []
        for scenario in candidate.scenarios:
            indexed = authored_outcomes(scenario.name, scenario.outcomes)
            if indexed:
                authored.append(scenario.name)
            outcomes.update(indexed)
        outcome_scenarios[candidate.name] = tuple(authored)
        capped_arm = arms[f"{candidate.name}/{CAPPED_ARM}"]
        funnels[candidate.name] = {
            name: compute_funnel(records, outcomes) for name, records in capped_arm.records.items()
        }

    core_uncapped = arms[f"{CORE_SET}/{UNCAPPED_ARM}"]
    return EvaluationResult(
        harness_version=HARNESS_VERSION,
        seed=seed if seed is not None else DEFAULT_SEED,
        scenario_digest=core.digest,
        scenario_names=core.scenario_names,
        records=core_uncapped.records,
        metrics=core_uncapped.metrics,
        holdout_digest=holdout.digest if holdout else "",
        holdout_names=holdout.scenario_names if holdout else (),
        arms=arms,
        ablations=ablations,
        sweep=sweep,
        label_agreement=build_label_agreement(labels),
        funnels=funnels,
        outcome_scenarios=outcome_scenarios,
    )


def _is_gated(result: EvaluationResult, fail_on: str) -> bool:
    """A hard violation in ANY arm gates -- including the budget-matched one. Checking only the
    core uncapped arm would let a regression hide in an arm nobody looked at.
    """
    if fail_on == "none":
        return False
    scored = [arm for arm in result.arms.values() if arm.arm != ABLATION_ARM]
    if fail_on == "all":
        return any(
            metrics.violation_total > 0 for arm in scored for metrics in arm.metrics.values()
        )
    return any(arm.metrics[fail_on].violation_total > 0 for arm in scored if fail_on in arm.metrics)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m silverloop.evaluation")
    parser.add_argument("scenario_dir", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--fail-on-violation", default=DEFAULT_FAIL_ON)
    args = parser.parse_args(argv)

    policy_names = {entry.name for entry in POLICIES}
    allowed_fail_on = {"all", "none", *policy_names}
    if args.fail_on_violation not in allowed_fail_on:
        print(
            f"error: --fail-on-violation must be one of: {', '.join(sorted(allowed_fail_on))}",
            file=sys.stderr,
        )
        return 2
    if args.check and args.out is None:
        print("error: --check requires --out", file=sys.stderr)
        return 2

    try:
        result = run_evaluation(args.scenario_dir, seed=args.seed)
    except (ScenarioSpecError, SimulationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(to_markdown(result))

    # The holdout freeze, printed on every run (see `evaluation/holdout.py`). Reported rather than
    # enforced here: `test_holdout_freeze.py` is what fails when the bytes have moved, and this
    # CLI's exit codes are a safety-policy gate, not a process gate.
    if result.has_holdout:
        frozen = holdout_frozen(Path(args.scenario_dir) / HOLDOUT_DIRNAME, result.holdout_digest)
        print(f"holdout_frozen: {frozen_label(frozen)}")

    exit_code = 1 if _is_gated(result, args.fail_on_violation) else 0

    if args.check:
        if not check_artifacts(result, args.out):
            print(
                f"error: artifacts in {args.out} are stale; run `pnpm evaluate` to regenerate",
                file=sys.stderr,
            )
            return 3
    elif args.out is not None:
        write_artifacts(result, args.out)

    return exit_code


__all__ = [
    "BUDGET_WITHHELD_RATIONALE",
    "CAPPED_ARM",
    "CORE_SET",
    "DEFAULT_SEED",
    "HARNESS_VERSION",
    "HEADLINE_ARM",
    "HOLDOUT_SET",
    "SWEEP_THRESHOLDS",
    "UNCAPPED_ARM",
    "UNIFORM_CONTACT_CAP",
    "Arm",
    "EvaluationResult",
    "fold_policy",
    "main",
    "run_evaluation",
]


if __name__ == "__main__":
    raise SystemExit(main())

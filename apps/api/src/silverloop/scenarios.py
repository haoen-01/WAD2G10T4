from __future__ import annotations

import sys
from pathlib import Path

import yaml

from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.sql_repository import SqlAlchemyRepository


def run_scenario(path: Path) -> list[str]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path}: scenario must be a mapping")
    events = document.get("events", [])
    expected = document.get("expected_decisions", [])
    if not isinstance(events, list) or not isinstance(expected, list):
        raise ValueError(f"{path}: events and expected_decisions must be lists")
    person_id = str(document.get("person_id", DEMO_PERSON_ID))

    repository = SqlAlchemyRepository(
        "sqlite+pysqlite:///:memory:", seed=int(document.get("seed", 2026))
    )
    repository.create_schema_for_tests()
    repository.reset(person_id=person_id)
    actual = [
        repository.advance(str(event), person_id=person_id).state.last_decision.value
        for event in events
    ]
    if actual != expected:
        raise AssertionError(f"{path.name}: expected {expected}, received {actual}")

    expected_cases = int(document.get("expected_cases", 0))
    cases = repository.list_cases(person_id=person_id)
    if len(cases) != expected_cases:
        raise AssertionError(f"{path.name}: expected {expected_cases} cases, received {len(cases)}")

    # Optional: the outcome recorded against each piece of outreach the run created, oldest first,
    # with `null` for one still awaiting a reply. Decisions say what the ladder permitted; this
    # says what the loop did about it afterwards -- today, the only outcome a scenario can
    # produce on its own is the response clock recording silence as `no_response`, since nothing
    # here taps a senior's buttons. Scenarios that omit the key are unchanged.
    if "expected_outcomes" in document:
        expected_outcomes = document["expected_outcomes"]
        if not isinstance(expected_outcomes, list):
            raise ValueError(f"{path}: expected_outcomes must be a list")
        # Oldest first, by `(created_at, intervention_id)` -- `list_interventions` returns the
        # reverse, and a scenario reads in the order the loop created them.
        interventions = sorted(
            repository.list_interventions(person_id=person_id),
            key=lambda intervention: (intervention.created_at, intervention.intervention_id),
        )
        actual_outcomes = [intervention.outcome for intervention in interventions]
        if actual_outcomes != expected_outcomes:
            raise AssertionError(
                f"{path.name}: expected outcomes {expected_outcomes}, received {actual_outcomes}"
            )
    repository.close()
    return actual


def main(directory: str) -> None:
    paths = sorted(Path(directory).glob("*.yaml"))
    if not paths:
        raise SystemExit(f"No scenario files found in {directory}")
    for path in paths:
        decisions = run_scenario(path)
        print(f"PASS {path.name}: {' -> '.join(decisions)}")
    print(f"{len(paths)} deterministic safety scenarios passed")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m silverloop.scenarios <scenario-directory>")
    main(sys.argv[1])

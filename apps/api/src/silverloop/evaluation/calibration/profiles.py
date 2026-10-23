"""Simulated coordinators: three fixed, deterministic ways of answering a review case.

SYNTHETIC. None of these is a model of a real coordinator; each is a rule written down so the
evaluation can ask "what does calibration do when the people teaching it are imperfect?". A
profile sees only what a coordinator would plausibly know about the episode -- the authored latent
label -- and the day the case reached them. It never sees the review setting.

- `accurate`: not a concern for anything that is not review-worthy; agrees with a review-worthy
  case, and says it should have reached them sooner when it opened after `should_reach_by_day`.
- `dismissive`: resolves every case as not a concern, review-worthy or not.
- `over_cautious`: agrees with every case and says every one should have reached them sooner.

Agreement is recorded as `acknowledged`, the way the guided threshold sequence records it: a
resolved agreement would close the concern while the decline continues and reopen it the next day,
which no coordinator agreeing with a case means.

Pure: stdlib and `silverloop.models` enums only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from silverloop.evaluation.calibration.sequences import Episode
from silverloop.models import CaseStatus, HumanAction, OverrideReason

ProfileName = Literal["accurate", "dismissive", "over_cautious"]
PROFILES: tuple[ProfileName, ...] = ("accurate", "dismissive", "over_cautious")

PROFILE_DESCRIPTIONS: dict[ProfileName, str] = {
    "accurate": (
        "Not a concern for benign episodes; agrees with review-worthy ones, and says a case "
        "should have reached them sooner only when it opened after the episode's latest "
        "acceptable day."
    ),
    "dismissive": "Resolves every case as not a concern, including review-worthy ones.",
    "over_cautious": "Agrees with every case and says every one should have reached them sooner.",
}

REVIEW_NOTE = "Simulated coordinator judgement (synthetic evaluation)."


@dataclass(frozen=True)
class Judgement:
    status: CaseStatus
    human_action: HumanAction
    override_reason: OverrideReason | None
    reached_too_late: bool


_NOT_A_CONCERN = Judgement(
    CaseStatus.RESOLVED, HumanAction.OVERRIDE, OverrideReason.NOT_A_CONCERN, reached_too_late=False
)


def judge(profile: ProfileName, episode: Episode | None, opened_day: int) -> Judgement:
    """How `profile` answers a case that opened on sequence day `opened_day` during `episode`.

    `episode` is `None` for a case opened outside every authored episode; every profile treats
    that as it would a benign episode.
    """
    if profile == "dismissive":
        return _NOT_A_CONCERN
    if profile == "over_cautious":
        return Judgement(CaseStatus.ACKNOWLEDGED, HumanAction.AGREE, None, reached_too_late=True)
    if profile == "accurate":
        if episode is None or not episode.review_worthy:
            return _NOT_A_CONCERN
        late = episode.should_reach_by_day is not None and opened_day > episode.should_reach_by_day
        return Judgement(CaseStatus.ACKNOWLEDGED, HumanAction.AGREE, None, reached_too_late=late)
    raise ValueError(f"Unknown profile {profile!r}")


def counts_toward_loosening(judgement: Judgement) -> bool:
    """The one judgement the fixed rule counts toward a looser setting: a resolved override for
    `not_a_concern`, not marked as reaching the coordinator too late."""
    return (
        judgement.status is CaseStatus.RESOLVED
        and judgement.human_action is HumanAction.OVERRIDE
        and judgement.override_reason is OverrideReason.NOT_A_CONCERN
        and not judgement.reached_too_late
    )


__all__ = [
    "PROFILES",
    "PROFILE_DESCRIPTIONS",
    "REVIEW_NOTE",
    "Judgement",
    "ProfileName",
    "counts_toward_loosening",
    "judge",
]

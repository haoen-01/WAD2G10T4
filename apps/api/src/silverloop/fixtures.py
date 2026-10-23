from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from silverloop.local_time import at_local
from silverloop.models import (
    ActivityAvailability,
    ActivityBooking,
    ActivityCandidate,
    ActivityIntensity,
    ActivityLocation,
    ActivitySource,
    ContextSignal,
    DailyMetric,
    DistanceBasis,
    IndoorOutdoor,
    IntegrationStatus,
    Programme,
    SocialPreference,
)
from silverloop.ontology import FORMAT_LABEL, ActivityFamily, ActivityType, Format

DEMO_PERSON_ID = "mdm-lim"


@dataclass(frozen=True)
class PersonaProfile:
    """Curated identity for a seeded/synthetic person. See fixtures.py D3/D4.

    Fields below `seed_offset` (F5) parameterise `synthetic_history`'s generic generator (used by
    every persona except `DEMO_PERSON_ID`, whose history stays hardcoded for byte-identical
    compatibility -- see `synthetic_history`). `mdm-lim`'s own profile carries the equivalent
    values for documentation only; they are never read for her.

    `is_playbook_persona=False` marks a persona that is **not** in the product playbook -- purely
    synthetic, invented to exercise a metric the playbook personas leave dead. Never imply these
    came from research or interviews.

    `age` and `context_note` are purely descriptive biography surfaced to the UI -- one short,
    factual line each, never a diagnosis or clinical inference. For synthetic personas
    (`is_playbook_persona=False`), `context_note` describes the behavioural pattern the persona
    was invented to exercise, not a real person.
    """

    person_id: str
    display_name: str
    preferred_language: str
    age: int | None = None
    context_note: str | None = None
    seed_offset: int = 0
    baseline_steps: int = 5850
    step_std: float = 420.0
    baseline_active_minutes: int = 42
    baseline_sleep_hours: float = 7.0
    baseline_wear_hours: float = 13.6
    tracker_adherence: float = 0.97
    history_days: int = 28
    weekend_multiplier: float = 1.0
    trend_per_day: float = 0.0
    is_playbook_persona: bool = True
    notes: str = ""


DEMO_PERSONAS: Mapping[str, PersonaProfile] = {
    DEMO_PERSON_ID: PersonaProfile(
        person_id=DEMO_PERSON_ID,
        display_name="Mdm Lim",
        preferred_language="English / Mandarin",
        age=74,
        context_note="Socially motivated; responds well to group-based encouragement.",
        seed_offset=0,
        baseline_steps=5850,
        step_std=420.0,
        baseline_active_minutes=42,
        baseline_sleep_hours=7.0,
        baseline_wear_hours=13.6,
        tracker_adherence=0.99,
        history_days=28,
        is_playbook_persona=True,
        notes=(
            "Playbook primary persona. 29-day fixture (28 history + 1 current), unchanged since "
            "before F5 -- see the F5 compatibility note in docs/testing.md."
        ),
    ),
    "mr-ravi": PersonaProfile(
        person_id="mr-ravi",
        display_name="Mr Ravi",
        preferred_language="English / Tamil",
        age=68,
        context_note="Low but stable activity; has disclosed knee discomfort.",
        seed_offset=5000,
        baseline_steps=2400,
        step_std=160.0,
        baseline_active_minutes=17,
        baseline_sleep_hours=6.8,
        baseline_wear_hours=13.0,
        tracker_adherence=0.96,
        history_days=90,
        is_playbook_persona=True,
        notes=(
            "Playbook primary persona: low but stable baseline, knee discomfort disclosed. "
            "Demo purpose: defeat a universal fixed step threshold (playbook §2)."
        ),
    ),
    "mdm-siti": PersonaProfile(
        person_id="mdm-siti",
        display_name="Mdm Siti",
        preferred_language="English / Malay",
        age=81,
        context_note="Irregular tracker sync; limited smartphone use.",
        seed_offset=10000,
        baseline_steps=3200,
        step_std=260.0,
        baseline_active_minutes=20,
        baseline_sleep_hours=7.2,
        baseline_wear_hours=12.0,
        tracker_adherence=0.55,
        history_days=90,
        is_playbook_persona=True,
        notes=(
            "Playbook primary persona: irregular sync, limited smartphone use. Demo purpose: "
            "data-quality discrimination -- low tracker adherence must yield audited NO_ACTION, "
            "never an inference from missing data."
        ),
    ),
    "mr-tan": PersonaProfile(
        person_id="mr-tan",
        display_name="Mr Tan",
        preferred_language="English / Hokkien",
        age=70,
        context_note=(
            "Synthetic profile; shows repeated mild activity dips used to test the weekly "
            "contact-fatigue cap."
        ),
        seed_offset=15000,
        baseline_steps=3200,
        step_std=220.0,
        baseline_active_minutes=26,
        baseline_sleep_hours=7.0,
        baseline_wear_hours=13.2,
        tracker_adherence=0.95,
        history_days=90,
        is_playbook_persona=False,
        notes=(
            "SYNTHETIC -- not in the product playbook; no research or interview basis. Invented "
            "to demonstrate the weekly contact-fatigue cap: repeated mild dips draw repeated "
            "contact from an uncapped baseline policy, which Care+ suppresses."
        ),
    ),
    "mdm-devi": PersonaProfile(
        person_id="mdm-devi",
        display_name="Mdm Devi",
        preferred_language="English / Tamil",
        age=76,
        context_note=("Synthetic profile; shows a gradual multi-week activity decline pattern."),
        seed_offset=20000,
        baseline_steps=6000,
        step_std=380.0,
        baseline_active_minutes=38,
        baseline_sleep_hours=7.1,
        baseline_wear_hours=13.4,
        tracker_adherence=0.97,
        history_days=90,
        weekend_multiplier=1.0,
        trend_per_day=-18.0,
        is_playbook_persona=False,
        notes=(
            "SYNTHETIC -- not in the product playbook; no research or interview basis. Invented "
            "to give the evaluation harness a second, independent persistent-decline case "
            "(playbook required scenario #4: gradual multi-week decline) so M2/M3 are not "
            "measured on a single data point."
        ),
    ),
    "mdm-wong": PersonaProfile(
        person_id="mdm-wong",
        display_name="Mdm Wong",
        preferred_language="English / Cantonese",
        age=72,
        context_note="Synthetic profile; activity naturally swings a lot from week to week.",
        seed_offset=25000,
        baseline_steps=5800,
        step_std=1620.0,
        weekend_multiplier=0.70,
        history_days=90,
        tracker_adherence=0.97,
        is_playbook_persona=False,
        notes=(
            "SYNTHETIC -- not in the product playbook; no research or interview basis. Invented "
            "to exercise the review-threshold calibrator: a routine whose ordinary swings cross "
            "the default review threshold."
        ),
    ),
}


def persona_profile(person_id: str) -> PersonaProfile:
    """Look up a curated persona profile.

    Falls back to a generic profile (display name equal to the opaque id, English) for any
    `person_id` outside `DEMO_PERSONAS` -- e.g. self-serve registrations or test-only people.
    F5 owns growing `DEMO_PERSONAS`; this fallback keeps the shared seam usable before that
    lands without requiring every caller to special-case an unknown persona.

    This lookup alone never provisions a person record: `SqlAlchemyRepository.reset()` only
    auto-creates a `PersonRow` for a curated persona (a key in `DEMO_PERSONAS`); any other
    `person_id` requires the caller to pass `allow_new_person=True` explicitly.
    """
    return DEMO_PERSONAS.get(
        person_id,
        PersonaProfile(person_id=person_id, display_name=person_id, preferred_language="English"),
    )


def persona_seed(person_id: str, base_seed: int) -> int:
    """The single seam both the repository and the evaluation harness use to derive a person's
    deterministic fixture seed. `persona_seed(DEMO_PERSON_ID, 2026)` MUST return `2026` unchanged
    -- every fixture, scenario and e2e assertion is pinned to that value.
    """
    return base_seed + persona_profile(person_id).seed_offset


def _mdm_lim_history(seed: int) -> tuple[list[DailyMetric], DailyMetric]:
    """Exact, unmodified pre-F5 generation for `DEMO_PERSON_ID`. Do not touch this function --
    its output is pinned byte-for-byte by every existing scenario, e2e assertion and committed
    evaluation artifact. See the F5 compatibility note in docs/testing.md.
    """
    rng = random.Random(seed)
    start = date(2026, 7, 21)
    history = [
        DailyMetric(
            day=start + timedelta(days=index),
            steps=max(3800, int(rng.gauss(5850, 420))),
            active_minutes=max(18, int(rng.gauss(42, 6))),
            sleep_hours=round(min(8.4, max(5.6, rng.gauss(7.0, 0.45))), 1),
            wear_hours=round(min(16, max(10, rng.gauss(13.6, 0.8))), 1),
            source="synthetic",
        )
        for index in range(28)
    ]
    current = DailyMetric(
        day=start + timedelta(days=28),
        steps=5720,
        active_minutes=40,
        sleep_hours=7.1,
        wear_hours=13.5,
        source="synthetic",
    )
    return history, current


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _generic_persona_history(
    seed: int, profile: PersonaProfile
) -> tuple[list[DailyMetric], DailyMetric]:
    """F5 generic fixture generator, used by every curated persona except `DEMO_PERSON_ID`.

    Follows playbook §12: seeded RNG, clipped-normal daily steps around the persona's own
    baseline, a weekday/weekend multiplier, MVPA correlated with (but not a deterministic
    conversion of) steps, bounded sleep variation, and independent non-wear/sync-failure days
    driven by `tracker_adherence`. The final day is always a clean, full-wear reading close to
    baseline (mirroring `DEMO_PERSON_ID`'s hand-picked `current` value) so every scenario begins
    from a predictable, fully-observed starting point; only the preceding history days vary.
    """
    rng = random.Random(seed)
    start = date(2026, 5, 1)
    days: list[DailyMetric] = []
    for index in range(profile.history_days):
        day = start + timedelta(days=index)
        weekend_factor = profile.weekend_multiplier if day.weekday() >= 5 else 1.0
        mean_steps = profile.baseline_steps * weekend_factor + profile.trend_per_day * index
        raw_steps = rng.gauss(mean_steps, profile.step_std)
        synced = rng.random() < profile.tracker_adherence
        if synced:
            steps = int(
                _clip(raw_steps, profile.baseline_steps * 0.35, profile.baseline_steps * 1.9)
            )
            wear_hours = round(_clip(rng.gauss(profile.baseline_wear_hours, 0.8), 9.0, 16.0), 1)
            mvpa_mean = profile.baseline_active_minutes * (steps / max(1, mean_steps))
            active_minutes = int(_clip(rng.gauss(mvpa_mean, 6), 8, 90))
            sleep_hours = round(_clip(rng.gauss(profile.baseline_sleep_hours, 0.5), 4.5, 9.0), 1)
        else:
            # Non-wear / sync-failure day: the tracker captured little to nothing.
            wear_hours = round(_clip(rng.gauss(2.0, 1.2), 0.0, 6.5), 1)
            steps = int(_clip(raw_steps * (wear_hours / 24), 0, profile.baseline_steps))
            active_minutes = int(_clip(steps / 90, 0, 20))
            sleep_hours = None
        days.append(
            DailyMetric(
                day=day,
                steps=max(0, steps),
                active_minutes=max(0, active_minutes),
                sleep_hours=sleep_hours,
                wear_hours=wear_hours,
                source="synthetic",
            )
        )
    current = DailyMetric(
        day=start + timedelta(days=profile.history_days),
        steps=int(profile.baseline_steps + profile.trend_per_day * profile.history_days),
        active_minutes=profile.baseline_active_minutes,
        sleep_hours=profile.baseline_sleep_hours,
        wear_hours=profile.baseline_wear_hours,
        source="synthetic",
    )
    return days, current


def synthetic_history(
    seed: int, profile: PersonaProfile | None = None
) -> tuple[list[DailyMetric], DailyMetric]:
    """Generate a person's fixture history.

    `profile` defaults to `DEMO_PERSON_ID`'s profile, which always routes to `_mdm_lim_history`
    -- the exact pre-F5 code path, unchanged -- so `synthetic_history(2026)` alone stays
    byte-identical. Every other curated persona routes to `_generic_persona_history`.
    """
    profile = profile or persona_profile(DEMO_PERSON_ID)
    if profile.person_id == DEMO_PERSON_ID:
        return _mdm_lim_history(seed)
    return _generic_persona_history(seed, profile)


def synthetic_programmes() -> list[Programme]:
    base_day = date(2026, 8, 24)
    return [
        Programme(
            programme_id="aac-chair-mobility",
            name="Chair Mobility & Balance",
            venue="Kampung Admiralty AAC",
            distance_km=0.7,
            next_session=datetime.combine(base_day, time(9, 30), tzinfo=UTC),
            accessibility=["seated option", "lift access", "Mandarin facilitator"],
        ),
        Programme(
            programme_id="aac-sheltered-walk",
            name="Sheltered Morning Walk",
            venue="Woodlands Community Hub",
            distance_km=1.2,
            next_session=datetime.combine(base_day + timedelta(days=1), time(8, 0), tzinfo=UTC),
            accessibility=["sheltered route", "slow-paced group"],
        ),
    ]


@dataclass(frozen=True)
class _Session:
    """One occurrence of a programme: which day of the coming week, and the local hour."""

    days_ahead: int
    hour: int
    minute: int = 0


@dataclass(frozen=True)
class _Programme:
    """A recurring AAC-style class, from which one candidate is emitted per session.

    Real active-ageing programmes run weekly, not once, and the catalogue has to reflect that or
    almost every request lands on a day nothing happens. Each occurrence becomes its own
    `ActivityCandidate` because that is what a person actually chooses between -- "Tuesday morning
    chair mobility" is a different answer from "Thursday evening chair mobility".

    Every field a person needs in order to *go* is carried here rather than left to be chased
    down elsewhere: the address and postal code, how to get there, how long it runs, whether to
    book, who to call, and what to bring. Cross-referencing three sources is what stops someone
    attending, and it falls hardest on the people least able to do the chasing.
    """

    slug: str
    title: str
    provider: str
    venue: str
    address: str
    postal_code: str
    distance_m: int
    # Hand-authored, never inferred. `ontology.normalise` can read "Sheltered Morning Walk" as a
    # walk, and `test_ontology.py` asserts it reproduces every one of these -- but the catalogue
    # is the authority and the normaliser is the check, not the other way round. A real directory
    # feed would carry these as fields too; guessing them from prose in product code is how a
    # listing acquires a fact nobody ever asserted.
    activity_type: ActivityType
    activity_families: tuple[ActivityFamily, ...]
    format: Format
    description: str
    indoor_outdoor: IndoorOutdoor
    social_shape: SocialPreference
    intensity: ActivityIntensity | None
    duration_minutes: int | None
    accessibility: tuple[str, ...]
    languages: tuple[str, ...]
    getting_there: tuple[str, ...]
    what_to_bring: tuple[str, ...]
    good_to_know: tuple[str, ...]
    booking: ActivityBooking
    booking_note: str | None
    contact_phone: str | None
    contact_note: str | None
    sessions: tuple[_Session, ...]
    price: str | None = None
    availability: ActivityAvailability = ActivityAvailability.AVAILABLE
    capacity: int | None = None


# Fourteen programmes across the week, morning through evening, each described fully enough to
# turn up to without ringing round first.
#
# The honesty rules from F26 still hold and are deliberately visible: two programmes carry no
# language tag (renders "Not listed", never a guess), one has no fixed session time, one has no
# phone number, one is full, and two have unknown intensity. Those are facts the catalogue does
# not have -- not gaps to be filled in with something plausible.
_PROGRAMMES: tuple[_Programme, ...] = (
    _Programme(
        slug="chair-mobility",
        title="Chair Mobility & Balance",
        provider="Kampung Admiralty AAC",
        venue="Kampung Admiralty Active Ageing Centre",
        address="676 Woodlands Drive 71, #02-01",
        postal_code="730676",
        distance_m=700,
        activity_type=ActivityType.CHAIR_EXERCISE,
        activity_families=(ActivityFamily.MOVEMENT,),
        format=Format.GROUP_CLASS,
        description=(
            "A seated class working through shoulders, ankles and legs at an easy pace, with a "
            "facilitator who counts nobody down and corrects nobody in front of the group."
        ),
        indoor_outdoor=IndoorOutdoor.INDOOR,
        social_shape=SocialPreference.SOCIAL,
        intensity=ActivityIntensity.LIGHT,
        duration_minutes=45,
        accessibility=("seated throughout", "lift access", "accessible toilet", "hearing loop"),
        languages=("English", "Mandarin"),
        getting_there=(
            "5 minutes on foot from Admiralty MRT (NS10), exit A",
            "Bus 913, 964 to Blk 676 Woodlands Dr 71",
        ),
        what_to_bring=("Comfortable clothes", "A water bottle"),
        good_to_know=(
            "Chairs are provided; nothing is done on the floor",
            "Arrive any time in the first 10 minutes",
        ),
        booking=ActivityBooking.DROP_IN,
        booking_note="Just turn up. No need to register.",
        contact_phone="6555 0101",
        contact_note="Ask for the activities desk",
        sessions=(_Session(1, 9, 30), _Session(3, 9, 30), _Session(5, 9, 30)),
        price="Free",
    ),
    _Programme(
        slug="sheltered-walk",
        title="Sheltered Morning Walk",
        provider="Woodlands Community Hub",
        venue="Woodlands Community Hub",
        address="30 Woodlands Avenue 1",
        postal_code="739065",
        distance_m=1200,
        activity_type=ActivityType.WALKING,
        activity_families=(
            ActivityFamily.MOVEMENT,
            ActivityFamily.SOCIAL,
        ),
        format=Format.GROUP_ACTIVITY,
        description=(
            "A slow loop along covered walkways, stopping at benches whenever anyone wants to. "
            "The group waits; nobody is left behind."
        ),
        indoor_outdoor=IndoorOutdoor.SHELTERED,
        social_shape=SocialPreference.SOCIAL,
        intensity=ActivityIntensity.LIGHT,
        duration_minutes=40,
        accessibility=(
            "sheltered route",
            "rest benches every 100m",
            "step-free",
            "toilets on route",
        ),
        languages=("English", "Malay"),
        getting_there=(
            "8 minutes on foot from Woodlands MRT (NS9/TE2), exit C",
            "Bus 900, 903 to Woodlands Interchange",
        ),
        what_to_bring=("Walking shoes", "A hat if you feel the heat"),
        good_to_know=(
            "Runs in light rain, as the route is covered end to end",
            "Walking aids are welcome and the pace is set by the slowest walker",
        ),
        booking=ActivityBooking.DROP_IN,
        booking_note="Meet at the main lobby. No need to register.",
        contact_phone="6555 0202",
        contact_note=None,
        sessions=(_Session(1, 8, 0), _Session(4, 8, 0)),
        price="Free",
    ),
    _Programme(
        slug="evening-social",
        title="Evening Tea & Chat",
        provider="Marsiling Active Ageing Centre",
        venue="Marsiling Active Ageing Centre",
        address="Blk 8 Marsiling Drive, #01-32",
        postal_code="730008",
        distance_m=850,
        activity_type=ActivityType.SOCIAL_MEETUP,
        activity_families=(ActivityFamily.SOCIAL,),
        format=Format.DROP_IN_GROUP,
        description=(
            "Tea, biscuits and conversation. No programme and nothing to join in with. People "
            "come to sit with others and leave when they like."
        ),
        indoor_outdoor=IndoorOutdoor.INDOOR,
        social_shape=SocialPreference.SOCIAL,
        intensity=ActivityIntensity.LIGHT,
        duration_minutes=90,
        accessibility=("step-free entrance", "seating throughout", "accessible toilet"),
        languages=("English", "Mandarin", "Hokkien"),
        getting_there=(
            "6 minutes on foot from Marsiling MRT (NS8), exit B",
            "Bus 856, 913 to Blk 8 Marsiling Dr",
        ),
        what_to_bring=(),
        good_to_know=(
            "Come and go as you please; there is no start or finish",
            "The room is well lit and quiet enough to hold a conversation",
        ),
        booking=ActivityBooking.DROP_IN,
        booking_note="Just come in. Nothing to sign.",
        contact_phone="6555 0303",
        contact_note="Ask for Mei Ling",
        sessions=(_Session(0, 18, 30), _Session(2, 18, 30), _Session(5, 18, 30)),
        price="Free",
    ),
    _Programme(
        slug="evening-stretch",
        title="Gentle Evening Stretch",
        provider="Woodlands Community Hub",
        venue="Woodlands Community Hub",
        address="30 Woodlands Avenue 1, Studio 2",
        postal_code="739065",
        distance_m=1200,
        activity_type=ActivityType.STRETCH,
        activity_families=(
            ActivityFamily.MOVEMENT,
            ActivityFamily.MIND_BODY,
        ),
        format=Format.GROUP_CLASS,
        description=(
            "Standing and seated stretches in a cool room, ending with five minutes of quiet "
            "breathing. Suits people who prefer to be out after the heat of the day."
        ),
        indoor_outdoor=IndoorOutdoor.INDOOR,
        social_shape=SocialPreference.SOCIAL,
        intensity=ActivityIntensity.LIGHT,
        duration_minutes=50,
        accessibility=("seated option for every movement", "lift access", "accessible toilet"),
        languages=("English",),
        getting_there=(
            "8 minutes on foot from Woodlands MRT (NS9/TE2), exit C",
            "Bus 900, 903 to Woodlands Interchange",
        ),
        what_to_bring=("Loose clothing", "A water bottle"),
        good_to_know=("Mats are provided but nothing requires getting down to the floor",),
        booking=ActivityBooking.DROP_IN,
        booking_note="Turn up 5 minutes early for a seat near the front.",
        contact_phone="6555 0202",
        contact_note=None,
        sessions=(_Session(1, 19, 0), _Session(4, 19, 0)),
        price="Free",
    ),
    _Programme(
        slug="evening-walk",
        title="Cool-of-Day Park Walk",
        provider="Admiralty Park volunteers",
        venue="Admiralty Park",
        address="Woodlands Avenue 12, main entrance",
        postal_code="738344",
        distance_m=1600,
        activity_type=ActivityType.WALKING,
        activity_families=(
            ActivityFamily.MOVEMENT,
            ActivityFamily.NATURE,
            ActivityFamily.SOCIAL,
        ),
        format=Format.GROUP_ACTIVITY,
        description=(
            "An easy walk on flat paved paths once the sun is off them, led by two volunteers "
            "who stay at the back with anyone taking their time."
        ),
        indoor_outdoor=IndoorOutdoor.OUTDOOR,
        social_shape=SocialPreference.SOCIAL,
        intensity=ActivityIntensity.MODERATE,
        duration_minutes=45,
        accessibility=("paved path throughout", "rest benches", "toilets at the entrance"),
        languages=(),
        getting_there=(
            "12 minutes on foot from Admiralty MRT (NS10)",
            "Bus 964 to Admiralty Park",
        ),
        what_to_bring=("Walking shoes", "Insect repellent if you are prone to bites"),
        good_to_know=(
            "Cancelled in heavy rain, so ring ahead if the weather looks poor",
            "Paths are lit but bring a torch if you prefer",
        ),
        booking=ActivityBooking.DROP_IN,
        booking_note="Meet at the main entrance sign.",
        contact_phone=None,
        contact_note="No phone line; ask at Kampung Admiralty AAC",
        sessions=(_Session(2, 19, 30), _Session(6, 19, 30)),
    ),
    _Programme(
        slug="tai-chi",
        title="Tai Chi in the Park",
        provider="Woodlands Wellness Circle",
        venue="Admiralty Park lawn",
        address="Woodlands Avenue 12, open lawn",
        postal_code="738344",
        distance_m=2100,
        activity_type=ActivityType.TAI_CHI,
        activity_families=(
            ActivityFamily.MIND_BODY,
            ActivityFamily.MOVEMENT,
            ActivityFamily.NATURE,
        ),
        format=Format.GROUP_CLASS,
        description="A slow, standing form practised on flat grass in the shade of the tree line.",
        indoor_outdoor=IndoorOutdoor.OUTDOOR,
        social_shape=SocialPreference.SOCIAL,
        intensity=ActivityIntensity.LIGHT,
        duration_minutes=60,
        accessibility=("flat ground", "shaded area"),
        languages=("Mandarin",),
        getting_there=("12 minutes on foot from Admiralty MRT (NS10)", "Bus 964 to Admiralty Park"),
        what_to_bring=("Flat shoes",),
        good_to_know=("This term is full, but the centre keeps a waiting list",),
        booking=ActivityBooking.REGISTER,
        booking_note="Register at the centre. Currently full; ask to be put on the list.",
        contact_phone="6555 0404",
        contact_note=None,
        sessions=(_Session(2, 8, 30), _Session(5, 8, 30)),
        availability=ActivityAvailability.FULL,
        capacity=20,
        price="Free",
    ),
    _Programme(
        slug="karaoke",
        title="Karaoke & Social Hour",
        provider="Toa Payoh Active Ageing Centre",
        venue="Toa Payoh Active Ageing Centre",
        address="Blk 177 Toa Payoh Central, #01-142",
        postal_code="310177",
        distance_m=3400,
        activity_type=ActivityType.KARAOKE,
        activity_families=(
            ActivityFamily.SOCIAL,
            ActivityFamily.CREATIVE,
        ),
        format=Format.DROP_IN_GROUP,
        description=(
            "Songs in three languages, a long song list and no obligation to sing. Plenty of "
            "people come only to listen."
        ),
        indoor_outdoor=IndoorOutdoor.INDOOR,
        social_shape=SocialPreference.SOCIAL,
        intensity=None,
        duration_minutes=120,
        accessibility=("lift access", "seated throughout", "accessible toilet"),
        languages=("English", "Mandarin", "Hokkien"),
        getting_there=(
            "4 minutes on foot from Toa Payoh MRT (NS19), exit B",
            "Bus 88, 145, 235 to Toa Payoh Interchange",
        ),
        what_to_bring=("$2 for the room",),
        good_to_know=("It gets loud, so sit near the back if that is easier",),
        booking=ActivityBooking.DROP_IN,
        booking_note="Pay at the door. No need to register.",
        contact_phone="6555 0505",
        contact_note=None,
        sessions=(_Session(3, 14, 0), _Session(6, 14, 0)),
        price="$2",
    ),
    _Programme(
        slug="gardening",
        title="Community Gardening",
        provider="Woodlands Green Fingers",
        venue="Block 512 rooftop garden",
        address="Blk 512 Woodlands Drive 14, rooftop",
        postal_code="730512",
        distance_m=650,
        activity_type=ActivityType.GARDENING,
        activity_families=(
            ActivityFamily.NATURE,
            ActivityFamily.CREATIVE,
            ActivityFamily.SOCIAL,
        ),
        format=Format.GROUP_ACTIVITY,
        description=(
            "Raised beds at waist height, so there is no kneeling or bending. Tools, gloves and "
            "seating are provided, and you can stop whenever you like."
        ),
        indoor_outdoor=IndoorOutdoor.OUTDOOR,
        social_shape=SocialPreference.SOCIAL,
        intensity=ActivityIntensity.LIGHT,
        duration_minutes=60,
        accessibility=(
            "raised beds, no kneeling needed",
            "lift access to roof",
            "seating",
            "shade",
        ),
        languages=("English", "Mandarin"),
        getting_there=(
            "7 minutes on foot from Admiralty MRT (NS10)",
            "Bus 913 to Blk 512 Woodlands Dr 14",
        ),
        what_to_bring=("A hat", "Water"),
        good_to_know=(
            "Tools and gloves are provided",
            "Moves indoors to the void deck if it rains",
        ),
        booking=ActivityBooking.DROP_IN,
        booking_note="Turn up at the rooftop. No need to register.",
        contact_phone="6555 0606",
        contact_note="Ask for the garden group",
        sessions=(_Session(1, 9, 0), _Session(4, 16, 30)),
        price="Free",
    ),
    _Programme(
        slug="brisk-walk",
        title="Brisk Neighbourhood Walk Group",
        provider="Woodlands Wellness Circle",
        venue="Woodlands Town Garden",
        address="Woodlands Street 13, garden entrance",
        postal_code="730013",
        distance_m=4600,
        activity_type=ActivityType.WALKING,
        activity_families=(
            ActivityFamily.MOVEMENT,
            ActivityFamily.SOCIAL,
        ),
        format=Format.GROUP_ACTIVITY,
        description=(
            "A faster walk for people who already walk regularly and want company doing it."
        ),
        indoor_outdoor=IndoorOutdoor.OUTDOOR,
        social_shape=SocialPreference.SOCIAL,
        intensity=ActivityIntensity.MODERATE,
        duration_minutes=50,
        accessibility=("paved route", "some gentle slopes"),
        languages=("English", "Tamil"),
        getting_there=(
            "10 minutes on foot from Woodlands MRT (NS9/TE2)",
            "Bus 903, 911 to Woodlands St 13",
        ),
        what_to_bring=("Walking shoes", "Water"),
        good_to_know=("The pace is brisk; the sheltered morning walk is gentler",),
        booking=ActivityBooking.DROP_IN,
        booking_note="Meet at the garden entrance.",
        contact_phone="6555 0404",
        contact_note=None,
        sessions=(_Session(2, 7, 30), _Session(6, 7, 30)),
    ),
    _Programme(
        slug="seated-strength",
        title="Seated Strength Basics",
        provider="Kampung Admiralty AAC",
        venue="Kampung Admiralty Active Ageing Centre",
        address="676 Woodlands Drive 71, #02-03 quiet room",
        postal_code="730676",
        distance_m=900,
        activity_type=ActivityType.CHAIR_EXERCISE,
        activity_families=(ActivityFamily.MOVEMENT,),
        format=Format.SELF_GUIDED,
        description=(
            "A printed card of six seated movements you work through at your own pace, in a room "
            "kept free for it. Staff are next door if you want to ask something."
        ),
        indoor_outdoor=IndoorOutdoor.INDOOR,
        social_shape=SocialPreference.SOLO,
        intensity=ActivityIntensity.LIGHT,
        duration_minutes=30,
        accessibility=("seated throughout", "lift access", "quiet room", "accessible toilet"),
        languages=("English",),
        getting_there=(
            "5 minutes on foot from Admiralty MRT (NS10), exit A",
            "Bus 913, 964 to Blk 676 Woodlands Dr 71",
        ),
        what_to_bring=("Comfortable clothes",),
        good_to_know=("Nobody watches or counts; it is yours to do as slowly as you like",),
        booking=ActivityBooking.DROP_IN,
        booking_note="Ask at the desk for the quiet room.",
        contact_phone="6555 0101",
        contact_note=None,
        sessions=(_Session(1, 14, 30), _Session(4, 14, 30)),
        price="Free",
    ),
    _Programme(
        slug="garden-stretch",
        title="Independent Garden Stretch",
        provider="Block 512 rooftop garden",
        venue="Block 512 rooftop garden",
        address="Blk 512 Woodlands Drive 14, rooftop",
        postal_code="730512",
        distance_m=500,
        activity_type=ActivityType.STRETCH,
        activity_families=(
            ActivityFamily.MOVEMENT,
            ActivityFamily.NATURE,
        ),
        format=Format.SELF_GUIDED,
        description=(
            "Open rooftop time with seating and shade, for stretching or simply sitting out."
        ),
        indoor_outdoor=IndoorOutdoor.OUTDOOR,
        social_shape=SocialPreference.SOLO,
        intensity=ActivityIntensity.LIGHT,
        duration_minutes=None,
        accessibility=("lift access to roof", "seating", "shade"),
        languages=(),
        getting_there=("7 minutes on foot from Admiralty MRT (NS10)",),
        what_to_bring=("A hat", "Water"),
        good_to_know=("Nobody is running anything; the space is simply open",),
        booking=ActivityBooking.DROP_IN,
        booking_note="Nothing to book.",
        contact_phone=None,
        contact_note="No phone line for this one",
        sessions=(_Session(0, 15, 0), _Session(3, 15, 0)),
    ),
    _Programme(
        slug="craft-circle",
        title="Afternoon Craft Circle",
        provider="Marsiling Active Ageing Centre",
        venue="Marsiling Active Ageing Centre",
        address="Blk 8 Marsiling Drive, #01-32",
        postal_code="730008",
        distance_m=850,
        activity_type=ActivityType.ARTS_CRAFTS,
        activity_families=(
            ActivityFamily.CREATIVE,
            ActivityFamily.SOCIAL,
        ),
        format=Format.DROP_IN_GROUP,
        description=(
            "Beading, simple sewing and card-making around one big table. Materials are provided "
            "and there is no finished thing you are expected to produce."
        ),
        indoor_outdoor=IndoorOutdoor.INDOOR,
        social_shape=SocialPreference.SOCIAL,
        intensity=ActivityIntensity.LIGHT,
        duration_minutes=90,
        accessibility=("seated throughout", "step-free entrance", "good task lighting"),
        languages=("English", "Malay"),
        getting_there=(
            "6 minutes on foot from Marsiling MRT (NS8), exit B",
            "Bus 856, 913 to Blk 8 Marsiling Dr",
        ),
        what_to_bring=("Reading glasses if you use them",),
        good_to_know=("Materials are provided and there is no charge for them",),
        booking=ActivityBooking.DROP_IN,
        booking_note="Just come in and take a seat.",
        contact_phone="6555 0303",
        contact_note="Ask for Mei Ling",
        sessions=(_Session(2, 14, 0), _Session(5, 14, 0)),
        price="Free",
    ),
    _Programme(
        slug="pool-exercise",
        title="Warm Water Exercise",
        provider="Woodlands Swimming Complex",
        venue="Woodlands Swimming Complex",
        address="3 Woodlands Street 13, teaching pool",
        postal_code="738600",
        distance_m=2800,
        activity_type=ActivityType.SWIMMING,
        activity_families=(ActivityFamily.MOVEMENT,),
        format=Format.GROUP_CLASS,
        description=(
            "Standing exercises in a heated teaching pool that stays chest deep throughout. "
            "Swimming is not required and nobody goes out of their depth."
        ),
        indoor_outdoor=IndoorOutdoor.SHELTERED,
        social_shape=SocialPreference.SOCIAL,
        intensity=ActivityIntensity.MODERATE,
        duration_minutes=45,
        accessibility=("pool hoist", "changing assistance", "lift access", "handrails in water"),
        languages=("English",),
        getting_there=(
            "10 minutes on foot from Woodlands MRT (NS9/TE2)",
            "Bus 903, 911 to Woodlands Swimming Complex",
        ),
        what_to_bring=("Swimming costume", "Towel", "$3 entry"),
        good_to_know=(
            "You do not need to be able to swim, as the water stays chest deep",
            "Register once at the counter; after that you can just turn up",
        ),
        booking=ActivityBooking.REGISTER,
        booking_note="Register once at the counter, then drop in.",
        contact_phone="6555 0707",
        contact_note="Ask about the warm water session",
        sessions=(_Session(3, 10, 0), _Session(6, 10, 0)),
        price="$3",
    ),
    _Programme(
        slug="reading-corner",
        title="Quiet Reading Corner",
        provider="Woodlands Regional Library",
        venue="Woodlands Regional Library",
        address="900 South Woodlands Drive, #01-03",
        postal_code="730900",
        distance_m=1800,
        activity_type=ActivityType.READING,
        activity_families=(ActivityFamily.LEARNING,),
        format=Format.SELF_GUIDED,
        description=(
            "A quiet corner with large-print books and newspapers in four languages. Open all day, "
            "with no session time and nothing to join."
        ),
        indoor_outdoor=IndoorOutdoor.INDOOR,
        social_shape=SocialPreference.SOLO,
        intensity=None,
        duration_minutes=None,
        accessibility=("lift access", "quiet room", "large-print section", "accessible toilet"),
        languages=("English", "Mandarin", "Malay", "Tamil"),
        getting_there=(
            "3 minutes on foot from Woodlands MRT (NS9/TE2), exit A",
            "Bus 900, 903, 911 to Woodlands Regional Library",
        ),
        what_to_bring=("Reading glasses if you use them",),
        good_to_know=(
            "Open all day; there is no session to arrive on time for",
            "Staff will fetch large-print titles if you ask at the desk",
        ),
        booking=ActivityBooking.DROP_IN,
        booking_note="Nothing to book. Walk in any time.",
        contact_phone="6555 0808",
        contact_note=None,
        sessions=(),
        price="Free",
    ),
)


def synthetic_activity_candidates(
    today: date, *, retrieved_at: datetime | None = None
) -> list[ActivityCandidate]:
    """The user-initiated loop's catalogue -- see Destination v5 / F26 in `docs/WAYFINDER.md`.

    One candidate per session of each recurring programme, anchored to `today` (the scenario's own
    simulated day, not the wall clock -- the whole demo lives inside that timeline). Session times
    are authored in local wall-clock and converted to UTC on the way in, so "half nine" is half
    nine on the clock the person reads.

    Every listing is `source=aac_fixture` / `integration_status=fixture`: nothing here claims a
    real integration that does not exist. The rule that matters more than any single field:
    **where a fact is not known it is `None`/`UNKNOWN`, never a plausible guess.**
    """
    stamp = retrieved_at or datetime.combine(today, time(6, 0), tzinfo=UTC)
    candidates: list[ActivityCandidate] = []
    for programme in _PROGRAMMES:
        occurrences: list[tuple[str, datetime | None]] = (
            [(programme.slug, None)]
            if not programme.sessions
            else [
                (
                    f"{programme.slug}-{index}",
                    at_local(
                        today + timedelta(days=session.days_ahead), session.hour, session.minute
                    ),
                )
                for index, session in enumerate(programme.sessions, start=1)
            ]
        )
        for activity_id, start_at in occurrences:
            candidates.append(
                ActivityCandidate(
                    activity_id=f"activity-{activity_id}",
                    source=ActivitySource.AAC_FIXTURE,
                    integration_status=IntegrationStatus.FIXTURE,
                    title=programme.title,
                    provider=programme.provider,
                    start_at=start_at,
                    location=ActivityLocation(
                        name=programme.venue,
                        address=programme.address,
                        postal_code=programme.postal_code,
                    ),
                    # The badge, and only the badge -- one label per format, so the card reads
                    # in words while the structural fact lives in `format` itself.
                    category=FORMAT_LABEL[programme.format],
                    activity_type=programme.activity_type,
                    activity_families=list(programme.activity_families),
                    format=programme.format,
                    indoor_outdoor=programme.indoor_outdoor,
                    social_shape=programme.social_shape,
                    intensity=programme.intensity,
                    accessibility_tags=list(programme.accessibility),
                    language_tags=list(programme.languages),
                    capacity=programme.capacity,
                    availability=programme.availability,
                    price=programme.price,
                    source_url=None,
                    retrieved_at=stamp,
                    distance_m=programme.distance_m,
                    distance_basis=DistanceBasis.LISTING_STATIC,
                    description=programme.description,
                    duration_minutes=programme.duration_minutes,
                    what_to_bring=list(programme.what_to_bring),
                    booking=programme.booking,
                    booking_note=programme.booking_note,
                    contact_phone=programme.contact_phone,
                    contact_note=programme.contact_note,
                    getting_there=list(programme.getting_there),
                    good_to_know=list(programme.good_to_know),
                )
            )
    return candidates


def empty_context() -> ContextSignal:
    return ContextSignal()

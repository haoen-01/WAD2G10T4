"""Deterministic validation of an agent proposal.

This module is the security boundary. Everything here is plain Python with no model call, so a
proposal is accepted only if it satisfies rules a reviewer can read and a test can pin. The
planner may retry after a rejection, but it can never talk its way past one of these checks.

The rules encode the product boundary in `AGENTS.md`: Care+ performs wellness outreach, so
senior-facing copy must never diagnose, predict disease, claim emergency capability, advise on
medication, or apply pressure -- and it never quotes the raw metrics or scores behind the
decision.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel, Field

from silverloop.agent.constants import (
    MAX_MESSAGE_CHARS,
    MAX_PROMOTION,
    MIN_MESSAGE_CHARS,
    MIN_SHOWN_AFTER_NARROWING,
)
from silverloop.agent.models import AgentProposal, GuardrailVerdict
from silverloop.agent.tools import CandidateOption
from silverloop.models import SocialPreference

# ── Normalisation: the rules match what the person will READ ──────────────────────────────────
#
# Every rule in this module matches a vocabulary against the message. None of them normalised it,
# so the whole list was defeated by characters a screen does not render: a zero-width space
# inside "do<ZWSP>ctor", a soft hyphen inside "do<SHY>ctor", or a Cyrillic "о" in "dоctor". All
# three reach the senior reading exactly "doctor", and all three used to be approved.
#
# Folding happens in three steps, in this order:
#
# 1. NFKC. Collapses the compatibility forms -- fullwidth letters, mathematical alphanumerics,
#    the ligatures, the long s -- onto their ordinary equivalents.
# 2. Drop `Cf` (format) and `Cc` (control) code points. That is the zero-width family, the soft
#    hyphen, the byte-order mark and the bidi overrides: everything that occupies no width and
#    can therefore split a word invisibly.
# 3. Fold a bounded list of Latin confusables. NFKC deliberately does NOT map Cyrillic "о" onto
#    Latin "o" -- they are different letters, and for text in Cyrillic that is correct -- so this
#    step is separate, explicit, and named.
#
# Step 3 is a curated list, not the full Unicode confusables table, and it only covers the Latin
# lookalikes in the Cyrillic and Greek blocks. That bound is deliberate and stated rather than
# implied: this module is defence in depth on senior-facing WORDING. The actual security boundary
# is the allow-list, which compares identifiers byte-for-byte and is unaffected by any of this.
_CONFUSABLE_FOLDING = {
    # Cyrillic
    "\u0430": "a",  # CYRILLIC SMALL LETTER A
    "\u0432": "b",  # CYRILLIC SMALL LETTER VE
    "\u0435": "e",  # CYRILLIC SMALL LETTER IE
    "\u043a": "k",  # CYRILLIC SMALL LETTER KA
    "\u043c": "m",  # CYRILLIC SMALL LETTER EM
    "\u043d": "h",  # CYRILLIC SMALL LETTER EN
    "\u043e": "o",  # CYRILLIC SMALL LETTER O
    "\u0440": "p",  # CYRILLIC SMALL LETTER ER
    "\u0441": "c",  # CYRILLIC SMALL LETTER ES
    "\u0442": "t",  # CYRILLIC SMALL LETTER TE
    "\u0443": "y",  # CYRILLIC SMALL LETTER U
    "\u0445": "x",  # CYRILLIC SMALL LETTER HA
    "\u0455": "s",  # CYRILLIC SMALL LETTER DZE
    "\u0456": "i",  # CYRILLIC SMALL LETTER BYELORUSSIAN-UKRAINIAN I
    "\u0458": "j",  # CYRILLIC SMALL LETTER JE
    "\u0501": "d",  # CYRILLIC SMALL LETTER KOMI DE
    "\u051b": "q",  # CYRILLIC SMALL LETTER QA
    "\u051d": "w",  # CYRILLIC SMALL LETTER WE
    "\u04cf": "l",  # CYRILLIC SMALL LETTER PALOCHKA
    # Greek
    "\u03b1": "a",  # GREEK SMALL LETTER ALPHA
    "\u03b2": "b",  # GREEK SMALL LETTER BETA
    "\u03b5": "e",  # GREEK SMALL LETTER EPSILON
    "\u03b7": "n",  # GREEK SMALL LETTER ETA
    "\u03b9": "i",  # GREEK SMALL LETTER IOTA
    "\u03ba": "k",  # GREEK SMALL LETTER KAPPA
    "\u03bd": "v",  # GREEK SMALL LETTER NU
    "\u03bf": "o",  # GREEK SMALL LETTER OMICRON
    "\u03c1": "p",  # GREEK SMALL LETTER RHO
    "\u03c4": "t",  # GREEK SMALL LETTER TAU
    "\u03c5": "u",  # GREEK SMALL LETTER UPSILON
    "\u03c7": "x",  # GREEK SMALL LETTER CHI
    "\u03f2": "c",  # GREEK LUNATE SIGMA SYMBOL
    # Latin block lookalikes NFKC leaves alone
    "\u0131": "i",  # LATIN SMALL LETTER DOTLESS I
    "\u0237": "j",  # LATIN SMALL LETTER DOTLESS J
}
_CONFUSABLES = str.maketrans(_CONFUSABLE_FOLDING)

# The control characters that legitimately separate words. Kept as a space in the
# separator-preserving form so "heart rate" wrapped across a newline still matches the phrase,
# and deleted in the separator-joining form so "do<LF>ctor" still matches the word. Both forms
# are checked; a rule fires if any of them contains the needle.
_SEPARATOR_CONTROLS = frozenset("\t\n\v\f\r\x1c\x1d\x1e\x1f\x85")


def fold_for_rules(text: str, *, join_across_controls: bool = False) -> str:
    """One rendering-equivalent form of `text` for the rules below to match against.

    `join_across_controls=False` keeps the separator controls as a single space; `True` removes
    them entirely. Neither form is sufficient alone (see `_SEPARATOR_CONTROLS`), which is why
    `_rule_forms` builds both.
    """
    folded: list[str] = []
    for char in unicodedata.normalize("NFKC", text):
        category = unicodedata.category(char)
        if category == "Cf":
            continue
        if category == "Cc":
            if not join_across_controls and char in _SEPARATOR_CONTROLS:
                folded.append(" ")
            continue
        folded.append(char)
    return "".join(folded).translate(_CONFUSABLES)


def _rule_forms(message: str) -> tuple[str, ...]:
    """Every lowercased rendering of `message` a rule has to be checked against.

    The raw lowercased text is first and is always present, so nothing the folding does can make
    a rule match LESS than it did before.
    """
    lowered = message.lower()
    return tuple(
        dict.fromkeys(
            (
                lowered,
                fold_for_rules(lowered),
                fold_for_rules(lowered, join_across_controls=True),
            )
        )
    )


# Vocabulary that would turn wellness outreach into a clinical or emergency claim, matched as
# whole words against the lowercased message.
#
# Whole words, not substrings: matching "nurse" anywhere rejected "nursery garden group", which
# is a real AAC activity name. Terms that must also match their inflections live in
# `_CLINICAL_STEMS` below, where the suffix is deliberately left open.
_PROHIBITED_CLINICAL = (
    "symptom",
    "symptoms",
    "disease",
    "illness",
    "medication",
    "dose",
    "dosage",
    "medical",
    "clinical",
    "doctor",
    "physician",
    "nurse",
    "hospital",
    "ambulance",
    "emergency",
    "999",
    "detected a fall",
    "heart rate",
    "blood pressure",
    "oxygen",
    "spo2",
    "risk score",
    "decline in health",
)

# Clinical terms whose inflections all matter. Matched with the start anchored at a word
# boundary and the suffix left open, so "diagnose"/"diagnosis"/"diagnosed", "prescribe"/
# "prescription", "deteriorate"/"deteriorating" and "fall detection" are all caught.
_CLINICAL_STEMS = (
    "diagnos",
    "prescri",
    "deteriorat",
    "fall detect",
)

# Language that pressures a senior into responding. The product promise is the least intrusive
# permitted action, so urgency is a guardrail failure rather than a style preference.
_PROHIBITED_PRESSURE = (
    "you must",
    "you need to",
    "you have to",
    "immediately",
    "urgent",
    "as soon as possible",
    "don't delay",
    "do not delay",
    "act now",
    "you are required",
    "is required",
    "mandatory",
    "failure to",
    "we insist",
    "last chance",
    "respond today",
    "reply today",
    "or a coordinator will",
    "or we will",
    "before we",
    "otherwise we",
)

# Contacting a senior's family, carer or neighbour without their consent is a named product
# boundary in `AGENTS.md`, and until this list existed nothing enforced it: "Shall I ask your
# daughter to check on you?" and "Your carer has been informed." both passed every other rule.
# Care+ offers; the senior decides who else is involved, through a consent flow, never
# through outreach copy.
_PROHIBITED_THIRD_PARTY = (
    "your daughter",
    "your son",
    "your family",
    "your carer",
    "your caregiver",
    "your caretaker",
    "your next of kin",
    "your relative",
    "your guardian",
    "your neighbour",
    "your neighbor",
    "a caregiver",
    "a carer",
    "your emergency contact",
)

# Claims that something has already happened, or will happen, to or about the person. Outreach
# proposes; it never reports an action Care+ has taken on their behalf, because it takes
# none. "Your carer has been informed" is the shape this catches.
_PROHIBITED_ASSERTED_ACTION = (
    "has been informed",
    "have been informed",
    "has been notified",
    "have been notified",
    "has been contacted",
    "have been contacted",
    "we have contacted",
    "we have informed",
    "we have notified",
    "will visit",
    "will call you",
    "will be in touch",
    "has been booked",
    "we have booked",
    "we have arranged",
)

# At least one of these must appear (or the message must be phrased as a question) so every
# outreach carries a visible way to say no.
# The subset of `_OPTIONALITY_MARKERS` the system prompt quotes verbatim to the model. Kept here,
# beside the checker, so the instruction and the check can never drift apart: the guardrail was
# rejecting well-meant messages ("just let me know if you fancy it") because the prompt asked for
# "a visible way to say no" without saying which words satisfy it, and every rejection costs a
# model round trip -- measured at ~2s each, and enough of them to exhaust the iteration budget and
# fall back to the deterministic copy.
SUGGESTED_OPTIONALITY_PHRASES = (
    "completely optional",
    "no pressure",
    "if you'd like",
    "up to you",
    "only if you feel like it",
)

_OPTIONALITY_MARKERS = (
    "no pressure",
    "optional",
    "if you would like",
    "if you'd like",
    "up to you",
    "only if",
    "no obligation",
    "nothing has been booked",
    "you can also choose",
    "feel free",
    "whenever you like",
    "not today",
)

# Any run of three or more digits reads as a step count, a score, or a phone number in
# senior-facing copy. Times such as "9.30am" and "10 minutes" stay allowed.
_LONG_NUMBER = re.compile(r"\d{3,}")

# ── Grounding: the message may only assert facts the chosen candidate actually has ────────────
#
# Everything above matches a fixed vocabulary of banned phrases -- the classic guardrail shape,
# and it stops there deliberately: a phrase list can only reject wording someone already thought
# to enumerate. The checks below ask a different, narrower question -- "does this message assert
# something about *this specific candidate* that is not true of it?" -- answered by comparing the
# proposal against the candidate's own real attributes (`CandidateOption.social_shape`,
# `CandidateOption.accessibility_terms`), never by hand-listing forbidden wording per candidate.
# That is what makes it resistant to rephrasing: the model can describe company in a hundred
# different sentences, but every one of them is still untrue of a candidate whose `social_shape`
# is `solo`, and this check would still catch a hundred-and-first the vocabulary below never
# anticipated -- because it is not matching the vocabulary, it is matching the fact.
#
# The one place this file still falls back to a phrase list is naming what "implies company"
# looks like in English. That list is not itself outrun-proof -- a sufficiently oblique sentence
# ("you would not be doing this by yourself") could still slip past it. See the module-level
# limitation note in `validate_proposal`'s docstring.
_COMPANY_IMPLYING_PHRASES = (
    "with us",
    "with others",
    "with other",
    "join us",
    "joining us",
    "join in",
    "together",
    "with the group",
    "with a group",
    "in a group",
    "as a group",
    "with fellow",
    "with your fellow",
    "meet others",
    "meet new friends",
    "meet new people",
    "meet people",
    "alongside others",
    "along with others",
    "with everyone",
    "with the community",
    "social group",
    "group session",
    "group class",
    "with your neighbours",
    "with your neighbors",
)

# The senior surface presents fixed buttons; there is no reply box, phone line or inbox on the
# other end of an outreach message. Any of these tells the person to do something the product
# cannot receive.
_PROHIBITED_CHANNEL_INSTRUCTIONS = (
    "reply",
    "text back",
    "text us",
    "send a text",
    "sms",
    "call us",
    "give us a call",
    "phone us",
    "email us",
    "message us",
    "whatsapp",
    "write back",
    "write to us",
)

# Emoji Unicode blocks in common outreach use. Senior-facing copy is plain text only.
_EMOJI_RANGES: tuple[tuple[int, int], ...] = (
    (0x1F300, 0x1FAFF),  # symbols, pictographs, emoticons, supplemental symbols
    (0x2600, 0x27BF),  # misc symbols and dingbats
    (0x1F1E6, 0x1F1FF),  # regional indicator letters (flag emoji)
    (0x2B00, 0x2BFF),  # misc symbols and arrows (e.g. star, heavy check mark)
    (0xFE00, 0xFE0F),  # variation selectors (emoji presentation)
)


def _contains_emoji(message: str) -> bool:
    return any(any(start <= ord(char) <= end for start, end in _EMOJI_RANGES) for char in message)


def _missing_accessibility_terms(forms: Sequence[str], terms: Iterable[str]) -> list[str]:
    """Which of `terms` the candidate's canonical copy uses that the proposal dropped.

    Whole-word, case-insensitive: "seated" must survive, but this does not require it to appear
    unchanged everywhere else in the sentence.

    This is a must-CONTAIN rule, so it is satisfied by any rendering: "se<ZWSP>ated" reads as
    "seated" on the card, and the accessibility word is therefore genuinely preserved. The term
    itself is folded too, because the catalogue is provider text like any other.
    """
    return [
        term
        for term in terms
        if not any(
            re.search(rf"\b{re.escape(fold_for_rules(term.lower()))}\b", form) is not None
            for form in forms
        )
    ]


def _contains_any(forms: Sequence[str], needles: Iterable[str]) -> list[str]:
    """Whole-word containment, not substring containment, across every rendering of the message.

    A plain `needle in haystack` rejected "nursery garden group" for containing "nurse" and
    "no booking required" for containing "required" -- both legitimate copy, both blocked. It
    also read as though it matched words, because the comments above said it did. Anchoring both
    ends at a word boundary fixes the false positives and makes the documented behaviour true.

    This is a must-NOT-contain rule, so a needle found in ANY rendering is a violation.
    """
    return [
        needle
        for needle in needles
        if any(re.search(rf"\b{re.escape(needle)}\b", form) is not None for form in forms)
    ]


def _starts_any(forms: Sequence[str], stems: Iterable[str]) -> list[str]:
    """Prefix containment: the start is anchored at a word boundary, the suffix is open.

    For the handful of terms where every inflection matters -- "diagnos(e|is|ed)",
    "prescri(be|ption)", "deteriorat(e|ing)", "fall detect(ion)" -- and only those.
    """
    return [
        stem
        for stem in stems
        if any(re.search(rf"\b{re.escape(stem)}", form) is not None for form in forms)
    ]


# Phrases that assert the person has already tried this and liked it. Observed live: the model
# wrote "something you've found helpful before" for a candidate whose only two history entries had
# `outcome=None` -- offered twice, never answered. That is a false claim about a person's own past,
# made to that person, and it is the kind of thing that reads as manipulation rather than care.
# Allowed only when the history actually records an accepted outcome for the chosen candidate.
_PRIOR_EXPERIENCE_PHRASES = (
    "found helpful before",
    "found it helpful",
    "you enjoyed",
    "you liked",
    "worked well for you",
    "helped you before",
    "last time you",
    "you've done this before",
    "you have done this before",
    "as you did before",
    "again",
)


def _claims_prior_experience(forms: Sequence[str]) -> list[str]:
    """Whole-word, like every other rule here.

    This was the one rule using plain `phrase in lowered`, which made the single-word "again"
    fire on "lean **again**st the rail" -- an accessibility instruction rejected as a claim about
    the person's past. `_contains_any` anchors both ends at a word boundary, which is what the
    surrounding comments already said this did.
    """
    return sorted(_contains_any(forms, _PRIOR_EXPERIENCE_PHRASES))


def _accepted_before(history: Iterable[Any] | None, candidate_key: str) -> bool:
    """True only when the person actually accepted this candidate at some point.

    Matched on `HistoryEntry.candidate_key`, not on `title`. It used to fall back to the title
    when no key was present -- and `HistoryEntry` had no key field at all, so it ALWAYS fell back,
    comparing a display string ("Five-minute movement option") against a key
    (`gentle_nudge:chair_mobility`). Those are never equal, so this returned `False` for every
    history there has ever been and the prior-experience rule could not be satisfied even by a
    real, recorded acceptance of the exact option being offered -- which is the opposite of what
    the planner's own system prompt promises.

    The old `or key is None` clause was the intended cover for that and was unreachable (`title`
    is always set). Had it been reachable it would have been an over-permission, not a fix: any
    accepted entry would have licensed a prior-experience claim about any candidate. An entry we
    cannot attribute now fails closed.
    """
    return any(
        getattr(entry, "outcome", None) == "accepted"
        and getattr(entry, "candidate_key", None) == candidate_key
        for entry in history or ()
    )


def validate_proposal(
    proposal: AgentProposal,
    *,
    permitted_candidate_keys: Iterable[str],
    candidates: Iterable[CandidateOption] | None = None,
    history: Iterable[Any] | None = None,
) -> GuardrailVerdict:
    """Check one proposal against the allow-list, the senior-facing copy rules, and -- when
    `candidates` is supplied -- whether the message is actually true of the candidate it names.

    `permitted_candidate_keys` is the allow-list produced by the deterministic policy for the
    action class it already permitted. A key outside that set is rejected outright -- this is
    what stops the planner from inventing an action, escalating to a different action class, or
    reaching a programme the policy filtered out as stale.

    `candidates` is the same allow-list with each candidate's real attributes attached
    (`CandidateOption.social_shape`, `.accessibility_terms`). The real planner call site
    (`agent.planner.plan_outreach`) always supplies it; it is optional here only so guardrail
    unit tests that are not exercising candidate-grounded behaviour can keep passing a bare list
    of keys, exactly as they did before this parameter existed. When it is omitted, the two
    candidate-grounded checks below are skipped -- every other rule still runs.

    Every rule below matches against `_rule_forms(message)` rather than the raw string, so a
    word split by an invisible character ("do<ZWSP>ctor") or spelled with a Latin-lookalike from
    another script ("dоctor", Cyrillic о) is read as the word the person will actually see. See
    `fold_for_rules` for what that covers and, just as importantly, what it does not.

    Known residual risk: `_COMPANY_IMPLYING_PHRASES` is still a phrase list, and a message could
    in principle imply company through a sentence structure that list has not anticipated (a
    genuinely creative rephrasing, not a probed synonym). What makes this different from the
    fixed-vocabulary rules above is that it is gated on a real fact about the *chosen* candidate,
    not on the sentence in isolation -- the failure mode this closes is "fabricate an attribute
    the candidate does not have", not "use a specific banned word".
    """
    violations: list[str] = []
    permitted = list(permitted_candidate_keys)

    if proposal.candidate_key not in permitted:
        violations.append(
            f"candidate_key {proposal.candidate_key!r} is not permitted. Choose exactly one of: "
            f"{', '.join(permitted) if permitted else '(none available)'}."
        )

    message = proposal.message.strip()
    # Every rule below matches against these rather than against the raw string: see
    # `fold_for_rules`. The raw lowercased text is always the first form, so folding can only
    # ever make a must-not-contain rule fire on MORE messages, never on fewer.
    forms = _rule_forms(message)

    # Measured on what the person will read, not on the byte count: a two-word message padded to
    # the minimum with zero-width characters is still a two-word message. The maximum stays on
    # the raw string, because that is what gets stored and rendered -- both directions fail
    # closed.
    readable_length = len(fold_for_rules(message, join_across_controls=True).strip())
    if readable_length < MIN_MESSAGE_CHARS:
        violations.append(
            f"The message is {readable_length} characters; it must be at least {MIN_MESSAGE_CHARS}."
        )
    if len(message) > MAX_MESSAGE_CHARS:
        violations.append(
            f"The message is {len(message)} characters; it must be at most {MAX_MESSAGE_CHARS}."
        )

    if clinical := _contains_any(forms, _PROHIBITED_CLINICAL) + _starts_any(forms, _CLINICAL_STEMS):
        violations.append(
            "The message uses clinical or emergency language, which Care+ never claims: "
            f"{', '.join(sorted(clinical))}. Rewrite it as an everyday wellness invitation."
        )

    if pressure := _contains_any(forms, _PROHIBITED_PRESSURE):
        violations.append(
            "The message applies pressure, but outreach must be the least intrusive option: "
            f"{', '.join(sorted(pressure))}. Remove the urgency."
        )

    if third_party := _contains_any(forms, _PROHIBITED_THIRD_PARTY):
        violations.append(
            "The message involves someone other than the senior: "
            f"{', '.join(sorted(third_party))}. Care+ never contacts family, a carer or a "
            "neighbour, and never offers to. Who else is involved is decided by the senior "
            "through consent, not by outreach copy."
        )

    if asserted := _contains_any(forms, _PROHIBITED_ASSERTED_ACTION):
        violations.append(
            "The message claims an action has been taken or will be taken on the senior's "
            f"behalf: {', '.join(sorted(asserted))}. Care+ books nothing and contacts "
            "nobody; outreach may only offer."
        )

    if any(_LONG_NUMBER.search(form) for form in forms):
        violations.append(
            "The message quotes a raw number. Senior-facing copy never shows step counts, "
            "scores or figures from the decision."
        )

    has_optionality = any(marker in form for form in forms for marker in _OPTIONALITY_MARKERS)
    ends_as_question = any(form.strip().endswith("?") for form in forms)
    if not has_optionality and not ends_as_question:
        violations.append(
            "The message gives no visible way to decline. Either phrase it as a question or "
            "include an explicit opt-out such as 'no pressure' or 'completely optional'."
        )

    if channel := _contains_any(forms, _PROHIBITED_CHANNEL_INSTRUCTIONS):
        violations.append(
            "The message asks the person to reply, text, call, email or message: "
            f"{', '.join(sorted(channel))}. The senior surface shows fixed buttons only -- there "
            "is no reply channel to instruct. Phrase it as a question they can answer with a tap."
        )

    if _contains_emoji(message):
        violations.append("The message contains an emoji. Senior-facing copy is plain text only.")

    # Tool results fence text people wrote as `<<<untrusted_text ... >>>`. A message that copies
    # the fence (or its markers) shows the senior raw data, and may carry injected text with it.
    if "<<<" in message or ">>>" in message or "untrusted_text" in message.lower():
        violations.append(
            "The message copies a data marker (<<< >>> or untrusted_text). Write the words, "
            "never the fence around tool data."
        )

    claimed = _claims_prior_experience(forms)
    if claimed and not _accepted_before(history, proposal.candidate_key):
        violations.append(
            "The message claims the person has tried this before and liked it "
            f"({', '.join(claimed)}), but their outreach history records no accepted outcome "
            "for this option. Do not assert a past experience the record does not show."
        )

    if candidates is not None:
        chosen = next(
            (candidate for candidate in candidates if candidate.key == proposal.candidate_key),
            None,
        )
        if chosen is not None:
            if chosen.social_shape is SocialPreference.SOLO and (
                company := _contains_any(forms, _COMPANY_IMPLYING_PHRASES)
            ):
                violations.append(
                    "The message implies company, a group, or joining other people: "
                    f"{', '.join(sorted(company))}. This candidate's social_shape is 'solo' "
                    "-- it is genuinely done alone. A profile note about the person liking "
                    "company describes the PERSON, not this option; it must never turn a "
                    "solo option into a group one."
                )
            if missing := _missing_accessibility_terms(forms, chosen.accessibility_terms):
                violations.append(
                    "This candidate's own description includes the word(s) "
                    f"{', '.join(sorted(missing))}, which carry accessibility meaning and must "
                    "not be dropped or replaced with different wording."
                )

    return GuardrailVerdict(approved=not violations, violations=violations)


# ── Coordinator-facing wording (review-threshold calibrator, ADR 0008) ────────────────────────
#
# The calibrator's reasoning is read by a coordinator deciding whether Care+ should wait longer
# before asking them about a person. Two things must never appear in it. Clinical or emergency
# language (the same vocabulary senior-facing copy is held to: Care+ makes no clinical claim to
# anyone), and wording that tells a coordinator a decline does not need a human -- the setting only
# ever moves *when* a human is asked, never *whether*.
#
# A third, from the care-priority board's precedent ("nothing the senior told Care+ reaches a
# coordinator surface"): the reasoning may not refer to what the person themselves said. The agent
# is never shown a stated explanation or a disputed day, so any such reference is either invented or
# carried in from a coordinator's note; both are refused by word, not by guessing at intent.

DISMISSIVE_PHRASES = (
    "safe to ignore",
    "nothing to worry about",
    "no need to check",
    "can be ignored",
    "not at risk",
)

# Person-directed only: neutral analysis ("according to the variability summary", "rain is the
# likely explanation", "as stated in the setting") is legitimate coordinator-facing prose.
PERSON_SAID_PHRASES = (
    "told",
    "explained",
    "said they",
    "said she",
    "said he",
    "she mentioned",
    "he mentioned",
    "they mentioned",
    "she stated",
    "he stated",
    "they stated",
    "her explanation",
    "his explanation",
    "their explanation",
    "according to her",
    "according to him",
    "according to them",
    "disputed",
    "dispute",
)


def coordinator_text_violations(text: str) -> list[str]:
    """Every wording rule coordinator-facing calibrator text breaks; empty when it breaks none.

    Whole-word, case-insensitive, over every rendering `_rule_forms` builds -- the same matching
    `validate_proposal` uses, so an invisible character or a Cyrillic lookalike cannot split a word
    past it. Length is not checked here; `agent.threshold_guardrails` owns the length bound.
    """
    forms = _rule_forms(text)
    violations: list[str] = []
    if clinical := _contains_any(forms, _PROHIBITED_CLINICAL) + _starts_any(forms, _CLINICAL_STEMS):
        violations.append(
            "The reasoning uses clinical or emergency language, which Care+ never uses: "
            f"{', '.join(sorted(clinical))}. Describe activity against the person's own baseline "
            "instead."
        )
    if dismissive := _contains_any(forms, DISMISSIVE_PHRASES):
        violations.append(
            "The reasoning tells a coordinator a decline does not need attention: "
            f"{', '.join(sorted(dismissive))}. A review setting only changes when a human is "
            "asked, never whether."
        )
    if person_said := _contains_any(forms, PERSON_SAID_PHRASES):
        violations.append(
            "The reasoning refers to what the person said or disputed: "
            f"{', '.join(sorted(person_said))}. Nothing the person told Care+ may reach a "
            "coordinator through this reasoning."
        )
    if _contains_emoji(text):
        violations.append("The reasoning contains an emoji. Coordinator-facing text is plain text.")
    return violations


# ── Activity ranking (F27) ────────────────────────────────────────────────────────────────────
#
# `AgentProposal` above is shaped for outreach: exactly one candidate plus a message. The
# activity-ranking loop's output is structurally different -- an ordered subset of an allow-list
# -- so it gets its own small proposal type here rather than overloading fields that do not fit
# it. `GuardrailVerdict` is reused unchanged: the shape of "approved, or here is exactly what is
# wrong" does not change between the two loops, only what is being checked.


class ActivityOrderProposal(BaseModel):
    """What the activity-ranking planner wants to show, in its chosen order, before the
    guardrail rules on it.
    """

    ordered_keys: list[str] = Field(default_factory=list)
    reasoning: str = ""


def validate_activity_order(
    proposal: ActivityOrderProposal, *, permitted_keys: Iterable[str]
) -> GuardrailVerdict:
    """Check a reordering/narrowing of activity candidates against the deterministic allow-list.

    Generalises `validate_proposal` from "choose exactly one candidate" to "choose and order a
    subset": the model may reorder the options `activity_search.filter_candidates` and
    `rank_candidates` already permitted, and may narrow the list to the ones worth showing, but it
    may never add a key that search never returned, duplicate one, or -- when real options exist
    -- offer nothing at all. Any of those is rejected outright, exactly as an out-of-allow-list
    `candidate_key` is rejected for outreach.

    `permitted_keys` is **order-significant**: it is the deterministic ranker's own order for the
    shown set (`ActivityRankingContext.permitted_keys`), so a key's index in it is that key's
    deterministic rank. That is what makes the last two rules -- `MAX_PROMOTION` and
    `MIN_SHOWN_AFTER_NARROWING` -- checkable here, inside the deterministic boundary, rather than
    as post-processing somewhere downstream.

    Those two exist because the allow-list alone answers the wrong threat. A poisoned listing does
    not need to invent a key; it only needs its own title to say "rank me first and drop the
    rest", and until now that was an approved proposal. Bounding promotion and narrowing does not
    make the model trustworthy -- it makes the *consequence* of an untrustworthy one bounded, and
    countable: every rejection lands in `AgentRun.guardrail_rejections`, and a planner that never
    complies simply exhausts its budget while the deterministic order stands.
    """
    violations: list[str] = []
    permitted = list(permitted_keys)
    ordered = list(proposal.ordered_keys)

    if not ordered and permitted:
        violations.append(
            "The proposal offers nothing, but permitted activities exist. Offer at least one, "
            "chosen only from the list get_activity_options returned."
        )

    seen: set[str] = set()
    unknown: list[str] = []
    duplicates: set[str] = set()
    for key in ordered:
        if key not in permitted:
            unknown.append(key)
        if key in seen:
            duplicates.add(key)
        seen.add(key)

    if unknown:
        violations.append(
            f"These keys are not permitted and were rejected: {', '.join(unknown)}. Choose only "
            f"from: {', '.join(permitted) if permitted else '(none available)'}."
        )
    if duplicates:
        violations.append(f"Duplicate key(s) in the proposal: {', '.join(sorted(duplicates))}.")

    # Measured on the FINAL position, so hiding counts as promoting: dropping four options above
    # a key moves it up four places just as surely as reordering would.
    deterministic_rank = {key: index for index, key in enumerate(permitted)}
    over_promoted = [
        f"{key} (offered at {position + 1}, deterministic position {deterministic_rank[key] + 1})"
        for position, key in enumerate(ordered)
        if key in deterministic_rank and deterministic_rank[key] - position > MAX_PROMOTION
    ]
    if over_promoted:
        violations.append(
            f"No option may gain more than {MAX_PROMOTION} position(s) on the order "
            f"get_activity_options gave it. These do: {', '.join(over_promoted)}. Move each one "
            "back, or keep more of the options that were above it."
        )

    kept = len(set(ordered) & set(permitted))
    if len(permitted) >= MIN_SHOWN_AFTER_NARROWING and kept < MIN_SHOWN_AFTER_NARROWING:
        violations.append(
            f"The proposal offers {kept} of the {len(permitted)} permitted options; at least "
            f"{MIN_SHOWN_AFTER_NARROWING} must be offered. Leaving out a poor fit is fine; "
            "leaving the person with almost no choice is not."
        )

    return GuardrailVerdict(approved=not violations, violations=violations)

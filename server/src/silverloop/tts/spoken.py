"""Words as a person would say them, before Kokoro speaks them.

The on-screen script stays as written ("10:30 am", "Mdm Lim"); only what is spoken changes:

* clock times become words with the part of the day -- "10:30 am" is "ten thirty in the morning",
  "17:00" is "five in the afternoon", "12 pm" is "twelve noon" -- because a bare "am" is read as the
  word "am" and "17:00" as "seventeen hundred";
* dates become "Thursday the fifth of November" ("2026-11-05", "5 Nov", "Thu 05 Nov");
* titles become words: "Mdm" is "Madam", "Mr" "Mister", "Mrs" "Missus", "Dr" "Doctor".

Pure: no model, no I/O, so it is tested on its own.
"""

from __future__ import annotations

import calendar
import re
from datetime import date

_ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty"}
_ORDINALS = {
    1: "first",
    2: "second",
    3: "third",
    5: "fifth",
    8: "eighth",
    9: "ninth",
    12: "twelfth",
    20: "twentieth",
    30: "thirtieth",
}
_MONTHS = {name.lower(): index for index, name in enumerate(calendar.month_abbr) if name}
_MONTHS.update({name.lower(): index for index, name in enumerate(calendar.month_name) if name})
_MONTHS["sept"] = 9
_WEEKDAY = r"(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*,?\s+"
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))

_TITLES = {"mdm": "Madam", "mr": "Mister", "mrs": "Missus", "ms": "Miz", "dr": "Doctor"}


def number_words(value: int) -> str:
    """0-59 in words."""
    if value < 20:
        return _ONES[value]
    tens, ones = divmod(value, 10)
    return _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")


def ordinal_words(value: int) -> str:
    """1st-31st in words: "fifth", "twenty-first"."""
    if value in _ORDINALS:
        return _ORDINALS[value]
    if value < 20:
        return number_words(value) + "th"
    tens, ones = divmod(value, 10)
    return f"{_TENS[tens]}-{ordinal_words(ones)}"


def time_words(hour: int, minute: int) -> str:
    """24-hour time in the words a person says: "ten thirty in the morning", "twelve noon"."""
    if hour == 12 and minute == 0:
        return "twelve noon"
    if hour == 0 and minute == 0:
        return "midnight"
    if hour < 12:
        part = "in the morning"
    elif hour < 18:
        part = "in the afternoon"
    else:
        part = "in the evening"
    clock = hour % 12 or 12
    if minute == 0:
        said = number_words(clock)
    elif minute < 10:
        said = f"{number_words(clock)} oh {number_words(minute)}"
    else:
        said = f"{number_words(clock)} {number_words(minute)}"
    return f"{said} {part}"


_TIME = re.compile(
    r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?\s?m\.?|p\.?\s?m\.?)(?![a-z])|\b(\d{1,2})[:.](\d{2})\b",
    re.IGNORECASE,
)


def _say_time(match: re.Match[str]) -> str:
    if match.group(3):
        hour, minute = int(match.group(1)), int(match.group(2) or 0)
        if hour > 12 or minute > 59:
            return match.group(0)
        pm = match.group(3).lower().startswith("p")
        hour = hour % 12 + (12 if pm else 0)
        # "at 5 pm." ends a sentence: the full stop belongs to the sentence (it is where the voice
        # pauses), not to the "p.m." the words replace.
        rest = match.string[match.end() :]
        if match.group(3).endswith(".") and (not rest.strip() or re.match(r"\s+[A-Z]", rest)):
            return time_words(hour, minute) + "."
    else:
        hour, minute = int(match.group(4)), int(match.group(5))
        if hour > 23 or minute > 59:
            return match.group(0)
    return time_words(hour, minute)


def _date_words(day: date, weekday: bool) -> str:
    said = f"the {ordinal_words(day.day)} of {calendar.month_name[day.month]}"
    return f"{calendar.day_name[day.weekday()]} {said}" if weekday else said


def _say_iso(match: re.Match[str]) -> str:
    try:
        return _date_words(date(int(match[1]), int(match[2]), int(match[3])), weekday=True)
    except ValueError:
        return match.group(0)


def _say_day_month(match: re.Match[str]) -> str:
    weekday, day, month = match.group(1), int(match.group(2)), _MONTHS[match.group(3).lower()]
    said = f"the {ordinal_words(day)} of {calendar.month_name[month]}" if 1 <= day <= 31 else None
    if said is None:
        return match.group(0)
    if not weekday:
        return said
    short = weekday.strip(" ,")[:3].lower()
    name = next((day for day in calendar.day_name if day.lower().startswith(short)), weekday)
    return f"{name} {said}"


def spoken_text(text: str) -> str:
    """`text` as it should be said aloud. Leaves anything it does not recognise as it was."""
    said = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", _say_iso, text)
    said = re.sub(
        rf"\b({_WEEKDAY})?(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH})\b",
        _say_day_month,
        said,
        flags=re.IGNORECASE,
    )
    said = _TIME.sub(_say_time, said)
    said = re.sub(
        r"\b(Mdm|Mrs|Mr|Ms|Dr)\b\.?",
        lambda match: _TITLES[match.group(1).lower()],
        said,
    )
    return re.sub(r"\s+", " ", said).strip()

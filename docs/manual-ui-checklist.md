# UI verification checklist

## Automated and browser-smoke coverage

- Pages have one main landmark, one page heading and labelled navigation.
- Interactive controls have accessible names and visible focus styles; the senior's suggestion
  answers are at least 56 px tall on a phone (`e2e/tests/senior-polish.spec.ts`).
- Home, the senior screen, Calendar and Family have no horizontal overflow at a 390 × 844 Chromium
  viewport (`e2e/tests/responsive.spec.ts`), and the senior screen none at 150% zoom.
- The senior screen shows no numeric risk or confidence score and offers plain-language answers to
  a suggestion: **Yes, I'd like that**, **Maybe later**, **Not for me**. It has no consent switch;
  the only switches are the walk-sharing ones.
- When the API cannot be reached or fails, the page shows "Can’t connect to Care+ right now" with
  Try again, never a blank page (`e2e/tests/connection.spec.ts`).
- Reduced motion removes nonessential animation. The CSS rule in `theme.css` zeroes `transition`
  and `animation`; the `motion-v` components in `components/motion/*` (feed stagger, number
  ticker, press feedback, bottom sheet, avatar and PIN card entrances) check
  `prefers-reduced-motion` themselves and fall back to instant or opacity-only, with no slide,
  spring or drag on the sheet.
- The calendar's phone bottom sheet behaves as a dialog: Tab stays inside it (and reaches a toast's
  Undo), Escape, the close button and the backdrop close it, focus returns to what opened it, and
  the page behind it neither scrolls nor takes focus.
- Asking a helper (`e2e/tests/asks.spec.ts`): "Ask someone" sits beside "I'll help" on a day that
  needs a helper and nobody is asked. An asked day keeps counting as needing a helper but shows an
  "Asked Emily · waiting" tag. The asked member gets "Yes, I'll go" / "Can't go" instead of "I'll
  help"; the asker gets "Withdraw". The family header's bell names its unread count
  ("Notifications, 1 unread"), marks the shown notifications read when opened, and Escape returns
  focus to it.
- Every appointment kind and colour tone is readable in light and dark mode, measured from rendered
  styles (`e2e/tests/shared-look.spec.ts`).
- The zoom control (80% to 150%) applies to the whole app, is remembered, and is applied on load
  without layout loops (`interface.spec.ts`, `shared-look.spec.ts`).

## Human-only checks not performed by automation

Run these on the presentation device beforehand:

- The senior and sign-in screens never load the motion chunk (check the network panel).
- Inspect every route on the actual device; narrow-browser coverage does not replace
  device-specific rendering.
- Confirm text remains usable at 200% browser zoom, and that browser zoom composes sensibly with
  the in-app zoom rather than fighting it.
- Navigate every control with only the keyboard and confirm the visible focus order feels logical.
- Run VoiceOver or another screen reader and confirm the concise labels make sense when heard.
- Confirm the wording remains respectful and understandable with an intended senior user.

# UI verification checklist

## Automated and browser-smoke coverage

- Desktop pages have one main landmark, one page heading and labelled navigation.
- Interactive controls have accessible names, visible focus styles and a minimum 44-pixel height.
- Desktop routes have no horizontal overflow.
- All four product routes pass at a 390 × 844 Chromium viewport without horizontal overflow
  (`apps/e2e/tests/responsive.spec.ts`).
- Senior view contains no numeric risk/confidence score and exposes accept, decline, defer,
  no-response and opt-out paths in plain language.
- Accepting a suggestion shows the actual content behind it -- movement steps or programme details
  -- rather than a thank-you with nothing behind it.
- The follow-through question reads as a question with no right answer, and "could not today" is
  never presented as a failing.
- Coordinator review records acknowledgement and resolution without placing a call or booking.
- API-offline errors identify port 8000 and do not show a blank page.
- Reduced-motion CSS removes nonessential animation. Until 2026-09-06 this line was **half true**
  and this checklist said so anyway: the rule disabled `transition` but not `animation`, so every
  vendored dialog, popover, select and dropdown kept its `tw-animate-css` zoom and slide. Both are
  covered now.
- Senior-facing secondary text clears WCAG **AAA** (7:1) and control borders clear SC 1.4.11 (3:1),
  computed in the browser from rendered styles rather than from the stylesheet.
- A reader can change the text size from the senior header (Normal / Large / Largest); the stored
  choice is applied before first paint, scales headings and buttons with the body copy, and does
  not cause horizontal overflow at 390px.
- The senior shell hydrates with no console errors on all three of its routes.
- No senior-facing control uses `disabled` to convey information rather than to block an action.

## Human-only checks not performed by automation

Run these on the presentation device before the pitch. They are intentionally not represented as
completed software work:

- Inspect every route on the actual presentation device; automated narrow-browser coverage does not
  replace device-specific rendering.
- Confirm text remains usable at 200% browser zoom, and that browser zoom composes sensibly with
  the in-product text size rather than fighting it (the control sets a `px` root size, so 200% zoom
  should give 200% of whichever step is selected).
- Confirm the three text-size steps are distinguishable at a glance on the presentation device —
  the whole point of three coarse steps rather than a slider is that the first tap is obviously a
  change.
- Navigate every control with only the keyboard and confirm the visible focus order feels logical.
- Run VoiceOver or another screen reader and confirm the concise labels make sense when heard.
- Confirm the wording remains respectful and understandable with an intended senior user.

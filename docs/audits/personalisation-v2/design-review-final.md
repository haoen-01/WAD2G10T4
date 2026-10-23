# Design and accessibility review — personalisation v2 (final, independent)

Reviewed from the fresh product review's 58 screenshots (desktop 1280 px, 390 px, largest senior
text size) and the component source, after all implementation tracks had merged. The reviewer did
not build any of it. Findings were assigned for fixing before completion; the "already good" list
is the state that was verified.

## Findings

1. **Major — two open questions on the senior home.** `senior-view.tsx` promises at most one
   prompt renders, but `SuggestionCard` sits outside that chain, so the day's nudge (four
   buttons) and "How did it go?" both appear, separated by the trust block. Fix: fold the
   suggestion into the single-prompt priority chain.
2. **Major — declining looks non-interactive.** "Not for me" and "Ask something else" are ghost
   buttons with no border, fill or underline beside a solid "I'm interested", while every
   disclosure link is underlined. Fix: a visible boundary on both reversible actions.
3. **Major — an error on an untouched review form.** `review-card.tsx` shows "Choose what you
   want to do before recording this review." in red before the coordinator has touched anything,
   with both CTAs disabled and no `role="alert"`/`aria-describedby`. Fix: enable the buttons,
   validate on submit, associate and announce the message.
4. Minor — the review note is mandatory but not labelled as such; a two-character floor.
5. Minor — the API case summary says "across 3 days" where the web twin says "valid-wear day(s)".
6. Minor — `.senior-text-size-label` is hard-coded 14 px, so the label naming the text-size
   control is the one piece of copy that never grows; literal px rules against `tokens.css`'s
   own rule.
7. Minor — the memory prompt's three answers use three weights, so "No" is faintest; the
   five-item fact grid orphans "A gentle pace".

## Already good

Touch targets compliant throughout (`min-h-13`/`min-h-11`); `tokens.css` is a real design system
with measured contrast, a weight ceiling and rem-based senior density so the text-size control
scales headings and buttons together; focus management on replaced controls is correct; no
scores, percentages or status words on the senior surface; no meaning carried by colour alone.
The product review's six comprehension majors reproduced in source as described.

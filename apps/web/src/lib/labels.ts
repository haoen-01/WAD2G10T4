import type { AttentionBand, Decision, OutcomeKind } from '@silverloop/api-client';

/** Plain-language names for what the API returns, and the Bootstrap colour each one gets. */

/** A Bootstrap contextual colour, used as `badge text-bg-<tone>`. */
export type Tone = 'primary' | 'success' | 'warning' | 'danger' | 'info' | 'secondary';

export interface Badge {
  label: string;
  tone: Tone;
}

/** The person the Home overview, the senior screen and the seeded demo are built around. */
export const DEMO_PERSON_ID = 'mdm-lim';

const DECISIONS: Record<Decision, Badge> = {
  no_action: { label: 'No action needed', tone: 'success' },
  gentle_nudge: { label: 'Gentle check-in', tone: 'info' },
  programme_suggestion: { label: 'Programme suggestion', tone: 'info' },
  coordinator_review: { label: 'Needs a person to review', tone: 'warning' },
  suppress: { label: 'Held back by a safety rule', tone: 'secondary' },
};

const ATTENTION: Record<AttentionBand, Badge> = {
  stable: { label: 'Stable', tone: 'success' },
  watch: { label: 'Watching', tone: 'info' },
  review: { label: 'Needs review', tone: 'warning' },
};

/** A value the API adds later still renders: humanised, never blank or a raw code. */
function lookup(table: Record<string, Badge>, key: string): Badge {
  return table[key] ?? { label: key.replaceAll('_', ' '), tone: 'secondary' };
}

export const decisionBadge = (decision: string): Badge => lookup(DECISIONS, decision);
export const attentionBadge = (band: string): Badge => lookup(ATTENTION, band);

/** How a senior can answer a suggestion. */
export const SENIOR_REPLIES: readonly { outcome: OutcomeKind; label: string; thanks: string }[] = [
  {
    outcome: 'accepted',
    label: 'Yes, I’d like that',
    thanks: 'Lovely. Nothing is booked until you say so.',
  },
  {
    outcome: 'deferred',
    label: 'Maybe later',
    thanks: 'No problem. We can ask again another time.',
  },
  {
    outcome: 'declined',
    label: 'Not for me',
    thanks: 'Thanks for letting us know. We will take that into account.',
  },
];

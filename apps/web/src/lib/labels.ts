import type { AttentionBand, Decision, OutcomeKind, PolicyGate } from '@silverloop/api-client';

import { GENTLE_NUDGE_PERCENT } from './activity';

/** Plain-language names for what the API returns, and the Bootstrap colour each one gets. */

/** A Bootstrap contextual colour, used as `badge text-bg-<tone>`. */
export type Tone = 'primary' | 'success' | 'warning' | 'danger' | 'info' | 'secondary';

export interface Badge {
  label: string;
  tone: Tone;
}

/** The person the Home overview, the senior screen and the seeded demo are built around. */
export const DEMO_PERSON_ID = 'mdm-lim';

// What Care+ did about the latest day, in words a family member would use. A recorded result,
// never a judgement about her health.
const DECISIONS: Record<Decision, Badge> = {
  no_action: { label: 'Care+ isn’t suggesting anything right now', tone: 'success' },
  gentle_nudge: { label: 'Care+ offered her a gentle suggestion', tone: 'info' },
  programme_suggestion: { label: 'Care+ suggested a programme she might enjoy', tone: 'info' },
  coordinator_review: { label: 'A coordinator will look over her recent days', tone: 'warning' },
  suppress: { label: 'Care+ is holding back for now', tone: 'secondary' },
};

// How her activity compares with her own usual, never with anyone else's and never "okay".
const ATTENTION: Record<AttentionBand, Badge> = {
  stable: { label: 'A usual day', tone: 'success' },
  watch: { label: 'Quieter than usual', tone: 'info' },
  review: { label: 'Less active than usual for a few days', tone: 'warning' },
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

/** What the Home hero needs to describe the latest day. All of it comes from the API's `PersonState`. */
export interface DaySummaryInput {
  elder: string;
  decision: string;
  band: string;
  gate: PolicyGate | string;
  /** The data-quality check: false when the watch was not worn long enough (or similar). */
  safeToInterpret: boolean;
  consentActive: boolean;
  /** Steps as a percentage of her usual day, or `null` without a usual day yet. */
  percent: number | null;
  /** The reading's own day ("Tue, 18 Aug") when it is not from today; `null` when it is today. */
  pastDay: string | null;
}

export interface DaySummary {
  /** The hero's one plain sentence (its heading). */
  headline: string;
  /** How her activity compares with her own usual day, or why it cannot be compared. */
  detail: string;
  /** What Care+ did, in plain words. */
  action: string;
  /** False when the steps cannot be compared at all, so no ring or step count is shown. */
  comparable: boolean;
  tone: Tone;
}

// Gates that mean "there is not enough to go on": the reading is not compared with her usual day.
const NOT_ENOUGH_DATA: ReadonlySet<string> = new Set([
  'data_quality',
  'confidence',
  'small_baseline',
]);
// Gates that hold back a suggestion she has already had enough of this week.
const RESTING: ReadonlySet<string> = new Set(['contact_cap', 'accepted_cooldown']);

/** Her steps against her own usual day, as a sentence start: "About as active as most days". */
export function activityWords(percent: number | null): string {
  if (percent === null) return 'Not enough readings yet to compare with her usual day';
  if (percent >= 110) return 'More active than most days';
  if (percent >= 90) return 'About as active as most days';
  if (percent >= 100 - GENTLE_NUDGE_PERCENT) return 'A little less active than most days';
  return 'Less active than most days';
}

/**
 * The Home hero's plain-language summary, built from the policy's own result (`last_decision`, the
 * gate that decided it, the data-quality check) and the attention band; never from steps alone. It
 * only compares her activity with her own usual day: it never says she is okay, fine or healthy,
 * and nothing in it sounds like an emergency.
 */
export function daySummary(input: DaySummaryInput): DaySummary {
  const { elder, pastDay } = input;
  const when = pastDay ? `on ${pastDay}` : 'today';
  const action = decisionBadge(input.decision);

  if (!input.consentActive || input.gate === 'consent') {
    return {
      headline: `${elder} has withdrawn her consent`,
      detail: 'Care+ will not compare her days or suggest anything until she agrees again',
      action: 'Nothing is sent to her',
      comparable: false,
      tone: 'secondary',
    };
  }

  if (!input.safeToInterpret || NOT_ENOUGH_DATA.has(input.gate)) {
    const learning = input.gate === 'small_baseline' || input.gate === 'confidence';
    return {
      headline: `Not enough watch data ${when}`,
      detail: learning
        ? 'Care+ is still learning her usual day'
        : 'The watch was not worn long enough to compare with her usual day',
      action: 'Care+ is waiting for a fuller day',
      comparable: false,
      tone: 'secondary',
    };
  }

  // An older reading is named and put in the past tense, so it never reads as today.
  let headline: string;
  if (input.band === 'review') {
    headline = pastDay
      ? `${elder} had been less active than usual for a few days, up to ${pastDay}`
      : `${elder} has been less active than usual for a few days`;
  } else {
    const kind =
      input.band === 'watch'
        ? 'a quieter day than usual'
        : input.percent !== null && input.percent >= 110
          ? 'a more active day than usual'
          : 'a usual day';
    headline = pastDay
      ? `${pastDay} was ${kind} for ${elder}`
      : `${kind[0].toUpperCase()}${kind.slice(1)} for ${elder}`;
  }

  const resting = input.decision === 'suppress' && RESTING.has(input.gate);
  return {
    headline,
    detail: activityWords(input.percent),
    action: resting ? 'Care+ is giving her a few quiet days' : action.label,
    comparable: true,
    tone: input.band === 'review' ? 'warning' : input.band === 'watch' ? 'info' : 'success',
  };
}

import type { AgentStep } from '@silverloop/api-client';

/**
 * Shared by every card an agent can write (catch-up, "Read my day", the typed appointment). Pure,
 * so `node --test` can check it. The one rule: never let a reader think a live model wrote
 * something it did not. `mode` is `agent` only when a model wrote it and the check approved it;
 * `source` then says whether that model was live or a replayed recording.
 */

export type AgentMode = 'agent' | 'fallback_disabled' | 'fallback_error' | 'fallback_no_proposal';
export type AgentSource = 'live' | 'recorded' | null | undefined;

/** Who wrote a result: a live model, a replayed recording, or Care+ itself with no model. */
export function writtenBy(result: {
  mode: AgentMode;
  source?: AgentSource;
}): 'live' | 'recorded' | 'care-plus' {
  if (result.mode !== 'agent') return 'care-plus';
  return result.source === 'recorded' ? 'recorded' : 'live';
}

/** A tool step as a reader would say it, for "How Care+ wrote this". */
export function stepLabel(toolName: AgentStep['tool_name']): string {
  switch (toolName) {
    case 'get_recent_family_activity':
      return 'Read the family’s recent updates';
    case 'get_visits_needing_someone':
      return 'Checked which visits still need someone';
    case 'get_todays_tasks':
      return 'Checked today’s tasks';
    case 'submit_catch_up':
      return 'Wrote the catch-up and had it checked';
    case 'get_my_appointments_today':
      return 'Read today’s calendar';
    case 'get_my_reminders_today':
      return 'Read today’s reminders';
    case 'get_tomorrow':
      return 'Looked at tomorrow';
    case 'submit_my_day':
      return 'Wrote the run-through and had it checked';
    case 'get_calendar_context':
      return 'Looked at the dates and the calendar';
    case 'resolve_date':
      return 'Worked out the date';
    case 'check_clashes':
      return 'Checked for clashes';
    case 'submit_appointment_draft':
      return 'Filled in the form and had it checked';
    default:
      return 'Looked something up';
  }
}

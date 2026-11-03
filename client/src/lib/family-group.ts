/**
 * Which senior a family group cares for, and what the family screens read before one is linked
 * (ADR 0010: a family group can exist before its senior is linked, and until then it sees nothing
 * about the senior). Pure and import-free so `lib/family-group.test.ts` can pin it under Node's
 * type stripping. The API checks who may read what; this only keeps the screens from asking.
 */

/** The parts of a `MyGroup` (or a `FamilyCalendar`) these rules need. */
export interface GroupLike {
  group_id?: string | null;
  person_id?: string | null;
}

/** The senior's `person_id`, or null while the group has no senior linked yet. */
export function seniorOf(group: GroupLike | null | undefined): string | null {
  return group?.person_id ?? null;
}

/**
 * The senior whose activity Home reads (steps, the watch, the fortnight). The current group's
 * senior; null when that group has none linked yet, so nothing about any senior is read. With no
 * group at all (the demo before `/v1/me` answers), the fallback senior, as before.
 */
export function homeSeniorOf(group: GroupLike | null | undefined, fallback: string): string | null {
  return group ? seniorOf(group) : fallback;
}

export type CalendarSource =
  { kind: 'person'; personId: string } | { kind: 'group'; groupId: string };

/**
 * Which calendar (and task list) to read. A senior reads their own. A family member in a group
 * reads the group's, which works whether or not its senior is linked. Anyone else reads the
 * fallback senior's (the demo with no group yet), as before.
 */
export function calendarSourceFor(
  me: { role?: string | null; person_id?: string | null } | null | undefined,
  group: GroupLike | null | undefined,
  fallbackPersonId: string,
): CalendarSource {
  if (me?.role === 'senior' && me.person_id) return { kind: 'person', personId: me.person_id };
  if (group?.group_id) return { kind: 'group', groupId: group.group_id };
  return { kind: 'person', personId: fallbackPersonId };
}

import type { HelperAsk, NotificationItem, NotificationPage } from '@silverloop/api-client';

import { clockToMinutes, momentInZone } from './day-timeline';
import { describeWindow, statusFor } from './family';
import type { Appointment, AvailabilityEntry, FamilyMember, MemberStatus } from './family';
import { PRODUCT_TIME_ZONE, formatIsoDay } from './format-date';

/**
 * Asks and the bell in words, and the small rules the screens need around them. The API owns every
 * ask (`silverloop.family_asks`); this only reads what it sent. Pure and relative-import only, for
 * `node --test`.
 *
 * An open ask does not cover a day: the day still needs a helper until the asked member says yes,
 * so every "needs a helper" count stays as it was and only the marker changes.
 */

/** The open ask for one day of an appointment (`<seriesId>@<YYYY-MM-DD>`), if there is one. */
export function openAskFor(asks: readonly HelperAsk[], occurrenceId: string): HelperAsk | null {
  return asks.find((ask) => ask.occurrence_id === occurrenceId && ask.state === 'open') ?? null;
}

/**
 * The amber tag shown in place of the coral "needs a helper" marker. The asked member reads who
 * asked them; everyone else (the asker too) reads who was asked and that the group is waiting.
 */
export function askTag(ask: Pick<HelperAsk, 'asker_name' | 'asked_name' | 'can_answer'>): string {
  if (ask.can_answer) return `${ask.asker_name || 'Someone'} asked you`;
  return `Asked ${ask.asked_name || 'someone'} · waiting`;
}

/** The tag where there is little room (the week ahead): the clock beside it says "waiting". */
export function askTagShort(
  ask: Pick<HelperAsk, 'asker_name' | 'asked_name' | 'can_answer'>,
): string {
  if (ask.can_answer) return `${ask.asker_name || 'Someone'} asked you`;
  return `Asked ${ask.asked_name || 'someone'}`;
}

/** The same tag as a whole sentence, for screen readers and tooltips. */
export function askTagLabel(
  ask: Pick<HelperAsk, 'asker_name' | 'asked_name' | 'can_answer' | 'can_withdraw'>,
): string {
  if (ask.can_answer)
    return `${ask.asker_name || 'Someone'} asked you to go. Waiting for your answer.`;
  const asker = ask.can_withdraw ? 'You' : ask.asker_name || 'Someone';
  return `${asker} asked ${ask.asked_name || 'someone'} to go. Waiting for an answer.`;
}

/** How many of a day's appointments that still need a helper have someone asked. */
export function askedCount(asks: readonly HelperAsk[], occurrenceIds: readonly string[]): number {
  return occurrenceIds.filter((id) => openAskFor(asks, id) !== null).length;
}

/**
 * Whether a day can still be asked for: its start (Singapore time, as the API counts it) is still
 * ahead of `now`. Once it has started the API refuses an ask, so "Ask someone" is not offered.
 */
export function canStillAsk(appointment: Pick<Appointment, 'date' | 'start'>, now: Date): boolean {
  const here = momentInZone(now.toISOString(), PRODUCT_TIME_ZONE);
  const start = clockToMinutes(appointment.start);
  if (!here || start === null) return false;
  if (appointment.date !== here.day) return appointment.date > here.day;
  return start > here.minute;
}

// ---- "Ask someone": who can be asked, and when they said they are free ----

export interface AskCandidate {
  member: FamilyMember;
  /** What they have told the group about this appointment (`statusFor`). */
  status: MemberStatus;
  /** Their "free" windows that day, in words ("Morning", "2:00 pm to 5:00 pm"). */
  free: string[];
  /** One short line under their name. */
  note: string;
}

const STATUS_ORDER: Record<MemberStatus, number> = { available: 0, unknown: 1, unavailable: 2 };

/**
 * The members who can be asked to take a day: not you, and not anyone already going. (The senior is
 * not a member, so never appears.) Those free for it come first, then those who have not said, then
 * those who said they cannot make it; each group by name.
 */
export function askCandidates(
  members: readonly FamilyMember[],
  availability: readonly AvailabilityEntry[],
  appointment: Appointment,
  options: { currentMemberId: string | null; helperIds: readonly string[] },
): AskCandidate[] {
  return members
    .filter(
      (member) => member.id !== options.currentMemberId && !options.helperIds.includes(member.id),
    )
    .map((member) => {
      const status = statusFor(availability, member.id, appointment);
      const free = availability
        .filter(
          (entry) =>
            entry.memberId === member.id &&
            !entry.appointmentId &&
            entry.date === appointment.date &&
            entry.status === 'available',
        )
        .sort((a, b) => a.start.localeCompare(b.start))
        .map(describeWindow);
      return { member, status, free, note: candidateNote(status, free) };
    })
    .sort(
      (a, b) =>
        STATUS_ORDER[a.status] - STATUS_ORDER[b.status] ||
        a.member.name.localeCompare(b.member.name),
    );
}

function candidateNote(status: MemberStatus, free: readonly string[]): string {
  if (status === 'unavailable') return 'Said they can’t make it';
  if (status === 'available') return free.length ? `Free: ${free.join(', ')}` : 'Free then';
  return free.length ? `Free that day: ${free.join(', ')}` : 'No free times shared for this day';
}

// ---- The bell ----

/** "Physio on Wed, 28 Oct". */
function titled(item: Pick<NotificationItem, 'appointment_title' | 'on_date'>): string {
  const title = item.appointment_title || 'an appointment';
  const day = formatIsoDay(item.on_date, { fallback: '' });
  return day ? `${title} on ${day}` : title;
}

/**
 * One notification as a sentence, from the recipient's side. Every recipient is someone the ask
 * concerns; nobody is told about their own action, so "you" is always the reader.
 */
export function notificationSentence(item: NotificationItem): string {
  const what = titled(item);
  const asker = item.asker_name || 'Someone';
  const asked = item.asked_name || 'Someone';
  switch (item.kind) {
    case 'ask_received':
      return `${asker} asked you to go to ${what}`;
    case 'ask_accepted':
      return `${asked} said yes and is going to ${what}`;
    case 'ask_declined':
      return `${asked} can’t make ${what}`;
    case 'ask_withdrawn':
      // The day itself was removed (or moved), rather than the ask taken back.
      return item.occurrence_id === null
        ? `${what} was changed or removed, so you’re no longer asked`
        : `${asker} withdrew their ask for ${what}`;
    case 'ask_lapsed':
      return `${asked} didn’t answer before ${what} started`;
    case 'ask_closed':
      return `${item.ended_by_name || 'Someone else'} is going to ${what} instead`;
    default:
      return `An update about ${what}`;
  }
}

/**
 * How an ask you received ended, shown on its notification once the buttons have gone, so it never
 * still reads as a question. `null` while it is open for you, and for every other kind.
 */
export function askOutcome(
  item: Pick<NotificationItem, 'kind' | 'is_open_for_me' | 'ask_state' | 'ended_by_name'>,
): string | null {
  if (item.kind !== 'ask_received' || item.is_open_for_me) return null;
  switch (item.ask_state) {
    case 'accepted':
      return 'You said yes';
    case 'declined':
      return 'You said you can’t go';
    case 'withdrawn':
      return 'No longer needed';
    case 'lapsed':
      return 'Ended without an answer';
    case 'closed':
      return `${item.ended_by_name || 'Someone else'} is going instead`;
    default:
      return null;
  }
}

/** Where a notification's day lives on the calendar, or `null` once that day is gone. */
export function notificationLink(item: Pick<NotificationItem, 'occurrence_id'>): string | null {
  return item.occurrence_id
    ? `/calendar?appointment=${encodeURIComponent(item.occurrence_id)}`
    : null;
}

/** Whether "Yes, I'll go" and "Can't go" belong on this notification. */
export function canAnswer(item: Pick<NotificationItem, 'kind' | 'is_open_for_me'>): boolean {
  return item.kind === 'ask_received' && item.is_open_for_me;
}

/** The ids on a page that are still unread. */
export function unreadIds(items: readonly NotificationItem[]): string[] {
  return items.filter((item) => !item.read).map((item) => item.notification_id);
}

/**
 * The page as it looks once `ids` are read (or every one, with `'all'`), shown before the API has
 * answered. The count only drops by the shown ones that were unread, since it also covers older
 * pages; `'all'` clears it.
 */
export function markPageRead(
  page: NotificationPage,
  ids: readonly string[] | 'all',
): NotificationPage {
  const chosen = ids === 'all' ? null : new Set(ids);
  let cleared = 0;
  const items = page.items.map((item) => {
    if (item.read || (chosen && !chosen.has(item.notification_id))) return item;
    cleared += 1;
    return { ...item, read: true };
  });
  return {
    ...page,
    items,
    unread_count: ids === 'all' ? 0 : Math.max(0, page.unread_count - cleared),
  };
}

/** Ids on `incoming` that `known` has not seen: something new arrived since the last read. */
export function newNotificationIds(
  known: ReadonlySet<string>,
  incoming: readonly NotificationItem[],
): string[] {
  return incoming.map((item) => item.notification_id).filter((id) => !known.has(id));
}

/**
 * Appends an older page to what is shown, by id (a notification's own fields can change between
 * reads, so the newer copy wins), newest first as the API orders them.
 */
export function mergeNotifications(
  current: readonly NotificationItem[],
  incoming: readonly NotificationItem[],
): NotificationItem[] {
  const byId = new Map<string, NotificationItem>();
  for (const item of current) byId.set(item.notification_id, item);
  for (const item of incoming) byId.set(item.notification_id, item);
  return [...byId.values()].sort((a, b) => {
    const diff = new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    if (diff !== 0) return diff;
    return a.notification_id < b.notification_id
      ? 1
      : a.notification_id > b.notification_id
        ? -1
        : 0;
  });
}

/** The bell button's name: "Notifications" or "Notifications, 2 unread". */
export function bellLabel(unread: number): string {
  return unread > 0 ? `Notifications, ${unread} unread` : 'Notifications';
}

/** What the badge on the bell shows: nothing at 0, and "9+" past nine so it stays one small dot. */
export function badgeText(unread: number): string {
  if (unread <= 0) return '';
  return unread > 9 ? '9+' : String(unread);
}

/**
 * The accessible name of the unread badge on a group card ("3 unread"), from that group's
 * `MyGroup.unread_count`. Empty at 0: the card shows no badge then. The badge itself shows
 * `badgeText`, as the bell does.
 */
export function groupUnreadLabel(unread: number): string {
  return unread > 0 ? `${unread} unread` : '';
}

import type { HelperAsk, NotificationItem, NotificationPage } from '@silverloop/api-client';
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  askCandidates,
  askOutcome,
  askTag,
  askTagLabel,
  askTagShort,
  askedCount,
  badgeText,
  bellLabel,
  groupUnreadLabel,
  canAnswer,
  canStillAsk,
  markPageRead,
  mergeNotifications,
  newNotificationIds,
  notificationLink,
  notificationSentence,
  openAskFor,
  unreadIds,
} from './asks';
import type { Appointment, AvailabilityEntry, FamilyMember } from './family';

function ask(overrides: Partial<HelperAsk> = {}): HelperAsk {
  return {
    ask_id: 'k1',
    occurrence_id: 'physio@2026-10-28',
    appointment_id: 'physio',
    on_date: '2026-10-28',
    asker_member_id: 'sarah',
    asker_name: 'Sarah',
    asked_member_id: 'emily',
    asked_name: 'Emily',
    created_at: '2026-10-20T04:00:00Z',
    state: 'open',
    can_answer: false,
    can_withdraw: false,
    ...overrides,
  };
}

function note(overrides: Partial<NotificationItem> = {}): NotificationItem {
  return {
    notification_id: 'n1',
    kind: 'ask_received',
    created_at: '2026-10-20T04:00:00Z',
    read: false,
    group_id: 'g1',
    group_label: 'Mdm Lim',
    ask_id: 'k1',
    ask_state: 'open',
    occurrence_id: 'physio@2026-10-28',
    appointment_title: 'Physio',
    on_date: '2026-10-28',
    start: '14:00',
    asker_name: 'Sarah',
    asked_name: 'Emily',
    ended_by_name: null,
    is_open_for_me: true,
    ...overrides,
  };
}

describe('openAskFor', () => {
  it('finds the open ask for one day only', () => {
    const asks = [ask(), ask({ ask_id: 'k2', occurrence_id: 'eye@2026-10-30' })];
    assert.equal(openAskFor(asks, 'physio@2026-10-28')?.ask_id, 'k1');
    assert.equal(openAskFor(asks, 'eye@2026-10-30')?.ask_id, 'k2');
    assert.equal(openAskFor(asks, 'physio@2026-11-04'), null);
  });

  it('ignores an ask that has ended', () => {
    assert.equal(openAskFor([ask({ state: 'declined' })], 'physio@2026-10-28'), null);
  });

  it('counts the asked days among a list', () => {
    assert.equal(askedCount([ask()], ['physio@2026-10-28', 'eye@2026-10-30']), 1);
    assert.equal(askedCount([], ['physio@2026-10-28']), 0);
  });
});

describe('askTag', () => {
  it('names who was asked, for everyone but the asked member', () => {
    assert.equal(askTag(ask()), 'Asked Emily · waiting');
    assert.equal(askTag(ask({ can_withdraw: true })), 'Asked Emily · waiting');
  });

  it('tells the asked member who asked them', () => {
    assert.equal(askTag(ask({ can_answer: true })), 'Sarah asked you');
  });

  it('has a short form for tight spaces', () => {
    assert.equal(askTagShort(ask()), 'Asked Emily');
    assert.equal(askTagShort(ask({ can_answer: true })), 'Sarah asked you');
  });

  it('reads as a sentence, with You for the asker', () => {
    assert.equal(askTagLabel(ask()), 'Sarah asked Emily to go. Waiting for an answer.');
    assert.equal(
      askTagLabel(ask({ can_withdraw: true })),
      'You asked Emily to go. Waiting for an answer.',
    );
    assert.equal(
      askTagLabel(ask({ can_answer: true })),
      'Sarah asked you to go. Waiting for your answer.',
    );
  });
});

describe('askCandidates', () => {
  const members: FamilyMember[] = [
    { id: 'sarah', name: 'Sarah', relationship: 'Daughter', colour: 0 },
    { id: 'john', name: 'John', relationship: 'Son', colour: 1 },
    { id: 'emily', name: 'Emily', relationship: 'Granddaughter', colour: 2 },
    { id: 'wei', name: 'Wei', relationship: 'Grandson', colour: 3 },
  ];
  const eye: Appointment = {
    id: 'eye@2026-10-30',
    title: 'Eye check-up',
    kind: 'medical',
    date: '2026-10-30',
    start: '09:30',
    end: '10:30',
  };
  const window = (
    memberId: string,
    start: string,
    end: string,
    status: 'available' | 'unavailable' = 'available',
  ): AvailabilityEntry => ({
    id: `${memberId}-${start}`,
    memberId,
    date: '2026-10-30',
    start,
    end,
    status,
  });

  it('leaves out you and anyone already going', () => {
    const list = askCandidates(members, [], eye, { currentMemberId: 'sarah', helperIds: ['wei'] });
    assert.deepEqual(
      list.map((candidate) => candidate.member.name),
      ['Emily', 'John'],
    );
  });

  it('puts those free first, and says when each is free', () => {
    const availability = [
      window('john', '08:00', '12:00'),
      window('emily', '14:00', '17:00'),
      window('wei', '00:00', '23:59', 'unavailable'),
    ];
    const list = askCandidates(members, availability, eye, {
      currentMemberId: 'sarah',
      helperIds: [],
    });
    assert.deepEqual(
      list.map((candidate) => [candidate.member.name, candidate.status, candidate.note]),
      [
        ['John', 'available', 'Free: Morning'],
        ['Emily', 'unknown', 'Free that day: 2:00 pm to 5:00 pm'],
        ['Wei', 'unavailable', 'Said they can’t make it'],
      ],
    );
  });

  it('says so when someone shared nothing for the day', () => {
    const [only] = askCandidates([members[1]], [], eye, { currentMemberId: null, helperIds: [] });
    assert.equal(only.note, 'No free times shared for this day');
    assert.deepEqual(only.free, []);
  });
});

describe('notificationSentence', () => {
  it('words every kind from the reader’s side', () => {
    const cases: [Partial<NotificationItem>, string][] = [
      [{ kind: 'ask_received' }, 'Sarah asked you to go to Physio on Wed, 28 Oct'],
      [{ kind: 'ask_accepted' }, 'Emily said yes and is going to Physio on Wed, 28 Oct'],
      [{ kind: 'ask_declined' }, 'Emily can’t make Physio on Wed, 28 Oct'],
      [{ kind: 'ask_withdrawn' }, 'Sarah withdrew their ask for Physio on Wed, 28 Oct'],
      [
        { kind: 'ask_withdrawn', occurrence_id: null },
        'Physio on Wed, 28 Oct was changed or removed, so you’re no longer asked',
      ],
      [{ kind: 'ask_lapsed' }, 'Emily didn’t answer before Physio on Wed, 28 Oct started'],
      [
        { kind: 'ask_closed', ended_by_name: 'John' },
        'John is going to Physio on Wed, 28 Oct instead',
      ],
      [{ kind: 'ask_closed' }, 'Someone else is going to Physio on Wed, 28 Oct instead'],
    ];
    for (const [fields, expected] of cases) {
      assert.equal(notificationSentence(note(fields)), expected, String(fields.kind));
    }
  });

  it('links to the day while it exists', () => {
    assert.equal(notificationLink(note()), '/calendar?appointment=physio%402026-10-28');
    assert.equal(notificationLink(note({ occurrence_id: null })), null);
  });

  it('offers an answer only on an ask still open for the reader', () => {
    assert.equal(canAnswer(note()), true);
    assert.equal(canAnswer(note({ is_open_for_me: false })), false);
    assert.equal(canAnswer(note({ kind: 'ask_declined' })), false);
  });
});

describe('askOutcome', () => {
  it('says how an ask you received ended, once it is no longer open for you', () => {
    const ended = (fields: Partial<NotificationItem>) =>
      askOutcome(note({ is_open_for_me: false, ...fields }));
    assert.equal(ended({ ask_state: 'accepted' }), 'You said yes');
    assert.equal(ended({ ask_state: 'declined' }), 'You said you can’t go');
    assert.equal(ended({ ask_state: 'withdrawn' }), 'No longer needed');
    assert.equal(ended({ ask_state: 'lapsed' }), 'Ended without an answer');
    assert.equal(ended({ ask_state: 'closed', ended_by_name: 'John' }), 'John is going instead');
  });

  it('says nothing while it is open, or on other kinds', () => {
    assert.equal(askOutcome(note()), null);
    assert.equal(askOutcome(note({ kind: 'ask_declined', is_open_for_me: false })), null);
  });
});

describe('canStillAsk', () => {
  // 02:00 UTC is 10:00 in Singapore.
  const now = new Date('2026-10-28T02:00:00Z');
  it('allows a later day, or later today', () => {
    assert.equal(canStillAsk({ date: '2026-10-29', start: '08:00' }, now), true);
    assert.equal(canStillAsk({ date: '2026-10-28', start: '14:00' }, now), true);
  });
  it('stops once the start (Singapore time) has passed', () => {
    assert.equal(canStillAsk({ date: '2026-10-28', start: '09:30' }, now), false);
    assert.equal(canStillAsk({ date: '2026-10-28', start: '10:00' }, now), false);
    assert.equal(canStillAsk({ date: '2026-10-27', start: '23:00' }, now), false);
  });
});

describe('the unread count', () => {
  const page = (): NotificationPage => ({
    items: [
      note({ notification_id: 'n3' }),
      note({ notification_id: 'n2', read: true }),
      note({ notification_id: 'n1' }),
    ],
    unread_count: 5, // three more unread on older pages
    next_before: 'n1',
  });

  it('lists the unread ids on a page', () => {
    assert.deepEqual(unreadIds(page().items), ['n3', 'n1']);
  });

  it('drops only by the shown ones that were unread', () => {
    const read = markPageRead(page(), ['n3', 'n2', 'n1']);
    assert.equal(read.unread_count, 3);
    assert.ok(read.items.every((item) => item.read));
  });

  it('clears everything with all', () => {
    const read = markPageRead(page(), 'all');
    assert.equal(read.unread_count, 0);
    assert.ok(read.items.every((item) => item.read));
  });

  it('never goes below zero', () => {
    assert.equal(markPageRead({ ...page(), unread_count: 1 }, ['n3', 'n1']).unread_count, 0);
  });

  it('spots ids it has not seen', () => {
    assert.deepEqual(newNotificationIds(new Set(['n1', 'n2']), page().items), ['n3']);
    assert.deepEqual(newNotificationIds(new Set(['n1', 'n2', 'n3']), page().items), []);
  });

  it('merges an older page newest first, the newer copy winning', () => {
    const merged = mergeNotifications(
      [note({ notification_id: 'b', created_at: '2026-10-21T00:00:00Z' })],
      [
        note({ notification_id: 'a', created_at: '2026-10-19T00:00:00Z' }),
        note({ notification_id: 'b', created_at: '2026-10-21T00:00:00Z', read: true }),
      ],
    );
    assert.deepEqual(
      merged.map((item) => [item.notification_id, item.read]),
      [
        ['b', true],
        ['a', false],
      ],
    );
  });

  it('names the bell with its count', () => {
    assert.equal(bellLabel(0), 'Notifications');
    assert.equal(bellLabel(2), 'Notifications, 2 unread');
    assert.equal(badgeText(0), '');
    assert.equal(badgeText(3), '3');
    assert.equal(badgeText(12), '9+');
  });

  it('labels the unread badge on a group card, and has none at 0', () => {
    assert.equal(groupUnreadLabel(0), '');
    assert.equal(groupUnreadLabel(1), '1 unread');
    assert.equal(groupUnreadLabel(12), '12 unread');
  });
});

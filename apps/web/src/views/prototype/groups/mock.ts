/**
 * PROTOTYPE (issue #18), throwaway. In-memory fixtures for the groups page, the Switch group
 * control and the "Link {senior}'s account" card. Nothing here touches the API.
 */
export interface ProtoMember {
  name: string;
  relationship: string;
  colour: number;
}

export interface ProtoGroup {
  id: string;
  /** The senior's own account name once linked; `null` until they show their Senior-link PIN. */
  linkedName: string | null;
  /** The name the creator typed when making the group (shown until the senior is linked). */
  typedName: string;
  myStatus: 'active' | 'pending';
  myRole: 'owner' | 'member';
  joinPin: string;
  members: ProtoMember[];
  steps: number | null;
  usualSteps: number | null;
  watch: string | null;
  nextVisit: string | null;
}

export type ProtoState = 'one' | 'two' | 'pending' | 'nosenior';
export const STATES: { key: ProtoState; label: string }[] = [
  { key: 'one', label: 'One group' },
  { key: 'two', label: 'Two groups' },
  { key: 'pending', label: 'Pending group' },
  { key: 'nosenior', label: 'No senior yet' },
];

export type ProtoScreen = 'groups' | 'home';
export const SCREENS: { key: ProtoScreen; label: string }[] = [
  { key: 'groups', label: 'Groups page' },
  { key: 'home', label: 'Family Home' },
];

const tan: ProtoGroup = {
  id: 'g-tan',
  linkedName: 'Tan Ah Lian',
  typedName: 'Mum',
  myStatus: 'active',
  myRole: 'owner',
  joinPin: '482 913',
  members: [
    { name: 'Wei Ling', relationship: 'Daughter', colour: 0 },
    { name: 'Jun Hao', relationship: 'Son', colour: 2 },
    { name: 'Mei Xin', relationship: 'Granddaughter', colour: 4 },
  ],
  steps: 3120,
  usualSteps: 4200,
  watch: 'Worn 9 h today · synced 10 min ago',
  nextVisit: 'Thu 2:30 pm · Polyclinic review (Jun Hao going)',
};

const lim: ProtoGroup = {
  id: 'g-lim',
  linkedName: 'Lim Boon Kiat',
  typedName: 'Grandpa',
  myStatus: 'active',
  myRole: 'member',
  joinPin: '105 774',
  members: [
    { name: 'Wei Ling', relationship: 'Granddaughter', colour: 0 },
    { name: 'Siew Kim', relationship: 'Daughter', colour: 1 },
  ],
  steps: 5480,
  usualSteps: 5000,
  watch: 'Worn 11 h today · synced 2 min ago',
  nextVisit: 'Sat 10:00 am · AAC tai chi',
};

const limPending: ProtoGroup = { ...lim, myStatus: 'pending', members: [lim.members[1]] };

const noSenior: ProtoGroup = {
  id: 'g-new',
  linkedName: null,
  typedName: 'Ah Ma',
  myStatus: 'active',
  myRole: 'owner',
  joinPin: '660 218',
  members: [
    { name: 'Wei Ling', relationship: 'Granddaughter', colour: 0 },
    { name: 'Daniel', relationship: 'Grandson', colour: 3 },
  ],
  steps: null,
  usualSteps: null,
  watch: null,
  nextVisit: 'Mon 9:00 am · Dental check (nobody going yet)',
};

export const FIXTURES: Record<ProtoState, ProtoGroup[]> = {
  one: [tan],
  two: [tan, lim],
  pending: [tan, limPending],
  nosenior: [noSenior],
};

export function seniorName(group: ProtoGroup): string {
  return group.linkedName ?? group.typedName;
}

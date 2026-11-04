<script setup lang="ts">
/**
 * A small set of line icons drawn inline as SVG, so the app needs no icon library. An icon is always
 * decoration next to words that say the same thing (the proposal asks for no unexplained icons), so
 * every one is hidden from screen readers.
 *
 * Use: `<Icon name="phone" />`. It takes the colour of the text around it (`currentColor`) and is
 * 1.25em square, so it grows with the zoom. Each appointment kind has an icon with the same name
 * (`medical`, `therapy`, `activity`, `errand`, `task`), so `<Icon :name="appointment.kind" />` works.
 * Need one that is not here? Ask A, or add it in a tiny PR that only touches this file.
 */

// Drawings used under more than one name.
const PEOPLE =
  '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6.5 6.5-6.5s6.5 2.9 6.5 6.5"/><circle cx="17" cy="9" r="2.5"/><path d="M16.8 13.6c2.7.4 4.7 2.7 4.7 5.4"/>';
const STETHOSCOPE =
  '<path d="M5 3H4v6a5 5 0 0 0 10 0V3h-1"/><path d="M9 14v1.5a5 5 0 0 0 10 0V13"/><circle cx="19" cy="11" r="2"/>';
const HAND_HEART =
  '<path d="M12 10.5S9 8.6 9 6.6A1.8 1.8 0 0 1 12 5.5a1.8 1.8 0 0 1 3 1.1c0 2-3 3.9-3 3.9z"/><path d="M2.5 15.5 5.5 14a3 3 0 0 1 2.4-.1l3.6 1.4H14a1.6 1.6 0 0 1 0 3.2h-3.5M2.5 20.5l3-1.4 5 1.4 8-3.8a1.6 1.6 0 0 0-1.5-2.8l-2.3 1"/>';
const WALK =
  '<circle cx="13.5" cy="4.5" r="2"/><path d="M12.5 8.5 11 14.5l3.5 3 1 4M11 14.5l-2.5 3-2 3.5M12.5 8.5l3 3.5 3 .5M12.5 8.5 9 10l-1.5 3"/>';
const BAG =
  '<path d="M5 8h14l-1.2 12.1a1 1 0 0 1-1 .9H7.2a1 1 0 0 1-1-.9z"/><path d="M9 10V7a3 3 0 0 1 6 0v3"/>';
const CHECK_SQUARE =
  '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8.5 12.3l2.5 2.5 4.5-5"/>';

const ICONS = {
  home: '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
  person: '<circle cx="12" cy="7.5" r="4"/><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8"/>',
  calendar:
    '<rect x="3" y="4.5" width="18" height="16.5" rx="2.5"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4"/>',
  users: PEOPLE,
  people: PEOPLE,
  'user-plus':
    '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6.5 6.5-6.5 2.4 0 4.5 1.3 5.6 3.2M18 13.5v7M14.5 17h7"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  'check-circle': '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16.2 9.5"/>',
  'chevron-left': '<path d="M15 5l-7 7 7 7"/>',
  'chevron-right': '<path d="M9 5l7 7-7 7"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 2"/>',
  pin: '<path d="M12 21s7-6.2 7-11.5A7 7 0 0 0 5 9.5C5 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
  note: '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4M9 12h7M9 16h5"/>',
  share:
    '<circle cx="18" cy="5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="19" r="2.5"/><path d="M8.2 10.8l7.6-4.4M8.2 13.2l7.6 4.4"/>',
  'calendar-plus':
    '<rect x="3" y="4.5" width="18" height="16.5" rx="2.5"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4M12 12.5v5M9.5 15h5"/>',
  speaker:
    '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
  stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  'eye-off':
    '<path d="M3 3l18 18M10.6 6.1A10 10 0 0 1 12 6c6.4 0 10 6 10 6a17 17 0 0 1-3.3 4.1M6.6 6.6C3.9 8.4 2 12 2 12s3.6 7 10 7c1.7 0 3.2-.4 4.5-1.1M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
  umbrella: '<path d="M12 3a9 9 0 0 1 9 9H3a9 9 0 0 1 9-9z"/><path d="M12 12v6.5a2 2 0 0 1-4 0"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
  pointer: '<path d="M5.5 3.5v15.5l4.3-4.1 3.1 6.6 2.7-1.2-3.1-6.5h6.2z"/>',
  wind: '<path d="M3 8h11a3 3 0 1 0-3-3M3 12h16a3 3 0 1 1-3 3M3 16h7"/>',
  flag: '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>',
  pill: '<path d="M10.5 3.5a4.95 4.95 0 0 1 7 7l-7 7a4.95 4.95 0 0 1-7-7z"/><path d="M7 10l7 7"/>',
  sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
  shield: '<path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"/>',
  'shield-check':
    '<path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
  'sign-out': '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 16l-4-4 4-4M6 12h10"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.8v.2"/>',
  alert: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.3v.2"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>',

  // ---- The kinds of appointment, named to match `AppointmentKind` (plus `task`). ----
  medical: STETHOSCOPE,
  therapy: HAND_HEART,
  activity: WALK,
  errand: BAG,
  task: CHECK_SQUARE,

  // ---- People and contact ----
  'user-check':
    '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6.5 6.5-6.5 2.4 0 4.5 1.3 5.6 3.2M15 17.5l2 2 4-4.5"/>',
  'user-x':
    '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6.5 6.5-6.5 2.4 0 4.5 1.3 5.6 3.2M16 15l4.5 4.5M20.5 15 16 19.5"/>',
  phone:
    '<path d="M5.5 3.5h3l1.8 4.6-2.3 1.5a11 11 0 0 0 6.4 6.4l1.5-2.3 4.6 1.8v3a2 2 0 0 1-2.2 2A16.5 16.5 0 0 1 3.5 5.7a2 2 0 0 1 2-2.2z"/>',
  chat: '<path d="M4.5 4.5h15a1.5 1.5 0 0 1 1.5 1.5v9.5a1.5 1.5 0 0 1-1.5 1.5H11l-5 4v-4H4.5A1.5 1.5 0 0 1 3 15.5V6a1.5 1.5 0 0 1 1.5-1.5z"/><path d="M7.5 9.5h9M7.5 12.5h6"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3.5 6.5 12 13l8.5-6.5"/>',
  hand: '<path d="M8 13V6a1.5 1.5 0 0 1 3 0v5M11 10.5V4.5a1.5 1.5 0 0 1 3 0v6M14 11V6a1.5 1.5 0 0 1 3 0v8a7 7 0 0 1-7 7 6.2 6.2 0 0 1-4.8-2.3l-2.6-3.3a1.6 1.6 0 0 1 2.4-2.1L8 15"/>',
  'thumbs-up':
    '<path d="M7 11v9.5H3.5V11z"/><path d="M7 11l3.6-7a2 2 0 0 1 3.4 1.6l-.8 4.4h5.5a2 2 0 0 1 2 2.4l-1.3 6.5a2 2 0 0 1-2 1.6H7"/>',
  smile:
    '<circle cx="12" cy="12" r="9"/><path d="M8.5 14.5a4.5 4.5 0 0 0 7 0M9 9.5v.5M15 9.5v.5"/>',
  heart:
    '<path d="M12 20s-7.5-4.6-9-9.5C2 7 4.3 4.5 7.2 4.5c2 0 3.6 1.2 4.8 3 1.2-1.8 2.8-3 4.8-3C19.7 4.5 22 7 21 10.5 19.5 15.4 12 20 12 20z"/>',

  // ---- Health and the day (reminders people type in, never advice) ----
  medicine:
    '<rect x="6" y="2.5" width="12" height="4" rx="1"/><path d="M7 6.5h10V19a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2z"/><path d="M12 10.5v6M9 13.5h6"/>',
  stethoscope: STETHOSCOPE,
  walk: WALK,
  cloud: '<path d="M7 18.5h10.5a4 4 0 0 0 .4-8 5.5 5.5 0 0 0-10.6-1.4A4.6 4.6 0 0 0 7 18.5z"/>',
  map: '<path d="M9 4 3.5 6v14L9 18l6 2 5.5-2V4L15 6z"/><path d="M9 4v14M15 6v14"/>',
  layers:
    '<path d="M12 3 2.5 8 12 13l9.5-5z"/><path d="M2.5 12.5 12 17.5l9.5-5M2.5 16.5 12 21.5l9.5-5"/>',
  locate:
    '<circle cx="12" cy="12" r="6.5"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3.5M12 18.5V22M2 12h3.5M18.5 12H22"/>',
  compass:
    '<circle cx="12" cy="12" r="9"/><path d="m12 5 2.6 7H9.4z" fill="currentColor"/><path d="m12 19-2.6-7h5.2z"/>',
  play: '<path d="M7 4.5v15l12-7.5z"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
  water: '<path d="M12 3s6 6.4 6 11a6 6 0 0 1-12 0c0-4.6 6-11 6-11z"/>',
  meal: '<path d="M6 3v6.5a2.5 2.5 0 0 0 5 0V3M8.5 3v18M17.5 21V3c-2.2 0-3.5 2.6-3.5 6.5S15.3 14 17.5 14"/>',
  bag: BAG,
  car: '<path d="M4.5 16.5H3.5V12l2.2-5.1A1.5 1.5 0 0 1 7.1 6h9.8a1.5 1.5 0 0 1 1.4.9L20.5 12v4.5h-1M8.5 16.5h7M3.5 12h17"/><circle cx="7" cy="16.5" r="2"/><circle cx="17" cy="16.5" r="2"/>',
  watch:
    '<rect x="6.5" y="7" width="11" height="10" rx="2.5"/><path d="M9 7l.6-4h4.8l.6 4M9 17l.6 4h4.8l.6-4M12 9.8V12l1.6 1"/>',
  battery: '<rect x="2.5" y="7" width="17" height="10" rx="2"/><path d="M21.5 10.5v3M6 10.5v3"/>',
  timer:
    '<circle cx="12" cy="13.5" r="7.5"/><path d="M12 9.5v4l2.5 2M9.5 2.5h5M12 2.5V6M19 6.5l1.5-1.5"/>',
  bell: '<path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
  star: '<path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/>',
  'trend-up': '<path d="M3 17l6-6 4 4 8-8M15 7h6v6"/>',
  'trend-down': '<path d="M3 7l6 6 4-4 8 8M15 17h6v-6"/>',

  // ---- Actions ----
  plus: '<path d="M12 5v14M5 12h14"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7"/>',
  send: '<path d="M4 12 20 4l-4.5 16-3.5-6.5z"/><path d="M12 13.5 20 4"/>',
  minus: '<path d="M5 12h14"/>',
  edit: '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
  trash:
    '<path d="M4 7h16M9.5 7V4h5v3M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13M10 11v6M14 11v6"/>',
  copy: '<rect x="8.5" y="8.5" width="12" height="12" rx="2"/><path d="M15.5 8.5V5.5a2 2 0 0 0-2-2h-8a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h3"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M16.5 6.5l3 3M14 9l2 2"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7.5a4 4 0 0 1 8 0V11"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.3-4.3"/>',
  list: '<path d="M10 6h10M10 12h10M10 18h10M4.5 6h.5M4.5 12h.5M4.5 18h.5"/>',
  checklist:
    '<path d="M11 6h9M11 12h9M11 18h9"/><path d="M3.5 6l1.5 1.5L7.5 5M3.5 12l1.5 1.5 2.5-2.5M3.5 18l1.5 1.5 2.5-2.5"/>',
  sliders:
    '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  question:
    '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.4 2.3c-.6.3-.9.9-.9 1.6v.4M12 16.8v.2"/>',
  'arrow-up': '<path d="M12 19V5M6 11l6-6 6 6"/>',
  'arrow-down': '<path d="M12 5v14M6 13l6 6 6-6"/>',
  'arrow-right': '<path d="M5 12h14M13 6l6 6-6 6"/>',
  'chevron-up': '<path d="M5 15l7-7 7 7"/>',
  'chevron-down': '<path d="M5 9l7 7 7-7"/>',
} as const;

export type IconName = keyof typeof ICONS;

defineProps<{ name: IconName }>();
</script>

<template>
  <svg
    class="sl-icon"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
    v-html="ICONS[name]"
  ></svg>
</template>

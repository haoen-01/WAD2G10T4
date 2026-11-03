import { computed, reactive, ref, shallowRef, watch } from 'vue';

import { calendarAppointments } from '@/composables/useFamily';
import { currentGroup, loadMe } from '@/composables/useMe';
import { showToast } from '@/composables/useToast';
import { demoSub, DEMO_FAMILY_SUBS, useViewMode } from '@/composables/useViewMode';
import { AUTH_ENABLED } from '@/lib/config';
import { distanceM } from '@/lib/geo';
import {
  advanceSim,
  DEMO_ROUTE,
  KEEP_FIXES,
  parseGpx,
  routeFromTrack,
  startSim,
  type DemoRoute,
  type SimState,
} from '@/lib/demo-walk';
import {
  checkStillness,
  DEFAULT_STILLNESS,
  HOUR_MS,
  LIMIT_CHOICES_MIN,
  MINUTE_MS,
  type BusyWindow,
  type Stillness,
} from '@/lib/stillness';
import {
  clockTime,
  formatDuration,
  nearWords,
  summarise,
  walkState,
  type WalkFix,
  type WalkState,
} from '@/lib/walk';

/**
 * The senior's live walk, shared by every screen (a module singleton, like `useFamily`): the GPS
 * readings, what they mean, the senior's sharing choices, and the "Still for a while" check-in.
 *
 * The readings come from a simulated watch (`lib/demo-walk.ts`) running in this browser: there is
 * no API for live location yet, so nothing here is sent anywhere or stored on a server. A real
 * watch would send its readings to the API, which would run the same check (see UPDATES.md).
 *
 * The senior decides: the family sees the walk only while "Share my walk" is on, and the check-in
 * runs only while "Tell my family if I stay in one place" is on too. Both start off.
 */

// ---- The senior's choices and the family's settings, kept in this browser ----

const STORAGE_KEY = 'careplus.walk.v1';

interface WalkSettings {
  /** The senior: share my walk with my family. */
  shareWalk: boolean;
  /** The senior: tell my family if I stay in one place for a long time. */
  stillnessAlerts: boolean;
  /** The family: how long in one place, away from home, before they are told. */
  limitMin: number;
  /** The family: also show a notification from the browser on this device. */
  notify: boolean;
}

const DEFAULTS: WalkSettings = {
  shareWalk: false,
  stillnessAlerts: false,
  limitMin: DEFAULT_STILLNESS.limitMs / MINUTE_MS,
  notify: false,
};

function readSettings(): WalkSettings {
  try {
    const saved = JSON.parse(
      window.localStorage.getItem(STORAGE_KEY) ?? '{}',
    ) as Partial<WalkSettings>;
    return {
      shareWalk: saved.shareWalk === true,
      stillnessAlerts: saved.stillnessAlerts === true,
      limitMin: (LIMIT_CHOICES_MIN as readonly number[]).includes(Number(saved.limitMin))
        ? Number(saved.limitMin)
        : DEFAULTS.limitMin,
      notify: saved.notify === true,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

const settings = reactive<WalkSettings>(readSettings());
watch(settings, () => {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // Storage blocked: the choices last until the page reloads.
  }
});

// ---- The simulated watch ----

const route = shallowRef<DemoRoute>(DEMO_ROUTE);
const sim = shallowRef<SimState | null>(null);
const fixes = shallowRef<WalkFix[]>([]);
const playing = ref(false);
/** How much faster than real time the demo runs: 1×, 5× or 20×. */
const speed = ref(1);
const realNow = ref(Date.now());
let timer: number | null = null;

/** The time on the walk's clock: the simulated clock while the demo runs, else the real one. */
const now = computed(() => sim.value?.clock ?? realNow.value);

function addFixes(more: WalkFix[]) {
  if (!more.length) return;
  const next = fixes.value.concat(more);
  fixes.value = next.length > KEEP_FIXES ? next.slice(next.length - KEEP_FIXES) : next;
}

/**
 * Runs the watch forward, a minute at a time so the check-in sees every stage on the way (the
 * senior is asked before the family is told, even when the demo skips an hour). Readings are kept
 * only while she shares her walk: what she did not share is never recorded.
 */
function step(elapsedMs: number) {
  let left = elapsedMs;
  do {
    if (!sim.value) return;
    const chunk = Math.min(left, MINUTE_MS);
    const result = advanceSim(sim.value, route.value, chunk);
    sim.value = result.state;
    if (settings.shareWalk) addFixes(result.fixes);
    review();
    left -= chunk;
  } while (left > 0);
}

function startTimer() {
  if (timer !== null) return;
  timer = window.setInterval(() => {
    realNow.value = Date.now();
    if (playing.value) step(1000 * speed.value);
  }, 1000);
}

function startDemo(chosen: DemoRoute = DEMO_ROUTE) {
  route.value = chosen;
  sim.value = startSim(Date.now());
  fixes.value = [];
  forgetStops();
  playing.value = true;
  step(0);
  startTimer();
}

function resetDemo() {
  playing.value = false;
  sim.value = null;
  fixes.value = [];
  forgetStops();
  route.value = DEMO_ROUTE;
}

function setPlaying(on: boolean) {
  playing.value = on && sim.value !== null;
}

function setSpeed(next: number) {
  speed.value = next;
}

function setStayStill(on: boolean) {
  if (sim.value) sim.value = { ...sim.value, stayStill: on };
}

function setSignalLost(on: boolean) {
  if (sim.value) sim.value = { ...sim.value, signalLost: on };
  review();
}

/** Moves the demo's clock on, as if that much time had passed. */
function skipAhead(ms = HOUR_MS) {
  step(ms);
}

/**
 * Plays a recorded walk (a GPX file). The file is read in this browser and not uploaded; the
 * Streets and Quiet map looks do fetch map pictures of the area it covers from OpenFreeMap.
 */
function playRecording(text: string, fileName: string): string | null {
  try {
    startDemo(routeFromTrack(parseGpx(text), fileName.replace(/\.gpx$/i, '')));
    return null;
  } catch (caught) {
    return caught instanceof Error ? caught.message : 'That file could not be read.';
  }
}

// ---- What the readings mean ----

const seniorName = computed(() => currentGroup.value?.senior_name ?? 'Mdm Lim');
const sharing = computed(() => settings.shareWalk);
const latest = computed(() => fixes.value[fixes.value.length - 1] ?? null);
const state = computed<WalkState>(() => walkState(fixes.value, now.value, route.value.home));
const summary = computed(() => summarise(fixes.value, now.value));
const near = computed(() =>
  latest.value
    ? nearWords(latest.value, [route.value.home, ...route.value.landmarks], route.value.area)
    : null,
);
const demoActive = computed(() => sim.value !== null);
const demoState = computed(() => sim.value);

/** Today's calendar, as spans of time, so a long stay at an appointment does not alert. */
const busy = computed<BusyWindow[]>(() =>
  calendarAppointments.map((appointment) => ({
    title: appointment.title,
    startMs: new Date(`${appointment.date}T${appointment.start}`).getTime(),
    endMs: new Date(`${appointment.date}T${appointment.end}`).getTime(),
  })),
);

const okAt = ref<number | null>(null);
const dismissed = ref<{ lng: number; lat: number; at: number } | null>(null);
/** When she turned the check-in on (on the walk's clock), so earlier time is not counted. */
const consentAt = ref<number | null>(null);
/** When her page first asked "Are you OK?" about the current stop. */
const askedAt = ref<number | null>(null);

/** Forgets every stop, alert and answer: a new walk, a reset, or sharing turned off. */
function forgetStops() {
  closeNotification();
  alerts.splice(0, alerts.length);
  okAt.value = null;
  dismissed.value = null;
  askedAt.value = null;
  // A new walk has a new clock: consent given before it counts from its start.
  consentAt.value = null;
}

const stillness = computed<Stillness>(() => {
  if (!settings.shareWalk || !settings.stillnessAlerts) return { kind: 'none' };
  return checkStillness({
    fixes: fixes.value,
    now: now.value,
    home: route.value.home,
    usualPlaces: route.value.usualPlaces,
    busy: busy.value,
    settings: { ...DEFAULT_STILLNESS, limitMs: settings.limitMin * MINUTE_MS },
    okAt: okAt.value,
    consentAt: consentAt.value,
    askedAt: askedAt.value,
    dismissed: dismissed.value,
  });
});

// ---- The check-in alerts ----

export type AlertStatus = 'open' | 'checking' | 'ok' | 'fine' | 'moved' | 'stopped';

export interface WalkAlert {
  id: string;
  stopStart: number;
  since: number;
  raisedAt: number;
  place: string;
  lng: number;
  lat: number;
  status: AlertStatus;
  /** What the family was told, fixed when the alert was raised (read out once). */
  words: string;
  /** Who said "I'm checking in". */
  checkingBy: string | null;
  closedAt: number | null;
  closedBy: string | null;
}

const alerts = reactive<WalkAlert[]>([]);
const openAlert = computed(
  () => alerts.find((alert) => alert.status === 'open' || alert.status === 'checking') ?? null,
);

/** Whether an alert is about the place she is in now (GPS wobble moves a stop's edges a little). */
function samePlace(alert: WalkAlert, point: { lng: number; lat: number }): boolean {
  return (
    distanceM([alert.lng, alert.lat], [point.lng, point.lat]) <= DEFAULT_STILLNESS.stillRadiusM
  );
}

/**
 * Raises an alert when a stop reaches the limit, and closes one once she has moved on. An alert
 * belongs to a place: it stays open while she is there (lost signal included) and is raised once
 * per stop, or again after she says "I'm OK" and the limit passes a second time.
 */
function review() {
  const result = stillness.value;
  const current = openAlert.value;
  if (current && result.kind === 'still' && !samePlace(current, result)) {
    close(current, 'moved', null);
  }
  if (result.kind !== 'still') return;
  // Her page asks "Are you OK?" from now on; the family is told only after she has had time.
  if (result.phase === 'soon' && (askedAt.value === null || askedAt.value < result.since)) {
    askedAt.value = now.value;
  }
  if (result.phase !== 'alert') return;
  const already = alerts.some(
    (alert) =>
      samePlace(alert, result) && alert.raisedAt >= result.since && alert.status !== 'moved',
  );
  if (already) return;
  const id = `${result.stopStart}:${result.since}`;
  const place = nearWords(result, route.value.landmarks, route.value.area);
  const alert: WalkAlert = {
    id,
    stopStart: result.stopStart,
    since: result.since,
    raisedAt: now.value,
    place,
    lng: result.lng,
    lat: result.lat,
    status: 'open',
    words: '',
    checkingBy: null,
    closedAt: null,
    closedBy: null,
  };
  alert.words = alertWords(alert);
  alerts.unshift(alert);
  tell(alert);
}

function close(alert: WalkAlert, status: AlertStatus, by: string | null) {
  alert.status = status;
  alert.closedAt = now.value;
  alert.closedBy = by;
  closeNotification();
}

let shownNotification: Notification | null = null;

function closeNotification() {
  shownNotification?.close();
  shownNotification = null;
}

/**
 * The family is told: the banner (always), a toast, and a browser notification if allowed. Not on
 * the senior's own screen: in the demo both views share this browser.
 */
function tell(alert: WalkAlert) {
  if (useViewMode().mode.value === 'senior') return;
  const words = alert.words;
  showToast(words, { duration: 8000 });
  if (!settings.notify || typeof Notification === 'undefined') return;
  if (Notification.permission !== 'granted') return;
  try {
    const shown = new Notification(`Check in with ${seniorName.value}?`, {
      body: words,
      tag: 'careplus-still',
    });
    shownNotification = shown;
    shown.onclick = () => {
      window.focus();
      navigate?.('/walk');
    };
  } catch {
    // Some browsers only allow notifications from a service worker: the banner still shows.
  }
}

/** "Mdm Lim has been in one place for 2 h 05 min, near the big lawn (since 2:05 pm)." */
function alertWords(alert: WalkAlert): string {
  const forMs = Math.max(0, now.value - alert.since);
  return `${seniorName.value} has been in one place for ${formatDuration(forMs)}, near ${alert.place} (since ${clockTime(alert.since)}).`;
}

let navigate: ((path: string) => void) | null = null;

/** The layout registers the router here, so a notification click can open the Walk page. */
function setNavigator(go: (path: string) => void) {
  navigate = go;
}

/** The family member using this screen, for "Sarah is checking in". */
async function myName(): Promise<string> {
  if (!AUTH_ENABLED) {
    const sub = demoSub();
    return Object.keys(DEMO_FAMILY_SUBS).find((name) => DEMO_FAMILY_SUBS[name] === sub) ?? 'Sarah';
  }
  const me = await loadMe().catch(() => null);
  return me?.display_name ?? 'A family member';
}

/** The alert still waiting with this id, if it has not closed meanwhile. */
const stillOpen = (id: string) =>
  alerts.find((a) => a.id === id && (a.status === 'open' || a.status === 'checking')) ?? null;

async function checkingIn() {
  const id = openAlert.value?.id;
  if (!id) return;
  const name = await myName();
  const alert = stillOpen(id);
  if (!alert) return;
  alert.checkingBy = name;
  alert.status = 'checking';
}

async function shesFine() {
  const id = openAlert.value?.id;
  if (!id) return;
  const name = await myName();
  const alert = stillOpen(id);
  if (!alert) return;
  dismissed.value = { lng: alert.lng, lat: alert.lat, at: now.value };
  close(alert, 'fine', name);
}

/** The senior: "I'm OK". Restarts the clock for this stop and closes any alert about it. */
function imOk() {
  okAt.value = now.value;
  const alert = openAlert.value;
  if (alert) close(alert, 'ok', seniorName.value);
}

/** Turning sharing off also forgets what was shared: the trail, stops and alerts. */
function setShareWalk(on: boolean) {
  settings.shareWalk = on;
  if (!on) {
    settings.stillnessAlerts = false;
    fixes.value = [];
    forgetStops();
  }
}

function setStillnessAlerts(on: boolean) {
  settings.stillnessAlerts = on && settings.shareWalk;
  if (settings.stillnessAlerts) {
    consentAt.value = now.value;
    return;
  }
  const alert = openAlert.value;
  if (alert) close(alert, 'stopped', seniorName.value);
  askedAt.value = null;
}

function setLimit(minutes: number) {
  if ((LIMIT_CHOICES_MIN as readonly number[]).includes(minutes)) settings.limitMin = minutes;
  review();
}

/** Asks the browser for permission to show notifications. Returns whether they are on. */
async function enableNotifications(): Promise<boolean> {
  if (typeof Notification === 'undefined') return false;
  const answer =
    Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
  settings.notify = answer === 'granted';
  return settings.notify;
}

function disableNotifications() {
  settings.notify = false;
}

export function useWalk() {
  return {
    settings,
    route,
    fixes,
    playing,
    speed,
    now,
    seniorName,
    sharing,
    latest,
    state,
    summary,
    near,
    stillness,
    alerts,
    openAlert,
    demoActive,
    demoState,
    alertWords,
    startDemo,
    resetDemo,
    setPlaying,
    setSpeed,
    setStayStill,
    setSignalLost,
    skipAhead,
    playRecording,
    checkingIn,
    shesFine,
    imOk,
    setShareWalk,
    setStillnessAlerts,
    setLimit,
    enableNotifications,
    disableNotifications,
    setNavigator,
  };
}

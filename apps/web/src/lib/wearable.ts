/**
 * How the senior's watch is described on Home: the battery colour band, and the words that go with
 * it. Pure and import-free so `lib/wearable.test.ts` can run it under Node's type stripping.
 *
 * The bands follow what phones use: green when there is plenty left, amber when it is getting low,
 * red when it needs charging soon. The colour is never the only signal: every band has its words.
 */
export type BatteryLevel = 'good' | 'low' | 'critical' | 'charging';

/** At or above this the battery is fine (green). */
export const BATTERY_GOOD_PERCENT = 50;
/** Below this it needs charging soon (red), and the family is asked to remind the senior. */
export const BATTERY_CRITICAL_PERCENT = 20;

export function batteryLevel(percent: number, charging: boolean): BatteryLevel {
  if (charging) return 'charging';
  if (percent >= BATTERY_GOOD_PERCENT) return 'good';
  if (percent >= BATTERY_CRITICAL_PERCENT) return 'low';
  return 'critical';
}

/** The battery in words: "72%, charging", "35%, getting low". */
export function describeBattery(percent: number, charging: boolean): string {
  const level = batteryLevel(percent, charging);
  if (level === 'charging') return `${percent}%, charging`;
  if (level === 'good') return `${percent}%`;
  if (level === 'low') return `${percent}%, getting low`;
  return `${percent}%, needs charging`;
}

/** "synced just now", "synced 12 min ago", "synced 3 h ago". */
export function syncedAgo(lastSyncedAt: string, now: Date): string {
  const minutes = Math.max(0, Math.floor((now.getTime() - Date.parse(lastSyncedAt)) / 60_000));
  if (minutes < 1) return 'synced just now';
  if (minutes < 60) return `synced ${minutes} min ago`;
  return `synced ${Math.floor(minutes / 60)} h ago`;
}

/**
 * Small map maths for the live walk: distances, directions and points along a path, in metres on
 * the Earth's surface. Points are `[longitude, latitude]`, the order GeoJSON and MapLibre use.
 * Pure and import-free so `lib/geo.test.ts` can run it under Node's type stripping.
 */
export type LngLat = [number, number];

const EARTH_RADIUS_M = 6_371_008.8;
const rad = (degrees: number) => (degrees * Math.PI) / 180;
const deg = (radians: number) => (radians * 180) / Math.PI;

/** Great-circle distance between two points, in metres. */
export function distanceM(a: LngLat, b: LngLat): number {
  const dLat = rad(b[1] - a[1]);
  const dLng = rad(b[0] - a[0]);
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(rad(a[1])) * Math.cos(rad(b[1])) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** The compass direction from `a` to `b`: 0 is north, 90 east, 0 to 360. */
export function bearingDeg(a: LngLat, b: LngLat): number {
  const y = Math.sin(rad(b[0] - a[0])) * Math.cos(rad(b[1]));
  const x =
    Math.cos(rad(a[1])) * Math.sin(rad(b[1])) -
    Math.sin(rad(a[1])) * Math.cos(rad(b[1])) * Math.cos(rad(b[0] - a[0]));
  return (deg(Math.atan2(y, x)) + 360) % 360;
}

/** The length of a path, in metres. */
export function pathLengthM(points: readonly LngLat[]): number {
  let total = 0;
  for (let i = 1; i < points.length; i += 1) total += distanceM(points[i - 1], points[i]);
  return total;
}

/**
 * The point `metres` along a path, and the direction of travel there. Before the start it is the
 * start; past the end it is the end.
 */
export function pointAlong(
  points: readonly LngLat[],
  metres: number,
): { point: LngLat; bearing: number } {
  if (points.length === 0) throw new Error('pointAlong needs at least one point');
  if (points.length === 1) return { point: points[0], bearing: 0 };
  let left = Math.max(0, metres);
  for (let i = 1; i < points.length; i += 1) {
    const a = points[i - 1];
    const b = points[i];
    const length = distanceM(a, b);
    if (left <= length || i === points.length - 1) {
      const t = length === 0 ? 0 : Math.min(1, left / length);
      return {
        point: [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t],
        bearing: bearingDeg(a, b),
      };
    }
    left -= length;
  }
  return { point: points[points.length - 1], bearing: 0 };
}

/** A point moved `eastM` metres east and `northM` metres north (fine for the few metres of GPS noise). */
export function offsetM(point: LngLat, eastM: number, northM: number): LngLat {
  const dLat = deg(northM / EARTH_RADIUS_M);
  const dLng = deg(eastM / (EARTH_RADIUS_M * Math.cos(rad(point[1]))));
  return [point[0] + dLng, point[1] + dLat];
}

/** A closed ring of points `radiusM` around `centre`: the GPS accuracy circle on the map. */
export function circleRing(centre: LngLat, radiusM: number, steps = 40): LngLat[] {
  const ring: LngLat[] = [];
  for (let i = 0; i <= steps; i += 1) {
    const angle = (i / steps) * 2 * Math.PI;
    ring.push(offsetM(centre, Math.sin(angle) * radiusM, Math.cos(angle) * radiusM));
  }
  return ring;
}
